#!/usr/bin/env python3
"""MARSWALK world model (docs/world_design.md, docs/world_model.md).

Every 4 m cell (585 x 732, cell = row * 585 + col, row 0 north) carries static layers (world_static_4m.npz)
and dynamic layers for any sol and local mean solar time (LMST, hours).  Every value is labelled
measured / derived / modelled.

    from phase4.world import World
    w = World.load()
    d = w.dynamic(4600, 13.0)         # dict of [732, 585] arrays + scalars
    w.cell(12345, 4600, 13.0)         # {name: {"value", "units", "class"}}
    w.hard_blocked(profile, 4600, 9.0, daylight=True)

Time: sol -> Ls from the orbit model (checked against REMS daily); LMST -> true solar time with the Mars equation of time
(Allison & McEwen 2000); sun position from Ls, latitude and hour angle.  The twin page omits the equation
of time (up to 40 min here); pass eot=False to reproduce the twin's formula.
"""
import csv, datetime as _dt, json, math, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROI = os.path.join(ROOT, "data", "processed", "roi")
WORLD = os.path.join(ROI, "world")
LAT_DEG, LON_E_DEG = -4.8, 137.41          # study-area centre (twin page uses lat -4.8)
OBLIQ_DEG = 25.19
SOLAR_CONST = 1361.0                       # W/m2 at 1 AU
A_AU, E_MARS, LS_PERI = 1.523679, 0.09341, 251.0
SOL_LEN_D = 1.0274912517
LANDING_UTC = _dt.datetime(2012, 8, 6, 5, 17, 57)   # MSL landing, sol 0
TAU_DEFAULT = 0.6                          # visible dust optical depth (assumption, no tau series in the data; see docs)
CELL_M = 4.046987178318
H_, W_ = 732, 585

CLASS = {  # class / unit labels for dynamic layers
    "sun_el": ("deg", "derived"), "sun_az": ("deg", "derived"), "in_shadow": ("bool", "derived"),
    "insolation": ("W/m2", "modelled"), "ground_temp_K": ("K", "modelled"),
    "air_temp_K": ("K", "measured (rover, same for every cell)"), "pressure_Pa": ("Pa", "measured (rover, same for every cell)"),
    "rh": ("%", "measured (rover, same for every cell)"), "uv": ("W/m2 UV A-E total", "measured (rover, same for every cell)"),
    "wind": ("m/s", "measured (rover) - no data in the REMS release (sensor out of service)"),
    "dose_rate_uGy_h": ("uGy/h", "modelled"), "sep_alert": ("bool", "measured (space weather, Earth-side notices)")}


# ----------------------------------------------------------------------------------------- time & sun
def nu_deg(M_rad):
    return (10.691 * np.sin(M_rad) + 0.623 * np.sin(2 * M_rad) + 0.050 * np.sin(3 * M_rad) + 0.005 * np.sin(4 * M_rad) + 0.0005 * np.sin(5 * M_rad))


def eot_hours(ls_deg):
    """Equation of time, hours; LTST = LMST + eot.  Allison & McEwen 2000 (Ls -> mean anomaly by iteration)."""
    ls = np.asarray(ls_deg, float); M = np.radians(ls - LS_PERI)
    for _ in range(25):
        M = np.radians(ls - 250.999 - nu_deg(M))
    L = np.radians(ls)
    return (2.861 * np.sin(2 * L) - 0.071 * np.sin(4 * L) + 0.002 * np.sin(6 * L) - nu_deg(M)) / 15.0


def _jd(dt):   # UTC datetime -> JD (UTC)
    return 2440587.5 + (dt - _dt.datetime(1970, 1, 1)).total_seconds() / 86400.0


def msd_of_utc(dt):
    """Mars Sol Date (Allison & McEwen) at the prime meridian for a UTC datetime."""
    jd_tt = _jd(dt) + 69.184 / 86400.0
    return (jd_tt - 2451549.5) / SOL_LEN_D + 44796.0 - 0.0009626


def utc_of_msd(msd):
    jd_tt = (msd - 44796.0 + 0.0009626) * SOL_LEN_D + 2451549.5
    return _dt.datetime(1970, 1, 1) + _dt.timedelta(days=jd_tt - 69.184 / 86400.0 - 2440587.5)


