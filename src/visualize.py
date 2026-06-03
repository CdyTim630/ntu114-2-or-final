"""Generate the figures used by the report and slides."""
from __future__ import annotations
import csv
from pathlib import Path
from collections import defaultdict
from statistics import mean, median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# pick a CJK font if available, otherwise fall back gracefully
_fonts = {f.name for f in fm.fontManager.ttflist}
for cand in ["Microsoft JhengHei", "Microsoft YaHei", "PMingLiU", "SimHei",
             "Noto Sans CJK TC", "Arial Unicode MS"]:
    if cand in _fonts:
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [cand, "DejaVu Sans"]
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["mathtext.default"] = "regular"
plt.rcParams["mathtext.fontset"] = "dejavusans"

ROOT = Path(__file__).parent.parent
RES = ROOT / "results"
FIG = ROOT / "results" / "figs"
FIG.mkdir(parents=True, exist_ok=True)


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_float(x):
    if x in ("", "inf", "None"): return float("inf")
    return float(x)


# ---------------------------------------------------------------------------
# Figure 1: Optimality gap by random instance size
# ---------------------------------------------------------------------------
def fig_gap_by_size():
    rows = _load(RES / "random.csv")
    by_inst = defaultdict(dict)
    for r in rows:
        by_inst[r["instance"]][r["solver"]] = r

    by_size = defaultdict(list)
    for inst, solvers in by_inst.items():
        milp = solvers.get("MILP")
        grasp = solvers.get("GRASP")
        if not milp or not grasp:
            continue
        if milp["feasible"] != "1" or grasp["feasible"] != "1":
            continue
        m_obj = _to_float(milp["obj"])
        g_obj = _to_float(grasp["obj"])
        if m_obj in (0, float("inf")) or g_obj == float("inf"):
            continue
        size = int(inst.split("_")[1].rstrip("p"))
        by_size[size].append((g_obj - m_obj) / abs(m_obj) * 100)

    sizes = sorted(by_size)
    gaps_grasp = [mean(by_size[s]) if by_size[s] else 0 for s in sizes]

    x = range(len(sizes))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(list(x), gaps_grasp, 0.5, color="#1f77b4")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{s} items" for s in sizes], fontsize=13)
    ax.set_ylabel("Aligned gap (%)", fontsize=15)
    ax.set_title("GRASP-LS gap by size", fontsize=17, fontweight="bold")
    ax.tick_params(axis="y", labelsize=13)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIG / "fig_gap_by_size.png", dpi=180)
    plt.close()


# ---------------------------------------------------------------------------
# Figure 2: Runtime scaling
# ---------------------------------------------------------------------------
def fig_runtime_by_size():
    rows = _load(RES / "random.csv")
    by_size = defaultdict(lambda: defaultdict(list))
    for r in rows:
        size = int(r["instance"].split("_")[1].rstrip("p"))
        try:
            rt = float(r["runtime"]) if r["runtime"] != "" else 0.0
        except ValueError:
            rt = 0.0
        by_size[size][r["solver"]].append(rt)

    sizes = sorted(by_size)
    milp_rt  = [mean(by_size[s]["MILP"]) for s in sizes]
    grasp_rt = [mean(by_size[s]["GRASP"]) for s in sizes]
    greedy_rt = [mean(by_size[s]["Greedy"]) for s in sizes]

    fig, ax = plt.subplots(figsize=(7, 4))
    # use millisecond axis to avoid log-scale negative-exponent rendering issues
    milp_ms  = [x * 1000 for x in milp_rt]
    grasp_ms = [x * 1000 for x in grasp_rt]
    greedy_ms = [max(x, 1e-4) * 1000 for x in greedy_rt]
    ax.plot(sizes, milp_ms,  "o-", label="MILP (Gurobi)", color="#2ca02c", linewidth=2.2, markersize=7)
    ax.plot(sizes, grasp_ms, "s-", label="GRASP-LS", color="#1f77b4", linewidth=2.2, markersize=7)
    ax.plot(sizes, greedy_ms, "^-", label="Greedy", color="#d62728", linewidth=2.2, markersize=7)
    ax.set_xlabel("Number of items", fontsize=15)
    ax.set_ylabel("Average runtime (ms)", fontsize=15)
    ax.set_title("Runtime by size", fontsize=17, fontweight="bold")
    ax.set_yscale("log")
    ax.tick_params(axis="both", labelsize=13)
    ax.legend(fontsize=12)
    ax.grid(True, which="both", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIG / "fig_runtime.png", dpi=180)
    plt.close()


