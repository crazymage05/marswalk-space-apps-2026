#!/usr/bin/env python3
"""Film clip for ANY route planned in the browser twin (see docs/render_route.md).

    python tools/render_route.py "<share link or #hash>" [--name NAME] [--preview | --final] [--seconds N] [--timelapse]

1. serves demo/twin on port 8789, opens twin.html?notour#<hash> in headless Chrome, waits for the route and reads the exact
   planned cells, the sol, the crew/carried settings and the verdict text -> film/routes/<name>/route.json (with provenance)
2. builds film/routes/<name>/scene.blend with the film pipeline (tools/f1_prep_data.py + tools/f1_blender_scene.py in route
   mode, then tools/f2_suitfix.py for the backpack): HiRISE terrain around the route, Curiosity Navcam scans, the Mark III
   suit walking the planned cells, a crane-down overview and a chase camera
3. --preview (default): Cycles 16 spp + OptiX denoise (or --engine eevee) at 960x540, every 2nd frame, encoded 12 fps -> preview.mp4
   --final: Cycles 64 spp at 1920x1080, every frame, 24 fps -> final.mp4 (the film's settings)
Every render holds tools/gpu_lock.py's lock and calls wait_cool() before each chunk."""
import argparse, hashlib, http.server, json, os, re, subprocess, sys, threading, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT); sys.path.insert(0, ROOT)
PORT = 8789
ROI_W, ROI_H = 2340, 2928          # ROI size in 1 m pixels (elevation_m.tif); the twin grid is 585 x 732 cells of 4 px
GW = 585                           # twin grid width (cells)
WALK_SPEED = 0.9                   # m/s, the film's walk cycle (1.5 m stride, 40 frames at 24 fps)
MAX_WINDOW_PX = 3_000_000          # 1 m terrain window cap (the film's own window is 1.31 M)


# ------------------------------------------------------------------ 1. capture the route from the twin page
def hash_of(link):
    link = link.strip()
    if link.lower() in ("", "default", "demo", "campaign", "#"): return ""
    return link.split("#", 1)[1] if "#" in link else link.lstrip("?#")


