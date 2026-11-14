import sys, glob
from PIL import Image
d, out = sys.argv[1], sys.argv[2]; pat = sys.argv[3] if len(sys.argv) > 3 else "walk_*.png"
fs = sorted(glob.glob(d + "/" + pat)); ims = [Image.open(f) for f in fs]
w, h = ims[0].size; cols = 4; rows = (len(ims) + cols - 1) // cols
m = Image.new("RGB", (cols * w, rows * h), "white")
for i, im in enumerate(ims): m.paste(im, ((i % cols) * w, (i // cols) * h))
m.save(out); print(m.size)
