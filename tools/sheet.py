"""Contact sheet of a walk_shots run (or two runs side by side).  usage: python tools/sheet.py <name> [<name2>]"""
import os, sys
from PIL import Image, ImageDraw
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
names = sys.argv[1:]; keys = [f"{p}_{t}" for p in ("start", "mid", "end") for t in ("0845", "1200", "1630")]
cw = 420; ims = []
for k in keys:
    for n in names:
        im = Image.open(os.path.join(ROOT, "runs", "twin_check", n, k + ".png")).convert("RGB"); im.thumbnail((cw, cw)); ims.append((f"{n} {k}", im))
cols = 3 * len(names); ch = max(i.size[1] for _, i in ims) + 16; rows = (len(ims) + cols - 1) // cols
s = Image.new("RGB", (cols * cw, rows * ch), "white"); d = ImageDraw.Draw(s)
for i, (lab, im) in enumerate(ims):
    x, y = (i % cols) * cw, (i // cols) * ch; s.paste(im, (x, y + 14)); d.text((x + 3, y + 1), lab, fill="black")
out = os.path.join(ROOT, "runs", "twin_check", "sheet_" + "_vs_".join(names) + ".jpg"); s.save(out, quality=88); print(out)
