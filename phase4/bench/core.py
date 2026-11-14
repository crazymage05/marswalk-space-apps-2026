"""Benchmark core: shared cost model (identical to phase4/astar.py), exact cell-line traversal, evaluator,
independent hard-limit checker. Does not modify phase4 modules."""
import math, sys, os
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
from phase4 import astronaut as A, costs as C, astar as AS, safety_validator as SV
from scipy import ndimage

INF = float("inf")


class Ctx:
    """Holds grid arrays as flat lists. Works for the real grid and for synthetic dicts (same keys)."""
    def __init__(self, grid, profile, blocked=None, mult=None):
        self.grid, self.profile = grid, profile
        self.H, self.W, self.cm = grid["height"], grid["width"], grid["cell_m"]
        self.blocked = C.hard_blocked(grid, profile) if blocked is None else blocked
        self.mult = C.cell_cost(grid, profile).astype(np.float64) if mult is None else mult
        self.el2 = np.nan_to_num(grid["elevation_m"]).astype(np.float64)
        self.bl = self.blocked.ravel().tolist(); self.mu = self.mult.ravel().tolist(); self.el = self.el2.ravel().tolist()
        self.clw = profile.climb_weight
        self._pat = {}

    def pattern(self, dr, dc):
        """Exact traversal of the straight segment between two cell centres. Returns
        cells  : tuple of (flat offset, fraction of the segment length inside that cell, dr, dc)
        sides  : zero-length corner-touched cells (still checked for blocking), as (flat, dr, dc)
        chain  : cells visited in order (flat offsets, dr, dc), for climb
        L      : segment length in metres.   Amanatides-Woo traversal with integer arithmetic (ties are exact)."""
        key = (dr, dc)
        if key in self._pat: return self._pat[key]
        W = self.W
        ar, ac = abs(dr), abs(dc); sr = 1 if dr > 0 else -1; sc = 1 if dc > 0 else -1
        if ar == 0: T = 2 * ac; tmr = dlr = INF; tmc, dlc = 1, 2
        elif ac == 0: T = 2 * ar; tmc = dlc = INF; tmr, dlr = 1, 2
        else: T = 2 * ar * ac; tmc, dlc, tmr, dlr = ar, 2 * ar, ac, 2 * ac
        cur = (0, 0); tp = 0; cells = []; chain = [(0, 0, 0)]; sides = []
        while cur != (dr, dc):
            t = min(tmc, tmr); cells.append((cur[0] * W + cur[1], (t - tp) / T, cur[0], cur[1])); tp = t
            if tmc == tmr:
                for s in ((cur[0] + sr, cur[1]), (cur[0], cur[1] + sc)): sides.append((s[0] * W + s[1], s[0], s[1]))
                cur = (cur[0] + sr, cur[1] + sc); tmc += dlc; tmr += dlr
            elif tmc < tmr: cur = (cur[0], cur[1] + sc); tmc += dlc
            else: cur = (cur[0] + sr, cur[1]); tmr += dlr
            chain.append((cur[0] * W + cur[1], cur[0], cur[1]))
        cells.append((cur[0] * W + cur[1], (T - tp) / T, cur[0], cur[1]))
        res = (tuple(cells), tuple(sides), tuple(chain), self.cm * math.hypot(dr, dc))
        self._pat[key] = res
        return res

    def seg(self, a, b):
        """(cost, blocked) of the straight segment a->b (flat indices): length x integral of the cell multiplier +
        climb_weight x sum of positive elevation steps between visited cells. For lattice moves this equals astar.py."""
        W = self.W
        cells, sides, chain, L = self.pattern(b // W - a // W, b % W - a % W)
        bl, mu, el = self.bl, self.mu, self.el
        blk = False; s = 0.0
        for off, fr, _, _ in cells:
            i = a + off
            if bl[i]: blk = True
            s += fr * mu[i]
        if not blk:
            for off, _, _ in sides:
                if bl[a + off]: blk = True; break
        climb = 0.0; prev = el[a]
        for off, _, _ in chain[1:]:
            e = el[a + off]
            if e > prev: climb += e - prev
            prev = e
        return L * s + self.clw * climb, blk

    def seg_cells(self, a, b):
        W = self.W
        cells, sides, _, _ = self.pattern(b // W - a // W, b % W - a % W)
        return [a + c[0] for c in cells] + [a + s[0] for s in sides]

    def edge_arrays(self, offsets):
        """Vectorised segment cost for each (dr,dc) offset from every cell: float64 (H,W), inf if the swept cells are
        blocked / outside the grid / the source is blocked."""
        P = 3; H, W = self.H, self.W
        mu = np.pad(self.mult, P, constant_values=1.0); el = np.pad(self.el2, P, mode="edge")
        bl = np.pad(self.blocked, P, constant_values=True)
        def sh(a, dr, dc): return a[P + dr:P + dr + H, P + dc:P + dc + W]
        out = []
        for dr, dc in offsets:
            cells, sides, chain, L = self.pattern(dr, dc)
            s = np.zeros((H, W)); b = self.blocked.copy()
            for _, fr, r, c in cells: s += fr * sh(mu, r, c); b |= sh(bl, r, c)
            for _, r, c in sides: b |= sh(bl, r, c)
            climb = np.zeros((H, W)); prev = sh(el, 0, 0)
            for _, r, c in chain[1:]:
                e = sh(el, r, c); climb += np.maximum(e - prev, 0); prev = e
            cost = L * s + self.clw * climb
            cost[b] = INF; out.append(cost)
        return out


# ---------------------------------------------------------------- independent checks
def independent_blocked(grid, profile):
    """Own re-derivation of the hard limits from raw layers (does not call costs.hard_blocked)."""
    sl, ro, vf = grid["slope_max_deg"], grid["rough_max_m"], grid["valid_frac"]
    b = np.zeros(sl.shape, bool)
    b |= np.nan_to_num(sl, nan=1e9) > profile.max_slope_deg
    b |= np.nan_to_num(ro, nan=1e9) > profile.rough_max_m
    b |= np.nan_to_num(vf, nan=-1.0) < profile.valid_frac_min
    b |= np.isnan(grid["elevation_m"])
    return b


def check_path_hard(grid, profile, vertices, blocked_ind=None, step=0.02):
    """Densely sample every polyline segment (every 0.02 cell; each sample is also tested nudged by +-1e-7 cell so a
    sample lying on a cell edge/corner tests every adjoining cell). Returns number of samples inside a hard-blocked
    cell. Independent of the pattern code used by the planners."""
    bi = independent_blocked(grid, profile) if blocked_ind is None else blocked_ind
    H, W = bi.shape; bad = 0
    pts = [divmod(v, W) for v in vertices]
    if len(pts) == 1: return int(bi[pts[0]])
    for (r0, c0), (r1, c1) in zip(pts[:-1], pts[1:]):
        n = max(2, int(math.hypot(r1 - r0, c1 - c0) / step) + 1)
        t = np.linspace(0, 1, n)
        y = r0 + 0.5 + t * (r1 - r0); x = c0 + 0.5 + t * (c1 - c0)
        for ey in (0.0, 1e-7, -1e-7):
            for ex in (0.0, 1e-7, -1e-7):
                yi = np.floor(y + ey).astype(int); xi = np.floor(x + ex).astype(int)
                if (yi < 0).any() or (xi < 0).any() or (yi >= H).any() or (xi >= W).any(): return 10 ** 6
                bad += int(bi[yi, xi].sum())
    return bad


def bresenham(r0, c0, r1, c1):
    out = []; dr, dc = abs(r1 - r0), abs(c1 - c0); sr = 1 if r1 > r0 else -1; sc = 1 if c1 > c0 else -1
    err = dc - dr; r, c = r0, c0
    while True:
        out.append((r, c))
        if r == r1 and c == c1: break
        e2 = 2 * err
        if e2 > -dr: err -= dr; c += sc
        if e2 < dc: err += dc; r += sr
    return out


def rasterize(vertices, W):
    """Adjacent-cell (Chebyshev step 1) rasterisation of a polyline for safety_validator.validate."""
    cells = []
    for a, b in zip(vertices[:-1], vertices[1:]):
        (ra, ca), (rb, cb) = divmod(a, W), divmod(b, W)
        seg = bresenham(ra, ca, rb, cb)
        cells += [r * W + c for r, c in (seg if not cells else seg[1:])]
    return cells if cells else list(vertices)


# ---------------------------------------------------------------- metrics
def path_metrics(ctx, vertices):
    """vertices: flat cell indices of the polyline (any-angle or lattice). Time/energy use the astronaut model with
    sub-steps of <= 1 cell and bilinear elevation; identical procedure for every algorithm."""
    grid, prof, W, cm = ctx.grid, ctx.profile, ctx.W, ctx.cm
    cost = 0.0; maxslope = 0.0; dists = []; grades = []; planar = 0.0
    sl = np.nan_to_num(grid["slope_max_deg"]).ravel()
    for a, b in zip(vertices[:-1], vertices[1:]):
        c, _ = ctx.seg(a, b); cost += c
        cs = ctx.seg_cells(a, b); maxslope = max(maxslope, float(sl[cs].max()))
        (ra, ca), (rb, cb) = divmod(a, W), divmod(b, W)
        L = math.hypot(rb - ra, cb - ca); n = max(1, math.ceil(L - 1e-9))
        rr = np.linspace(ra, rb, n + 1); cc = np.linspace(ca, cb, n + 1)
        z = ndimage.map_coordinates(ctx.el2, [rr, cc], order=1)
        pdn = cm * L / n; planar += cm * L
        for k in range(n):
            dz = float(z[k + 1] - z[k]); dists.append(math.hypot(pdn, dz)); grades.append(dz / pdn)
    r = A.route_resources(prof, dists, grades)
    pts = [divmod(v, W) for v in vertices]
    hd = [math.degrees(math.atan2(q[0] - p[0], q[1] - p[1])) for p, q in zip(pts[:-1], pts[1:])]
    turns = []
    for h0, h1 in zip(hd[:-1], hd[1:]):
        d = abs((h1 - h0 + 180) % 360 - 180)
        if d > 1e-6: turns.append(d)
    return dict(length_m=float(sum(dists)), planar_m=planar, cost=cost, time_s=r["time_s"], energy_kj=r["energy_kj"],
                dose_uGy=r["dose_uGy"], max_slope_deg=maxslope, turns_gt30=sum(1 for d in turns if d > 30.0001),
                total_turn_deg=float(sum(turns)), n_vertices=len(vertices))


def validate_path(ctx, vertices):
    cells = rasterize(vertices, ctx.W)
    v = SV.validate(cells, ctx.grid, ctx.profile)
    return v["ok"], v["summary"].get("checks_failed", [])