def serve():
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(s, *a, **k): super().__init__(*a, directory=os.path.join(ROOT, "demo", "twin"), **k)
        def log_message(s, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def capture(hash_, make_link=None):
    """Open the twin with the share hash; returns the dict that becomes route.json (minus the film section)."""
    from playwright.sync_api import sync_playwright
    srv = serve()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True,
                                  args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=d3d11", "--enable-webgl"])
            page = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
            errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
            url = f"http://127.0.0.1:{PORT}/twin.html?notour" + ("#" + hash_ if hash_ else "")
            page.goto(url, wait_until="load", timeout=120000)
            page.wait_for_function("document.getElementById('loading').hidden === true", timeout=240000)
            if make_link: make_link(page)          # test helper: drive the page, then read the share hash back
            want = dict(kv.split("=", 1) for kv in hash_.split("&") if "=" in kv)
            t0 = time.time(); last = None; stable = 0
            while time.time() - t0 < 180:
                page.wait_for_timeout(1000)
                st = page.evaluate("""() => ({ cells: window.__routeCells && window.__routeCells(), multi: window.__multiState && window.__multiState(),
                    verdict: document.getElementById('verdict').hidden ? '' : document.getElementById('verdict').innerText })""")
                ok = bool(st["cells"]) and "Checking" not in st["verdict"] and st["verdict"] != ""
                if want.get("r") == "multi": ok = ok and bool(st["multi"])
                if want.get("a") and want.get("b") and not want.get("r") and ok:
                    ax, ay = map(int, want["a"].split(",")); bx, by = map(int, want["b"].split(","))
                    ok = st["cells"][0] == ay * GW + ax and st["cells"][-1] == by * GW + bx
                key = ",".join(map(str, st["cells"])) if ok else None
                stable = stable + 1 if ok and key == last else 0; last = key
                if stable >= 3 and time.time() - t0 > 4: break
            else:
                raise SystemExit("the page did not produce a stable route within 180 s (link not applied?)")
            data = page.evaluate("""() => { const $ = id => document.getElementById(id), t = id => $(id) ? $(id).innerText.trim() : null;
                return { cells: window.__routeCells(), sol: +$('sol').value, maxSlope: +$('maxSlope').value,
                  crew: window.__crew ? window.__crew.state() : null, multi: window.__multiState ? window.__multiState() : null,
                  weights: window.__weights ? window.__weights() : null, verdict: t('verdict'), status: t('status'),
                  stats: { distance: t('sDist'), time: t('sTime'), climb: t('sClimb'), steepest: t('sSteep'), dose: t('sDose') },
                  hash_now: location.hash.replace(/^#/, '') } }""")
            data["page_errors"] = errors
            b.close()
    finally:
        srv.shutdown()
    return data


# ------------------------------------------------------------------ geometry helpers (normal Python)
def dtm_origin():
    import rasterio
    with rasterio.open("data/processed/roi/elevation_m.tif") as r: return r.transform.c, r.transform.f, r.transform.a


def cell_xy(c, X0, Y0, S):
    """twin cell (row*585+col) -> grid metres (east, north) of its 1 m pixel centre, as in f1_prep_data.py"""
    return X0 + S * (4 * (c % GW) + 1.5), Y0 - S * (4 * (c // GW) + 1.5)


def film_params(rt, a, X0, Y0, S):
    cells = rt["cells"]; xy = np.array([cell_xy(c, X0, Y0, S) for c in cells])
    seg = np.hypot(*np.diff(xy, axis=0).T); cum = np.r_[0, np.cumsum(seg)]; length = float(cum[-1])
    ov_f, walk_f = int(round(a.overview * 24)), int(round(a.seconds * 24))
    real_m = WALK_SPEED * a.seconds
    tail = min(a.tail, 0.5 * a.seconds)                  # time-lapse: the last `tail` seconds are real-speed, walk-level shots (the suit is only readable there)
    tl_f, tail_s0 = 0, 0.0
    if a.timelapse and length > real_m * 1.2:
        tl_s = a.seconds - tail; tl_m = length - WALK_SPEED * tail
        tl_s = max(tl_s, tl_m / (WALK_SPEED * a.max_speedup))          # the speed-up cap lengthens the clip instead of leaving the route unfinished
        speedup = tl_m / (WALK_SPEED * tl_s); tl_f = int(round(tl_s * 24)); tail_s0 = tl_m; walk_f = tl_f + int(round(tail * 24))
        if speedup < 1.5: speedup, tl_f = 1.0, 0
    else: speedup = 1.0
    walk_m = real_m * speedup if not tl_f else length
    if a.start_s is not None: s0 = a.start_s
    elif speedup > 1.0: s0 = 0.0
    else:                                              # real speed: start so the walker crosses a measured Navcam scan if the route passes one
        s0 = 0.0
        sc = [(m["anchor_x_m"], m["anchor_y_m"], m.get("radius_m", 25.0)) for m in json.load(open("demo/twin/meshes/meshes.json"))["meshes"]]
        best = None
        for (mx, my, rad) in sc:
            d = np.hypot(xy[:, 0] - mx, xy[:, 1] - my); k = int(np.argmin(d))
            if d[k] < 0.8 * rad and (best is None or cum[k] < best[0]): best = (float(cum[k]), rad)
        if best: s0 = best[0] - 0.5 * walk_m
    s0 = float(min(max(0.0, s0), max(0.0, length - walk_m)))
    # 1 m terrain window (pixels of the 1 m DTM): the part of the route that is filmed (the whole route in a time-lapse) plus a margin
    lo_s, hi_s = (0.0, length) if speedup > 1.0 else (max(0.0, s0 - 30.0), min(length, s0 + walk_m + 60.0))
    sel = xy[(cum >= lo_s) & (cum <= hi_s)]
    if len(sel) < 2: sel = xy
    px = np.c_[(sel[:, 0] - X0) / S, (Y0 - sel[:, 1]) / S]; marg = a.margin if a.margin else (150 if speedup > 1.0 else 300)
    c0, c1 = int(np.floor(px[:, 0].min() - marg)), int(np.ceil(px[:, 0].max() + marg)); r0, r1 = int(np.floor(px[:, 1].min() - marg)), int(np.ceil(px[:, 1].max() + marg))
    for _ in range(2):                                  # at least 500 px each way, then clamp into the ROI
        if c1 - c0 < 500: m = (c0 + c1) // 2; c0, c1 = m - 250, m + 250
        if r1 - r0 < 500: m = (r0 + r1) // 2; r0, r1 = m - 250, m + 250
        c0, c1, r0, r1 = max(0, c0), min(ROI_W, c1), max(0, r0), min(ROI_H, r1)
    if (c1 - c0) * (r1 - r0) > MAX_WINDOW_PX:
        raise SystemExit(f"the terrain window for this route would be {c1 - c0} x {r1 - r0} px (> {MAX_WINDOW_PX / 1e6:.1f} M); "
                         f"use real speed (no --timelapse) or a smaller margin (--margin)")
    E0 = X0 + S * (c0 + c1) / 2; N0 = Y0 - S * (r0 + r1) / 2
    film = dict(window_1m=[c0, c1, r0, r1], start_s=s0, speedup=speedup, walk_m=walk_m, route_m=length, seconds=a.seconds, overview_s=a.overview,
                ov_frames=ov_f, frames=ov_f + walk_f, lmst=a.lmst, sol=rt["sol"], fps=24, tl_frames=tl_f, tail_s0=tail_s0, scan_clean=not a.raw_scans)
    crew = rt.get("crew") or {}
    if crew.get("haven") and crew.get("rover") is not None:
        rx, ry = cell_xy(crew["rover"], X0, Y0, S); film["rover_xy"] = [rx - E0, ry - N0]
    return film


# ------------------------------------------------------------------ captions + encode (Blender sequencer, no ffmpeg on this machine)
def unit_gap(x): return re.sub(r"(\d)([A-Za-z\u00b5\u00b0]+)", lambda m: m.group(1) + " " + m.group(2), x or "")


def caption_lines(rt, film, label):
    """two caption lines: the twin's own numbers for this route, then the data credits"""
    st = rt.get("stats") or {}; vt = rt.get("verdict") or ""; ver = "NO-GO" if vt.startswith("NO-GO") else "GO" if vt.startswith("GO") else ""
    dist = unit_gap(st.get("distance")) or f"{film['route_m'] / 1000:.2f} km"
    t1 = f"MARSWALK route, sol {rt['sol']} | {dist}" + (f" | {st['time']} walking" if st.get("time") else "") + (f" | climb {unit_gap(st['climb'])}" if st.get("climb") else "")          + (f" | flight rules {ver}" if ver else "") + (f" | {len((rt.get('multi') or {}).get('dests') or [])} stops" if rt.get("multi") else "")
    t2 = "HiRISE terrain (NASA/JPL/UArizona), Curiosity Navcam scans (NASA/JPL-Caltech) | pebbles, backpack, gait illustrative | " + label
    return t1, t2


def caption_frames(src, dst, files, rt, film, label):
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs(dst, exist_ok=True)
    fb = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 22); fr = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 15)
    t1, t2 = caption_lines(rt, film, label)
    for fn in files:
        im = Image.open(os.path.join(src, fn)).convert("RGBA"); W, H = im.size; k = W / 960.0
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
        d.rectangle((0, H - int(62 * k), W, H), fill=(14, 10, 8, 150)); d.rectangle((0, H - int(62 * k), int(5 * k), H), fill=(224, 164, 99, 255))
        for txt, base, y, col in ((t1, fb, 56, (246, 238, 228, 255)), (t2, fr, 26, (225, 210, 192, 255))):
            sz = base.size * k; f_ = base.font_variant(size=int(sz))
            while d.textlength(txt, font=f_) > W - 28 * k and sz > 8 * k: sz -= 0.5; f_ = base.font_variant(size=int(sz))     # shrink to fit the frame
            d.text((int(16 * k), H - int(y * k)), txt, font=f_, fill=col)
        Image.alpha_composite(im, ov).convert("RGB").save(os.path.join(dst, fn))


def encode(dst, files, fps, out):
    names = "[" + ",".join(repr(f) for f in files) + "]"
    code = f"""
import bpy, struct
files = {names}
with open(r"{dst}/" + files[0], "rb") as fh: fh.read(16); W, H = struct.unpack(">II", fh.read(8))
sc = bpy.context.scene; sc.render.fps = {fps}; sc.frame_start = 1; sc.frame_end = len(files)
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
se = sc.sequence_editor_create()
st = se.strips.new_image(name="clip", filepath=r"{dst}/" + files[0], channel=1, frame_start=1)
for f in files[1:]: st.elements.append(f)
r = sc.render; r.image_settings.file_format = "FFMPEG"; r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"; r.ffmpeg.ffmpeg_preset = "GOOD"; r.ffmpeg.audio_codec = "NONE"
r.use_sequencer = True; r.filepath = r"{out}"; r.use_file_extension = False
bpy.ops.render.render(animation=True)
"""
    tmp = os.path.join(os.path.dirname(dst), "_encode_tmp.py"); open(tmp, "w").write(code)
    blender = open("tools/blender_path.txt").read().strip()
    rc = subprocess.run([blender, "-b", "--factory-startup", "--python", tmp]).returncode; os.remove(tmp)
    return rc


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("link", help='share link, "#hash", or "default" (the campaign route, like the Campaign start -> end button)')
    ap.add_argument("--name"); g = ap.add_mutually_exclusive_group(); g.add_argument("--preview", action="store_true"); g.add_argument("--final", action="store_true")
    ap.add_argument("--seconds", type=float, default=20.0, help="seconds of walking (default 20), after the overview")
    ap.add_argument("--overview", type=float, default=4.0, help="seconds of crane-down overview first (default 4, min 1)")
    ap.add_argument("--timelapse", action="store_true", help="walk the whole route in --seconds (speed-up capped by --max-speedup) instead of real speed")
    ap.add_argument("--max-speedup", type=float, default=400.0); ap.add_argument("--tail", type=float, default=8.0, help="time-lapse only: seconds of real-speed walk-level shots at the end of the clip (default 8)")
    ap.add_argument("--twin-scans", action="store_true", help="scan clean-up with exactly the twin's limits (clamp -0.2..+0.4, edge 0.6 m) instead of the tighter film tuning")
    ap.add_argument("--raw-scans", action="store_true", help="show the Navcam scans as the raw stereo meshes (default: cleaned as in the twin: curtain triangles dropped, high-pass merge onto HiRISE)")
    ap.add_argument("--start-s", type=float, help="metres along the route where the walk starts (default: through a Navcam scan if the route passes one, else 0)")
    ap.add_argument("--margin", type=float, help="metres of 1 m terrain around the filmed part of the route (default 300, time-lapse 150)")
    ap.add_argument("--lmst", type=int, default=9, choices=(9, 16), help="local mean solar time of the sun (9 = el 42 deg, 16 = low sun)")
    ap.add_argument("--engine", choices=("cycles", "eevee")); ap.add_argument("--res"); ap.add_argument("--spp", type=int); ap.add_argument("--step", type=int, help="render every Nth frame (preview default 2)")
    ap.add_argument("--chunk", type=int, default=40); ap.add_argument("--first", type=int, help="first frame (test)"); ap.add_argument("--last", type=int, help="last frame (test)")
    ap.add_argument("--resume", action="store_true", help="keep frames already rendered in this folder (only if the scene did not change)"); ap.add_argument("--build-only", action="store_true", help="capture + build the scene, no render"); ap.add_argument("--reuse-route", action="store_true", help="use the existing route.json (skip the browser)")
    a = ap.parse_args(); a.overview = max(1.0, a.overview)
    final = a.final
    a.engine = a.engine or "cycles"; a.res = a.res or ("1920x1080" if final else "960x540"); a.spp = a.spp or (64 if final else 16); a.step = a.step or (1 if final else 2)
    h = hash_of(a.link); name = a.name or ("route_" + hashlib.sha1(h.encode()).hexdigest()[:6])
    out = os.path.join(ROOT, "film", "routes", name); os.makedirs(out, exist_ok=True); rj = os.path.join(out, "route.json")
    t_all = time.time()

    # 1. route from the twin
    if a.reuse_route and os.path.exists(rj): rt = json.load(open(rj)); print("reusing", rj)
    else:
        t0 = time.time(); rt = capture(h)
        rt.update(link=a.link, hash=h, captured_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  commit=subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
                  source="demo/twin/twin.html served on 127.0.0.1:%d; cells = window.__routeCells() (twin grid, row*585+col)" % PORT)
        print(f"captured {len(rt['cells'])} cells, sol {rt['sol']}, crew {rt['crew']}, in {time.time() - t0:.0f} s\n  verdict: {(rt['verdict'] or '').splitlines()[0:1]}\n  stats: {rt['stats']}")
        if rt["page_errors"]: print("  page errors:", rt["page_errors"])
    X0, Y0, S = dtm_origin(); film = film_params(rt, a, X0, Y0, S); rt["film"] = film
    json.dump(rt, open(rj, "w"), indent=1)
    print("film:", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in film.items()})

    # 2. scene
    from tools.gpu_lock import gpu_lock, wait_cool
    data_dir = os.path.join(out, "f1_data"); blend = os.path.join(out, "scene.blend"); raw = os.path.join(out, "scene_nosuit.blend")
    env = {**os.environ, "F1_ROUTE_FILE": rj, "F1_OUT": data_dir}
    t0 = time.time(); subprocess.check_call([sys.executable, "tools/f1_prep_data.py"], env=env, stdout=subprocess.DEVNULL); print(f"prep {time.time() - t0:.0f} s")
    blender = open("tools/blender_path.txt").read().strip()
    with gpu_lock("render_route-" + name):                                  # every Blender run (scene build, suit, render, encode) holds the GPU lock
        run_blender_part(a, out, name, final, film, rt, blender, data_dir, blend, raw, t_all, wait_cool)


