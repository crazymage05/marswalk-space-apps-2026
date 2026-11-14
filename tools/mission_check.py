"""Independent verification of demo/twin/mission.html against mission_log.json."""
import json, re, math, sys, copy
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]   # repo root, on any machine
OUT = ROOT / "runs/twin_check/mission_check"; OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8765/mission.html"
LOG = json.load(open(ROOT / "demo/twin/mission_log.json"))
S = LOG["steps"]; M = LOG["mission"]; N = len(S); BANDS = M["limits"]["bands"]
TL = M["timeline"]
KEYS = ["t_s","energy_kj","dose_uGy","fatigue","margin_time_s","margin_energy_kj","dose_rate_uGy_h","tau_at_walker","sun_el_deg","light_time_min"]
UPPER = ["t_s","energy_kj","dose_uGy"]; LOWER = ["margin_time_s","margin_energy_kj"]
def exp_state(k, v):
    b = BANDS[k]
    if k in UPPER: return "red" if v >= b["red"] else "yellow" if v >= b["yellow"] else "green"
    return "red" if v <= b["red"] else "yellow" if v <= b["yellow"] else "green"
def hms(s):
    s = int(round(max(0, s))); return f"{s//3600}:{(s%3600)//60:02d}:{s%60:02d}"
# inferred display: (decimals, scale) ; t_s handled separately
DISP = {"energy_kj":(1,1),"dose_uGy":(2,1),"fatigue":(1,100),"margin_time_s":(1,1/60),"margin_energy_kj":(1,1),
        "dose_rate_uGy_h":(2,1),"tau_at_walker":(2,1),"sun_el_deg":(1,1),"light_time_min":(2,1)}
def close(a, b): return abs(a-b) <= 1e-9*max(1, abs(b))
res = {}; fails = []
def rec(name, ok, total, note=""):
    res.setdefault(name, [0, 0, []]); res[name][0] += ok; res[name][1] += total
    if note and len(res[name][2]) < 8: res[name][2].append(note)

