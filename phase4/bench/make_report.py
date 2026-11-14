"""Aggregate results -> markdown tables (results/tables.md) and figures (docs/figures/planner_pareto.png, planner_paths.png)."""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
from scipy import stats
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from phase4.bench.core import ROOT, C, A
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
FIG = os.path.join(ROOT, "docs", "figures")
NAMES = dict(astar8="A* 8-conn (baseline)", astar16="A* 16-conn", lazy_theta="Lazy Theta*", astar8_smooth="A* 8-conn + string pulling")
ORDER = list(NAMES)
COL = dict(astar8="#444444", astar16="#1f77b4", lazy_theta="#d62728", astar8_smooth="#2ca02c")
rng = np.random.default_rng(0)


def load():
    d = json.load(open(os.path.join(RES, "bench_results.json"))); rows = d["rows"]
    by = {a: {r["scenario"]: r for r in rows if r["algo"] == a} for a in ORDER}
    scen = [s for s in by["astar8"] if all(s in by[a] for a in ORDER)]
    return d, by, scen


def ms(x): return f"{np.mean(x):.2f} / {np.median(x):.2f} / {np.std(x, ddof=1):.2f}"


def tables(d, by, scen):
    out = []
    mets = [("length_m", "Path length (m)", "{:.1f}"), ("cost", "Model cost (m-equiv)", "{:.0f}"), ("time_s", "Travel time (min)", "{:.2f}"),
            ("energy_kj", "Energy (kJ)", "{:.1f}"), ("max_slope_deg", "Max cell slope crossed (deg)", "{:.1f}"),
            ("turns_gt30", "Heading changes > 30 deg", "{:.1f}"), ("total_turn_deg", "Total turning (deg)", "{:.0f}"),
            ("runtime_ms", "Runtime (ms, median of 3)", "{:.0f}"), ("expanded", "Nodes expanded", "{:.0f}")]
    out.append("### Per-algorithm summary (21 scenarios; mean / median / sd)\n")
    out.append("| Metric | " + " | ".join(NAMES[a] for a in ORDER) + " |\n|---|" + "---|" * len(ORDER))
    for k, lab, f in mets:
        cells = []
        for a in ORDER:
            x = np.array([by[a][s][k] for s in scen], float)
            if k == "time_s": x = x / 60
            cells.append(f"{f.format(np.mean(x))} / {f.format(np.median(x))} / {f.format(np.std(x, ddof=1))}")
        out.append(f"| {lab} | " + " | ".join(cells) + " |")
    out.append("| Validator pass | " + " | ".join(f"{sum(by[a][s]['validator_ok'] for s in scen)}/{len(scen)}" for a in ORDER) + " |")
    out.append("| Own checker: samples in hard-blocked cells | " + " | ".join(str(sum(by[a][s]['hard_block_samples'] for s in scen)) for a in ORDER) + " |")
    out.append("\n### Paired differences against 8-connected A* (same 21 scenarios; negative = better except runtime)\n")
    out.append("| Algorithm | Metric | mean diff % | median % | sd % | min..max % | 95% bootstrap CI of mean | Wilcoxon p | scenarios better |\n|---|---|---|---|---|---|---|---|---|")
    for a in ORDER[1:]:
        for k, lab in [("length_m", "length"), ("cost", "model cost"), ("time_s", "travel time"), ("energy_kj", "energy"), ("runtime_ms", "runtime")]:
            b = np.array([by["astar8"][s][k] for s in scen], float); x = np.array([by[a][s][k] for s in scen], float)
            dp = 100 * (x - b) / b
            boots = [rng.choice(dp, len(dp)).mean() for _ in range(5000)]; lo, hi = np.percentile(boots, [2.5, 97.5])
            try: p = stats.wilcoxon(x, b).pvalue
            except ValueError: p = float("nan")
            out.append(f"| {NAMES[a]} | {lab} | {dp.mean():+.2f} | {np.median(dp):+.2f} | {dp.std(ddof=1):.2f} | {dp.min():+.2f}..{dp.max():+.2f} | [{lo:+.2f}, {hi:+.2f}] | {p:.2g} | {int((x < b - 1e-9).sum())}/{len(dp)} |")
    out.append("\n### Campaign scenario only\n")
    out.append("| Algorithm | length m | cost | time s | energy kJ | max slope | turns>30 | total turn deg | runtime ms | expanded | validator |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for a in ORDER:
        r = by[a]["campaign"]
        out.append(f"| {NAMES[a]} | {r['length_m']:.1f} | {r['cost']:.0f} | {r['time_s']:.0f} | {r['energy_kj']:.1f} | {r['max_slope_deg']:.1f} | {r['turns_gt30']} | {r['total_turn_deg']:.0f} | {r['runtime_ms']:.0f} | {r['expanded']} | {'pass' if r['validator_ok'] else 'FAIL'} |")
    # model cost ordering counts
    out.append("\n### Model-cost ties and ordering\n")
    for a in ORDER[1:]:
        x = np.array([by[a][s]["cost"] for s in scen]); b = np.array([by["astar8"][s]["cost"] for s in scen])
        out.append(f"- {NAMES[a]}: cost below A*8 in {(x < b - 1e-6).sum()}/{len(x)}, above in {(x > b + 1e-6).sum()}/{len(x)}")
    # scaling of runtime with expanded nodes
    out.append("\n### Runtime per 1000 expanded nodes (ms), median over scenarios\n")
    for a in ORDER:
        x = np.array([by[a][s]["runtime_ms"] / (by[a][s]["expanded"] / 1000) for s in scen]); out.append(f"- {NAMES[a]}: {np.median(x):.2f}")
    return "\n".join(out)


def fig_paths(by):
    g = C.load_grid(); W = g["width"]; prof = A.get_profile("nominal")
    blocked = C.hard_blocked(g, prof)
    verts = {a: [divmod(v, W) for v in by[a]["campaign"]["vertices"]] for a in ORDER}
    allp = np.array([p for a in ORDER for p in verts[a]]); r0, c0 = allp.min(0) - 12; r1, c1 = allp.max(0) + 12
    r0, c0 = max(0, r0), max(0, c0); r1, c1 = min(g["height"], r1), min(W, c1)
    z = np.nan_to_num(g["elevation_m"])[r0:r1, c0:c1]
    from matplotlib.colors import LightSource
    hs = LightSource(azdeg=315, altdeg=40).hillshade(z, vert_exag=2, dx=4.05, dy=4.05)
    fig, axs = plt.subplots(1, 2, figsize=(14, 7.2), gridspec_kw=dict(width_ratios=[1, 1]))
    for ax, zoom in zip(axs, [False, True]):
        ax.imshow(hs, cmap="gray", extent=(c0, c1, r1, r0), vmin=0, vmax=1)
        ov = np.zeros(blocked[r0:r1, c0:c1].shape + (4,)); ov[blocked[r0:r1, c0:c1]] = (0.85, 0.1, 0.1, 0.35)
        ax.imshow(ov, extent=(c0, c1, r1, r0))
        for a, lw in zip(ORDER, [2.6, 1.8, 1.8, 1.8]):
            p = np.array(verts[a]) + 0.5
            ax.plot(p[:, 1], p[:, 0], color=COL[a], lw=lw, label=f"{NAMES[a]}: {by[a]['campaign']['length_m']:.0f} m, {by[a]['campaign']['turns_gt30']} turns>30", alpha=0.95,
                    ls={"astar8": "-", "astar16": "--", "lazy_theta": "-", "astar8_smooth": ":"}[a])
        s, t = verts["astar8"][0], verts["astar8"][-1]
        ax.plot(s[1] + .5, s[0] + .5, "o", color="gold", mec="k", ms=9, zorder=5); ax.plot(t[1] + .5, t[0] + .5, "s", color="gold", mec="k", ms=9, zorder=5)
        if zoom:
            # zoom into the segment with the largest disagreement between A*8 and Lazy Theta*
            pa = np.array(verts["astar8"]) ; mid = pa[len(pa) // 2]
            ax.set_xlim(mid[1] - 45, mid[1] + 45); ax.set_ylim(mid[0] + 45, mid[0] - 45); ax.set_title("Zoom: about 360 m wide, mid-route (red = hard-blocked)")
        else:
            ax.set_xlim(c0, c1); ax.set_ylim(r1, r0); ax.set_title("Campaign scenario, nominal profile (red = hard-blocked cells, 25%)\ngold circle start, square goal")
        ax.set_xlabel("column (4.05 m cells)"); ax.set_ylabel("row")
    axs[0].legend(loc="lower left", fontsize=7.5, framealpha=0.92)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "planner_paths.png"), dpi=130); plt.close(fig)


