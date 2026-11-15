/* MARSWALK data feed panel for mission control. Plain JS, no libraries.
   Shows what the poller (tools/ingest.py -> feed.json) has fetched, how late each source is, and lets you upload
   data (RAD CSV, REMS CSV, Navcam image, JSON records) that is validated here, stored in IndexedDB
   "marswalk-feed"/"records" and broadcast on BroadcastChannel "marswalk-feed" so an open twin tab updates at once.
   Record schema: docs/data_feed.md. Nothing is sent to any server. */
(function () {
"use strict";
var GRID = { w: 585, h: 732 };
var DB_NAME = 'marswalk-feed', STORE = 'records';
var LABELS = ['measured', 'modelled', 'simulated'];
var TYPES = ['rad', 'photo', 'weather', 'hazard'];
var chan = null, acked = {}, feed = null, uploads = [], twinData = null, last = { msgs: [] };
var $ = function (id) { return document.getElementById(id); };
var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };

function css() {
  var s = document.createElement('style');
  s.textContent =
  '#feed{margin:0 16px 12px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}' +
  '#feed h2{font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut)}' +
  '#feed h3{font-size:12px;margin:12px 0 6px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut)}' +
  '#feed .top{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-bottom:8px}' +
  '#feed .top .sp{flex:1 1 200px;color:var(--mut);font-size:12px}' +
  '#feed .lnk{display:inline-block;color:var(--cyan);text-decoration:none;border:1px solid var(--cyan);border-radius:4px;padding:5px 10px}' +
  '#feed .lnk:hover{background:var(--cyan);color:#001}' +
  '#feed .src{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(350px,1fr))}' +
  '#feed .card{background:var(--panel2);border:1px solid var(--line);border-left:5px solid var(--line);border-radius:4px;padding:8px 10px;min-width:0}' +
  '#feed .card.ok{border-left-color:var(--ok)}#feed .card.no_new,#feed .card.offline{border-left-color:var(--warn)}#feed .card.error{border-left-color:var(--bad)}' +
  '#feed .card .nm{display:flex;flex-wrap:wrap;gap:4px 8px;align-items:baseline;justify-content:space-between}' +
  '#feed .card .nm b{font-size:15px}' +
  '#feed .card .mi{color:var(--mut);font-size:12px}' +
  '#feed .chip{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;border-radius:3px;padding:1px 6px;background:var(--line);color:var(--tx)}' +
  '#feed .chip.ok{background:var(--ok);color:#04100a}#feed .chip.no_new,#feed .chip.offline{background:var(--warn);color:#110}#feed .chip.error{background:var(--bad);color:#fff}' +
  '#feed .chain{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin:8px 0 4px}' +
  '#feed .chain div{position:relative;padding:4px 2px 4px 6px;border-top:3px solid var(--cyan);font-size:11px;color:var(--mut);min-width:0;overflow-wrap:anywhere}' +
  '#feed .chain div b{display:block;color:var(--tx);font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums}' +
  '#feed .chain div.na{border-top-color:var(--line)}' +
  '#feed .chain div i{display:block;font-style:normal;color:var(--ground);font-size:11px;font-variant-numeric:tabular-nums}' +
  '#feed .card .tl{color:var(--mut);font-size:11px;margin-top:2px}' +
  '#feed details{margin-top:4px;font-size:12px;color:var(--mut)}#feed details summary{cursor:pointer;color:var(--cyan)}' +
  '#feed .tw{overflow:auto;max-height:260px;border:1px solid var(--line);border-radius:4px}' +
  '#feed table{border-collapse:collapse;width:100%;font-size:12px}' +
  '#feed th{position:sticky;top:0;background:var(--panel2);text-align:left;color:var(--mut);font-weight:600;padding:4px 8px;border-bottom:1px solid var(--line);white-space:nowrap}' +
  '#feed td{padding:3px 8px;border-bottom:1px solid var(--line);vertical-align:top;font-variant-numeric:tabular-nums}' +
  '#feed td.sm{max-width:380px;overflow-wrap:anywhere}' +
  '#feed .tg{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;border-radius:3px;padding:0 5px}' +
  '#feed .tg.measured{background:var(--ok);color:#04100a}#feed .tg.modelled{background:var(--cyan);color:#001}#feed .tg.simulated{background:var(--sim);color:#110}' +
  '#feed .up{display:grid;gap:12px;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}' +
  '#feed .drop{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;text-align:center;min-height:120px;padding:12px;border:2px dashed var(--line);border-radius:6px;background:var(--panel2);color:var(--mut);cursor:pointer}' +
  '#feed .drop.over,#feed .drop:focus-within{border-color:var(--cyan);color:var(--tx)}' +
  '#feed .drop input{max-width:100%}' +
  '#feed .frm{display:grid;gap:6px;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));align-items:end}' +
  '#feed label[hidden]{display:none}' +
  '#feed label{display:block;font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}' +
  '#feed input[type=number],#feed select{width:100%;margin-top:2px;font:inherit;background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:4px;padding:4px 6px}' +
  '#feed .chk{display:flex;gap:8px;align-items:flex-start;margin:8px 0;font-size:13px;color:var(--tx);text-transform:none;letter-spacing:0}' +
  '#feed .help{color:var(--mut);font-size:12px;margin:4px 0}' +
  '#feed .help code{background:var(--bg);padding:0 4px;border-radius:3px;color:var(--tx)}' +
  '#feed .msgs{list-style:none;margin:8px 0 0;padding:0;max-height:200px;overflow:auto}' +
  '#feed .msgs li{border-left:4px solid var(--line);padding:3px 8px;margin-bottom:4px;background:var(--panel2);border-radius:0 4px 4px 0;font-size:12px;overflow-wrap:anywhere}' +
  '#feed .msgs li.ok{border-left-color:var(--ok)}#feed .msgs li.err{border-left-color:var(--bad)}#feed .msgs li.warn{border-left-color:var(--warn)}' +
  '#feed .none{color:var(--mut);padding:6px 0}' +
  '#feed .ex{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));margin:0 0 12px}' +
  '#feed .xc{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:10px 12px;min-width:0}' +
  '#feed .xc h3{margin:0 0 6px}#feed .xc p{margin:0 0 8px;font-size:12px;color:var(--mut)}' +
  '#feed .xg{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}' +
  '#feed .xg figure{align-self:start;margin:0;border:1px solid var(--line);border-radius:4px;overflow:hidden;background:#000;min-width:0}' +
  '#feed .xg img{display:block;width:100%;height:auto;aspect-ratio:3/2;object-fit:cover}' +
  '#feed .xg figcaption{padding:4px 6px;font-size:11px;color:var(--mut);background:var(--panel)}' +
  '#feed .xg figcaption b{color:var(--fg);font-weight:600}#feed .xg a{color:var(--cyan)}' +
  '#feed .lat{display:flex;flex-wrap:wrap;gap:6px 14px;margin:0 0 8px;font-size:12px}#feed .lat span{border:1px solid var(--line);border-radius:4px;padding:3px 8px}' +
  '#feed .lat b{font-weight:600}' +
  '@media(max-width:800px){#feed .up{grid-template-columns:minmax(0,1fr)}#feed .chain{grid-template-columns:repeat(2,minmax(0,1fr))}}';
  document.head.appendChild(s);
}

function build() {
  var sec = document.createElement('section');
  sec.id = 'feed'; sec.setAttribute('aria-label', 'Data feed');
  sec.innerHTML =
    '<h2>Data feed: from public release to the digital twin</h2>' +
    '<div class="top"><button id="feRefresh" type="button">Refresh</button><a class="lnk" id="feOpen" href="twin.html" target="_blank" rel="noopener">Open twin</a>' +
    '<span class="sp" id="feGen" role="status" aria-live="polite"></span></div>' +
    '<div class="src" id="feSrc"></div>' +
    '<div class="ex" id="feEx"></div>' +
    '<h3>Records <span id="feCnt" class="mi"></span></h3><div class="tw"><table><thead><tr><th>Label</th><th>Type</th><th>Source</th><th>Sol</th><th>Observed (UTC)</th><th>Value</th><th>In the twin</th></tr></thead><tbody id="feRec"></tbody></table></div>' +
    '<h3>Upload your own data</h3><div class="up">' +
    '<div><label class="drop" id="feDrop"><b>Drop files here or choose</b><span>RAD CSV, REMS CSV, Navcam JPG/PNG, or a JSON file of records</span>' +
    '<input type="file" id="feFile" multiple accept=".csv,.json,.jpg,.jpeg,.png,image/jpeg,image/png,text/csv,application/json" aria-label="Choose files to upload"></label>' +
    '<label class="chk"><input type="checkbox" id="feReal"><span>This is real mission data. Unticked, every record is labelled <b>simulated</b>.</span></label>' +
    '<ul class="msgs" id="feMsgs" aria-live="polite"></ul></div>' +
    '<div><div class="help"><b>RAD CSV:</b> <code>sol,uGy_h[,observed_utc]</code><br><b>REMS CSV:</b> <code>sol,min_C,max_C[,pressure_Pa]</code><br>' +
    '<b>JSON:</b> an array of records (or <code>{"records":[...]}</code>) in the feed schema, see docs/data_feed.md.<br>' +
    '<b>Navcam image:</b> fill in the sol and a place on the twin grid, then drop the image.</div>' +
    '<div class="frm"><label>Sol<input type="number" id="feSol" min="0" max="99999" step="1" placeholder="e.g. 4687"></label>' +
    '<label>Camera<select id="feCam"><option>NAV_LEFT_B</option><option>NAV_RIGHT_B</option><option>MAST_LEFT</option><option>MAST_RIGHT</option></select></label>' +
    '<label>Place<select id="fePlace"><option value="xy">Twin grid x, y</option><option value="near">Near Curiosity\'s stop on sol</option></select></label>' +
    '<label id="feXl">x (0-' + GRID.w + ')<input type="number" id="feX" min="0" max="' + GRID.w + '" step="0.01"></label>' +
    '<label id="feYl">y (0-' + GRID.h + ')<input type="number" id="feY" min="0" max="' + GRID.h + '" step="0.01"></label>' +
    '<label id="feNl" hidden>Stop sol<input type="number" id="feNear" min="0" max="99999" step="1"></label></div>' +
    '<div class="top" style="margin-top:10px"><button id="feClear" type="button">Clear my uploads</button><span class="mi" id="feStore"></span></div></div></div>';
  var after = document.querySelector('main');
  if (after && after.parentNode) after.parentNode.insertBefore(sec, after.nextSibling); else document.body.appendChild(sec);
}

// ---------- time helpers
function pd(s) { var t = s ? Date.parse(s) : NaN; return isNaN(t) ? null : t; }
function fmt(s) { var t = pd(s); return t === null ? 'n/a' : new Date(t).toISOString().slice(0, 16).replace('T', ' ') + 'Z'; }
function dur(ms) {
  if (ms === null || isNaN(ms)) return '';
  var a = Math.abs(ms) / 1000;
  if (a < 90) return a.toFixed(0) + ' s';
  if (a < 5400) return (a / 60).toFixed(0) + ' min';
  if (a < 172800) return (a / 3600).toFixed(1) + ' h';
  return (a / 86400).toFixed(1) + ' d';
}
function ago(s) { var t = pd(s); return t === null ? '' : (Date.now() - t < 60000 ? 'just now' : dur(Date.now() - t) + ' ago'); }
function fmt2(t) { var x = new Date(t).toISOString(); return x.slice(0, 10) + '<br>' + x.slice(11, 16) + 'Z'; }

// ---------- IndexedDB
function openDB() {
  return new Promise(function (res, rej) {
    if (!window.indexedDB) { rej(new Error('IndexedDB is not available in this browser')); return; }
    var r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = function () { if (!r.result.objectStoreNames.contains(STORE)) r.result.createObjectStore(STORE, { keyPath: 'id' }); };
    r.onsuccess = function () { res(r.result); };
    r.onerror = function () { rej(r.error || new Error('IndexedDB open failed')); };
  });
}
function idb(mode, fn) {
  return openDB().then(function (db) {
    return new Promise(function (res, rej) {
      var tx = db.transaction(STORE, mode), st = tx.objectStore(STORE), out = fn(st);
      tx.oncomplete = function () { db.close(); res(out && out.result !== undefined ? out.result : undefined); };
      tx.onerror = tx.onabort = function () { db.close(); rej(tx.error || new Error('IndexedDB transaction failed')); };
    });
  });
}
function putAll(recs) { return idb('readwrite', function (st) { recs.forEach(function (r) { st.put(r); }); }); }
function allRecs() { return idb('readonly', function (st) { return st.getAll(); }).then(function (a) { return a || []; }); }
function clearUploads() { return idb('readwrite', function (st) { var q = st.openCursor(); q.onsuccess = function () { var c = q.result; if (c) { if (c.value.source === 'upload' || c.value.source === 'hazard_watch') c.delete(); c.continue(); } }; }); }

// ---------- messages
function say(kind, text) {
  var li = document.createElement('li'); li.className = kind; li.textContent = text;
  var ul = $('feMsgs'); ul.insertBefore(li, ul.firstChild);
  while (ul.children.length > 60) ul.removeChild(ul.lastChild);
}

// ---------- parsing and validation
function parseCSV(text) {
  text = text.replace(/^﻿/, '');
  var rows = [], row = [], cur = '', q = false, i, c;
  for (i = 0; i < text.length; i++) {
    c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cur); rows.push(row); row = []; cur = ''; }
    else cur += c;
  }
  if (cur !== '' || row.length) { row.push(cur); rows.push(row); }
  return rows.filter(function (r) { return r.some(function (x) { return x.trim() !== ''; }) && !/^\s*#/.test(r[0]); });
}
function num(s) { s = String(s == null ? '' : s).trim(); if (s === '' || !/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) return null; return parseFloat(s); }
function solOf(s) { var n = num(s); return n !== null && n >= 0 && n <= 99999 && Math.floor(n) === n ? n : null; }
function isoOrNull(s) { s = (s || '').trim(); if (!s) return null; var t = Date.parse(s); return isNaN(t) ? undefined : new Date(t).toISOString().replace(/\.\d+Z$/, 'Z'); }
function sha256(buf) {
  if (!(window.crypto && crypto.subtle)) return Promise.resolve(null);
  return crypto.subtle.digest('SHA-256', buf).then(function (h) { return Array.prototype.map.call(new Uint8Array(h), function (b) { return (b < 16 ? '0' : '') + b.toString(16); }).join(''); }, function () { return null; });
}
function base(type, sol, label, obs, name, hash, method) {
  var t = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  return { id: '', type: type, source: 'upload', observed_utc: obs, available_utc: t, ingested_utc: t, sol: sol, label: label,
           provenance: { url: 'upload:' + name, sha256: hash, method: method } };
}

function parseTable(text, name, hash, label) {
  var rows = parseCSV(text), errs = [], out = [];
  if (rows.length < 2) return { recs: [], errs: ['File has no data rows (need a header line and at least one row).'] };
  var head = rows[0].map(function (h) { return h.trim().toLowerCase(); });
  var ix = function (n) { return head.indexOf(n); };
  var kind = ix('ugy_h') >= 0 ? 'rad' : (ix('min_c') >= 0 && ix('max_c') >= 0 ? 'weather' : null);
  if (!kind || ix('sol') < 0) return { recs: [], errs: ['Cannot tell what this CSV is. The header must be "sol,uGy_h[,observed_utc]" (RAD) or "sol,min_C,max_C[,pressure_Pa]" (REMS); found "' + rows[0].join(',') + '".'] };
  rows.slice(1).forEach(function (r, k) {
    var n = k + 2, sol = solOf(r[ix('sol')]);
    if (sol === null) { errs.push('Row ' + n + ': sol "' + (r[ix('sol')] || '') + '" must be a whole number from 0 to 99999.'); return; }
    var obs = ix('observed_utc') >= 0 ? isoOrNull(r[ix('observed_utc')]) : null;
    if (obs === undefined) { errs.push('Row ' + n + ': observed_utc "' + r[ix('observed_utc')] + '" is not a date (use e.g. 2026-03-29T10:00:00Z).'); return; }
    var rec;
    if (kind === 'rad') {
      var d = num(r[ix('ugy_h')]);
      if (d === null) { errs.push('Row ' + n + ': uGy_h "' + (r[ix('ugy_h')] || '') + '" is not a number.'); return; }
      if (!(d > 0 && d < 1000)) { errs.push('Row ' + n + ': uGy_h ' + d + ' is outside 0 to 1000 (Curiosity RAD reads about 5 to 12 uGy/h).'); return; }
      rec = base('rad', sol, label, obs, name, hash, 'CSV upload, one row per sol');
      rec.rad = { uGy_h: d }; rec.id = 'rad-upload-' + sol;
    } else {
      var lo = num(r[ix('min_c')]), hi = num(r[ix('max_c')]), p = ix('pressure_pa') >= 0 ? r[ix('pressure_pa')].trim() : '';
      if (lo === null) { errs.push('Row ' + n + ': min_C "' + (r[ix('min_c')] || '') + '" is not a number.'); return; }
      if (hi === null) { errs.push('Row ' + n + ': max_C "' + (r[ix('max_c')] || '') + '" is not a number.'); return; }
      if (lo > hi) { errs.push('Row ' + n + ': min_C ' + lo + ' is above max_C ' + hi + '.'); return; }
      if (lo < -150 || hi > 60) { errs.push('Row ' + n + ': temperatures ' + lo + ' to ' + hi + ' deg C are outside -150 to 60.'); return; }
      var pv = null;
      if (p !== '') { pv = num(p); if (pv === null || pv < 100 || pv > 1500) { errs.push('Row ' + n + ': pressure_Pa "' + p + '" must be a number from 100 to 1500.'); return; } }
      rec = base('weather', sol, label, obs, name, hash, 'CSV upload, one row per sol');
      rec.weather = { min_C: lo, max_C: hi, pressure_Pa: pv }; rec.id = 'weather-upload-' + sol;
    }
    out.push(rec);
  });
  return { recs: out, errs: errs };
}

function checkRecord(r, n, label, name, hash) {
  var e = function (m) { return 'Record ' + n + ': ' + m; };
  if (!r || typeof r !== 'object' || Array.isArray(r)) return { err: e('not an object.') };
  if (typeof r.id !== 'string' || !r.id) return { err: e('"id" must be a non-empty string.') };
  if (TYPES.indexOf(r.type) < 0) return { err: e('"type" must be one of ' + TYPES.join(', ') + '.') };
  if (solOf(r.sol) === null) return { err: e('"sol" must be a whole number from 0 to 99999.') };
  if (r.label != null && LABELS.indexOf(r.label) < 0) return { err: e('"label" must be measured, modelled or simulated.') };
  var b = r[r.type];
  if (!b || typeof b !== 'object') return { err: e('missing the "' + r.type + '" block.') };
  if (r.type === 'rad' && !(typeof b.uGy_h === 'number' && b.uGy_h > 0 && b.uGy_h < 1000)) return { err: e('rad.uGy_h must be a number between 0 and 1000.') };
  if (r.type === 'weather') {
    if (typeof b.min_C !== 'number' || typeof b.max_C !== 'number' || b.min_C > b.max_C) return { err: e('weather.min_C and max_C must be numbers with min_C <= max_C.') };
    if (b.pressure_Pa != null && typeof b.pressure_Pa !== 'number') return { err: e('weather.pressure_Pa must be a number or null.') };
  }
  if (r.type === 'photo') {
    if (typeof b.file !== 'string' || !b.file) return { err: e('photo.file must be a path relative to demo/twin.') };
    if (!(typeof b.x === 'number' && b.x >= 0 && b.x <= GRID.w && typeof b.y === 'number' && b.y >= 0 && b.y <= GRID.h)) return { err: e('photo.x and photo.y must be inside the ' + GRID.w + ' x ' + GRID.h + ' grid.') };
  }
  if (r.type === 'hazard') {
    if (['dust_storm', 'cme', 'sep', 'obstacle'].indexOf(b.kind) < 0) return { err: e('hazard.kind must be dust_storm, cme, sep or obstacle.') };
    if (pd(b.start_utc) === null || (b.end_utc != null && pd(b.end_utc) === null)) return { err: e('hazard.start_utc must be a date; end_utc a date or null (no end known yet).') };
    if (b.end_utc != null && pd(b.end_utc) < pd(b.start_utc)) return { err: e('hazard.end_utc is before start_utc.') };
    if (typeof b.radius_km !== 'number' || b.radius_km < 0) return { err: e('hazard.radius_km must be a number >= 0.') };
    if (b.center != null && !(typeof b.center.lat === 'number' && typeof b.center.lon === 'number')) return { err: e('hazard.center must be null or {lat, lon}.') };
    if (typeof b.affects_site !== 'boolean') return { err: e('hazard.affects_site must be true or false.') };
  }
  var t = new Date().toISOString().replace(/\.\d+Z$/, 'Z'), out = JSON.parse(JSON.stringify(r)), note = null;
  if (label === 'simulated' && r.label && r.label !== 'simulated') note = 'Record ' + n + ' (' + r.id + '): label "' + r.label + '" changed to simulated because "real mission data" is not ticked.';
  out.label = label === 'simulated' ? 'simulated' : (r.label || 'measured');
  out.source = 'upload'; out.ingested_utc = t; out.available_utc = out.available_utc || t; out.observed_utc = out.observed_utc || null;
  out.provenance = out.provenance || { url: 'upload:' + name, sha256: hash, method: 'JSON upload' };
  return { rec: out, note: note };
}
function parseJSONRecords(text, name, hash, label) {
  var j;
  try { j = JSON.parse(text); } catch (err) { return { recs: [], errs: ['Not valid JSON: ' + err.message] }; }
  var arr = Array.isArray(j) ? j : (j && Array.isArray(j.records) ? j.records : null);
  if (!arr) return { recs: [], errs: ['Expected an array of records or {"records":[...]}.'] };
  var recs = [], errs = [], notes = [];
  arr.forEach(function (r, k) { var c = checkRecord(r, k + 1, label, name, hash); if (c.err) errs.push(c.err); else { recs.push(c.rec); if (c.note) notes.push(c.note); } });
  return { recs: recs, errs: errs, notes: notes };
}

// ---------- image
function formPlace() {
  var sol = solOf($('feSol').value);
  if (sol === null) return Promise.reject(new Error('Enter the sol of the image first (whole number).'));
  if ($('fePlace').value === 'xy') {
    var x = num($('feX').value), y = num($('feY').value);
    if (x === null || y === null) return Promise.reject(new Error('Enter x and y (twin grid cell) or pick "Near Curiosity\'s stop on sol".'));
    if (x < 0 || x > GRID.w || y < 0 || y > GRID.h) return Promise.reject(new Error('x must be 0 to ' + GRID.w + ' and y 0 to ' + GRID.h + '.'));
    return Promise.resolve({ sol: sol, x: x, y: y });
  }
  var ns = solOf($('feNear').value);
  if (ns === null) return Promise.reject(new Error('Enter the stop sol (whole number).'));
  return (twinData ? Promise.resolve(twinData) : fetch('data.json').then(function (r) { if (!r.ok) throw new Error('data.json not found'); return r.json(); }).then(function (d) { twinData = d; return d; }))
    .then(function (d) {
      var w = d.waypoints.filter(function (p) { return p.sol <= ns; });
      if (!w.length) throw new Error('No Curiosity stop on or before sol ' + ns + ' inside the twin area (first one is sol ' + d.waypoints[0].sol + ').');
      var p = w[w.length - 1];
      return { sol: sol, x: p.x, y: p.y, stop: p.sol };
    });
}
function readImage(file, place, label, hash) {
  return new Promise(function (res, rej) {
    var url = URL.createObjectURL(file), im = new Image();
    im.onload = function () {
      var k = Math.min(1, 720 / Math.max(im.width, im.height)), c = document.createElement('canvas');
      c.width = Math.round(im.width * k); c.height = Math.round(im.height * k);
      c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      var rec = base('photo', place.sol, label, null, file.name, hash, 'image upload, resized to 720 px, placed ' + (place.stop ? 'at the stop of sol ' + place.stop : 'by x,y'));
      rec.photo = { file: c.toDataURL('image/jpeg', 0.78), x: place.x, y: place.y, camera: $('feCam').value };
      rec.id = 'photo-upload-' + (hash ? hash.slice(0, 12) : Date.now());
      res(rec);
    };
    im.onerror = function () { URL.revokeObjectURL(url); rej(new Error('The browser could not decode this image.')); };
    im.src = url;
  });
}

// ---------- handle files
function handleFile(file) {
  var name = file.name, lower = name.toLowerCase(), label = $('feReal').checked ? 'measured' : 'simulated';
  if (file.size > 25e6) { say('err', name + ': larger than 25 MB, not read.'); return Promise.resolve(); }
  var isImg = /\.(jpe?g|png)$/.test(lower) || /^image\/(jpeg|png)$/.test(file.type);
  var isCsv = /\.csv$/.test(lower), isJson = /\.json$/.test(lower);
  if (!isImg && !isCsv && !isJson) { say('err', name + ': unsupported file type. Use .csv, .json, .jpg or .png.'); return Promise.resolve(); }
  return file.arrayBuffer().then(function (buf) {
    return sha256(buf).then(function (hash) {
      var pre;
      if (isImg) pre = formPlace().then(function (pl) { return readImage(file, pl, label, hash); }).then(function (r) { return { recs: [r], errs: [] }; });
      else {
        var text = new TextDecoder('utf-8').decode(buf);
        pre = Promise.resolve(isJson ? parseJSONRecords(text, name, hash, label) : parseTable(text, name, hash, label));
      }
      return pre.then(function (p) { return finish(name, p, label); });
    });
  }).catch(function (err) { say('err', name + ': ' + (err && err.message ? err.message : err)); });
}
function finish(name, p, label) {
  p.errs.slice(0, 25).forEach(function (m) { say('err', name + ': ' + m); });
  if (p.errs.length > 25) say('err', name + ': ... and ' + (p.errs.length - 25) + ' more problems.');
  (p.notes || []).forEach(function (m) { say('warn', name + ': ' + m); });
  if (!p.recs.length) { say('err', name + ': nothing imported' + (p.errs.length ? ' (' + p.errs.length + ' problem' + (p.errs.length > 1 ? 's' : '') + ').' : '.')); return; }
  return putAll(p.recs).then(function () {
    p.recs.forEach(function (r) { try { if (chan) chan.postMessage({ record: r }); } catch (e) { /* closed channel */ } });
    say(p.errs.length ? 'warn' : 'ok', name + ': ' + p.recs.length + ' record' + (p.recs.length > 1 ? 's' : '') + ' sent to twin as ' + label.toUpperCase() +
      (p.errs.length ? '; ' + p.errs.length + ' row' + (p.errs.length > 1 ? 's' : '') + ' skipped.' : '.') + ' Stored in this browser; an open twin tab updates now, a closed one reads them when it loads.');
    return refreshUploads();
  }, function (err) { say('err', name + ': could not store records (' + err.message + '). Nothing was sent.'); });
}
function handleFiles(list) { var fs = Array.prototype.slice.call(list || []); return fs.reduce(function (p, f) { return p.then(function () { return handleFile(f); }); }, Promise.resolve()); }

// ---------- rendering
function srcCard(s) {
  var o = pd(s.newest_observed_utc), a = pd(s.newest_available_utc), g = pd(s.last_ingested_utc);
  var st = s.status || 'ok';
  var step = function (title, t, d, sub) {
    return '<div' + (t === null && !sub ? ' class="na"' : '') + '>' + title + '<b>' + (t === null ? (sub || 'none yet') : fmt2(t)) + '</b>' + (d ? '<i>' + d + '</i>' : '') + '</div>';
  };
  var chain =
    step('Observed', o, '') +
    step('Public', a, o !== null && a !== null ? '+' + dur(a - o) : '') +
    step('Ingested', g, a !== null && g !== null ? '+' + dur(g - a) : '', 'no new records') +
    '<div' + (g === null ? ' class="na"' : '') + '>In the twin<b>' + (g === null ? 'nothing to send' : 'on twin load') + '</b>' +
    (g !== null ? '<i>feed.json is read at load</i>' : '') + '</div>';
  var ex = s.extra && s.extra.latency_median_h != null ? ' Median exposure to public: ' + s.extra.latency_median_h + ' h.' : '';
  return '<div class="card ' + esc(st) + '"><div class="nm"><b>' + esc(s.name) + '</b><span class="chip ' + esc(st) + '">' + esc(st.replace('_', ' ')) + '</span></div>' +
    '<div class="mi">' + esc(s.mission) + ' / ' + esc(s.instrument) + '</div>' +
    '<div class="chain" role="group" aria-label="Latency chain for ' + esc(s.name) + '">' + chain + '</div>' +
    '<div class="tl">Checked ' + esc(ago(s.last_checked_utc) || 'never') + '. New items last poll: ' + esc(s.items_new == null ? 0 : s.items_new) + '.' + esc(ex) + '</div>' +
    '<div class="tl">Typical latency: ' + esc(s.typical_latency) + '</div>' +
    (s.note ? '<details><summary>What the last poll found</summary>' + esc(s.note) + '</details>' : '') + '</div>';
}

// ---------- Perseverance and DSN cards (read the status blocks that tools/feeds/m2020_raw.py and gibs_dsn.py wrote)
function srcById(id) { var a = feed && feed.sources ? feed.sources : []; for (var i = 0; i < a.length; i++) if (a[i].id === id) return a[i]; return null; }
function okPath(p) { return typeof p === 'string' && /^feed\/[\w\/.\-]+$/.test(p) ? p : null; }
function okUrl(u, host) { return typeof u === 'string' && u.indexOf('https://' + host + '/') === 0 ? u : null; }
function hrs(h) { return h == null ? 'n/a' : h >= 48 ? (h / 24).toFixed(1) + ' d' : h.toFixed(1) + ' h'; }
function persCard() {
  var p = srcById('m2020_raw'), c = srcById('msl_raw');
  if (!p || !p.extra || !p.extra.thumbs) return '';
  var x = p.extra, cx = c && c.extra ? c.extra : {};
  var figs = x.thumbs.map(function (t) {
    var f = okPath(t.file); if (!f) return '';
    var pg = okUrl(t.page, 'mars.nasa.gov');
    var cap = '<b>Sol ' + esc(t.sol) + '</b> ' + esc(t.camera) + '<br>taken ' + esc(fmt(t.taken_utc)) + '<br>public +' + esc(hrs(t.latency_h));
    return '<figure><img src="' + esc(f) + '" alt="Perseverance ' + esc(t.camera) + ' image, sol ' + esc(t.sol) + '" loading="lazy" width="480" height="320"><figcaption>' +
      (pg ? '<a href="' + esc(pg) + '" target="_blank" rel="noopener">' + cap + '</a>' : cap) + '<br>' + esc(t.credit) + '</figcaption></figure>';
  }).join('');
  return '<div class="xc" id="fePers"><h3>Perseverance (Jezero) today</h3>' +
    '<div class="lat" role="group" aria-label="Latency comparison">' +
    '<span>Perseverance newest: <b>sol ' + esc(x.newest_sol) + '</b>, taken ' + esc(fmt(p.newest_observed_utc)) + ' (' + esc(ago(p.newest_observed_utc)) + ')</span>' +
    '<span>Exposure to public, median of newest ' + esc(x.latency_n) + ': Perseverance <b>' + esc(hrs(x.latency_median_h)) + '</b> vs Curiosity <b>' + esc(hrs(cx.latency_median_h)) + '</b></span></div>' +
    '<div class="xg">' + figs + '</div>' +
    '<p style="margin-top:8px">A second live point-of-view source: newest Navcam and Mastcam-Z frames from the public raw-image feed. Perseverance works in Jezero, not in the Gale twin, so these frames are not placed on the twin map. Credit NASA/JPL-Caltech. ' +
    '<a href="https://mars.nasa.gov/mars2020/multimedia/raw-images/" target="_blank" rel="noopener" style="color:var(--cyan)">Mars Perseverance Raw Images Gallery</a></p></div>';
}
function dsnCard() {
  var g = srcById('gibs_dsn');
  if (!g || !g.extra || !g.extra.sites) return '';
  var figs = g.extra.sites.map(function (t) {
    var f = okPath(t.image); if (!f) return '';
    var wv = okUrl(t.worldview, 'worldview.earthdata.nasa.gov');
    var lay = String(t.layer || '').replace('_CorrectedReflectance_TrueColor', ' true colour');
    return '<figure><img src="' + esc(f) + '" alt="' + esc(t.name) + ' from space on ' + esc(t.date) + ', true colour with IMERG precipitation overlay" loading="lazy" width="480" height="320"><figcaption><b>' + esc(t.name) + '</b><br>' +
      esc(t.date) + ' UTC<br>' + esc(lay) + ' + IMERG precipitation rate<br>rain pixels ' + (t.rain_share == null ? 'n/a' : (t.rain_share * 100).toFixed(1) + '%') + '<br>' +
      (wv ? '<a href="' + esc(wv) + '" target="_blank" rel="noopener">Open in Worldview</a>' : '') + '</figcaption></figure>';
  }).join('');
  return '<div class="xc" id="feDsn"><h3>Earth side: DSN ground stations (NASA Worldview/GIBS)</h3>' +
    '<div class="xg" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr))">' + figs + '</div>' +
    '<p style="margin-top:8px">Mars-to-Earth links end at these three Deep Space Network complexes, and heavy cloud or rain at a site degrades high-frequency links. This is imagery for context on the Earth end of the link; MARSWALK does not model link margins. ' +
    'Imagery: NASA GIBS (the service behind <a href="https://worldview.earthdata.nasa.gov/" target="_blank" rel="noopener" style="color:var(--cyan)">NASA Worldview</a>), roughly 540 by 440 km around each site; site coordinates from the JPL DSN Radio Astronomy User Guide. ' +
    'Colored overlay: precipitation rate. Last fetched ' + esc(fmt(g.last_checked_utc)) + '.</p></div>';
}
function summary(r) {
  if (r.type === 'rad') return r.rad.uGy_h + ' uGy/h';
  if (r.type === 'weather') return r.weather.min_C + ' to ' + r.weather.max_C + ' C' + (r.weather.pressure_Pa != null ? ', ' + r.weather.pressure_Pa + ' Pa' : '');
  if (r.type === 'photo') return r.photo.camera + ' at x ' + r.photo.x + ', y ' + r.photo.y;
  if (r.type === 'hazard') return r.hazard.kind + (r.hazard.affects_site ? ' affects site' : ' no site effect') + ' ' + fmt(r.hazard.start_utc).slice(0, 10) + ' to ' + fmt(r.hazard.end_utc).slice(0, 10);
  return '';
}
function render() {
  var srcs = feed && feed.sources ? feed.sources : [];
  $('feSrc').innerHTML = srcs.length ? srcs.map(srcCard).join('') :
    '<div class="none">No feed.json yet. Run <code>python tools/ingest.py --once</code> in the repo to fetch NASA data; uploads below work without it.</div>';
  $('feEx').innerHTML = persCard() + dsnCard();
  $('feGen').textContent = feed ? 'feed.json written ' + fmt(feed.generated_utc) + ' (' + ago(feed.generated_utc) + ')' : 'feed.json not found';
  var seen = {}, rows = [];
  (feed && feed.records ? feed.records : []).concat(uploads).forEach(function (r) { seen[r.id] = r; });
  Object.keys(seen).forEach(function (k) { rows.push(seen[k]); });
  rows.sort(function (a, b) { return (pd(b.ingested_utc) || 0) - (pd(a.ingested_utc) || 0) || b.sol - a.sol; });
  $('feCnt').textContent = '(' + rows.length + (rows.length > 120 ? ', newest 120 shown' : '') + ')';
  $('feRec').innerHTML = rows.length ? rows.slice(0, 120).map(function (r) {
    var up = r.source === 'upload';
    return '<tr><td><span class="tg ' + esc(r.label) + '">' + esc(String(r.label).toUpperCase()) + '</span></td><td>' + esc(r.type) + '</td><td>' + esc(r.source) + '</td><td>' + esc(r.sol) + '</td><td>' + esc(fmt(r.observed_utc)) +
      '</td><td class="sm">' + esc(summary(r)) + '</td><td>' + (acked[r.id] ? 'confirmed by twin' : (up ? 'sent ' + esc(ago(r.ingested_utc)) : 'via feed.json')) + '</td></tr>';
  }).join('') : '<tr><td colspan="7" class="none">No records yet.</td></tr>';
  $('feStore').textContent = uploads.length + ' upload' + (uploads.length === 1 ? '' : 's') + ' stored in this browser';
}
function loadFeed() {
  return fetch('feed.json', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
    .then(function (j) { feed = j && j.sources ? j : null; render(); });
}
function refreshUploads() {
  return allRecs().then(function (a) { uploads = a.filter(function (r) { return r.source === 'upload'; }); render(); }, function () { uploads = []; render(); });
}

function wire() {
  var drop = $('feDrop'), file = $('feFile');
  file.addEventListener('change', function () { handleFiles(file.files).then(function () { file.value = ''; }); });
  ['dragenter', 'dragover'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
  ['dragleave', 'drop'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
  drop.addEventListener('drop', function (e) { if (e.dataTransfer && e.dataTransfer.files) handleFiles(e.dataTransfer.files); });
  $('fePlace').addEventListener('change', function () {
    var near = $('fePlace').value === 'near';
    $('feXl').hidden = $('feYl').hidden = near; $('feNl').hidden = !near;
  });
  $('feRefresh').addEventListener('click', function () { loadFeed(); refreshUploads(); });
  $('feClear').addEventListener('click', function () { clearUploads().then(function () { say('ok', 'Your uploads were removed from this browser. Open twin tabs keep what they already received until reloaded.'); return refreshUploads(); }, function (e) { say('err', 'Could not clear: ' + e.message); }); });
  try {
    chan = new BroadcastChannel('marswalk-feed');
    chan.onmessage = function (e) {
      var m = e.data || {}, ids = m.ack ? [].concat(m.ack) : [];
      if (ids.length) { ids.forEach(function (i) { acked[i] = true; }); render(); }
    };
  } catch (err) { chan = null; say('warn', 'BroadcastChannel is not available: records are stored but an open twin tab will only see them after a reload.'); }
}

function init() {
  css(); build(); wire(); render();
  loadFeed(); refreshUploads();
  setInterval(function () { if (!document.hidden) { loadFeed(); render(); } }, 60000);
  window.__feed = { handleFiles: handleFiles, records: function () { return uploads.slice(); }, feed: function () { return feed; } };
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
