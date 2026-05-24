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
    by_size = defaultdict(lambda: {"MILP": [], "GRASP": [], "Greedy": []})
    for r in rows:
        size = int(r["instance"].split("_")[1].rstrip("p"))
        by_size[size][r["solver"]].append(_to_float(r["obj"]))

    sizes = sorted(by_size)
    gaps_grasp = []
    gaps_greedy = []
    for s in sizes:
        opt = by_size[s]["MILP"]
        gr  = by_size[s]["GRASP"]
        gd  = by_size[s]["Greedy"]
        g = [(g_i - m_i) / abs(m_i) * 100 for m_i, g_i in zip(opt, gr) if m_i not in (0, float("inf"))]
        d = [(g_i - m_i) / abs(m_i) * 100 for m_i, g_i in zip(opt, gd) if m_i not in (0, float("inf")) and g_i != float("inf")]
        gaps_grasp.append(mean(g) if g else 0)
        gaps_greedy.append(mean(d) if d else 0)

    x = range(len(sizes))
    w = 0.35
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar([i - w/2 for i in x], gaps_grasp, w, label="GRASP-LS", color="#1f77b4")
    ax.bar([i + w/2 for i in x], gaps_greedy, w, label="Greedy baseline", color="#d62728")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{s} items" for s in sizes])
    ax.set_ylabel("平均 optimality gap (%)")
    ax.set_title("不同隨機例題規模下的最佳化差距")
    ax.legend()
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
    ax.plot(sizes, milp_ms,  "o-", label="MILP (Gurobi)", color="#2ca02c")
    ax.plot(sizes, grasp_ms, "s-", label="GRASP-LS (proposed)", color="#1f77b4")
    ax.plot(sizes, greedy_ms, "^-", label="Greedy baseline", color="#d62728")
    ax.set_xlabel("商品數")
    ax.set_ylabel("平均 runtime (毫秒)")
    ax.set_title("Runtime 隨例題規模成長情形")
    ax.set_yscale("log")
    ax.legend()
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

    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.plot(betas, costs, "o-", color="#1f77b4", label="總花費 (NT$)")
    ax1.set_xlabel(r"蛋白質權重 $\beta$")
    ax1.set_ylabel("總花費 (NT$)", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax2 = ax1.twinx()
    ax2.plot(betas, pros, "s--", color="#d62728", label="總蛋白質 (g)")
    ax2.set_ylabel("總蛋白質 (g)", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    ax1.set_title(r"$\beta$ 變化下的成本-蛋白質權衡")
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
    # check whether the recent items {22, 42, 50} reappear
    repeats = []
    for r in gamma_rows:
        ids = set(int(x) for x in r["items"].split("|") if x)
        repeats.append(len({22, 42, 50} & ids))
    costs = [float(r["cost"]) for r in gamma_rows]

    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.bar(range(len(gammas)), repeats, color="#9467bd", alpha=0.7, label="重複出現次數")
    ax1.set_xticks(range(len(gammas)))
    ax1.set_xticklabels([str(g) for g in gammas])
    ax1.set_xlabel(r"歷史懲罰權重 $\gamma$")
    ax1.set_ylabel("近期商品再次出現次數", color="#9467bd")
    ax1.set_ylim(0, 3.5)
    ax2 = ax1.twinx()
    ax2.plot(range(len(gammas)), costs, "o-", color="#ff7f0e", label="總花費")
    ax2.set_ylabel("總花費 (NT$)", color="#ff7f0e")
    ax1.set_title(r"$\gamma$ 對推薦多樣性的影響")
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
    rates = [by_solver[s][0] / by_solver[s][1] * 100 for s in solvers]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(solvers, rates, color=["#2ca02c", "#1f77b4", "#d62728"])
    ax.set_ylabel("hard-feasible 比率 (%)")
    ax.set_title("真實情境下三種解法的可行性")
    ax.set_ylim(0, 110)
    for b, v in zip(bars, rates):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 2,
                f"{v:.0f}%", ha="center")
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

    fig, axes = plt.subplots(1, 4, figsize=(13, 3.4))
    for ax, vals, title, ref in zip(
            axes,
            [cals, pros, sods, costs],
            ["熱量 (kcal)", "蛋白質 (g)", "鈉 (mg)", "花費 (NT$)"],
            [targets["U1_male_cut-regular"][0], targets["U1_male_cut-regular"][1], 960, 120]):
        bars = ax.bar(solvers, vals, color=["#2ca02c", "#1f77b4", "#d62728"])
        ax.axhline(ref, ls="--", color="black", alpha=0.5)
        ax.set_title(title)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width()/2, b.get_height(),
                    f"{v:.0f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle("U1（男・減脂・正餐）下三種解法的營養與成本對比", y=1.02)
    plt.tight_layout()
    plt.savefig(FIG / "fig_real_breakdown.png", dpi=180, bbox_inches="tight")
    plt.close()


if __name__ == "__main__":
    fig_gap_by_size()
    fig_runtime_by_size()
    fig_beta_tradeoff()
    fig_gamma_diversity()
    fig_feasibility()
    fig_realworld_breakdown()
    print("Figures written to", FIG)
