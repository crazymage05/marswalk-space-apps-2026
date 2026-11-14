#!/usr/bin/env python3
"""Calibrate the two ground-temperature coefficients and validate the world model (docs/world_model.md).
Writes data/processed/roi/world/world_params.json, world_validation.json and docs/figures/world_*.png.
    python phase4/validate_world.py
Light: a few dozen 4 m map evaluations, no loops over cells except 300 random cells for the horizon spot-check."""
import csv, datetime as dt, json, math, os, sys
import numpy as np, rasterio
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from phase4 import world as wm, themis_match as tm
FIG = os.path.join(ROOT, "docs", "figures"); os.makedirs(FIG, exist_ok=True)
V = {}

# ----------------------------------------------------------------- parameters not fitted: physics
SIGMA = 5.670374e-8
ALBEDO, EMISS, TI = 0.25, 0.95, 350.0      # assumptions: Gale dusty-rock albedo ~0.2-0.25; thermal inertia ~300-400 tiu (J m-2 K-1 s-1/2)
omega = 2 * math.pi / 88775.244
T_REF = 250.0
A_COEF = (1 - ALBEDO) / (4 * EMISS * SIGMA * T_REF ** 3 + TI * math.sqrt(omega))   # K per W/m2, harmonic response of a half-space
base_params = dict(tau=wm.TAU_DEFAULT, albedo=ALBEDO, a_K_per_Wm2=round(A_COEF, 4), kappa_K_per_K=0.0, airmass_cap=10.0, cme_window_days=0)
json.dump({"params": base_params}, open(os.path.join(wm.WORLD, "world_params.json"), "w"))
w = wm.World.load(); S = w.S

# ----------------------------------------------------------------- THEMIS: images inside the REMS window
ims = [i for i in tm.themis_images() if i["utc"] is not None and 4500 <= wm.utc_to_sol_lmst(i["utc"])[0] <= 4796]
dawn = []
for f in ("themis_day_bt_k", "themis_night_bt_k"):
    ds = rasterio.open(os.path.join(wm.ROI, f + ".tif"))
    for b, n in enumerate(ds.descriptions, 1):
        if float(n.split("LST")[1]) < 9:
            a = ds.read(b).astype(float); a[a <= 0] = np.nan
            if np.isfinite(a).mean() > .8: dawn.append((n.split("_")[0], (a - np.nanmean(a)) / np.nanstd(a)))
win = {i["id"] for i in ims}
z_loo = np.nanmedian(np.stack([z for n, z in dawn if n not in win]), axis=0)     # dawn warmth from the 9 images NOT in the REMS window
cell = lambda a: a[np.ix_(np.minimum(((np.arange(732) + .5) / 732 * a.shape[0]).astype(int), a.shape[0] - 1), np.minimum(((np.arange(585) + .5) / 585 * a.shape[1]).astype(int), a.shape[1] - 1))]
zcell = cell(z_loo)
V["themis"] = {"n_dawn_images_total": len(dawn), "n_used_for_z_loo": len(dawn) - sum(n in win for n, _ in dawn)}


def image_terms(im, lm_shift=0.0):
    sol, _ = wm.utc_to_sol_lmst(im["utc"]); ls = w.ls_of_sol(sol, im["ltst"])
    lm = im["ltst"] - float(wm.eot_hours(ls)) + lm_shift
    d = w.dynamic(sol, lm)
    return dict(id=im["id"], date=im["date"], sol=sol, lmst=lm, ltst=im["ltst"], sun_el=d["sun_el"], base=d["ground_temp_baseline_K"], wave=d["ground_temp_baseline_K"] - w.rems_daymean_ground(sol),
                dS=tm.block25(d["insolation"] - d["insolation_flat"]), Z=tm.block25(-zcell), shadow=tm.block25(d["in_shadow"].astype(float)),
                bt=im["bt"][:29, :23], gap=d["rems_gap_sols"])


