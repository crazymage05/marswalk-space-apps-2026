/* "Rock chemistry (ChemCam, APXS)" layer for twin.html. One script tag, nothing else to edit.
 *
 * How it plugs in (same way why_route.js / tour.js do): it adds one checkbox to the Layers list (.toggles), and draws on its own
 * transparent canvas laid over #view. It projects each target with the page's camera (window.MW.camera, published by why_route.js)
 * and the page's own terrain arrays (MW.data, same data.json decode) so markers sit on the terrain at the current vertical
 * exaggeration (#ex). Data: chem.json (built by tools/export_chem_twin.py from PDS ChemCam MOC and APXS oxide tables).
 * Every number on the card comes from chem.json; the tag says "measured". Positions are the rover's waypoint, not the target.
 */
(function () {
  "use strict";
  if (window.__chem) return;
  const $ = id => document.getElementById(id);
  const base = (() => { try { const s = document.currentScript && document.currentScript.src; return s ? s.replace(/[^/]*$/, "") : ""; } catch (e) { return ""; } })();
  const COL = { cc: "#ff8fb8", ap: "#9be564" };
  const ORDER = ["SiO2", "TiO2", "Al2O3", "FeOT", "FeO", "MgO", "CaO", "Na2O", "K2O", "MnO", "P2O5", "SO3", "Cl", "Cr2O3"];
  const BAR_MAX = 60;   // wt% at full bar width
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const S = window.__chem = { on: false, targets: [], hover: null, pinned: null, ready: false };

  function start(view, toggles) {
    const css = document.createElement("style");
    css.textContent = `
#chemCv { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; z-index:4; }
#chemCard { position:absolute; z-index:7; width:min(300px, calc(100% - 24px)); background:rgba(31,24,19,0.96); border:1px solid #6b5a49; border-radius:4px;
  padding:10px 12px; color:#f1e7da; font-size:12px; line-height:1.35; box-shadow:0 6px 20px rgba(0,0,0,0.5); }
#chemCard[hidden] { display:none; }
#chemCard h3 { margin:0 0 2px; font-size:14px; font-weight:700; padding-right:18px; word-break:break-word; }
#chemCard .meta { color:#d8c8b4; margin-bottom:6px; }
#chemCard .tag { display:inline-block; font-family:ui-monospace,Consolas,monospace; font-size:10px; letter-spacing:.05em; text-transform:uppercase;
  border:1px solid #9be564; color:#9be564; border-radius:3px; padding:0 4px; margin-left:6px; }
#chemCard .ox { display:grid; grid-template-columns:44px 1fr 92px; align-items:center; gap:6px; margin:2px 0; }
#chemCard .ox .bar { height:7px; background:#3a2e25; border-radius:2px; overflow:hidden; }
#chemCard .ox .bar i { display:block; height:100%; }
#chemCard .ox .v { text-align:right; font-variant-numeric:tabular-nums; }
#chemCard .ox .v small { color:#c9b8a3; }
#chemCard .note { color:#d8c8b4; font-size:11px; margin-top:6px; }
#chemCard button { position:absolute; top:4px; right:6px; background:none; border:0; color:#f1e7da; font-size:16px; cursor:pointer; line-height:1; }
#chemLegend { position:absolute; left:12px; bottom:12px; z-index:5; background:rgba(22,17,13,0.82); border:1px solid #4a3d32; border-radius:3px;
  padding:4px 8px; font-size:11px; color:#f1e7da; pointer-events:none; }
#chemLegend[hidden] { display:none; }`;
    document.head.appendChild(css);

    const cv = document.createElement("canvas"); cv.id = "chemCv"; cv.setAttribute("aria-hidden", "true"); view.appendChild(cv);
    const ctx = cv.getContext("2d");
    const card = document.createElement("div"); card.id = "chemCard"; card.hidden = true; card.setAttribute("role", "dialog"); card.setAttribute("aria-label", "Rock chemistry of one target");
    view.appendChild(card);
    const legend = document.createElement("div"); legend.id = "chemLegend"; legend.hidden = true; view.appendChild(legend);

    const lab = document.createElement("label");
    lab.innerHTML = '<input type="checkbox" id="lyChem"> <span class="sw" style="background:linear-gradient(90deg,#ff8fb8 50%,#9be564 50%)"></span> Rock chemistry (ChemCam, APXS)';
    toggles.appendChild(lab);
    const box = lab.querySelector("input");
    box.onchange = () => { S.on = box.checked; legend.hidden = !S.on; if (!S.on) { S.pinned = S.hover = null; card.hidden = true; } };

    let proj = [];   // [{t, px, py}] visible markers this frame
    const v = new THREE.Vector3();

    function hAt(gx, gy) {
      const d = MW.data, EX = +(($("ex") || { value: 1.5 }).value), W = d.W, Z = d.Z;
      gx = Math.max(0, Math.min(W - 1.001, gx)); gy = Math.max(0, Math.min(d.H - 1.001, gy));
      const x0 = Math.floor(gx), y0 = Math.floor(gy), fx = gx - x0, fy = gy - y0, i = y0 * W + x0;
      return (Z[i] * (1 - fx) * (1 - fy) + Z[i + 1] * fx * (1 - fy) + Z[i + W] * (1 - fx) * fy + Z[i + W + 1] * fx * fy - d.zMean) * EX;
    }
    function frame() {
      requestAnimationFrame(frame);
      const r = view.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
      if (cv.width !== Math.round(r.width * dpr) || cv.height !== Math.round(r.height * dpr)) { cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, r.width, r.height);
      proj = [];
      const walking = window.__walk && window.__walk.on;
      if (!S.on || walking || !MW.camera || !MW.data) { if (walking) card.hidden = true; return; }
      const d = MW.data, cam = MW.camera, seen = {};
      for (const t of S.targets) {
        const k = t.x + "," + t.y, n = seen[k] = (seen[k] || 0) + 1;
        v.set((t.x - (d.W - 1) / 2) * d.CELL, hAt(t.x, t.y) + 30, (t.y - (d.H - 1) / 2) * d.CELL).project(cam);
        if (v.z > 1 || Math.abs(v.x) > 1.05 || Math.abs(v.y) > 1.05) continue;
        // targets that share a waypoint are fanned out on a small ring so each stays clickable
        const a = n * 2.4, rad = n === 1 ? 0 : 5 + 1.8 * Math.sqrt(n);
        proj.push({ t, px: (v.x + 1) / 2 * r.width + Math.cos(a) * rad, py: (1 - v.y) / 2 * r.height + Math.sin(a) * rad });
      }
      for (const p of proj) {
        const sel = p.t === S.pinned || p.t === S.hover, c = p.t.instrument === "APXS" ? COL.ap : COL.cc, s = sel ? 7 : 4;
        ctx.beginPath();
        if (p.t.instrument === "APXS") { ctx.moveTo(p.px, p.py - s - 1); ctx.lineTo(p.px + s + 1, p.py); ctx.lineTo(p.px, p.py + s + 1); ctx.lineTo(p.px - s - 1, p.py); ctx.closePath(); }
        else ctx.arc(p.px, p.py, s, 0, 7);
        ctx.fillStyle = c; ctx.fill(); ctx.lineWidth = sel ? 2.5 : 1.5; ctx.strokeStyle = sel ? "#fff" : "#16110d"; ctx.stroke();
      }
      if (card.hidden === false && (S.pinned || S.hover)) place(S.pinned || S.hover);
    }

    function nearest(ev) {
      const r = view.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
      let best = null, bd = 12;
      for (const p of proj) { const dd = Math.hypot(p.px - x, p.py - y); if (dd < bd) { bd = dd; best = p; } }
      return best;
    }
    function place(t) {
      const p = proj.find(q => q.t === t); if (!p) { card.hidden = true; return; }
      const r = view.getBoundingClientRect(), w = card.offsetWidth, h = card.offsetHeight;
      let x = p.px + 14, y = p.py - h / 2;
      if (x + w > r.width - 8) x = p.px - w - 14;
      card.style.left = Math.max(8, x) + "px"; card.style.top = Math.max(8, Math.min(r.height - h - 8, y)) + "px";
    }
    function fill(t) {
      const keys = ORDER.filter(k => t.oxides[k]);
      let h = `<button type="button" aria-label="Close">&times;</button><h3>${esc(t.name)}<span class="tag">${esc(t.label)}</span></h3>` +
        `<div class="meta">${esc(t.instrument)} &middot; sol ${t.sol}${t.autonomous ? " &middot; autonomous (AEGIS) target" : ""}${t.n_points ? " &middot; " + t.n_points + " laser points" : ""}</div>`;
      for (const k of keys) {
        const o = t.oxides[k], pm = o.rmsep != null ? o.rmsep : o.stderr, w = Math.max(0.5, Math.min(100, o.wt / BAR_MAX * 100));
        h += `<div class="ox"><span>${k}</span><span class="bar"><i style="width:${w}%;background:${t.instrument === "APXS" ? COL.ap : COL.cc}"></i></span>` +
          `<span class="v">${o.wt.toFixed(o.wt < 1 ? 2 : 1)}${pm != null ? " <small>&plusmn;" + pm.toFixed(pm < 1 ? 2 : 1) + "</small>" : ""}</span></div>`;
      }
      h += `<div class="note">wt% oxide; bars to ${BAR_MAX} wt%. ${t.instrument === "APXS" ? "&plusmn; = statistical precision." : "&plusmn; = model error (RMSEP)."}` +
        (t.instrument === "ChemCam LIBS" ? " FeOT = all iron as FeO." : "") + `</div>` +
        `<div class="note"><b>Position:</b> ${esc(t.position_note)}</div><div class="note">Source: NASA PDS Geosciences Node.</div>`;
      card.innerHTML = h; card.querySelector("button").onclick = () => { S.pinned = null; card.hidden = true; };
    }
    function show(t) { fill(t); card.hidden = false; place(t); }

    view.addEventListener("pointermove", ev => {
      if (!S.on || S.pinned || (window.__walk && window.__walk.on)) return;
      const p = nearest(ev), t = p && p.t;
      if (t !== S.hover) { S.hover = t; if (t) show(t); else card.hidden = true; }
      view.style.cursor = t ? "pointer" : "";
    });
    let down = null;
    view.addEventListener("pointerdown", ev => { down = [ev.clientX, ev.clientY]; }, true);
    view.addEventListener("pointerup", ev => {
      if (!S.on || !down || Math.hypot(ev.clientX - down[0], ev.clientY - down[1]) > 5 || card.contains(ev.target)) return;
      const p = nearest(ev);
      if (p) { S.pinned = p.t; S.hover = p.t; show(p.t); ev.stopPropagation(); }   // keep the page from also planning a route to this spot
      else if (S.pinned) { S.pinned = null; S.hover = null; card.hidden = true; }
    }, true);
    document.addEventListener("keydown", ev => { if (ev.key === "Escape" && !card.hidden) { S.pinned = S.hover = null; card.hidden = true; } });

    S.show = show; S.proj = () => proj; S.legend = () => legend;
    const n = { cc: S.targets.filter(t => t.instrument !== "APXS").length, ap: S.targets.filter(t => t.instrument === "APXS").length };
    legend.innerHTML = `<span style="color:${COL.cc}">&#9679;</span> ChemCam (${n.cc}) &nbsp; <span style="color:${COL.ap}">&#9670;</span> APXS (${n.ap}) &nbsp; measured, rover position`;
    S.ready = true; requestAnimationFrame(frame);
  }

  async function boot() {
    let d;
    try { d = await (await fetch(base + "chem.json")).json(); } catch (e) { console.warn("chem.js: chem.json not readable: " + e.message); return; }
    S.targets = d.targets || []; S.data = d;
    for (let n = 0; n < 600; n++) {   // wait for the page (view, layer list, camera hook)
      const view = $("view"), tg = document.querySelector(".toggles");
      if (view && tg && window.THREE && window.MW && MW.camera && MW.data) return start(view, tg);
      await new Promise(r => setTimeout(r, 100));
    }
    console.warn("chem.js: page hooks (MW.camera, MW.data, #view, .toggles) not found; layer not added");
  }
  boot();
})();
