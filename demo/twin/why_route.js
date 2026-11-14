/* "Why this route" overlay for twin.html (button + key W).
 *
 * twin.html keeps the route, the terrain arrays and the camera inside one closure, so this file reads them without
 * editing the page: it (1) records the route cells the page strokes onto its terrain texture, (2) re-reads the same
 * terrain arrays from data.json (browser cache), (3) uses the page's own exported astronaut model (window.__walk.suitModel,
 * the JS port of phase4/astronaut.py v2) and (4) wraps THREE.OrbitControls / renderer.render to learn the controls,
 * camera and scene. Nothing here invents a number: every value is computed from those inputs, or shown as "not available".
 * Tags: "measured" = from NASA data (HiRISE DTM, RAD); "modelled" = planner cost or astronaut model; "simulated" = scripted event.
 * Also exposes window.MW for tour.js.
 */
(function () {
  "use strict";
  if (window.MW) return;
  const MW = window.MW = { raw: null, rawVer: 0, controls: null, camera: null, scene: null, data: null, home: null, A: null };
  const $ = id => document.getElementById(id);

  // ---- hook 1: controls + camera (twin.html constructs the controls after its first awaits, i.e. after this runs)
  try {
    if (window.THREE && THREE.OrbitControls) {
      const O = THREE.OrbitControls;
      const Wrap = function (obj, el) { const c = new O(obj, el); MW.controls = c; MW.camera = obj; return c; };
      Wrap.prototype = O.prototype; THREE.OrbitControls = Wrap;
    }
  } catch (e) { console.warn("why_route: OrbitControls hook unavailable: " + e.message); }

  // ---- hook 2: scene, from the page's own render call
  (function waitWalk(n) {
    const WK = window.__walk;
    if (!WK || !WK.renderer) { if (n < 1800) requestAnimationFrame(() => waitWalk(n + 1)); return; }
    const r = WK.renderer, orig = r.render.bind(r);
    r.render = function (s, c) { if (c === MW.camera && s !== MW.scene) { MW.scene = s; if (!MW.home && MW.controls) MW.home = { t: MW.controls.target.clone(), p: MW.camera.position.clone() }; } return orig(s, c); };
  })(0);

  // ---- hook 3: the route polyline. drawTexture() strokes it as width 6, #6fd8ea, after drawImage(terrain photo).
  try {
    const P = CanvasRenderingContext2D.prototype, oBegin = P.beginPath, oMove = P.moveTo, oLine = P.lineTo, oStroke = P.stroke;
    let pts = null;
    P.beginPath = function () { pts = null; return oBegin.call(this); };
    P.moveTo = function (x, y) { if (this.canvas && !this.canvas.isConnected) pts = [[x, y]]; return oMove.call(this, x, y); };
    P.lineTo = function (x, y) { if (pts) pts.push([x, y]); return oLine.call(this, x, y); };
    P.stroke = function () {
      if (pts && pts.length > 1 && this.lineWidth === 6 && this.strokeStyle === "#6fd8ea") {
        const a = pts[0], b = pts[pts.length - 1], k = pts.length + ":" + a[0] + "," + a[1] + ":" + b[0] + "," + b[1];
        if (!MW.raw || MW.raw.key !== k) { MW.raw = { pts, cw: this.canvas.width, ch: this.canvas.height, key: k }; MW.rawVer++; }
      }
      pts = null; return oStroke.call(this);
    };
  } catch (e) { console.warn("why_route: route hook unavailable: " + e.message); }

  // ---- terrain arrays (same decode as twin.html)
  const bytes = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  MW.ready = (async function () {
    const D = await (await fetch("data.json")).json(), G = D.grid, N = G.w * G.h;
    const zq = new Uint16Array(bytes(D.z).buffer), Z = new Float32Array(N);
    let zMean = 0; for (let i = 0; i < N; i++) { Z[i] = G.zmin + zq[i] * G.zscale; zMean += Z[i]; } zMean /= N;
    MW.data = { W: G.w, H: G.h, CELL: G.cell_m, Z, zMean, SLOPE: bytes(D.slope), ROUGH: bytes(D.rough), LOOSE: bytes(D.loose), rad: D.rad, dtm: D.dtm, ortho: D.ortho };
    return MW.data;
  })().catch(e => { console.warn("why_route: data.json not readable: " + e.message); return null; });

  // flight rule names: copied from phase4/safety_validator.py RULES (plan-time rules)
  const RULE = { "CS-01": "Terrain slope above the walker's limit", "CS-02": "Obstacle roughness above the limit", "CS-03": "Terrain unknown (no slope or roughness data)",
    "CS-04": "Terrain data confidence too low", "CS-05": "EVA time with the walk back exceeds the limit minus the reserve", "CS-06": "Walking energy with the walk back exceeds the budget minus the reserve",
    "CS-07": "Radiation dose of the round trip exceeds the per-EVA limit", "HZ-1": "Route crosses the core of a dust event", "SY-01": "Route is empty", "SY-02": "Route leaves the terrain grid",
    "SY-03": "Route is not continuous (cells not 8-neighbours)" };

  const toWorld = (gx, gy) => { const d = MW.data; return [(gx - (d.W - 1) / 2) * d.CELL, (gy - (d.H - 1) / 2) * d.CELL]; };
  const hAt = (gx, gy) => { const d = MW.data, EX = +($("ex") || { value: 1.5 }).value; const W = d.W, Z = d.Z;
    gx = Math.max(0, Math.min(W - 1.001, gx)); gy = Math.max(0, Math.min(d.H - 1.001, gy));
    const x0 = Math.floor(gx), y0 = Math.floor(gy), fx = gx - x0, fy = gy - y0, i = y0 * W + x0;
    return (Z[i] * (1 - fx) * (1 - fy) + Z[i + 1] * fx * (1 - fy) + Z[i + W] * (1 - fx) * fy + Z[i + W + 1] * fx * fy - d.zMean) * EX; };
  MW.worldOf = (cell) => { const d = MW.data, gx = cell % d.W, gy = Math.floor(cell / d.W), [x, z] = toWorld(gx, gy); return [x, hAt(gx, gy), z]; };

  function routeCells() {
    const d = MW.data, r = MW.raw, wk = window.__walk;
    if (!d) return null;
    const sd = $("sDist"); if (sd && sd.textContent.trim() === "–") return null;      // page shows no route stats: route was cleared
    if (wk && wk.on && wk.routeCells) { try { return wk.routeCells(); } catch (e) { /* fall through */ } }
    if (!r) return null;
    const sx = r.cw / d.W, sy = r.ch / d.H;
    return r.pts.map(p => Math.round(p[1] / sy - 0.5) * d.W + Math.round(p[0] / sx - 0.5));
  }

  const planW = () => Object.assign({ slope: 2, rough: 12, loose: 1.5, climb: 3, descent: 0.5 }, (window.__planner && window.__planner.weights) || {});
  // ---- analysis of the current route
  function analyse() {
    const d = MW.data, sm = window.__walk && window.__walk.suitModel, cells = routeCells();
    if (!d || !cells || cells.length < 2) return null;
    const { W, CELL, Z, SLOPE, ROUGH, LOOSE } = d, maxS = window.__planner && window.__planner.limit ? window.__planner.limit() : +$("maxSlope").value, sol = +$("sol").value;
    const PW = planW();   // live planner weights from twin.html (Route preferences); defaults 2, 12, 1.5, 3, 0.5
    const cost = (run, dz, n) => { const t = { base: run, slope: run * PW.slope * (SLOPE[n] / maxS) ** 2, rough: run * Math.max(0, ROUGH[n] / 200 - 0.08) * PW.rough,
      loose: run * LOOSE[n] / 255 * PW.loose, climb: Math.max(0, dz) * PW.climb, descent: Math.max(0, -dz) * PW.descent }; t.total = t.base + t.slope + t.rough + t.loose + t.climb + t.descent; return t; };
    const crew = window.__crew ? window.__crew.state() : { carried: 0, pair: false, haven: false, rover: null };
    const A = { cells, maxS, sol, PW, crew, steps: [], terms: { base: 0, slope: 0, rough: 0, loose: 0, climb: 0, descent: 0, total: 0 }, dist: 0, climb: 0, steep: 0 };
    const ds = [], gs = [];
    for (let k = 1; k < cells.length; k++) {
      const a = cells[k - 1], b = cells[k], pd = CELL * Math.hypot(Math.floor(a / W) - Math.floor(b / W), a % W - b % W); if (!pd) continue;
      const dz = Z[b] - Z[a], t = cost(pd, dz, b);
      A.steps.push({ b, t }); for (const q in A.terms) A.terms[q] += t[q];
      A.dist += pd; A.climb += Math.max(0, dz); A.steep = Math.max(A.steep, SLOPE[b]); ds.push(Math.hypot(pd, dz)); gs.push(dz / pd);
    }
    // astronaut model v2 (same recursion as twin.html suitTrack); the walk back starts with fresh fatigue, as there
    if (sm) {
      const S = sm.SUIT, fat = (f, e) => Math.min(1, Math.max(0, f + e / S.fatCap));
      const res = (dd, gg) => { let t = 0, e = 0, f = 0; for (let k = 0; k < dd.length; k++) { const v = sm.stepSpeed(gg[k], f), de = sm.stepEnergy(dd[k], gg[k]); t += dd[k] / v; e += de; f = fat(f, de); } return { t, e, f }; };
      A.out = res(ds, gs); A.back = res(ds.slice().reverse(), gs.slice().reverse().map(g => -g)); A.suit = S;
      const keep = 1 - S.reserve, rate = (d.rad.reduce((a, b) => Math.abs(b.sol - sol) < Math.abs(a.sol - sol) ? b : a)).uGy_h;
      A.rate = rate; A.tlim = S.evaH * 3600 * keep; A.elim = S.eBudget * keep;
      A.useT = (A.out.t + A.back.t) / A.tlim; A.useE = (A.out.e + A.back.e) / A.elim; A.useD = rate * (A.out.t + A.back.t) / 3600 / S.doseBudget;
    }
    // equal-count segments, dominant = largest added cost (total minus plain distance)
    const nSeg = Math.min(24, A.steps.length), segs = [];
    for (let s = 0; s < nSeg; s++) { const i0 = Math.floor(s * A.steps.length / nSeg), i1 = Math.floor((s + 1) * A.steps.length / nSeg), t = { base: 0, slope: 0, rough: 0, loose: 0, climb: 0, descent: 0, total: 0 };
      for (let i = i0; i < i1; i++) for (const q in t) t[q] += A.steps[i].t[q];
      let dom = "slope", dv = -1; for (const q of ["slope", "rough", "loose", "climb", "descent"]) if (t[q] > dv) { dv = t[q]; dom = q; }
      segs.push({ i0, i1, t, extra: t.total - t.base, dom, domVal: dv, len: t.base }); }
    A.segs = segs; A.dom = segs.reduce((a, b) => b.extra > a.extra ? b : a, segs[0]);
    // rejected alternative: straight line start to end on the same grid
    const c0 = cells[0], c1 = cells[cells.length - 1], x0 = c0 % W, y0 = Math.floor(c0 / W), x1 = c1 % W, y1 = Math.floor(c1 / W), n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0));
    const L = { cells: 0, over: 0, steep: 0, dist: 0, cost: 0, cells_list: [c0] }; let prev = c0;
    // every cell the line passes through (4 samples per cell step, same as tools/f1_prep_data.py), so the film and the page agree
    const N = 4 * n + 1;
    for (let i = 1; i <= N; i++) { const c = Math.round(y0 + (y1 - y0) * i / N) * W + Math.round(x0 + (x1 - x0) * i / N); if (c === prev) continue;
      const pd = CELL * Math.hypot(Math.floor(c / W) - Math.floor(prev / W), c % W - prev % W); L.cells++; L.cells_list.push(c); L.dist += pd; L.steep = Math.max(L.steep, SLOPE[c]); if (SLOPE[c] > maxS) L.over++;
      L.cost += cost(pd, Z[c] - Z[prev], c).total; prev = c; }
    L.walk = L.dist; L.dist = CELL * Math.hypot(x1 - x0, y1 - y0);   // a walker on a straight line covers the straight distance, not the cell staircase
    A.line = L; A.overFrac = (() => { let k = 0; for (let i = 0; i < SLOPE.length; i++) if (SLOPE[i] > maxS) k++; return k / SLOPE.length; })();
    // flight rules from the page's own validator port (window.__flight, equal to the Python validator on the 47-case test)
    const fl = window.__flight, rate0 = A.rate != null ? A.rate : undefined;
    if (fl && fl.check && MW.flightReady) { try { A.flight = fl.check(cells, rate0); L.flight = fl.check(L.cells_list, rate0); } catch (e) { A.flight = null; } }
    return A;
  }
  MW.analyse = analyse;

  // ---- panel
  const css = document.createElement("style");
  css.textContent = `
.mw-bar{position:absolute;top:12px;right:12px;display:flex;gap:6px;z-index:6}
.mw-bar button{background:rgba(22,17,13,.82)}
.mw-bar button[aria-pressed=true]{background:var(--dust,#e0a463);color:var(--ground,#16110d);border-color:var(--dust,#e0a463)}
@media (max-width:700px){.mw-bar{top:12px;bottom:auto}}
.view.walking .mw-bar{display:none}
.mw-panel{position:absolute;top:48px;right:12px;bottom:12px;width:min(390px,calc(100% - 24px));overflow:auto;z-index:7;background:rgba(22,17,13,.94);border:1px solid var(--line,#3b2e24);border-radius:4px;padding:10px 12px;font-size:12px;line-height:1.45;color:var(--fg,#f1e7da)}
@media (max-width:700px){.mw-panel{top:12px;bottom:44px}}
.mw-panel h3{margin:0;font:700 14px var(--display,sans-serif);text-transform:uppercase;letter-spacing:.04em}
.mw-panel h4{margin:12px 0 4px;font:600 11px var(--mono,monospace);letter-spacing:.08em;text-transform:uppercase;color:var(--dust,#e0a463)}
.mw-panel h4 .mw-t{text-transform:none;letter-spacing:0}
.mw-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
.mw-r{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:2px 0;border-bottom:1px solid rgba(255,255,255,.06)}
.mw-r b{font:500 12px var(--mono,monospace);text-align:right;font-variant-numeric:tabular-nums}
.mw-t{display:inline-block;font:10px var(--mono,monospace);padding:0 4px;border-radius:2px;margin-left:4px;vertical-align:1px}
.mw-t.m{background:#244a3a;color:#bff0d6}.mw-t.s{background:#3d3a63;color:#d6d2ff}.mw-t.x{background:#5a3a1e;color:#ffd9a8}
.mw-n{color:var(--muted,#a99785);font-size:11px;margin:3px 0}
.mw-ok{color:var(--ok,#9fd27a)}.mw-bad{color:var(--hazard,#e5563c)}
.mw-segs{display:flex;align-items:flex-end;gap:2px;height:46px;margin:4px 0}
.mw-segs i{flex:1;background:#6fd8ea;opacity:.75;min-height:2px}.mw-segs i.d{background:#ff9f1c;opacity:1}
.mw-panel label{display:flex;gap:6px;align-items:center;margin-top:8px}
`;
  document.head.appendChild(css);

  const view = $("view"); if (!view) return;
  const bar = document.createElement("div"); bar.className = "mw-bar";
  const btn = document.createElement("button"); btn.type = "button"; btn.id = "mwBtn"; btn.setAttribute("aria-pressed", "false"); btn.title = "Why this route (key W)"; btn.textContent = "Why this route (W)";
  bar.appendChild(btn); view.appendChild(bar);
  MW.bar = bar;
  const panel = document.createElement("div"); panel.className = "mw-panel"; panel.id = "mwPanel"; panel.hidden = true; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Why this route");
  view.appendChild(panel);

  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const NA = '<b>not available</b>';
  const tag = k => `<span class="mw-t ${k === "measured" ? "m" : k === "modelled" ? "s" : "x"}">${k}</span>`;
  const row = (l, v, t) => `<div class="mw-r"><span>${l}${t ? tag(t) : ""}</span>${v == null ? NA : `<b>${v}</b>`}</div>`;
  const hm = s => { const m = Math.round(s / 60); return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min` : `${m} min`; };
  const pct = x => (100 * x).toFixed(0) + " %";
  const TERM = { slope: "slope (cell slope vs limit, squared)", rough: "roughness above 8 cm (5 m scale)", loose: "loose ground (THEMIS)", climb: "climb (per m up)", descent: "descent (per m down)" };
  const termLbl = (q, PW) => q === "climb" ? `climb (${PW.climb} per m up)` : q === "descent" ? `descent (${PW.descent} per m down)` : TERM[q];

  // replan reason: demo/twin/replan.json, written by tools/export_replan.py from phase5/replan.py (a committed file, so no 404)
  MW.replan = null; MW.replanTried = false;
  MW.loadReplan = () => MW.replanTried ? Promise.resolve(MW.replan) : (MW.replanTried = true, fetch("replan.json").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(j => (MW.replan = j)).catch(() => null));

  let hl = null, hlKey = "";
  function clearHl() { if (hl && MW.scene) { MW.scene.remove(hl); hl.geometry.dispose(); hl.material.dispose(); } hl = null; hlKey = ""; }
  function drawHl(A) {
    const on = !panel.hidden && $("mwHl") && $("mwHl").checked && A && MW.scene && window.THREE;
    if (!on) { clearHl(); return; }
    const key = A.dom.i0 + ":" + A.dom.i1 + ":" + A.cells.length + ":" + $("ex").value + ":" + (MW.scene.uuid);
    if (key === hlKey) return; clearHl();
    const pts = []; for (let i = A.dom.i0; i <= A.dom.i1 && i < A.steps.length; i++) { const w = MW.worldOf(A.steps[i].b); pts.push(new THREE.Vector3(w[0], w[1] + 6, w[2])); }
    if (pts.length < 2) return;
    hl = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), Math.max(8, pts.length * 3), 6, 6, false), new THREE.MeshBasicMaterial({ color: 0xff9f1c, depthTest: false, transparent: true, opacity: 0.95 }));
    hl.renderOrder = 20; MW.scene.add(hl); hlKey = key;
  }

  function render() {
    const A = MW.A = analyse(), keepHl = $("mwHl") ? $("mwHl").checked : true;
    let h = `<div class="mw-head"><h3>Why this route</h3><button type="button" id="mwX" aria-label="Close">Close</button></div>`;
    h += `<div class="mw-n">${tag("measured")} NASA data (HiRISE terrain model, RAD dose rate) ${tag("modelled")} planner cost or astronaut model v2 (not validated physiology) ${tag("simulated")} scripted event</div>`;
    if (!MW.data) h += `<p>Terrain data not available (data.json could not be read).</p>`;
    else if (!A) h += `<p>No route yet. Click the terrain twice to set a start and an end, or press "Campaign start &rarr; end".</p>`;
    else {
      h += `<h4>Totals</h4>`;
      h += row("Distance, 4 m steps (planar)", (A.dist / 1000).toFixed(2) + " km", "measured");
      h += row("Climb", Math.round(A.climb) + " m", "measured");
      h += row("Steepest cell on the route", A.steep + "&deg;", "measured");
      { const me = window.__planner && window.__planner.mapErr, mg = window.__planner && window.__planner.margin && window.__planner.margin();
        if (me) h += `<div class="mw-n">Map slope accuracy: +/-${me.deg}&deg; mean error vs Curiosity's tilt sensor (measured, ${me.stops} stops).${mg ? ` Safety margin applied: planned to ${A.maxS.toFixed(1)}&deg;.` : ""}</div>`; }
      const cw = A.crew, F0 = A.flight, rv = cw.haven && cw.rover != null ? `rover at x ${cw.rover % MW.data.W}, y ${Math.floor(cw.rover / MW.data.W)}` : null;
      h += row("Walk-back measured to", rv ? esc(rv) : "start", "modelled");
      if (rv) h += `<div class="mw-n">The rover is modelled support (a future crew rover, not Curiosity's capability), used as the point of refuge. The rules take the worst abort point along the route: time and energy spent so far plus the walk from there to the rover on the cheapest allowed path.</div>`;
      h += row("Carried load, each astronaut", cw.carried > 0 ? cw.carried + " kg" : "none", "modelled");
      h += row("Crew", cw.pair ? "2 astronauts (buddy pair)" : "1 astronaut", "modelled");
      h += row(`Energy, one way (model v2${cw.carried > 0 ? ", with " + cw.carried + " kg carried" : ""})`, A.out ? A.out.e.toFixed(0) + " kJ" : null, "modelled");
      if (cw.pair && F0 && F0.E != null) h += row("Per person / crew total energy at the worst abort point", `${F0.E.toFixed(0)} / ${(2 * F0.E).toFixed(0)} kJ`, "modelled") +
        row("Per person / crew total metabolic O2 (kJ / 20.1 J per ml)", `${(F0.E / 20.1).toFixed(0)} / ${(2 * F0.E / 20.1).toFixed(0)} L`, "modelled") +
        `<div class="mw-n">Both astronauts must pass CS-05 to CS-07 on their own numbers (NASA DRA 5.0 section 5.2: EVAs by a minimum of two people, a buddy system). Suit leakage, ventilation and partner assistance are not modelled.</div>`;
      h += row("Time, one way (model v2, with fatigue)", A.out ? hm(A.out.t) : null, "modelled");
      h += row("Walking time shown in the rail (speed only)", ($("sTime").textContent || "").replace(/(\d)([a-z])/gi, "$1 $2").replace(/\s+/g, " ").trim() || null, "modelled");
      h += row(`Dose, ${A.crew.haven ? "worst abort point to the rover" : "round trip with fatigue"}, sol ${A.sol} rate (the rail shows one way)`, A.out ? (A.rate * (A.crew.haven && A.flight && A.flight.T != null ? A.flight.T : A.out.t + A.back.t) / 3600).toFixed(2) + " &micro;Gy" : null, "modelled");
      h += `<div class="mw-n">Dose = measured RAD rate (${A.rate != null ? A.rate.toFixed(2) + " &micro;Gy/h" : "not available"}) &times; modelled time.</div>`;

      h += `<h4>Planner cost by term ${tag("modelled")}</h4>`;
      h += `<div class="mw-n">Per 4 m step: run &times; (1 + ${A.PW.slope}(slope/limit)&sup2; + ${A.PW.rough} &times; roughness above 8 cm + ${A.PW.loose} &times; loose/255) + ${A.PW.climb} &times; climb + ${A.PW.descent} &times; descent (the A* in twin.html, with the weights set under Route preferences${["slope", "rough", "loose", "climb", "descent"].every(q => A.PW[q] === ({ slope: 2, rough: 12, loose: 1.5, climb: 3, descent: 0.5 })[q]) ? "; these are the defaults" : "; NOT the defaults"}). Units: metres-equivalent.</div>`;
      h += row("Plain distance (cost on flat, smooth ground)", A.terms.base.toFixed(0));
      for (const q of ["slope", "rough", "loose", "climb", "descent"]) h += row(termLbl(q, A.PW), `${A.terms[q].toFixed(0)} (${pct(A.terms[q] / A.terms.total)})`);
      h += row("Total route cost", A.terms.total.toFixed(0));

      const mx = Math.max(...A.segs.map(s => s.extra), 1e-9), di = A.segs.indexOf(A.dom);
      h += `<h4>Cost by segment ${tag("modelled")}</h4><div class="mw-segs" role="img" aria-label="Added cost for ${A.segs.length} equal segments">` +
        A.segs.map((s, k) => `<i class="${k === di ? "d" : ""}" style="height:${Math.max(4, 100 * s.extra / mx)}%" title="segment ${k + 1}: +${s.extra.toFixed(0)} added cost, mostly ${s.dom}"></i>`).join("") + `</div>`;
      h += `<div class="mw-n">Segment ${di + 1} of ${A.segs.length} adds the most cost: +${A.dom.extra.toFixed(0)} over ${A.dom.len.toFixed(0)} m, mostly ${esc(termLbl(A.dom.dom, A.PW))} (${pct(A.dom.domVal / Math.max(A.dom.extra, 1e-9))} of its added cost).</div>`;
      h += `<label><input type="checkbox" id="mwHl" ${keepHl ? "checked" : ""}> Highlight this segment on the 3D route (orange)</label>`;

      h += `<h4>Flight rules checked</h4><div class="mw-n">Page validator (window.__flight), equal to the Python validator on its 47-case test. MARSWALK's own rules, not NASA values. Daylight (CS-08) is not checked on this page.</div>`;
      const F = A.flight, fr = f => f.rules_failed.map(r => `${r} ${esc(RULE[r] || "")}`).join("; ");
      if (F) {
        h += `<div class="mw-r"><span>Validator decision (same as the panel under the route stats)</span><b class="${F.decision === "GO" ? "mw-ok" : "mw-bad"}">${esc(F.decision)}${F.rule ? " " + esc(F.rule) : ""}</b></div>`;
        h += `<div class="mw-n">${F.decision === "GO" ? "CS-01 to CS-07 and SY-01 to SY-03 all pass." : "Deciding rule " + esc(F.rule) + ". Failed: " + fr(F) + "."} ${tag("modelled")}</div>`;
        h += `<div class="mw-n">CS-01 slope: the planner never enters a cell above the ${window.__planner && window.__planner.margin && window.__planner.margin() ? A.maxS.toFixed(1) + "&deg; limit (slider less the map-error safety margin)" : A.maxS + "&deg; limit"}; steepest cell here ${A.steep}&deg; ${tag("measured")}.</div>`;
        if (F.T != null) { const lim = A.suit ? ` (limits ${hm(A.tlim)} and ${A.elim.toFixed(0)} kJ, after the ${pct(A.suit.reserve)} reserve)` : "";
          h += `<div class="mw-n">${A.crew.haven ? "Worst abort point, walking to the rover" : "Round trip"} (CS-05, CS-06): ${hm(F.T)}, ${F.E.toFixed(0)} kJ${lim}. Dose (CS-07): ${A.out ? (A.rate * F.T / 3600).toFixed(2) + " &micro;Gy of " + A.suit.doseBudget : "not available"} ${tag("modelled")}.</div>`; }
      } else h += `<div class="mw-n">${MW.flightReady ? "Flight check not available." : "Checking flight rules&hellip;"}</div>`;

      const L = A.line;
      h += `<h4>Rejected alternative: straight line</h4>`;
      const LF = L.flight, LD = `${(L.dist / 1000).toFixed(2)} km against ${(A.dist / 1000).toFixed(2)} km for the route`;
      if (LF && LF.decision !== "GO") h += `<div class="mw-r"><span>Start to end in a straight line</span><b class="mw-bad">rejected</b></div><div class="mw-n">Flight rules say NO-GO: ${esc(LF.rule)} ${esc(RULE[LF.rule] || "")}${LF.rules_failed.length > 1 ? "; also " + esc(LF.rules_failed.slice(1).join(", ")) : ""}. ${L.over} of its ${L.cells} cells are steeper than ${A.maxS}&deg; (steepest ${L.steep}&deg;) ${tag("measured")}. ${LD}.</div>`;
      else h += `<div class="mw-r"><span>Start to end in a straight line</span><b>${LF ? "passes the rules" : "not available"}</b></div><div class="mw-n">${LF ? "It passes the flight rules, so the planner chose by cost: " : ""}straight-line cost ${L.over ? "not comparable (cells above the limit)" : L.cost.toFixed(0)} against ${A.terms.total.toFixed(0)} for the route; ${LD} ${tag("modelled")}.</div>`;
    }

    h += `<h4>Hazard replan <span id="mwRep"></span></h4><div id="mwRepBody" class="mw-n">Checking for the replan output&hellip;</div>`;
    panel.innerHTML = h;
    $("mwX").onclick = () => toggle(false);
    if ($("mwHl")) $("mwHl").onchange = () => drawHl(MW.A);
    drawHl(A);
    MW.loadReplan().then(j => {
      const b = $("mwRepBody"); if (!b) return;
      if (!j) { b.innerHTML = `Replan output not available (replan.json could not be read).`; return; }
      const k = x => (x / 1000).toFixed(2) + " km";
      b.innerHTML = `${tag("simulated")} <b style="text-align:left">${esc(j.rule || "no rule")}</b><br>${esc(j.explanation || "")}` +
        `<br>Rest of the walk, before: ${k(j.before.distance_m)}, ${j.before.energy_kj.toFixed(0)} kJ; after: ${k(j.after.distance_m)}, ${j.after.energy_kj.toFixed(0)} kJ ${tag("modelled")}.` +
        `<br><span>Event: simulated, seed ${j.provenance.seed}. Route: Python A* on the campaign start to end. Source ${esc(j.provenance.script)}, commit ${esc(j.provenance.git_hash)}.</span>`;
    });
  }

  function toggle(on) {
    on = on == null ? panel.hidden : on; panel.hidden = !on; btn.setAttribute("aria-pressed", String(on));
    if (on) { MW.ready.then(() => (window.__flight && __flight.ready ? __flight.ready().catch(() => 0) : 0)).then(() => { MW.flightReady = !!window.__flight; render(); }); } else clearHl();
  }
  MW.togglePanel = toggle; MW.panel = panel;
  btn.addEventListener("click", () => toggle());
  document.addEventListener("keydown", e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target, tn = t && t.tagName; if (tn === "INPUT" || tn === "SELECT" || tn === "TEXTAREA" || (t && t.isContentEditable)) return;
    if (e.key === "w" || e.key === "W") { toggle(); e.preventDefault(); }
    else if (e.key === "Escape" && !panel.hidden && !(window.MWTour && MWTour.active)) toggle(false);
  });
  // keep the panel current while open: route, slope limit, sol or exaggeration changed
  let last = "";
  setInterval(() => { if (panel.hidden) return; const k = MW.flightReady + "|" + MW.rawVer + "|" + ($("sDist") || {}).textContent + "|" + $("maxSlope").value + "|" + (window.__planner && window.__planner.limit ? window.__planner.limit() : "") + "|" + $("sol").value + "|" + $("ex").value + "|" + JSON.stringify(planW()) + "|" + JSON.stringify(window.__crew ? window.__crew.state() : null) + "|" + (window.__walk && window.__walk.on) + "|" + (MW.scene && MW.scene.uuid);
    if (k !== last) { last = k; const st = panel.scrollTop; render(); panel.scrollTop = st; } }, 500);
})();