T = [image_terms(i) for i in ims]
dawn_T = [t for t in T if t["ltst"] < 9]; dusk_T = [t for t in T if t["ltst"] > 15]
def fit_kappa(sub):
    x = np.concatenate([((t["Z"] - np.nanmean(t["Z"])) * t["wave"])[np.isfinite(t["bt"])].ravel() for t in sub])
    y = np.concatenate([(t["bt"] - np.nanmean(t["bt"]))[np.isfinite(t["bt"])].ravel() for t in sub])
    return float(x @ y / (x @ x))
kappa = fit_kappa(dawn_T)
loo = {}
for k, t in enumerate(dawn_T):                      # leave one dawn image out: fit on the other two, test on the held-out one
    kk = fit_kappa([u for j, u in enumerate(dawn_T) if j != k]); pred = kk * (t["Z"] - np.nanmean(t["Z"])) * t["wave"]; obs = t["bt"] - np.nanmean(t["bt"]); g = np.isfinite(obs)
    loo[t["id"]] = dict(kappa_fit_on_others=round(kk, 4), pattern_rmse_K=round(float(np.sqrt(np.mean((pred - obs)[g] ** 2))), 3), pattern_rmse_no_term_K=round(float(np.sqrt(np.mean(obs[g] ** 2))), 3))
base_params["kappa_K_per_K"] = round(kappa, 4)
json.dump({"params": base_params, "fit": {"kappa": "pooled least squares of demeaned THEMIS dawn BT on (-z_loo)*REMS diurnal departure, 3 dawn images in the REMS window, z_loo from the other 9 images",
                                             "a_K_per_Wm2": "physical: (1-albedo)/(4 eps sigma T^3 + TI sqrt(omega)), not fitted (THEMIS cannot constrain it, see docs)",
                                             "albedo": ALBEDO, "emissivity": EMISS, "thermal_inertia_tiu": TI, "T_ref_K": T_REF, "tau": "assumed 0.6, no tau series in the data"}},
          open(os.path.join(wm.WORLD, "world_params.json"), "w"), indent=1)
w = wm.World.load(); S = w.S
V["params"] = base_params; V["kappa_loo"] = loo

# ----------------------------------------------------------------- validation 3b: THEMIS brightness temperature vs modelled ground temperature
def themis_stats(shift=0.0, use_term=True):
    rows = []
    for im in ims:
        t = image_terms(im, shift); sol = t["sol"]; d = w.dynamic(sol, t["lmst"])
        model = tm.block25(d["ground_temp_K"]) if use_term else tm.block25(d["ground_temp_K"] - w.p["kappa_K_per_K"] * (-np.nan_to_num(S["dawn_warmth_z"])) * t["wave"])
        # replace the world's z (all 12 images, circular) by z_loo for an honest test
        model = t["base"] + w.p["a_K_per_Wm2"] * t["dS"] + (w.p["kappa_K_per_K"] * t["Z"] * t["wave"] if use_term else 0.0)
        obs = t["bt"]; g = np.isfinite(obs) & np.isfinite(model); e = (model - obs)[g]
        pe = (model - np.nanmean(model[g])) - (obs - np.nanmean(obs[g])); pe = pe[g]
        rows.append(dict(id=t["id"], date=t["date"], sol=t["sol"], lmst=round(t["lmst"], 2), kind="dawn" if t["ltst"] < 9 else "dusk", sun_el=round(t["sun_el"], 1), rems_baseline_K=round(t["base"], 1),
                         themis_mean_K=round(float(obs[g].mean()), 1), model_mean_K=round(float(model[g].mean()), 1), bias_K=round(float(e.mean()), 2), rmse_K=round(float(np.sqrt((e ** 2).mean())), 2),
                         pattern_rmse_K=round(float(np.sqrt((pe ** 2).mean())), 2), pattern_corr=round(float(np.corrcoef(model[g], obs[g])[0, 1]), 2) if model[g].std() > 1e-6 else None, n=int(g.sum()),
                         rems_gap_sols=t["gap"]))
    return rows