def scan_env(a):
    """scan clean-up parameters for f1_blender_scene.py. Default = the twin's fitScan plus film tuning (tighter clamp, edges > 0.35 m, facets steeper than 41 deg,
    islands under 1200 triangles dropped): with the twin's own limits the remaining stereo patches still read as floating paper flakes in a close-up."""
    if a.twin_scans: return {}
    return {"F1_SCAN_CLAMP": "-0.1,0.15", "F1_SCAN_EDGE": "0.35", "F1_SCAN_NZ": "0.75", "F1_SCAN_MINCOMP": "1200"}


def run_blender_part(a, out, name, final, film, rt, blender, data_dir, blend, raw, t_all, wait_cool):
    def blender_run(args, env_extra, log, product):    # Blender exits 0 even when the script raised, so check for the product file
        if os.path.exists(product): os.remove(product)
        subprocess.call([blender, "-b"] + args, env={**os.environ, **env_extra}, stdout=open(os.path.join(out, log), "w"), stderr=subprocess.STDOUT)
        if not os.path.exists(product): raise SystemExit(f"Blender did not write {product}; see {os.path.join(out, log)}")
    t0 = time.time(); blender_run(["--python", "tools/f1_blender_scene.py", "--", ROOT], {"F1_DATA_DIR": data_dir, "F1_OUT_BLEND": raw, **scan_env(a)}, "build.log", raw)
    print(f"blender scene {time.time() - t0:.0f} s")
    t0 = time.time(); blender_run([raw, "--python", "tools/f2_suitfix.py"], {"F2_OUT_BLEND": blend}, "suitfix.log", blend)
    os.remove(raw); print(f"suit backpack {time.time() - t0:.0f} s -> {blend}")
    if a.build_only: return

    # 3. render under the GPU lock, then captions and the MP4
    w, hh = a.res.split("x"); fdir = os.path.join(out, "frames_final" if final else "frames_preview")
    for d_ in ((fdir, fdir + "_cap") if not a.resume else ()):          # frames of an older scene must not be reused (the renderer skips existing PNGs)
        if os.path.isdir(d_): [os.remove(os.path.join(d_, x)) for x in os.listdir(d_) if re.fullmatch(r"frame_\d{4}\.png", x)]
    f0 = a.first or 1; f1 = a.last or film["frames"]; todo = list(range(f0, f1 + 1, a.step)); t0 = time.time()
    for i in range(0, len(todo), a.chunk):
        part = todo[i:i + a.chunk]; wait_cool()
        subprocess.check_call([blender, "-b", blend, "--python", "tools/render_route_blender.py", "--", str(part[0]), str(part[-1]), str(a.step), fdir, w, hh, a.engine, str(a.spp)])
    dt = time.time() - t0; print(f"RENDER {len(todo)} frames in {dt:.0f} s = {dt / len(todo):.1f} s/frame ({a.engine}, {a.res}, {a.spp} spp, step {a.step})")
    files = [f"frame_{f:04d}.png" for f in todo]; cap = fdir + "_cap"
    label = f"{a.engine} {a.spp} spp {a.res}" + (" PREVIEW" if not final else "") + (", time-lapse x%.0f" % film["speedup"] if film["speedup"] > 1.5 else "")
    caption_frames(fdir, cap, files, rt, film, label)
    mp4 = os.path.join(out, "final.mp4" if final else "preview.mp4"); fps = 24 // a.step
    rc = encode(cap, files, fps, mp4); print("encode exit", rc, mp4, os.path.exists(mp4) and f"{os.path.getsize(mp4) / 1e6:.1f} MB")
    print(f"total {time.time() - t_all:.0f} s")


if __name__ == "__main__":
    main()
