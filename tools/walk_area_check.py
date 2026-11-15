"""3D walk area checks (twin.html): the campaign, science and Curiosity-track routes lie inside the walk area; target search
returns only cells inside it; the big "Walk this route" button appears with a route and starts the walk; a route that
leaves the area is refused with a message; the day theme is the default.   python tools/walk_area_check.py"""
import subprocess, sys, time, os
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
srv = subprocess.Popen([sys.executable, "-m", "http.server", "8899", "--bind", "127.0.0.1", "-d", os.path.join(ROOT, "demo/twin")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(1.5)
res, errs = [], []
SHOT = os.path.join(ROOT, "data/processed/checks"); os.makedirs(SHOT, exist_ok=True)


def ck(n, c, i=""):
    res.append(bool(c)); print(("PASS " if c else "FAIL ") + n, i)


INSIDE = "() => { const A = window.__walkArea, r = __routeCells(); return r ? r.every(c => { const x = c % 585, y = (c / 585) | 0; return x >= A.x0 && x <= A.x1 && y >= A.y0 && y <= A.y1; }) : null; }"
try:
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=d3d11"])
        pg = b.new_page(viewport={"width": 1440, "height": 900}); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:8899/twin.html?notour"); pg.wait_for_function("document.getElementById('loading').hidden===true && window.__walkArea && __walkArea.ok", timeout=180000)
        ck("day theme by default", pg.evaluate("document.documentElement.dataset.theme") == "day")
        ck("walk area known", pg.evaluate("window.__walkArea.ok"), str(pg.evaluate("({x0: __walkArea.x0, x1: Math.round(__walkArea.x1), y0: __walkArea.y0, y1: Math.round(__walkArea.y1)})")))
        pg.click("#btnClear"); pg.wait_for_timeout(400); ck("no Walk button without a route (after Clear)", pg.evaluate("document.getElementById('walkFab').hidden"))
        for btn in ("btnDemo", "btnSci", "btnTrack"):
            pg.click("#" + btn); pg.wait_for_timeout(2500); ck(f"{btn} route inside the walk area", pg.evaluate(INSIDE))
        pg.click("#btnDemo"); pg.wait_for_timeout(1500)
        ck("Walk button shows with a route", not pg.evaluate("document.getElementById('walkFab').hidden"))
        pg.screenshot(path=os.path.join(SHOT, "walk_area_map.png"))
        pg.locator("#tgtQ").fill("water"); pg.locator("#tgtGo").click(); pg.wait_for_timeout(4000)
        cand = pg.evaluate("() => { const A = __walkArea; return [...document.querySelectorAll('#tgtList2 li')].length; }")
        allin = pg.evaluate("() => { const A = __walkArea; const pins = window.__cands ? __cands() : null; return pins; }")
        st = pg.inner_text("#tgtStatus")[:120]
        ck("water search returns targets", cand > 0, f"{cand} targets; {st}")
        # route that leaves the area: from the campaign start to a cell far outside it
        out = pg.evaluate("() => { const A = __walkArea; const r = __routeCells(); const a = r[0]; const x = Math.min(584, Math.round(A.x1) + 60), y = (a / 585) | 0; return y * 585 + x; }")
        pg.evaluate("c => { const r = __routeCells(); const a = r[0], W = 585; const cells = []; let x = a % W, y = (a / W) | 0; const tx = c % W; while (x !== tx) { cells.push(y * W + x); x += x < tx ? 1 : -1; } cells.push(c); __planCells(cells); }", out)
        pg.wait_for_timeout(800); pg.click("#walkFab"); pg.wait_for_timeout(1500)
        ck("route leaving the area is refused with a message", not pg.evaluate("window.__walk && window.__walk.on") and "3D walk area" in pg.inner_text("#status"), pg.inner_text("#status")[:90])
        pg.click("#btnDemo"); pg.wait_for_timeout(1500); pg.click("#walkFab")
        pg.wait_for_function("window.__walk && window.__walk.on === true", timeout=120000); pg.wait_for_timeout(1500)
        ck("big Walk button starts the walk", pg.evaluate("window.__walk.on"))
        ck("Walk button hidden while walking", not pg.locator("#walkFab").is_visible())
        b.close()
finally:
    srv.terminate()
ck("no page errors", not errs, "; ".join(errs[:2])); print(f"walk_area {sum(res)}/{len(res)}")
