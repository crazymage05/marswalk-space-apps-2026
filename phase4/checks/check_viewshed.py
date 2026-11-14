import sys; import os as _os; sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np, rasterio
from scipy.ndimage import map_coordinates
from phase4 import visibility as v
dtm = rasterio.open("data/processed/roi/elevation_m.tif").read(1).astype(np.float64)
f = np.where(np.isfinite(dtm), dtm, -1e9); RES=v.RES
def los(r, c, tr, tc, eye=1.7):
    r0, c0 = 4*r+1.5, 4*c+1.5; r1, c1 = 4*tr+1.5, 4*tc+1.5
    L = np.hypot(r1-r0, c1-c0)*RES; n = int(L/0.5)
    t = np.arange(1, n+1)/n
    rr = r0+(r1-r0)*t; cc = c0+(c1-c0)*t; d = L*t
    z = map_coordinates(f, [rr, cc], order=1)
    z0 = map_coordinates(f, [[r0],[c0]], order=1)[0]+eye
    if z[-1] < -1e8: return False
    a = (z - d*d/(2*v.R_MARS) - z0)/d
    return a[-1] >= a[:-1].max() - 1e-6 if n > 1 else True
rng = np.random.default_rng(1)
for (r,c) in [(366,292),(100,120),(600,450)]:
    m = v.visible_from(r,c); agree=tot=0; fp=fn=0
    for _ in range(250):
        ang=rng.uniform(0,2*np.pi); rad=rng.uniform(3,73)
        tr=int(round(r-rad*np.cos(ang))); tc=int(round(c+rad*np.sin(ang)))
        if not(0<=tr<732 and 0<=tc<585): continue
        t=los(r,c,tr,tc); tot+=1; agree+= (t==m[tr,tc]); fp+= (m[tr,tc] and not t); fn += (t and not m[tr,tc])
    print((r,c),"agree",agree,"/",tot,"false-visible",fp,"false-hidden",fn, "visible frac", m[max(r-74,0):r+75, max(c-74,0):c+75].mean().round(2))
# flat check
v._dtm = np.zeros((2928,2340),np.float32); m=v.visible_from(366,292); 
rr,cc=np.mgrid[:732,:585]; inside=np.hypot(rr-366,cc-292)*4.047<290
print("flat: all cells within 290 m visible:", m[inside].all(), "visible beyond 310 m:", m[np.hypot(rr-366,cc-292)*4.047>320].any())
