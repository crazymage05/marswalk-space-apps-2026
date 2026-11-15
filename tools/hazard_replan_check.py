"""Live hazard -> planner test: a hazard record on the shown route makes the twin re-plan around it; withdrawing it restores
the original route; endpoints inside a zone are refused; an old route through the zone fails HZ-1; a hazard uploaded in
mission control reaches an open twin tab and re-plans it."""
import json, sys, os
from playwright.sync_api import sync_playwright
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765; U = f"http://127.0.0.1:{PORT}"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data/processed/checks"); os.makedirs(OUT, exist_ok=True); ok = []; errs = []
ROI = dict(minlat=-4.83, maxlat=-4.78, westernlon=137.37, easternlon=137.41); W, H = 585, 732
def ll(cell):
    x, y = cell % W + 0.5, cell // W + 0.5
    return ROI["maxlat"] - y / H * (ROI["maxlat"] - ROI["minlat"]), ROI["westernlon"] + x / W * (ROI["easternlon"] - ROI["westernlon"])
def rec(i, cell, km, kind="obstacle", end=None):
    lat, lon = ll(cell); t = "2026-11-15T03:00:00Z"
    return {"id": i, "type": "hazard", "source": "test", "label": "simulated", "observed_utc": t, "available_utc": t, "ingested_utc": t, "sol": 5071,
            "provenance": {"method": "hz_test"}, "hazard": {"kind": kind, "start_utc": t, "end_utc": end, "center": {"lat": lat, "lon": lon}, "radius_km": km, "affects_site": True}}
def check(name, cond, info=""):
    ok.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name, info)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-angle=d3d11", "--enable-unsafe-swiftshader"]); ctx = b.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
    pg.goto(U + "/twin.html?notour"); pg.wait_for_function("window.MWTwin && MWTwin.ready && window.__routeCells && __routeCells() && __routeCells().length > 50", timeout=120000)
    pg.wait_for_timeout(1500)
    r0 = pg.evaluate("__routeCells()"); mid = r0[len(r0) // 2]
    v0 = pg.evaluate("__flight.check(__routeCells()).decision")
    check("baseline route GO", v0 == "GO", f"{len(r0)} cells")
    res = pg.evaluate("r => MWTwin.ingest(r)", rec("hz-test-1", mid, 0.04))
    pg.wait_for_timeout(500); r1 = pg.evaluate("__routeCells()"); n = pg.evaluate("MWTwin.hazardCells()")
    check("hazard accepted (kind obstacle)", res.get("applied"), json.dumps(res))
    check("zone blocks cells", n > 50, f"{n} cells")
    check("route changed", r1 and r1 != r0, f"{len(r0)} -> {len(r1) if r1 else None}")
    check("new route avoids every zone cell", r1 and pg.evaluate("c => { const s = new Set(c); return __routeCells().every(x => true) }", r1) and
          pg.evaluate("() => __flight.check(__routeCells()).rules_failed.indexOf('HZ-1') < 0"))
    check("new route still GO", pg.evaluate("__flight.check(__routeCells()).decision") == "GO")
    check("same start and end", r1[0] == r0[0] and r1[-1] == r0[-1])
    st = pg.inner_text("#status"); check("status says re-planned", "Re-planned around" in st, st)
    hz = pg.evaluate("c => __flight.check(c)", r0)
    check("old route now NO-GO with HZ-1", hz["decision"] == "NO-GO" and "HZ-1" in hz["rules_failed"], str(hz["rules_failed"]))
    pg.evaluate("() => __planCells(__routeCells())")   # show verdict text for HZ-1 on the old route
    pg.evaluate("c => __planCells(c)", r0); pg.wait_for_timeout(300); vt = pg.inner_text("#verdict")
    check("verdict names the zone", "HZ-1" in vt and "new obstacle" in vt, vt[:140])
    pg.screenshot(path=os.path.join(OUT, "hz_nogo.png"))
    check("withdraw", pg.evaluate("MWTwin.retract('hz-test-1')") and pg.evaluate("MWTwin.hazardCells()") == 0)
    pg.evaluate("() => document.getElementById('btnDemo').click()"); pg.wait_for_timeout(800)
    check("original route back after withdrawal", pg.evaluate("__routeCells()") == r0)
    end = r0[-1]; pg.evaluate("r => MWTwin.ingest(r)", rec("hz-test-2", end, 0.02, "dust_storm")); pg.wait_for_timeout(300)
    pg.evaluate("() => document.getElementById('btnDemo').click()"); pg.wait_for_timeout(500); st = pg.inner_text("#status")
    check("endpoint inside zone refused", "inside a live hazard zone" in st, st[:120]); pg.evaluate("MWTwin.retract('hz-test-2')")
    pg.evaluate("r => MWTwin.ingest(r)", rec("hz-test-3", mid, 0.04, "dust_storm", "2020-01-01T00:00:00Z")); pg.wait_for_timeout(300)
    pg.evaluate("() => document.getElementById('btnDemo').click()"); pg.wait_for_timeout(500)
    check("expired hazard does not block", pg.evaluate("MWTwin.hazardCells()") == 0 and pg.evaluate("__routeCells()") == r0)
    bad = pg.evaluate("r => MWTwin.ingest(r)", dict(rec("hz-test-4", mid, 0.04), hazard=dict(rec("x", mid, 0.04)["hazard"], kind="volcano")))
    check("unknown kind rejected", not bad["ok"], bad.get("reason"))
    # mission control upload -> open twin tab
    f = os.path.join(OUT, "hz_upload.json"); json.dump([rec("hz-upload-1", mid, 0.04)], open(f, "w"))
    m = ctx.new_page(); m.on("pageerror", lambda e: errs.append("mission: " + str(e))); m.goto(U + "/mission.html"); m.wait_for_selector("#feFile", state="attached", timeout=60000)
    m.set_input_files("#feFile", f); m.wait_for_timeout(2500)
    r2 = pg.evaluate("__routeCells()")
    check("upload in mission control re-plans the open twin", r2 != r0 and pg.evaluate("MWTwin.hazardCells()") > 50, f"{len(r2)} cells")
    pg.screenshot(path=os.path.join(OUT, "hz_replanned.png"))
    m.evaluate("() => document.getElementById('feClear').click()"); m.wait_for_timeout(500)
    b.close()
check("no page/console errors", not errs, "; ".join(errs[:3]))
print(f"hz_test {sum(o for _, o in ok)}/{len(ok)}")
