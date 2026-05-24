"""Self-proposed heuristic: GRASP-LS (Greedy Randomized Adaptive Search Procedure
+ Local Search) for the convenience-store meal-recommendation MILP.

Why GRASP-LS:
  * The MILP has a few hundred binary variables and dense non-linear coupling
    via slack penalties; pure greedy is brittle, pure random is wasteful.
  * GRASP balances diversification (random RCL) with intensification (LS swaps),
    and the restart loop covers different combo activation patterns.
  * Combos are treated as "super-items" so the heuristic decides combo vs single
    in the same scoring step (avoids the "should I take this combo" subproblem).

Three phases:
  1. Greedy Randomized Construction  — repeatedly pick from a Restricted
     Candidate List built from a composite priority score.
  2. Local Search (1-1 swap / 0-1 add / 1-0 drop)  — first-improvement.
  3. Multi-start: K independent restarts, keep best.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import random
import time

from data_loader import Instance, Product, Combo
from preprocessing import MealTarget
from model_milp import Weights, Solution, history_penalty


@dataclass
class _State:
    """Mutable state used while building / improving a solution."""
    items_alone: List[int] = field(default_factory=list)   # product ids picked as singles
    combos_picked: List[int] = field(default_factory=list)  # combo ids picked

    def covered_items(self, instance: Instance) -> set:
        s = set(self.items_alone)
        cmap = {c.cid: c for c in instance.combos}
        for cid in self.combos_picked:
            s.update(cmap[cid].item_ids)
        return s


def _agg(state: _State, instance: Instance) -> Dict[str, float]:
    pmap = {p.pid: p for p in instance.products}
    cmap = {c.cid: c for c in instance.combos}
    items = state.covered_items(instance)
    cost = sum(pmap[pid].price for pid in state.items_alone) \
         + sum(cmap[cid].promo_price for cid in state.combos_picked)
    agg = {"cost": cost, "cal": 0.0, "pro": 0.0, "fat": 0.0,
           "carb": 0.0, "sug": 0.0, "sod": 0.0, "n": len(items)}
    for pid in items:
        p = pmap[pid]
        agg["cal"]  += p.cal
        agg["pro"]  += p.pro
        agg["fat"]  += p.fat
        agg["carb"] += p.carb
        agg["sug"]  += p.sug
        agg["sod"]  += p.sod
    return agg


def _objective(state: _State, instance: Instance, meal: MealTarget,
               w: Weights, h: Dict[int, float],
               budget: Optional[float]) -> Tuple[float, bool, Dict[str, float]]:
    """Return (objective_value, hard_feasible?, aggregates).
    Hard constraints: calorie band, item count, budget, exclusivity, regular-mode mains/protein.
    Soft constraints: appear as penalty terms in the objective.
    """
    pmap = {p.pid: p for p in instance.products}
    items = state.covered_items(instance)

    # exclusivity: any item must appear at most once (combo overlap with single = infeasible)
    # since we only pick combos that are mutually disjoint from chosen singles, enforce here.
    # Build a multi-count to detect violation:
    multi: Dict[int, int] = {}
    for pid in state.items_alone:
        multi[pid] = multi.get(pid, 0) + 1
    cmap = {c.cid: c for c in instance.combos}
    for cid in state.combos_picked:
        for pid in cmap[cid].item_ids:
            multi[pid] = multi.get(pid, 0) + 1
    if any(v > 1 for v in multi.values()):
        return float("inf"), False, {}

    agg = _agg(state, instance)
    # hard: count cap
    if agg["n"] > meal.n_max or agg["n"] < 1:
        return float("inf"), False, agg
    # hard: calorie band
    if agg["cal"] > meal.cal_max or agg["cal"] < meal.cal_min:
        return float("inf"), False, agg
    # hard: budget
    if budget is not None and agg["cost"] > budget + 1e-6:
        return float("inf"), False, agg
    # hard: regular mode requires main + protein
    if meal.n_max >= 4:
        has_main = any(pmap[pid].is_main for pid in items)
        has_pro  = any(pmap[pid].is_protein for pid in items)
        if not (has_main and has_pro):
            return float("inf"), False, agg

    # soft penalties
    sP    = max(0.0, meal.protein_min - agg["pro"])
    sFatL = max(0.0, meal.fat_min  - agg["fat"])
    sFatH = max(0.0, agg["fat"]    - meal.fat_max)
    sCarL = max(0.0, meal.carb_min - agg["carb"])
    sCarH = max(0.0, agg["carb"]   - meal.carb_max)
    sSug  = max(0.0, agg["sug"]    - meal.sugar_max)
    sSod  = max(0.0, agg["sod"]    - meal.sodium_max)

    hist_total = sum(h.get(pid, 0.0) for pid in items)
    obj = (w.alpha * agg["cost"]
           - w.beta  * agg["pro"]
           + w.gamma * hist_total
           + w.lam_pro * sP
           + w.lam_fat_lo * sFatL + w.lam_fat_hi * sFatH
           + w.lam_carb_lo * sCarL + w.lam_carb_hi * sCarH
           + w.lam_sug * sSug + w.lam_sod * sSod)
    return obj, True, agg


def _priority_score(p: Product, w: Weights, h: Dict[int, float],
                    meal: MealTarget) -> float:
    """Composite static score used to build the RCL.
    Items with high protein-per-cost, that fit nutrition limits well, and
    have low recent-usage penalty rank higher.
    """
    cal_norm  = p.cal / max(meal.cal_max, 1.0)
    sod_norm  = p.sod / max(meal.sodium_max, 1.0)
    sug_norm  = p.sug / max(meal.sugar_max, 1.0)
    bonus = 0.0
    if p.is_main:    bonus += 1.2
    if p.is_protein: bonus += 1.5
    return (w.beta * p.pro
            - w.alpha * p.price * 0.06
            - w.gamma * h.get(p.pid, 0.0)
            - 0.6 * cal_norm
            - w.lam_sod * sod_norm
            - w.lam_sug * sug_norm
            + bonus)


def _combo_score(c: Combo, instance: Instance, w: Weights, h: Dict[int, float],
                 meal: MealTarget) -> float:
    pmap = {p.pid: p for p in instance.products}
    discount = c.original_price - c.promo_price
    base = sum(_priority_score(pmap[i], w, h, meal) for i in c.item_ids)
    return base + 0.25 * discount    # extra reward for the combo discount


# ---------------------------------------------------------------------------
# Phase 1: Greedy Randomized Construction
# ---------------------------------------------------------------------------
def _construct(instance: Instance, meal: MealTarget, w: Weights,
               h: Dict[int, float], budget: Optional[float],
               rcl_alpha: float, rng: random.Random) -> _State:
    state = _State()
    pmap = {p.pid: p for p in instance.products}

    # Pre-compute priorities once.
    item_pri  = [(p, _priority_score(p, w, h, meal)) for p in instance.products]
    combo_pri = [(c, _combo_score(c, instance, w, h, meal)) for c in instance.combos]

    # Round 1: take one combo with probability proportional to combo discount.
    # Helps the heuristic discover the discount structure that pure greedy misses.
    if combo_pri and rng.random() < 0.6:
        combo_pri_sorted = sorted(combo_pri, key=lambda x: x[1], reverse=True)
        cmax = combo_pri_sorted[0][1]
        cmin = combo_pri_sorted[-1][1]
        thr = cmax - rcl_alpha * (cmax - cmin) if cmax != cmin else cmin
        rcl = [c for c, sc in combo_pri_sorted if sc >= thr]
        if rcl:
            chosen = rng.choice(rcl)
            trial = _State(combos_picked=[chosen.cid])
            _, feas, _ = _objective(trial, instance, meal, w, h, budget)
            if feas or len(chosen.item_ids) <= meal.n_max:
                state.combos_picked.append(chosen.cid)

    # Then add single items one by one, respecting all hard constraints.
    while True:
        agg = _agg(state, instance)
        if agg["n"] >= meal.n_max:
            break
        # candidates: not already covered, and adding does not break budget / cal cap
        covered = state.covered_items(instance)
        cand = []
        for p, sc in item_pri:
            if p.pid in covered:
                continue
            new_cost = agg["cost"] + p.price
            if budget is not None and new_cost > budget:
                continue
            if agg["cal"] + p.cal > meal.cal_max:
                continue
            cand.append((p, sc))
        if not cand:
            break

        # Greedy stopping: if we already meet cal_min, only continue while
        # objective looks like it would still improve.
        agg_cur = _agg(state, instance)
        if agg_cur["cal"] >= meal.cal_min and agg_cur["n"] >= 2:
            obj_cur, feas_cur, _ = _objective(state, instance, meal, w, h, budget)
            # try the best candidate; only add if it improves the objective
            cand_sorted = sorted(cand, key=lambda x: x[1], reverse=True)
            improved = False
            for p, _sc in cand_sorted[:3]:
                trial = _State(items_alone=state.items_alone + [p.pid],
                               combos_picked=list(state.combos_picked))
                obj_new, feas_new, _ = _objective(trial, instance, meal, w, h, budget)
                if (not feas_cur and feas_new) or (feas_cur and feas_new and obj_new < obj_cur - 1e-6):
                    state = trial
                    improved = True
                    break
            if not improved:
                break
        else:
            # still need to reach cal_min: pick from RCL
            cand_sorted = sorted(cand, key=lambda x: x[1], reverse=True)
            smax = cand_sorted[0][1]
            smin = cand_sorted[-1][1]
            thr = smax - rcl_alpha * (smax - smin) if smax != smin else smin
            rcl = [p for p, sc in cand_sorted if sc >= thr]
            chosen = rng.choice(rcl)
            state.items_alone.append(chosen.pid)

    return state


# ---------------------------------------------------------------------------
# Phase 2: Local Search (1-1 swap, 0-1 add, 1-0 drop, 1-combo swap)
# ---------------------------------------------------------------------------
def _local_search(state: _State, instance: Instance, meal: MealTarget,
                  w: Weights, h: Dict[int, float], budget: Optional[float],
                  max_iter: int = 200) -> _State:
    best_obj, best_feas, _ = _objective(state, instance, meal, w, h, budget)
    pmap = {p.pid: p for p in instance.products}
    cmap = {c.cid: c for c in instance.combos}

    for _ in range(max_iter):
        improved = False
        covered = state.covered_items(instance)

        # 1-1 swap: replace one single item with another not in solution
        for old_pid in list(state.items_alone):
            # try each replacement
            for new_p in instance.products:
                if new_p.pid in covered:
                    continue
                trial = _State(
                    items_alone=[p for p in state.items_alone if p != old_pid] + [new_p.pid],
                    combos_picked=list(state.combos_picked),
                )
                obj, feas, _ = _objective(trial, instance, meal, w, h, budget)
                if feas and (not best_feas or obj < best_obj - 1e-6):
                    state, best_obj, best_feas = trial, obj, True
                    improved = True
                    break
            if improved:
                break
        if improved:
            continue

        # 1-0 drop
        for old_pid in list(state.items_alone):
            trial = _State(items_alone=[p for p in state.items_alone if p != old_pid],
                           combos_picked=list(state.combos_picked))
            obj, feas, _ = _objective(trial, instance, meal, w, h, budget)
            if feas and obj < best_obj - 1e-6:
                state, best_obj, best_feas = trial, obj, True
                improved = True
                break
        if improved:
            continue

        # 0-1 add
        for new_p in instance.products:
            if new_p.pid in covered:
                continue
            trial = _State(items_alone=state.items_alone + [new_p.pid],
                           combos_picked=list(state.combos_picked))
            obj, feas, _ = _objective(trial, instance, meal, w, h, budget)
            if feas and obj < best_obj - 1e-6:
                state, best_obj, best_feas = trial, obj, True
                improved = True
                break
        if improved:
            continue

        # combo swap: replace one combo with a different combo, or with two singles
        for old_cid in list(state.combos_picked):
            for new_c in instance.combos:
                if new_c.cid == old_cid:
                    continue
                trial = _State(
                    items_alone=list(state.items_alone),
                    combos_picked=[c for c in state.combos_picked if c != old_cid] + [new_c.cid],
                )
                obj, feas, _ = _objective(trial, instance, meal, w, h, budget)
                if feas and obj < best_obj - 1e-6:
                    state, best_obj, best_feas = trial, obj, True
                    improved = True
                    break
            if improved:
                break
        if improved:
            continue

        # combo -> 2 singles: try dropping a combo, then re-add singles via 0-1 search later
        # (covered by future construction restart; we stop here to save iterations.)

        break

    return state


# ---------------------------------------------------------------------------
# Phase 3: Multi-start GRASP-LS
# ---------------------------------------------------------------------------
def solve_grasp(instance: Instance, meal: MealTarget, w: Weights,
                budget: Optional[float] = None, n_restarts: int = 15,
                rcl_alpha_range: Tuple[float, float] = (0.10, 0.40),
                seed: int = 0,
                time_limit: float = 30.0) -> Optional[Solution]:
    rng = random.Random(seed)
    h = history_penalty(instance)

    best_state: Optional[_State] = None
    best_obj = float("inf")
    best_agg: Dict[str, float] = {}
    t0 = time.time()

    for r in range(n_restarts):
        if time.time() - t0 > time_limit:
            break
        alpha = rng.uniform(*rcl_alpha_range)
        state = _construct(instance, meal, w, h, budget, alpha, rng)
        state = _local_search(state, instance, meal, w, h, budget)
        obj, feas, agg = _objective(state, instance, meal, w, h, budget)
        if feas and obj < best_obj:
            best_obj, best_state, best_agg = obj, state, agg

    if best_state is None:
        return None

    pmap = {p.pid: p for p in instance.products}
    cmap = {c.cid: c for c in instance.combos}
    items_total = sorted(best_state.covered_items(instance))
    runtime = time.time() - t0

    # recompute slacks for reporting
    pro_total = best_agg["pro"]
    return Solution(
        obj=best_obj,
        runtime=runtime,
        cost=best_agg["cost"],
        nutri={"cal": best_agg["cal"], "pro": best_agg["pro"],
               "fat": best_agg["fat"], "carb": best_agg["carb"],
               "sug": best_agg["sug"], "sod": best_agg["sod"],
               "n": best_agg["n"]},
        items_alone=list(best_state.items_alone),
        combos_picked=list(best_state.combos_picked),
        items_total=items_total,
        slacks={
            "pro":     max(0.0, meal.protein_min - pro_total),
            "fat_lo":  max(0.0, meal.fat_min - best_agg["fat"]),
            "fat_hi":  max(0.0, best_agg["fat"] - meal.fat_max),
            "carb_lo": max(0.0, meal.carb_min - best_agg["carb"]),
            "carb_hi": max(0.0, best_agg["carb"] - meal.carb_max),
            "sug":     max(0.0, best_agg["sug"] - meal.sugar_max),
            "sod":     max(0.0, best_agg["sod"] - meal.sodium_max),
        },
        feasible_hard=True,
        gap=0.0,
    )
