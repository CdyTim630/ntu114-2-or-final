"""Smoke test for the three solvers on a real-world instance."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from data_loader import load_real_instance
from preprocessing import UserProfile, compute_daily_target, to_meal_target
from model_milp import Weights, solve_milp
from heuristic_proposed import solve_grasp
from heuristic_baseline import solve_greedy


def fmt_sol(name, sol):
    if sol is None:
        return f"{name:>8s}: NO SOLUTION"
    n = sol.nutri
    return (f"{name:>8s}: obj={sol.obj:8.2f}  cost={sol.cost:6.1f}  "
            f"cal={n['cal']:6.1f}  pro={n['pro']:5.1f}  sod={n['sod']:6.0f}  "
            f"items={sol.items_total}  combos={sol.combos_picked}  "
            f"time={sol.runtime:.3f}s")


def main():
    inst = load_real_instance("data")
    user = UserProfile(sex="M", age=22, height_cm=175, weight_kg=70,
                       activity="mid", goal="cut", budget=120, scenario="regular")
    daily = compute_daily_target(user)
    meal  = to_meal_target(daily, user.scenario)
    print(f"Meal target  cal∈[{meal.cal_min:.0f},{meal.cal_max:.0f}]  "
          f"pro>={meal.protein_min:.1f}  budget={user.budget}  Nmax={meal.n_max}")

    w = Weights()
    sol_milp   = solve_milp(inst, meal, w, budget=user.budget, time_limit=20.0)
    sol_grasp  = solve_grasp(inst, meal, w, budget=user.budget, n_restarts=20, seed=7)
    sol_greedy = solve_greedy(inst, meal, w, budget=user.budget)

    print(fmt_sol("MILP",   sol_milp))
    print(fmt_sol("GRASP",  sol_grasp))
    print(fmt_sol("Greedy", sol_greedy))

    if sol_milp and sol_grasp:
        gap = (sol_grasp.obj - sol_milp.obj) / max(abs(sol_milp.obj), 1e-6) * 100
        print(f"GRASP gap vs MILP: {gap:.2f}%")

    pmap = {p.pid: p for p in inst.products}
    if sol_milp:
        print("\nMILP picks:")
        for pid in sol_milp.items_total:
            p = pmap[pid]
            print(f"  - {p.name}  NT${p.price:.0f}  {p.cal:.0f}kcal  pro={p.pro:.1f}g  sod={p.sod:.0f}mg")


if __name__ == "__main__":
    main()
