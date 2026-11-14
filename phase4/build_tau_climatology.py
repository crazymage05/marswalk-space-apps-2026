"""Seasonal dust optical depth (tau) climatology at Gale from Curiosity's Mastcam solar-imaging record (W3).

Writes data/processed/roi/tables/tau_climatology.csv and demo/twin/tau_climatology.json. Run from the repo root.

Input: data/raw/gapfill/tau_mastcam/msl_tau_880.csv and msl_tau_440.csv (Lemmon et al., PDS4 review bundle; columns
product id, sol, Ls, tau, uncertainty; sols 33.5-3953.5, see provenance.json). The record ends about 550 sols before
the 2025 campaign (sols 4500-4799), so the campaign has NO measured tau: the twin uses the climatological median for the
season, labelled as such.

Method: Mars year from Ls wraps in sol order (sol 0 = MY 31). 36 bins of 10 deg Ls; per bin and wavelength the median,
25th and 75th percentile over all observations, and the number of Mars years seen. Lookup for any Ls: linear between bin
centres, circular in Ls. All Mars years are kept (median is robust); the MY34 global dust storm is reported separately.
"""
import sys, os, json, csv
sys.path.insert(0, os.getcwd())
import numpy as np
from phase4.world import ls_am

SRC = "data/raw/gapfill/tau_mastcam"

def load(wl):
    rows = [r for r in csv.reader(open(f"{SRC}/msl_tau_{wl}.csv")) if r and r[0].strip()]
    a = np.array([[float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in rows])
    a = a[np.argsort(a[:, 0])]
    my = 31 + np.concatenate([[0], np.cumsum(np.diff(a[:, 1]) < -180)])
    return {"sol": a[:, 0], "ls": a[:, 1], "tau": a[:, 2], "unc": a[:, 3], "my": my, "n_raw": len(rows)}

D = {wl: load(wl) for wl in (880, 440)}
for wl, d in D.items():
    bad = (~np.isfinite(d["tau"])) | (d["tau"] <= 0) | (d["tau"] > 10)
    print(f"{wl} nm: {d['n_raw']} rows, sols {d['sol'].min():.1f}-{d['sol'].max():.1f}, Mars years {sorted(set(d['my']))}, "
          f"tau {d['tau'].min():.3f}-{d['tau'].max():.3f}, rejected {bad.sum()}")
    for k in ("sol", "ls", "tau", "unc", "my"): d[k] = d[k][~bad]

edges = np.arange(0, 361, 10); cen = edges[:-1] + 5
tab = []
for b in range(36):
    row = {"ls_lo": int(edges[b]), "ls_hi": int(edges[b + 1]), "ls_centre": int(cen[b])}
    for wl, d in D.items():
        m = (d["ls"] >= edges[b]) & (d["ls"] < edges[b + 1]); t = d["tau"][m]
        row[f"n_{wl}"] = int(m.sum()); row[f"years_{wl}"] = len(set(d["my"][m]))
        row[f"median_{wl}"] = round(float(np.median(t)), 3) if m.any() else None
        row[f"p25_{wl}"] = round(float(np.percentile(t, 25)), 3) if m.any() else None
        row[f"p75_{wl}"] = round(float(np.percentile(t, 75)), 3) if m.any() else None
        if 180 <= edges[b] < 270:
            k = m & (d["my"] != 34)
            row[f"median_{wl}_noMY34"] = round(float(np.median(d["tau"][k])), 3) if k.any() else None
    tab.append(row)
assert all(r["median_880"] is not None for r in tab), "empty 880 nm bin"

# 440/880 ratio on near-simultaneous pairs
a, b = D[880], D[440]
j = np.searchsorted(b["sol"], a["sol"]).clip(1, len(b["sol"]) - 1)
j = np.where(np.abs(b["sol"][j - 1] - a["sol"]) < np.abs(b["sol"][j] - a["sol"]), j - 1, j)
pair = np.abs(b["sol"][j] - a["sol"]) < 0.05
ratio = float(np.median(b["tau"][j][pair] / a["tau"][pair]))
print(f"tau440/tau880 median {ratio:.3f} over {pair.sum()} pairs")

def lookup(ls, key="median_880"):
    v = np.array([r[key] for r in tab]); x = (ls - 5) % 360 / 10; i0 = int(np.floor(x)) % 36; f = x - np.floor(x)
    return float(v[i0] * (1 - f) + v[(i0 + 1) % 36] * f)

os.makedirs("data/processed/roi/tables", exist_ok=True)
out = "data/processed/roi/tables/tau_climatology.csv"
keys = list(dict.fromkeys(k for r in tab for k in r))
with open(out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(tab)
label = "climatological tau for this season (Mastcam, sols 33-3953), not a 2025 measurement"
json.dump({"ls_centre": [r["ls_centre"] for r in tab], "tau880": [r["median_880"] for r in tab], "tau440": [r["median_440"] for r in tab],
           "p25_880": [r["p25_880"] for r in tab], "p75_880": [r["p75_880"] for r in tab], "ratio_440_880": round(ratio, 3),
           "label": label, "source": "phase4/build_tau_climatology.py from data/raw/gapfill/tau_mastcam (Lemmon et al.)",
           "lookup": "linear between 10-deg bin centres, circular in Ls"}, open("demo/twin/tau_climatology.json", "w"))
print("saved", out, "and demo/twin/tau_climatology.json")
for sol in (4500, 4650, 4799):
    ls = ls_am(sol + 12 / 24 - 0.5)
    print(f"sol {sol}: Ls {ls:.1f}  tau880 {lookup(ls):.3f}  tau440 {lookup(ls, 'median_440'):.3f}  (bin {int(ls // 10) * 10}-{int(ls // 10) * 10 + 10})")
