#!/usr/bin/env python3
"""
MARSWALK Phase 4 - Gymnasium environment for the RL walker on the 4 m navigation grid, driven by the world model.

Physics are NOT defined here: speed, energy, fatigue, dose, EVA time and return reserve come from phase4/astronaut.py
(same Profile as A*, safety_validator and eval_rl), and the static hard limits are costs.hard_blocked(grid, profile).
Perception comes from phase4/world.py (static layers per cell + dynamic layers at the episode's sol and local time).

cell = row * 585 + col, row 0 north. Actions: 0 N 1 NE 2 E 3 SE 4 S 5 SW 6 W 7 NW 8 STOP.

Observation (Dict), patch (16, 15, 15) egocentric north-up, centred on the walker:
   0 slope_max/90 (unknown = 1)          1 rough_max/0.35 clipped 0..2 (unknown = 2)     2 loose (THEMIS, 101 m)
   3 rock_frac (0 where not covered)     4 not_covered (no rock_frac / ground_type; corridor-only layers)
   5 ground_type bedrock  6 sand  7 pebbly (one-hot, all 0 where not covered)
   8 (z - z_here)/20 clipped -1..1       9 science/5 clipped -1..2 (CRISM hydration/sulfate score, 18 m)
  10 unknown mask (NaN slope/rough/elevation, valid_frac < limit, off-map, or hidden when visibility=True)
  11 hard-blocked mask (static limits + the enabled dynamic limits; off-map = 1)
  12 in_shadow  13 insolation/700  14 (ground_temp_K - 200)/80 clipped -1..2 (modelled)  15 dose rate/10 uGy/h (modelled)
  Channels 12-15 are DYNAMIC: they are re-read as simulated time advances (refreshed every `dyn_step_h` of LMST).
vec (14,): 0,1 goal unit dx,dy (east,north); 2 log-distance to goal; 3 Euclid distance/2 km; 4 EVA time used/limit;
   5 energy used/budget; 6 dose used/budget; 7 standing on a science>2 cell; 8,9 sin,cos of time of day (LMST);
   10 sun elevation/90 (negative at night); 11 sep_alert (DONKI notice that sol); 12 fatigue 0..1;
   13 return margin: 1 - max over (time, energy, dose) of (used + retrace-the-route cost)/(limit x (1 - return reserve)),
      so 0 means the walker can just afford to walk back along its own route.
Reward: progress toward goal (change in geodesic distance, per cell) - step cost (time, energy, loose/steep ground, dose)
        - unsafe penalty (episode ends, or the move is refused when mask_invalid=True) + goal bonus
        (+ optional one-time science-stop bonus for STOP on a science>2 cell).
Episode ends: success; unsafe (hard-blocked cell, optionally shadow / ground temperature outside the suit range /
sunset); truncated when the round trip no longer fits the profile budgets (EVA time, energy, dose, with the return reserve,
the same rule safety_validator.validate applies) or after max_steps.
Visibility (default off): cells of the patch not in the walker's line of sight (phase4/visibility.visible_patch,
eye 1.7 m, on the 1 m DTM) are reported as unknown.
Curriculum: set_level(k) selects the start-goal distance band (LEVELS, metres).
"""
import math
import os
import sys
from dataclasses import dataclass

import numpy as np
import gymnasium as gym
from gymnasium import spaces
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra, connected_components

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from phase4 import astronaut as A
from phase4 import costs
from phase4.world import World, eot_hours, LAT_DEG, OBLIQ_DEG

W, H, CELL_M = 585, 732, 4.046987178318
R = 7                                   # patch half size -> 15 x 15
PATCH = 2 * R + 1
N_CH = 16
N_VEC = 14
DIRS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]   # (drow, dcol): N NE E SE S SW W NW
STOP = 8
# (min_m, max_m) start-goal straight-line distance per curriculum level
LEVELS = [(40, 100), (60, 200), (100, 400), (200, 800), (300, 1300), (300, 2000)]
CAMPAIGN_SOLS = (4500, 4799)
SOL_S = 3600.0 * 1.0274912517           # seconds per LMST hour (Mars hour = 1.0275 Earth hours)
VIS_RADIUS_M = 48.0                     # the 15x15 patch reaches 40 m from the centre; checked equal to radius 300 in tests
CH = dict(slope=0, rough=1, loose=2, rock=3, not_covered=4, bedrock=5, sand=6, pebbly=7, relz=8, science=9, unknown=10,
          blocked=11, shadow=12, insol=13, temp=14, dose=15)
