"""
F3: record paced screen captures of the demo pages (headless Chrome, network off, 1280x720 WebM; the edit scales to 1080p) for the final video.

    python -m http.server 8765 --bind 127.0.0.1 -d demo/twin      # serve first
    python tools/f3_capture.py [port] [clip ...]                  # clips: entry tour why walk mission (default all)

Writes film/capture/<clip>.webm and film/capture/capture.json (durations, errors). Each clip is its own browser
context, so the tour starts as on a first visit. Uses the same page hooks as tools/rehearsal.py and twin_check.py.
Run when the GPU is free (WebGL frame rate drops while Blender renders).
"""
import json, os, shutil, sys, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = sys.argv[1:]; port = int(args.pop(0)) if args and args[0].isdigit() else 8765
CLIPS = args or ["entry", "tour", "why", "walk", "mission"]
BASE = f"http://127.0.0.1:{port}"; OUT = os.path.join(ROOT, "film", "capture"); os.makedirs(OUT, exist_ok=True)
SIZE = VID = {"width": 1280, "height": 720}   # 1280x720 layout: text readable in a video; scaled to 1080p in the edit
if os.environ.get("F3_SIZE"):                 # e.g. F3_SIZE=1920x1080 for the 30 s demo clips
    w, h = map(int, os.environ["F3_SIZE"].lower().split("x")); SIZE = VID = {"width": w, "height": h}
report = {}


def loaded(pg):
    pg.wait_for_function("document.getElementById('loading') && document.getElementById('loading').hidden === true", timeout=180000)


def smooth_scroll(pg, to_y, ms=4000):
    pg.evaluate(f"() => window.scrollTo({{top: {to_y}, behavior: 'smooth'}})"); pg.wait_for_timeout(ms)


