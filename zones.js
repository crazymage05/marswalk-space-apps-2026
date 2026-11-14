/* Zone grid helper shared by twin.html and mission.html (one script tag each).
 *
 * The study area is split into square zones of 200 m. Columns are lettered A, B, C ... from west to east (after Z: AA, AB ...),
 * rows are numbered 1, 2, 3 ... from north to south, so "C4" is the third column from the west and the fourth row from the north.
 * A 4.047 m cell belongs to the zone that holds its centre: zone column = floor((col + 0.5) / (200 / cellM)), same for rows.
 * 200 m is 49.42 cells, so zone edges fall between cells at fractional positions; the last column and row are cut off by the
 * edge of the map and are narrower than 200 m (zoneWidthM / zoneHeightM give the real size).
 *
 *   MWZones.setGrid(w, h, cellM)   call once the grid size is known (twin: data.json grid; mission: mission_log grid)
 *   MWZones.label(col, row)        "C4" for the cell at grid column col, row row
 *   MWZones.labelOfCell(i)         the same for a flat cell index (row * w + col)
 *   MWZones.name(zc, zr)           "C4" for the zone at zone column zc, zone row zr (both 0-based)
 *   MWZones.id(zc, zr), .zc(id), .zr(id), .count, .cols, .rows, .size   zone index = zr * cols + zc
 *   MWZones.edge(k)                position of the k-th zone boundary in cells, from the map's west or north edge
 *   MWZones.parse("C4")            {zc, zr} or null
 */
(function () {
  "use strict";
  const Z = window.MWZones = { SIZE_M: 200, w: 0, h: 0, cellM: 0, per: 0, cols: 0, rows: 0, count: 0, ready: false };
  const colName = i => { let s = ""; i++; while (i > 0) { const r = (i - 1) % 26; s = String.fromCharCode(65 + r) + s; i = (i - r - 1) / 26; } return s; };
  let zcOf = null, zrOf = null;
  Z.setGrid = (w, h, cellM) => {
    Z.w = w; Z.h = h; Z.cellM = cellM; Z.per = Z.SIZE_M / cellM;
    zcOf = new Uint16Array(w); zrOf = new Uint16Array(h);
    for (let c = 0; c < w; c++) zcOf[c] = Math.floor((c + 0.5) / Z.per);
    for (let r = 0; r < h; r++) zrOf[r] = Math.floor((r + 0.5) / Z.per);
    Z.cols = zcOf[w - 1] + 1; Z.rows = zrOf[h - 1] + 1; Z.count = Z.cols * Z.rows; Z.ready = true;
    return Z;
  };
  Z.colName = colName;
  Z.name = (zc, zr) => colName(zc) + (zr + 1);
  Z.label = (col, row) => {
    if (!Z.ready || col < 0 || row < 0 || col >= Z.w || row >= Z.h) return "";
    return Z.name(zcOf[col | 0], zrOf[row | 0]);
  };
  Z.colZone = c => zcOf[c];
  Z.rowZone = r => zrOf[r];
  Z.labelOfCell = i => Z.label(i % Z.w, Math.floor(i / Z.w));
  Z.id = (zc, zr) => zr * Z.cols + zc;
  Z.zc = id => id % Z.cols;
  Z.zr = id => Math.floor(id / Z.cols);
  Z.ofCell = i => Z.id(zcOf[i % Z.w], zrOf[Math.floor(i / Z.w)]);
  Z.edge = k => k * Z.per;
  Z.zoneWidthM = zc => Math.min(Z.SIZE_M, Z.w * Z.cellM - zc * Z.SIZE_M);
  Z.zoneHeightM = zr => Math.min(Z.SIZE_M, Z.h * Z.cellM - zr * Z.SIZE_M);
  Z.parse = s => {
    const m = /^([A-Za-z]{1,2})(\d{1,3})$/.exec(String(s || "").trim()); if (!m) return null;
    let zc = 0; for (const ch of m[1].toUpperCase()) zc = zc * 26 + (ch.charCodeAt(0) - 64);
    const zr = +m[2] - 1; zc -= 1;
    return zc >= 0 && zr >= 0 && zc < Z.cols && zr < Z.rows ? { zc, zr } : null;
  };
  // compact trail of the zones a list of cells passes through, e.g. "C2 > C3 > D3 > D4"; long trails keep the ends
  Z.trail = (cells, max = 14) => {
    const seq = []; let prev = -1;
    for (const c of cells) { const id = Z.ofCell(c); if (id !== prev) { seq.push(id); prev = id; } }
    const names = seq.map(id => Z.name(Z.zc(id), Z.zr(id)));
    const txt = names.length > max ? names.slice(0, max - 3).concat(["...", names[names.length - 2], names[names.length - 1]]).join(" > ") : names.join(" > ");
    return { names, text: txt };
  };
})();