DYN0 = 12
# optional coarse map view (Cfg.coarse): 15 x 15 cells of 4 x 4 nav cells (16.2 m), 243 m across, centred on the walker
CR, CK = 7, 4
CPATCH = 2 * CR + 1
CWIN = CPATCH * CK                      # 60 nav cells
CPAD = CWIN // 2                        # 30
C_CH = 5                                # blocked frac, unknown frac, mean slope/90, relative elevation/100, goal cell (+ visited if trail)


@dataclass
class Cfg:
    """Options that change what the agent sees or which dynamic limits apply (shared by the env and step_logs)."""
    visibility: bool = False
    forbid_shadow: bool = False          # entering a cell in shadow (sun below the local horizon, or night) is unsafe
    forbid_night: bool = True            # walking when the sun is below the flat horizon ends the episode as unsafe
    temp_range_K: tuple = None           # (tmin, tmax) modelled ground temperature limits; None = off (suit limits are not in the data)
    sep_stop: bool = False               # sample only sols without a DONKI SEP/CME-for-Mars notice (hard stop of new EVAs)
    dyn_step_h: float = 0.5              # dynamic layers are recomputed every this many LMST hours (cached per sol and step)
    dose_model: str = "astronaut"        # "astronaut": RAD campaign mean x time (as A*/validator); "world": per-cell modelled rate
    coarse: bool = False                 # add obs["coarse"]: 243 m map view (the orbital map an astronaut carries; no route, no distance field)
    trail: bool = False                  # memory of the walk: visit count as an extra patch channel (and a coarse channel)


