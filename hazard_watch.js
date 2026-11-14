/* MARSWALK hazard watch (mission control). Plain JS, no libraries.
   1. Radiation: Mars-arrival predictions from feed.json (NASA DONKI WSA-ENLIL, label modelled) checked against the EVA window,
      with the published timing error beside each one. Skill check: data/processed/hazards/cme_skill.json, docs/hazard_watch.md.
   2. Dust: an operator tool. Someone who has seen a storm on an orbiter image (MRO MARCI) enters it; this page does great-circle
      geometry to Gale and, with two sightings, the observed front speed. It is not a forecast. Records are labelled "simulated"
      and are written to IndexedDB "marswalk-feed" / store "records" and to BroadcastChannel "marswalk-feed" as {record}. */
(function () {
"use strict";
// ---- constants, each one stated on screen
var GALE = { lat: -4.8, lon: 137.41 };      // study-area centre used by phase4/world.py (ROI lat -4.83..-4.78, lon 137.37..137.41)
var R_MARS = 3389.5;                         // km, mean radius (IAU)
var PAD_H = 20;                              // typical Mars arrival-time error, hours: upper end of the published SD 17-20 h (von Forstner et al. 2019, arXiv:1904.10859, 45 events)
var ENLIL_MAE_H = 10;                        // mean absolute ENLIL-vs-Forbush transit-time difference, 15 events (von Forstner et al. 2018, arXiv:1712.07301); best-of-several-runs, so optimistic
var V_MIN = 6, V_MAX = 26;                   // m/s, dust-storm front/expansion speeds measured from MARCI/VMC images, MY36 (Sanchez-Lavega et al. 2025, arXiv:2501.05337; errors 1-2 m/s)
var DUST_SEASON = [180, 360];                // Ls of the dusty season (Wolkenberg et al. 2018, arXiv:1802.02653; Kass et al. 2016)
var CS07 = "CS-07 (Radiation dose of the round trip exceeds the per-EVA limit)";   // wording from why_route.js
var DB_NAME = "marswalk-feed", STORE = "records", CH = "marswalk-feed";
var FEED = [], feedErr = "", tau = null, evaDefaultH = 3, doseBudget = 250;
var el = {};
var D2R = Math.PI / 180;

function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
function two(n) { return (n < 10 ? "0" : "") + n; }
function fmtUtc(ms) { if (!isFinite(ms)) return "-"; var d = new Date(ms); return d.getUTCFullYear() + "-" + two(d.getUTCMonth() + 1) + "-" + two(d.getUTCDate()) + " " + two(d.getUTCHours()) + ":" + two(d.getUTCMinutes()) + " UTC"; }
function isoMs(ms) { return new Date(ms).toISOString().replace(/\.\d+Z$/, "Z"); }
function inputVal(ms) { return new Date(ms).toISOString().slice(0, 16); }     // for datetime-local, read as UTC
function parseInp(v) { return v ? Date.parse(v + ":00Z") : NaN; }
function fmtDur(h) { return h >= 48 ? (h / 24).toFixed(1) + " d" : h >= 1 ? h.toFixed(1) + " h" : Math.round(h * 60) + " min"; }

// ---- geometry
function toRad(x) { return x * D2R; }
function gcKm(a, b) {   // haversine
  var f1 = toRad(a.lat), f2 = toRad(b.lat), dl = toRad(b.lon - a.lon), dp = f2 - f1;
  var h = Math.sin(dp / 2) * Math.sin(dp / 2) + Math.cos(f1) * Math.cos(f2) * Math.sin(dl / 2) * Math.sin(dl / 2);
  return 2 * R_MARS * Math.asin(Math.min(1, Math.sqrt(h)));
}
function bearing(a, b) {   // initial bearing a -> b, degrees clockwise from north
  var f1 = toRad(a.lat), f2 = toRad(b.lat), dl = toRad(b.lon - a.lon);
  var y = Math.sin(dl) * Math.cos(f2), x = Math.cos(f1) * Math.sin(f2) - Math.sin(f1) * Math.cos(f2) * Math.cos(dl);
  return (Math.atan2(y, x) / D2R + 360) % 360;
}
function compass(b) { return ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][Math.round(b / 22.5) % 16]; }
// Track of a front: great circle through s1 -> s2. Returns cross-track and along-track (from s1) distance of point g, km.
function trackOf(s1, s2, g) {
  var d13 = gcKm(s1, g) / R_MARS, t13 = toRad(bearing(s1, g)), t12 = toRad(bearing(s1, s2));
  var xt = Math.asin(Math.sin(d13) * Math.sin(t13 - t12));
  var at = Math.acos(Math.max(-1, Math.min(1, Math.cos(d13) / Math.cos(xt)))) * R_MARS;
  if (Math.cos(t13 - t12) < 0) at = -at;
  return { xt: Math.abs(xt) * R_MARS, at: at };
}

// ---- Mars solar longitude (Allison & McEwen 2000, Planet. Space Sci. 48, 215); check: gives 110.65 deg for UTC 2025-07-15 01:01 (repo F1 doc: 110.8 at sol 4600)
function marsLs(ms) {
  var jd = ms / 86400000 + 2440587.5, D = jd + 69.184 / 86400 - 2451545.0;
  var M = toRad(19.3871 + 0.52402073 * D), a = 270.3863 + 0.52403840 * D;
  var P = [[0.0071, 2.2353, 49.409], [0.0057, 2.7543, 168.173], [0.0039, 1.1177, 191.837], [0.0037, 15.7866, 21.736], [0.0021, 2.1354, 15.704], [0.0020, 2.4694, 95.528], [0.0018, 32.8493, 49.095]];
  var pbs = 0; for (var i = 0; i < P.length; i++) pbs += P[i][0] * Math.cos(toRad(0.985626 * D / P[i][1] + P[i][2]));
  var nu = (10.691 + 3e-7 * D) * Math.sin(M) + 0.623 * Math.sin(2 * M) + 0.050 * Math.sin(3 * M) + 0.005 * Math.sin(4 * M) + 0.0005 * Math.sin(5 * M) + pbs;
  return ((a + nu) % 360 + 360) % 360;
}
// Mars sol number from UTC: reference RAD_RDR_2024_100_16_45_4151 label, START_OBS_UTC 2024-100 16:45:20 at 4151 0:31:37
function marsSol(ms) { return Math.floor(4151 + (31 * 60 + 37) / 86400 + (ms - Date.UTC(2024, 3, 9, 16, 45, 20)) / 1000 / 88775.244); }
function tauAt(ls) {   // linear between 10-deg bin centres, circular in Ls (tau_climatology.json 'lookup')
  if (!tau) return null;
  var c = tau.ls_centre, n = c.length, i = 0;
  while (i < n && c[i] <= ls) i++;
  var i0 = (i - 1 + n) % n, i1 = i % n, l0 = c[i0], l1 = c[i1] + (i1 <= i0 ? 360 : 0), x = ls < c[0] ? ls + 360 : ls;
  var w = (x - l0 < 0 ? x + 360 - l0 : x - l0) / (l1 - l0);
  function mix(a) { return a[i0] + (a[i1] - a[i0]) * w; }
  return { tau: mix(tau.tau880), p25: mix(tau.p25_880), p75: mix(tau.p75_880) };
}

// ---- storage: IndexedDB marswalk-feed / records (created if missing) and BroadcastChannel
function openDb() {
  return new Promise(function (res, rej) {
    if (!window.indexedDB) return rej(new Error("IndexedDB not available"));
    var r = indexedDB.open(DB_NAME);
    r.onerror = function () { rej(r.error); };
    r.onsuccess = function () {
      var db = r.result;
      if (db.objectStoreNames.contains(STORE)) { db.onversionchange = function () { db.close(); }; return res(db); }
      var v = db.version + 1; db.close();
      var r2 = indexedDB.open(DB_NAME, v);
      r2.onupgradeneeded = function () { if (!r2.result.objectStoreNames.contains(STORE)) r2.result.createObjectStore(STORE, { keyPath: "id" }); };
      r2.onerror = function () { rej(r2.error); };
      r2.onsuccess = function () { r2.result.onversionchange = function () { r2.result.close(); }; res(r2.result); };
    };
  });
}
function putRecord(rec) {
  return openDb().then(function (db) {
    return new Promise(function (res, rej) {
      var tx = db.transaction(STORE, "readwrite"); tx.objectStore(STORE).put(rec);
      tx.oncomplete = function () { db.close(); res(); }; tx.onerror = function () { db.close(); rej(tx.error); };
    });
  }).then(function () {
    try { var bc = new BroadcastChannel(CH); bc.postMessage({ record: rec }); bc.close(); } catch (e) { /* no BroadcastChannel */ }
  });
}
function sha256Hex(text) {
  if (!(window.crypto && crypto.subtle)) return Promise.resolve("");
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(function (b) {
    return Array.prototype.map.call(new Uint8Array(b), function (x) { return ("0" + x.toString(16)).slice(-2); }).join("");
  }, function () { return ""; });
}

// ---- styles and markup
function css() {
  var s = document.createElement("style");
  s.textContent =
  "#hazard{margin:0 16px 12px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}" +
  "#hazard h2{font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut)}" +
  "#hazard h3{font-size:13px;margin:0 0 6px;letter-spacing:.04em}" +
  "#hazard .hwg{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}" +
  "#hazard .box{border:1px solid var(--line);border-radius:6px;padding:8px;background:var(--panel2);min-width:0}" +
  "#hazard .tg{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;border-radius:3px;padding:0 5px;vertical-align:middle}" +
  "#hazard .tg.ok{background:var(--ok);color:#04100a}#hazard .tg.cy{background:var(--cyan);color:#001}#hazard .tg.wa{background:var(--warn);color:#110}#hazard .tg.sm{background:var(--sim);color:#110}" +
  "#hazard .row{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;margin-bottom:6px}" +
  "#hazard label{color:var(--mut);font-size:12px;display:flex;flex-direction:column;gap:2px}" +
  "#hazard input{font:inherit;font-size:13px;background:var(--panel);color:var(--tx);border:1px solid var(--line);border-radius:4px;padding:3px 6px;width:100%;min-width:0}" +
  "#hazard input.n{width:84px}#hazard input.d{width:178px}" +
  "#hazard .lst{max-height:150px;overflow:auto;border:1px solid var(--line);border-radius:4px;background:var(--panel)}" +
  "#hazard .it{display:flex;flex-wrap:wrap;gap:2px 8px;align-items:baseline;padding:4px 8px;border-bottom:1px solid var(--line);border-left:4px solid var(--line);font-size:12px;font-variant-numeric:tabular-nums}" +
  "#hazard .it:last-child{border-bottom:0}#hazard .it.hit{border-left-color:var(--bad)}#hazard .it.near{border-left-color:var(--warn)}#hazard .it .m{color:var(--mut)}" +
  "#hazard .verdict{margin:6px 0 0;padding:6px 8px;border-radius:4px;border:1px solid var(--line);font-size:13px}" +
  "#hazard .verdict.v-bad{border-color:var(--bad);background:rgba(248,81,73,.15)}#hazard .verdict.v-warn{border-color:var(--warn);background:rgba(227,179,65,.13)}#hazard .verdict.v-ok{border-color:var(--ok)}" +
  "#hazard .notes{color:var(--mut);font-size:12px;margin:6px 0 0}#hazard .notes b{color:var(--tx)}" +
  "#hazard .out{font-size:13px;margin-top:6px}#hazard .out div{margin-bottom:3px}" +
  "#hazard .err{color:var(--bad);font-size:12px}" +
  "@media(max-width:1000px){#hazard .hwg{grid-template-columns:minmax(0,1fr)}}";
  document.head.appendChild(s);
}
function tag(kind) { var c = { measured: "ok", modelled: "cy", simulated: "sm", scenario: "wa" }[kind] || "wa"; return '<span class="tg ' + c + '">' + kind.toUpperCase() + "</span>"; }

function build() {
  var sec = document.createElement("section"); sec.id = "hazard"; sec.setAttribute("aria-label", "Hazard watch");
  sec.innerHTML =
    "<h2>Hazard watch: threats seen elsewhere, checked against this site " + tag("modelled") + " " + tag("simulated") + "</h2>" +
    '<div class="hwg">' +
    '<div class="box" id="hwRad"><h3>Radiation storms (space weather) ' + tag("modelled") + "</h3>" +
      '<div class="row"><label>EVA start (UTC)<input id="hwEvaS" class="d" type="datetime-local"></label>' +
      '<label>EVA length (h)<input id="hwEvaH" class="n" type="number" min="0.5" step="0.5"></label>' +
      '<button id="hwReload" type="button">Reload feed</button></div>' +
      '<div class="lst" id="hwRadList" role="list"></div><div class="verdict v-ok" id="hwVerdict" role="status"></div>' +
      '<p class="notes" id="hwSkill"></p></div>' +
    '<div class="box" id="hwDust"><h3>Dust storm seen from orbit: operator entry ' + tag("simulated") + "</h3>" +
      '<div class="row"><b style="font-size:12px">Sighting 1</b><label>Lat<input id="hwLat1" class="n" type="number" step="0.1" min="-90" max="90"></label>' +
      '<label>Lon E<input id="hwLon1" class="n" type="number" step="0.1" min="-360" max="360"></label>' +
      '<label>Radius km<input id="hwR1" class="n" type="number" step="10" min="1"></label>' +
      '<label>Seen (UTC)<input id="hwT1" class="d" type="datetime-local"></label></div>' +
      '<div class="row"><b style="font-size:12px">Sighting 2 (optional)</b><label>Lat<input id="hwLat2" class="n" type="number" step="0.1" min="-90" max="90"></label>' +
      '<label>Lon E<input id="hwLon2" class="n" type="number" step="0.1" min="-360" max="360"></label>' +
      '<label>Radius km<input id="hwR2" class="n" type="number" step="10" min="1"></label>' +
      '<label>Seen (UTC)<input id="hwT2" class="d" type="datetime-local"></label></div>' +
      '<div class="row"><button id="hwCalc" type="button">Compute and add to watch</button><button id="hwEx" type="button">Fill example</button><button id="hwClr" type="button">Clear</button></div>' +
      '<div class="out" id="hwOut" role="status" aria-live="polite"></div>' +
      '<p class="notes" id="hwSeason"></p></div>' +
    "</div>";
  var main = document.querySelector("main"), scr = document.querySelector("body > script");
  document.body.insertBefore(sec, scr || null);
  ["hwEvaS", "hwEvaH", "hwReload", "hwRadList", "hwVerdict", "hwSkill", "hwLat1", "hwLon1", "hwR1", "hwT1", "hwLat2", "hwLon2", "hwR2", "hwT2", "hwCalc", "hwEx", "hwClr", "hwOut", "hwSeason"].forEach(function (id) { el[id] = document.getElementById(id); });
}

// ---- radiation part
function evaWindow() {
  var s = parseInp(el.hwEvaS.value), h = parseFloat(el.hwEvaH.value);
  if (!isFinite(s) || !isFinite(h) || h <= 0) return null;
  return { s: s, e: s + h * 3600000 };
}
function radItems() {
  return FEED.filter(function (r) { return r && r.type === "hazard" && r.hazard && (r.hazard.kind === "cme" || r.hazard.kind === "sep"); })
    .map(function (r) { var a = Date.parse(r.hazard.start_utc), b = r.hazard.end_utc ? Date.parse(r.hazard.end_utc) : a; return { r: r, a: a, b: b, glancing: /glancing/.test(r.hazard.note || "") }; })
    .filter(function (x) { return isFinite(x.a); }).sort(function (x, y) { return y.a - x.a; });
}
function renderRad() {
  var w = evaWindow(), items = radItems(), now = Date.now(), pad = PAD_H * 3600000, html = "", hit = 0, hitHard = 0, cme = 0;
  items.forEach(function (x) {
    var isCme = x.r.hazard.kind === "cme", inWin = false;
    if (isCme) {
      cme++;
      inWin = w && (x.a - pad) <= w.e && (x.b + pad) >= w.s;
      if (inWin) { hit++; if (!x.glancing) hitHard++; }
    }
    var cls = inWin ? (x.glancing ? "it near" : "it hit") : "it";
    html += '<div class="' + cls + '" role="listitem">' + tag(x.r.label || "modelled") +
      "<b>" + (isCme ? "Mars arrival " + esc(fmtUtc(x.a)) : "SEP onset " + esc(fmtUtc(x.a))) + "</b>" +
      (isCme ? '<span class="m">window ' + esc(fmtUtc(x.a - pad)) + " to " + esc(fmtUtc(x.b + pad)) + " (+/- " + PAD_H + " h)</span>" : "") +
      '<span class="m">' + esc(x.r.source || "") + (x.glancing ? ", glancing blow" : "") + (isCme ? ", sol " + esc(x.r.sol) : "") + "</span>" +
      '<span class="m" title="' + esc(x.r.hazard.note || "") + '">' + (isCme ? "error figure: SD 17-20 h (published)" : "seen near Earth/STEREO A, not at Mars") + "</span>" +
      (inWin ? "<b>inside EVA window</b>" : "") + "</div>";
  });
  if (!items.length) html = '<div class="it"><span class="m">' + (feedErr ? esc(feedErr) : "No hazard records in feed.json (run tools/ingest.py).") + "</span></div>";
  el.hwRadList.innerHTML = html;
  var v = el.hwVerdict;
  if (!w) { v.className = "verdict v-warn"; v.innerHTML = "Enter an EVA start time and length."; }
  else if (hitHard) {
    v.className = "verdict v-bad";
    v.innerHTML = "<b>NO-GO advisory by radiation rule " + esc(CS07) + ".</b> " + hitHard + " predicted Mars arrival" + (hitHard > 1 ? "s fall" : " falls") + " inside the EVA window plus the typical timing error (+/- " + PAD_H + " h). Recommend staying near shelter. " +
      "Advisory only: a CME arrival can bring energetic particles but is not a dose forecast; the CS-07 check in the flight rules still uses the planned dose (budget " + doseBudget + " &micro;Gy per EVA). " + tag("modelled");
  } else if (hit) {
    v.className = "verdict v-warn";
    v.innerHTML = "<b>Caution:</b> " + hit + " glancing-blow arrival" + (hit > 1 ? "s" : "") + " within the EVA window +/- " + PAD_H + " h. Recommend staying near shelter and watching RAD; " + "rule " + esc(CS07) + " is not triggered by a glancing blow alone. " + tag("modelled");
  } else {
    v.className = "verdict v-ok";
    v.innerHTML = cme ? "No predicted Mars arrival within the EVA window +/- " + PAD_H + " h among " + cme + " in the feed. This is not a guarantee: DONKI only lists CMEs it has modelled." : "No Mars arrival predictions to check. " + tag("modelled");
  }
  el.hwSkill.innerHTML = "<b>Skill check.</b> DONKI gives no uncertainty for the Mars arrival time. Published errors: ENLIL minus Forbush-decrease transit time, mean absolute about " + ENLIL_MAE_H + " h (15 ICMEs, best of several runs; von Forstner et al. 2018, arXiv:1712.07301); " +
    "arrival at Mars versus RAD, mean -11 to +5 h, SD 17 to 20 h (45 events, heliospheric-imager methods; arXiv:1904.10859). " +
    "Our own check against Curiosity RAD (45 sol files 2024-2026, one sol per 10 or fewer) found no sustained dose enhancement matching a predicted arrival, so no timing error could be measured here; the May 2024 storm is not in the repo RAD files. " +
    "See data/processed/hazards/cme_skill.json. " + tag("measured") + " RAD, " + tag("modelled") + " ENLIL.";
}
function loadFeed() {
  feedErr = "";
  return fetch("feed.json", { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error("feed.json not available (" + r.status + ")"); return r.json(); })
    .then(function (j) { FEED = j.records || []; }, function (e) { FEED = []; feedErr = String(e.message || e); })
    .then(loadIdb).then(renderRad);
}
function loadIdb() {   // operator records of earlier visits and anything feed.js stored
  return openDb().then(function (db) {
    return new Promise(function (res) {
      var rq = db.transaction(STORE).objectStore(STORE).getAll();
      rq.onsuccess = function () { db.close(); var ids = {}; FEED.forEach(function (r) { ids[r.id] = 1; }); (rq.result || []).forEach(function (r) { if (!ids[r.id] && r.hazard && r.hazard.kind !== "dust_storm") FEED.push(r); }); res(); };
      rq.onerror = function () { db.close(); res(); };
    });
  }).catch(function () { /* IndexedDB blocked: feed.json alone is enough */ });
}

// ---- dust part
function readSighting(n) {
  var lat = parseFloat(el["hwLat" + n].value), lon = parseFloat(el["hwLon" + n].value), r = parseFloat(el["hwR" + n].value), t = parseInp(el["hwT" + n].value);
  if (!isFinite(lat) && !isFinite(lon) && !isFinite(r) && !isFinite(t)) return null;
  if (!isFinite(lat) || !isFinite(lon) || !isFinite(r) || !isFinite(t)) return { bad: "Sighting " + n + " needs latitude, longitude, radius and a date." };
  if (Math.abs(lat) > 90) return { bad: "Latitude must be between -90 and 90." };
  return { lat: lat, lon: lon, r: r, t: t };
}
function seasonText(ms) {
  var ls = marsLs(ms), t = tauAt(ls), inS = ls >= DUST_SEASON[0] && ls <= DUST_SEASON[1];
  return "Season at " + fmtUtc(ms) + ": Ls " + ls.toFixed(0) + " deg, " + (inS ? "<b>inside</b>" : "outside") + " the dusty season (Ls " + DUST_SEASON[0] + "-" + DUST_SEASON[1] + ", when most regional and global storms occur; Wolkenberg et al. 2018, arXiv:1802.02653)." +
    (t ? " Mastcam climatological dust optical depth here: tau880 " + t.tau.toFixed(2) + " (quartiles " + t.p25.toFixed(2) + " to " + t.p75.toFixed(2) + "; sols 33-3953, not a current measurement) " + tag("measured") + "." : "");
}
function compute() {
  var a = readSighting(1), b = readSighting(2), o = [], rec = null, now = Date.now();
  if (!a) { el.hwOut.innerHTML = '<span class="err">Enter at least sighting 1.</span>'; return; }
  if (a.bad || (b && b.bad)) { el.hwOut.innerHTML = '<span class="err">' + esc(a.bad || b.bad) + "</span>"; return; }
  var d1 = gcKm(a, GALE), brg1 = bearing(GALE, a), head1 = bearing(a, GALE);
  o.push("Sighting 1 centre is <b>" + d1.toFixed(0) + " km</b> from Gale (edge " + Math.max(0, d1 - a.r).toFixed(0) + " km), seen from Gale toward " + brg1.toFixed(0) + " deg (" + compass(brg1) + "); a heading of " + head1.toFixed(0) + " deg would point at Gale.");
  var haz = { kind: "dust_storm", center: { lat: a.lat, lon: a.lon }, radius_km: a.r }, seen = a.t, label = "scenario";
  if (b) {
    if (b.t <= a.t) { el.hwOut.innerHTML = '<span class="err">Sighting 2 must be later than sighting 1.</span>'; return; }
    var dd = gcKm(a, b), dtS = (b.t - a.t) / 1000, v = dd * 1000 / dtS, hd = bearing(a, b), tk = trackOf(a, b, GALE), d2 = gcKm(b, GALE);
    o.push("Observed front motion " + dd.toFixed(0) + " km in " + fmtDur(dtS / 3600) + " = <b>" + v.toFixed(1) + " m/s</b> toward " + hd.toFixed(0) + " deg (" + compass(hd) + "). " + tag("simulated"));
    if (v > 40 || v < 1) o.push('<span class="err">Speed outside the 6-26 m/s of measured storms (Sanchez-Lavega et al. 2025); check the positions and dates.</span>');
    var rem = tk.at - gcKm(a, b), half = tk.xt <= b.r ? Math.sqrt(b.r * b.r - tk.xt * tk.xt) : 0;
    haz = { kind: "dust_storm", center: { lat: b.lat, lon: b.lon }, radius_km: b.r }; seen = b.t; label = "simulated";
    if (d2 <= b.r) {
      o.push("<b>Gale was already inside the storm at sighting 2</b> (centre " + d2.toFixed(0) + " km away, radius " + b.r.toFixed(0) + " km).");
      haz.start_utc = isoMs(b.t); haz.end_utc = isoMs(b.t + (b.r + d2) * 1000 / v * 1000); haz.affects_site = true;
      haz.note = "Operator scenario: Gale inside the storm at sighting 2; leaves in about " + fmtDur((b.r + d2) / v / 3.6) + " if it keeps moving.";
    } else if (tk.xt > b.r) {
      o.push("Track passes Gale at " + tk.xt.toFixed(0) + " km, outside the radius " + b.r.toFixed(0) + " km: <b>misses Gale by " + (tk.xt - b.r).toFixed(0) + " km</b> if it keeps heading and size.");
      haz.affects_site = false; haz.start_utc = haz.end_utc = isoMs(b.t); haz.note = "Operator scenario: straight-line track misses Gale by " + (tk.xt - b.r).toFixed(0) + " km at the observed heading.";
    } else if (rem + half < 0) {
      o.push("The storm is <b>moving away</b>: closest approach to Gale was already passed.");
      haz.affects_site = false; haz.start_utc = haz.end_utc = isoMs(b.t); haz.note = "Operator scenario: moving away from Gale.";
    } else {
      var tin = b.t + Math.max(0, rem - half) * 1000 / v * 1000, tout = b.t + (rem + half) * 1000 / v * 1000;
      o.push("If it keeps this speed, heading and radius, the storm body covers Gale from <b>" + fmtUtc(tin) + "</b> to <b>" + fmtUtc(tout) + "</b> (" + fmtDur((tout - tin) / 3600000) + "; arrival in " + fmtDur(Math.max(0, tin - now) / 3600000) + " from now). " +
        "Track passes " + tk.xt.toFixed(0) + " km from Gale's line. No error bar: sighting position errors are not known to this tool. " + tag("simulated"));
      haz.affects_site = true; haz.start_utc = isoMs(tin); haz.end_utc = isoMs(tout);
      haz.note = "Operator scenario from two sightings: front speed " + v.toFixed(1) + " m/s toward " + hd.toFixed(0) + " deg, assumed constant; arrival window is leading to trailing edge over Gale.";
    }
  } else {
    var edge = Math.max(0, d1 - a.r), t0 = a.t + edge * 1000 / V_MAX * 1000, t1 = a.t + edge * 1000 / V_MIN * 1000;
    if (d1 <= a.r) {
      o.push("Gale was inside the sighted storm at the time of sighting.");
      haz.affects_site = true; haz.start_utc = haz.end_utc = isoMs(a.t); haz.note = "Operator scenario: Gale inside the sighted radius.";
    } else {
      o.push("<b>Scenario, if the storm headed straight for Gale</b> at " + V_MIN + " to " + V_MAX + " m/s (front speeds measured from MARCI/VMC images in Mars year 36, Sanchez-Lavega et al. 2025, arXiv:2501.05337): leading edge arrives between <b>" + fmtUtc(t0) + "</b> and <b>" + fmtUtc(t1) + "</b>. " + tag("scenario") +
        " A single sighting gives no heading, so most storms will not go this way; add a second sighting to estimate motion.");
      haz.affects_site = false; haz.start_utc = isoMs(t0); haz.end_utc = isoMs(t1);
      haz.note = "Operator scenario, one sighting, assumed heading straight at Gale at " + V_MIN + "-" + V_MAX + " m/s; not a forecast. Window is the leading-edge arrival range.";
    }
  }
  var eva = evaWindow(), s0 = Date.parse(haz.start_utc), s1 = Date.parse(haz.end_utc);
  if (eva && haz.affects_site && s1 >= eva.s && s0 <= eva.e) o.push("<b>Overlaps the EVA window.</b> Re-plan: mission control applies HZ-1 / HZ-2 from tau measured at the walker, not from this scenario.");
  el.hwOut.innerHTML = o.map(function (x) { return "<div>" + x + "</div>"; }).join("");
  el.hwSeason.innerHTML = seasonText(seen) + (haz.start_utc && s0 > seen ? "<br>" + seasonText(s0).replace("Season at", "Season at arrival,") : "");
  var core = JSON.stringify({ haz: haz, seen: seen, a: a, b: b });
  rec = { type: "hazard", source: "hazard_watch", observed_utc: isoMs(seen), available_utc: isoMs(now), ingested_utc: isoMs(now), sol: marsSol(seen), label: "simulated", hazard: haz,
    provenance: { url: "operator entry on mission.html (nothing fetched)", sha256: "", method: (b ? "two orbiter sightings, constant-velocity great-circle extrapolation" : "one orbiter sighting, speed range from literature") + "; Mars radius " + R_MARS + " km; Gale " + GALE.lat + ", " + GALE.lon } };
  sha256Hex(core).then(function (h) {
    rec.provenance.sha256 = h; rec.id = "sim-dust-" + (h ? h.slice(0, 12) : String(now));
    return putRecord(rec);
  }).then(function () {
    el.hwOut.insertAdjacentHTML("beforeend", '<div class="m" id="hwSaved">Record ' + esc(rec.id) + " written to IndexedDB marswalk-feed/records and broadcast. " + tag("simulated") + "</div>");
    window.__hazard = { record: rec, calc: { distKm: d1, bearingDeg: brg1 } };
  }, function (e) { el.hwOut.insertAdjacentHTML("beforeend", '<div class="err">Could not store the record: ' + esc(e && e.message || e) + "</div>"); });
  window.__hazard = { record: rec, calc: { distKm: d1, bearingDeg: brg1 } };
}
function example() {
  var now = Date.now();
  el.hwLat1.value = "-20"; el.hwLon1.value = "100"; el.hwR1.value = "400"; el.hwT1.value = inputVal(now - 24 * 3600000);
  el.hwLat2.value = "-14"; el.hwLon2.value = "112"; el.hwR2.value = "450"; el.hwT2.value = inputVal(now);
  el.hwOut.innerHTML = '<div class="m">Example numbers only, not an observed storm. ' + tag("simulated") + "</div>";
}
function clearForm() { ["hwLat1", "hwLon1", "hwR1", "hwT1", "hwLat2", "hwLon2", "hwR2", "hwT2"].forEach(function (k) { el[k].value = ""; }); el.hwOut.innerHTML = ""; }

function init() {
  css(); build();
  var n = Date.now(), touched = false, tries = 0;
  function fromLog() {   // EVA length and dose budget from the mission log once mission.html has loaded it
    var H = window.__mission && window.__mission.log, tl = H && H.mission && H.mission.plan_decision && H.mission.plan_decision.timeline;
    if (!H) return false;
    if (H.mission.limits && H.mission.limits.dose_budget_uGy) doseBudget = H.mission.limits.dose_budget_uGy;
    if (tl && tl.nominal_plus_contingency_s && !touched) { evaDefaultH = Math.round(tl.nominal_plus_contingency_s / 1800) / 2; el.hwEvaH.value = evaDefaultH; }
    renderRad(); return true;
  }
  el.hwEvaS.value = inputVal(n); el.hwEvaH.value = evaDefaultH;
  el.hwEvaH.addEventListener("input", function () { touched = true; });
  var iv = setInterval(function () { if (fromLog() || ++tries > 100) clearInterval(iv); }, 100);
  el.hwEvaS.addEventListener("input", renderRad); el.hwEvaH.addEventListener("input", renderRad);
  el.hwReload.onclick = loadFeed; el.hwCalc.onclick = compute; el.hwEx.onclick = example; el.hwClr.onclick = clearForm;
  el.hwSeason.innerHTML = seasonText(n) + " Where to look: MRO MARCI daily global maps. Malin Space Science Systems' weekly Mars weather report is an HTML page with a movie and no data feed (its index, as fetched on 2026-11-13, ends in February 2022), so there is no automatic dust feed here.";
  fetch("tau_climatology.json").then(function (r) { return r.json(); }).then(function (j) { tau = j; el.hwSeason.innerHTML = seasonText(n) + " Where to look: MRO MARCI daily global maps. Malin Space Science Systems' weekly Mars weather report is an HTML page with a movie and no data feed (its index, as fetched on 2026-11-13, ends in February 2022), so there is no automatic dust feed here."; }, function () { });
  loadFeed();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { setTimeout(init, 0); }); else setTimeout(init, 0);
})();
