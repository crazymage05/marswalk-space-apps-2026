"""Zone card Start here / End here: buttons in walk order, Start here sets the start in the zone, End here plans to the zone (desktop and phone). Run from the repo root: python tools/zone_start_end_check.py"""
import subprocess, sys, time
from playwright.sync_api import sync_playwright
srv = subprocess.Popen([sys.executable, "-m", "http.server", "8899", "--bind", "127.0.0.1", "-d", "demo/twin"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(1.5)
res = []; errs = []
def ck(n, c, i=""): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n, i)
ZONE_OF = "c => { const Zn = MWZones, x = c % 585, y = (c / 585) | 0; for (let zr = 0; zr < Zn.rows; zr++) for (let zc = 0; zc < Zn.cols; zc++) if (x >= Zn.edge(zc) && x < Zn.edge(zc+1) && y >= Zn.edge(zr) && y < Zn.edge(zr+1)) return Zn.name(zc, zr); }"
try:
  with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=d3d11"])
    for W, H in ((1440, 900), (400, 860)):
        pg = b.new_page(viewport={"width": W, "height": H}, has_touch=W < 600); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:8899/twin.html?notour"); pg.wait_for_function("document.getElementById('loading').hidden===true && window.__zones && __zones.state.ready", timeout=180000); pg.wait_for_timeout(1000)
        op = lambda name: pg.evaluate("n => { const z = MWZones.parse(n); __zones.open(MWZones.id(z.zc, z.zr)); }", name)
        op("E5"); pg.wait_for_timeout(600)
        labels = pg.evaluate("[...document.querySelectorAll('#zoneCard .zbtns button')].map(b => b.textContent)")
        ck(f"[{W}] buttons in walk order", labels == ["Start here", "End here", "Add as stop"], str(labels))
        pg.click("#zoneStartBtn"); pg.wait_for_timeout(400)
        st = pg.evaluate("({s: window.__routeCells(), status: document.getElementById('status').textContent, msg: document.getElementById('zoneMsg').textContent})")
        ck(f"[{W}] Start here sets start in E5, clears route", st["s"] is None and "Start set in zone E5" in st["status"], st["status"][:60])
        op("C9"); pg.wait_for_timeout(600); pg.click("#zoneGo"); pg.wait_for_timeout(1500)
        r = pg.evaluate("() => { const c = __routeCells(); return c ? {n: c.length, a: c[0], b: c[c.length-1], v: document.getElementById('verdict').innerText.slice(0, 40)} : null; }")
        za = pg.evaluate(ZONE_OF, r["a"]) if r else None; zb = pg.evaluate(ZONE_OF, r["b"]) if r else None
        ck(f"[{W}] End here plans E5 -> C9", r and za == "E5" and zb == "C9", f"{za} -> {zb}, {r and r['n']} cells")
        ck(f"[{W}] verdict shown", r and ("GO" in r["v"] or "NO-GO" in r["v"]), r and r["v"])
        pg.close()
    b.close()
finally:
  srv.terminate()
ck("no page errors", not errs, "; ".join(errs[:2])); print(f"{sum(res)}/{len(res)}")
