"""Reads from the twin page (headless): sun az/el per LMST on sol 4600 (the page's own sunDir), three campaign-route walk poses,
tau climatology value, corridor origin in world coords, zMean. Writes runs/bake/page_facts.json. Helper for tools/bake_ground.py."""
import http.server, json, os, sys, threading
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8790
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=os.path.join(ROOT, "demo", "twin"), **k)
    def log_message(s, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
TIMES = [8, 10, 12, 14, 16]; FR = [0.1, 0.5, 0.85]
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=d3d11"])
    pg = b.new_context(viewport={"width": 960, "height": 540}).new_page()
    pg.goto(f"http://127.0.0.1:{PORT}/twin.html?notour", timeout=120000)
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=240000)
    pg.click("#btnDemo"); pg.wait_for_timeout(1500)
    pg.click("#btnWalk"); pg.wait_for_function("window.__walk.on===true", timeout=240000)
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=240000)
    pg.wait_for_timeout(2500); pg.keyboard.press("Space")
    out = pg.evaluate("""([T, FR]) => { const W = window.__walk, L = W.routeLength();
      const sun = T.map(t => { const s = W.sunDir(t, 4600); return { lmst: t, az: s.az, el: s.el, ls: s.ls }; });
      const poses = FR.map(f => { const s = L * f, p = W.routeAt(s), a = W.routeAt(Math.min(L, s + 10));
        return { frac: f, s, pos: p, ahead: a, yaw: Math.atan2(a[0] - p[0], -(a[2] - p[2])), ground_y: W.groundY(p[0], p[2]) }; });
      return { sun, poses, route_len: L, tau: W.tau, pitch_default: W.pitch, fov: W.cam.fov, near: W.cam.near }; }""", [TIMES, FR])
    b.close()
os.makedirs(os.path.join(ROOT, "runs", "bake"), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, "runs", "bake", "page_facts.json"), "w"), indent=1); print(json.dumps(out, indent=1))
