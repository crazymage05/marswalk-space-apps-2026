"""D2 rehearsal: run the demo script (BUILD_PLAN section 7) end to end in headless Chrome with the network OFF.

usage: python tools/rehearsal.py <name> [port]        (serve demo/twin on the port first)
Every request not to 127.0.0.1 is aborted. Beats: entry page -> twin overview + a layer -> plan (GO with rule) and the
'why this route' overlay -> A* vs RL -> first-person walk with the visor -> follow view -> mission-control replay at 60x
(event, local proposal, countdown, ground reply, end). Times each beat, records errors and screenshots to
runs/twin_check/<name>/, writes rehearsal.json. Fails loudly if a beat does not reach its expected state.
"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name = sys.argv[1]; port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
OUT = os.path.join(ROOT, "runs", "twin_check", name); os.makedirs(OUT, exist_ok=True)
BASE = f"http://127.0.0.1:{port}"
beats, errors, blocked = [], [], set()


def beat(title, fn):
    t = time.time(); ok, info = True, ""
    try: info = fn() or ""
    except Exception as e: ok, info = False, f"{type(e).__name__}: {str(e)[:300]}"
    beats.append(dict(beat=title, ok=ok, seconds=round(time.time() - t, 1), info=info)); print(("OK  " if ok else "FAIL"), f"{time.time() - t:5.1f}s", title, "|", str(info)[:160])


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=" + ("d3d11" if sys.platform == "win32" else "metal")])
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.route("**/*", lambda r: (blocked.add(r.request.url.split("/")[2]), r.abort()) if not r.request.url.startswith(BASE) else r.continue_())
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "net::ERR_FAILED" not in m.text and "fonts.googleapis" not in m.text else None)
    t0 = time.time()

    def entry():
        pg.goto(f"{BASE}/index.html"); pg.wait_for_selector("text=Validation scoreboard", timeout=20000); pg.wait_for_timeout(800)
        rows = pg.evaluate("() => document.querySelectorAll('table tbody tr, .sb-card, [data-row]').length")
        pg.screenshot(path=os.path.join(OUT, "0_entry.png")); return f"scoreboard elements {rows}"
    beat("0:00 entry page (offline)", entry)

    def overview():
        pg.goto(f"{BASE}/twin.html?notour"); pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=180000)
        pg.check("#lyHyd"); pg.wait_for_timeout(1200); pg.screenshot(path=os.path.join(OUT, "1_overview_hydrated.png")); pg.uncheck("#lyHyd")
        return "layer 'hydrated minerals' on"
    beat("0:30 twin overview and a layer", overview)

    def planning():
        pg.click("#btnDemo"); pg.wait_for_function("!document.getElementById('verdict').hidden && !/Checking/.test(document.getElementById('verdict').textContent)", timeout=30000)
        v = pg.evaluate("document.querySelector('#verdict b.v').textContent"); assert v == "GO", v
        pg.locator("body").press("w"); pg.wait_for_timeout(1200); pg.screenshot(path=os.path.join(OUT, "2_plan_go_why.png")); pg.locator("body").press("w")
        return pg.inner_text("#verdict").replace("\n", " ")[:120]
    beat("1:00 plan, GO with rule, why this route", planning)

    def rl():
        opts = pg.evaluate("() => [...document.getElementById('cmpSel').options].map(o => o.value)")
        pick = next(o for o in opts if o not in ("off", "")); pg.select_option("#cmpSel", pick); pg.wait_for_timeout(1500)
        pg.screenshot(path=os.path.join(OUT, "3_astar_vs_rl.png")); txt = pg.inner_text("#status")[:120]; pg.select_option("#cmpSel", "off"); return f"{pick}: {txt}"
    beat("1:30 A* vs RL", rl)

    def walk():
        pg.click("#btnDemo"); pg.wait_for_timeout(800); pg.click("#btnWalk")
        pg.wait_for_function("window.__walk.on===true", timeout=240000); pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=240000)
        pg.wait_for_timeout(5000); v = pg.evaluate("() => window.__walk.visorVals"); assert v and v["t"] > 0, v
        pg.locator("#view").screenshot(path=os.path.join(OUT, "4_walk_visor.png"))
        pg.select_option("#wView", "follow"); pg.wait_for_timeout(3000); pg.locator("#view").screenshot(path=os.path.join(OUT, "5_walk_follow.png"))
        g = pg.evaluate("() => window.__walk.gaitState()"); pg.keyboard.press("Escape"); pg.wait_for_timeout(800)
        return f"visor t={v['t']:.0f}s e={v['e']:.0f}kJ limit={v['limit']} {v['limitUse'] * 100:.0f}%; steps {g['steps']}, prints {g['prints']}"
    beat("2:00 first-person walk, visor, follow view", walk)

    def mission():
        pg.goto(f"{BASE}/mission.html"); pg.wait_for_function("window.__mission && window.__mission.log", timeout=30000)
        tl = pg.evaluate("() => window.__mission.log.mission.timeline.map(e => [e.kind, e.step])"); ev = dict(tl)["hazard"]; rep = dict(tl)["ground_reply"]
        pg.select_option("select", "60") if pg.locator("select").count() else None
        pg.click("#play"); seen, shots = [], set()
        t = time.time()
        while time.time() - t < 120:
            st = pg.evaluate("() => window.__mission.step"); kinds = pg.evaluate("() => window.__mission.logShown()")
            for k in kinds:
                if k not in seen: seen.append(k)
            for label, at in (("6_event", ev), ("7_countdown", (ev + rep) // 2)):
                if st >= at and label not in shots: shots.add(label); pg.screenshot(path=os.path.join(OUT, label + ".png"))
            if st >= (ev + rep) // 2 and "skip" not in shots:
                shots.add("skip"); pg.click("#skip"); pg.wait_for_timeout(500); pg.screenshot(path=os.path.join(OUT, "8_reply.png"))
            if st >= len(pg.evaluate("() => window.__mission.log.steps")) - 1 and "eva_end" in kinds: break
            pg.wait_for_timeout(250)
        pg.screenshot(path=os.path.join(OUT, "9_end.png"))
        want = [k for k, _ in tl]; assert [k for k in seen if k in want] == want, f"order {seen}"
        return f"order {seen}; banner {pg.evaluate('() => window.__mission.banner()')}"
    beat("2:45 + 3:30 mission control: event, re-plan, countdown, skip, reply, end", mission)

    total = time.time() - t0
    b.close()
res = dict(total_s=round(total, 1), beats=beats, errors=errors, blocked_hosts=sorted(blocked), all_ok=all(x["ok"] for x in beats) and not errors)
json.dump(res, open(os.path.join(OUT, "rehearsal.json"), "w"), indent=1)
print(f"total {total:.0f} s; errors {errors[:3]}; blocked {sorted(blocked)}; ALL OK: {res['all_ok']}")