_MSD_SOL0 = math.floor(msd_of_utc(LANDING_UTC) + LON_E_DEG / 360.0)    # local-midnight MSD that starts MSL sol 0


def sol_lmst_to_utc(sol, lmst):
    """UTC datetime of a given MSL sol and LMST hour at the study area (A&M MSD, sol 0 = landing day)."""
    return utc_of_msd(_MSD_SOL0 + sol + lmst / 24.0 - LON_E_DEG / 360.0)


def utc_to_sol_lmst(dt):
    m = msd_of_utc(dt) + LON_E_DEG / 360.0 - _MSD_SOL0
    return int(math.floor(m)), 24.0 * (m - math.floor(m))


def ls_am(sol_float):
    """Ls (deg) from Allison & McEwen (no perturbers; ~0.05 deg), for sols outside the REMS table."""
    dt = utc_of_msd(_MSD_SOL0 + sol_float + 0.5 - LON_E_DEG / 360.0)
    D = _jd(dt) + 69.184 / 86400.0 - 2451545.0
    M = math.radians(19.3871 + 0.52402075 * D)
    return (270.3871 + 0.524038496 * D + float(nu_deg(M))) % 360.0


def mars_r_au(ls_deg):
    nu = math.radians(ls_deg - LS_PERI)
    return A_AU * (1 - E_MARS ** 2) / (1 + E_MARS * math.cos(nu))


def sun_position(ls_deg, lmst, lat_deg=LAT_DEG, eot=True):
    """(elevation, azimuth) in degrees; azimuth clockwise from north.  Same trigonometry as the twin page's
    sunDir() except for the optional equation-of-time shift of the hour angle."""
    ls = math.radians(ls_deg); lat = math.radians(lat_deg)
    dec = math.asin(math.sin(math.radians(OBLIQ_DEG)) * math.sin(ls))
    ha = math.radians((lmst + (float(eot_hours(ls_deg)) if eot else 0.0) - 12.0) * 15.0)
    el = math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha) * math.cos(dec), math.cos(lat) * math.sin(dec) - math.sin(lat) * math.cos(dec) * math.cos(ha))
    return math.degrees(el), (math.degrees(az) + 360.0) % 360.0


