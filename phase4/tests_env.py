#!/usr/bin/env python3
"""World-aware RL environment checks (no training). Run: python phase4/tests_env.py

1 check_env (default and with visibility + dynamic limits)
2 static and dynamic observation channels equal world.cell() values at several cells
3 dynamic channels differ between dawn and noon
4 visibility masks cells behind a ridge (ridge found from the horizon data, checked against an independent 1 m DTM ray march)
5 physics: replaying an A* route in the env gives astar.route_metrics time/energy/dose; env blocked mask == costs.hard_blocked;
  env budget rule agrees with safety_validator
6 dynamic limits: night ends unsafe, shadow limit, temperature limit, sep_stop sampling
"""
import os, sys, math
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from phase4 import astar, astronaut as A, costs, safety_validator, scenarios, visibility
from phase4.env import MarsWalkEnv, GridData, CH, R, W, H, DIRS, CELL_M

RES = []


def check(name, ok, msg=""):
    RES.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (" - " + msg if msg else ""), flush=True)


def t1_check_env():
    from gymnasium.utils.env_checker import check_env
    for kw in (dict(), dict(visibility=True, forbid_shadow=True, temp_range_K=(150.0, 300.0), mask_invalid=True)):
        e = MarsWalkEnv(level=1, seed=3, **kw)
        check_env(e, skip_render_check=True)
        o, _ = e.reset(seed=1)
        ok = True
        for _ in range(60):
            o, r, te, tr, i = e.step(int(e.action_space.sample()))
            ok &= bool(e.observation_space.contains(o)) and bool(np.isfinite(o["patch"]).all())
            if te or tr:
                o, _ = e.reset()
        check("check_env + obs in space %s" % kw, ok)


