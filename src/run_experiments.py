"""Full experiment campaign for the final report.

Runs three solvers (MILP / GRASP-LS / Greedy) across:
  * 6 real-world user profiles  x 3 scenarios = 18 real-world instances.
  * 6 random instance sizes x 5 seeds = 30 random instances.
  * Sensitivity sweep on weight (alpha, beta) for one fixed profile.

Outputs are written to results/ as CSV files used by the report tables and plots.
"""
from __future__ import annotations
import csv
import sys
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from data_loader import load_real_instance, generate_random_instance, Instance
from preprocessing import UserProfile, compute_daily_target, to_meal_target
from model_milp import Weights, solve_milp, Solution
from heuristic_proposed import solve_grasp
from heuristic_baseline import solve_greedy


REAL_USERS = [
    ("U1_male_cut",       UserProfile("M", 22, 175, 70, "mid",  "cut",      120, "regular")),
    ("U2_male_bulk",      UserProfile("M", 24, 178, 75, "high", "bulk",     150, "regular")),
    ("U3_male_maintain",  UserProfile("M", 30, 172, 70, "low",  "maintain", 100, "regular")),
    ("U4_female_cut",     UserProfile("F", 21, 162, 52, "mid",  "cut",      100, "regular")),
    ("U5_female_maint",   UserProfile("F", 26, 165, 55, "low",  "maintain",  90, "regular")),
    ("U6_female_bulk",    UserProfile("F", 23, 168, 58, "high", "bulk",     130, "regular")),
]
SCENARIOS = ["light", "regular", "latenight"]


def _row_from_sol(name: str, sol: Optional[Solution], inst_id: str,
                  meal_cal_min: float, meal_pro_min: float) -> Dict:
    if sol is None:
        return {"solver": name, "instance": inst_id, "feasible": 0,
                "obj": "", "cost": "", "cal": "", "pro": "",
                "fat": "", "carb": "", "sug": "", "sod": "", "n": "",
                "items": "", "combos": "", "runtime": "", "gap": "",
                "cal_min": meal_cal_min, "pro_min": meal_pro_min}
    return {
        "solver": name, "instance": inst_id,
        "feasible": int(sol.feasible_hard),
        "obj":  round(sol.obj, 4) if sol.obj != float("inf") else "inf",
        "cost": round(sol.cost, 2),
        "cal":  round(sol.nutri["cal"], 1),
        "pro":  round(sol.nutri["pro"], 1),
        "fat":  round(sol.nutri["fat"], 1),
        "carb": round(sol.nutri["carb"], 1),
        "sug":  round(sol.nutri["sug"], 1),
        "sod":  round(sol.nutri["sod"], 0),
        "n":    int(sol.nutri["n"]),
        "items":  "|".join(map(str, sol.items_total)),
        "combos": "|".join(map(str, sol.combos_picked)),
        "runtime": round(sol.runtime, 4),
        "gap": round(sol.gap, 6),
        "cal_min": round(meal_cal_min, 1),
        "pro_min": round(meal_pro_min, 1),
    }


def run_real_world(out_path: Path) -> None:
    inst = load_real_instance(str(ROOT.parent / "data"))
    w = Weights()
    rows: List[Dict] = []

    for user_id, profile in REAL_USERS:
        for scen in SCENARIOS:
            profile.scenario = scen
            meal = to_meal_target(compute_daily_target(profile), scen)
            inst_id = f"{user_id}-{scen}"

            sol_m  = solve_milp(inst, meal, w, budget=profile.budget, time_limit=30.0)
            sol_g  = solve_grasp(inst, meal, w, budget=profile.budget,
                                 n_restarts=25, seed=42)
            sol_gr = solve_greedy(inst, meal, w, budget=profile.budget)

            rows.append(_row_from_sol("MILP",   sol_m,  inst_id, meal.cal_min, meal.protein_min))
            rows.append(_row_from_sol("GRASP",  sol_g,  inst_id, meal.cal_min, meal.protein_min))
            rows.append(_row_from_sol("Greedy", sol_gr, inst_id, meal.cal_min, meal.protein_min))
            print(f"[real] {inst_id}: MILP={_obj(sol_m)}  GRASP={_obj(sol_g)}  "
                  f"Greedy={_obj(sol_gr)}  gap={_gap(sol_m, sol_g)}%")

    _write_csv(out_path, rows)


def run_random(out_path: Path) -> None:
    w = Weights()
    rows: List[Dict] = []
    sizes = [(30, 8), (50, 15), (80, 25), (120, 35), (200, 60), (300, 90)]
    seeds = [1, 2, 3, 4, 5]
    profile = UserProfile("M", 22, 175, 70, "mid", "cut", 120, "regular")
    meal = to_meal_target(compute_daily_target(profile), profile.scenario)

    for (n_p, n_c) in sizes:
        for seed in seeds:
            rinst = generate_random_instance(n_p, n_c, seed=seed)
            inst_id = f"rand_{n_p}p_{n_c}c_s{seed}"

            sol_m  = solve_milp(rinst, meal, w, budget=profile.budget, time_limit=60.0)
            sol_g  = solve_grasp(rinst, meal, w, budget=profile.budget,
                                 n_restarts=25, seed=seed * 11)
            sol_gr = solve_greedy(rinst, meal, w, budget=profile.budget)

            rows.append(_row_from_sol("MILP",   sol_m,  inst_id, meal.cal_min, meal.protein_min))
            rows.append(_row_from_sol("GRASP",  sol_g,  inst_id, meal.cal_min, meal.protein_min))
            rows.append(_row_from_sol("Greedy", sol_gr, inst_id, meal.cal_min, meal.protein_min))
            print(f"[rand] {inst_id}: MILP={_obj(sol_m)}  GRASP={_obj(sol_g)}  "
                  f"Greedy={_obj(sol_gr)}  gap={_gap(sol_m, sol_g)}%")

    _write_csv(out_path, rows)


