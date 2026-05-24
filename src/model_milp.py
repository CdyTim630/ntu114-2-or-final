"""Exact MILP formulation solved by Gurobi (benchmark for the proposed heuristic).

Implements the model in Section 4 of the proposal — variables a_i, y_k, x_i,
soft-constraint slacks s_*, and the weighted objective with cost / protein /
history-penalty / soft-violation terms.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import gurobipy as gp
from gurobipy import GRB

from data_loader import Instance
from preprocessing import MealTarget


@dataclass
class Weights:
    alpha: float = 1.0           # cost
    beta: float = 0.5            # protein bonus
    gamma: float = 2.0           # history penalty
    lam_pro: float = 6.0
    lam_fat_lo: float = 2.0
    lam_fat_hi: float = 3.0
    lam_carb_lo: float = 1.0
    lam_carb_hi: float = 1.5
    lam_sug: float = 4.0
    lam_sod: float = 0.05


@dataclass
class Solution:
    obj: float
    runtime: float
    cost: float
    nutri: Dict[str, float]
    items_alone: List[int]
    combos_picked: List[int]
    items_total: List[int]            # all product ids that appear (single or via combo)
    slacks: Dict[str, float]
    feasible_hard: bool                # hard constraints satisfied (calorie band, count, etc.)
    gap: float = 0.0


def history_penalty(instance: Instance, L: int = 5) -> Dict[int, float]:
    """h_i = sum over the last L records of (L - r + 1) if item i was used in the r-th most recent record."""
    h: Dict[int, float] = {p.pid: 0.0 for p in instance.products}
    recent = instance.history[:L]
    for r, pid in enumerate(recent, start=1):
        if pid in h:
            h[pid] += float(L - r + 1)
    return h


def solve_milp(instance: Instance, meal: MealTarget, w: Weights,
               budget: Optional[float] = None,
               time_limit: float = 60.0, mip_gap: float = 1e-4,
               verbose: bool = False) -> Optional[Solution]:
    P = instance.products
    K = instance.combos
    pid2idx = {p.pid: i for i, p in enumerate(P)}
    h = history_penalty(instance)

    m = gp.Model("conv_meal")
    if not verbose:
        m.Params.OutputFlag = 0
    m.Params.TimeLimit = time_limit
    m.Params.MIPGap = mip_gap

    a = m.addVars(len(P), vtype=GRB.BINARY, name="a")
    y = m.addVars(len(K), vtype=GRB.BINARY, name="y")

    # x_i = a_i + sum_{k: i in S_k} y_k
    def x_expr(i: int):
        item_id = P[i].pid
        expr = a[i]
        for k_idx, c in enumerate(K):
            if item_id in c.item_ids:
                expr = expr + y[k_idx]
        return expr

    # (1) mutual exclusion: x_i <= 1
    for i in range(len(P)):
        m.addConstr(x_expr(i) <= 1, name=f"excl_{i}")

    # slacks
    sP    = m.addVar(lb=0, name="s_pro")
    sFatL = m.addVar(lb=0, name="s_fat_lo")
    sFatH = m.addVar(lb=0, name="s_fat_hi")
    sCarL = m.addVar(lb=0, name="s_carb_lo")
    sCarH = m.addVar(lb=0, name="s_carb_hi")
    sSug  = m.addVar(lb=0, name="s_sug")
    sSod  = m.addVar(lb=0, name="s_sod")

    # totals via x_i
    cost_total = (gp.quicksum(P[i].price * a[i] for i in range(len(P)))
                  + gp.quicksum(K[k].promo_price * y[k] for k in range(len(K))))
    cal_total  = gp.quicksum(P[i].cal  * x_expr(i) for i in range(len(P)))
    pro_total  = gp.quicksum(P[i].pro  * x_expr(i) for i in range(len(P)))
    fat_total  = gp.quicksum(P[i].fat  * x_expr(i) for i in range(len(P)))
    carb_total = gp.quicksum(P[i].carb * x_expr(i) for i in range(len(P)))
    sug_total  = gp.quicksum(P[i].sug  * x_expr(i) for i in range(len(P)))
    sod_total  = gp.quicksum(P[i].sod  * x_expr(i) for i in range(len(P)))
    count_total = gp.quicksum(x_expr(i) for i in range(len(P)))
    history_total = gp.quicksum(h[P[i].pid] * x_expr(i) for i in range(len(P)))

    # (2) budget
    if budget is not None:
        m.addConstr(cost_total <= budget, name="budget")

    # (3) protein lower-bound (soft)
    m.addConstr(pro_total + sP >= meal.protein_min, name="protein_lo")
    # (4) calorie band (hard)
    m.addConstr(cal_total >= meal.cal_min, name="cal_lo")
    m.addConstr(cal_total <= meal.cal_max, name="cal_hi")
    # (5) fat band (soft)
    m.addConstr(fat_total + sFatL >= meal.fat_min, name="fat_lo")
    m.addConstr(fat_total - sFatH <= meal.fat_max, name="fat_hi")
    # (6) carb band (soft)
    m.addConstr(carb_total + sCarL >= meal.carb_min, name="carb_lo")
    m.addConstr(carb_total - sCarH <= meal.carb_max, name="carb_hi")
    # (7) sugar upper (soft)
    m.addConstr(sug_total - sSug <= meal.sugar_max, name="sugar_hi")
    # (8) sodium upper (soft)
    m.addConstr(sod_total - sSod <= meal.sodium_max, name="sodium_hi")
    # (9) count upper (hard)
    m.addConstr(count_total <= meal.n_max, name="count")
    # at least 1 item
    m.addConstr(count_total >= 1, name="count_lo")

    # (10) regular mode -> at least 1 main
    # (11) regular mode -> at least 1 protein source
    if meal.n_max >= 4:  # treat regular if cap is large
        mains = [i for i, p in enumerate(P) if p.is_main]
        proteins = [i for i, p in enumerate(P) if p.is_protein]
        if mains:
            m.addConstr(gp.quicksum(x_expr(i) for i in mains) >= 1, name="has_main")
        if proteins:
            m.addConstr(gp.quicksum(x_expr(i) for i in proteins) >= 1, name="has_protein")

    # objective
    obj = (w.alpha * cost_total
           - w.beta * pro_total
           + w.gamma * history_total
           + w.lam_pro * sP
           + w.lam_fat_lo * sFatL + w.lam_fat_hi * sFatH
           + w.lam_carb_lo * sCarL + w.lam_carb_hi * sCarH
           + w.lam_sug * sSug + w.lam_sod * sSod)
    m.setObjective(obj, GRB.MINIMIZE)

    m.optimize()

    if m.SolCount == 0:
        return None

    items_alone = [P[i].pid for i in range(len(P)) if a[i].X > 0.5]
    combos_picked = [K[k].cid for k in range(len(K)) if y[k].X > 0.5]
    items_total_set = set(items_alone)
    for k in range(len(K)):
        if y[k].X > 0.5:
            items_total_set.update(K[k].item_ids)
    items_total = sorted(items_total_set)

    return Solution(
        obj=m.ObjVal,
        runtime=m.Runtime,
        cost=cost_total.getValue(),
        nutri={
            "cal":  cal_total.getValue(),
            "pro":  pro_total.getValue(),
            "fat":  fat_total.getValue(),
            "carb": carb_total.getValue(),
            "sug":  sug_total.getValue(),
            "sod":  sod_total.getValue(),
            "n":    count_total.getValue(),
        },
        items_alone=items_alone,
        combos_picked=combos_picked,
        items_total=items_total,
        slacks={"pro": sP.X, "fat_lo": sFatL.X, "fat_hi": sFatH.X,
                "carb_lo": sCarL.X, "carb_hi": sCarH.X,
                "sug": sSug.X, "sod": sSod.X},
        feasible_hard=True,
        gap=m.MIPGap if m.IsMIP else 0.0,
    )
