"""D1 check: the twin's in-page flight rules (window.__flight.check) agree with phase4/safety_validator.py.

usage: python tools/rules_js_check.py [port] [n_random]
Builds good A* routes between random passable cells and adversarial mutations (teleport, steep, NaN, rough, low
confidence, off-grid, empty), runs Python validate + flight_decision (rate 6.45 uGy/h, as Python) and the page's check
on the same cells, and compares decision, deciding rule, set of failed rules, round-trip time and energy.
"""
import sys, os, json, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
import numpy as np
from playwright.sync_api import sync_playwright
from phase4 import costs, astar, astronaut as A, safety_validator as SV

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765; n_rand = int(sys.argv[2]) if len(sys.argv) > 2 else 20
g = costs.load_grid(); P = A.get_profile("nominal"); W, H = g["width"], g["height"]
S, RO, VF = g["slope_max_deg"], g["rough_max_m"], g["valid_frac"]
bl = costs.hard_blocked(g, P); free = np.flatnonzero(~bl.ravel()); rng = random.Random(5)
cases = []
while len([c for c in cases if c[0].startswith("route")]) < n_rand:
    a, b = int(rng.choice(free)), int(rng.choice(free))
    if abs(a // W - b // W) + abs(a % W - b % W) < 60: continue
    r = astar.plan(g, a, b, P)
    if r["success"]: cases.append((f"route{len(cases)}", r["route"]))
base = cases[0][1]
def first(mask): idx = np.argwhere(mask); return int(idx[0][0] * W + idx[0][1])
cases += [("teleport", base[:20] + base[40:]), ("steep", base[:10] + [first(np.nan_to_num(S) > 25)]),
          ("nan", [first(~np.isfinite(S))]), ("rough", [first((np.nan_to_num(RO) > 0.35) & (np.nan_to_num(S, nan=99) <= 25))]),
          ("lowvf", [first(np.nan_to_num(VF, nan=1) < 0.5)]), ("offgrid", base[:5] + [W * H + 3]), ("empty", [])]
rows = []
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=metal"]); pg = br.new_page(); err = []
    pg.on("pageerror", lambda e: err.append(str(e)))
    pg.goto(f"http://127.0.0.1:{port}/twin.html"); pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=180000)
    pg.wait_for_function("window.__flight != null"); exact = pg.evaluate("() => window.__flight.ready()"); print("exact rule mask loaded:", exact)
    for name, cells in cases:
        v = SV.validate(cells, g, P); d = SV.flight_decision(v, P); js = pg.evaluate(f"() => window.__flight.check({json.dumps(cells)}, 6.45)")
        sm = v["summary"]; pyf = sorted(d["rules_failed"]); jsf = sorted(js["rules_failed"])
        dt = abs(js["T"] - sm["roundtrip_time_s"]) / sm["roundtrip_time_s"] * 100 if js.get("T") and sm.get("roundtrip_time_s") else None
        de = abs(js["E"] - sm["roundtrip_energy_kj"]) / sm["roundtrip_energy_kj"] * 100 if js.get("E") and sm.get("roundtrip_energy_kj") else None
        ok = d["decision"] == js["decision"] and d["rule"] == js["rule"] and pyf == jsf
        rows.append(dict(case=name, n=len(cells), py=[d["decision"], d["rule"], pyf], js=[js["decision"], js["rule"], jsf], dT_pct=dt, dE_pct=de, agree=ok))
    br.close()
for r in rows: print(("OK  " if r["agree"] else "DIFF"), r["case"], r["n"], r["py"], r["js"], "dT%", r["dT_pct"] and round(r["dT_pct"], 3), "dE%", r["dE_pct"] and round(r["dE_pct"], 3))
agree = sum(r["agree"] for r in rows); wT = max([r["dT_pct"] for r in rows if r["dT_pct"] is not None] or [0]); wE = max([r["dE_pct"] for r in rows if r["dE_pct"] is not None] or [0])
print(f"agree {agree}/{len(rows)}; worst round-trip time diff {wT:.3f}%, energy {wE:.3f}%; page errors {err}")
os.makedirs(os.path.join(ROOT, "runs", "twin_check", "rules_js"), exist_ok=True)
json.dump(dict(rows=rows, agree=agree, n=len(rows), worst_dT_pct=wT, worst_dE_pct=wE, errors=err), open(os.path.join(ROOT, "runs", "twin_check", "rules_js", "rules_js.json"), "w"), indent=1, default=str)