# ---------------------------------------------------------------------------
# Figure 3: Cost vs Protein trade-off (sensitivity sweep on beta)
# ---------------------------------------------------------------------------
def fig_beta_tradeoff():
    rows = _load(RES / "sensitivity.csv")
    beta_rows = [r for r in rows if r["instance"].startswith("beta=")]
    betas = [float(r["instance"].split("=")[1]) for r in beta_rows]
    costs = [float(r["cost"]) for r in beta_rows]
    pros  = [float(r["pro"])  for r in beta_rows]

    fig, ax1 = plt.subplots(figsize=(7, 4.8))
    ax1.plot(betas, costs, "o-", color="#1f77b4", label="Total cost (NT$)")
    ax1.set_xlabel(r"Protein weight $\beta$", fontsize=16)
    ax1.set_ylabel("Total cost (NT$)", color="#1f77b4", fontsize=16)
    ax1.tick_params(axis="y", labelcolor="#1f77b4", labelsize=15)
    ax1.tick_params(axis="x", labelsize=15)
    ax2 = ax1.twinx()
    ax2.plot(betas, pros, "s--", color="#d62728", label="Total protein (g)")
    ax2.set_ylabel("Total protein (g)", color="#d62728", fontsize=16)
    ax2.tick_params(axis="y", labelcolor="#d62728", labelsize=15)
    ax1.set_title(r"Cost--protein trade-off vs. $\beta$", fontsize=16)
    ax1.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIG / "fig_beta_tradeoff.png", dpi=180)
    plt.close()


# ---------------------------------------------------------------------------
# Figure 4: Effect of historical-penalty weight gamma
# ---------------------------------------------------------------------------
def fig_gamma_diversity():
    rows = _load(RES / "sensitivity.csv")
    gamma_rows = [r for r in rows if r["instance"].startswith("gamma=")]
    gammas = [float(r["instance"].split("=")[1]) for r in gamma_rows]
    # baseline = the gamma=0 optimum's items (the "recent history" that was
    # injected); count how many of them reappear as gamma grows.
    base_row = next((r for r in gamma_rows if abs(float(r["instance"].split("=")[1])) < 1e-9), gamma_rows[0])
    base_set = set(int(x) for x in base_row["items"].split("|") if x)
    repeats = []
    for r in gamma_rows:
        ids = set(int(x) for x in r["items"].split("|") if x)
        repeats.append(len(base_set & ids))
    costs = [float(r["cost"]) for r in gamma_rows]

    fig, ax1 = plt.subplots(figsize=(7, 4.8))
    ax1.bar(range(len(gammas)), repeats, color="#9467bd", alpha=0.7, label="Repeated items")
    ax1.set_xticks(range(len(gammas)))
    ax1.set_xticklabels([str(g) for g in gammas])
    ax1.set_xlabel(r"History-penalty weight $\gamma$", fontsize=16)
    ax1.set_ylabel("Repeated recent items", color="#9467bd", fontsize=16)
    ax1.set_ylim(0, 3.5)
    ax1.tick_params(axis="both", labelsize=15)
    ax2 = ax1.twinx()
    ax2.plot(range(len(gammas)), costs, "o-", color="#ff7f0e", label="Total cost")
    ax2.set_ylabel("Total cost (NT$)", color="#ff7f0e", fontsize=16)
    ax2.tick_params(axis="y", labelsize=15)
    ax1.set_title(r"Effect of $\gamma$ on diversity", fontsize=16)
    plt.tight_layout()
    plt.savefig(FIG / "fig_gamma_diversity.png", dpi=180)
    plt.close()


# ---------------------------------------------------------------------------
# Figure 5: Feasibility rate across solvers (real world)
# ---------------------------------------------------------------------------
def fig_feasibility():
    rows = _load(RES / "real_world.csv")
    by_solver = defaultdict(lambda: [0, 0])
    for r in rows:
        by_solver[r["solver"]][1] += 1
        if r["feasible"] == "1":
            by_solver[r["solver"]][0] += 1

    solvers = ["MILP", "GRASP", "Greedy"]
    labels  = ["MILP", "GRASP-LS", "Greedy"]
    rates = [by_solver[s][0] / by_solver[s][1] * 100 for s in solvers]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(labels, rates, color=["#2ca02c", "#1f77b4", "#d62728"])
    ax.set_ylabel("Hard-feasible rate (%)", fontsize=18)
    ax.set_title("Feasibility on 18 real instances", fontsize=19, fontweight="bold")
    ax.set_ylim(0, 110)
    ax.tick_params(labelsize=17)
    for b, v in zip(bars, rates):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 2,
                f"{v:.0f}%", ha="center", fontsize=18, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIG / "fig_feasibility.png", dpi=180)
    plt.close()


