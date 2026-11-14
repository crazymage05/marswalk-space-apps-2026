"""Planners for the benchmark. All use core.Ctx: same cost model, same hard limits as phase4/astar.py."""
import heapq, math, time
from array import array
import numpy as np
from .core import Ctx, INF

N8 = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
KN = [(-2, -1), (-2, 1), (-1, 2), (1, 2), (2, 1), (2, -1), (1, -2), (-1, -2)]
N16 = N8 + KN


def edge_tables(ctx, offsets):
    return [array("d", e.ravel().tolist()) for e in ctx.edge_arrays(offsets)]


def grid_astar(ctx, tables, offsets, start, goal, hmode="euclid", hscale=1.0):
    """Generic lattice A* over precomputed edge-cost tables (inf = not allowed). hmode: 'euclid' | 'octile' | 'zero'.
    hscale multiplies cm*distance (used for weighted objectives). Returns dict(route, cost, expanded)."""
    W, H, cm = ctx.W, ctx.H, ctx.cm
    gr, gc = divmod(goal, W); S2 = math.sqrt(2) - 1
    if hmode == "euclid": h = lambda r, c: hscale * cm * math.hypot(r - gr, c - gc)
    elif hmode == "octile":
        def h(r, c):
            dr, dc = abs(r - gr), abs(c - gc); return hscale * cm * (max(dr, dc) + S2 * min(dr, dc))
    else: h = lambda r, c: 0.0
    sr, sc = divmod(start, W)
    dist = {start: 0.0}; parent = {start: -1}; done = set()
    pq = [(h(sr, sc), start)]; exp = 0
    nbo = [(dr * W + dc, dr, dc, t) for (dr, dc), t in zip(offsets, tables)]
    while pq:
        _, u = heapq.heappop(pq)
        if u in done: continue
        done.add(u); exp += 1
        if u == goal: break
        du = dist[u]; r, c = divmod(u, W)
        for off, dr, dc, t in nbo:
            w = t[u]
            if w == INF: continue
            v = u + off
            if v in done: continue
            nd = du + w
            if nd < dist.get(v, INF):
                dist[v] = nd; parent[v] = u
                heapq.heappush(pq, (nd + h(r + dr, c + dc), v))
    if goal not in done: return dict(route=[], cost=INF, expanded=exp)
    route = []; u = goal
    while u != -1: route.append(u); u = parent[u]
    route.reverse()
    return dict(route=route, cost=dist[goal], expanded=exp)


def lazy_theta(ctx, start, goal):
    """Lazy Theta* (Nash et al. 2010) on the 8-connected lattice; line-of-sight uses the exact cell traversal (every crossed
    cell, plus corner-touched cells, must be unblocked); edge cost = exact integral of the cell multiplier along the segment
    + climb term (ctx.seg). Heuristic: Euclidean distance (admissible since multiplier >= 1)."""
    W, H, cm = ctx.W, ctx.H, ctx.cm
    bl, seg = ctx.bl, ctx.seg
    gr, gc = divmod(goal, W)
    def h(u):
        r, c = divmod(u, W); return cm * math.hypot(r - gr, c - gc)
    g = {start: 0.0}; par = {start: start}; closed = set(); pq = [(h(start), start)]
    def nbrs(u):
        r, c = divmod(u, W)
        for dr, dc in N8:
            nr, nc = r + dr, c + dc
            if 0 <= nr < H and 0 <= nc < W and not bl[nr * W + nc]: yield nr * W + nc
    while pq:
        _, s = heapq.heappop(pq)
        if s in closed: continue
        p = par[s]
        if p != s:
            _, blk = seg(p, s)
            if blk:   # SetVertex: line of sight to the optimistic parent failed -> best closed lattice neighbour
                best, bp = INF, -1
                for n in nbrs(s):
                    if n in closed:
                        cst, b2 = seg(n, s)
                        if not b2 and g[n] + cst < best: best, bp = g[n] + cst, n
                g[s] = best; par[s] = bp; p = bp
                if bp == -1: continue
        closed.add(s)
        if s == goal: break
        for n in nbrs(s):
            if n in closed: continue
            # path 1: via s on the lattice edge (must respect the corner rule); path 2: via parent(s) (lazy, LOS deferred)
            c1, b1 = seg(s, n); cand = []
            if not b1: cand.append((g[s] + c1, s))
            ps = par[s]
            if ps != s:
                c2, _ = seg(ps, n); cand.append((g[ps] + c2, ps))
            if not cand: continue
            nd, npar = min(cand)
            if nd < g.get(n, INF):
                g[n] = nd; par[n] = npar; heapq.heappush(pq, (nd + h(n), n))
    if goal not in closed: return dict(route=[], cost=INF, expanded=len(closed))
    route = [goal]
    while route[-1] != start: route.append(par[route[-1]])
    route.reverse()
    return dict(route=route, cost=g[goal], expanded=len(closed))


