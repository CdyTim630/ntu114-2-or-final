"""Extra experiments requested for the final report.

Adds two studies on top of run_experiments.py, written to results/:

  (A) random_scenarios.csv — a factorial STRESS-TEST design on random
      instances.  Factors crossed:
        * Budget level:  tight  vs  loose
        * Protein goal:  high (bulk)  vs  loose (maintain)
      => 2 x 2 = 4 scenarios, each over several sizes x seeds.  We record
      MILP/GRASP-LS feasibility, optimality gap, and runtime to show whether
      GRASP-LS stays close to the optimum under extreme conditions.

  (B) human_baseline.csv — a simulated "uninformed shopper" baseline.  For
      each real user we draw many random within-budget baskets (a proxy for
      grabbing items without nutritional optimization) and measure how often
      such a pick meets the single-meal targets, vs. the model.  This gives a
      current-solution comparison (target-attainment / spend).
"""
from __future__ import annotations
import csv
import random
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from data_loader import load_real_instance, generate_random_instance
from preprocessing import UserProfile, compute_daily_target, to_meal_target
from model_milp import Weights, solve_milp, history_penalty
from heuristic_proposed import solve_grasp, _State, _agg, _objective


def _write_csv(path: Path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        wri = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wri.writeheader()
        wri.writerows(rows)
    print(f"  wrote {path}  ({len(rows)} rows)")


# ---------------------------------------------------------------------------
# (A) factorial stress-test scenarios on random instances
# ---------------------------------------------------------------------------
def run_random_scenarios(out_path: Path) -> None:
    w = Weights()
    sizes = [(80, 25), (120, 35), (200, 60)]
    seeds = [1, 2, 3, 4]
    # 2x2 design: (budget level, protein goal)
    scenarios = [
        ("tight_highpro", 90,  "bulk"),
        ("tight_loosepro", 90, "maintain"),
        ("loose_highpro", 220, "bulk"),
        ("loose_loosepro", 220, "maintain"),
    ]
    rows = []
    for scen_name, budget, goal in scenarios:
        profile = UserProfile("M", 22, 175, 70, "mid", goal, budget, "regular")
        meal = to_meal_target(compute_daily_target(profile), "regular")
        for (n_p, n_c) in sizes:
            for seed in seeds:
                rinst = generate_random_instance(n_p, n_c, seed=seed)
                sm = solve_milp(rinst, meal, w, budget=budget, time_limit=30.0)
                sg = solve_grasp(rinst, meal, w, budget=budget, n_restarts=25, seed=seed * 11)
                mfeas = bool(sm and sm.feasible_hard)
                gfeas = bool(sg and sg.feasible_hard)
                gap = ""
                if mfeas and gfeas and sm.obj not in (0, float("inf")):
                    gap = round((sg.obj - sm.obj) / max(abs(sm.obj), 1e-6) * 100, 2)
                rows.append({
                    "scenario": scen_name, "budget": budget, "goal": goal,
                    "size": f"{n_p}p_{n_c}c", "seed": seed,
                    "milp_feasible": int(mfeas), "grasp_feasible": int(gfeas),
                    "gap_pct": gap,
                    "milp_runtime": round(sm.runtime, 4) if sm else "",
                    "grasp_runtime": round(sg.runtime, 4) if sg else "",
                })
        # per-scenario console summary
        sub = [r for r in rows if r["scenario"] == scen_name]
        gaps = [r["gap_pct"] for r in sub if isinstance(r["gap_pct"], (int, float))]
        grt = [r["grasp_runtime"] for r in sub if isinstance(r["grasp_runtime"], (int, float))]
        avg_gap = f"{mean(gaps):.2f}" if gaps else "NA"
        avg_grt = f"{mean(grt):.2f}" if grt else "NA"
        print(f"[scen] {scen_name:>16} (B={budget},{goal}): "
              f"MILP feas {sum(r['milp_feasible'] for r in sub)}/{len(sub)}, "
              f"GRASP feas {sum(r['grasp_feasible'] for r in sub)}/{len(sub)}, "
              f"avg gap {avg_gap}% (n={len(gaps)}), GRASP avg {avg_grt}s")
    _write_csv(out_path, rows)


# ---------------------------------------------------------------------------
# (B) simulated uninformed-shopper baseline vs the model
# ---------------------------------------------------------------------------
REAL_USERS = [
    ("U1_male_cut",      UserProfile("M", 22, 175, 70, "mid",  "cut",      120, "regular")),
    ("U2_male_bulk",     UserProfile("M", 24, 178, 75, "high", "bulk",     150, "regular")),
    ("U3_male_maintain", UserProfile("M", 30, 172, 70, "low",  "maintain", 100, "regular")),
    ("U4_female_cut",    UserProfile("F", 21, 162, 52, "mid",  "cut",      100, "regular")),
    ("U5_female_maint",  UserProfile("F", 26, 165, 55, "low",  "maintain",  90, "regular")),
    ("U6_female_bulk",   UserProfile("F", 23, 168, 58, "high", "bulk",     130, "regular")),
]


def run_human_baseline(out_path: Path, trials: int = 4000) -> None:
    inst = load_real_instance(str(ROOT.parent / "data"))
    h = history_penalty(inst)          # no history -> all zeros
    w = Weights()
    products = list(inst.products)
    rows = []

    for uid, profile in REAL_USERS:
        profile.scenario = "regular"
        meal = to_meal_target(compute_daily_target(profile), "regular")
        B = profile.budget

        # reference: the model's own meal (GRASP-LS; MILP for cost lower bound)
        sg = solve_grasp(inst, meal, w, budget=B, n_restarts=25, seed=42)
        sm = solve_milp(inst, meal, w, budget=B, time_limit=30.0)

        rng = random.Random(1000 + len(uid))
        costs = []
        c_all = c_cal = c_pro = c_sug = c_sod = 0
        for _ in range(trials):
            target_n = rng.choice([2, 3, 4])      # a typical blind grab
            order = products[:]
            rng.shuffle(order)
            chosen, cost = [], 0.0
            for p in order:
                if len(chosen) >= target_n:
                    break
                if cost + p.price > B:
                    continue
                chosen.append(p.pid); cost += p.price
            st = _State(items_alone=chosen)
            _, feas, _ = _objective(st, inst, meal, w, h, B)
            agg = _agg(st, inst)
            costs.append(agg["cost"])
            if feas: c_all += 1
            if meal.cal_min <= agg["cal"] <= meal.cal_max: c_cal += 1
            if agg["pro"] >= meal.protein_min: c_pro += 1
            if agg["sug"] <= meal.sugar_max:   c_sug += 1
            if agg["sod"] <= meal.sodium_max:  c_sod += 1

        row = {
            "user": uid, "budget": B,
            "human_avg_cost": round(mean(costs), 1),
            "human_all_targets_pct": round(100 * c_all / trials, 1),
            "human_cal_inband_pct":  round(100 * c_cal / trials, 1),
            "human_protein_met_pct": round(100 * c_pro / trials, 1),
            "human_sugar_ok_pct":    round(100 * c_sug / trials, 1),
            "human_sodium_ok_pct":   round(100 * c_sod / trials, 1),
            "model_cost":     round(sg.cost, 1) if sg else "",
            "model_feasible": int(bool(sg and sg.feasible_hard)),
            "milp_cost":      round(sm.cost, 1) if sm and sm.feasible_hard else "",
        }
        rows.append(row)
        print(f"[human] {uid}: all-targets {row['human_all_targets_pct']}%  "
              f"protein {row['human_protein_met_pct']}%  sodium-ok {row['human_sodium_ok_pct']}%  "
              f"avg NT${row['human_avg_cost']}  | model NT${row['model_cost']} (feasible)")
    _write_csv(out_path, rows)


if __name__ == "__main__":
    out = ROOT.parent / "results"
    print(">>> (A) factorial stress-test scenarios")
    run_random_scenarios(out / "random_scenarios.csv")
    print(">>> (B) uninformed-shopper baseline")
    run_human_baseline(out / "human_baseline.csv")
    print(">>> done.")
