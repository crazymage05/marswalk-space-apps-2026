/* Shareable mission links for twin.html. The "Share" button writes the mission state into the URL hash and copies the link;
 * opening a link with a hash restores it through the page's own controls. Hash format (all keys optional):
 *   #s=4500&a=x,y&b=x,y&m=25&e=1.5&h=1&w=1
 *   s sol, a/b route start/end cell (grid x,y), r route button (demo|sci|track: multi-stop routes are re-planned by the
 *   same button, not from a/b), m steepest slope allowed (deg), e vertical exaggeration,
 *   h slope-hazard layer on, w "why this route" panel open.
 *   r=multi: a multi-destination route (Find a target card): a = its start cell, d = destination cells "x,y~x,y" (up to 6, in the
 *   order chosen; the page re-orders them by A* cost), rt=1 return to start. wt = planner cost weights "slope,rough,loose,climb,descent",
 *   written only when they differ from the defaults (2,12,1.5,3,0.5). Older links without these keys work as before.
 *   Crew and support (Plan a walk card), each written only when on: kg = carried load per astronaut (1-80), pair=1 buddy pair,
 *   rv = rover parked as safe haven, "x,y" cell (the walk back is measured to it instead of the start).
 * Unknown or invalid values are ignored. A link with state does not auto-run the tour (tour.js reads localStorage once at
 * load, so the "seen" flag is set for that moment only and put back afterwards).
 */
