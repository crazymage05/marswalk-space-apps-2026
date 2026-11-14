"""H1: anomaly detection on REMS campaign hourly data (single-point station at Curiosity).

Methods: "baseline" (robust z vs same LMST hour over previous N available sols) and
"chronos" (Chronos-Bolt zero-shot, one series per LMST hour over available sols, 1-step forecast).
Run:  python -m phase5.forecast --all
"""
import argparse, json, time, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HOURLY = ROOT / "data/processed/roi/tables/rems_rmd_campaign_hourly.csv"
DAILY = ROOT / "data/processed/roi/tables/rems_daily.csv"
OUT = ROOT / "data/processed/roi/hazards"
VARS = ["air_temp_C", "ground_temp_C", "pressure_Pa", "uv_abc_Wm2"]
# MAD floors so near-constant history (night UV, quiet pressure) does not give infinite z
MAD_FLOOR = {"air_temp_C": 1.0, "ground_temp_C": 1.5, "pressure_Pa": 3.0, "uv_abc_Wm2": 0.02}
UV_DAY_MIN = 0.05            # W/m2: UV only evaluated where expected daytime level exceeds this
N_HIST, MIN_HIST, MAX_SOL_GAP, Z_THR = 14, 5, 80, 3.5
CTX_LEN, BAND_WIDEN = 32, 1.645 / 1.2816   # Bolt gives q0.1/q0.9 only; widen to ~5-95% under Gaussian
MODEL_ID, SEED = "amazon/chronos-bolt-small", 20260101
HELD_OUT_SOLS = 60

_cache = {}


def load_hourly():
    d = pd.read_csv(HOURLY).sort_values(["lmst_hour", "sol"]).reset_index(drop=True)
    for v in ("air_temp_C", "ground_temp_C"):
        d.loc[d[v] < -150, v] = np.nan
    return d


def load_daily():
    d = pd.read_csv(DAILY)
    for c in ("min_temp", "max_temp", "min_gts_temp", "max_gts_temp"):
        d.loc[d[c] < -100, c] = np.nan
    return d


def coverage():
    d, dd = load_hourly(), load_daily()
    per = d.groupby("sol").size()
    gaps = np.diff(np.array(sorted(d.sol.unique())))
    c = {"rows": len(d), "sols": int(d.sol.nunique()), "sol_min": int(d.sol.min()), "sol_max": int(d.sol.max()),
         "span_sols": int(d.sol.max() - d.sol.min() + 1),
         "hours_per_sol_median": float(per.median()), "hours_per_sol_min": int(per.min()),
         "sols_with_24h": int((per == 24).sum()), "sol_gap_counts": {int(k): int(v) for k, v in pd.Series(gaps).value_counts().sort_index().items()},
         "rows_per_lmst_hour": {int(k): int(v) for k, v in d.lmst_hour.value_counts().sort_index().items()},
         "non_null": {v: int(d[v].notna().sum()) for v in VARS},
         "uv_daytime_rows(>0.05)": int((d.uv_abc_Wm2 > UV_DAY_MIN).sum())}
    dd2 = dd[(dd.sol >= 4500) & (dd.sol <= 4796)]
    c["daily_total_sols"] = len(dd)
    c["daily_valid_max_temp_sols"] = int(dd.max_temp.notna().sum())
    c["daily_valid_pressure_sols"] = int(dd.pressure.notna().sum())
    c["daily_rows_in_campaign_window"] = len(dd2)
    return c


