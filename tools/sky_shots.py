"""W3 check: look at the sun on the three campaign sols at three times; record the tau, sun size and sky brightness used.

usage: python tools/sky_shots.py <name> [port]      (serve demo/twin on the port first)
For sols 4500, 4650, 4799 and LMST 09:00, 12:00, 17:30 the first-person camera is turned to the sun's azimuth (pitched
to keep the horizon in view) and the frame saved to runs/twin_check/<name>/sol<sol>_<time>.png, with stats.json holding
__walk.light (tau, airmass, beam, skyB, sunRadiusDeg) and the measured diameter of the saturated sun blob in pixels.
"""
import json, os, sys
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name = sys.argv[1]; port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
OUT = os.path.join(ROOT, "runs", "twin_check", name); os.makedirs(OUT, exist_ok=True)
stats, errors = {}, []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"])
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(f"http://127.0.0.1:{port}/twin.html")
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=180000)
    pg.click("#btnDemo"); pg.wait_for_timeout(1500)
    pg.click("#btnWalk"); pg.wait_for_function("window.__walk.on===true", timeout=240000)
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=240000)
    pg.wait_for_timeout(2500); pg.keyboard.press("Space")
    pg.locator("#view").scroll_into_view_if_needed()
    for sol in (4500, 4650, 4799):
        pg.evaluate(f"() => {{ const el = document.getElementById('sol'); el.value = {sol}; el.dispatchEvent(new Event('input')); el.dispatchEvent(new Event('change')); }}")
        for tn, lm in (("0900", 9.0), ("1200", 12.0), ("1730", 17.5)):
            pg.evaluate(f"""() => {{ const W = window.__walk; W.lmst0 = {lm}; W.simSec = 0;
                const el = document.getElementById('wStart'); el.value = {lm}; el.dispatchEvent(new Event('input')); W.s = W.routeLength() * 0.5; }}""")
            pg.wait_for_timeout(1800)
            info = pg.evaluate(f"""() => {{ const W = window.__walk, v = W.sunDir({lm}, {sol}).v;
                W.yawOff = Math.atan2(v.x, -v.z) - W.baseYaw; W.pitch = Math.max(-0.05, Math.asin(v.y) - 0.12);
                return {{ sunEl: Math.asin(v.y) * 180 / Math.PI, sol: +document.getElementById('sol').value }}; }}""")
            pg.wait_for_timeout(500)
            f = os.path.join(OUT, f"sol{sol}_{tn}.png")
            pg.locator("#view canvas").first.screenshot(path=f)
            light = pg.evaluate("() => window.__walk.light")
            hud = pg.evaluate("() => document.getElementById('wTau').textContent")
            a = np.asarray(Image.open(f).convert("RGB")).astype(np.float32); sat = a.min(-1) >= 250
            if sat.any():
                ys, xs = np.nonzero(sat); cy, cx = np.median(ys), np.median(xs); k = (np.abs(ys - cy) < 40) & (np.abs(xs - cx) < 40)
                blob = float(2 * np.sqrt(k.sum() / np.pi))
            else: blob = 0.0
            stats[f"sol{sol}_{tn}"] = {**info, "light": light, "hud_tau": hud, "mean": round(float(a.mean()), 1), "sun_blob_diam_px": round(blob, 1),
                                       "expected_disc_px": round(light["sunRadiusDeg"] * 2 / (60 / a.shape[0]), 1)}
    b.close()
stats["_console_errors"] = errors
json.dump(stats, open(os.path.join(OUT, "stats.json"), "w"), indent=1)
for k, v in stats.items(): print(k, v)
