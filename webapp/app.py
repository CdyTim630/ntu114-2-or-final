"""Flask web app — interactive convenience-store meal recommender.

Demonstrates the OR model from the report end-to-end:
  user form  ->  Mifflin-St Jeor preprocessing  ->  MILP (Gurobi) or GRASP-LS
  ->  recommended meal + nutrition breakdown.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from data_loader import load_real_instance, Instance, Product
from preprocessing import UserProfile, compute_daily_target, to_meal_target, SCENARIO_PARAMS
from model_milp import (Weights, solve_milp, history_tier, HISTORY_MAX,
                        HISTORY_TIER_LABELS)
from heuristic_proposed import solve_grasp


app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "or-final-project-2026"
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
# re-read templates from disk on every request so HTML edits show up on a plain
# browser refresh — no server restart needed (debug stays off, no debugger exposed)
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.after_request
def _no_cache(resp):
    # Disable caching for BOTH the HTML page and the static assets, otherwise the
    # browser keeps serving a stale index.html and edits silently don't appear.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# load the real-world instance once at startup (prefer scraped real data if present)
DATA_DIR = ROOT / "data"
INSTANCE: Instance = load_real_instance(str(DATA_DIR))
print(f"[startup] loaded {len(INSTANCE.products)} products, {len(INSTANCE.combos)} combos")


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/recommend")
def api_recommend():
    """JSON endpoint: user profile in -> recommendation + nutrition out."""
    payload = request.get_json(force=True)
    try:
        profile = UserProfile(
            sex=payload["sex"],
            age=int(payload["age"]),
            height_cm=float(payload["height"]),
            weight_kg=float(payload["weight"]),
            activity=payload["activity"],
            goal=payload["goal"],
            budget=float(payload["budget"]),
            scenario=payload["scenario"],
        )
    except (KeyError, ValueError) as e:
        return jsonify({"ok": False, "err": f"invalid input: {e}"}), 400

    daily = compute_daily_target(profile)
    meal  = to_meal_target(daily, profile.scenario)

    # apply history from session (cookie)
    hist = session.get("history", [])
    INSTANCE.history = hist[:HISTORY_MAX]

    w = Weights(
        alpha=float(payload.get("alpha", 1.0)),
        beta=float(payload.get("beta", 0.5)),
        gamma=float(payload.get("gamma", 6.0)),
        gamma_cat=float(payload.get("gamma_cat", 8.0)),
    )
    solver = payload.get("solver", "grasp")
    t0 = time.time()
    seed = int(time.time() * 1000) % 99999
    if solver == "milp":
        sol = solve_milp(INSTANCE, meal, w, budget=profile.budget, time_limit=20.0)
    else:
        # diversify: pick at random among near-optimal meals so each click gives
        # some variety even before the history penalty kicks in. n_restarts /
        # time_limit kept modest so the page responds in ~2-3 s.
        sol = solve_grasp(INSTANCE, meal, w, budget=profile.budget, n_restarts=12,
                          seed=seed, diversify=8.0, time_limit=5.0)
        if sol is None:
            # GRASP's greedy path can miss a tight feasible meal (e.g. a snug
            # budget); fall back to the exact MILP so the user still gets a meal
            # whenever one exists.
            sol = solve_milp(INSTANCE, meal, w, budget=profile.budget, time_limit=20.0)
    runtime = time.time() - t0

    if sol is None:
        return jsonify({"ok": False, "err": "Infeasible — try widening the budget or switching scenario."}), 200

    pmap = {p.pid: p for p in INSTANCE.products}
    items = [pmap[pid] for pid in sol.items_total]

    # update history queue: newly recommended items go to the front (rank 1 ->
    # top tier), older ones age down; drop anything past the last tier.
    new_hist = sol.items_total + hist
    seen, dedup = set(), []
    for pid in new_hist:
        if pid in seen: continue
        seen.add(pid); dedup.append(pid)
    session["history"] = dedup[:HISTORY_MAX]

    return jsonify({
        "ok": True,
        "solver": solver,
        "runtime_ms": round(runtime * 1000, 1),
        "obj": round(sol.obj, 2),
        "items": [{
            "pid": p.pid, "name": p.name, "category": p.category,
            "price": p.price, "cal": p.cal, "pro": p.pro, "fat": p.fat,
            "carb": p.carb, "sug": p.sug, "sod": p.sod,
            "is_main": p.is_main, "is_protein": p.is_protein,
        } for p in items],
        "combos": [
            next((c for c in INSTANCE.combos if c.cid == cid), None).__dict__
            for cid in sol.combos_picked
        ],
        "totals": {
            "cost": round(sol.cost, 1),
            **{k: round(v, 1) for k, v in sol.nutri.items()},
        },
        "targets": {
            "cal_min":     round(meal.cal_min, 1),
            "cal_max":     round(meal.cal_max, 1),
            "protein_min": round(meal.protein_min, 1),
            "fat_min":     round(meal.fat_min, 1),
            "fat_max":     round(meal.fat_max, 1),
            "carb_min":    round(meal.carb_min, 1),
            "carb_max":    round(meal.carb_max, 1),
            "sugar_max":   round(meal.sugar_max, 1),
            "sodium_max":  round(meal.sodium_max, 1),
            "n_max":       meal.n_max,
            "budget":      profile.budget,
        },
        "daily": {k: round(getattr(daily, k), 1)
                  for k in ["cal", "protein", "fat_min", "fat_max", "carb_min", "carb_max"]},
        "history": [{"pid": pid, "name": pmap[pid].name,
                     "category": pmap[pid].category,
                     "tier": history_tier(r),
                     "tier_label": HISTORY_TIER_LABELS[min(history_tier(r), len(HISTORY_TIER_LABELS) - 1)]}
                    for r, pid in enumerate(session["history"], start=1) if pid in pmap],
        "slacks":  {k: round(v, 1) for k, v in sol.slacks.items()},
    })


@app.post("/api/reset_history")
def api_reset_history():
    session["history"] = []
    return jsonify({"ok": True})


@app.route("/api/history")
def api_history():
    """Current session taste-memory, formatted like the recommend response's
    `history` field so the front-end can render it on demand (modal)."""
    pmap = {p.pid: p for p in INSTANCE.products}
    hist = session.get("history", [])
    return jsonify({"ok": True, "history": [
        {"pid": pid, "name": pmap[pid].name,
         "category": pmap[pid].category,
         "tier": history_tier(r),
         "tier_label": HISTORY_TIER_LABELS[min(history_tier(r), len(HISTORY_TIER_LABELS) - 1)]}
        for r, pid in enumerate(hist, start=1) if pid in pmap]})


@app.route("/api/products")
def api_products():
    return jsonify([{
        "pid": p.pid, "name": p.name, "category": p.category,
        "price": p.price, "cal": p.cal, "pro": p.pro, "sod": p.sod,
        "is_main": p.is_main, "is_protein": p.is_protein,
    } for p in INSTANCE.products])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