def run(page, tag):
    errs = []
    page.on("console", lambda m: errs.append(("console", m.text)) if m.type == "error" else None)
    page.on("pageerror", lambda e: errs.append(("pageerror", str(e))))
    page.goto(URL); page.wait_for_function("window.__mission && window.__mission.log")
    page.wait_for_timeout(1500)
    def txt(i): return page.inner_text(f"#tile_{i} .n").strip()
    def tile_state(i):
        c = page.get_attribute(f"#tile_{i}", "class"); return re.search(r"s-(\w+)", c).group(1) if re.search(r"s-(\w+)", c) else None
    # 1/2
    for i in range(N):
        page.evaluate(f"window.__mission.setStep({i})")
        tv = page.evaluate("window.__mission.tiles()")
        ok_h = all(close(tv[k], S[i][k]) for k in KEYS)
        rec(f"{tag}1 hook exact", ok_h, 1, f"step {i}" if not ok_h else "")
        okt = True; bad = ""
        for k in KEYS:
            t = txt(k)
            if k == "t_s":
                e = hms(S[i][k]); ok = t == e
            else:
                d, sc = DISP[k]; e = f"{S[i][k]*sc:.{d}f}"
                ok = abs(float(t) - float(e)) <= 10**-d * 1.0001
                ok_exact = t == e
                rec(f"{tag}1 text exact-rounding {k}", ok_exact, 1)
            if not ok: okt = False; bad += f" {k}: page '{t}' json {e};"
        rec(f"{tag}1 text within 1 unit", okt, 1, f"step {i}:{bad}" if not okt else "")
        # bands
        ok_b = True; bad = ""
        for k in UPPER+LOWER:
            ps = tile_state(k); es = exp_state(k, S[i][k])
            ltxt = page.inner_text(f"#tile_{k} .lim")
            if ps != es or f"({es})" not in ltxt: ok_b = False; bad += f" {k}: page {ps} exp {es};"
        rec(f"{tag}2 band state all steps", ok_b, 1, f"step {i}:{bad}" if not ok_b else "")
        # banner
        b = page.evaluate("window.__mission.banner()"); bd = page.inner_text("#bDec").strip(); br = page.inner_text("#bRule")
        okb = b["decision"] == S[i]["decision"] == bd and page.get_attribute("#banner","class") == "GO"
        rec(f"{tag}5 banner decision", okb, 1, f"step {i}: {b} {bd}" if not okb else "")
        hz_exp = i >= M["event_step"]
        okr = ("HZ-1" in br) == hz_exp
        rec(f"{tag}5 rule line HZ-1 iff step>=event", okr, 1, f"step {i}: '{br}'" if not okr else "")
        # countdown
        sent = next(e for e in TL if e["kind"]=="comm_sent"); rep = next(e for e in TL if e["kind"]=="ground_reply")
        cd = page.evaluate("window.__mission.countdown()")
        if sent["step"] <= i < rep["step"]:
            e = rep["t_s"] - S[i]["t_s"]; ok = cd is not None and abs(cd-e) < 0.01
            vis = page.inner_text("#cd").strip(); okv = vis == hms(e)
            rec(f"{tag}4 countdown hook (in window)", ok, 1, f"step {i}: {cd} vs {e}" if not ok else "")
            rec(f"{tag}4 countdown text (in window)", okv, 1, f"step {i}: '{vis}' vs {hms(e)}" if not okv else "")
        else:
            ok = cd is None and page.query_selector("#cd") is None
            rec(f"{tag}4 countdown null outside window", ok, 1, f"step {i}: {cd}" if not ok else "")
    # 2 synthetic: mutate bands in page's own log (state() reads L.limits.bands live)
    for k in UPPER+LOWER:
        for target in ("green","yellow","red"):
            # choose a step and set bands so the true value lands in target
            i = N//2; v = S[i][k]
            if k in UPPER:
                bd = {"green":{"yellow":v+2,"red":v+4},"yellow":{"yellow":v-1,"red":v+4},"red":{"yellow":v-2,"red":v-1}}[target]
            else:
                bd = {"green":{"yellow":v-2,"red":v-4},"yellow":{"yellow":v+1,"red":v-4},"red":{"yellow":v+2,"red":v+1}}[target]
            page.evaluate(f"window.__mission.log.limits.bands['{k}']={json.dumps(bd)}; window.__mission.setStep({i})")
            got = tile_state(k); rec(f"{tag}2 synthetic bands (page's own state())", got == target, 1, f"{k} want {target} got {got}" if got != target else "")
        # boundary equality: upper v==yellow -> yellow, v==red -> red (>=); lower <=
        i = N//2; v = S[i][k]
        for edge, want in (("yellow","yellow"),("red","red")):
            bd = dict(BANDS[k]); 
            if k in UPPER: bd = {"yellow": v-5 if edge!="yellow" else v, "red": v if edge=="red" else v+5}
            else: bd = {"yellow": v+5 if edge!="yellow" else v, "red": v if edge=="red" else v-5}
            page.evaluate(f"window.__mission.log.limits.bands['{k}']={json.dumps(bd)}; window.__mission.setStep({i})")
            got = tile_state(k); rec(f"{tag}2 boundary-equality", got == want, 1, f"{k} edge {edge} want {want} got {got}" if got != want else "")
        page.evaluate(f"window.__mission.log.limits.bands['{k}']={json.dumps(BANDS[k])}")
    page.evaluate("window.__mission.setStep(0)")
    # named steps for 2
    ev = M["event_step"]; rp = next(e for e in TL if e["kind"]=="ground_reply")["step"]
    for i in (0, ev, rp, N-1):
        st = {k: exp_state(k, S[i][k]) for k in UPPER+LOWER}
        page.evaluate(f"window.__mission.setStep({i})")
        ok = all(tile_state(k) == st[k] for k in st); rec(f"{tag}2 named steps 0/event/reply/last", ok, 1, f"step {i} {st}" if not ok else "")
    # skip
    page.evaluate("window.__mission.setStep(0)"); page.click("#skip"); st = page.evaluate("window.__mission.step")
    rec(f"{tag}4 skip -> reply step", st == rp, 1, f"got {st} exp {rp}")
    page.evaluate("window.__mission.setStep(%d)"%rp); rec(f"{tag}4 skip disabled at reply", page.is_disabled("#skip"), 1)
    # 3 cyan pixels
    def cyan():
        return page.evaluate("""()=>{const c=document.getElementById('map');const x=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let n=0;
        for(let i=0;i<x.length;i+=4){if(x[i+2]>x[i]+15&&x[i+1]>x[i]+10&&x[i+2]>90&&x[i+3]>200)n++}return n}""")
    page.click("#fit")
    cy = {}
    for i in (0, ev-1, ev, ev+1, 100, 200):
        page.evaluate(f'window.__mission.setStep({i})'); cy[i] = cyan()
    rec(f"{tag}3 cyan absent before event, present from event", cy[0]==0 and cy[ev-1]==0 and cy[ev]>50 and cy[100]>50 and cy[200]>50, 1, str(cy))
    # replay order via Play at fastest speed
    page.evaluate("window.__mission.setStep(0)")
    page.select_option("#speed", "60")
    speeds = page.evaluate("[...document.querySelectorAll('#speed option')].map(o=>+o.value)")
    page.evaluate("""()=>{window.__seen=[];window.__cy=[];let last=[];const f=()=>{const cur=window.__mission.logShown();
      if(cur.length!==last.length){window.__seen.push(...cur.slice(last.length));last=cur}requestAnimationFrame(f)};f()}""")
    page.click("#play")
    page.wait_for_function("document.getElementById('play').textContent==='Play' && window.__mission.step===%d" % (N-1), timeout=120000)
    seen = page.evaluate("window.__seen"); exp = [e["kind"] for e in TL]
    chron = [e["kind"] for e in sorted(TL, key=lambda e: e["t_s"])]
    rec(f"{tag}3 replay order == chronological ({speeds} max {max(speeds)}x used 60x)", seen == exp == chron, 1, f"seen {seen}")
    # play at 10x briefly: cyan appears after event
    # 6
    sw = page.evaluate("document.documentElement.scrollWidth"); cw = page.evaluate("document.documentElement.clientWidth")
    rec(f"{tag}6 no horizontal scroll", sw <= cw, 1, f"scrollWidth {sw} clientWidth {cw}")
    rec(f"{tag}6 console/page errors == 0", len(errs) == 0, 1, str(errs))
    page.screenshot(path=str(OUT / f"{tag}final.png"), full_page=True)
    page.evaluate("window.__mission.setStep(%d)"%ev); page.screenshot(path=str(OUT / f"{tag}event.png"), full_page=True)

with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=metal"])
    for tag, vp in (("desk ", {"width":1440,"height":900}), ("mob  ", {"width":400,"height":860})):
        ctx = br.new_context(viewport=vp); page = ctx.new_page(); run(page, tag); ctx.close()
    # twin.html
    ctx = br.new_context(viewport={"width":1440,"height":900}); page = ctx.new_page(); errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append("console:"+m.text) if m.type=="error" else None)
    page.goto("http://127.0.0.1:8765/twin.html")
    try:
        page.wait_for_function("document.getElementById('loading').hidden===true", timeout=180000); loaded = True
    except Exception as e: loaded = False
    rec("twin.html loads", loaded, 1); rec("twin.html 0 page/console errors", not errs, 1, str(errs[:3]))
    page.screenshot(path=str(OUT/"twin.png")); br.close()
lines = []
for k, (o, t, notes) in res.items():
    lines.append(f"{'PASS' if o==t else 'FAIL'}  {k}: {o}/{t}  {'; '.join(notes) if o!=t else ''}")
(OUT/"report.txt").write_text("\n".join(lines)); print("\n".join(lines))