# ---------------------------------------------------------------------------
# Figure 6: Real-world solution stack (one example) – nutrient breakdown
# ---------------------------------------------------------------------------
def fig_realworld_breakdown():
    rows = _load(RES / "real_world.csv")
    targets = {}
    for r in rows:
        targets[r["instance"]] = (float(r["cal_min"]), float(r["pro_min"]))
    # use U1 regular as the showcase
    ex = [r for r in rows if r["instance"] == "U1_male_cut-regular"]
    if not ex: return
    solvers = []; cals = []; pros = []; sods = []; costs = []
    for r in ex:
        solvers.append(r["solver"])
        cals.append(_to_float(r["cal"])  if r["cal"]  not in ("", "inf") else 0)
        pros.append(_to_float(r["pro"])  if r["pro"]  not in ("", "inf") else 0)
        sods.append(_to_float(r["sod"])  if r["sod"]  not in ("", "inf") else 0)
        costs.append(_to_float(r["cost"]) if r["cost"] not in ("", "inf") else 0)

    # clean English display names for the solvers (consistent: GRASP-LS)
    _label = {"milp": "MILP", "grasp": "GRASP-LS", "greedy": "Greedy",
              "MILP": "MILP", "GRASP": "GRASP-LS", "Greedy": "Greedy"}
    xlabels = [_label.get(s, s) for s in solvers]

    fig, axes = plt.subplots(1, 4, figsize=(13, 3.9))
    panels = [
        (cals,  "Calories (kcal)", targets["U1_male_cut-regular"][0], "min"),
        (pros,  "Protein (g)",     targets["U1_male_cut-regular"][1], "min"),
        (sods,  "Sodium (mg)",     960, "cap"),
        (costs, "Cost (NT$)",      120, "budget"),
    ]
    for ax, (vals, title, ref, kind) in zip(axes, panels):
        bars = ax.bar(xlabels, vals, color=["#2ca02c", "#1f77b4", "#d62728"])
        ax.axhline(ref, ls="--", color="black", alpha=0.6, label=f"{kind} = {ref:.0f}")
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.tick_params(axis="x", labelsize=12)
        ax.tick_params(axis="y", labelsize=10)
        ax.set_ylim(top=max(vals + [ref]) * 1.28)
        ax.legend(fontsize=10, loc="upper left", frameon=False)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width()/2, b.get_height(),
                    f"{v:.0f}", ha="center", va="bottom", fontsize=12, fontweight="bold")
    # flag the Greedy sodium violation
    gi = next((i for i, s in enumerate(xlabels) if s == "Greedy"), None)
    if gi is not None and sods[gi] > 960:
        axes[2].text(gi, sods[gi] * 1.12, "violates sodium cap",
                     ha="center", va="bottom", fontsize=10.5,
                     color="#d62728", fontweight="bold")
    fig.suptitle("U1 (male · cut · regular): nutrition & cost across solvers",
                 y=1.03, fontsize=15, fontweight="bold")
    plt.tight_layout()
    plt.savefig(FIG / "fig_real_breakdown.png", dpi=180, bbox_inches="tight")
    plt.close()


def fig_price_of_diversity():
    """想法 1 — the price-of-diversity curve: as the epsilon-optimal sampling
    window grows, more distinct meals become reachable, but the average cost
    premium over the MILP optimum rises. Shows the diversity/optimality trade-off."""
    path = RES / "price_of_diversity.csv"
    if not path.exists():
        return
    rows = _load(path)
    eps      = [float(r["eps"]) for r in rows]
    distinct = [int(r["distinct_meals"]) for r in rows]
    premium  = [float(r["cost_premium"]) for r in rows]

    x = range(len(eps))
    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.bar(x, distinct, color="#1f77b4", alpha=0.75, label="Distinct meals")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels([f"{e:.0f}" for e in eps])
    ax1.set_xlabel("ε-best window (NT$)", fontsize=14)
    ax1.set_ylabel("Distinct meals reachable", color="#1f77b4", fontsize=14)
    ax1.tick_params(axis="y", labelcolor="#1f77b4", labelsize=13)
    ax1.tick_params(axis="x", labelsize=13)
    ax2 = ax1.twinx()
    ax2.plot(list(x), premium, "s--", color="#d62728", label="Avg. cost premium")
    ax2.set_ylabel("Avg. cost premium vs. optimum (NT$)", color="#d62728", fontsize=14)
    ax2.tick_params(axis="y", labelcolor="#d62728", labelsize=13)
    ax1.set_title("Price of diversity: variety vs. cost premium", fontsize=16)
    ax1.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIG / "fig_price_of_diversity.png", dpi=180)
    plt.close()


if __name__ == "__main__":
    fig_gap_by_size()
    fig_runtime_by_size()
    fig_beta_tradeoff()
    fig_gamma_diversity()
    fig_feasibility()
    fig_realworld_breakdown()
    fig_price_of_diversity()
    print("Figures written to", FIG)
