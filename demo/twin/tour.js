/* 60-second guided tour for twin.html. Starts on first load (remembered in localStorage), "Tour" button replays it,
 * Skip button or Esc ends it. Uses window.MW from why_route.js for the camera/controls and route numbers; steps whose
 * target is not on the page (validation scoreboard, mission control link) are skipped. Add ?notour to the URL to disable
 * the automatic start. Test hook: window.__tourSpeed = 20 divides every wait.
 */
(function () {
  "use strict";
  const $ = id => document.getElementById(id), KEY = "marswalk_tour_done_v1";
  const view = $("view"); if (!view) return;
  const speed = () => Math.max(1, +window.__tourSpeed || 1);
  const sleep = ms => new Promise(r => setTimeout(r, ms / speed()));
  const T = { active: false, step: 0, steps: 0, log: [] }; window.MWTour = T;
  const MW = () => window.MW || {};

  const css = document.createElement("style");
  css.textContent = `
.tour-card{position:fixed;left:50%;bottom:12px;transform:translateX(-50%);width:min(560px,calc(100% - 24px));z-index:60;background:rgba(22,17,13,.96);border:1px solid var(--dust,#e0a463);border-radius:4px;padding:10px 12px;font-size:13px;line-height:1.45;color:var(--fg,#f1e7da);box-shadow:0 4px 20px rgba(0,0,0,.5)}
.tour-card[hidden]{display:none}
.tour-top{display:flex;justify-content:space-between;align-items:center;gap:8px;font:11px var(--mono,monospace);letter-spacing:.06em;text-transform:uppercase;color:var(--dust,#e0a463);margin-bottom:4px}
.tour-card p{margin:0}
.tour-prog{height:3px;background:rgba(255,255,255,.15);margin-top:8px;border-radius:2px;overflow:hidden}.tour-prog i{display:block;height:100%;width:0;background:var(--route,#6fd8ea)}
.tour-hl{outline:2px solid var(--route,#6fd8ea)!important;outline-offset:3px}
`;
  document.head.appendChild(css);
  const card = document.createElement("div"); card.className = "tour-card"; card.id = "tourCard"; card.hidden = true; card.setAttribute("role", "status"); card.setAttribute("aria-live", "polite");
  card.innerHTML = `<div class="tour-top"><span id="tourNo"></span><button type="button" id="tourSkip">Skip tour (Esc)</button></div><p id="tourTxt"></p><div class="tour-prog"><i id="tourBar"></i></div>`;
  document.body.appendChild(card);
  const replay = document.createElement("button"); replay.type = "button"; replay.id = "tourBtn"; replay.textContent = "Tour"; replay.title = "Replay the 60-second tour";
  const mwBar = MW().bar; if (mwBar) mwBar.appendChild(replay); else { replay.style.cssText = "position:absolute;top:12px;right:12px;z-index:6"; view.appendChild(replay); }

  const remember = () => { try { localStorage.setItem(KEY, "1"); } catch (e) { /* storage blocked: fine */ } };
  const seen = () => { try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; } };

  // ---- camera: smooth move of the page's OrbitControls
  const ease = t => t * t * (3 - 2 * t);
  function pose(center, dist, azDeg, elDeg) {
    const az = azDeg * Math.PI / 180, el = elDeg * Math.PI / 180, c = MW().controls;
    if (c) dist = Math.max(c.minDistance, Math.min(c.maxDistance, dist));
    return { t: center, p: [center[0] + dist * Math.cos(el) * Math.sin(az), center[1] + dist * Math.sin(el), center[2] - dist * Math.cos(el) * Math.cos(az)] };
  }
  function fly(to, ms) {
    const c = MW().controls, cam = MW().camera; if (!c || !cam || !to) return Promise.resolve();
    const t0 = c.target.clone(), p0 = cam.position.clone(), t1 = new THREE.Vector3(...to.t), p1 = new THREE.Vector3(...to.p), start = performance.now(), dur = Math.max(60, ms / speed());
    return new Promise(res => { (function f(now) { if (!T.active) return res();
      const k = Math.min(1, (now - start) / dur), e = ease(k); c.target.lerpVectors(t0, t1, e); cam.position.lerpVectors(p0, p1, e); c.update(); if (k < 1) requestAnimationFrame(f); else res(); })(start); });
  }
  const azOf = () => { const c = MW().controls, cam = MW().camera; return c && cam ? Math.atan2(cam.position.x - c.target.x, -(cam.position.z - c.target.z)) * 180 / Math.PI : 35; };
  const homePose = () => { const m = MW(); if (!m.home) return null; const t = m.home.t, p = m.home.p; return { t: [t.x, t.y, t.z], p: [p.x, p.y, p.z] }; };

  function routeFrame() {
    const m = MW(), A = m.A || (m.analyse && m.analyse()); if (!A || !m.worldOf) return null;
    let x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9, y = 0;
    for (const c of A.cells) { const w = m.worldOf(c); x0 = Math.min(x0, w[0]); x1 = Math.max(x1, w[0]); z0 = Math.min(z0, w[2]); z1 = Math.max(z1, w[2]); y += w[1]; }
    return { A, centre: [(x0 + x1) / 2, y / A.cells.length, (z0 + z1) / 2], size: Math.hypot(x1 - x0, z1 - z0) };
  }

  const setText = (n, N, txt) => { $("tourNo").textContent = `Step ${n} of ${N}`; $("tourTxt").textContent = txt; };
  let timer = 0;
  function progress(ms) { const b = $("tourBar"); b.style.transition = "none"; b.style.width = "0"; void b.offsetWidth; b.style.transition = `width ${ms / speed()}ms linear`; b.style.width = "100%"; }
  let hlEl = null; const unhl = () => { if (hlEl) hlEl.classList.remove("tour-hl"); hlEl = null; };
  const hl = el => { unhl(); if (el) { el.classList.add("tour-hl"); hlEl = el; try { el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) { /* old browser */ } } };
  let startedWalk = false;

  const present = sel => { const e = document.querySelector(sel); return e && !e.hidden ? e : null; };
  const SB = "#scoreboard, [data-scoreboard], .scoreboard", MC = 'a[href*="mission.html"], a[href*="mission"]';

  // ---- steps. Each has when() (skip if false), text(), ms (dwell), act() (camera / UI)
  const steps = [
    { id: "terrain", ms: 8000,
      text: () => { const m = MW(), d = m.data; return `Terrain: Mount Sharp in Gale Crater, from a HiRISE stereo terrain model${d && d.dtm ? " (" + d.dtm + ")" : ""} on a ${d ? d.CELL.toFixed(0) : "4"} m grid, with the HiRISE orbiter image draped over it. Orange line: the route Curiosity drove in sols 4500 to 4799. Drag to orbit, scroll to zoom.`; },
      act: async () => { const h = homePose(); if (h) { const c = h.t; await fly(pose(c, Math.hypot(h.p[0] - c[0], h.p[1] - c[1], h.p[2] - c[2]) * 0.85, azOf() + 40, 32), 5500); } } },
    { id: "route", ms: 9000,
      text: () => { const f = routeFrame(); return f ? `Planned route: an A* search on the 4 m grid between the start and end points, avoiding ground steeper than ${f.A.maxS} degrees. ${(f.A.dist / 1000).toFixed(2)} km long with ${Math.round(f.A.climb)} m of climb (measured from the terrain model).` : "Planned route: not available in this view (no route could be planned)."; },
      act: async () => { if (!MW().analyse || !MW().analyse()) { const b = $("btnDemo"); if (b) b.click(); await sleep(900); }
        const f = routeFrame(); if (f) await fly(pose(f.centre, Math.max(450, f.size * 1.5), azOf(), 45), 5000); } },
    { id: "why", ms: 10000,
      text: () => { const A = MW().A; return A && A.dom ? `Why this route: the panel (key W) splits the planner cost into slope, roughness, loose ground and climb, checks flight rules CS-01, CS-05, CS-06 and CS-07, and shows the straight line the planner rejected. The orange segment adds the most cost, mostly ${A.dom.dom}.` : "Why this route: the panel (key W) shows the cost terms and rules for a planned route. No route is available to show here."; },
      act: async () => { if (MW().togglePanel) { MW().togglePanel(true); await MW().ready; await sleep(700); }
        const A = MW().A, m = MW(); if (A && A.dom && m.worldOf) { const a = m.worldOf(A.steps[A.dom.i0].b), b = m.worldOf(A.steps[Math.min(A.steps.length - 1, A.dom.i1)].b);
          await fly(pose([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2], 420, azOf(), 40), 4500); } } },
    { id: "hazard", ms: 8000,
      text: () => { const j = MW().replan; return j ? `Hazard and replan: rule ${j.rule || "none"} on a simulated dust event. ${j.explanation || ""}`.replace(/^(.{400}).+$/s, "$1...") : "Hazard and replan: the replan output (replan.json) could not be read."; },
      act: async () => { if (MW().loadReplan) await MW().loadReplan(); const p = MW().panel; if (p) { const e = $("mwRepBody"); if (e) e.scrollIntoView({ block: "nearest", behavior: "smooth" }); } } },
    { id: "walk", ms: 9000,
      text: () => "Astronaut and rover: the suited astronaut walks the planned route at the speed of the astronaut model v2 (modelled, not validated physiology); Curiosity is placed where it stood on the chosen sol.",
      act: async () => { if (MW().togglePanel) MW().togglePanel(false);
        const b = $("btnWalk"), wk = window.__walk; if (!b || !wk || !(MW().analyse && MW().analyse())) return;
        b.click(); startedWalk = true;
        for (let i = 0; i < 400 && T.active && !wk.on; i++) await new Promise(r => setTimeout(r, 100));
        if (wk.on) { const s = $("wView"); if (s) { s.value = "follow"; s.dispatchEvent(new Event("change")); } } } },
    { id: "scoreboard", when: () => present(SB), ms: 6000,
      text: () => "Validation scoreboard: results built only from the outputs of the real test and check runs (tools/scoreboard.py).",
      act: async () => { await exitWalk(); hl(present(SB)); } },
    { id: "mission", when: () => present(MC), ms: 6000,
      text: () => "Mission control view: the scripted mission with a simulated dust event, the replan, and the Earth to Mars light-time delay.",
      act: async () => { await exitWalk(); hl(present(MC)); } },
  ];

  async function exitWalk() {   // if the walk is still loading, wait for it to start, then leave it (the tour must not strand the user in walk mode)
    const wk = window.__walk; if (!startedWalk || !wk) return; startedWalk = false;
    for (let i = 0; i < 900 && !wk.on; i++) await new Promise(r => setTimeout(r, 100));
    if (wk.on && !T.active) { const b = $("wExit"); if (b) b.click(); }
    else if (wk.on) { const b = $("wExit"); if (b) b.click(); await sleep(400); }
  }

  async function run() {
    if (T.active) return;
    try { await (MW().ready || Promise.resolve()); } catch (e) { /* data optional */ }
    T.active = true; T.log = []; card.hidden = false;
    const plan = steps.filter(s => !s.when || s.when()); T.steps = plan.length;
    for (let i = 0; i < plan.length && T.active; i++) {
      const s = plan[i]; T.step = i + 1; T.log.push(s.id); unhl();
      if (s.id !== "scoreboard" && s.id !== "mission") { try { view.scrollIntoView({ block: "nearest" }); } catch (e) { /* ignore */ } }
      const t0 = performance.now(); setText(i + 1, plan.length, s.text());
      try { await s.act(); } catch (e) { console.warn("tour step " + s.id + ": " + e.message); }
      if (!T.active) break;
      setText(i + 1, plan.length, s.text()); progress(Math.max(1500, s.ms - (performance.now() - t0) * speed()));
      const left = Math.max(1500, s.ms - (performance.now() - t0) * speed()); await sleep(left);
    }
    finish();
  }
  function finish() {
    const was = T.active; T.active = false; card.hidden = true; unhl(); remember();
    if (was) { exitWalk(); }
    if (MW().togglePanel && MW().panel && !MW().panel.hidden) MW().togglePanel(false);
  }
  $("tourSkip").onclick = () => finish();
  replay.addEventListener("click", () => { if (T.active) return; run(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && T.active) { e.preventDefault(); finish(); } });
  T.start = run; T.skip = finish;

  // ---- automatic start on first load, once the terrain has loaded
  if (!/[?&]notour\b/.test(location.search) && !seen()) {
    (function wait(n) { const l = $("loading"); if (l && l.hidden && MW().controls) setTimeout(run, 800); else if (n < 1200) setTimeout(() => wait(n + 1), 250); })(0);
  }
})();