# ---------------------------------------------------------------- baseline
def run_baseline(d, var, rows=None):
    """Return DataFrame indexed like d with expected, scale, z, flag, eligible for variable var."""
    n = len(d)
    out = pd.DataFrame({"expected": np.nan, "z": np.nan, "scale": np.nan, "eligible": False, "flag": False}, index=d.index)
    for h, g in d.groupby("lmst_hour"):
        sols, vals, idx = g.sol.values, g[var].values, g.index.values
        for k in range(len(g)):
            if rows is not None and idx[k] not in rows:
                continue
            if np.isnan(vals[k]):
                continue
            lo = k
            hist = []
            for j in range(k - 1, -1, -1):
                if sols[k] - sols[j] > MAX_SOL_GAP or len(hist) >= N_HIST:
                    break
                if not np.isnan(vals[j]):
                    hist.append(vals[j])
            if len(hist) < MIN_HIST:
                continue
            hist = np.array(hist)
            med = np.median(hist)
            mad = 1.4826 * np.median(np.abs(hist - med))
            sc = max(mad, MAD_FLOOR[var])
            if var == "uv_abc_Wm2":
                if med < UV_DAY_MIN:
                    continue
                sc = max(mad, 0.1 * med)
            z = (vals[k] - med) / sc
            out.loc[idx[k], ["expected", "scale", "z", "eligible"]] = [med, sc, z, True]
            out.loc[idx[k], "flag"] = abs(z) > Z_THR
    return out


# ---------------------------------------------------------------- chronos
def get_pipeline():
    if "pipe" not in _cache:
        import torch
        from chronos import BaseChronosPipeline
        from huggingface_hub import snapshot_download
        import chronos
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        t = time.time()
        try:
            pipe = BaseChronosPipeline.from_pretrained(MODEL_ID, device_map=dev, torch_dtype=torch.float32)
            torch.zeros(1, device=dev)
            pipe.predict_quantiles(inputs=[torch.arange(20, dtype=torch.float32)], prediction_length=1, quantile_levels=[0.1, 0.5, 0.9])
        except Exception as e:  # fall back to CPU
            print("mps failed, using cpu:", repr(e)[:200], file=sys.stderr)
            dev = "cpu"
            pipe = BaseChronosPipeline.from_pretrained(MODEL_ID, device_map="cpu", torch_dtype=torch.float32)
        rev = Path(snapshot_download(MODEL_ID)).name
        _cache["pipe"] = pipe
        _cache["meta"] = {"model": MODEL_ID, "model_revision": rev, "chronos_forecasting": getattr(chronos, "__version__", "2.3.2"),
                          "device": dev, "load_seconds": round(time.time() - t, 2)}
    return _cache["pipe"], _cache["meta"]


def run_chronos(d, var, rows=None):
    import torch
    pipe, _ = get_pipeline()
    out = pd.DataFrame({"expected": np.nan, "lo": np.nan, "hi": np.nan, "eligible": False, "flag": False}, index=d.index)
    ctxs, tgt = [], []
    for h, g in d.groupby("lmst_hour"):
        sols, vals, idx = g.sol.values, g[var].values, g.index.values
        for k in range(len(g)):
            if rows is not None and idx[k] not in rows:
                continue
            if np.isnan(vals[k]):
                continue
            hist = []
            for j in range(k - 1, -1, -1):
                if sols[k] - sols[j] > MAX_SOL_GAP or len(hist) >= CTX_LEN:
                    break
                if not np.isnan(vals[j]):
                    hist.append(vals[j])
            if len(hist) < MIN_HIST:
                continue
            hist = hist[::-1]
            if var == "uv_abc_Wm2" and np.median(hist[-N_HIST:]) < UV_DAY_MIN:
                continue
            ctxs.append(torch.tensor(hist, dtype=torch.float32))
            tgt.append((idx[k], vals[k]))
    if not ctxs:
        return out
    qs = []
    for b in range(0, len(ctxs), 256):
        q, _ = pipe.predict_quantiles(inputs=ctxs[b:b + 256], prediction_length=1, quantile_levels=[0.1, 0.5, 0.9])
        qs.append(q[:, 0, :].float().cpu().numpy())
    q = np.concatenate(qs)
    for (i, v), (q10, q50, q90) in zip(tgt, q):
        lo, hi = q50 - BAND_WIDEN * (q50 - q10), q50 + BAND_WIDEN * (q90 - q50)
        out.loc[i, ["expected", "lo", "hi", "eligible"]] = [q50, lo, hi, True]
        out.loc[i, "flag"] = bool(v < lo or v > hi)
    return out


