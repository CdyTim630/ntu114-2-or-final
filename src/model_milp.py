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
    gamma: float = 2.0           # history penalty (same ITEM seen recently)
    gamma_cat: float = 8.0       # diversity penalty (same CATEGORY seen recently)
    lam_pro: float = 6.0
    lam_fat_lo: float = 2.0
    lam_fat_hi: float = 3.0
    lam_carb_lo: float = 1.0
    lam_carb_hi: float = 1.5
    lam_sug: float = 4.0
    lam_sod: float = 0.15            # raised so the optimiser actively avoids salt


# Sodium is convenience food's worst offender (it was over target ~70% of the
# time). Keep it soft so feasibility is preserved, but cap the worst case with a
# hard ceiling at this multiple of the per-meal sodium target.
SOD_HARD_MULT = 1.5


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


# ---------------------------------------------------------------------------
# Tiered recency penalty (MLFQ-style, like an OS multi-level feedback queue).
#
# The recommendation history is an ordered list of distinct items, most-recent
# first. Each item sits in a TIER decided by its recency rank: the most-recent
# items are in the top tier (strongly avoided), and items age DOWN into lower
# tiers with a smaller penalty as newer meals push them back. The bottom band
# carries weight ~0, so an item effectively "leaves memory" once it ages past
# the last band (and we drop it from storage at HISTORY_MAX). Re-recommending an
# item moves it back to rank 1 -> top tier (promotion). Within a tier, items
# stay ordered by recency.
HISTORY_TIER_BOUNDS  = [3, 8, 16, 30]              # rank upper-bound of tiers 0..3
HISTORY_TIER_WEIGHTS = [5.0, 2.5, 1.0, 0.3, 0.0]   # penalty weight per tier (last=0)
HISTORY_MAX = HISTORY_TIER_BOUNDS[-1]              # keep this many distinct items
HISTORY_TIER_LABELS = ["剛吃過", "前幾餐", "久未推", "更久以前"]


def history_tier(rank: int) -> int:
    """0-indexed tier for a 1-indexed recency rank (rank 1 = most recent)."""
    for t, ub in enumerate(HISTORY_TIER_BOUNDS):
        if rank <= ub:
            return t
    return len(HISTORY_TIER_BOUNDS)


def aged_weight(rank: int) -> float:
    """Tiered penalty weight for an item at the given recency rank."""
    return HISTORY_TIER_WEIGHTS[history_tier(rank)]


def history_penalty(instance: Instance, L: int = HISTORY_MAX) -> Dict[int, float]:
    """h_i = tiered recency weight of item i (0 if it is not in recent history)."""
    h: Dict[int, float] = {p.pid: 0.0 for p in instance.products}
    for r, pid in enumerate(instance.history[:L], start=1):
        if pid in h:
            h[pid] += aged_weight(r)
    return h


def category_penalty(instance: Instance, L: int = HISTORY_MAX) -> Dict[int, float]:
    """g_i = tiered recency weight accumulated over item i's whole CATEGORY.
    Penalising the whole category (not just the exact item) stops the optimiser
    from swapping one 豆漿 variant for another and calling it 'diverse' — after a
    乳製品 is recommended, every 乳製品 is discouraged next time, forcing a
    genuinely different food type."""
    pmap = {p.pid: p for p in instance.products}
    cat_weight: Dict[str, float] = {}
    for r, pid in enumerate(instance.history[:L], start=1):
        p = pmap.get(pid)
        if p and p.category:
            cat_weight[p.category] = cat_weight.get(p.category, 0.0) + aged_weight(r)
    return {p.pid: cat_weight.get(p.category, 0.0) for p in instance.products}


def combined_penalty(instance: Instance, w: "Weights", L: int = HISTORY_MAX) -> Dict[int, float]:
    """Per-item penalty folding BOTH the item-level history penalty and the
    category-level diversity penalty into one dict, so the existing objective
    term ``w.gamma * sum(h_i x_i)`` carries both. The fold is exact: the effective
    category coefficient works out to ``gamma_cat`` (independent of ``gamma``)::

        w.gamma * (h_item + (gamma_cat/gamma) * g_cat) = gamma*h_item + gamma_cat*g_cat

    If ``gamma`` is 0 the history term vanishes entirely (diversity disabled)."""
    h = history_penalty(instance, L)
    if not w.gamma:
        return h
    g = category_penalty(instance, L)
    ratio = w.gamma_cat / w.gamma
    return {pid: h.get(pid, 0.0) + ratio * g.get(pid, 0.0) for pid in h}


