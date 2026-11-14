"""H2: a SIMULATED moving dust event for MARSWALK (labelled simulated everywhere it is shown).

The event is a region of raised dust optical depth tau that moves in a straight line at constant speed:
    tau(r, t) = tau_bg + (tau_peak - tau_bg) * exp(-0.5 (r / sigma)^2),   sigma = radius_m / 2,
r = distance from the centre at time t (hours after the event start). tau_bg is the climatological tau of the season
(phase4/build_tau_climatology.py). Rules (phase5/hazard_config.json): HZ-1 tau >= 2.0 blocks a cell; HZ-2 tau >= 1.0
raises its cost. For planning, the footprint is swept over a look-ahead window (default 2 h): a cell is blocked if the
core covers it at any time in the window. Insolation under the event: direct beam x exp(-(tau - tau_bg) m). Visibility:
Koschmieder 3.912 / beta with beta = tau / H_local (H_local = 1.5 km, an ASSUMPTION for a low dust cloud).
Events are reproducible from a seed and stored as JSON in data/processed/roi/hazards/.
"""
import json, math, os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "phase5", "hazard_config.json")))
OUT = os.path.join(ROOT, "data", "processed", "roi", "hazards")


def tau_background(sol=None, ls=None):
    """Climatological tau (880 nm median) for the season; 0.6 if the table is missing."""
    p = os.path.join(ROOT, "data", "processed", "roi", "tables", "tau_climatology.csv")
    if not os.path.exists(p): return 0.6
    import csv
    rows = list(csv.DictReader(open(p)))
    if ls is None:
        if sol is None: return 0.6
        from phase4.world import ls_am
        ls = ls_am(sol + 0.5 - 0.5)
    cen = np.array([float(r["ls_centre"]) for r in rows]); v = np.array([float(r["median_880"]) for r in rows])
    x = ((ls - 5) % 360) / 10; i0 = int(x) % 36; f = x - math.floor(x)
    return float(v[i0] * (1 - f) + v[(i0 + 1) % 36] * f)


def make_event(seed, grid, route=None, sol=4600, lmst_start=11.0, trigger=None, **over):
    """Draw an event from a seed. With a route, the centre is placed near a point at route_frac of it, ahead of a walker."""
    rng = np.random.default_rng(seed); R = CFG["event_ranges"]; W, H, cm = grid["width"], grid["height"], grid["cell_m"]
    u = lambda k: float(rng.uniform(*R[k]))
    if route:
        c = route[int(len(route) * u("route_frac"))]; r0, c0 = divmod(c, W)
    else:
        r0, c0 = int(rng.integers(50, H - 50)), int(rng.integers(50, W - 50))
    a = rng.uniform(0, 2 * math.pi); off = u("offset_m")
    ev = dict(kind="dust_event", SIMULATED=True, label="SIMULATED dust event (not an observed storm)", seed=int(seed),
              sol=int(sol), lmst_start=float(lmst_start), trigger=trigger or {"kind": "button"},
              centre_xy_m=[c0 * cm + off * math.cos(a), r0 * cm + off * math.sin(a)],   # x = col * cell, y = row * cell (south +)
              radius_m=u("radius_m"), speed_mps=u("speed_mps"), direction_deg=float(rng.uniform(0, 360)),   # heading, clockwise from north
              tau_peak=u("tau_peak"), tau_bg=tau_background(sol), rules=CFG["rules"], lookahead_h=CFG["lookahead_h"],
              grid_cell_m=cm, grid_shape=[H, W])
    ev.update(over)
    ev["id"] = f"dust_{ev['seed']}_{ev['sol']}_{ev['lmst_start']:.2f}"
    return ev


def centre_at(ev, t_h):
    """Centre (x, y) in metres at t_h hours after the start; heading clockwise from north, north = row decreasing."""
    d = ev["speed_mps"] * t_h * 3600.0; h = math.radians(ev["direction_deg"])
    return ev["centre_xy_m"][0] + d * math.sin(h), ev["centre_xy_m"][1] - d * math.cos(h)


def tau_field(ev, t_h, shape=None):
    H, W = shape or ev["grid_shape"]; cm = ev["grid_cell_m"]; cx, cy = centre_at(ev, t_h)
    yy, xx = np.mgrid[0:H, 0:W]; r2 = ((xx * cm - cx) ** 2 + (yy * cm - cy) ** 2) / (ev["radius_m"] / 2) ** 2
    return (ev["tau_bg"] + (ev["tau_peak"] - ev["tau_bg"]) * np.exp(-0.5 * r2)).astype(np.float32)


def overlay(ev, t0_h, t1_h=None):
    """Swept rules over [t0, t1] (default t0 + lookahead): (blocked bool HxW, cost_mult HxW, max tau HxW)."""
    t1_h = t0_h + ev["lookahead_h"] if t1_h is None else t1_h
    n = max(1, int(math.ceil((t1_h - t0_h) * 3600 / CFG["sweep_step_s"])))
    tmax = None
    for k in range(n + 1):
        t = tau_field(ev, t0_h + (t1_h - t0_h) * k / n); tmax = t if tmax is None else np.maximum(tmax, t)
    r1, r2 = ev["rules"]["HZ-1"], ev["rules"]["HZ-2"]
    blocked = tmax >= r1["tau_ge"]
    frac = np.clip((tmax - ev["tau_bg"]) / max(1e-6, ev["tau_peak"] - ev["tau_bg"]), 0, 1)
    mult = np.where(tmax >= r2["tau_ge"], 1.0 + r2["k"] * frac, 1.0)
    return blocked, mult, tmax


def insolation_factor(tau, tau_bg, sun_el_deg):
    """Direct-beam factor under the event relative to the background sky (Beer-Lambert, airmass capped at 10)."""
    m = min(1 / max(math.sin(math.radians(max(sun_el_deg, 0.1))), 1e-3), 10.0)
    return math.exp(-(tau - tau_bg) * m)


def visibility_km(tau):
    return 3.912 / (tau / CFG["near_surface_scale_height_km"])


def save(ev, path=None):
    os.makedirs(OUT, exist_ok=True); path = path or os.path.join(OUT, ev["id"] + ".json")
    json.dump(ev, open(path, "w"), indent=1); return path


def load(path):
    return json.load(open(path))


def event_from_anomaly(anomaly, grid, route=None, seed=None, **over):
    """H1 -> H2: start a SIMULATED dust event from an H1 anomaly dict (phase5/forecast.detect). The anomaly is a WEAK
    trigger (H1's detectors have low precision on this sparse single-station record, docs/phase5_h1_forecast.md);
    the event's start sol and hour are the anomaly's, the seed defaults to a hash of them so it is reproducible."""
    sol, hour = int(anomaly.get("sol", 4600)), float(anomaly.get("lmst_hour", 11.0))
    seed = seed if seed is not None else (sol * 100 + int(hour)) % (2 ** 31)
    trig = {"kind": "h1_anomaly", "strength": "weak", "method": anomaly.get("method"), "variable": anomaly.get("variable"),
            "value": anomaly.get("value"), "expected": anomaly.get("expected"), "sol": sol, "lmst_hour": hour}
    return make_event(seed, grid, route, sol=sol, lmst_start=hour, trigger=trig, **over)
