"""Validation scoreboard for the entry page: demo/twin/scoreboard.json, built only from real outputs.

usage: python tools/scoreboard.py [twin_check_pass_desktop] [twin_check_pass_phone]
Runs the Python test suites (phase4/tests_env.py, tests_nav.py, tests_rules.py, phase5/tests_hazard.py) and parses the
result files the browser checks wrote under runs/twin_check/ (twin_check report.json, hud_check, gait_check, sv_check,
mission_check). Every row names its source so a reader can rerun it. A missing result file becomes a row with
result "not run", never a pass.
"""
import json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")
RUNS = os.path.join(ROOT, "runs", "twin_check")
rows = []


def row(area, check, result, numbers, source, measured="computed"):
    rows.append(dict(area=area, check=check, result=result, numbers=numbers, source=source, kind=measured))


def suite(path, area, what):
    t = time.time(); r = subprocess.run([PY, path], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    out = r.stdout + r.stderr
    m = re.findall(r"(\d+)/(\d+) (?:checks )?passed", out); n_pass = out.count("\nPASS") + (1 if out.startswith("PASS") else 0)
    if m: a, b = map(int, m[-1])
    else: a, b = n_pass, n_pass + out.count("\nFAIL") + (1 if out.startswith("FAIL") else 0)
    row(area, what, "pass" if r.returncode == 0 and a == b and b > 0 else "fail", f"{a}/{b} in {time.time() - t:.0f} s", path)


def load(p):
    p = os.path.join(RUNS, p); return json.load(open(p)) if os.path.exists(p) else None


suite("phase4/tests_env.py", "RL environment", "Gymnasium environment: actions, shaping, termination, determinism")
suite("phase4/tests_nav.py", "Planner", "A* vs independent Dijkstra, validator catches broken routes, recommended planner")
suite("phase4/tests_rules.py", "Flight rules", "16 adversarial routes NO-GO by the expected rule; GO/NO-GO/ABORT logic")
suite("phase5/tests_hazard.py", "Hazards", "Dust event reproducible; re-plan avoids every blocked cell and passes the validator")

desk = sys.argv[1] if len(sys.argv) > 1 else None; phone = sys.argv[2] if len(sys.argv) > 2 else None
for name, label in ((desk, "desktop 1440 px"), (phone, "phone 400 px")):
    r = load(f"{name}/report.json") if name else None
    if r is None: row("Browser", f"Twin page, {label}", "not run", "-", "tools/twin_check.py"); continue
    n_ok = sum(1 for c in r["checks"] if c.get("ok") or c.get("pass") or c.get("result") == "PASS")
    errs = len(r["console_errors"]) + len(r["page_errors"]) + len(r["failed_requests"]) + len(r["http_errors"])
    row("Browser", f"Twin page, {label}: every control, walk, scans, sol slider", "pass" if r["pass"] and errs == 0 else "fail",
        f"{n_ok}/{len(r['checks'])} checks, {errs} errors, GPU: {r.get('webgl_renderer', '?')[:40]}", f"tools/twin_check.py ({name})")

h = load("hud_check/hud_check.json")
if h:
    worst = max(abs(v[2]) for rw in h["rows"] for k, v in rw["comp"].items() if k != "dose_vs_pyrate")
    row("Suit model", "Helmet HUD equals the Python astronaut model and validator (start, middle, end, 3 random)",
        "pass" if worst < 1 and not h["errors"] else "fail", f"worst difference {worst:.2f}% (target 1%)", "tools/hud_check.py (independent agent)")
else: row("Suit model", "Helmet HUD vs Python", "not run", "-", "tools/hud_check.py")

g = load("gait_check/results.json")
if g:
    sl = max(g[k]["slide_max_cm"] for k in ("flat_w1", "slope_w1", "w15")); vm = max(abs(g[k]["vert_med_cm"]) for k in ("flat_w1", "slope_w1", "w15"))
    row("Walking astronaut", "Planted feet do not slide; boots on the ground (flat, 8.5 deg slope, 15x speed)",
        "pass" if sl < 5 and vm < 2 and not g["console_errors"] else "fail", f"max slide {sl:.1f} cm (target 5), ankle height median {vm:.2f} cm", "tools/gait_check.py (independent agent)")
else: row("Walking astronaut", "Foot slide", "not run", "-", "tools/gait_check.py")

s = load("sv_check/sv_check.json")
if s: row("Terrain light", "Terrain occlusion on the GPU equals the stored sky-view layers", "pass" if s["pass"] and not s["console_errors"] else "fail",
          f"{s['n']} points, max difference {s['max_abs_diff']:.4f} (target 0.01)", "tools/sv_check.py")
else: row("Terrain light", "Terrain occlusion", "not run", "-", "tools/sv_check.py")

mp = os.path.join(RUNS, "mission_check", "report.txt")
if os.path.exists(mp):
    t = open(mp).read(); npass, nfail = len(re.findall(r"^PASS", t, re.M)), len(re.findall(r"^FAIL", t, re.M))
    steps = re.search(r"hook exact: (\d+)/(\d+)", t)
    row("Mission control", "Every tile equals the mission log at every step; replay order; light-time countdown",
        "pass" if nfail == 0 and npass > 0 else "fail", f"{npass} checks passed, {nfail} failed" + (f"; tiles exact at {steps.group(1)}/{steps.group(2)} steps" if steps else ""),
        "tools/mission_check.py (independent agent)")
else: row("Mission control", "Mission page vs log", "not run", "-", "tools/mission_check.py")

# labelled data provenance (what is measured and what is modelled), for the page's legend
prov = [dict(item="Terrain (HiRISE 1 m stereo DTM, 25 cm image)", kind="measured"),
        dict(item="Curiosity Navcam 3D scans and photos, rover track", kind="measured"),
        dict(item="REMS weather at the rover; RAD dose rate per sol", kind="measured"),
        dict(item="Dust optical depth: Mastcam climatology for the season (not a 2025 measurement)", kind="derived"),
        dict(item="Mars-Earth light-time (JPL Horizons)", kind="computed"),
        dict(item="Ground temperature and dose per cell, sky view, insolation", kind="modelled"),
        dict(item="Astronaut speed, energy and fatigue (suited reduced-gravity data, v2)", kind="modelled"),
        dict(item="Dust event and its re-plan", kind="SIMULATED")]
out = dict(generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), rows=rows, provenance=prov,
           summary=dict(passed=sum(r["result"] == "pass" for r in rows), failed=sum(r["result"] == "fail" for r in rows),
                        not_run=sum(r["result"] == "not run" for r in rows)))
json.dump(out, open(os.path.join(ROOT, "demo", "twin", "scoreboard.json"), "w"), indent=1)
for r in rows: print(f"{r['result']:8s} {r['area']:18s} {r['numbers']}")
print(out["summary"])