def run_detrended(d, var, rows=None):
    """Theil-Sen linear trend in sol over previous N same-hour obs; z of value vs prediction."""
    from scipy.stats import theilslopes
    out = pd.DataFrame({"expected": np.nan, "z": np.nan, "scale": np.nan, "eligible": False, "flag": False}, index=d.index)
    for h, g in d.groupby("lmst_hour"):
        sols, vals, idx = g.sol.values, g[var].values, g.index.values
        for k in range(len(g)):
            if (rows is not None and idx[k] not in rows) or np.isnan(vals[k]):
                continue
            hs, hv = [], []
            for j in range(k - 1, -1, -1):
                if sols[k] - sols[j] > MAX_SOL_GAP or len(hv) >= N_HIST:
                    break
                if not np.isnan(vals[j]):
                    hs.append(sols[j]); hv.append(vals[j])
            if len(hv) < MIN_HIST:
                continue
            hs, hv = np.array(hs, float), np.array(hv)
            if var == "uv_abc_Wm2" and np.median(hv) < UV_DAY_MIN:
                continue
            sl, ic, _, _ = theilslopes(hv, hs)
            pred = ic + sl * sols[k]
            res = hv - (ic + sl * hs)
            sc = max(1.4826 * np.median(np.abs(res - np.median(res))), MAD_FLOOR[var])
            if var == "uv_abc_Wm2":
                sc = max(sc, 0.1 * abs(np.median(hv)))
            z = (vals[k] - pred) / sc
            out.loc[idx[k], ["expected", "scale", "z", "eligible"]] = [pred, sc, z, True]
            out.loc[idx[k], "flag"] = abs(z) > Z_THR
    return out


def pressure_drift():
    """Measured drift of same-hour series: Theil-Sen slope per hour (whole campaign) and over 14-obs windows."""
    from scipy.stats import theilslopes
    d = load_hourly(); per_hour, win = [], []
    for v in ("pressure_Pa", "air_temp_C", "ground_temp_C"):
        ph, wd, ws = [], [], []
        for h, g in d.groupby("lmst_hour"):
            s, x = g.sol.values.astype(float), g[v].values
            m = ~np.isnan(x); s, x = s[m], x[m]
            ph.append(theilslopes(x, s)[0])
            for k in range(N_HIST, len(s) + 1):
                sl = theilslopes(x[k - N_HIST:k], s[k - N_HIST:k])[0]
                wd.append(abs(sl) * (s[k - 1] - s[k - N_HIST])); ws.append(abs(sl))
        out = {"median_abs_slope_per_sol_whole_campaign": float(np.median(np.abs(ph))),
               "median_abs_window_slope_per_sol": float(np.median(ws)),
               "median_abs_drift_over_14obs_window": float(np.median(wd)), "p90_abs_drift_over_14obs_window": float(np.percentile(wd, 90))}
        per_hour.append((v, out))
    r = dict(per_hour)
    sp = [g.sol.values[N_HIST - 1:] - g.sol.values[:len(g) - N_HIST + 1] for _, g in d.groupby("lmst_hour")]
    r["median_sol_span_of_14_obs"] = float(np.median(np.concatenate(sp)))
    return r


ZM = ("baseline", "detrended")
RUNNERS = {"baseline": run_baseline, "chronos": run_chronos, "detrended": run_detrended}


# ---------------------------------------------------------------- API
def _explain(method, var, val, exp, z, lo, hi, flag):
    if method in ZM:
        return f"{var}={val:.3g} vs same-LMST-hour median {exp:.3g} over previous <= {N_HIST} sols: robust z={z:+.1f} ({'>' if flag else '<='} {Z_THR})"
    return f"{var}={val:.3g} vs Chronos-Bolt forecast median {exp:.3g}, ~90% band [{lo:.3g}, {hi:.3g}]: {'outside' if flag else 'inside'}"


def _prov(method):
    p = {"input_file": str(HOURLY.relative_to(ROOT)), "method": method, "caveat": "single-point REMS station at Curiosity, not an area-wide field"}
    if method in ZM:
        p.update(N=N_HIST, min_count=MIN_HIST, z_threshold=Z_THR, mad_floor=MAD_FLOOR, max_sol_gap=MAX_SOL_GAP)
    else:
        p.update(get_pipeline()[1]); p.update(context_len=CTX_LEN, band="q0.1/q0.9 widened x%.3f to ~5-95%%" % BAND_WIDEN, min_count=MIN_HIST)
    return p