def run_sensitivity(out_path: Path) -> None:
    """Sweep beta (protein-bonus weight) and gamma (history penalty).
    Uses a high budget to expose the trade-off (low budget pins solutions)."""
    inst = load_real_instance(str(ROOT.parent / "data"))
    profile = UserProfile("M", 22, 175, 70, "mid", "cut", 220, "regular")
    meal = to_meal_target(compute_daily_target(profile), "regular")
    rows: List[Dict] = []

    # broader range so the trade-off becomes visible
    for beta in [0.0, 0.5, 1.0, 2.0, 4.0, 8.0]:
        w = Weights(beta=beta, lam_pro=8.0)
        sol = solve_milp(inst, meal, w, budget=profile.budget, time_limit=15.0)
        rows.append(_row_from_sol("MILP", sol, f"beta={beta}", meal.cal_min, meal.protein_min))

    # history effect: dynamically take the gamma=0 optimum's items as the recent
    # history, then sweep gamma to show the tiered-memory penalty drives them out.
    # gamma_cat is held at 0 here to isolate the ITEM-level history effect.
    base = load_real_instance(str(ROOT.parent / "data"))
    sol0 = solve_milp(base, meal, Weights(gamma=0.0, gamma_cat=0.0),
                      budget=profile.budget, time_limit=15.0)
    hist_items = list(sol0.items_total)
    for gamma in [0.0, 1.0, 2.0, 5.0, 10.0, 20.0]:
        inst_with_hist = load_real_instance(str(ROOT.parent / "data"))
        inst_with_hist.history = list(hist_items)
        w = Weights(gamma=gamma, gamma_cat=0.0)
        sol = solve_milp(inst_with_hist, meal, w, budget=profile.budget, time_limit=15.0)
        rows.append(_row_from_sol("MILP", sol, f"gamma={gamma}",
                                  meal.cal_min, meal.protein_min))

    _write_csv(out_path, rows)


def run_price_of_diversity(out_path: Path) -> None:
    """想法 1 — quantify the *price of diversity*.

    The recommender samples uniformly among epsilon-optimal solutions, i.e. the
    set { s : z(s) <= z* + epsilon }.  We sweep the window epsilon and measure,
    over many random seeds, (a) how many DISTINCT meals the sampler can produce
    and (b) the average objective/cost premium paid relative to the MILP optimum
    z*.  The resulting curve is the cost of diversity: how much variety you buy
    per NT$ of optimality you give up.
    """
    inst = load_real_instance(str(ROOT.parent / "data"))
    profile = UserProfile("M", 22, 175, 70, "mid", "maintain", 120, "regular")
    meal = to_meal_target(compute_daily_target(profile), "regular")
    w = Weights()
    z_opt = solve_milp(inst, meal, w, budget=profile.budget, time_limit=30.0).obj

    rows: List[Dict] = []
    for eps in [0.0, 2.0, 4.0, 8.0, 16.0, 32.0]:
        pool = solve_milp(inst, meal, w, budget=profile.budget, time_limit=60.0,
                          pool_eps=eps, pool_max=800)
        # distinct meals whose objective is within eps of the optimum
        meals = [(ids, cost, o) for (ids, cost, o) in pool if o <= z_opt + eps + 1e-6]
        n = len(meals)
        avg_cost = mean(c for _, c, _ in meals) if meals else float("nan")
        min_cost = min(c for _, c, _ in meals) if meals else float("nan")
        max_cost = max(c for _, c, _ in meals) if meals else float("nan")
        rows.append({
            "eps": eps,
            "distinct_meals": n,
            "min_cost": round(min_cost, 2),
            "avg_cost": round(avg_cost, 2),
            "max_cost": round(max_cost, 2),
            "milp_opt_obj": round(z_opt, 3),
            "cost_premium": round(avg_cost - min_cost, 2),
        })
        print(f"[div] eps={eps:>4}: distinct meals={n:>3}  "
              f"cost NT${min_cost:.0f}-{max_cost:.0f}  "
              f"avg-premium=NT${avg_cost - min_cost:.1f}")
    _write_csv(out_path, rows)


def _obj(sol):
    if sol is None: return "None"
    return f"{sol.obj:.2f}"

def _gap(sol_m, sol_g):
    if sol_m is None or sol_g is None: return "NA"
    if sol_m.obj == 0: return "0"
    return f"{(sol_g.obj - sol_m.obj) / max(abs(sol_m.obj), 1e-6) * 100:.2f}"

def _write_csv(path: Path, rows: List[Dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        wri = csv.DictWriter(f, fieldnames=keys)
        wri.writeheader()
        wri.writerows(rows)
    print(f"  wrote {path}  ({len(rows)} rows)")


if __name__ == "__main__":
    out_dir = ROOT.parent / "results"
    out_dir.mkdir(exist_ok=True)
    print(">>> real-world experiments")
    run_real_world(out_dir / "real_world.csv")
    print(">>> random instances")
    run_random(out_dir / "random.csv")
    print(">>> sensitivity sweep")
    run_sensitivity(out_dir / "sensitivity.csv")
    print(">>> price of diversity (想法 1)")
    run_price_of_diversity(out_dir / "price_of_diversity.csv")
    print(">>> done.")
