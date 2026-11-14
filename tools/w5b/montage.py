"""python tools/w5b/montage.py dir out.png tagA tagB view frames  -> rows tagA (before) over tagB (after)"""
import sys
from PIL import Image, ImageDraw
d, out, ta, tb, view = sys.argv[1:6]; fr = sys.argv[6].split(',')
ims = [[Image.open(f"{d}/{t}_{view}_{int(f):02d}.png").convert("RGB") for f in fr] for t in (ta, tb)]
w, h = ims[0][0].size; M = Image.new("RGB", (w * len(fr), h * 2))
for r, row in enumerate(ims):
    for c, im in enumerate(row): M.paste(im, (c * w, r * h)); ImageDraw.Draw(M).text((c * w + 6, r * h + 6), f"{(ta, tb)[r]} f{fr[c]}", fill=(255, 255, 0))
M.save(out)
