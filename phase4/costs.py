"""
MARSWALK Phase 4 - grid loading, per-cell traversal cost and hard constraints (Module 5A).

Cell multiplier  m(s) = 1 + K * C(s),   C(s) = w_t C_terrain + w_x C_exposure + w_e C_environment
                                                + w_m C_mobility + w_u C_uncertainty,   every term in 0..1.
m >= 1 so straight-line distance is an admissible A* heuristic. K = COST_SCALE = 4 (a cell can cost
up to 5x its length). Hard hazards are NOT in the cost: see hard_blocked().
"""
import json, os
import numpy as np
try:
    from . import astronaut as A
except ImportError:
    import astronaut as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID_NPZ = os.path.join(ROOT, "data", "processed", "roi", "nav_grid_4m.npz")
COST_SCALE = 4.0


def load_grid(path=None) -> dict:
    path = path or GRID_NPZ
    z = np.load(path)
    g = {k: z[k] for k in z.files}
    meta_path = os.path.splitext(path)[0] + ".json"
    g["meta"] = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    g["height"], g["width"] = g["elevation_m"].shape
    g["cell_m"] = float(g["meta"].get("cell_m", 4.046987178318))
    return g


BOULDER_JSON = os.path.join(ROOT, "data", "processed", "roi", "boulder_cells.json")
_BOULDER_CACHE = {}


def boulder_blocked(grid, path=None) -> np.ndarray:
    """bool mask, True = cell within a HiRISE-detected boulder's footprint + margin (tools/export_boulders.py). All False
    when the file is missing or the grid is not the 585 x 732 ROI grid."""
    path = path or BOULDER_JSON
    m = np.zeros((grid["height"], grid["width"]), bool)
    if not os.path.exists(path):
        return m
    if path not in _BOULDER_CACHE:
        _BOULDER_CACHE[path] = np.array(json.load(open(path))["cells"], dtype=np.int64)
    c = _BOULDER_CACHE[path]
    if (grid["height"], grid["width"]) == (732, 585):
        m.flat[c] = True
    return m


def hard_blocked(grid, profile, allow_unknown_rough=False) -> np.ndarray:
    """True = never enter. slope_max > max_slope, rough > rough_max, valid_frac < min, NaN slope/elev,
    NaN roughness (unknown) unless allow_unknown_rough (then the cell is only penalised by C_uncertainty), and
    boulder footprint cells while profile.avoid_boulders (default True)."""
    sl, ro, vf = grid["slope_max_deg"], grid["rough_max_m"], grid["valid_frac"]
    with np.errstate(invalid="ignore"):
        b = (sl > profile.max_slope_deg) | (ro > profile.rough_max_m) | (vf < profile.valid_frac_min)
    b |= np.isnan(sl) | np.isnan(grid["elevation_m"])
    if not allow_unknown_rough:
        b |= np.isnan(ro)
    if getattr(profile, "avoid_boulders", True):
        b |= boulder_blocked(grid)
    return b


def cell_terms(grid, profile) -> dict:
    """The five cost terms, each float32 0..1 (see docs/phase4_navigation.md for the table)."""
    sl = np.nan_to_num(grid["slope_max_deg"], nan=profile.max_slope_deg)
    slm = np.nan_to_num(grid["slope_mean_deg"], nan=profile.max_slope_deg)
    ro = grid["rough_max_m"]
    # terrain: steepest slope relative to the limit (squared) and roughness relative to the limit. NaN roughness -> 1.
    c_slope = np.clip(sl / profile.max_slope_deg, 0, 1) ** 2
    c_rough = np.clip(np.nan_to_num(ro, nan=profile.rough_max_m) / profile.rough_max_m, 0, 1)
    terrain = 0.6 * c_slope + 0.4 * c_rough
    # exposure: radiation is time-based, so the spatial proxy is the extra time outside caused by the local
    # mean slope: 1 - v(grade)/v(0) (Tobler, uphill and downhill both slow), clipped 0..1. Time x 6.45 uGy/h is dose.
    grade = np.tan(np.radians(slm))
    v0 = A.step_speed_mps(profile, 0.0)
    v = np.array([A.step_speed_mps(profile, x) for x in np.linspace(0, 0.6, 61)])
    vg = np.interp(grade, np.linspace(0, 0.6, 61), v)
    exposure = np.clip(1 - vg / v0, 0, 1)
    # environment: loose-material hint (THEMIS dawn warmth, 0..1, coarse ~100 m). Missing -> 0.5.
    environment = np.clip(np.nan_to_num(grid["loose"], nan=0.5), 0, 1)
    # mobility: metabolic cost relative to flat at the local mean slope, (E(grade)/E(0) - 1)/4 clipped 0..1.
    e = np.array([A.step_energy_kj(profile, 1.0, x) for x in np.linspace(0, 0.6, 61)])
    mobility = np.clip((np.interp(grade, np.linspace(0, 0.6, 61), e) / e[0] - 1) / 4.0, 0, 1)
    # uncertainty: 1 - valid_frac (terrain data confidence); NaN roughness -> 1.
    unc = 1 - np.clip(np.nan_to_num(grid["valid_frac"], nan=0.0), 0, 1)
    unc = np.where(np.isnan(ro), 1.0, unc)
    return {k: x.astype(np.float32) for k, x in
            dict(terrain=terrain, exposure=exposure, environment=environment, mobility=mobility, uncertainty=unc).items()}


def cell_cost(grid, profile) -> np.ndarray:
    """float32 per-cell traversal multiplier, >= 1 (blocked cells still get a finite value; check hard_blocked)."""
    t = cell_terms(grid, profile)
    w = profile.cost_weights
    c = sum(wi * t[k] for wi, k in zip(w, ["terrain", "exposure", "environment", "mobility", "uncertainty"]))
    return (1.0 + COST_SCALE * c).astype(np.float32)


def cell_index(grid, row, col):
    return int(row) * grid["width"] + int(col)


def cell_rc(grid, idx):
    return divmod(int(idx), grid["width"])
