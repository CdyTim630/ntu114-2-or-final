"""Simple baseline heuristic: pure greedy by protein-per-NT-dollar.

Used only as a "very simple heuristic" benchmark required by the spec, to
show the value of the more sophisticated GRASP-LS algorithm. Combos are
considered only if their items rank in the top-K by ratio.
"""
from typing import Dict, List, Optional
import time

from data_loader import Instance
from preprocessing import MealTarget
from model_milp import Weights, Solution, history_penalty
from heuristic_proposed import _State, _objective, _agg


def solve_greedy(instance: Instance, meal: MealTarget, w: Weights,
                 budget: Optional[float] = None) -> Optional[Solution]:
    t0 = time.time()
    h = history_penalty(instance)
    ratio = []
    for p in instance.products:
        r = p.pro / max(p.price, 1.0)         # protein per NTD
        ratio.append((p, r))
    ratio.sort(key=lambda x: x[1], reverse=True)

    state = _State()
    pmap = {p.pid: p for p in instance.products}

    for p, _ in ratio:
        agg = _agg(state, instance)
        if agg["n"] >= meal.n_max:
            break
        if p.pid in state.covered_items(instance):
            continue
        if budget is not None and agg["cost"] + p.price > budget:
            continue
        if agg["cal"] + p.cal > meal.cal_max:
            continue
        state.items_alone.append(p.pid)

    obj, feas, agg = _objective(state, instance, meal, w, h, budget)
    if not feas:
        # If hard-infeasible (e.g. cal_min not met), keep going with the closest
        # we can manage so we still get a comparable number.
        for p, _ in ratio:
            agg2 = _agg(state, instance)
            if agg2["n"] >= meal.n_max:
                break
            if p.pid in state.covered_items(instance):
                continue
            if budget is not None and agg2["cost"] + p.price > budget:
                continue
            state.items_alone.append(p.pid)
            agg2 = _agg(state, instance)
            if agg2["cal"] >= meal.cal_min and agg2["cal"] <= meal.cal_max:
                break
        obj, feas, agg = _objective(state, instance, meal, w, h, budget)

    items_total = sorted(state.covered_items(instance))
    return Solution(
        obj=obj,
        runtime=time.time() - t0,
        cost=agg.get("cost", 0.0),
        nutri={"cal": agg.get("cal",0), "pro": agg.get("pro",0),
               "fat": agg.get("fat",0), "carb": agg.get("carb",0),
               "sug": agg.get("sug",0), "sod": agg.get("sod",0),
               "n":   agg.get("n",0)},
        items_alone=list(state.items_alone),
        combos_picked=list(state.combos_picked),
        items_total=items_total,
        slacks={
            "pro":     max(0.0, meal.protein_min - agg.get("pro", 0)),
            "fat_lo":  max(0.0, meal.fat_min - agg.get("fat", 0)),
            "fat_hi":  max(0.0, agg.get("fat", 0) - meal.fat_max),
            "carb_lo": max(0.0, meal.carb_min - agg.get("carb", 0)),
            "carb_hi": max(0.0, agg.get("carb", 0) - meal.carb_max),
            "sug":     max(0.0, agg.get("sug", 0) - meal.sugar_max),
            "sod":     max(0.0, agg.get("sod", 0) - meal.sodium_max),
        },
        feasible_hard=feas,
        gap=0.0,
    )
