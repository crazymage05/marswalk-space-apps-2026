import sys, os, random, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from phase4.bench.core import *
g = C.load_grid(); p = A.get_profile('nominal'); ctx = Ctx(g, p); W = ctx.W
random.seed(1)
for dr, dc in [(1, 0), (1, 1), (1, 2), (2, 1), (0, 5), (3, 3), (-4, 7), (7, -3), (5, -5), (2, 4), (0, -3)]:
    cells, sides, chain, L = ctx.pattern(dr, dc); assert abs(sum(c[1] for c in cells) - 1) < 1e-12
    allc = {c[0] for c in cells} | {s[0] for s in sides}; n = 4000
    for k in range(n + 1):
        t = k / n; y = 0.5 + t * dr; x = 0.5 + t * dc
        for ey in (0, 1e-9, -1e-9):
            for ex in (0, 1e-9, -1e-9):
                assert int((y + ey) // 1) * W + int((x + ex) // 1) in allc, (dr, dc, t)
print('pattern: every point of dense-sampled segments lies in a listed cell; fractions sum to 1')
bl = ctx.bl; nb = 0
for _ in range(3000):
    u = random.randrange(100000, 300000); dr, dc = random.choice([(-1, 0), (0, 1), (1, 1), (-1, -1), (1, -1), (-1, 1), (1, 0), (0, -1)])
    v = u + dr * W + dc
    if bl[u] or bl[v] or u % W in (0, W - 1): continue
    c, b = ctx.seg(u, v)
    if dr and dc and (bl[u + dr * W] or bl[u + dc]): assert b; continue
    assert not b
    d = ctx.cm * (math.sqrt(2) if dr and dc else 1)
    ref = d * 0.5 * (ctx.mu[u] + ctx.mu[v]) + ctx.clw * max(ctx.el[v] - ctx.el[u], 0)
    assert abs(c - ref) < 1e-6 * ref, (c, ref); nb += 1
print('lattice edge cost == astar.py formula on', nb, 'random edges (and corner rule matches)')
offs = [(0, 1), (1, 1), (1, 2), (-2, 1), (2, -1), (-1, -2)]
E = ctx.edge_arrays(offs)
for (dr, dc), Ea in zip(offs, E):
    for _ in range(800):
        r = random.randrange(3, ctx.H - 3); c = random.randrange(3, W - 3); u = r * W + c; v = u + dr * W + dc
        cst, b = ctx.seg(u, v); ref = INF if (b or ctx.bl[u]) else cst
        assert Ea[r, c] == ref or abs(Ea[r, c] - ref) < 1e-6 * ref, (dr, dc, Ea[r, c], ref)
print('vectorised edge arrays == scalar seg()')
