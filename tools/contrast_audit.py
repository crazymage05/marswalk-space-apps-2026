"""Contrast audit of the MARSWALK pages in both themes (WCAG 2.x contrast ratio).

usage: python tools/contrast_audit.py [port]        (serve demo/twin on the port first)
For index.html, twin.html?notour and mission.html, in the day and dusk themes at 1440 and 400 px: every visible element
with its own text is measured against its effective background (semi-transparent backgrounds composited down the
ancestor chain). Text over an image, gradient or canvas is counted as "on image" and not scored. Threshold: 4.5:1,
or 3:1 for large text (>= 24 px, or >= 18.66 px bold). Writes runs/twin_check/contrast_audit.json.
"""
import json, os, sys
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
JS = r"""() => {
  const P = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(',').map(x => parseFloat(x));
    return [v[0], v[1], v[2], v.length > 3 ? v[3] : 1]; };
  const lum = c => { const f = x => { x /= 255; return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const over = (top, bot) => { const a = top[3]; return [top[0] * a + bot[0] * (1 - a), top[1] * a + bot[1] * (1 - a), top[2] * a + bot[2] * (1 - a), 1]; };
  function bg(el) {           // composite backgrounds from el down to the root; null if an image/gradient/canvas is under the text
    const stack = [];
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
      if (e.tagName === 'CANVAS' || e.tagName === 'IMG') return null;
      const c = P(cs.backgroundColor); if (c && c[3] > 0) { stack.push(c); if (c[3] >= 0.999) break; }
      if (e.classList && (e.classList.contains('view'))) return null;   // over the 3D canvas
    }
    let out = [255, 255, 255, 1]; for (let i = stack.length - 1; i >= 0; i--) out = over(stack[i], out); return out;
  }
  const res = { n: 0, onImage: 0, fails: [] };
  document.querySelectorAll('body *').forEach(el => {
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (!own) return; const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (r.width < 1 || r.height < 1 || cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) return;
    if (el.closest('[hidden]') || el.closest('.sr') || el.closest('.sr-only')) return;
    const b = bg(el); if (!b) { res.onImage++; return; }
    let fg = P(cs.color); if (!fg) return; if (fg[3] < 1) fg = over(fg, b);
    const L1 = lum(fg), L2 = lum(b), cr = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700, large = size >= 24 || (size >= 18.66 && bold);
    res.n++; if (cr < (large ? 3 : 4.5)) res.fails.push({ cr: +cr.toFixed(2), text: el.textContent.trim().slice(0, 50), tag: el.tagName.toLowerCase(),
      cls: (el.className && el.className.baseVal === undefined ? el.className : '').toString().slice(0, 40), id: el.id || '', fg: cs.color, bg: 'rgb(' + b.slice(0, 3).map(Math.round) + ')' });
  });
  return res; }"""
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for page in ("index.html", "twin.html?notour", "mission.html"):
        for theme in ("day", "dusk"):
            for w, h in ((1440, 900), (400, 860)):
                ctx = b.new_context(viewport={"width": w, "height": h}); pg = ctx.new_page()
                pg.add_init_script(f"try{{localStorage.setItem('mw_theme','{theme}')}}catch(e){{}}")
                pg.goto(f"http://127.0.0.1:{port}/{page}", wait_until="load")
                if "twin" in page: pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=180000); pg.click("#btnDemo")
                pg.wait_for_timeout(2500)
                r = pg.evaluate(JS); key = f"{page.split('?')[0]} {theme} {w}"; out[key] = r
                print(f"{key:28s} text elements {r['n']:4d}  on image {r['onImage']:3d}  below threshold {len(r['fails'])}")
                ctx.close()
    b.close()
json.dump(out, open(os.path.join(ROOT, "runs", "twin_check", "contrast_audit.json"), "w"), indent=1)
fails = {k: v["fails"] for k, v in out.items() if v["fails"]}
for k, v in fails.items():
    for f in v[:6]: print("  ", k, "|", f["cr"], f["tag"], f["id"] or f["cls"], "|", f["text"], "|", f["fg"], "on", f["bg"])