V["themis"]["per_image"] = themis_stats(0.0, True)
V["themis"]["per_image_without_dawn_term"] = themis_stats(0.0, False)
V["themis"]["timing_sensitivity"] = {str(s): [(r["id"], r["bias_K"]) for r in themis_stats(s, True)] for s in (-0.5, 0.5)}
for kind in ("dawn", "dusk"):
    r = [x for x in V["themis"]["per_image"] if x["kind"] == kind]
    V["themis"][kind + "_mean_bias_K"] = round(float(np.mean([x["bias_K"] for x in r])), 2); V["themis"][kind + "_mean_rmse_K"] = round(float(np.mean([x["rmse_K"] for x in r])), 2)

# ----------------------------------------------------------------- time and sun checks
daily = list(csv.DictReader(open(os.path.join(wm.ROI, "tables", "rems_daily.csv"))))
camp = [r for r in daily if 4500 <= int(r["sol"]) <= 4800 and r["ls"]]
hm = lambda s: int(s[:2]) + int(s[3:5]) / 60
sols = np.array([int(r["sol"]) for r in camp]); rl = np.array([float(r["ls"]) for r in camp]); sr = np.array([hm(r["sunrise"]) for r in camp]); ss = np.array([hm(r["sunset"]) for r in camp])
am = np.array([wm.ls_am(s - 0.5) for s in sols]); am_mid = np.array([w.ls_of_sol(s, 12.0) for s in sols])
V["ls"] = dict(rems_integer_equals_floor_of_model_at_sol_start_pct=round(float((np.floor(am) == rl).mean() * 100), 1), rems_minus_model_midsol_mean_deg=round(float((rl - am_mid).mean()), 2),
               rems_minus_model_midsol_sd=round(float((rl - am_mid).std()), 2))
def sun_times(ls, eot):
    dec = np.arcsin(math.sin(math.radians(wm.OBLIQ_DEG)) * np.sin(np.radians(ls))); lat = math.radians(wm.LAT_DEG)
    H = np.degrees(np.arccos(-math.tan(lat) * np.tan(dec))) / 15
    e = wm.eot_hours(ls) if eot else 0.0
    return 12 - H - e, 12 + H - e
ls_mid = np.array([w.ls_of_sol(s, 6.0) for s in sols])
for tag, (a, b) in {"with_eot": sun_times(ls_mid, True), "twin_formula_no_eot": sun_times(ls_mid, False)}.items():
    V.setdefault("sunrise_vs_rems", {})[tag] = dict(sunrise_bias_min=round(float((a - sr).mean() * 60), 1), sunrise_sd_min=round(float((a - sr).std() * 60), 1), sunrise_max_abs_min=round(float(np.abs(a - sr).max() * 60), 1),
                                                    sunset_bias_min=round(float((b - ss).mean() * 60), 1), sunset_sd_min=round(float((b - ss).std() * 60), 1), sunset_max_abs_min=round(float(np.abs(b - ss).max() * 60), 1))
V["eot_range_hours_in_campaign"] = [round(float(wm.eot_hours(ls_mid).min()), 3), round(float(wm.eot_hours(ls_mid).max()), 3)]
# twin formula, written literally from twin.html sunDir() (integer Ls from walk.json), against world.sun_position(eot=False)
wj = json.load(open(os.path.join(ROOT, "demo", "twin", "walk.json"))); twin_ls = {int(k): v for k, v in wj["ls"].items()}
def twin_sun(ls, lmst, lat):
    ls, lat = math.radians(ls), math.radians(lat); dec = math.asin(math.sin(math.radians(25.19)) * math.sin(ls)); ha = (lmst - 12) * 15 * math.pi / 180
    el = math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha) * math.cos(dec), math.cos(lat) * math.sin(dec) - math.sin(lat) * math.cos(dec) * math.cos(ha))
    return math.degrees(el), (math.degrees(az) + 360) % 360
