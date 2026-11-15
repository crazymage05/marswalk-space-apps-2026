"""Check the hosted MARSWALK site end to end: every page loads, no failed requests or HTTP errors, the twin plans the
campaign route (215 cells, GO), the walk starts, mission control loads its log, the intro video is served.

    python tools/live_site_check.py https://crazymage05.github.io/marswalk-space-apps-2026/
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/") + "/"
res, bad = [], []


def ck(name, cond, info=""):
    res.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, info)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=d3d11", "--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: bad.append("pageerror " + str(e)[:120]))
    # a video's partial (range) download cancelled by leaving the page is net::ERR_ABORTED, not a failure
    pg.on("requestfailed", lambda r: bad.append(f"failed {r.url[-60:]} ({r.failure})") if "fonts.g" not in r.url and not (r.url.endswith(".mp4") and "ABORTED" in str(r.failure)) else print("  (ignored) cancelled", r.url[-40:], r.failure))
    pg.on("response", lambda r: bad.append(f"HTTP {r.status} {r.url[-80:]}") if r.status >= 400 else None)

    pg.goto(BASE, timeout=120000); pg.wait_for_timeout(2500)
    ck("first visit lands on the intro", pg.url.endswith("intro.html"), pg.url)
    pg.click("#play"); pg.click("[data-answer=no]"); pg.wait_for_timeout(1500)
    ck("intro answer line", "journey" in pg.inner_text("#answerLine"))
    ok = pg.evaluate("() => new Promise(r => { const v = document.getElementById('vid'); v.preload = 'auto'; v.load(); v.oncanplay = () => r(v.duration); setTimeout(() => r(0), 30000); })")
    ck("intro demo video loads", ok and ok > 25, f"duration {ok:.1f} s" if ok else "no data")
    pg.click("#skip"); pg.wait_for_timeout(2500)
    ck("Skip intro opens the dashboards", "hub" in pg.url and pg.locator("text=Validation scoreboard").count() > 0, pg.url)

    pg.goto(BASE + "twin.html?notour", timeout=120000)
    pg.wait_for_function("document.getElementById('loading').hidden === true", timeout=240000)
    pg.click("#btnDemo")
    pg.wait_for_function("!document.getElementById('verdict').hidden && !/Checking/.test(document.getElementById('verdict').textContent)", timeout=90000)
    n = pg.evaluate("__routeCells().length"); v = pg.inner_text("#verdict")[:4]
    ck("twin plans the campaign route", n == 215 and v.startswith("GO"), f"{n} cells, {v!r}")
    pg.click("#btnWalk"); pg.wait_for_function("window.__walk && window.__walk.on === true", timeout=180000); pg.wait_for_timeout(5000)
    ck("walk view starts", pg.evaluate("window.__walk.on"))
    pg.keyboard.press("Escape"); pg.wait_for_timeout(1000)

    pg.goto(BASE + "mission.html", timeout=120000)
    pg.wait_for_function("window.__mission && window.__mission.log", timeout=90000)
    ck("mission control loads its log", pg.evaluate("window.__mission.log.mission.timeline.length") > 5)
    b.close()

ck("no page errors, failed requests or HTTP errors", not bad, "; ".join(bad[:5]))
print(f"live site {sum(res)}/{len(res)}")