def fig_pareto():
    p = json.load(open(os.path.join(RES, "pareto_results.json")))["points"]
    ws = [x for x in p if x["lam"] is not None]; oth = [x for x in p if x["lam"] is None]
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    T = np.array([x["time_nofatigue_s"] for x in ws]) / 60; R = np.array([x["risk_m"] for x in ws])
    ax.plot(T, R, "-o", color="#1f77b4", label="weighted-sum A* (8-conn), lambda sweep")
    for x, tt, rr in zip(ws, T, R): ax.annotate(f"{x['lam']:g}", (tt, rr), textcoords="offset points", xytext=(4, 5), fontsize=8)
    for x, c, m in zip(oth, ["#444444", "#d62728"], ["s", "^"]):
        ax.plot(x["time_nofatigue_s"] / 60, x["risk_m"], m, color=c, ms=9, label=x["label"])
    ax.set_xlabel("Travel time, no fatigue (min)"); ax.set_ylabel("Risk exposure (risk-metres: sum of length x cell risk)")
    ax.set_title("Time vs risk, campaign scenario (labels = lambda, weight on risk)"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, "planner_pareto.png"), dpi=140); plt.close(fig)


if __name__ == "__main__":
    d, by, scen = load()
    open(os.path.join(RES, "tables.md"), "w").write(tables(d, by, scen))
    fig_paths(by)
    if os.path.exists(os.path.join(RES, "pareto_results.json")): fig_pareto()
    print(open(os.path.join(RES, "tables.md")).read())
