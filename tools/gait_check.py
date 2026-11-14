"""Independent gait verification of the twin's animated astronaut. usage: python tools/gait_check.py [port]"""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "runs", "twin_check", "gait_check")
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
CROP = (int(os.environ.get("CX", 360)), int(os.environ.get("CY", 150)), int(os.environ.get("CW", 720)), int(os.environ.get("CH", 600)))
errors = []
SAMPLER = """async (n) => {
  const W = window.__walk, out = [];
  for (let i = 0; i < n; i++) {
    await new Promise(r => requestAnimationFrame(r));
    const g = W.gaitState();
    out.push({t: g.t, s: W.s, stance: g.stance, ww: g.wWalk, feet: g.feet, body: g.body, yaw: g.yaw,
              gy: g.feet.map(f => W.groundY(f[0], f[2])), steps: g.steps, prints: g.prints});
  }
  return out;
}"""

def pct(a, q): return float(np.percentile(a, q)) if len(a) else None

def analyse(samples, label):
    """planted = ankle clearance within 1 cm of its min over the previous 1.5 m of travel (one cycle)."""
    s = np.array([x["s"] for x in samples]); res = {"slide": [], "vert": [], "agree": [], "phases": 0}
    for f in (0, 1):
        feet = np.array([x["feet"][f] for x in samples]); gy = np.array([x["gy"][f] for x in samples])
        clr = feet[:, 1] - gy - 0.160 + 0.160  # clearance above ground
        st = np.array([x["stance"][f] for x in samples])
        planted = np.zeros(len(samples), bool)
        for i in range(len(samples)):
            j = np.searchsorted(s, s[i] - 1.5)
            if s[i] - s[0] < 1.5: continue
            planted[i] = clr[i] <= clr[j:i + 1].min() + 0.01
        res["agree"].append(float((planted == st)[s - s[0] >= 1.5].mean()))
        i = 0
        while i < len(samples):
            if not planted[i]: i += 1; continue
            k = i
            while k + 1 < len(samples) and planted[k + 1]: k += 1
            if i > 0 and k < len(samples) - 1 and k - i >= 1:   # complete phase, >=2 samples
                d = np.hypot(feet[i:k + 1, 0] - feet[i, 0], feet[i:k + 1, 2] - feet[i, 2]).max()
                res["slide"].append(float(d)); res["phases"] += 1
            if k - i >= 0 and i > 0:
                res["vert"] += list((clr[i:k + 1] - 0.160)) if False else list(feet[i:k + 1, 1] - gy[i:k + 1] - 0.160)
            i = k + 1
    sl, v = np.array(res["slide"]), np.array(res["vert"])
    # flag-based phases (stance flags from the page) with the same metrics, plus count of swing-phase frames below ground
    fs, fv, below = [], [], []
    for f in (0, 1):
        feet = np.array([x["feet"][f] for x in samples]); gy = np.array([x["gy"][f] for x in samples])
        st = np.array([x["stance"][f] for x in samples]); i = 0
        while i < len(samples):
            if not st[i]: i += 1; continue
            k = i
            while k + 1 < len(samples) and st[k + 1]: k += 1
            if i > 0 and k < len(samples) - 1:
                fs.append(float(np.hypot(feet[i:k + 1, 0] - feet[i, 0], feet[i:k + 1, 2] - feet[i, 2]).max()))
                fv += list(feet[i:k + 1, 1] - gy[i:k + 1] - 0.160)
            i = k + 1
        below += list(feet[~st, 1] - gy[~st] - 0.160)
    fs, fv, below = np.array(fs) * 100, np.array(fv) * 100, np.array(below) * 100
    flag = {"phases": len(fs), "slide_max_cm": float(fs.max()), "slide_med_cm": pct(fs, 50), "slide_p95_cm": pct(fs, 95),
            "vert_med_cm": pct(fv, 50), "vert_min_cm": float(fv.min()), "vert_max_cm": float(fv.max()),
            "swing_frames": int(len(below)), "swing_frames_sole_below_ground_gt2cm": int((below < -2).sum()), "swing_min_cm": float(below.min())}
    return {"flag_based": flag, "label_": label, "label": label, "frames": len(samples), "phases": res["phases"],
            "slide_max_cm": float(sl.max() * 100) if len(sl) else None, "slide_med_cm": pct(sl * 100, 50) if len(sl) else None,
            "slide_p95_cm": pct(sl * 100, 95) if len(sl) else None,
            "vert_med_cm": pct(v * 100, 50) if len(v) else None, "vert_min_cm": float(v.min() * 100) if len(v) else None,
            "vert_max_cm": float(v.max() * 100) if len(v) else None, "planted_vs_flag_agree": res["agree"],
            "steps_delta": samples[-1]["steps"] - samples[0]["steps"], "s_span": float(s[-1] - s[0])}

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"])
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(f"http://127.0.0.1:{port}/twin.html")
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=180000)
    pg.click("#btnDemo"); pg.wait_for_timeout(1500)
    pg.click("#btnWalk"); pg.wait_for_function("window.__walk.on===true", timeout=240000)
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=240000)
    pg.wait_for_function("window.__walk.gait != null", timeout=120000)
    pg.select_option("#wView", "follow")
    def setwarp(w):
        pg.select_option("#wWarp", str(w)); pg.evaluate(f"window.__walk.warp={w}")
    def collect(n):
        out = []
        while n > 0:
            c = min(n, 300); out += pg.evaluate(SAMPLER, c); n -= c
        return out
    setwarp(1); pg.wait_for_timeout(1500)
    L = pg.evaluate("window.__walk.routeLength()"); print("route length", L)
    # slope scan
    scan = pg.evaluate("""async (L) => { const W = window.__walk, o = [];
      for (let s = 20; s < L - 40; s += Math.max(5, L / 300)) { W.s = s; await new Promise(r => requestAnimationFrame(r)); await new Promise(r => requestAnimationFrame(r));
        const g = W.gaitState(), c = Math.cos(g.yaw), n = Math.sin(g.yaw), b = g.body;
        const hs = []; for (const d of [[c, n], [n, -c]]) { hs.push(Math.abs(W.groundY(b[0]+d[0]*2, b[2]+d[1]*2) - W.groundY(b[0]-d[0]*2, b[2]-d[1]*2)) / 4); }
        o.push([s, hs[0], hs[1], g.yaw]); } return o; }""", L)
    sc = np.array(scan)
    # yaw convention unknown: take direction of greater slope magnitude of the two perpendicular axes as ambiguous; use travel direction by checking both
    # better: use HUD-independent estimate from body displacement
    print("scan points", len(sc))
    # flat: median-slope region; steep: along-route slope, smoothed over ~ 12 m
    sm = np.convolve(np.maximum(sc[:, 1], 0), np.ones(5) / 5, "same")
    def runs(label, s0, warp, nframes):
        pg.evaluate(f"window.__walk.s = {s0}"); setwarp(warp); pg.wait_for_timeout(2500)
        smp = collect(nframes); smp = [x for x in smp]
        return analyse(smp, label), smp
    results, allruns = {}, {}
    flat_i = int(np.argmin(sm[2:-2])) + 2; steep_i = int(np.argmax(sm[2:-2])) + 2
    print("flat s", sc[flat_i, 0], "slope", sm[flat_i], "steep s", sc[steep_i, 0], "slope", sm[steep_i])
    # start 10 m before so the walker traverses the chosen spot
    r, smp = runs("flat_w1", max(5, sc[flat_i, 0] - 8), 1, 1500); results["flat_w1"] = r; allruns["flat_w1"] = smp
    r, smp = runs("slope_w1", max(5, sc[steep_i, 0] - 3), 1, 1100); results["slope_w1"] = r; allruns["slope_w1"] = smp
    r, smp = runs("w15", 30, 15, 600); results["w15"] = r; allruns["w15"] = smp
    results["steep_info"] = {"s": float(sc[steep_i, 0]), "slope_deg": float(np.degrees(np.arctan(sm[steep_i]))),
                             "flat_slope_deg": float(np.degrees(np.arctan(sm[flat_i])))}
    hud = pg.evaluate("document.getElementById('wSlope') && document.getElementById('wSlope').textContent"); results["hud_slope_now"] = hud
    json.dump(allruns, open(os.path.join(OUT, 'raw_samples.json'), 'w'))
    # footprints
    pl = np.array(pg.evaluate("window.__walk.printList")); st_total = pg.evaluate("window.__walk.gaitState()")
    results["prints_total"] = len(pl); results["gait_steps_total"] = st_total["steps"]; results["gait_prints_total"] = st_total["prints"]
    segs = []
    for k, smp in allruns.items():
        pts = np.array([[x["body"][0], x["body"][2]] for x in smp]); ss = np.array([x["s"] for x in smp])
        ok = np.r_[True, np.diff(ss) < 3] # break at jumps
        for i in range(1, len(pts)):
            if ok[i] and np.hypot(*(pts[i] - pts[i-1])) > 1e-6: segs.append((pts[i-1], pts[i]))
    A = np.array([s_[0] for s_ in segs]); Bv = np.array([s_[1] for s_ in segs]); D = Bv - A; l2 = (D**2).sum(1)
    offs = []; covered = []
    for x, z, yaw in pl:
        q = np.array([x, z]); t = np.clip(((q - A) * D).sum(1) / l2, 0, 1); proj = A + D * t[:, None]
        d = np.hypot(*(q - proj).T); i = int(np.argmin(d))
        if d[i] > 3: offs.append(None); continue     # not on a sampled stretch
        cr = D[i][0] * (q[1] - proj[i][1]) - D[i][1] * (q[0] - proj[i][0])
        offs.append(float(np.sign(cr) * d[i]))
    cov = [(o, pl[i]) for i, o in enumerate(offs) if o is not None]
    ao = np.array([o for o, _ in cov]); results["prints_on_sampled_route"] = len(cov)
    results["print_abs_offset_mean_m"] = float(np.abs(ao).mean()) if len(ao) else None
    results["print_abs_offset_max_m"] = float(np.abs(ao).max()) if len(ao) else None
    results["print_signed_mean_m"] = float(ao.mean()) if len(ao) else None
    ch = tot = 0
    for i in range(1, len(offs)):
        if offs[i] is None or offs[i-1] is None: continue
        if np.hypot(*(pl[i][:2] - pl[i-1][:2])) > 2.5: continue
        tot += 1; ch += np.sign(offs[i]) != np.sign(offs[i-1])
    results["alternation_ratio"] = ch / tot if tot else None; results["alternation_pairs"] = tot
    # idle
    setwarp(1); pg.wait_for_timeout(1500)
    pg.keyboard.press("Space"); pg.wait_for_timeout(1200)
    idle = pg.evaluate("""async () => { const W = window.__walk, o = [], t0 = performance.now();
        while (performance.now() - t0 < 2200) { const g = W.gaitState(); o.push({tm: performance.now()-t0, body: g.body, feet: g.feet, ww: g.wWalk, s: W.s}); await new Promise(r => setTimeout(r, 50)); } return o; }""")
    ib = np.array([x["body"] for x in idle]); ifeet = np.array([x["feet"] for x in idle])
    results["idle"] = {"body_range_m": float(np.ptp(ib, axis=0).max()), "feet_range_cm": float(np.ptp(ifeet, axis=0).max() * 100),
                       "wWalk_last": idle[-1]["ww"], "s_range": float(np.ptp([x["s"] for x in idle]))}
    pg.keyboard.press("Space"); pg.wait_for_timeout(1500)
    r2 = pg.evaluate("window.__walk.gaitState()"); results["idle"]["resumed_wWalk"] = r2["wWalk"]
    # visual: 3 steps at warp 1
    pg.evaluate("window.__walk.s = window.__walk.routeLength()*0.3"); setwarp(1); pg.wait_for_timeout(2500)
    shots = []; meta = []
    for i in range(26):
        f = os.path.join(OUT, f"frame_{i:02d}.png"); g = pg.evaluate("(()=>{const g=window.__walk.gaitState();return {t:g.t,steps:g.steps,stance:g.stance,s:window.__walk.s}})()")
        pg.locator("#view canvas").first.screenshot(path=f); shots.append(f); meta.append(g)
    results["shots_meta"] = meta
    results["console_errors"] = errors
    b.close()

# contact sheet
cols, tw, th = 6, 360, 300
rows = (len(shots) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * th))
for i, f in enumerate(shots):
    im = Image.open(f).convert("RGB").crop((CROP[0], CROP[1], CROP[0] + CROP[2], CROP[1] + CROP[3])).resize((tw, th))
    d = ImageDraw.Draw(im); d.rectangle((0, 0, 190, 14), fill=(0, 0, 0)); d.text((2, 1), f"#{i} steps={meta[i]['steps']} st={meta[i]['stance']}", fill=(255, 255, 0))
    sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
sheet.save(os.path.join(OUT, "contact_sheet.png"))
json.dump(results, open(os.path.join(OUT, "results.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in results.items() if k != "shots_meta"}, indent=1))
