import sys; import os as _os; sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np
from phase4.horizon import horizon_angles, sky_factors
res = 1.0117467945795
# flat
flat = np.zeros((900, 900)); r = np.array([450.5, 300.5]); c = np.array([450.5, 600.5])
h, tr = horizon_angles(flat, r, c, res, max_m=300, verbose=False)
print("flat horizon range", h.min(), h.max(), "(0 = nothing seen beyond 300 m grid)")
# large flat to see the -atan(1.7/d) behaviour
flat = np.zeros((2400, 2400)); h, tr = horizon_angles(flat, np.array([1200.0]), np.array([1200.0]), res, verbose=False)
print("flat 2km: raw horizon", h.min(), h.max(), "sky_view", sky_factors(h)[0], sky_factors(h)[1], "truncated", tr.mean())
# pit: inverted cone depth 30 m, rim radius 100 m, at centre
n = 800; yy, xx = np.mgrid[0:n, 0:n]; rr = np.hypot(yy - 400.0, xx - 400.0) * res
pit = np.where(rr < 100, 30 * rr / 100, 30.0)
h, tr = horizon_angles(pit, np.array([400.0]), np.array([400.0]), res, max_m=400, verbose=False)
an = np.degrees(np.arctan((30 - 1.7) / 100))
print(f"pit: analytic {an:.3f}  computed min {h.min():.3f} max {h.max():.3f}")
sv, ss = sky_factors(h); h0 = np.radians(an)
print(f"pit sky_view {sv[0]:.4f} analytic {np.cos(h0)**2:.4f}; sky_solid {ss[0]:.4f} analytic {1-np.sin(h0):.4f}")
# wall: north wall 20 m high at 150 m (row decreasing)
wall = np.zeros((900, 900)); wall[:450 - int(150 / res)] = 20.0
h, tr = horizon_angles(wall, np.array([450.0]), np.array([450.0]), res, max_m=400, verbose=False)
print(f"wall north: computed {h[0,0]:.3f} analytic approx {np.degrees(np.arctan(18.3/ (150))):.3f}, east {h[8,0]:.3f}, south {h[16,0]:.3f}")