d_noeot, d_eot, d_tls = [], [], []
for sol in range(4500, 4800, 25):
    for lm in (6.5, 9, 12, 15, 17.5):
        tl = twin_ls.get(sol, None)
        if tl is None: continue
        e0, a0 = twin_sun(wj["ls"][str(sol)], lm, wj["lat"]); e1, a1 = wm.sun_position(wj["ls"][str(sol)], lm, wj["lat"], eot=False)
        d_noeot.append((abs(e0 - e1), abs(((a0 - a1 + 180) % 360) - 180)))
        e2, a2 = wm.sun_position(w.ls_of_sol(sol, lm), lm, eot=True); d_eot.append((abs(e0 - e2), abs(((a0 - a2 + 180) % 360) - 180) if e0 < 60 else 0.0, e2))
V["sun_vs_twin"] = dict(twin_ls_integers_minus_model_mean_deg=round(float(np.mean([twin_ls[s] - w.ls_of_sol(s, 12.0) for s in twin_ls if 4500 <= s <= 4800])), 2),
                        no_eot_max_el_diff_deg=float(np.max(np.array(d_noeot)[:, 0])), no_eot_max_az_diff_deg=float(np.max(np.array(d_noeot)[:, 1])),
                        with_eot_and_model_ls_max_el_diff_deg=round(float(np.max(np.array(d_eot)[:, 0])), 2), with_eot_and_model_ls_max_az_diff_deg=round(float(np.max(np.array(d_eot)[:, 1])), 2),
                        with_eot_median_el_diff_deg=round(float(np.median(np.array(d_eot)[:, 0])), 2))
# sol -> Earth date
for conv, lmst in (("start of sol (LMST 0)", 0.0), ("local noon (LMST 12)", 12.0), ("LMST 6", 6.0)):
    pred = [w.utc_date(int(r["sol"]), lmst) for r in daily if r["terrestrial_date"]]; obs = [r["terrestrial_date"] for r in daily if r["terrestrial_date"]]
    diff = np.array([(dt.date.fromisoformat(p) - dt.date.fromisoformat(o)).days for p, o in zip(pred, obs)])
    V.setdefault("sol_to_date_vs_rems_daily", {})[conv] = dict(n=len(diff), exact_pct=round(float((diff == 0).mean() * 100), 1), within_1_day_pct=round(float((np.abs(diff) <= 1).mean() * 100), 1), max_abs_days=int(np.abs(diff).max()))
V["themis_time_check"] = [dict(id=t["id"], utc_to_lmst_minus_ltst_minus_eot_h=round(wm.utc_to_sol_lmst(i["utc"])[1] - t["lmst"], 3)) for i, t in zip(ims, T)]
allims = [i for i in tm.themis_images() if i["utc"] is not None]
V["themis_time_check_all"] = dict(n=len(allims), max_abs_h=round(max(abs(wm.utc_to_sol_lmst(i["utc"])[1] - (i["ltst"] - float(wm.eot_hours(w.ls_of_sol(wm.utc_to_sol_lmst(i["utc"])[0], i["ltst"]))))) for i in allims), 3),
                                  max_abs_ls_deg=round(max(abs(w.ls_of_sol(wm.utc_to_sol_lmst(i["utc"])[0], wm.utc_to_sol_lmst(i["utc"])[1]) - i["ls_label"]) for i in allims), 2))

# ----------------------------------------------------------------- REMS reproduction at the rover track cells
track = S["dist_to_rover_track_m"] == 0; inside = track & np.isfinite(S["elevation_m"])
hr = np.array(sorted(w.rems_sols)); res = []; mx = []; cmp_daily = []
dly = {int(r["sol"]): r for r in daily}
for sol in hr[::2]:
    if not np.isfinite(w._rems_raw["ground_temp_K"][list(w.rems_sols).index(sol)]).sum() >= 20: continue
    obs = np.array([w._rems_raw["ground_temp_K"][list(w.rems_sols).index(sol), h] for h in range(24)])
    mod = np.array([np.nanmean(w.dynamic(int(sol), h + 0.5)["ground_temp_K"][inside]) for h in range(24)]); g = np.isfinite(obs)
    res.append((sol, (mod - obs)[g]))
    r = dly.get(int(sol))
    if r and r["max_gts_temp"] and r["min_gts_temp"]: cmp_daily.append((sol, float(r["max_gts_temp"]) + 273.15, float(r["min_gts_temp"]) + 273.15, np.nanmax(mod), np.nanmin(mod), np.nanmax(obs[g]), np.nanmin(obs[g])))
