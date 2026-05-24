"""Generate LaTeX-ready summary tables from the experiment CSVs."""
import csv
from pathlib import Path
from collections import defaultdict
from statistics import mean

ROOT = Path(__file__).parent.parent
RES = ROOT / "results"


def fnum(s, fmt=".2f"):
    if s in ("", "inf"): return "--"
    try: return f"{float(s):{fmt}}"
    except: return s


def full_real_table():
    rows = list(csv.DictReader(open(RES / "real_world.csv", encoding="utf-8")))
    by_inst = defaultdict(dict)
    for r in rows:
        by_inst[r["instance"]][r["solver"]] = r

    out = []
    out.append(r"\begin{tabular}{lrrrrrrrrr}")
    out.append(r"\toprule")
    out.append(r"Instance & Cal range & $P^{min}$ & "
               r"MILP & GRASP & Gap & MILP & GRASP & Greedy \\")
    out.append(r"        & (kcal)    & (g)       & "
               r"obj  & obj   & (\%) & feas & feas  & feas   \\")
    out.append(r"\midrule")

    grasp_gaps = []
    for inst in sorted(by_inst):
        m  = by_inst[inst].get("MILP", {})
        g  = by_inst[inst].get("GRASP", {})
        gr = by_inst[inst].get("Greedy", {})
        if not m: continue
        cal_min = float(m["cal_min"])
        suffix = inst.split("-")[-1]
        ratio_map = {"light": 0.25/0.15, "regular": 0.45/0.30, "latenight": 0.15/0.05}
        cal_max = cal_min * ratio_map.get(suffix, 1.5)
        cal_range = f"{cal_min:.0f}--{cal_max:.0f}"
        m_obj = float(m["obj"]) if m["obj"] not in ("", "inf") else None
        g_obj = float(g["obj"]) if g["obj"] not in ("", "inf") else None
        gap = ""
        if m_obj is not None and g_obj is not None and abs(m_obj) > 1e-6:
            gap_v = (g_obj - m_obj) / abs(m_obj) * 100
            grasp_gaps.append(gap_v)
            gap = f"{gap_v:.1f}"
        label = inst.replace("_", r"\_")
        out.append(f"{label} & {cal_range} & {float(m['pro_min']):.1f} & "
                   f"{fnum(m['obj'])} & {fnum(g['obj'])} & {gap} & "
                   f"{'Y' if m.get('feasible')=='1' else 'N'} & "
                   f"{'Y' if g.get('feasible')=='1' else 'N'} & "
                   f"{'Y' if gr.get('feasible')=='1' else 'N'} \\\\")
    out.append(r"\bottomrule")
    out.append(r"\end{tabular}")

    avg_gap = mean(grasp_gaps) if grasp_gaps else 0
    print(f"avg GRASP gap = {avg_gap:.2f}% over {len(grasp_gaps)} instances")
    return "\n".join(out)


def random_summary_table():
    rows = list(csv.DictReader(open(RES / "random.csv", encoding="utf-8")))
    by_size = defaultdict(lambda: {"MILP": [], "GRASP": [], "Greedy": []})
    by_size_total = defaultdict(lambda: defaultdict(int))
    for r in rows:
        size = int(r["instance"].split("_")[1].rstrip("p"))
        by_size_total[size][r["solver"]] += 1
        if r["feasible"] == "1" and r["obj"] not in ("", "inf"):
            by_size[size][r["solver"]].append((float(r["obj"]), float(r["runtime"]),
                                              r["feasible"] == "1"))

    out = []
    out.append(r"\begin{tabular}{rrrrrrrrr}")
    out.append(r"\toprule")
    out.append(r"$|I|$ & $|K|$ & \multicolumn{2}{c}{MILP} & "
               r"\multicolumn{3}{c}{GRASP-LS} & \multicolumn{2}{c}{Greedy} \\")
    out.append(r"      &       & obj & time (s) & obj & gap (\%) & time (s) & feas & gap (\%) \\")
    out.append(r"\midrule")

    for size in sorted(by_size):
        milp = by_size[size]["MILP"]
        grasp = by_size[size]["GRASP"]
        greedy = by_size[size]["Greedy"]
        if not milp: continue

        m_obj = mean([x[0] for x in milp])
        m_rt  = mean([x[1] for x in milp])
        g_obj = mean([x[0] for x in grasp]) if grasp else float("nan")
        g_rt  = mean([x[1] for x in grasp]) if grasp else float("nan")
        gd_obj = mean([x[0] for x in greedy]) if greedy else float("nan")
        gd_total = by_size_total[size]["Greedy"]
        gd_feas = (len(greedy) / gd_total * 100) if gd_total else 0

        gap_g = (g_obj - m_obj) / abs(m_obj) * 100
        gap_gd_val = (gd_obj - m_obj) / abs(m_obj) * 100 if greedy else None
        gap_gd_str = f"{gap_gd_val:.0f}" if gap_gd_val is not None else "--"

        Kmap = {30:8, 50:15, 80:25, 120:35, 200:60, 300:90}
        out.append(f"{size} & {Kmap.get(size,'?')} & "
                   f"{m_obj:.1f} & {m_rt:.3f} & "
                   f"{g_obj:.1f} & {gap_g:.1f} & {g_rt:.3f} & "
                   f"{gd_feas:.0f}\\% & {gap_gd_str} \\\\")
    out.append(r"\bottomrule")
    out.append(r"\end{tabular}")
    return "\n".join(out)


if __name__ == "__main__":
    Path(RES / "tables").mkdir(exist_ok=True)
    (RES / "tables" / "real_full.tex").write_text(full_real_table(), encoding="utf-8")
    (RES / "tables" / "random_summary.tex").write_text(random_summary_table(), encoding="utf-8")
    print("Tables written to", RES / "tables")
