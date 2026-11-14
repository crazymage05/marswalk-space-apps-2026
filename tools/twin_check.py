"""Headless-Chrome verification of demo/twin/twin.html on a local server.
usage: python twin_check.py <pass_name> <width> <height> <port>
Writes screenshots and report.json to runs/twin_check/<pass_name>/.
Serve the page first: python -m http.server 8765 --bind 127.0.0.1 -d demo/twin"""
import json, os, re, sys, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name, Wd, Ht, port = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
OUT = os.path.join(ROOT, "runs", "twin_check", name)
os.makedirs(OUT, exist_ok=True)
URL = f"http://127.0.0.1:{port}/twin.html?notour"     # the guided tour (tour.js) is tested separately at the end
R = {"pass": name, "viewport": [Wd, Ht], "console_errors": [], "console_warnings": [], "page_errors": [],
     "failed_requests": [], "http_errors": [], "checks": []}


def check(label, ok, detail=""):
    R["checks"].append({"check": label, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + label + (f" - {detail}" if detail else ""), flush=True)


def shot(page, fn, full=False):
    page.screenshot(path=os.path.join(OUT, fn), full_page=full)


def white_pct(page):
    """Share (%) of pure-white pixels (all channels >= 250) in the 3D view canvas, from a fresh screenshot."""
    import io
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(io.BytesIO(page.locator("#view canvas").first.screenshot())).convert("RGB"))
    return round(float((a.min(-1) >= 250).mean() * 100), 1)