e = np.concatenate([x[1] for x in res])
V["rems_track"] = dict(n_sols=len(res), n_values=int(e.size), bias_K=round(float(e.mean()), 2), rmse_K=round(float(np.sqrt((e ** 2).mean())), 2), max_abs_K=round(float(np.abs(e).max()), 2), track_cells=int(inside.sum()))
cd = np.array(cmp_daily)
V["rems_track_vs_daily_summary"] = dict(n_sols=len(cd), model_daily_max_minus_rems_max_gts_K=round(float(np.mean(cd[:, 3] - cd[:, 1])), 2), model_daily_min_minus_rems_min_gts_K=round(float(np.mean(cd[:, 4] - cd[:, 2])), 2),
                                        hourly_obs_max_minus_rems_max_gts_K=round(float(np.mean(cd[:, 5] - cd[:, 1])), 2), hourly_obs_min_minus_rems_min_gts_K=round(float(np.mean(cd[:, 6] - cd[:, 2])), 2))

# ----------------------------------------------------------------- shielding
sv = S["sky_view"]; f = w.dose_factor; ok = np.isfinite(f)
edge = np.load(os.path.join(wm.WORLD, "horizon_32_4m.npz"))["edge_flag"].astype(bool)
q = np.nanpercentile(f[ok], [0, 0.1, 1, 50, 99, 100])
V["shielding"] = dict(sky_view_ref_on_track=round(w.sky_ref, 4), factor_min=round(float(q[0]), 3), factor_p01=round(float(q[1]), 3), factor_p1=round(float(q[2]), 3), factor_median=round(float(q[3]), 3), factor_p99=round(float(q[4]), 3), factor_max=round(float(q[5]), 3),
                      track_mean_factor=round(float(np.nanmean(f[track])), 4), share_cells_below_0p9_pct=round(float((f[ok] < 0.9).mean() * 100), 2), share_above_1_pct=round(float((f[ok] > 1).mean() * 100), 2),
                      edge_share_pct=round(float(edge.mean() * 100), 1), dose_rate_range_uGy_h_sol4600=[round(float(np.nanmin(w.dynamic(4600, 12)["dose_rate_uGy_h"])), 2), round(float(np.nanmax(w.dynamic(4600, 12)["dose_rate_uGy_h"])), 2)])
lowest = np.argsort(np.where(ok, f, 9).ravel())[:2000]; rr, cc = np.divmod(lowest, 585)
V["shielding"]["lowest_2000_cells"] = dict(mean_elevation_m=round(float(np.nanmean(S["elevation_m"][rr, cc])), 1), roi_mean_elevation_m=round(float(np.nanmean(S["elevation_m"])), 1), mean_slope_deg=round(float(np.nanmean(S["slope_mean_deg"][rr, cc])), 1),
                                           roi_mean_slope_deg=round(float(np.nanmean(S["slope_mean_deg"])), 1), share_edge_flagged_pct=round(float(edge[rr, cc].mean() * 100), 1))
# second pass: independent horizon from the 4 m mean elevation (different data resolution and code path), 300 random interior cells
rng = np.random.default_rng(1); el = S["elevation_m"].astype(float)
cand = np.argwhere(np.isfinite(el) & ~edge); pick = cand[rng.choice(len(cand), 300, replace=False)]
dist = np.arange(1, 500) * wm.CELL_M * 1.0   # up to ~2 km
azs = np.radians(np.arange(32) * 11.25); diffs = []; svs = []
Rm = 3396190.0
for r0, c0 in pick:
    h = np.zeros(32)
    for k, a in enumerate(azs):
        rr_ = np.rint(r0 - dist / wm.CELL_M * math.cos(a)).astype(int); cc_ = np.rint(c0 + dist / wm.CELL_M * math.sin(a)).astype(int)
        m = (rr_ >= 0) & (rr_ < 732) & (cc_ >= 0) & (cc_ < 585); z = el[rr_[m], cc_[m]]; d_ = dist[m]
        ang = np.degrees(np.arctan2(z - (el[r0, c0] + 1.7) - d_ ** 2 / (2 * Rm), d_)); ang = ang[np.isfinite(ang)]
        h[k] = max(ang.max(), 0.0) if ang.size else 0.0     # horizon floor of 0 when nothing rises above the eye plane
    hz = S["horizon_deg"][:, r0, c0].astype(float)
    diffs.append(np.maximum(hz, 0) - h); svs.append((np.mean(np.cos(np.radians(h)) ** 2), sv[r0, c0]))