class GridData:
    """Loaded once per process and profile: world, static channel stack, blocked mask, components, graph, dynamic cache."""
    _inst = {}

    @classmethod
    def get(cls, profile="nominal"):
        if profile not in cls._inst:
            cls._inst[profile] = cls(profile)
        return cls._inst[profile]

    def __init__(self, profile="nominal"):
        self.profile = A.get_profile(profile)
        self.world = w = World.load()
        grid = costs.load_grid()
        S = w.S
        self.elev = grid["elevation_m"].astype(np.float32)
        self.blocked = costs.hard_blocked(grid, self.profile)            # exactly what A* and the validator use
        self.slope, self.rough, self.loose, self.science = grid["slope_max_deg"], grid["rough_max_m"], grid["loose"], grid["science"]
        prof = self.profile
        with np.errstate(invalid="ignore"):
            unknown = (~np.isfinite(S["slope_max_deg"])) | (~np.isfinite(S["rough_max_m"])) | (~np.isfinite(S["elevation_m"])) \
                | (S["valid_frac"] < prof.valid_frac_min)
        covered = (S["ground_type"] >= 0) & np.isfinite(S["rock_frac"])
        gt = S["ground_type"]
        st = np.zeros((12, H, W), np.float32)
        st[0] = np.nan_to_num(S["slope_max_deg"] / 90.0, nan=1.0)
        st[1] = np.clip(np.nan_to_num(S["rough_max_m"] / prof.rough_max_m, nan=2.0), 0, 2)
        st[2] = np.nan_to_num(S["loose"], nan=0.0)
        st[3] = np.where(covered, np.nan_to_num(S["rock_frac"], nan=0.0), 0.0)
        st[4] = ~covered
        for k in range(3):
            st[5 + k] = covered & (gt == k)
        st[8] = np.nan_to_num(S["elevation_m"], nan=0.0)               # made relative at patch time
        st[9] = np.clip(np.nan_to_num(S["science"], nan=0.0) / 5.0, -1, 2)
        st[10] = unknown
        st[11] = self.blocked
        pad = np.zeros((12, H + 2 * R, W + 2 * R), np.float32)
        pad[:, R:-R, R:-R] = st
        pad[10] = 1.0                                                   # off-map: unknown and blocked
        pad[10, R:-R, R:-R] = st[10]
        pad[11] = 1.0
        pad[11, R:-R, R:-R] = st[11]
        self.spad = pad
        self.z = np.nan_to_num(self.elev, nan=0.0)
        self.sci_raw = np.nan_to_num(self.science, nan=0.0)
        cs = np.zeros((4, H + 2 * CPAD, W + 2 * CPAD), np.float32)       # off-map = blocked and unknown
        cs[0] = 1.0; cs[1] = 1.0
        cs[0, CPAD:-CPAD, CPAD:-CPAD] = self.blocked
        cs[1, CPAD:-CPAD, CPAD:-CPAD] = unknown
        cs[2, CPAD:-CPAD, CPAD:-CPAD] = np.clip(np.nan_to_num(S["slope_max_deg"], nan=90.0) / 90.0, 0, 1)
        cs[3] = np.pad(self.z, CPAD, mode="edge")                       # off-map elevation = nearest edge (it is flagged blocked anyway)
        self.cpad = cs
        # 8-neighbour graph over free cells for geodesic distance (cost in cell units)
        free = ~self.blocked
        idx = np.arange(H * W).reshape(H, W)
        rows, cols, vals = [], [], []
        for dr, dc in [(0, 1), (1, 0), (1, 1), (1, -1)]:
            r0, r1 = max(0, -dr), min(H, H - dr)
            c0, c1 = max(0, -dc), min(W, W - dc)
            a = idx[r0:r1, c0:c1]
            b = idx[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
            m = free[r0:r1, c0:c1] & free[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
            if dr and dc:                                    # no corner cutting (same rule as phase4/astar.py)
                m &= free[r0:r1, c0 + dc:c1 + dc] & free[r0 + dr:r1 + dr, c0:c1]
            rows.append(a[m]); cols.append(b[m]); vals.append(np.full(int(m.sum()), np.hypot(dr, dc), np.float32))
        r = np.concatenate(rows); c = np.concatenate(cols); v = np.concatenate(vals)
        self.graph = csr_matrix((np.concatenate([v, v]), (np.concatenate([r, c]), np.concatenate([c, r]))), shape=(H * W, H * W))
        _, lab = connected_components(self.graph, directed=False)
        lab = lab.reshape(H, W) + 1
        lab[self.blocked] = 0
        self.labels = lab
        sizes = np.bincount(lab.ravel(), minlength=lab.max() + 1)
        sizes[0] = 0
        self.big = np.where(sizes >= 2000)[0]
        self.big_p = sizes[self.big] / sizes[self.big].sum()
        self.comp_cells = {int(k): np.nonzero(lab == k) for k in self.big}
        # caches
        self._dyn, self._daylight, self._sep, self._ls, self._sun = {}, {}, {}, {}, {}

    # -- time / sun ---------------------------------------------------------------------------------------------
    def ls(self, sol):
        if sol not in self._ls:
            self._ls[sol] = self.world.ls_of_sol(sol, 12.0)
        return self._ls[sol]

    def sun_el(self, sol, lmst):
        """Sun elevation (deg); same formula as world.sun_position with Ls and the equation of time fixed at local noon of
        the sol (avoids 25 iterations per call; differs from the per-instant value by < 0.02 deg)."""
        k = self._sun.get(sol)
        if k is None:
            ls = self.ls(sol)
            k = self._sun[sol] = (math.asin(math.sin(math.radians(OBLIQ_DEG)) * math.sin(math.radians(ls))), float(eot_hours(ls)))
        dec, eot = k
        lat = math.radians(LAT_DEG)
        ha = math.radians((lmst + eot - 12.0) * 15.0)
        return math.degrees(math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha)))

    def daylight(self, sol):
        """(first, last) LMST hour with the sun above the flat horizon on `sol`."""
        if sol not in self._daylight:
            h = np.arange(0.0, 24.0, 0.1)
            up = np.array([self.sun_el(sol, x) > 0 for x in h])
            self._daylight[sol] = (float(h[up][0]), float(h[up][-1])) if up.any() else (12.0, 12.0)
        return self._daylight[sol]

    def sep(self, sol, lmst=12.0):
        """DONKI SEP / CME-for-Mars notice on the Earth (UTC) date of (sol, lmst); a sol can straddle two UTC dates."""
        k = (int(sol), int(round(lmst * 2)))
        if k not in self._sep:
            self._sep[k] = bool(self.world.sep_alert(int(sol), k[1] / 2.0)[0])
        return self._sep[k]

    def clock(self, sol0, lmst0, t_s):
        """(sol, lmst hour) after t_s simulated seconds from (sol0, lmst0)."""
        x = lmst0 + t_s / SOL_S
        return sol0 + int(x // 24.0), x % 24.0

    # -- dynamic layers (cached per sol and dyn_step_h bin) -------------------------------------------------------
    def dyn(self, sol, lmst, step_h=0.5):
        b = int(round(lmst / step_h))
        key = (int(sol), b, step_h)
        d = self._dyn.get(key)
        if d is None:
            lm = (b * step_h) % 24.0
            wd = self.world.dynamic(int(sol), lm)
            ch = np.zeros((4, H + 2 * R, W + 2 * R), np.float16)
            ch[0, R:-R, R:-R] = wd["in_shadow"]
            ch[1, R:-R, R:-R] = np.clip(wd["insolation"] / 700.0, 0, 2)
            ch[2, R:-R, R:-R] = np.clip(np.nan_to_num((wd["ground_temp_K"] - 200.0) / 80.0, nan=0.0), -1, 2)
            ch[3, R:-R, R:-R] = np.clip(np.nan_to_num(wd["dose_rate_uGy_h"] / 10.0, nan=0.0), 0, 2)
            self.world._cache.pop((int(sol), round(float(lm), 4), True), None)    # keep memory small
            d = ch
            if len(self._dyn) >= 14:
                self._dyn.pop(next(iter(self._dyn)))
            self._dyn[key] = d
        return d

    # -- geometry -----------------------------------------------------------------------------------------------
    def static_patch(self, row, col):
        p = self.spad[:, row:row + PATCH, col:col + PATCH]
        out = np.empty((N_CH, PATCH, PATCH), np.float32)
        out[:12] = p
        out[CH["relz"]] = np.clip((p[8] - self.z[row, col]) / 20.0, -1, 1)
        return out

    def coarse_patch(self, row, col, goal, visited=None):
        """(C_CH [+1], 15, 15) pooled 4 x 4 view centred on the walker's nav cell (it lies in coarse cell (7, 7))."""
        r0, c0 = row + CPAD - CPAD, col + CPAD - CPAD                    # window rows row-30 .. row+29 in unpadded coordinates
        win = self.cpad[:, r0:r0 + CWIN, c0:c0 + CWIN].reshape(4, CPATCH, CK, CPATCH, CK).mean(axis=(2, 4))
        n = C_CH + (visited is not None)
        out = np.zeros((n, CPATCH, CPATCH), np.float32)
        out[0], out[1], out[2] = win[0], win[1], win[2]
        out[3] = np.clip((win[3] - self.z[row, col]) / 100.0, -1, 1)
        gr, gc = divmod(int(goal), W)
        gi, gj = (gr - row + CPAD) // CK, (gc - col + CPAD) // CK
        if 0 <= gi < CPATCH and 0 <= gj < CPATCH:
            out[4, gi, gj] = 1.0
        if visited is not None:
            vp = np.zeros((CWIN, CWIN), np.float32)
            ra, ca = max(row - CPAD, 0), max(col - CPAD, 0)
            rb, cb = min(row - CPAD + CWIN, H), min(col - CPAD + CWIN, W)
            vp[ra - (row - CPAD):rb - (row - CPAD), ca - (col - CPAD):cb - (col - CPAD)] = visited[ra:rb, ca:cb] > 0
            out[5] = vp.reshape(CPATCH, CK, CPATCH, CK).mean(axis=(1, 3))
        return out

    def geodesic(self, goal, limit):
        # graph holds both directions of every edge, so directed=True is identical and skips scipy's per-call symmetrisation
        return dijkstra(self.graph, directed=True, indices=goal, limit=limit).reshape(H, W)


@dataclass
class Walk:
    """Walker/clock state needed to build an observation (also used by phase4/step_logs.py)."""
    t_s: float = 0.0
    energy_kj: float = 0.0
    dose_uGy: float = 0.0
    fatigue: float = 0.0
    margin: float = 1.0
    sol: int = 4600
    lmst0: float = 9.0


def build_obs(g, cell, goal, walk, cfg=None, visited=None):
    """Observation for a walker at `cell` heading to `goal` (cell indices)."""
    cfg = cfg or Cfg()
    prof = g.profile
    r, c = divmod(int(cell), W)
    gr, gc = divmod(int(goal), W)
    sol, lmst = g.clock(walk.sol, walk.lmst0, walk.t_s)
    p = g.static_patch(r, c)
    dyn = g.dyn(sol, lmst, cfg.dyn_step_h)[:, r:r + PATCH, c:c + PATCH].astype(np.float32)
    p[DYN0:DYN0 + 4] = dyn
    off = p[CH["unknown"]] > 0                                                      # unknown or off-map
    p[DYN0:DYN0 + 4] *= ~off                                                        # no dynamic values where nothing is known
    if cfg.forbid_shadow:
        p[CH["blocked"]] = np.maximum(p[CH["blocked"]], dyn[0] > 0)
    if cfg.temp_range_K is not None:
        T = dyn[2] * 80.0 + 200.0
        p[CH["blocked"]] = np.maximum(p[CH["blocked"]], ((T < cfg.temp_range_K[0]) | (T > cfg.temp_range_K[1])) & ~off)
    if cfg.visibility:
        from phase4 import visibility
        vis = visibility.visible_patch(r, c, half=R, radius_m=VIS_RADIUS_M)
        hid = ~vis & (p[CH["unknown"]] == 0)                                        # hidden but on the map
        p[:CH["unknown"]] *= ~hid
        p[CH["unknown"] + 1:] *= ~hid
        p[CH["unknown"]][hid] = 1.0
    el = g.sun_el(sol, lmst)
    dx, dy = (gc - c) * CELL_M, (r - gr) * CELL_M                                   # east, north
    dist = float(np.hypot(dx, dy))
    u = (dx / dist, dy / dist) if dist > 1e-6 else (0.0, 0.0)
    ang = 2 * math.pi * lmst / 24.0
    vec = np.array([u[0], u[1], np.log1p(dist) / np.log1p(2500.0), min(dist / 2000.0, 2.0),
                    walk.t_s / (prof.eva_time_h * 3600.0), walk.energy_kj / prof.energy_budget_kj,
                    walk.dose_uGy / prof.dose_budget_uGy, float(g.sci_raw[r, c] > 2.0),
                    math.sin(ang), math.cos(ang), el / 90.0, float(g.sep(sol, lmst)), walk.fatigue, walk.margin], np.float32)
    obs = {"patch": p, "vec": vec}
    if cfg.trail:
        v = np.zeros((PATCH, PATCH), np.float32)
        if visited is not None:
            ra, ca, rb, cb = max(r - R, 0), max(c - R, 0), min(r + R + 1, H), min(c + R + 1, W)
            v[ra - (r - R):rb - (r - R), ca - (c - R):cb - (c - R)] = np.minimum(visited[ra:rb, ca:cb], 6) / 3.0
        obs["patch"] = np.concatenate([p, v[None]], 0)                             # channel 16: visits (0..2)
    if cfg.coarse:
        obs["coarse"] = g.coarse_patch(r, c, goal, visited if cfg.trail else None)
    return obs


class MarsWalkEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, level=0, mask_invalid=False, science_bonus=0.0, seed=None, max_level=len(LEVELS) - 1,
                 goal_radius_cells=1.0, profile="nominal", visibility=False, forbid_shadow=False, forbid_night=True,
                 temp_range_K=None, sep_stop=False, dyn_step_h=0.5, dose_model="astronaut", sols=CAMPAIGN_SOLS,
                 min_daylight_h=2.0, w_time=0.0007, w_energy=0.00018, w_dose=0.01, coarse=False, trail=False):
        super().__init__()
        self.g = GridData.get(profile)
        self.prof = self.g.profile
        self.cfg = Cfg(visibility=visibility, forbid_shadow=forbid_shadow, forbid_night=forbid_night,
                       temp_range_K=tuple(temp_range_K) if temp_range_K else None, sep_stop=sep_stop,
                       dyn_step_h=dyn_step_h, dose_model=dose_model, coarse=coarse, trail=trail)
        self.sols, self.min_daylight_h = sols, min_daylight_h
        self.level, self.max_level = int(level), int(max_level)
        self.mask_invalid, self.science_bonus = mask_invalid, science_bonus
        self.goal_radius = goal_radius_cells
        self.w_time, self.w_energy, self.w_dose = w_time, w_energy, w_dose
        self.action_space = spaces.Discrete(9)
        sp = {"patch": spaces.Box(-1.0, 2.0, (N_CH + int(trail), PATCH, PATCH), np.float32),
              "vec": spaces.Box(-3.0, 3.0, (N_VEC,), np.float32)}
        if coarse:
            sp["coarse"] = spaces.Box(-1.0, 1.0, (C_CH + int(trail), CPATCH, CPATCH), np.float32)
        self.observation_space = spaces.Dict(sp)
        self.visited = np.zeros((H, W), np.uint16) if trail else None
        self._rng = np.random.default_rng(seed)
        self.cell = self.goal = None
        self.start_goal = None                                    # optional fixed (start, goal) for evaluation
        self.sol0, self.lmst0 = 4600, 9.0
        self.walk = Walk()

    # --- curriculum / sampling -------------------------------------------------------------------------
    def set_level(self, k):
        self.level = int(np.clip(k, 0, self.max_level))
        return self.level

    def get_level(self):
        return self.level

    def sample_pair(self):
        g = self.g
        lo, hi = LEVELS[self.level]
        for _ in range(2000):
            comp = int(self._rng.choice(g.big, p=g.big_p))
            ys, xs = g.comp_cells[comp]
            i = self._rng.integers(len(ys))
            r0, c0 = int(ys[i]), int(xs[i])
            ang = self._rng.uniform(0, 2 * np.pi)
            d = self._rng.uniform(lo, hi) / CELL_M
            r1, c1 = int(round(r0 - d * np.sin(ang))), int(round(c0 + d * np.cos(ang)))
            if 0 <= r1 < H and 0 <= c1 < W and g.labels[r1, c1] == comp:
                return r0 * W + c0, r1 * W + c1
        raise RuntimeError("could not sample a start-goal pair")

    def sample_time(self):
        """Sol from the campaign range (no SEP/CME notice if sep_stop) and a start LMST in daylight."""
        g = self.g
        for _ in range(200):
            sol = int(self._rng.integers(self.sols[0], self.sols[1] + 1))
            rise, sset = g.daylight(sol)
            hi = max(sset - self.min_daylight_h, rise + 0.25)
            lmst = float(self._rng.uniform(rise + 0.25, hi))
            if not (self.cfg.sep_stop and g.sep(sol, lmst)):    # no new EVA while a notice is active at the start time
                break
        return sol, lmst

    # --- gym API ---------------------------------------------------------------------------------------
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        o = options or {}
        pair = o.get("start_goal") or self.start_goal
        for _ in range(50):
            s, t = pair if pair else self.sample_pair()
            s, t = int(s), int(t)
            d_euc = float(np.hypot(s // W - t // W, s % W - t % W))
            self.dist_field = self.g.geodesic(t, limit=max(60.0, 8.0 * d_euc + 60.0))
            if np.isfinite(self.dist_field[s // W, s % W]):
                break
            if pair:                                                # given pair (evaluation): use the full geodesic field
                self.dist_field = self.g.geodesic(t, limit=np.inf)
                break
            # sampled pair whose detour exceeds the Dijkstra window: max_steps and the shaping would be wrong, so resample
        if o.get("sol") is not None:
            self.sol0, self.lmst0 = int(o["sol"]), float(o.get("lmst", 9.0))
        else:
            self.sol0, self.lmst0 = self.sample_time()
        self.cell, self.goal = s, t
        self.t_s = self.energy = self.dose = 0.0
        self.fatigue = 0.0
        self.ret_t = self.ret_e = self.ret_dose = 0.0               # cost of walking back along the route actually walked
        self.legs = []                                              # (3D distance, grade) of every move, for the exact round trip
        self.steps = 0
        d0 = self._d(s)
        self.max_steps = int(4 * max(d0, 10.0) + 60)
        self.sci_done = set()
        self.d_prev = d0
        self.walk = Walk(sol=self.sol0, lmst0=self.lmst0)
        if self.visited is not None:
            self.visited[:] = 0
            self.visited[s // W, s % W] = 1
        return self._obs(), {"start": s, "goal": t, "sol": self.sol0, "lmst0": self.lmst0}

    def _d(self, cell):
        v = self.dist_field[cell // W, cell % W]
        if np.isfinite(v):
            return float(v)
        r, c = divmod(cell, W)                                # outside the Dijkstra window: Euclidean with margin
        gr, gc = divmod(self.goal, W)
        return float(np.hypot(r - gr, c - gc)) * 1.5 + 5.0

    def _margin(self):
        """1 - max committed fraction of the reserve-adjusted budgets (time, energy, dose), return leg included."""
        p = self.prof
        keep = 1.0 - p.return_reserve_frac
        T, E, D = self.t_s + self.ret_t, self.energy + self.ret_e, self.dose + self.ret_dose
        return 1.0 - max(T / (p.eva_time_h * 3600.0 * keep), E / (p.energy_budget_kj * keep), D / p.dose_budget_uGy)

    def _round_trip_exceeded(self):
        """Exact out-and-back check as safety_validator.validate (back leg with its own fatigue); None or the first limit exceeded."""
        p = self.prof
        if not self.legs:
            return None
        d, gr = zip(*self.legs)
        back = A.route_resources(p, d[::-1], [-x for x in gr[::-1]])
        keep = 1.0 - p.return_reserve_frac
        T, E = self.t_s + back["time_s"], self.energy + back["energy_kj"]
        if T > p.eva_time_h * 3600.0 * keep:
            return "time"
        if E > p.energy_budget_kj * keep:
            return "energy"
        if self.dose + self.ret_dose * back["time_s"] / max(self.ret_t, 1e-9) > p.dose_budget_uGy:
            return "dose"
        return None

    def _obs(self):
        w = self.walk
        w.t_s, w.energy_kj, w.dose_uGy, w.fatigue, w.margin = self.t_s, self.energy, self.dose, self.fatigue, self._margin()
        return build_obs(self.g, self.cell, self.goal, w, self.cfg, self.visited)

    def _dyn_at(self, t_s):
        sol, lmst = self.g.clock(self.sol0, self.lmst0, t_s)
        return sol, lmst, self.g.dyn(sol, lmst, self.cfg.dyn_step_h)

    def _dynamic_bad(self, rr, cc, t_s):
        """None, or the reason a cell is unsafe at time t_s from the enabled dynamic limits."""
        sol, lmst, d = self._dyn_at(t_s)
        if self.cfg.forbid_night and self.g.sun_el(sol, lmst) <= 0.0:
            return "night"
        if self.cfg.forbid_shadow and d[0, rr + R, cc + R] > 0:
            return "shadow"
        if self.cfg.temp_range_K is not None:
            T = float(d[2, rr + R, cc + R]) * 80.0 + 200.0
            if T < self.cfg.temp_range_K[0] or T > self.cfg.temp_range_K[1]:
                return "temperature"
        return None

    def action_masks(self):
        """True where the move is legal now (target on map, not hard-blocked incl. enabled dynamic limits); STOP always legal."""
        r, c = divmod(self.cell, W)
        m = np.ones(9, bool)
        for a, (dr, dc) in enumerate(DIRS):
            rr, cc = r + dr, c + dc
            m[a] = 0 <= rr < H and 0 <= cc < W and not self.g.blocked[rr, cc]
            if m[a] and dr and dc:
                m[a] = not (self.g.blocked[r, cc] or self.g.blocked[rr, c])
            if m[a] and self._dynamic_bad(rr, cc, self.t_s) is not None:
                m[a] = False
        return m

    def _rate(self, rr, cc, t_s):
        if self.cfg.dose_model == "world":
            return float(self._dyn_at(t_s)[2][3, rr + R, cc + R]) * 10.0
        return A.RAD_RATE_UGY_H

    def _rest(self, dt):
        self.t_s += dt
        self.dose += self._rate(self.cell // W, self.cell % W, self.t_s) * dt / 3600.0
        self.fatigue = A.fatigue_update(self.prof, self.fatigue, 0.0, dt)

    def step(self, action):
        g, a, p = self.g, int(action), self.prof
        r, c = divmod(self.cell, W)
        reward, terminated, info = 0.0, False, {"is_success": False, "unsafe": False, "budget_exceeded": None, "unsafe_reason": None}
        self.steps += 1
        dt = 5.0                                               # STOP / refused move costs 5 s
        if a == STOP:
            reward -= 0.02
            self._rest(dt)
            if self.science_bonus and g.sci_raw[r, c] > 2.0 and self.cell not in self.sci_done:
                self.sci_done.add(self.cell); reward += self.science_bonus
        else:
            dr, dc = DIRS[a]
            rr, cc = r + dr, c + dc
            bad = (not (0 <= rr < H and 0 <= cc < W)) or g.blocked[rr, cc]
            if not bad and dr != 0 and dc != 0:                # corner cutting is refused (same rule as astar.py)
                bad = bool(g.blocked[r, cc] or g.blocked[rr, c])
            reason = "blocked" if bad else None
            if not bad:
                pd = CELL_M * math.hypot(dr, dc)
                dz = float(g.z[rr, cc] - g.z[r, c])
                grade = dz / pd
                dist3 = math.hypot(pd, dz)                     # same geometry as astar.route_metrics / safety_validator
                v = A.step_speed_mps(p, grade, self.fatigue)
                dt = dist3 / v
                e = A.step_energy_kj(p, dist3, grade)
                reason = self._dynamic_bad(rr, cc, self.t_s + dt)
                bad = reason is not None
            if bad and self.mask_invalid and reason != "night":
                reward -= 0.05
                dt = 5.0
                self._rest(dt)
            elif bad:
                reward -= 5.0; terminated = True; info["unsafe"] = True; info["unsafe_reason"] = reason
            else:
                self.t_s += dt; self.energy += e
                rate = self._rate(rr, cc, self.t_s)
                self.dose += rate * dt / 3600.0
                self.fatigue = A.fatigue_update(p, self.fatigue, e)
                vb = A.step_speed_mps(p, -grade, 0.0)           # retrace leg: reversed grade, as the validator's back leg
                self.ret_t += dist3 / vb; self.ret_e += A.step_energy_kj(p, dist3, -grade)
                self.ret_dose += rate * (dist3 / vb) / 3600.0
                self.legs.append((dist3, grade))
                self.cell = rr * W + cc
                if self.visited is not None and self.visited[rr, cc] < 65535:
                    self.visited[rr, cc] += 1
                d_new = self._d(self.cell)
                reward += 0.1 * (self.d_prev - d_new)         # per cell of geodesic progress
                self.d_prev = d_new
                reward -= self.w_time * dt + self.w_energy * e + self.w_dose * rate * dt / 3600.0
                reward -= 0.01 * float(g.loose[rr, cc] > 0.5) + 0.01 * float(g.slope[rr, cc] > 15)
        truncated = False
        if not terminated:
            margin = self._margin()
            if margin < 0.0:                                   # round trip no longer fits (validator rule): budget exceeded
                truncated = True
                keep = 1.0 - p.return_reserve_frac
                fr = {"time": (self.t_s + self.ret_t) / (p.eva_time_h * 3600.0 * keep),
                      "energy": (self.energy + self.ret_e) / (p.energy_budget_kj * keep),
                      "dose": (self.dose + self.ret_dose) / p.dose_budget_uGy}
                info["budget_exceeded"] = max(fr, key=fr.get)
            elif np.hypot(self.cell // W - self.goal // W, self.cell % W - self.goal % W) <= self.goal_radius:
                bad_rt = self._round_trip_exceeded()
                if bad_rt:                                     # at the goal the validator's exact round trip decides
                    truncated = True; info["budget_exceeded"] = bad_rt
                else:
                    reward += 10.0; terminated = True; info["is_success"] = True
            elif self.steps >= self.max_steps:
                truncated = True
        sol, lmst = g.clock(self.sol0, self.lmst0, self.t_s)
        info.update(t_s=self.t_s, energy_kj=self.energy, dose_uGy=self.dose, fatigue=self.fatigue, cell=self.cell,
                    sol=sol, lmst=lmst, return_margin=self._margin())
        return self._obs(), float(reward), terminated, truncated, info