def _eval_rows(d, method, rows=None, variables=VARS):
    res = {v: RUNNERS[method](d, v, rows) for v in variables}
    return res


def _records(d, res, method, sel, only_flagged):
    recs = []
    for i in sel:
        sol, hr = int(d.at[i, "sol"]), int(d.at[i, "lmst_hour"])
        items = []
        for v, r in res.items():
            if not r.at[i, "eligible"]:
                continue
            val, exp, flag = float(d.at[i, v]), float(r.at[i, "expected"]), bool(r.at[i, "flag"])
            z = float(r.at[i, "z"]) if method in ZM else float((val - exp) / max(r.at[i, "hi"] - r.at[i, "lo"], 1e-9) * 2 * 1.645)
            lo = None if method in ZM else float(r.at[i, "lo"]); hi = None if method in ZM else float(r.at[i, "hi"])
            it = {"anomaly": flag, "sol": sol, "lmst_hour": hr, "variable": v, "value": val, "expected": exp, "method": method}
            if method in ZM:
                it["z"] = z
            else:
                it["band"] = [lo, hi]
            it["explanation"] = _explain(method, v, val, exp, z, lo, hi, flag)
            items.append((abs(z), it))
        if not items:
            continue
        if only_flagged and not any(it["anomaly"] for _, it in items):
            continue
        fl = [x for x in items if x[1]["anomaly"]] or items
        best = max(fl, key=lambda x: x[0])[1]
        best = dict(best); best["details"] = [it for _, it in items]
        recs.append(best)
    return recs


def detect(sol, lmst_hour, method="baseline"):
    """Anomaly check of one (sol, lmst_hour) campaign row. History = earlier rows only."""
    d = _cache.setdefault("d", load_hourly())
    m = d[(d.sol == sol) & (d.lmst_hour == lmst_hour)]
    if m.empty:
        return {"anomaly": False, "variable": None, "value": None, "expected": None, "method": method,
                "explanation": f"no observation at sol {sol} LMST hour {lmst_hour} in the campaign table"}
    i = m.index[0]
    key = ("res", method)
    if key not in _cache:  # full-table pass is cheap and reused
        _cache[key] = _eval_rows(d, method)
    recs = _records(d, _cache[key], method, [i], False)
    if not recs:
        return {"anomaly": False, "variable": None, "value": None, "expected": None, "method": method,
                "explanation": "insufficient history (< %d prior same-hour observations) or UV night hour" % MIN_HIST}
    return recs[0]


def scan(sol_min, sol_max, method="baseline", out=None):
    d = _cache.setdefault("d", load_hourly())
    res = _eval_rows(d, method)
    sel = d[(d.sol >= sol_min) & (d.sol <= sol_max)].sort_values(["sol", "lmst_hour"]).index
    recs = _records(d, res, method, sel, True)
    prov = _prov(method); prov.update(seed=SEED, sol_range=[int(sol_min), int(sol_max)], rows_scanned=len(sel))
    for r in recs:
        r["provenance"] = prov
    out = Path(out or OUT / f"anomalies_{method}.json"); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recs, indent=1))
    out.with_name(out.stem + "_meta.json").write_text(json.dumps(prov, indent=1))
    return recs


# ---------------------------------------------------------------- evaluation
def make_heldout(seed=SEED, per_var=8):
    d = load_hourly()
    cut = d.sol.max() - HELD_OUT_SOLS
    rng = np.random.default_rng(seed)
    inj = []
    for v in VARS:
        cand = d[(d.sol > cut) & d[v].notna()]
        if v == "uv_abc_Wm2":
            cand = cand[cand[v] > 1.0]    # clearly daytime
        pick = rng.choice(cand.index.values, size=per_var, replace=False)
        for i in pick:
            sgn = rng.choice([-1, 1]); jit = rng.uniform(0.75, 1.25)
            if v == "air_temp_C": new = d.at[i, v] + sgn * 8 * jit
            elif v == "ground_temp_C": new = d.at[i, v] + sgn * 10 * jit
            elif v == "pressure_Pa": new = d.at[i, v] + sgn * 15 * jit
            else: new = d.at[i, v] * (0.5 if sgn < 0 else 1.6)
            inj.append((i, v, float(d.at[i, v]), float(new)))
    dm = d.copy()
    for i, v, old, new in inj:
        dm.at[i, v] = new
    return dm, inj, cut