diffs = np.array(diffs); svs = np.array(svs)
V["shielding"]["independent_check_300_cells"] = dict(horizon_mean_abs_diff_deg=round(float(np.abs(diffs).mean()), 2), horizon_median_abs_diff_deg=round(float(np.median(np.abs(diffs))), 2),
                                                    horizon_bias_deg=round(float(diffs.mean()), 2), sky_view_mean_abs_diff=round(float(np.abs(svs[:, 0] - svs[:, 1]).mean()), 4), sky_view_corr=round(float(np.corrcoef(svs[:, 0], svs[:, 1])[0, 1]), 3))

# ----------------------------------------------------------------- SEP / DONKI
sp = [(s, w.sep_alert(s, 12.0)) for s in range(4500, 4797) if w.sep_covered(s, 12.0)]
V["sep"] = dict(donki_range=list(w.donki_range), sep_days=len(w.sep_days), cme_mars_days=len(w.cme_mars_days), campaign_sols_covered=len(sp), sols_alert_total=sum(a[0] for _, a in sp),
                sols_alert_sep=sum(("SEP" in a[1]) for _, a in sp), sols_alert_cme_only=sum((a[1] == "CME") for _, a in sp), last_covered_sol=max(s for s, _ in sp))

# ----------------------------------------------------------------- static checks
meta = w.meta["layers"]
V["static_coverage_pct"] = {k: v["coverage_pct"] for k, v in meta.items()}
nav = np.load(os.path.join(wm.ROI, "nav_grid_4m.npz"))
V["static_vs_nav_grid"] = {k: bool(np.array_equal(np.nan_to_num(S[k]), np.nan_to_num(nav[k]))) for k in ("elevation_m", "slope_max_deg", "slope_mean_deg", "rough_max_m", "valid_frac", "hydration", "sulfate", "science", "loose")}
# ground-type alignment: slope distributions by type, and best integer shift of the material grid
gt = S["ground_type"]; sl = S["slope_mean_deg"]; best = []
for dr in range(-2, 3):
    for dc in range(-2, 3):
        g2 = np.roll(np.roll(gt, dr, 0), dc, 1); best.append((float(np.nanmean(sl[g2 == 0]) - np.nanmean(sl[g2 == 1])), dr, dc))
V["ground_type"] = dict(mean_slope_by_type={t: round(float(np.nanmean(sl[gt == i])), 1) for i, t in enumerate(("bedrock", "sand", "pebbly"))}, best_shift_by_slope_contrast=sorted(best, reverse=True)[0][1:], share_cells={t: int((gt == i).sum()) for i, t in enumerate(("bedrock", "sand", "pebbly"))})
V["rover_scan"] = dict(cells=int(S["rover_scan"].sum()), scans=len(json.load(open(os.path.join(ROOT, "demo", "twin", "meshes", "meshes_index.json")))))
# speed
import time; t0 = time.time(); [w.dynamic(4600, 7 + .37 * i) for i in range(10)]; V["dynamic_seconds_per_call"] = round((time.time() - t0) / 10, 3)
json.dump(V, open(os.path.join(wm.WORLD, "world_validation.json"), "w"), indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))