def solve_milp(instance: Instance, meal: MealTarget, w: Weights,
               budget: Optional[float] = None,
               time_limit: float = 60.0, mip_gap: float = 1e-4,
               verbose: bool = False,
               pool_eps: Optional[float] = None, pool_max: int = 600):
    """Solve the meal-recommendation MILP.

    Normally returns the single optimal ``Solution`` (or None if infeasible).
    If ``pool_eps`` is set, instead enumerates the epsilon-optimal SET via
    Gurobi's solution pool and returns a list of distinct meals
    ``[(frozenset_of_item_ids, cost, obj), ...]`` whose objective is within
    ``pool_eps`` of the optimum — used to measure the price of diversity."""
    P = instance.products
    K = instance.combos
    pid2idx = {p.pid: i for i, p in enumerate(P)}
    h = combined_penalty(instance, w)

    m = gp.Model("conv_meal")
    if not verbose:
        m.Params.OutputFlag = 0
    m.Params.TimeLimit = time_limit
    m.Params.MIPGap = mip_gap
    if pool_eps is not None:
        m.Params.PoolSearchMode = 2          # find the n best solutions
        m.Params.PoolSolutions = pool_max
        m.Params.PoolGapAbs = pool_eps       # keep solutions within eps of opt

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
    # (8) sodium upper (soft) + hard ceiling so a meal can't be egregiously salty
    m.addConstr(sod_total - sSod <= meal.sodium_max, name="sodium_hi")
    m.addConstr(sod_total <= meal.sodium_max * SOD_HARD_MULT, name="sodium_ceiling")
    # (9) count upper (hard)
    m.addConstr(count_total <= meal.n_max, name="count")
    # at least 1 item
    m.addConstr(count_total >= 1, name="count_lo")

    # ---- meal-structure constraints (realistic basket shape) ----
    # At most one drink and one dessert/snack in any meal, so the optimiser can't
    # build a "meal" out of three snacks or two drinks.
    drinks   = [i for i, p in enumerate(P) if p.role == "drink"]
    desserts = [i for i, p in enumerate(P) if p.role == "dessert"]
    if drinks:
        m.addConstr(gp.quicksum(x_expr(i) for i in drinks) <= 1, name="max_one_drink")
    if desserts:
        m.addConstr(gp.quicksum(x_expr(i) for i in desserts) <= 1, name="max_one_dessert")
    # (10) regular mode -> exactly one staple main (no "two breads" meals)
    # (11) regular mode -> at least 1 protein source
    if meal.n_max >= 4:  # treat regular if cap is large
        mains = [i for i, p in enumerate(P) if p.is_main]
        proteins = [i for i, p in enumerate(P) if p.is_protein]
        if mains:
            m.addConstr(gp.quicksum(x_expr(i) for i in mains) == 1, name="exactly_one_main")
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

    if pool_eps is not None:
        # enumerate the epsilon-optimal set: distinct meals (item-set) keyed to
        # avoid double-counting symmetric single/combo encodings of the same meal
        pool: Dict[frozenset, Tuple[float, float]] = {}
        for s in range(m.SolCount):
            m.Params.SolutionNumber = s
            ids = {P[i].pid for i in range(len(P)) if a[i].Xn > 0.5}
            cost = sum(P[i].price for i in range(len(P)) if a[i].Xn > 0.5)
            for k in range(len(K)):
                if y[k].Xn > 0.5:
                    ids.update(K[k].item_ids)
                    cost += K[k].promo_price
            key = frozenset(ids)
            if key not in pool or m.PoolObjVal < pool[key][1]:
                pool[key] = (cost, m.PoolObjVal)
        return [(k, v[0], v[1]) for k, v in pool.items()]

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