def txt(page, sel):
    return page.locator(sel).inner_text().strip()


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True,
                          args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=" + ("d3d11" if sys.platform == "win32" else "metal"), "--enable-webgl"])
    ctx = b.new_context(viewport={"width": Wd, "height": Ht}, device_scale_factor=1)
    page = ctx.new_page()
    page.on("console", lambda m: (R["console_errors"] if m.type == "error" else R["console_warnings"] if m.type == "warning" else []).append(m.text))
    page.on("pageerror", lambda e: R["page_errors"].append(str(e)))
    page.on("requestfailed", lambda q: R["failed_requests"].append(f"{q.url} {q.failure}"))
    page.on("response", lambda r: R["http_errors"].append(f"{r.status} {r.url}") if r.status >= 400 else None)

    t0 = time.time()
    page.goto(URL, wait_until="load", timeout=120000)
    page.wait_for_function("document.getElementById('loading').hidden === true", timeout=180000)
    page.wait_for_timeout(2500)
    R["load_s"] = round(time.time() - t0, 1)
    gl = page.evaluate("""() => { const c = document.createElement('canvas').getContext('webgl2');
        if (!c) return null; const d = c.getExtension('WEBGL_debug_renderer_info');
        return d ? c.getParameter(d.UNMASKED_RENDERER_WEBGL) : c.getParameter(c.RENDERER); }""")
    R["webgl_renderer"] = gl
    check("page loads and loading overlay clears", True, f"{R['load_s']} s, WebGL renderer: {gl}")
    shot(page, "01_overview.png")
    shot(page, "01_overview_full.png", full=True)

    # demo() runs on load: campaign start -> end
    stats0 = {k: txt(page, "#" + k) for k in ["sDist", "sTime", "sClimb", "sSteep", "sDose", "sTemp"]}
    R["initial_stats"] = stats0; R["initial_status"] = txt(page, "#status")
    check("campaign route planned on load", stats0["sDist"] not in ("–", "", "-"), json.dumps(stats0))

    # layers
    for lid in ["lyHaz", "lyTrav", "lyPhotos", "lyRoute", "lyStops", "lyHyd", "lyFe", "lyDawn"]:
        cb = page.locator("#" + lid)
        before = cb.is_checked()
        cb.click(); page.wait_for_timeout(700)
        after = cb.is_checked()
        shot(page, f"02_layer_{lid}_{'on' if after else 'off'}.png")
        legend = txt(page, "#lgTitle") if page.locator("#lgTitle").count() else ""
        check(f"layer toggle {lid}", after != before, f"{before}->{after}, legend '{legend}'")
        cb.click(); page.wait_for_timeout(300)

    # buttons
    for bid in ["btnDemo", "btnSci", "btnTrack"]:
        page.click("#" + bid); page.wait_for_timeout(2500)
        st = {k: txt(page, "#" + k) for k in ["sDist", "sTime", "sClimb", "sSteep", "sDose"]}
        status = txt(page, "#status")
        R[f"btn_{bid}"] = {"stats": st, "status": status}
        shot(page, f"03_{bid}.png")
        check(f"button {bid} plans a route", st["sDist"] not in ("–", "", "-") and "No path" not in status, f"{st} | {status[:160]}")
        if bid == "btnDemo":   # D1: the in-page flight rules give a verdict for the planned route, equal to Python's
            page.wait_for_function("!document.getElementById('verdict').hidden && /GO/.test(document.getElementById('verdict').textContent) && !/Checking/.test(document.getElementById('verdict').textContent)", timeout=30000)
            vt = txt(page, "#verdict"); sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from phase4 import costs as _C, astronaut as _A, safety_validator as _SV
            rc = page.evaluate("() => window.__routeCells ? window.__routeCells() : null")
            py = _SV.flight_decision(_SV.validate(rc, _C.load_grid(), _A.get_profile("nominal")), _A.get_profile("nominal")) if rc else None
            check("flight-rule verdict shown for the planned route and equal to the Python validator",
                  py is not None and page.evaluate("document.querySelector('#verdict b.v').textContent") == py["decision"] and (py["rule"] is None or py["rule"] in vt), f"page: {vt[:140]} | python: {py and py['text']}")
    page.click("#btnClear"); page.wait_for_timeout(500)
    check("Clear resets stats", txt(page, "#sDist") in ("–", "-", ""), txt(page, "#hint"))
    check("Clear hides the verdict", page.evaluate("document.getElementById('verdict').hidden"), "")

    # manual click planning on the 3D view
    page.uncheck("#lyPhotos")                      # photo pins would catch the clicks (a pin click opens the photo instead)
    page.locator("#view").scroll_into_view_if_needed(); page.wait_for_timeout(500)
    cv = page.locator("#view canvas").first
    bb = cv.bounding_box()
    tries = []
    for (a, c) in [((0.40, 0.40), (0.62, 0.62)), ((0.50, 0.30), (0.50, 0.70)), ((0.35, 0.60), (0.60, 0.40))]:
        for fx, fy in (a, c):
            x, y = bb["x"] + bb["width"] * fx, bb["y"] + bb["height"] * fy
            page.mouse.move(x, y); page.mouse.down(); page.mouse.up(); page.wait_for_timeout(1200)
        st = {k: txt(page, "#" + k) for k in ["sDist", "sTime", "sClimb", "sSteep", "sDose"]}
        tries.append({"stats": st, "status": txt(page, "#status")})
        if st["sDist"] not in ("–", "", "-"):
            break
    R["manual_plan"] = tries
    shot(page, "04_manual_plan.png")
    check("manual click start + end plans a route (real pointer clicks on the 3D map)", st["sDist"] not in ("–", "", "-"),
          f"{len(tries)} pair(s): " + " | ".join(f"{t['stats']['sDist']} {t['status'][:70]}" for t in tries))
    page.check("#lyPhotos")

    # cell inspector vs world_cells.json
    page.locator("#view").scroll_into_view_if_needed(); page.wait_for_timeout(300); bb = cv.bounding_box()
    page.mouse.move(bb["x"] + bb["width"] * 0.5, bb["y"] + bb["height"] * 0.5); page.wait_for_timeout(900)
    card_hidden = page.evaluate("document.getElementById('cellCard').hidden")
    cell = page.evaluate("document.getElementById('cellCard').dataset.cell")
    card = txt(page, "#cellCard") if not card_hidden else ""
    R["cell_card"] = {"cell": cell, "text": card}
    shot(page, "05_cell_card.png")
    check("cell inspector shows the 4 m cell under the cursor", (not card_hidden) and bool(cell), f"cell {cell}: {card[:200]!r}")

    # A* vs RL selector vs routes_rl.json
    rl = json.load(open(os.path.join(ROOT, "data/processed/roi/routes_rl.json")))
    opts = page.locator("#cmpSel option").all_inner_texts()
    R["cmp_options"] = opts
    check("A* vs RL selector lists every evaluated scenario", len(opts) - 1 == len(rl["scenarios"]), f"{len(opts) - 1} options vs {len(rl['scenarios'])} scenarios")
    mism = []
    for k, s in enumerate(rl["scenarios"]):
        page.select_option("#cmpSel", str(k)); page.wait_for_timeout(350)
        note = txt(page, "#cmpNote")
        nums = [float(x) for x in re.findall(r"([\d.]+) km", note)]
        a_km = (s["astar"]["distance_m"] or 0) / 1000
        ok = nums and abs(nums[0] - round(a_km, 2)) < 0.006
        if s["reached_goal"]:
            ok = ok and len(nums) > 1 and abs(nums[1] - round(s["distance_m"] / 1000, 2)) < 0.006 and "passes" in note
        else:
            ok = ok and "did not reach" in note
        if not ok:
            mism.append((s["id"], note, round(a_km, 3), round(s["distance_m"] / 1000, 3), s["reached_goal"], s["validator_ok"]))
        if k in (0, 1, 2):
            shot(page, f"06_cmp_{s['id']}.png")
    R["cmp_mismatches"] = mism
    check("A* vs RL notes match routes_rl.json for every scenario", not mism, f"{len(mism)} mismatches: {mism[:3]}")
    page.select_option("#cmpSel", "")

    # first-person walk on the campaign route
    page.click("#btnDemo"); page.wait_for_timeout(1500)
    page.click("#btnWalk")
    page.wait_for_function("window.__walk && window.__walk.on === true", timeout=240000)
    page.wait_for_function("document.getElementById('loading').hidden === true", timeout=240000)
    page.wait_for_timeout(3000)
    hud_ids = ["wSol", "wTime", "wSun", "wDist", "wEl", "wSlope", "wElev", "wDose"]
    samples = []
    for i in range(4):
        samples.append({k: txt(page, "#" + k) for k in hud_ids} | {"s": page.evaluate("window.__walk.s")})
        shot(page, f"07_walk_fp_{i}.png")
        page.wait_for_timeout(4000)
    R["walk_samples"] = samples
    adv = samples[-1]["s"] > samples[0]["s"] and samples[-1]["wDist"] != samples[0]["wDist"] and samples[-1]["wTime"] != samples[0]["wTime"]
    check("walk advances: position, walked distance and clock change", adv, f"s {samples[0]['s']:.1f} -> {samples[-1]['s']:.1f}; {samples[0]['wDist']} -> {samples[-1]['wDist']}; {samples[0]['wTime']} -> {samples[-1]['wTime']}")
    page.select_option("#wView", "follow"); page.wait_for_timeout(2500); shot(page, "08_walk_follow.png")
    page.click("#wCardBtn"); page.wait_for_timeout(1500)
    wcell = txt(page, "#wCell") if not page.evaluate("document.getElementById('wCell').hidden") else ""
    check("'Ground here' card shows data in walk mode", bool(wcell), wcell[:160])
    shot(page, "09_walk_groundcard.png")
    page.click("#wCardBtn"); page.select_option("#wView", "fp")
    page.keyboard.press("Space"); page.wait_for_timeout(300)
    s1 = page.evaluate("window.__walk.s"); page.wait_for_timeout(2000); s2 = page.evaluate("window.__walk.s")
    check("Space pauses the walk", abs(s2 - s1) < 1e-6 and txt(page, "#wPlay") == "Play", f"s {s1:.2f} -> {s2:.2f}, button '{txt(page, '#wPlay')}'")
    page.keyboard.press("Space")
    # ground texture close-up (seam check): look down
    page.evaluate("window.__walk.pitch = -0.9"); page.keyboard.press("Space"); page.wait_for_timeout(1200)
    shot(page, "10_walk_ground_closeup.png"); page.keyboard.press("Space")
    page.keyboard.press("Escape"); page.wait_for_timeout(800)
    check("Esc leaves walk mode", page.evaluate("window.__walk.on") is False and page.evaluate("document.getElementById('walkHud').hidden"), "")

    # Curiosity's track: visit every rover 3D scan
    page.click("#btnTrack"); page.wait_for_timeout(2500)
    page.click("#btnWalk"); page.wait_for_function("window.__walk.on === true", timeout=120000); page.wait_for_timeout(2500)
    page.keyboard.press("Space")    # pause, then jump
    scans = page.evaluate("window.__walk.scans()")
    R["scans_in_page"] = scans
    n_idx = len(json.load(open(os.path.join(ROOT, "demo", "twin", "meshes", "meshes_index.json"))))
    check(f"all {n_idx} rover 3D scans in meshes_index.json are loaded in walk mode", len(scans) == n_idx and len({s['sol'] for s in scans}) == n_idx,
          f"{len(scans)} scans: {sorted(s['sol'] for s in scans)}")
    seen = []
    for k, sc in enumerate(scans):
        d = page.evaluate(f"window.__walk.jumpNear({sc['x']}, {sc['z']})")
        page.keyboard.press("Space"); page.wait_for_timeout(1800); page.keyboard.press("Space"); page.wait_for_timeout(400)
        lab = txt(page, "#wScan") if not page.evaluate("document.getElementById('wScanBox').hidden") else ""
        ph = page.evaluate("document.getElementById('wPhoto').hidden")
        seen.append({"sol": sc["sol"], "route_dist_m": round(d, 1), "hud": lab, "photo_shown": not ph})
        shot(page, f"11_scan_{sc['sol']}.png")
        seen[-1]["white_pct"] = white_pct(page)
    R["scan_visits"] = seen
    worst = max(seen, key=lambda s: s["white_pct"])
    check("no blown-out (pure white) rover scan in the walk view: <= 5% of the 3D view at every scan", worst["white_pct"] <= 5,
          f"worst sol {worst['sol']}: {worst['white_pct']}%; all: {[(s['sol'], s['white_pct']) for s in seen]}")
    on = [s for s in seen if s["route_dist_m"] <= 10]; off = [s["sol"] for s in seen if s["route_dist_m"] > 10]
    ok = len(on) >= 1 and all(str(s["sol"]) in s["hud"] for s in on)
    check("walker standing at each on-route scan (<= 10 m from the track) sees 'Curiosity 3D scan, sol N' for the right sol", ok,
          f"{len(on)} on route; off route (not reachable by the walker, listed only): {off}; " + json.dumps(seen))
    page.keyboard.press("Escape"); page.wait_for_timeout(600)

    # sol slider changes dose/temperature
    page.click("#btnDemo"); page.wait_for_timeout(1500)
    t_a, so_a = txt(page, "#sTemp"), txt(page, "#solOut")
    page.locator("#sol").fill("4750"); page.locator("#sol").dispatch_event("input"); page.wait_for_timeout(1000)
    t_b, so_b = txt(page, "#sTemp"), txt(page, "#solOut")
    check("changing the sol slider updates the sol and that sol's air temperature",
          so_a != so_b and t_b not in ("–", "", "-") and t_a != t_b, f"sol {so_a} -> {so_b}; temp {t_a} -> {t_b}")
    R["sol_temp"] = [t_a, t_b]
    shot(page, "12_final.png", full=True)
    # B's additions (tour.js, why_route.js): the "why this route" overlay agrees with the validator panel, and the tour
    # runs to its end on a fresh page (no localStorage) and leaves the page usable
    page.click("#btnDemo"); page.wait_for_timeout(2000)
    page.wait_for_function("!document.getElementById('verdict').hidden && !/Checking/.test(document.getElementById('verdict').textContent)", timeout=30000)
    panel = page.evaluate("document.querySelector('#verdict b.v').textContent")
    page.locator("body").press("w"); page.wait_for_timeout(1500)
    ov = page.evaluate("""() => { const t = [...document.querySelectorAll('.mw-r')].find(r => /Validator decision/.test(r.textContent));
        const vis = [...document.querySelectorAll('div,section,aside')].some(e => /Flight rules checked/.test(e.textContent) && e.offsetParent !== null && e.children.length < 400);
        return { dec: t ? t.querySelector('b').textContent : null, visible: vis }; }""")
    check("'why this route' overlay opens with W and its validator decision equals the GO/NO-GO panel",
          bool(ov["visible"]) and ov["dec"] is not None and ov["dec"].split()[0] == panel, f"panel {panel} | overlay {ov}")
    page.locator("body").press("w"); page.wait_for_timeout(500)
    tp = ctx.new_page(); terr = []
    tp.on("pageerror", lambda e: terr.append(str(e))); tp.on("console", lambda m: terr.append(m.text) if m.type == "error" else None)
    tp.add_init_script("window.__tourSpeed = 20; try { localStorage.clear(); } catch (e) {}")
    tp.goto(f"http://127.0.0.1:{port}/twin.html", wait_until="load", timeout=120000)
    tp.wait_for_function("document.getElementById('loading').hidden === true", timeout=180000)
    try:
        tp.wait_for_function("window.MWTour && window.MWTour.steps > 0 && !window.MWTour.active", timeout=120000)
        tl = tp.evaluate("() => ({ steps: window.MWTour.steps, log: window.MWTour.log, card: document.getElementById('tourCard').hidden })")
    except Exception as e:
        tl = {"error": str(e)[:200]}
    tp.evaluate("() => { if (window.__walk && window.__walk.on) document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); }"); tp.wait_for_timeout(1500)
    tp.click("#btnDemo"); tp.wait_for_timeout(2500)
    after = tp.inner_text("#sDist")
    check("guided tour runs to its end on first visit, hides its card, and the page still plans a route",
          "error" not in tl and tl.get("card") is True and len(tl.get("log", [])) == tl.get("steps") and after not in ("–", "-", "") and not terr,
          f"{tl} | distance after tour: {after} | errors: {terr[:2]}")
    tp.close()
    # share links (share.js): a multi-stop route (science walk) and the sol survive the round trip exactly
    sp = ctx.new_page(); sp.goto(URL, wait_until="load", timeout=120000)
    sp.wait_for_function("document.getElementById('loading').hidden === true", timeout=180000)
    sp.click("#btnSci"); sp.wait_for_timeout(2500); sp.locator("#sol").fill("4700"); sp.locator("#sol").dispatch_event("input"); sp.wait_for_timeout(300)
    orig = sp.evaluate("() => window.__routeCells()"); sp.click("#shareBtn"); sp.wait_for_timeout(600); link = sp.evaluate("() => location.href")
    rp = ctx.new_page(); rerr = []; rp.on("pageerror", lambda e: rerr.append(str(e)))
    rp.goto(link, wait_until="load", timeout=120000); rp.wait_for_function("document.getElementById('loading').hidden === true", timeout=180000); rp.wait_for_timeout(4000)
    back = rp.evaluate("() => [window.__routeCells(), document.getElementById('sol').value]")
    check("share link restores the same multi-stop route and sol", orig is not None and back[0] == orig and back[1] == "4700" and not rerr,
          f"{link.split('#')[-1]} | {len(orig or [])} vs {len(back[0] or [])} cells, sol {back[1]} | errors {rerr[:1]}")
    sp.close(); rp.close()
    b.close()

R["n_checks"] = len(R["checks"]); R["n_failed"] = sum(not c["ok"] for c in R["checks"])
json.dump(R, open(os.path.join(OUT, "report.json"), "w"), indent=1)
print(f"\n{name}: {R['n_checks'] - R['n_failed']}/{R['n_checks']} checks passed; console errors {len(R['console_errors'])}, "
      f"page errors {len(R['page_errors'])}, failed requests {len(R['failed_requests'])}, HTTP errors {len(R['http_errors'])}")
for k in ("console_errors", "page_errors", "failed_requests", "http_errors"):
    for x in R[k][:10]:
        print(f"  {k}: {x[:240]}")
