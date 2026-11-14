/* MARSWALK suit view (NASA side). Plain JS, no libraries, no fetches.
   Reads the mission replay through the page hook window.__mission (log, step) and re-renders when the step changes.
   Everything here is derived from the log or labelled ASSUMED / SIMULATED. See docs/suit_view.md. */
(function () {
"use strict";
// ---- constants (each one is stated on screen too)
var KJ_PER_L_O2 = 20.1;      // kJ per L O2 (J_PER_ML_O2 = 20.1 in phase4/astronaut.py, RER about 0.85)
var RQ = 0.85;               // ASSUMED respiratory quotient (CO2 produced / O2 used)
var EVA_H = 8;               // ASSUMED: tank sized for an 8 h EVA at the nominal level-walking rate. Not a NASA value.
var P0_KPA = 29.6;           // suit pressure of the NASA suited-walking tests the model uses (docs/astronaut_model.md, TP-2010)
var LEAK_RATE = 0.02;        // kPa/s, ASSUMED, SIMULATED slow leak: the pressure fall rate if nothing made up the loss
var FLOOR_KPA = 24;          // ASSUMED pressure floor at which the regulator holds the suit (SIMULATED)
var VOL_M3 = 0.03;           // ASSUMED suit free gas volume (~30 L). No NASA value in the repo; stated plainly, not justified further.
var T_K = 293;               // suit gas temperature, assumed
var R_J = 8.314;             // J/mol/K
var SU1_KPA = 25;            // SU-1 demo rule: pressure threshold (MARSWALK demo rule; phase4/safety_validator.py has no suit-pressure rule)
// Make-up flow: leak loses n_dot = (dP/dt) * V / (R T) mol/s; as L/min of O2 at 101.325 kPa and 293 K (molar volume R T / P)
var MAKEUP_LMIN = LEAK_RATE * 1000 * VOL_M3 / (R_J * T_K) * (R_J * T_K / 101325) * 1000 * 60;
var WALKBACK_S = 0;          // walk-back time for the SU-1 O2 rule: nominal round trip from the log plan (set in init)
var TC = null;               // cached SU-1 trip time
var BODY_KG = 90;            // body mass in the model (150 kg total - 60 kg suit), phase4/astronaut.py Profile.body_mass_kg
var K_MARS = 0.032 / 0.060;  // Wickman & Luna 1995 (Aerospace Med. Assoc.), Mars 1.2 m/s: slope 0.032 / no-load intercept 0.060 kcal/kg/min = 0.533 per unit L/body mass
var LOAD_KG = 0;             // carried equipment / samples (kg), set by the Carried box or the plan (profile.carried_kg); 0 = unchanged
var SMOOTH = 5;              // steps used for d(energy)/dt
var LEAK_T0 = null;          // mission time (s) when the leak button was pressed
var H, S, el = {}, lastKey = null, tagCls = { measured: 'ok', modelled: 'cy', assumed: 'wa', SIMULATED: 'sm' };
var NOM_W = 0, CAP_L = 0;

function css() {
  var s = document.createElement('style');
  s.textContent =
  '#suit{margin:0 16px 12px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}' +
  '#suit h2{font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut)}' +
  '#suit .clk{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}' +
  '#suit .side{border:1px solid var(--line);border-radius:6px;padding:8px;background:var(--panel2);min-width:0}' +
  '#suit .side.earth{opacity:.62;filter:grayscale(.7)}' +
  '#suit .sh{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline;margin-bottom:6px}' +
  '#suit .sh b{font-size:15px;letter-spacing:.08em}#suit .sh .age{color:var(--ground);font-size:12px}#suit .sh .t{color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums}' +
  '#suit .grid{display:grid;gap:6px;grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}' +
  '#suit .st{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--line);border-radius:4px;padding:4px 8px;min-width:0}' +
  '#suit .st .l{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.05em}' +
  '#suit .st .v{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}#suit .st .v small{font-size:11px;color:var(--mut);font-weight:400}' +
  '#suit .st.s-red{border-left-color:var(--bad)}#suit .st.s-yellow{border-left-color:var(--warn)}' +
  '#suit .tg{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;border-radius:3px;padding:0 5px;margin-top:2px}' +
  '#suit .tg.ok{background:var(--ok);color:#04100a}#suit .tg.cy{background:var(--cyan);color:#001}#suit .tg.wa{background:var(--warn);color:#110}#suit .tg.sm{background:var(--sim);color:#110}' +
  '#suit .alert{margin-top:6px;padding:6px 8px;border-radius:4px;border:1px solid var(--bad);background:rgba(248,81,73,.15);font-size:13px}' +
  '#suit .alert.off{display:none}#suit .nodata{color:var(--mut);padding:8px 0}' +
  '#suit .notes{color:var(--mut);font-size:12px;margin:6px 0 0}#suit .notes b{color:var(--tx)}' +
  '#sbar{position:relative;height:30px;margin:14px 4px 4px;border-top:2px solid var(--line)}' +
  '#sbar .end{position:absolute;top:6px;font-size:11px;color:var(--mut);letter-spacing:.06em}' +
  '#sbar .pk{position:absolute;top:-8px;width:14px;height:14px;margin-left:-7px;border-radius:50%;border:2px solid #001}' +
  '#suit .ctl{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}' +
  '#suit .pl{display:flex;flex-wrap:wrap;gap:2px 12px;font-size:11px;color:var(--mut)}' +
  '@media(max-width:700px){#suit .clk{grid-template-columns:minmax(0,1fr)}}';
  document.head.appendChild(s);
}

function build() {
  var sec = document.createElement('section'); sec.id = 'suit'; sec.setAttribute('aria-label', 'Suit health, NASA side');
  sec.innerHTML =
    '<h2>Suit health (NASA side view) <span class="tg sm">SIMULATED</span></h2>' +
    '<div class="clk">' +
    '<div class="side" id="sMars"><div class="sh"><b>MARS NOW</b><span class="t" id="sMt"></span></div><div class="grid" id="gMars"></div><div class="alert off" id="aMars" role="alert"></div></div>' +
    '<div class="side earth" id="sEarth"><div class="sh"><b>EARTH SEES</b><span class="age" id="sAge"></span><span class="t" id="sEt"></span></div><div class="grid" id="gEarth"></div><div class="alert off" id="aEarth" role="status"></div></div>' +
    '</div>' +
    '<div id="sbar" aria-label="Mars to Earth link, messages in flight"></div>' +
    '<div class="pl" id="spl"></div>' +
    '<p class="notes" id="sNo"></p>' +
    '<div class="ctl"><label for="sLoad">Carried (kg)</label><input type="number" id="sLoad" min="0" max="80" step="1" value="0" style="width:64px"><span class="hmeta" id="sLoadInfo"></span><button type="button" id="sLeak">Simulate suit leak</button><button type="button" id="sReset" disabled>Reset leak</button><span class="hmeta" id="sLeakInfo"></span></div>' +
    '<p class="notes" id="sAs"></p>';
  var main = document.querySelector('main');
  main.parentNode.insertBefore(sec, main.nextSibling);
  ['gMars', 'gEarth', 'aMars', 'aEarth', 'sMt', 'sEt', 'sAge', 'sbar', 'spl', 'sNo', 'sAs', 'sLeak', 'sReset', 'sLeakInfo', 'sLoad', 'sLoadInfo'].forEach(function (k) { el[k] = document.getElementById(k); });
  el.sLoad.oninput = function () { var v = parseFloat(el.sLoad.value); LOAD_KG = isFinite(v) ? Math.min(80, Math.max(0, v)) : 0; TC = null; lastKey = null; render(); };
  el.sLeak.onclick = function () { LEAK_T0 = S[H.step].t_s; TC = null; el.sLeak.disabled = true; el.sReset.disabled = false; lastKey = null; render(); };
  el.sReset.onclick = function () { LEAK_T0 = null; TC = null; el.sLeak.disabled = false; el.sReset.disabled = true; lastKey = null; render(); };
}

// ---- model
function rateW(i) {   // d(energy_kj)/dt in W over SMOOTH steps (model v2 energy is gross metabolic)
  var a = Math.max(0, i - SMOOTH), b = i;
  if (b === a) b = Math.min(S.length - 1, SMOOTH);
  return loadF() * (S[b].energy_kj - S[a].energy_kj) * 1000 / (S[b].t_s - S[a].t_s);
}
function loadF() { return 1 + K_MARS * LOAD_KG / BODY_KG; }   // level-walking load factor 1 + k L/body_mass; 1 at 0 kg (climbing adds more: not applied here)
function leaking(t) { return LEAK_T0 !== null && t >= LEAK_T0; }
function pressure(t) { return leaking(t) ? Math.max(FLOOR_KPA, P0_KPA - LEAK_RATE * (t - LEAK_T0)) : P0_KPA; }
function leakL(t) { return leaking(t) ? MAKEUP_LMIN / 60 * (t - LEAK_T0) : 0; }   // extra O2 used since the leak began
function tCross() {   // first logged time at or after the leak start when SU-1 trips (whichever rule comes first)
  if (LEAK_T0 === null) return null;
  if (TC === null) { TC = Infinity; for (var i = 0; i < S.length; i++) if (S[i].t_s >= LEAK_T0 && suitState(i).alert) { TC = S[i].t_s; break; } }
  return TC;
}
function suitState(i) {
  var s = S[i], w = rateW(i), met = w / 1000 / KJ_PER_L_O2 * 60, mk = leaking(s.t_s) ? MAKEUP_LMIN : 0, lmin = met + mk;
  var used = loadF() * s.energy_kj / KJ_PER_L_O2 + leakL(s.t_s), p = pressure(s.t_s), left = CAP_L - used, mins = lmin > 0 ? left / lmin : NaN;
  var byP = p < SU1_KPA, byO2 = leaking(s.t_s) && mins * 60 < WALKBACK_S;
  return { i: i, t_s: s.t_s, met_W: w, o2_Lmin: lmin, makeup_Lmin: mk, o2_used_L: used, o2_left_L: left, o2_left_min: mins,
           co2_Lmin: met * RQ, heat_W: w, p_kPa: p, alert: byP || byO2, why: byP ? 'pressure' : byO2 ? 'O2 time' : '' };
}
function earthIndex(i) {   // latest step at or before (t - one-way light time); -1 if the first signal has not arrived
  var t = S[i].t_s - S[i].light_time_min * 60;
  if (t < 0) return -1;
  var j = i; while (j > 0 && S[j].t_s > t) j--;
  return S[j].t_s <= t ? j : -1;
}

var DEF = [
  ['met_W', 'Metabolic rate', function (v) { return v.toFixed(0); }, 'W', 'modelled'],
  ['o2_Lmin', 'O2 consumption', function (v) { return v.toFixed(2); }, 'L/min', 'modelled'],
  ['o2_used_L', 'O2 used', function (v) { return v.toFixed(1); }, 'L', 'modelled'],
  ['o2_left_L', 'O2 remaining', function (v) { return v.toFixed(0); }, 'L', 'assumed'],
  ['makeup_Lmin', 'O2 make-up (leak)', function (v) { return v.toFixed(2); }, 'L/min', 'SIMULATED'],
  ['co2_Lmin', 'CO2 produced', function (v) { return v.toFixed(2); }, 'L/min', 'assumed'],
  ['heat_W', 'Heat load', function (v) { return v.toFixed(0); }, 'W', 'modelled'],
  ['p_kPa', 'Suit pressure', function (v) { return v.toFixed(1); }, 'kPa', 'assumed']
];
function defs() { return LEAK_T0 === null ? DEF.filter(function (d) { return d[0] !== 'makeup_Lmin'; }) : DEF; }
function tileHTML(d, st) {
  var tag = (d[0] === 'p_kPa' || d[0] === 'o2_Lmin') && LEAK_T0 !== null ? 'SIMULATED' : d[4], cls = '';
  if (d[0] === 'p_kPa') cls = st.alert ? ' s-red' : (st.p_kPa < P0_KPA - 0.05 ? ' s-yellow' : '');
  var unit = d[0] === 'o2_left_L' ? 'L (' + (st.o2_left_min / 60).toFixed(1) + ' h at this rate)' : d[3];
  return '<div class="st' + cls + '" data-k="' + d[0] + '"><div class="l">' + d[1] + '</div><div class="v"><span class="n">' + d[2](st[d[0]]) + '</span> <small>' + unit + '</small></div><span class="tg ' + tagCls[tag] + '">' + tag + '</span></div>';
}
function fmtT(s) { s = Math.round(s); return Math.floor(s / 3600) + ':' + String(Math.floor(s % 3600 / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }

function packets(t, lt) {   // messages in flight, from the log's comm events
  var tl = H.log.mission.timeline, f = function (k) { return tl.filter(function (e) { return e.kind === k; })[0]; };
  var sent = f('comm_sent'), rx = f('comm_received_earth'), rep = f('ground_reply'), out = [];
  if (sent && rx) out.push({ n: 'request (Mars to Earth)', a: sent.t_s, b: rx.t_s, up: true, c: '#f0a35e' });
  if (rx && rep) out.push({ n: 'ground reply (Earth to Mars)', a: rx.t_s, b: rep.t_s, up: false, c: '#ffb870' });
  if (LEAK_T0 !== null) { var tc = tCross(); out.push({ n: 'SU-1 suit alert (Mars to Earth)', a: tc, b: tc + lt * 60, up: true, c: '#f85149' }); }
  return out.filter(function (p) { return t >= p.a && t < p.b; });
}

function render() {
  var i = H.step, s = S[i], lt = s.light_time_min, key = i + '|' + LEAK_T0 + '|' + LOAD_KG;
  if (key === lastKey) return;
  lastKey = key;
  var m = suitState(i), j = earthIndex(i), e = j < 0 ? null : suitState(j);
  el.gMars.innerHTML = defs().map(function (d) { return tileHTML(d, m); }).join('');
  el.sMt.textContent = 'suit time ' + fmtT(m.t_s);
  el.gEarth.innerHTML = e ? defs().map(function (d) { return tileHTML(d, e); }).join('') : '<div class="nodata">No data yet: the first signal from the suit has not reached Earth (one-way light time ' + lt.toFixed(1) + ' min).</div>';
  el.sEt.textContent = e ? 'suit time ' + fmtT(e.t_s) : '';
  el.sAge.textContent = (e ? ((m.t_s - e.t_s) / 60).toFixed(1) : lt.toFixed(1)) + ' min old';
  var al = function (node, st, side) {
    if (st && st.alert) { node.className = 'alert'; node.textContent = 'SIMULATED SUIT ALERT (SU-1, ' + st.why + '): pressure ' + st.p_kPa.toFixed(1) + ' kPa, O2 ' + (st.o2_left_min / 60).toFixed(1) + ' h at this rate. SU-1 demo rule: end EVA and walk back now.' + (side === 'earth' ? ' (This is the Mars alert, seen on Earth ' + lt.toFixed(1) + ' min late.)' : ''); }
    else { node.className = 'alert off'; node.textContent = ''; }
  };
  al(el.aMars, m, 'mars'); al(el.aEarth, e, 'earth');
  var t = m.t_s, ps = packets(t, lt), html = '<span class="end" style="left:0">MARS</span><span class="end" style="right:0">EARTH</span>';
  ps.forEach(function (p) { var f = (t - p.a) / (p.b - p.a); if (!p.up) f = 1 - f; html += '<i class="pk" title="' + p.n + '" style="left:' + (f * 100).toFixed(1) + '%;background:' + p.c + '"></i>'; });
  el.sbar.innerHTML = html;
  el.spl.innerHTML = ps.length ? ps.map(function (p) { return '<span><b style="color:' + p.c + '">&#9679;</b> ' + p.n + ', arrives in ' + fmtT(p.b - t) + '</span>'; }).join('') : '<span>No message in flight.</span>';
  el.sNo.innerHTML = '<b>No live call is possible: one-way light time ' + lt.toFixed(1) + ' min.</b> EARTH SEES is the suit state from ' + lt.toFixed(1) + ' min ago; anything Earth sends reaches the suit after a further ' + lt.toFixed(1) + ' min.';
  el.sLoadInfo.textContent = LOAD_KG > 0 ? 'SIMULATED: metabolic rate x ' + loadF().toFixed(3) + ' (1 + ' + K_MARS.toFixed(3) + ' x ' + LOAD_KG + ' kg / ' + BODY_KG + ' kg); tank size unchanged' : 'no extra load (plan as logged)';
  el.sLeakInfo.textContent = LEAK_T0 === null ? '' : 'SIMULATED leak from suit time ' + fmtT(LEAK_T0) + ': ' + LEAK_RATE + ' kPa/s (assumed), pressure floor ' + FLOOR_KPA + ' kPa (assumed), make-up ' + MAKEUP_LMIN.toFixed(2) + ' L/min; SU-1 trips at ' + fmtT(tCross()) + (m.t_s < LEAK_T0 ? ' (not started yet at this time)' : '');
  window.__suit = { mars: m, earth: e, earthIndex: j, leakT0: LEAK_T0, alertMars: m.alert, alertEarth: !!(e && e.alert), packets: ps.length, lightMin: lt, state: suitState };
}

function init() {
  H = window.__mission; S = H.log.steps;
  var last = S[S.length - 1];
  WALKBACK_S = H.log.mission.plan_decision.timeline.nominal_roundtrip_s;
  NOM_W = last.energy_kj * 1000 / last.t_s;               // mean metabolic power of this logged level-walking mission = "nominal rate"
  CAP_L = EVA_H * 3600 * NOM_W / 1000 / KJ_PER_L_O2;      // ASSUMED capacity
  var pl = (H.log.profile && H.log.profile.carried_kg) || (H.log.mission.astronaut_model && H.log.mission.astronaut_model.carried_kg) || 0;
  LOAD_KG = isFinite(+pl) ? Math.max(0, +pl) : 0;
  css(); build(); el.sLoad.value = LOAD_KG;
  el.sAs.innerHTML =
    '<b>Tags:</b> modelled = computed from the mission log (model v2 gross metabolic energy; O2 = energy / ' + KJ_PER_L_O2 + ' kJ per L, phase4/astronaut.py); assumed = our parameter, not a NASA value; SIMULATED = invented fault. No tile is measured: there is no real suit telemetry. ' +
    '<b>Assumed:</b> O2 capacity ' + CAP_L.toFixed(0) + ' L (tank sized for an ' + EVA_H + ' h EVA at the nominal level-walking rate, ' + NOM_W.toFixed(0) + ' W, the mean rate of this log); RQ ' + RQ + ' for CO2; nominal suit pressure ' + P0_KPA + ' kPa from the suited-walking tests in docs/astronaut_model.md; leak ' + LEAK_RATE + ' kPa/s, pressure floor ' + FLOOR_KPA + ' kPa, suit free volume ' + VOL_M3 + ' m3, gas at ' + T_K + ' K (ideal gas). Heat load is taken equal to metabolic power. Heart rate is left out: no cited relation in the repo. ' +
    '<b>Carried load (SIMULATED):</b> metabolic power and O2 used are multiplied by 1 + ' + K_MARS.toFixed(3) + ' x load / ' + BODY_KG + ' kg body mass, the Mars level-walking increment of Wickman &amp; Luna 1995 (unsuited, underwater, 1.2 m/s, tested to 80 % of body weight); the extra cost of climbing with the load is not added here (model: docs/astronaut_model.md). The tank stays sized for the unloaded log. ' +
    '<b>Leak model (SIMULATED):</b> pressure falls at the leak rate to the floor and holds; the regulator makes up the loss from the O2 supply: make-up = leak rate x V / (R T) = ' + MAKEUP_LMIN.toFixed(2) + ' L/min of O2 (at 101.3 kPa, 293 K), added to O2 consumption. <b>SU-1 demo rule:</b> end EVA and walk back when suit pressure is below ' + SU1_KPA + ' kPa OR O2 time left at the current rate is below the walk-back time (' + (WALKBACK_S / 60).toFixed(0) + ' min, the nominal round trip), whichever comes first (MARSWALK demo rule; phase4/safety_validator.py has no suit-pressure rule). The alert and walk-back call are shown here only; the replayed log is unchanged.';
  function loop() { try { render(); } catch (err) { console.error(err); return; } requestAnimationFrame(loop); }
  loop();
}
var tries = 0, iv = setInterval(function () {
  if (window.__mission && window.__mission.log) { clearInterval(iv); init(); } else if (++tries > 400) clearInterval(iv);
}, 50);
})();