def smooth_path(ctx, route, window=150):
    """Cost-aware string pulling: from each vertex jump to the farthest later vertex (within `window`) that has exact
    line of sight AND whose straight-segment cost does not exceed the cost of the A* sub-path it replaces."""
    n = len(route)
    cum = [0.0]
    for a, b in zip(route[:-1], route[1:]): cum.append(cum[-1] + ctx.seg(a, b)[0])
    out = [route[0]]; i = 0
    while i < n - 1:
        nxt = i + 1
        for j in range(min(n - 1, i + window), i + 1, -1):
            c, blk = ctx.seg(route[i], route[j])
            if not blk and c <= cum[j] - cum[i] + 1e-9: nxt = j; break
        out.append(route[nxt]); i = nxt
    return out


class DStarLite:
    """D* Lite (Koenig & Likhachev 2002), 8-connected, same edge costs and corner rule as astar.py. Searches from the goal;
    g(s) = cost-to-goal. Edge costs are directional (climb term)."""
    def __init__(self, ctx, start, goal):
        self.ctx = ctx; self.W, self.H, self.cm = ctx.W, ctx.H, ctx.cm
        self.bl = list(ctx.bl); self.mu, self.el, self.clw = ctx.mu, ctx.el, ctx.clw
        self.start, self.goal, self.last = start, goal, start
        self.km = 0.0; self.g = {}; self.rhs = {goal: 0.0}; self.U = []; self.inU = {}
        self.expanded = 0
        self.inU[goal] = self._key(goal); heapq.heappush(self.U, (self.inU[goal], goal))

    def h(self, a, b):
        W = self.W; dr = abs(a // W - b // W); dc = abs(a % W - b % W)
        return self.cm * (max(dr, dc) + (math.sqrt(2) - 1) * min(dr, dc))
    def _key(self, s):
        m = min(self.g.get(s, INF), self.rhs.get(s, INF))
        return (m + self.h(self.start, s) + self.km, m)
    def nbrs(self, u):
        W, H = self.W, self.H; r, c = divmod(u, W)
        for dr, dc in N8:
            nr, nc = r + dr, c + dc
            if 0 <= nr < H and 0 <= nc < W: yield nr * W + nc, dr, dc
    def cost(self, u, v, dr, dc):
        bl = self.bl; W = self.W
        if bl[u] or bl[v]: return INF
        if dr and dc and (bl[u + dr * W] or bl[u + dc]): return INF
        d = self.cm * (1.4142135623730951 if dr and dc else 1.0)
        return d * 0.5 * (self.mu[u] + self.mu[v]) + self.clw * max(self.el[v] - self.el[u], 0.0)
    def update_vertex(self, u):
        if u != self.goal:
            best = INF
            for v, dr, dc in self.nbrs(u):
                gv = self.g.get(v, INF)
                if gv == INF: continue
                c = self.cost(u, v, dr, dc)
                if c + gv < best: best = c + gv
            self.rhs[u] = best
        self.inU.pop(u, None)
        if self.g.get(u, INF) != self.rhs.get(u, INF):
            k = self._key(u); self.inU[u] = k; heapq.heappush(self.U, (k, u))
    def compute(self):
        U, inU, g, rhs = self.U, self.inU, self.g, self.rhs
        while True:
            while U and inU.get(U[0][1]) != U[0][0]: heapq.heappop(U)
            if not U: break
            k, u = U[0]
            ks = self._key(self.start)   # float tolerance: exact ties in f are common (octile-tight heuristic) and round-off must not stop the search early
            if not (k[0] < ks[0] + 1e-7 or rhs.get(self.start, INF) != g.get(self.start, INF)): break
            heapq.heappop(U); del inU[u]; self.expanded += 1
            kn = self._key(u)
            if k < kn: inU[u] = kn; heapq.heappush(U, (kn, u))
            elif g.get(u, INF) > rhs.get(u, INF):
                g[u] = rhs[u]
                for p, _, _ in self.nbrs(u): self.update_vertex(p)
            else:
                g[u] = INF; self.update_vertex(u)
                for p, _, _ in self.nbrs(u): self.update_vertex(p)
    def path(self):
        if self.g.get(self.start, INF) == INF: return []
        route = [self.start]; u = self.start
        while u != self.goal:
            best, bv = INF, None
            for v, dr, dc in self.nbrs(u):
                c = self.cost(u, v, dr, dc) + self.g.get(v, INF)
                if c < best: best, bv = c, v
            if bv is None or len(route) > 100000: return []
            route.append(bv); u = bv
        return route
    def move_to(self, new_start):
        self.km += self.h(self.last, new_start); self.last = new_start; self.start = new_start
    def block_cells(self, cells):
        new = [c for c in cells if not self.bl[c]]
        for c in new: self.bl[c] = True
        touched = set()
        for c in new:
            touched.add(c)
            for v, _, _ in self.nbrs(c): touched.add(v)
        for u in touched: self.update_vertex(u)
        return len(new)