def evaluate(method, dm, inj, cut):
    test = set(dm.index[dm.sol > cut])
    t0 = time.time()
    res = _eval_rows(dm, method, rows=test)
    run_t = time.time() - t0
    injset = {(i, v) for i, v, _, _ in inj}
    rows = []
    for v in VARS:
        r = res[v]
        el = r[r.eligible & r.index.isin(test)]
        isinj = np.array([(i, v) in injset for i in el.index])
        fl = el.flag.values.astype(bool)
        tp = int((fl & isinj).sum()); fp = int((fl & ~isinj).sum()); fn = int((~fl & isinj).sum())
        P = tp / (tp + fp) if tp + fp else 0.0; R = tp / (tp + fn) if tp + fn else 0.0
        F = 2 * P * R / (P + R) if P + R else 0.0
        rows.append({"method": method, "variable": v, "n_eval": len(el), "n_injected": int(isinj.sum()), "tp": tp, "fp": fp, "fn": fn,
                     "precision": round(P, 3), "recall": round(R, 3), "f1": round(F, 3),
                     "false_positive_rate": round(fp / max(int((~isinj).sum()), 1), 4)})
    return rows, run_t


def run_all():
    OUT.mkdir(parents=True, exist_ok=True)
    cov = coverage(); (OUT / "h1_coverage.json").write_text(json.dumps(cov, indent=1))
    print("coverage:", json.dumps({k: v for k, v in cov.items() if k not in ("rows_per_lmst_hour",)}))
    dm, inj, cut = make_heldout()
    (OUT / "h1_injected.json").write_text(json.dumps([{"row": int(i), "sol": int(dm.at[i, "sol"]), "lmst_hour": int(dm.at[i, "lmst_hour"]), "variable": v, "original": o, "injected": n} for i, v, o, n in inj], indent=1))
    all_rows, timing = [], {}
    # model load (excluded from method time) measured separately
    t = time.time(); _, meta = get_pipeline(); load_t = time.time() - t
    for method in ("baseline", "chronos", "detrended"):
        t0 = time.time()
        rows, run_t = evaluate(method, dm, inj, cut)
        timing[method] = {"eval_seconds_excl_load": round(run_t, 2)}
        all_rows += rows
    timing["chronos"]["model_load_seconds"] = meta["load_seconds"]
    timing["chronos"]["eval_seconds_incl_load"] = round(timing["chronos"]["eval_seconds_excl_load"] + meta["load_seconds"], 2)
    for m in ("baseline", "detrended"): timing[m]["eval_seconds_incl_load"] = timing[m]["eval_seconds_excl_load"]
    drift = pressure_drift(); (OUT / "h1_drift.json").write_text(json.dumps(drift, indent=1)); print("drift:", json.dumps(drift))
    # full scans for H2
    d0 = load_hourly()
    for method in ("baseline", "chronos", "detrended"):
        t0 = time.time(); recs = scan(int(d0.sol.min()), int(d0.sol.max()), method)
        timing[method]["full_scan_seconds"] = round(time.time() - t0, 2); timing[method]["n_anomalies_clean_data"] = len(recs)
    cmp = pd.DataFrame(all_rows)
    cmp["held_out_from_sol"] = int(cut) + 1; cmp["seed"] = SEED
    cmp.to_csv(OUT / "h1_comparison.csv", index=False)
    (OUT / "h1_timing.json").write_text(json.dumps({"timing": timing, "chronos_meta": meta}, indent=1))
    print(cmp.drop(columns=["held_out_from_sol", "seed"]).to_string(index=False))
    print("timing:", json.dumps(timing)); print("chronos:", json.dumps(meta))
    # end-to-end API check
    r = detect(int(d0.sol.iloc[-1]), int(d0.lmst_hour.iloc[-1]), "baseline"); print("detect demo:", r["explanation"] if r else r)
    return cmp


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.all: run_all()
    else: ap.print_help()