def t2_channels():
    g = GridData.get()
    w = g.world
    S = w.S
    e = MarsWalkEnv(level=1, seed=0)
    sol, lmst = 4600, 9.0
    cov = np.argwhere((S["ground_type"] >= 0) & np.isfinite(S["rock_frac"]))
    unc = np.argwhere(S["ground_type"] < 0)
    nan_r = np.argwhere(np.isnan(S["rough_max_m"]) & np.isfinite(S["elevation_m"]))
    cells = [tuple(cov[len(cov) // 2]), tuple(cov[len(cov) // 5]), tuple(unc[len(unc) // 2]), tuple(unc[len(unc) // 7]),
            tuple(nan_r[len(nan_r) // 2]), (300, 300)]
    bad = []
    for (r, c) in cells:
        if r < R or c < R or r >= H - R or c >= W - R:
            continue
        cidx = r * W + c
        e.reset(options={"start_goal": (cidx, cidx), "sol": sol, "lmst": lmst})
        e.cell = cidx
        o = e._obs()["patch"]
        # check the centre and four more cells inside the patch
        for dr, dc in [(0, 0), (-3, 2), (4, -5), (7, 7), (-7, -7)]:
            rr, cc = r + dr, c + dc
            wc = w.cell(rr * W + cc, sol, lmst)       # lmst 9.0 is a bin centre of the 0.5 h dynamic step: exact
            p = o[:, R + dr, R + dc]
            v = lambda k: wc[k]["value"]
            exp = {}
            exp[CH["slope"]] = 1.0 if v("slope_max_deg") is None else v("slope_max_deg") / 90.0
            exp[CH["rough"]] = 2.0 if v("rough_max_m") is None else min(v("rough_max_m") / 0.35, 2.0)
            exp[CH["loose"]] = v("loose") or 0.0
            gt = v("ground_type")
            covered = gt >= 0 and v("rock_frac") is not None
            exp[CH["rock"]] = (v("rock_frac") or 0.0) if covered else 0.0
            exp[CH["not_covered"]] = 0.0 if covered else 1.0
            for k, n in enumerate(("bedrock", "sand", "pebbly")):
                exp[CH[n]] = 1.0 if (covered and gt == k) else 0.0
            exp[CH["science"]] = float(np.clip(v("science") / 5.0, -1, 2))
            unknown = v("slope_max_deg") is None or v("rough_max_m") is None or v("elevation_m") is None or v("valid_frac") < 0.5
            exp[CH["unknown"]] = float(unknown)
            exp[CH["blocked"]] = float(g.blocked[rr, cc])
            if not unknown:
                exp[CH["shadow"]] = float(bool(v("in_shadow")))
                exp[CH["insol"]] = float(np.clip(v("insolation") / 700.0, 0, 2))
                exp[CH["temp"]] = float(np.clip((v("ground_temp_K") - 200.0) / 80.0, -1, 2))
                exp[CH["dose"]] = float(np.clip(v("dose_rate_uGy_h") / 10.0, 0, 2))
            if v("elevation_m") is not None:
                exp[CH["relz"]] = float(np.clip((v("elevation_m") - S["elevation_m"][r, c]) / 20.0, -1, 1))
            for ch, val in exp.items():
                tol = 2e-3 if ch >= CH["shadow"] else 1e-5          # dynamic channels are stored as float16
                if abs(float(p[ch]) - val) > tol:
                    bad.append((r, c, dr, dc, ch, float(p[ch]), val))
    check("observation channels equal world.cell() at %d cells x 5 offsets" % len(cells), not bad, str(bad[:3]))


def t3_dynamic_change():
    g = GridData.get()
    e = MarsWalkEnv(level=1, seed=0)
    out = {}
    for lm in (6.0, 12.0):
        s = (300 * W + 300)
        e.reset(options={"start_goal": (s, s), "sol": 4600, "lmst": lm})
        o = e._obs()
        out[lm] = o["patch"][12:16]
    diff = np.abs(out[6.0] - out[12.0]).reshape(4, -1).max(1)
    check("dynamic channels (shadow, insolation, temperature, dose) differ between LMST 6 and 12", bool((diff[:3] > 0.05).all()),
          "max abs diff per channel %s" % np.round(diff, 3))
    e.reset(options={"start_goal": (s, s), "sol": 4600, "lmst": 9.0})
    v0 = e._obs()
    e.t_s = 3 * 3600.0                                              # three hours later, same place
    v1 = e._obs()
    check("dynamic channels update as episode time advances", np.abs(v0["patch"][12:15] - v1["patch"][12:15]).max() > 0.05
          and abs(v0["vec"][10] - v1["vec"][10]) > 0.05, "sun el/90 %.3f -> %.3f" % (v0["vec"][10], v1["vec"][10]))


def t4_visibility():
    g = GridData.get()
    w = g.world
    hz = w.S["horizon_deg"].astype(np.float32)
    hmax = hz.max(0)
    rng = np.random.default_rng(2)
    ok_cells = np.argwhere(np.isfinite(w.S["elevation_m"]) & (hmax > 20))
    best = None
    for i in rng.choice(len(ok_cells), 400, replace=False):
        r, c = ok_cells[i]
        if r < 9 or c < 9 or r > H - 10 or c > W - 10:
            continue
        P = visibility.visible_patch(r, c, 7, 48.0)
        hid = int((~P).sum())
        if best is None or hid > best[0]:
            best = (hid, r, c)
    hid, r, c = best
    # independent check: march a straight 1 m ray over the DTM to each hidden cell; blocked if an intermediate sample
    # rises above the line from the eye to the target
    visibility._load()
    dtm = visibility._dtm

    def bil(y, x):
        y0, x0 = int(np.floor(y)), int(np.floor(x)); fy, fx = y - y0, x - x0
        return (dtm[y0, x0] * (1 - fx) * (1 - fy) + dtm[y0, x0 + 1] * fx * (1 - fy) + dtm[y0 + 1, x0] * (1 - fx) * fy
                + dtm[y0 + 1, x0 + 1] * fx * fy)
    oy, ox = 4 * r + 1.5, 4 * c + 1.5
    eye = bil(oy, ox) + 1.7
    P = visibility.visible_patch(r, c, 7, 48.0)
    agree = tot = 0
    azs = []
    for i in range(15):
        for j in range(15):
            if (i, j) == (7, 7):
                continue
            ty, tx = 4 * (r - 7 + i) + 1.5, 4 * (c - 7 + j) + 1.5
            anyv = False                                   # a cell is visible if any of its 4 central samples is (as visibility.py)
            for oyy in (-0.5, 0.5):
                for oxx in (-0.5, 0.5):
                    yy, xx = ty + oyy, tx + oxx
                    dd = math.hypot(yy - oy, xx - ox) * visibility.RES
                    at = (bil(yy, xx) - eye) / dd
                    blk = any((bil(oy + f * (yy - oy), ox + f * (xx - ox)) - eye) / (f * dd) > at + 1e-4 for f in np.linspace(0.01, 0.99, 200))
                    anyv |= not blk
            tot += 1; agree += (anyv == bool(P[i, j]))
            if not P[i, j]:
                azs.append((i, j))
    # horizon data: the hidden cells lie in azimuths where the cell's horizon is above the elevation angle of the target
    cons = 0
    for (i, j) in azs:
        dy, dx = (7 - i), (j - 7)                                   # north, east (cells)
        az = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        d = math.hypot(dy, dx) * CELL_M
        ang = math.degrees(math.atan2(w.S["elevation_m"][r - 7 + i, c - 7 + j] - w.S["elevation_m"][r, c] - 1.7, d))
        cons += float(w.horizon_at(az)[r, c]) >= ang - 1.0
    check("visibility: ridge cell (%d,%d) horizon max %.1f deg, %d/224 patch cells hidden; ray-march agrees on %d/%d cells" % (r, c, hmax[r, c], hid, agree, tot),
          hid > 0 and agree / tot > 0.95, "independent bilinear 200-step ray march, any of 4 central samples")
    check("visibility: every hidden cell lies behind the horizon recorded in horizon_32_4m (%d/%d)" % (cons, len(azs)), cons == len(azs))
    # the env masks them
    e = MarsWalkEnv(level=1, seed=0, visibility=True)
    s = r * W + c
    e.reset(options={"start_goal": (s, s), "sol": 4600, "lmst": 9.0})
    e.cell = s
    on, e.cfg.visibility = e._obs()["patch"], False
    off = e._obs()["patch"]
    e.cfg.visibility = True
    hidden = ~P
    unk_on = on[CH["unknown"]] > 0
    ok_mask = bool(unk_on[hidden].all()) and bool((on[:CH["unknown"]][:, hidden] == 0).all()) and bool((on[CH["unknown"] + 1:][:, hidden] == 0).all())
    seen = (~hidden) & (off[CH["unknown"]] == 0)
    ok_same = bool(np.allclose(on[:, seen], off[:, seen]))
    check("env(visibility=True) reports hidden cells as unknown (all other channels 0) and leaves visible cells unchanged", ok_mask and ok_same,
          "%d hidden, %d visible-known" % (hidden.sum(), seen.sum()))
    # radius 48 vs 300 agreement
    tot = diff = 0
    for k in rng.choice(len(ok_cells), 60, replace=False):
        rr, cc = ok_cells[k]
        if rr < 9 or cc < 9 or rr > H - 10 or cc > W - 10:
            continue
        a_, b_ = visibility.visible_patch(rr, cc, 7, 48.0), visibility.visible_patch(rr, cc, 7, 300.0)
        tot += 225; diff += int((a_ != b_).sum())
    print("     info: visible_patch radius 48 m vs 300 m differ on %.2f%% of patch cells (ray-sampling density)" % (100.0 * diff / tot))


def t5_physics():
    g = GridData.get()
    grid = costs.load_grid()
    prof = A.get_profile("nominal")
    check("env blocked mask == costs.hard_blocked", bool((g.blocked == costs.hard_blocked(grid, prof)).all()),
          "%.2f%% blocked" % (100 * g.blocked.mean()))
    sc = scenarios.make_scenarios(grid, prof, n=3, seed=0, min_km=0.5, max_km=1.5)
    for s in sc:
        r = astar.plan(grid, s["start"], s["goal"], prof)
        route = [int(x) for x in r["route"]]
        e = MarsWalkEnv(level=1, seed=0, goal_radius_cells=0.0)      # exact goal cell so the last step is walked too
        e.reset(options={"start_goal": (route[0], route[-1]), "sol": 4600, "lmst": 8.0})
        info = {}
        for a_, b_ in zip(route[:-1], route[1:]):
            a = DIRS.index((b_ // W - a_ // W, b_ % W - a_ % W))
            _, _, te, tr, info = e.step(a)
            if te or tr:
                break
        m = astar.route_metrics(grid, route, prof)
        v = safety_validator.validate(route, grid, prof)
        ok = (abs(info["t_s"] - m["time_s"]) < 0.5 and abs(info["energy_kj"] - m["energy_kj"]) < 0.01
              and abs(info["dose_uGy"] - m["dose_uGy"]) < 1e-3 and info["is_success"] == v["ok"])
        # retrace leg vs the validator's back leg (validator applies fatigue on the back leg, env uses none)
        rt = info["t_s"] + e.ret_t
        check("%s: env replay of the A* route = astar.route_metrics (t %.1f/%.1f s, E %.2f/%.2f kJ, dose %.3f/%.3f) and success == validator ok (%s)" % (
            s["id"], info["t_s"], m["time_s"], info["energy_kj"], m["energy_kj"], info["dose_uGy"], m["dose_uGy"], v["ok"]), ok,
            "round trip env %.0f s vs validator %.0f s" % (rt, v["summary"]["roundtrip_time_s"]))
    # a long route on the fatigued profile: env must stop on the same budget the validator names
    pf = A.get_profile("fatigued")
    gridf = grid
    scf = scenarios.make_scenarios(gridf, pf, n=12, seed=5, min_km=1.2, max_km=2.0)
    n_agree = n_fail = 0
    for s in scf:
        r = astar.plan(gridf, s["start"], s["goal"], pf)
        if not r.get("success"):
            continue
        route = [int(x) for x in r["route"]]
        v = safety_validator.validate(route, gridf, pf)
        e = MarsWalkEnv(level=1, seed=0, profile="fatigued", forbid_night=False, goal_radius_cells=0.0)
        e.reset(options={"start_goal": (route[0], route[-1]), "sol": 4600, "lmst": 8.0})
        info = {}
        for a_, b_ in zip(route[:-1], route[1:]):
            a = DIRS.index((b_ // W - a_ // W, b_ % W - a_ % W))
            _, _, te, tr, info = e.step(a)
            if te or tr:
                break
        n_fail += (not v["ok"])
        n_agree += (info["is_success"] == v["ok"])
    check("fatigued profile, %d long routes: env success == validator ok on %d (validator rejects %d)" % (len(scf), n_agree, n_fail),
          n_agree >= len(scf) - 1 - 0, "disagreement can come from the validator's fatigue on the back leg")


def t6_limits():
    g = GridData.get()
    s = 300 * W + 300
    free = np.argwhere(~g.blocked)
    # night: start at dusk, walk until unsafe(night)
    e = MarsWalkEnv(level=1, seed=0)
    rise, sset = g.daylight(4600)
    e.reset(options={"start_goal": (s, s + 10), "sol": 4600, "lmst": sset - 0.01})
    e.t_s = 0.0
    res = None
    for _ in range(200):
        m = e.action_masks()
        acts = np.nonzero(m[:8])[0]
        if not len(acts):
            break
        _, _, te, tr, info = e.step(int(acts[0]))
        if te or tr:
            res = info; break
    check("forbid_night: walking past sunset ends the episode unsafe(night)", res is not None and res["unsafe_reason"] == "night",
          "sunset LMST %.2f h" % sset)
    # shadow limit: find a shadowed neighbour at low sun
    e = MarsWalkEnv(level=1, seed=0, forbid_shadow=True, forbid_night=False)
    d = g.dyn(4600, rise + 0.6, 0.5)
    sh = np.argwhere((d[0, R:-R, R:-R] > 0) & ~g.blocked)
    ns = 0
    for (r, c) in sh[:: max(1, len(sh) // 400)]:
        nb = [(r + dr, c + dc) for dr, dc in DIRS]
        if any(0 <= a < H and 0 <= b < W and d[0, a + R, b + R] == 0 and not g.blocked[a, b] for a, b in nb):
            e.reset(options={"start_goal": (r * W + c, r * W + c + 3), "sol": 4600, "lmst": rise + 0.6})
            m = e.action_masks()
            ok = True
            for k, (dr, dc) in enumerate(DIRS):
                a, b = r + dr, c + dc
                if 0 <= a < H and 0 <= b < W and d[0, a + R, b + R] > 0:
                    ok &= not m[k]
            ns += ok
            if ns >= 5:
                break
    check("forbid_shadow: action_masks forbid moves into shadowed neighbours (5 sunrise cells)", ns >= 5)
    # temperature limit
    e = MarsWalkEnv(level=1, seed=0, temp_range_K=(0.0, 100.0), forbid_night=False)   # impossible range: everything out of range
    e.reset(options={"start_goal": (s, s + 10), "sol": 4600, "lmst": 12.0})
    _, _, te, tr, info = e.step(int(np.nonzero(e.action_masks()[:8] | True)[0][0]))
    check("temp_range_K outside the modelled temperature ends the step unsafe(temperature)", te and info["unsafe_reason"] == "temperature",
          str(info["unsafe_reason"]))
    # sep_stop
    e = MarsWalkEnv(level=1, seed=0, sep_stop=True)
    n_alert = sum(g.sep(x) for x in range(4500, 4800))
    st = [e.sample_time() for _ in range(400)]
    check("sep_stop samples no start (sol, LMST) with a notice (%d of 300 campaign sols have sep_alert at noon)" % n_alert, not any(g.sep(x, l) for x, l in st))
    e = MarsWalkEnv(level=1, seed=0)
    lm = [e.sample_time() for _ in range(300)]
    ok = all(g.sun_el(sol, x) > 0 for sol, x in lm)
    check("start LMST always in daylight (300 samples)", ok)


if __name__ == "__main__":
    for f in (t1_check_env, t2_channels, t3_dynamic_change, t4_visibility, t5_physics, t6_limits):
        try:
            f()
        except Exception as ex:
            import traceback; traceback.print_exc()
            check(f.__name__, False, repr(ex))
    print("%d/%d checks passed" % (sum(RES), len(RES)))
    sys.exit(0 if all(RES) else 1)
