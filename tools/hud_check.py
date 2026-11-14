"""Independent check of the twin's helmet HUD against phase4 Python models."""
import sys, os, math, json, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from phase4 import costs, astronaut as A, astar, safety_validator as SV
from playwright.sync_api import sync_playwright

OUT = os.path.join(ROOT, "runs", "twin_check", "hud_check"); os.makedirs(OUT, exist_ok=True)
grid = costs.load_grid(); prof = A.get_profile("nominal")
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"])
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errors.append("console:" + m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append("pageerror:" + str(e)))
    pg.goto("http://127.0.0.1:8765/twin.html")
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=180000)
    pg.click("#btnDemo"); pg.wait_for_timeout(1500)
    pg.click("#btnWalk"); pg.wait_for_function("window.__walk.on===true", timeout=240000)
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=240000)
    pg.wait_for_timeout(2500); pg.keyboard.press("Space")
    cells = [int(c) for c in pg.evaluate("() => Array.from(window.__walk.routeCells())")]

    # python reference
    W, cm = grid["width"], grid["cell_m"]; z = np.nan_to_num(grid["elevation_m"])
    d, g = [], []
    for a, c in zip(cells[:-1], cells[1:]):
        (ra, ca), (rb, cb) = divmod(a, W), divmod(c, W)
        pd = cm * math.hypot(ra - rb, ca - cb); dz = float(z[rb, cb] - z[ra, ca])
        d.append(math.hypot(pd, dz)); g.append(dz / pd)
    n = len(d); cumD = [0]; cumT = [0]; cumE = [0]; cumF = [0]
    t = e = f = 0.0
    for di, gi in zip(d, g):
        v = A.step_speed_mps(prof, gi, f); de = A.step_energy_kj(prof, di, gi)
        t += di / v; e += de; f = A.fatigue_update(prof, f, de)
        cumD.append(cumD[-1] + di); cumT.append(t); cumE.append(e); cumF.append(f)
    # reverse leg for each prefix k
    def back(k):
        tt = ee = ff = 0.0
        for di, gi in zip(d[:k][::-1], g[:k][::-1]):
            v = A.step_speed_mps(prof, -gi, ff); de = A.step_energy_kj(prof, di, -gi)
            tt += di / v; ee += de; ff = A.fatigue_update(prof, ff, de)
        return tt, ee
    backs = {}
    def at(dist):
        k = min(max(np.searchsorted(cumD, dist, side="right") - 1, 0), n - 1)
        fr = (dist - cumD[k]) / d[k]
        return k, fr
    def ref(u):
        dist = u * cumD[-1]; k, fr = at(dist)
        T = cumT[k] + fr * (cumT[k+1] - cumT[k]); E = cumE[k] + fr * (cumE[k+1] - cumE[k]); F = cumF[k] + fr * (cumF[k+1] - cumF[k])
        if k not in backs: backs[k] = (back(k), back(k + 1))
        (t0, e0), (t1, e1) = backs[k]
        BT = t0 + fr * (t1 - t0); BE = e0 + fr * (e1 - e0)
        keep = 1 - prof.return_reserve_frac; tl = prof.eva_time_h * 3600 * keep; el = prof.energy_budget_kj * keep
        return dict(t=T, e=E, f=F, backT=BT, backE=BE, marginMin=(tl - T - BT) / 60, marginKJ=el - E - BE)
    # totals
    rm = astar.route_metrics(grid, cells, prof); val = SV.validate(cells, grid, prof)["summary"]
    bT, bE = back(n)
    tot = dict(my_T=cumT[-1], rm_T=rm["time_s"], my_E=cumE[-1], rm_E=rm["energy_kj"], my_F=cumF[-1], rm_F=rm["fatigue"], my_D=cumD[-1], rm_D=rm["distance_m"],
               my_rt_T=cumT[-1] + bT, sv_rt_T=val["roundtrip_time_s"], my_rt_E=cumE[-1] + bE, sv_rt_E=val["roundtrip_energy_kj"])
    print("TOTALS", json.dumps(tot, indent=1))
    # elevation diff: page vs python along route via hook if any; skip, report via totals of page at u=1
    random.seed(7)
    us = [0.05, 0.5, 1.0] + sorted(round(random.uniform(0.1, 0.95), 4) for _ in range(3))
    rows = []
    def pct(a, bb): return 0.0 if bb == 0 and a == 0 else (a - bb) / (abs(bb) if bb else 1) * 100
    for u in us:
        pg.evaluate(f"() => {{ window.__walk.s = window.__walk.routeLength() * {u}; }}"); pg.wait_for_timeout(1200)
        v = pg.evaluate("() => window.__walk.visorVals")
        txt = {k: pg.inner_text("#" + k) for k in ["vTime", "vEnergy", "vDose", "vFat", "vMargin", "vLimit", "wEl", "wDose"]}
        r = ref(v["u"]); r["dose_pyrate"] = A.dose_uGy(r["t"]); r["dose_pagerate"] = v["rate"] * r["t"] / 3600
        comp = {}
        for k in ["t", "e", "f", "backT", "backE", "marginMin", "marginKJ"]: comp[k] = (v[k], r[k], pct(v[k], r[k]))
        comp["dose"] = (v["dose"], r["dose_pagerate"], pct(v["dose"], r["dose_pagerate"]))
        comp["dose_vs_pyrate"] = (v["dose"], r["dose_pyrate"], pct(v["dose"], r["dose_pyrate"]))
        rows.append(dict(u_req=u, u=v["u"], rate=v["rate"], comp=comp, text=txt, limit=(v["limit"], v["limitUse"])))
        print(f"\nu={u} (page u={v['u']:.5f}) rate={v['rate']}  text={txt} limit={v['limit']} {v['limitUse']:.3f}")
        for k, (a, bb, dd) in comp.items(): print(f"  {k:15s} page={a:12.4f} py={bb:12.4f} diff={dd:+.3f}%")
    json.dump(dict(totals=tot, rows=rows, errors=errors), open(os.path.join(OUT, "hud_check.json"), "w"), indent=1, default=str)
    print("\nERRORS", errors)
    b.close()
print("python rate", A.RAD_RATE_UGY_H)