def entry(pg):
    pg.goto(f"{BASE}/index.html?hub"); pg.wait_for_timeout(3000)
    h = pg.evaluate("() => document.body.scrollHeight")
    smooth_scroll(pg, h // 3, 4000); smooth_scroll(pg, 2 * h // 3, 4000); smooth_scroll(pg, 0, 3000)


def tour(pg):
    pg.goto(f"{BASE}/twin.html"); loaded(pg)
    pg.wait_for_function("window.MWTour && window.MWTour.active", timeout=30000)
    pg.wait_for_function("window.MWTour && !window.MWTour.active", timeout=150000); pg.wait_for_timeout(1500)


def why(pg):
    pg.goto(f"{BASE}/twin.html?notour"); loaded(pg); pg.wait_for_timeout(2000)
    pg.click("#btnDemo")
    pg.wait_for_function("!document.getElementById('verdict').hidden && !/Checking/.test(document.getElementById('verdict').textContent)", timeout=30000)
    pg.wait_for_timeout(4000); pg.keyboard.press("w"); pg.wait_for_timeout(6000)
    pg.evaluate("() => { const p = document.querySelector('.mw-panel'); if (p) p.scrollTo({top: p.scrollHeight / 2, behavior: 'smooth'}); }"); pg.wait_for_timeout(5000)
    pg.evaluate("() => { const p = document.querySelector('.mw-panel'); if (p) p.scrollTo({top: p.scrollHeight, behavior: 'smooth'}); }"); pg.wait_for_timeout(5000)
    pg.keyboard.press("w"); pg.wait_for_timeout(2000)


def walk(pg):
    pg.goto(f"{BASE}/twin.html?notour"); loaded(pg); pg.wait_for_timeout(1500)
    pg.click("#btnDemo"); pg.wait_for_timeout(2500); pg.click("#btnWalk")
    pg.wait_for_function("window.__walk && window.__walk.on === true", timeout=120000); pg.wait_for_timeout(9000)
    pg.select_option("#wView", "follow"); pg.wait_for_timeout(12000)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(1500)


def layers(pg):                                   # 30 s demo 8-11.5 s: CRISM layer on, campaign route draws, GO verdict
    pg.goto(f"{BASE}/twin.html?notour"); loaded(pg); pg.wait_for_timeout(1500)
    pg.evaluate("document.getElementById('lyHyd').click()"); pg.wait_for_timeout(2500); pg.click("#btnDemo")
    pg.wait_for_function("!document.getElementById('verdict').hidden && !/Checking/.test(document.getElementById('verdict').textContent)", timeout=30000)
    pg.wait_for_timeout(3000); pg.evaluate("document.getElementById('lyHyd').click()"); pg.wait_for_timeout(1500)


def find(pg):                                     # 30 s demo: search "water", 3 destinations, return to start, plan
    pg.goto(f"{BASE}/twin.html?notour"); loaded(pg); pg.wait_for_timeout(1500)
    pg.locator("#tgtQ").scroll_into_view_if_needed(); pg.fill("#tgtQ", "water"); pg.wait_for_timeout(600)
    (pg.click("#tgtGo") if pg.locator("#tgtGo").count() else pg.keyboard.press("Enter")); pg.wait_for_function("document.querySelectorAll('#tgtList2 input[type=checkbox]').length >= 3", timeout=60000)
    pg.wait_for_timeout(1500)
    for i in range(3): pg.locator("#tgtList2 input[type=checkbox]").nth(i).check(); pg.wait_for_timeout(500)
    pg.check("#dstRet"); pg.click("#btnMulti")
    pg.wait_for_function("!document.getElementById('verdict').hidden && !/Checking/.test(document.getElementById('verdict').textContent)", timeout=60000)
    pg.wait_for_timeout(4000)


def mission_event(pg):                            # 30 s demo 20.5-24 s: dust event, re-plan, countdown to the ground reply
    pg.goto(f"{BASE}/mission.html"); pg.wait_for_function("window.__mission && window.__mission.log", timeout=30000)
    tl = pg.evaluate("() => window.__mission.log.mission.timeline.map(e => [e.kind, e.step])"); ev = dict(tl)["hazard"]; rep = dict(tl)["ground_reply"]
    if pg.locator("select").count(): pg.select_option("select", "60")
    pg.click("#play"); t = time.time()
    while time.time() - t < 90 and pg.evaluate("() => window.__mission.step") < ev: pg.wait_for_timeout(200)
    pg.wait_for_timeout(6000)


def mission(pg):
    pg.goto(f"{BASE}/mission.html"); pg.wait_for_function("window.__mission && window.__mission.log", timeout=30000); pg.wait_for_timeout(2500)
    if pg.locator("select").count(): pg.select_option("select", "60")
    pg.click("#play"); pg.wait_for_timeout(12000)
    pg.locator("#sLeak").scroll_into_view_if_needed(); pg.wait_for_timeout(2500); pg.click("#sLeak"); pg.wait_for_timeout(20000)
    smooth_scroll(pg, 0, 3000); pg.wait_for_timeout(15000)
    pg.locator("#sLeak").scroll_into_view_if_needed(); pg.wait_for_timeout(15000)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True,
                          args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=" + ("d3d11" if sys.platform == "win32" else "metal")])
    for name in CLIPS:
        tmp = os.path.join(OUT, "_" + name); shutil.rmtree(tmp, ignore_errors=True)
        ctx = b.new_context(viewport=SIZE, record_video_dir=tmp, record_video_size=VID)
        ctx.route("**/*", lambda r: r.abort() if not r.request.url.startswith(BASE) else r.continue_())
        pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "net::ERR_FAILED" not in m.text else None)
        t = time.time(); ok = True
        try: globals()[name](pg)
        except Exception as e: ok = False; errs.append(f"{type(e).__name__}: {str(e)[:300]}")
        vp = pg.video.path(); ctx.close()
        dst = os.path.join(OUT, name + ".webm"); shutil.move(vp, dst); shutil.rmtree(tmp, ignore_errors=True)
        report[name] = dict(ok=ok, seconds=round(time.time() - t, 1), mb=round(os.path.getsize(dst) / 1e6, 1), errors=errs[:5])
        print(("OK  " if ok else "FAIL"), name, report[name])
    b.close()
json.dump(report, open(os.path.join(OUT, "capture.json"), "w"), indent=1)