(function () {
  "use strict";
  const $ = id => document.getElementById(id), TOUR_KEY = "marswalk_tour_done_v1";
  const parse = () => {
    const out = {}, h = location.hash.replace(/^#/, "");
    h.split("&").forEach(kv => { const i = kv.indexOf("="); if (i > 0) out[kv.slice(0, i)] = kv.slice(i + 1); });
    return out;
  };
  const num = (v, lo, hi) => { const n = v != null && v !== "" ? Number(v) : NaN; return Number.isFinite(n) && n >= lo && n <= hi ? n : null; };
  const pair = v => { const m = /^(\d{1,5}),(\d{1,5})$/.exec(v || ""); return m ? [+m[1], +m[2]] : null; };
  const H0 = parse(), hasState = ["s", "a", "b", "m", "e", "h", "w", "d", "wt", "rt", "kg", "pair", "rv"].some(k => k in H0);

  // keep the tour from auto-starting for a shared link: tour.js is loaded after this file and checks the flag once
  if (hasState) {
    let prev = null; try { prev = localStorage.getItem(TOUR_KEY); localStorage.setItem(TOUR_KEY, "1"); } catch (e) { prev = undefined; }
    setTimeout(() => { if (prev === undefined) return; try { prev === null ? localStorage.removeItem(TOUR_KEY) : localStorage.setItem(TOUR_KEY, prev); } catch (e) {} }, 0);
  }

  const fire = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }));
  const setRange = (id, v) => { const el = $(id); if (!el || v == null) return false;
    const lo = +el.min, hi = +el.max; if (!(v >= lo && v <= hi)) return false; el.value = v; fire(el, "input"); return true; };
  const setCheck = (id, on) => { const el = $(id); if (el && el.checked !== on) { el.checked = on; fire(el, "change"); } };
  const grid = () => (window.MW && MW.data) || null;
  // A (2026-11-13): multi-stop routes (science walk, Curiosity's track) are not start-to-end A* routes, so a link with
  // only a/b restored a different, shorter route. Record which route button made the current route (r=demo|sci|track,
  // only while the route is still exactly that button's) and press the same button on restore.
  const MODES = { demo: "btnDemo", sci: "btnSci", track: "btnTrack" }; let snap = null;
  const cellsKey = () => { const c = window.__routeCells && window.__routeCells(); return c && c.length ? c.join(",") : null; };
  // a slope-limit or safety-margin change re-plans the same route button's route; keep that route's r= tag (only if it was still that route)
  document.addEventListener("change", e => { if (e.target && (e.target.id === "maxSlope" || e.target.id === "margin") && snap && snap.key && snap.key === cellsKey()) setTimeout(() => { snap.key = cellsKey(); }, 0); }, true);
  document.addEventListener("click", e => { for (const [m, id] of Object.entries(MODES)) if (e.target && e.target.id === id) setTimeout(() => { snap = { mode: m, key: cellsKey() }; }, 0); }, true);

  function collect() {
    const p = [], add = (k, v) => p.push(k + "=" + v);
    add("s", $("sol").value);
    const cells = window.__routeCells && window.__routeCells(), d = grid();
    const ms = window.__multiState && window.__multiState(), xyOf = c => d ? (c % d.W) + "," + Math.floor(c / d.W) : "";
    if (ms && d) { add("r", "multi"); add("a", xyOf(ms.src)); add("d", ms.dests.map(xyOf).join("~")); if (ms.ret) add("rt", 1); }
    else if (snap && snap.key && snap.key === cellsKey()) add("r", snap.mode);   // restored by pressing the same route button
    else if (cells && cells.length > 1 && d) {
      const xy = c => (c % d.W) + "," + Math.floor(c / d.W);
      add("a", xy(cells[0])); add("b", xy(cells[cells.length - 1]));
    }
    add("m", $("maxSlope").value); if ($("margin") && $("margin").checked) add("mg", 1); add("e", $("ex").value);
    const wt = window.__weights && window.__weights(); if (wt) add("wt", wt.join(","));
    const cr = window.__crew && window.__crew.state();
    if (cr) { if (cr.carried > 0) add("kg", cr.carried); if (cr.pair) add("pair", 1); if (cr.haven && cr.rover != null && d) add("rv", xyOf(cr.rover)); }
    if ($("lyHaz").checked) add("h", 1);
    if (window.MW && MW.panel && !MW.panel.hidden) add("w", 1);
    return p.join("&");
  }

  function apply(S) {
    const d = grid();
    if (S.wt && window.__setWeights) { const q = S.wt.split(",").map(Number); if (q.length === 5 && q.every(v => Number.isFinite(v) && v >= 0 && v <= 100)) window.__setWeights({ slope: q[0], rough: q[1], loose: q[2], climb: q[3], descent: q[4] }); }
    if ($("margin") && ($("margin").checked !== (S.mg === "1"))) $("margin").checked = S.mg === "1";   // before the slider, whose change handler plans with the effective limit
    setRange("sol", num(S.s, 0, 1e5)); setRange("ex", num(S.e, 0, 100)); setRange("maxSlope", num(S.m, 0, 90));
    const kg = num(S.kg, 1, 80), rv = pair(S.rv);   // crew and support first, so the verdict of the restored route already includes them
    if (window.__crew && (kg != null || S.pair === "1" || rv)) window.__crew.restore({ carried: kg != null ? kg : undefined, pair: S.pair === "1" ? true : undefined,
      haven: rv ? true : undefined, rover: rv && d && rv[0] < d.W && rv[1] < d.H ? rv[1] * d.W + rv[0] : undefined });
    if (S.h === "1") setCheck("lyHaz", true);
    const a = pair(S.a), b = pair(S.b);
    const dl = (S.d || "").split("~").map(pair).filter(p => p && d && p[0] < d.W && p[1] < d.H).slice(0, 6);
    if (S.r === "multi" && a && dl.length && d && window.__multiRestore && a[0] < d.W && a[1] < d.H) window.__multiRestore(a[1] * d.W + a[0], dl.map(p => p[1] * d.W + p[0]), S.rt === "1");
    else if (S.r && MODES[S.r] && $(MODES[S.r])) $(MODES[S.r]).click();
    else if (a && b && d && a[0] < d.W && b[0] < d.W && a[1] < d.H && b[1] < d.H && window.__planCells) {
      const A = a[1] * d.W + a[0], B = b[1] * d.W + b[0];
      window.__planCells([A, B]);            // sets the two points; the slope control's own change handler then runs the real A* plan
      fire($("maxSlope"), "change");
    }
    if (S.w === "1" && window.MW && typeof MW.togglePanel === "function") MW.togglePanel(true);
  }

  function ui() {
    const btn = document.createElement("button"); btn.type = "button"; btn.id = "shareBtn"; btn.textContent = "Share";
    btn.title = "Copy a link that restores this route, sol and settings";
    btn.style.cssText = "position:fixed;right:12px;top:12px;z-index:50;padding:6px 12px;font:12px var(--mono,monospace);cursor:pointer";
    const box = document.createElement("input"); box.type = "text"; box.readOnly = true; box.id = "shareBox"; box.hidden = true; box.setAttribute("aria-label", "Shareable link");
    box.style.cssText = "position:fixed;right:12px;top:48px;z-index:50;width:min(420px,calc(100vw - 24px));padding:5px;font:12px var(--mono,monospace);box-sizing:border-box";
    const note = document.createElement("span"); note.id = "shareNote"; note.setAttribute("role", "status"); note.hidden = true;
    note.style.cssText = "position:fixed;right:80px;top:18px;z-index:50;font:12px var(--mono,monospace);color:var(--fg,#eee)";
    btn.onclick = async () => {
      const hash = "#" + collect(); history.replaceState(null, "", hash);
      const url = location.href; box.value = url; let ok = false;
      try { await navigator.clipboard.writeText(url); ok = true; } catch (e) {}
      box.hidden = ok; note.hidden = false; note.textContent = ok ? "Link copied" : "Copy the link below";
      if (!ok) { box.hidden = false; box.focus(); box.select(); }
      clearTimeout(btn._t); btn._t = setTimeout(() => { note.hidden = true; }, 3000);
    };
    document.body.append(btn, box, note);
  }

  function start() {
    ui();
    if (!hasState) return;
    (function wait(n) {
      const l = $("loading"), ready = l && l.hidden && grid() && window.__planCells;
      if (ready) { try { apply(H0); } catch (e) { console.warn("share: could not apply link", e); } }
      else if (n < 1200) setTimeout(() => wait(n + 1), 250);
    })(0);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
