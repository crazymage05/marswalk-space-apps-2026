"""Fixed first-person walk screenshots for before/after comparisons of the twin's walk rendering.

usage: python tools/walk_shots.py <name> [port]
Serve the page first: python -m http.server 8765 --bind 127.0.0.1 -d demo/twin
Stands the walker at 3 points of the campaign route (start, middle, near the end) at LMST 08:45, 12:00 and 16:30
on sol 4600, first-person view, paused, and saves <point>_<time>.png plus stats.json (per-image mean, share of
clipped pixels per channel, share of near-black pixels) to runs/twin_check/<name>/.
"""
import json, os, sys
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
exposure = float(os.environ.get("WALK_EXPOSURE", "0"))     # 0 = keep the page default
OUT = os.path.join(ROOT, "runs", "twin_check", name)
os.makedirs(OUT, exist_ok=True)
POINTS = {"start": 0.05, "mid": 0.5, "end": 0.9}          # fraction of the route length
TIMES = {"0845": 8.75, "1200": 12.0, "1630": 16.5}
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
    pg.wait_for_timeout(2500)
    pg.keyboard.press("Space")                                   # pause
    if exposure > 0:
        pg.evaluate(f"() => {{ window.__walk.exposure = {exposure}; window.__walk.renderer.toneMappingExposure = {exposure}; }}")
    pg.locator("#view").scroll_into_view_if_needed()
    for pn, frac in POINTS.items():
        for tn, lm in TIMES.items():
            pg.evaluate(f"""() => {{ const W = window.__walk; W.lmst0 = {lm}; W.simSec = 0;
                const el = document.getElementById('wStart'); el.value = {lm}; el.dispatchEvent(new Event('input'));
                W.s = W.routeLength() * {frac}; W.pitch = -0.12; W.yawOff = 0; }}""")
            pg.wait_for_timeout(1500)
            f = os.path.join(OUT, f"{pn}_{tn}.png")
            pg.locator("#view canvas").first.screenshot(path=f)
            a = np.asarray(Image.open(f).convert("RGB")).astype(np.float32)
            stats[f"{pn}_{tn}"] = {"mean": round(float(a.mean()), 1),
                                   "clipped_pct": [round(float((a[..., k] >= 254).mean() * 100), 2) for k in range(3)],
                                   "black_pct": round(float((a.max(-1) <= 8).mean() * 100), 2),
                                   "p5_p95": [round(float(np.percentile(a.mean(-1), 5)), 1), round(float(np.percentile(a.mean(-1), 95)), 1)]}
    b.close()
stats["_console_errors"] = errors
json.dump(stats, open(os.path.join(OUT, "stats.json"), "w"), indent=1)
for k, v in stats.items():
    print(k, v)