# ----------------------------------------------------------------- figures
def show(ax, a, title, cmap="viridis", vmin=None, vmax=None, cb=True, label=""):
    im = ax.imshow(a, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest"); ax.set_title(title, fontsize=9); ax.set_xticks([]); ax.set_yticks([])
    if cb: plt.colorbar(im, ax=ax, fraction=0.04, pad=0.02, label=label)
fig, ax = plt.subplots(2, 4, figsize=(18, 9))
show(ax[0, 0], S["elevation_m"], "elevation_m (measured)", "terrain", label="m"); show(ax[0, 1], S["slope_max_deg"], "slope_max_deg (derived)", "magma", 0, 40, label="deg")
show(ax[0, 2], S["loose"], "loose (derived, coarse ~100 m)", "cividis", label="0-1"); show(ax[0, 3], S["science"], "science (CRISM, ~18 m)", "RdBu_r", -4, 4, label="z sum")
show(ax[1, 0], np.where(gt >= 0, gt, np.nan), "ground_type (corridor)", "Set2", label="0 bedrock 1 sand 2 pebbly"); show(ax[1, 1], S["rock_frac"], "rock_frac (corridor)", "gray_r", 0, 0.05, label="0-1")
show(ax[1, 2], S["dist_to_rover_track_m"], "dist_to_rover_track_m", "viridis_r", 0, 1500, label="m"); ax[1, 2].contour(S["rover_scan"].astype(float), [0.5], colors="r", linewidths=0.6)
show(ax[1, 3], S["dtm_uncert_m"], "dtm_uncert_m (derived)", "magma", 0, 5, label="m")
plt.tight_layout(); plt.savefig(os.path.join(FIG, "world_static_layers.png"), dpi=70); plt.close()

fig, ax = plt.subplots(1, 3, figsize=(17, 6.5))
show(ax[0], f, "terrain shielding factor (modelled), 1 = open ground where RAD measured", "RdYlBu", 0.6, 1.05, label="x RAD rate")
ax[0].contour(track.astype(float), [0.5], colors="k", linewidths=0.4)
show(ax[1], np.where(edge, np.nan, f), "same, cells >300 m from the ROI edge only", "RdYlBu", 0.6, 1.05, label="x RAD rate")
ax[2].hist(f[ok & ~edge], 80, color="C0", alpha=.8, label="interior"); ax[2].hist(f[ok & edge], 80, color="C3", alpha=.6, label="edge (<300 m, biased high)"); ax[2].axvline(1, color="k", lw=.8)
ax[2].set_xlabel("shielding factor"); ax[2].set_ylabel("cells"); ax[2].legend(); ax[2].set_title("histogram", fontsize=9)
plt.tight_layout(); plt.savefig(os.path.join(FIG, "world_shielding.png"), dpi=70); plt.close()

fig, ax = plt.subplots(2, 4, figsize=(18, 9)); k = 0
for sol, lm in ((4600, 6.5), (4600, 9.0), (4600, 13.0), (4600, 16.5)):
    d = w.dynamic(sol, lm)
    show(ax[0, k], np.where(d["in_shadow"], np.nan, d["insolation"]), "insolation W/m2 (modelled) sol %d LMST %.1f\nsun el %.1f az %.0f; shadow %.0f%%" % (sol, lm, d["sun_el"], d["sun_az"], d["in_shadow"].mean() * 100), "inferno", 0, None, label="W/m2")
    ax[0, k].imshow(np.where(d["in_shadow"], 1.0, np.nan), cmap="Greys", alpha=.5, vmin=0, vmax=2, interpolation="nearest")
    show(ax[1, k], d["ground_temp_K"], "ground_temp_K (modelled) base %.0f K" % d["ground_temp_baseline_K"], "coolwarm", label="K"); k += 1
plt.tight_layout(); plt.savefig(os.path.join(FIG, "world_dynamic_maps.png"), dpi=70); plt.close()

fig, ax = plt.subplots(1, 3, figsize=(17, 5.2))
pi = V["themis"]["per_image"]; x = np.arange(len(pi))
ax[0].bar(x - .2, [p["themis_mean_K"] for p in pi], .4, label="THEMIS BT mean"); ax[0].bar(x + .2, [p["model_mean_K"] for p in pi], .4, label="model mean")
ax[0].set_ylim(170, 225); ax[0].set_xticks(x); ax[0].set_xticklabels(["%s\n%s %.1fh" % (p["date"], p["kind"], p["lmst"]) for p in pi], fontsize=7); ax[0].set_ylabel("K"); ax[0].legend(); ax[0].set_title("per image: level (bias %s K dawn, %s K dusk)" % (V["themis"]["dawn_mean_bias_K"], V["themis"]["dusk_mean_bias_K"]), fontsize=9)
cols = ["C0", "C1", "C2", "C3", "C4"]
for i_, t in enumerate(T):
    mdl = t["base"] + w.p["a_K_per_Wm2"] * t["dS"] + w.p["kappa_K_per_K"] * t["Z"] * t["wave"]
    g = np.isfinite(t["bt"]); ax[1].scatter((mdl - np.nanmean(mdl))[g], (t["bt"] - np.nanmean(t["bt"]))[g], s=6, c=cols[i_], alpha=.6, label=t["id"][:9] + (" dusk" if t["ltst"] > 15 else " dawn"))
ax[1].plot([-5, 5], [-5, 5], "k", lw=.7); ax[1].set_xlabel("model minus image mean (K)"); ax[1].set_ylabel("THEMIS minus image mean (K)"); ax[1].legend(fontsize=7); ax[1].set_title("spatial pattern (100 m pixels, z from the 9 other images)", fontsize=9)
for sol in (4600, 4700):
    sol = int(w.rems_sols[np.argmin(np.abs(w.rems_sols - sol))])      # nearest sol that has hourly data
    obs = w._rems_raw["ground_temp_K"][list(w.rems_sols).index(sol)]
    mod = [np.nanmean(w.dynamic(sol, h + .5)["ground_temp_K"][inside]) for h in range(24)]
    ax[2].plot(np.arange(24) + .5, mod, label="model, track cells, sol %d" % sol)
    if obs is not None: ax[2].plot(np.arange(24) + .5, obs, "k.", ms=4)
ax[2].set_xlabel("LMST (h)"); ax[2].set_ylabel("K"); ax[2].legend(fontsize=7); ax[2].set_title("REMS hourly (dots) vs model at the track cells", fontsize=9)
plt.tight_layout(); plt.savefig(os.path.join(FIG, "world_ground_temp_validation.png"), dpi=70); plt.close()

fig, ax = plt.subplots(1, 3, figsize=(17, 4.6))
a, b = sun_times(ls_mid, True); a0, b0 = sun_times(ls_mid, False)
ax[0].plot(sols, (a - sr) * 60, label="sunrise, with EoT"); ax[0].plot(sols, (a0 - sr) * 60, label="sunrise, twin formula (no EoT)"); ax[0].plot(sols, (b - ss) * 60, "--", label="sunset, with EoT"); ax[0].plot(sols, (b0 - ss) * 60, "--", label="sunset, twin formula")
ax[0].set_xlabel("sol"); ax[0].set_ylabel("model minus REMS (min)"); ax[0].legend(fontsize=7); ax[0].set_title("sunrise/sunset vs rems_daily (LMST)", fontsize=9)
ax[1].plot(sols, rl - am, ".", ms=3, label="REMS integer Ls minus model at sol start"); ax[1].plot(sols, rl - am_mid, ".", ms=3, label="minus model at mid-sol"); ax[1].set_xlabel("sol"); ax[1].set_ylabel("deg"); ax[1].legend(fontsize=7); ax[1].set_title("Ls: REMS integers are truncated", fontsize=9)
ax[2].plot(sols, [float(wm.eot_hours(l)) * 60 for l in ls_mid]); ax[2].set_xlabel("sol"); ax[2].set_ylabel("equation of time (min)"); ax[2].set_title("LTST - LMST at the study area", fontsize=9)
plt.tight_layout(); plt.savefig(os.path.join(FIG, "world_time_sun_checks.png"), dpi=70); plt.close()
print(json.dumps(V, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))[:9000])