# ----------------------------------------------------------------------------------------- the world
class World:
    def __init__(self, static, meta, params):
        self.S, self.meta, self.p = static, meta, params
        self.H, self.W = static["elevation_m"].shape
        self.cell_m = CELL_M
        self._cache = {}
        n = {k: np.nan_to_num(static[k].astype(np.float64), nan=0.0) for k in ("slope_plane_deg", "aspect_deg")}
        s, a = np.radians(n["slope_plane_deg"]), np.radians(n["aspect_deg"])
        self._n = (np.sin(s) * np.sin(a), np.sin(s) * np.cos(a), np.cos(s))   # unit surface normal (E, N, Up)
        self._tables()
        # dose reference: mean sky_view factor on Curiosity's track cells (where RAD measured)
        track = static["dist_to_rover_track_m"] == 0
        sv = static["sky_view"]
        self.sky_ref = float(np.nanmean(sv[track]))
        self.dose_factor = (sv / self.sky_ref).astype(np.float32)
        self.dose_factor[~np.isfinite(static["elevation_m"])] = np.nan

    # -- loading
    @classmethod
    def load(cls, root=None):
        d = root or WORLD
        z = np.load(os.path.join(d, "world_static_4m.npz"))
        static = {k: z[k] for k in z.files}
        for need in ("horizon_deg", "sky_view", "sky_solid"):
            if need not in static:
                raise RuntimeError("world_static_4m.npz has no %s: rerun phase4/build_world_static.py after horizon_32_4m.npz exists" % need)
        meta = json.load(open(os.path.join(d, "world_static_4m.json")))
        pj = os.path.join(d, "world_params.json")
        params = dict(tau=TAU_DEFAULT, albedo=0.25, a_K_per_Wm2=0.0, kappa_K_per_K=0.0, airmass_cap=10.0, cme_window_days=0)
        if os.path.exists(pj): params.update(json.load(open(pj))["params"])
        return cls(static, meta, params)

    # -- tables: REMS daily/hourly, RAD per sol, DONKI
    def _tables(self):
        T = os.path.join(ROI, "tables")
        rows = list(csv.DictReader(open(os.path.join(T, "rems_daily.csv"))))
        self.date_of_sol = {int(r["sol"]): r["terrestrial_date"] for r in rows}
        self.rems_ls = {int(r["sol"]): float(r["ls"]) for r in rows if r["ls"] not in ("", None)}   # integer, truncated (see docs)
        # hourly REMS (bin centres h + 0.5 LMST); fill short gaps cyclically within a sol
        hr = list(csv.DictReader(open(os.path.join(T, "rems_rmd_campaign_hourly.csv"))))
        self.rems_sols = np.array(sorted({int(r["sol"]) for r in hr}))
        idx = {s: i for i, s in enumerate(self.rems_sols)}
        cols = {"ground_temp_K": ("ground_temp_C", 273.15), "air_temp_K": ("air_temp_C", 273.15), "pressure_Pa": ("pressure_Pa", 0.0),
                "rh": ("rel_humidity_pct", 0.0), "uv": ("uv_abc_Wm2", 0.0), "wind": ("wind_speed_ms", 0.0)}
        self._rems = {k: np.full((len(self.rems_sols), 24), np.nan) for k in cols}
        for r in hr:
            for k, (c, off) in cols.items():
                v = r[c]
                if v not in ("", "nan"): self._rems[k][idx[int(r["sol"])], int(r["lmst_hour"])] = float(v) + off
        self._rems_raw = {k: v.copy() for k, v in self._rems.items()}
        for k in self._rems:
            for i in range(len(self.rems_sols)):
                row = self._rems[k][i]; g = np.isfinite(row)
                if g.sum() >= 8 and not g.all():                       # cyclic linear fill of missing hours
                    h = np.arange(24); self._rems[k][i] = np.interp(h, np.r_[h[g] - 24, h[g], h[g] + 24], np.r_[row[g], row[g], row[g]])
                elif g.sum() < 8: self._rems[k][i] = np.nan             # too few hours: sol unusable for the diurnal curve
        rp = list(csv.DictReader(open(os.path.join(T, "rad_per_sol.csv"))))
        self._rad_sol = np.array([float(r["sol"]) for r in rp]); self._rad_E = np.array([float(r["mean_E_uGy_h"]) for r in rp])
        self._rad_B = np.array([float(r["mean_B_uGy_h"]) for r in rp])
        # DONKI: SEP notices, and CME notices that list Mars among the affected missions
        dk = list(csv.DictReader(open(os.path.join(ROOT, "data", "raw", "gapfill", "donki", "key_events_per_date.csv"))))
        self.sep_days = sorted({r["issue_time"][:10] for r in dk if r["type"] == "SEP"})
        self.cme_mars_days = sorted({r["issue_time"][:10] for r in dk if r["type"] == "CME" and "Mars" in r["note"]})
        self.donki_range = (min(r["issue_time"][:10] for r in dk), max(r["issue_time"][:10] for r in dk))

    # -- time helpers
    def ls_of_sol(self, sol, lmst=12.0):
        """Ls (deg) at (sol, lmst).  Allison & McEwen orbit model: it reproduces 98.6% of the integer Ls in rems_daily.csv
        when those are read as floor(Ls at the start of the sol), so the REMS integers are truncated (mean -0.5 deg) and
        are not used directly."""
        return ls_am(sol + lmst / 24.0 - 0.5)

    def utc_date(self, sol, lmst=12.0):
        return sol_lmst_to_utc(sol, lmst).strftime("%Y-%m-%d")

    # -- REMS at (sol, lmst)
    def rems(self, sol, lmst):
        """REMS value per variable at (sol, lmst): linear in sol between measured sols, linear in LMST between hour-bin centres.
        Outside the table the nearest measured sol is used (flagged in 'rems_sol_used')."""
        out = {}; x = (lmst - 0.5) % 24.0; h0 = int(math.floor(x)) % 24; h1 = (h0 + 1) % 24; f = x - math.floor(x)
        for k, arr in self._rems.items():
            col = lambda h: arr[:, h]
            v0, v1 = col(h0), col(h1); v = v0 * (1 - f) + v1 * f
            g = np.isfinite(v)
            out[k] = float(np.interp(sol, self.rems_sols[g], v[g])) if g.sum() >= 2 else float("nan")
        near = self.rems_sols[np.argmin(np.abs(self.rems_sols - sol))]
        out["rems_sol_used"] = int(near); out["rems_gap_sols"] = int(abs(near - sol))
        return out

    def rems_daymean_ground(self, sol):
        a = self._rems["ground_temp_K"]; m = np.array([np.mean(r) if np.isfinite(r).all() else np.nan for r in a]); g = np.isfinite(m)
        return float(np.interp(sol, self.rems_sols[g], m[g]))

    def rad_rate(self, sol, kind="E"):
        r = self._rad_E if kind == "E" else self._rad_B
        return float(np.interp(sol, self._rad_sol, r))

    def sep_alert(self, sol, lmst=12.0):
        d = self.utc_date(sol, lmst); w = int(self.p.get("cme_window_days", 0))
        day = _dt.date.fromisoformat(d)
        near = lambda days: any(0 <= (day - _dt.date.fromisoformat(x)).days <= w for x in days)
        sep = d in self.sep_days; cme = near(self.cme_mars_days)
        return bool(sep or cme), ("SEP" if sep else "") + ("+" if sep and cme else "") + ("CME" if cme else "")

    def sep_covered(self, sol, lmst=12.0):
        """True if the Earth date lies inside the downloaded DONKI range (outside it sep_alert is False because it is unknown)."""
        return self.donki_range[0] <= self.utc_date(sol, lmst) <= self.donki_range[1]

    # -- geometry
    def horizon_at(self, az_deg):
        """Horizon elevation (deg) per cell in direction az_deg, linear between the 32 stored azimuths."""
        hz = self.S["horizon_deg"]; x = (az_deg % 360.0) / 11.25; i0 = int(math.floor(x)) % 32; i1 = (i0 + 1) % 32; f = x - math.floor(x)
        return hz[i0].astype(np.float32) * (1 - f) + hz[i1].astype(np.float32) * f

    def cos_incidence(self, el, az):
        e, a = math.radians(el), math.radians(az)
        s = (math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e))
        return np.clip(self._n[0] * s[0] + self._n[1] * s[1] + self._n[2] * s[2], 0.0, None).astype(np.float32)

    def beam_flux(self, ls, el):
        """Direct-beam flux on a surface normal to the sun (W/m2): S0 / r^2 * exp(-tau * m), m = 1/sin(el), capped."""
        if el <= 0: return 0.0
        m = min(1.0 / math.sin(math.radians(el)), self.p["airmass_cap"])
        return SOLAR_CONST / mars_r_au(ls) ** 2 * math.exp(-self.p["tau"] * m)

    # -- dynamic layers
    def dynamic(self, sol, lmst, eot=True):
        key = (int(sol), round(float(lmst), 4), eot)
        if key in self._cache: return self._cache[key]
        ls = self.ls_of_sol(sol, lmst); el, az = sun_position(ls, lmst, eot=eot)
        out = {"sol": int(sol), "lmst": float(lmst), "ls": ls, "sun_el": el, "sun_az": az, "utc_date": self.utc_date(sol, lmst)}
        shape = (self.H, self.W)
        if el > 0:
            shadow = el < self.horizon_at(az)
            ci = self.cos_incidence(el, az); b = self.beam_flux(ls, el)
            ins = np.where(shadow, 0.0, b * ci).astype(np.float32)
            flat = b * math.sin(math.radians(el))
        else:
            shadow = np.ones(shape, bool); ins = np.zeros(shape, np.float32); flat = 0.0
        shadow = shadow | ~np.isfinite(self.S["elevation_m"])
        out["in_shadow"], out["insolation"], out["insolation_flat"] = shadow, ins, float(flat)
        # ground temperature (modelled)
        R = self.rems(sol, lmst); base = R["ground_temp_K"]
        wave = base - self.rems_daymean_ground(sol)                         # diurnal departure at the rover
        z = np.nan_to_num(self.S["dawn_warmth_z"], nan=0.0)
        gt = base + self.p["a_K_per_Wm2"] * (ins - flat) + self.p["kappa_K_per_K"] * (-z) * wave
        gt = np.where(np.isfinite(self.S["elevation_m"]), gt, np.nan).astype(np.float32)
        out["ground_temp_K"] = gt
        out["ground_temp_baseline_K"] = base
        for k in ("air_temp_K", "pressure_Pa", "rh", "uv", "wind"): out[k] = R[k]
        out["rems_sol_used"], out["rems_gap_sols"] = R["rems_sol_used"], R["rems_gap_sols"]
        out["dose_rate_uGy_h"] = (self.rad_rate(sol) * self.dose_factor).astype(np.float32)
        out["sep_alert"], out["sep_kind"] = self.sep_alert(sol, lmst); out["sep_covered"] = self.sep_covered(sol, lmst)
        if len(self._cache) > 6: self._cache.pop(next(iter(self._cache)))
        self._cache[key] = out
        return out

    # -- one cell
    def cell(self, cell_index, sol, lmst):
        r, c = divmod(int(cell_index), self.W)
        out = {"cell": int(cell_index), "row": r, "col": c}
        for k, v in self.S.items():
            if v.ndim == 3: val = [float(x) for x in v[:, r, c]]
            else: val = v[r, c].item()
            if isinstance(val, float) and not np.isfinite(val): val = None
            m = self.meta["layers"].get(k, {})
            out[k] = {"value": val, "units": m.get("units", ""), "class": m.get("cls", "")}
        d = self.dynamic(sol, lmst)
        for k in ("sun_el", "sun_az", "air_temp_K", "pressure_Pa", "rh", "uv", "wind", "sep_alert"):
            v = d[k]; v = None if (isinstance(v, float) and not np.isfinite(v)) else v
            out[k] = {"value": v, "units": CLASS[k][0], "class": CLASS[k][1]}
        for k in ("in_shadow", "insolation", "ground_temp_K", "dose_rate_uGy_h"):
            v = d[k][r, c].item(); v = None if (isinstance(v, float) and not np.isfinite(v)) else v
            out[k] = {"value": v, "units": CLASS[k][0], "class": CLASS[k][1]}
        out["sol"], out["lmst"], out["ls"] = int(sol), float(lmst), d["ls"]
        return out

    # -- safety
    def static_blocked(self, profile, allow_unknown_rough=False):
        sl, ro, vf = self.S["slope_max_deg"], self.S["rough_max_m"], self.S["valid_frac"]
        with np.errstate(invalid="ignore"):
            b = (sl > profile.max_slope_deg) | (ro > profile.rough_max_m) | (vf < profile.valid_frac_min)
        b |= np.isnan(sl) | np.isnan(self.S["elevation_m"])
        if not allow_unknown_rough: b |= np.isnan(ro)
        return b

    def hard_blocked(self, profile, sol=None, lmst=None, allow_unknown_rough=False, daylight=False, tmin_K=None, tmax_K=None, stop_on_sep=False):
        """Static hard limits (as phase4/costs.hard_blocked) plus optional dynamic ones, evaluated at (sol, lmst):
        daylight   - block cells whose horizon hides the sun (shadow or night);
        tmin_K/tmax_K - block cells whose modelled ground temperature leaves the suit limits (SIMULATED limits, set by caller);
        stop_on_sep   - block everything while sep_alert is set (no new EVAs).
        The cumulative dose budget is a path property and stays in the environment / validator."""
        b = self.static_blocked(profile, allow_unknown_rough)
        if sol is None or lmst is None:
            if daylight or tmin_K is not None or tmax_K is not None or stop_on_sep:
                raise ValueError("dynamic limits need sol and lmst")
            return b
        d = self.dynamic(sol, lmst); b = b.copy()
        if daylight: b |= d["in_shadow"]
        with np.errstate(invalid="ignore"):
            if tmin_K is not None: b |= d["ground_temp_K"] < tmin_K
            if tmax_K is not None: b |= d["ground_temp_K"] > tmax_K
        if stop_on_sep and d["sep_alert"]: b[:] = True
        return b
