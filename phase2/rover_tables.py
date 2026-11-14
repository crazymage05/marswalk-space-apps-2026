"""MARSWALK Phase 2: rover and environment tables. Run from e:\\nasa:  python phase2/rover_tables.py"""
import os, sys, re, json, glob, bisect
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import numpy as np, pandas as pd
import marswalk_grid as G

RAW = "data/raw/curiosity"
TAB = os.path.join(G.OUT, "tables"); VEC = os.path.join(G.OUT, "vectors")
os.makedirs(TAB, exist_ok=True); os.makedirs(VEC, exist_ok=True)
W, H = G.WIDTH, G.HEIGHT
S0, S1 = 4500, 4799


def grid(lon, lat):
    x, y = G.lonlat_to_xy(lon, lat); c, r = G.xy_to_pixel(x, y)
    return x, y, c, r


def inroi(c, r):
    c = np.asarray(c); r = np.asarray(r)
    return (c >= 0) & (c < W) & (r >= 0) & (r < H)


def clean(v):
    if isinstance(v, float) and np.isnan(v): return None
    return v.item() if hasattr(v, "item") else v


# ---------------------------------------------------------------- 1 traverse
def traverse():
    wp = json.load(open(f"{RAW}/traverse/MSL_waypoints.json"))["features"]
    df = pd.DataFrame([dict(f["properties"]) for f in wp]).sort_values(["sol", "site", "drive"]).reset_index(drop=True)
    df["x"], df["y"], df["col"], df["row"] = grid(df.lon.values, df.lat.values)
    df["in_roi"] = inroi(df.col, df.row)
    df["campaign"] = (df.sol >= S0) & (df.sol <= S1)
    df.to_csv(f"{TAB}/waypoints.csv", index=False)
    feats = [{"type": "Feature", "properties": {k: clean(v) for k, v in r.items()},
              "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]}} for r in df.to_dict("records")]
    json.dump({"type": "FeatureCollection", "features": feats}, open(f"{VEC}/traverse_waypoints.geojson", "w"))
    tl = json.load(open(f"{RAW}/traverse/MSL_traverse.json"))["features"]
    lf = []; nroi = 0
    for i, f in enumerate(tl):
        g = f["geometry"]; parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        pts = np.array([c for part in parts for c in part], float)
        x, y, c, r = grid(pts[:, 0], pts[:, 1]); m = inroi(c, r)
        mid = pts[len(pts) // 2]
        d = (df.lon - mid[0]) ** 2 + (df.lat - mid[1]) ** 2; sol = int(df.sol.iloc[int(d.values.argmin())])
        pr = {"index": i, "length_m": f["properties"].get("Length"), "sol_nearest_wp": sol,
              "x0": float(x[0]), "y0": float(y[0]), "col0": float(c[0]), "row0": float(r[0]),
              "x1": float(x[-1]), "y1": float(y[-1]), "col1": float(c[-1]), "row1": float(r[-1]),
              "in_roi": bool(m.any()), "n_vertices_in_roi": int(m.sum()), "campaign": bool(S0 <= sol <= S1)}
        nroi += pr["in_roi"]
        lf.append({"type": "Feature", "properties": pr, "geometry": g})
    json.dump({"type": "FeatureCollection", "features": lf}, open(f"{VEC}/traverse_lines.geojson", "w"))
    G.register("tables_traverse", file=["tables/waypoints.csv", "vectors/traverse_waypoints.geojson", "vectors/traverse_lines.geojson"],
        units="x,y metres in grid CRS; col,row fractional pixels (1.0117 m); lon/lat deg; elev_geoid m; tilt deg",
        source="data/raw/curiosity/traverse/MSL_waypoints.json, MSL_traverse.json",
        method="lonlat_to_xy/xy_to_pixel; in_roi = pixel inside 2340x2928 grid; campaign = 4500<=sol<=4799. Line sol is the nearest waypoint to the line midpoint (line features carry no sol).",
        rows={"waypoints": len(df), "lines": len(lf)},
        validation={"waypoints_in_roi": int(df.in_roi.sum()), "waypoints_campaign": int(df.campaign.sum()),
                    "campaign_in_roi": int((df.campaign & df.in_roi).sum()), "lines_in_roi": int(nroi)},
        limitations="Waypoints are end-of-drive positions only; line sol attribution approximate.")
    print("traverse", len(df), "in_roi", int(df.in_roi.sum()), "campaign", int(df.campaign.sum()), "lines", len(lf), nroi)
    return df


# ---------------------------------------------------------------- 2 RAD
def rad():
    obs = []; skipped = [0]
    for t in sorted(glob.glob(f"{RAW}/rad/DATA/**/RAD_RDR_*.TXT", recursive=True)):
        txt = open(t, encoding="latin1").read()
        secs = re.split(r"^\[(\w+): (\d+)\]\s*$", txt, flags=re.M)
        d = {}
        for i in range(1, len(secs), 3):
            name, n, body = secs[i], int(secs[i + 1]), secs[i + 2]
            o = d.setdefault(n, {})
            if name == "OBSERVATION":
                for m in re.finditer(r'^(\w+)=(.*)$', body, re.M): o[m.group(1)] = m.group(2).strip().strip('"')
            elif name in ("DOSIMETRY_TOTAL_DOSE_B", "DOSIMETRY_TOTAL_DOSE_E"):
                m = re.search(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", body)
                if m: o[name[-1]] = float(m.group(0))
        for n, o in sorted(d.items()):
            if len(o.get("START_OBS_MARS", "N/A").split()) != 2: skipped[0] += 1; continue
            sol, lmst = o["START_OBS_MARS"].split()
            obs.append({"file": os.path.basename(t), "sol": int(sol), "lmst": lmst, "utc_start": o.get("START_OBS_UTC"),
                        "duration_s": float(o.get("OBS_DURATION", "nan")),
                        "dose_rate_B_uGy_h": o.get("B", np.nan), "dose_rate_E_uGy_h": o.get("E", np.nan)})
    df = pd.DataFrame(obs)
    df.to_csv(f"{TAB}/rad_observations.csv", index=False)
    v = df.dropna(subset=["dose_rate_E_uGy_h", "dose_rate_B_uGy_h"])
    v = v[(v.dose_rate_E_uGy_h > 0) & (v.dose_rate_B_uGy_h > 0)]
    ps = v.groupby("sol").agg(n_obs=("sol", "size"), mean_E_uGy_h=("dose_rate_E_uGy_h", "mean"), median_E_uGy_h=("dose_rate_E_uGy_h", "median"),
                              mean_B_uGy_h=("dose_rate_B_uGy_h", "mean"), median_B_uGy_h=("dose_rate_B_uGy_h", "median")).reset_index()
    ps["daily_dose_E_uGy"] = ps.mean_E_uGy_h * 24.66; ps["daily_dose_B_uGy"] = ps.mean_B_uGy_h * 24.66
    ps.to_csv(f"{TAB}/rad_per_sol.csv", index=False)
    c = v[(v.sol >= S0) & (v.sol <= S1)]
    cs = {"n_obs": int(len(c)), "sols": int(c.sol.nunique()),
          "mean_E": float(c.dose_rate_E_uGy_h.mean()), "mean_B": float(c.dose_rate_B_uGy_h.mean()),
          "min_E": float(c.dose_rate_E_uGy_h.min()), "max_E": float(c.dose_rate_E_uGy_h.max()),
          "min_B": float(c.dose_rate_B_uGy_h.min()), "max_B": float(c.dose_rate_B_uGy_h.max()),
          "mean_daily_E_uGy": float(c.dose_rate_E_uGy_h.mean() * 24.66), "mean_daily_B_uGy": float(c.dose_rate_B_uGy_h.mean() * 24.66)}
    allr = {"n_obs": int(len(v)), "min_E": float(v.dose_rate_E_uGy_h.min()), "max_E": float(v.dose_rate_E_uGy_h.max()),
            "min_B": float(v.dose_rate_B_uGy_h.min()), "max_B": float(v.dose_rate_B_uGy_h.max())}
    G.register("tables_rad", file=["tables/rad_observations.csv", "tables/rad_per_sol.csv"],
        units="dose rate microGray/hour (B = silicon detector, E = plastic/tissue-like); daily dose microGray = mean rate * 24.66 h",
        source="data/raw/curiosity/rad/DATA/**/RAD_RDR_*.TXT (+ .LBL units)",
        method="Parsed every [OBSERVATION: NN] with DOSIMETRY_TOTAL_DOSE_B/E; per-sol means over observations with positive doses",
        rows={"observations": int(len(df)), "skipped_no_timestamp_NA": skipped[0], "valid_observations": int(len(v)), "sols": int(len(ps))},
        validation={"campaign": cs, "all_time": allr, "expectation": "Mars surface roughly 200-300 uGy/day"},
        limitations="Sparse sampling within a sol; per-sol mean not duration weighted; RAD is rover-fixed, not location-resolved.")
    print("RAD obs", len(df), "valid", len(v), "sols", len(ps)); print("campaign", cs); print("all", allr)


# ---------------------------------------------------------------- 3 REMS
REMS_COLS = ["TIMESTAMP", "LMST", "LTST", "HORIZONTAL_WIND_SPEED", "VERTICAL_WIND_SPEED", "WIND_DIRECTION", "WS_CONFIDENCE_LEVEL",
 "BRIGHTNESS_TEMP", "BRIGHTNESS_TEMP_LONG_TERM_UNCERTAINTY", "BRIGHTNESS_TEMP_SHORT_TERM_UNCERTAINTY", "GTS_CONFIDENCE_LEVEL",
 "BOOM1_LOCAL_AIR_TEMP", "ATS_BOOM1_CONFIDENCE_LEVEL", "BOOM2_LOCAL_AIR_TEMP", "ATS_BOOM2_CONFIDENCE_LEVEL", "AMBIENT_TEMP", "AMBIENT_TEMP_CONFIDENCE_LEVEL",
 "UV_A", "UV_B", "UV_C", "UV_ABC", "UV_D", "UV_E", "UV_A_UNC", "UV_B_UNC", "UV_C_UNC", "UV_ABC_UNC", "UV_D_UNC", "UV_E_UNC", "UVS_CONFIDENCE_LEVEL",
 "LOCAL_RELATIVE_HUMIDITY", "HS_TEMP", "LOCAL_RELATIVE_HUMIDITY_UNCERTAINTY", "VOLUME_MIXING_RATIO", "VOLUME_MIXING_RATIO_UNCERTAINTY",
 "HS_CONFIDENCE_LEVEL", "PS_CONFIGURATION", "PRESSURE", "PRESSURE_UNCERTAINTY", "PS_CONFIDENCE_LEVEL"]


def rems():
    files = sorted(f for f in glob.glob(f"{RAW}/rems/SOL_*/SOL*/*RMD*.TAB")
                   if S0 <= int(re.search(r"SOL(\d+)[\\/][^\\/]*$", f).group(1)) <= S1)
    import csv, io
    recs = []; malformed = 0
    for f in files:   # the raw tables contain a few corrupted lines (e.g. SOL04660); keep only rows with exactly 40 fields
        for ln in open(f, encoding="latin1"):
            row = next(csv.reader([ln], skipinitialspace=True))
            if len(row) != 40 or not re.match(r"^\d+M\d\d:", row[1]): malformed += 1; continue
            recs.append(row)
    d = pd.DataFrame(recs, columns=REMS_COLS)
    num_cols = [c for c in REMS_COLS if c not in ("LMST", "LTST") and not c.endswith("CONFIDENCE_LEVEL") and c != "PS_CONFIGURATION"]
    for c in num_cols: d[c] = pd.to_numeric(d[c], errors="coerce")
    d[num_cols] = d[num_cols].where(d[num_cols] != -999.0)
    lm = d.LMST.str.extract(r"^(\d+)M(\d+):")
    d["sol"] = lm[0].astype(int); d["lmst_hour"] = lm[1].astype(int)
    d["air_K"] = d.AMBIENT_TEMP; d["ground_K"] = d.BRIGHTNESS_TEMP
    keys = {"air_K": "air_K", "ground_K": "ground_K", "pressure": "PRESSURE", "rh": "LOCAL_RELATIVE_HUMIDITY", "uv_abc": "UV_ABC"}
    n0 = {k: int(d[c].notna().sum()) for k, c in keys.items()}
    d.loc[(d.air_K < 100) | (d.air_K > 330), "air_K"] = np.nan
    d.loc[(d.ground_K < 100) | (d.ground_K > 340), "ground_K"] = np.nan
    d.loc[(d.PRESSURE <= 0) | (d.PRESSURE > 2000), "PRESSURE"] = np.nan
    d.loc[(d.LOCAL_RELATIVE_HUMIDITY < 0) | (d.LOCAL_RELATIVE_HUMIDITY > 100), "LOCAL_RELATIVE_HUMIDITY"] = np.nan
    d.loc[d.UV_ABC < 0, "UV_ABC"] = np.nan
    n1 = {k: int(d[c].notna().sum()) for k, c in keys.items()}
    d["air_C"] = d.air_K - 273.15; d["ground_C"] = d.ground_K - 273.15
    out = d.groupby(["sol", "lmst_hour"]).agg(
        n_records=("sol", "size"), air_temp_C=("air_C", "mean"), n_air=("air_C", "count"),
        ground_temp_C=("ground_C", "mean"), n_ground=("ground_C", "count"),
        pressure_Pa=("PRESSURE", "mean"), n_pressure=("PRESSURE", "count"),
        rel_humidity_pct=("LOCAL_RELATIVE_HUMIDITY", "mean"), n_rh=("LOCAL_RELATIVE_HUMIDITY", "count"),
        uv_abc_Wm2=("UV_ABC", "mean"), n_uv=("UV_ABC", "count"),
        uv_a_Wm2=("UV_A", "mean"), uv_b_Wm2=("UV_B", "mean"), uv_c_Wm2=("UV_C", "mean"), uv_d_Wm2=("UV_D", "mean"), uv_e_Wm2=("UV_E", "mean"),
        wind_speed_ms=("HORIZONTAL_WIND_SPEED", "mean"), n_wind=("HORIZONTAL_WIND_SPEED", "count")).reset_index()
    out.round(4).to_csv(f"{TAB}/rems_rmd_campaign_hourly.csv", index=False)

    j = json.load(open(f"{RAW}/rems/nasa_weather_api/weather_msl.json"))["soles"]

    def num(s):
        try: return float(s)
        except Exception: return np.nan
    rows = []; dropped = {}
    for s in j:
        r = {"sol": int(s["sol"]), "terrestrial_date": s["terrestrial_date"], "ls": num(s["ls"])}
        for k in ["min_temp", "max_temp", "pressure", "min_gts_temp", "max_gts_temp"]:
            v = num(s[k])
            if not np.isnan(v):
                bad = (k.endswith("temp") and (v <= -100 or v > 50)) or (k == "pressure" and (v < 300 or v > 1200))
                if bad: dropped[k] = dropped.get(k, 0) + 1; v = np.nan
            r[k] = v
        for k in ["sunrise", "sunset", "local_uv_irradiance_index", "atmo_opacity"]:
            r[k] = None if s[k] == "--" else s[k]
        rows.append(r)
    dd = pd.DataFrame(rows).sort_values("sol"); dd.to_csv(f"{TAB}/rems_daily.csv", index=False)
    c = dd[(dd.sol >= S0) & (dd.sol <= S1)]
    G.register("tables_rems", file=["tables/rems_rmd_campaign_hourly.csv", "tables/rems_daily.csv"],
        units="air_temp_C (AMBIENT_TEMP K-273.15), ground_temp_C (BRIGHTNESS_TEMP K-273.15), pressure_Pa, rel_humidity_pct, UV bands W/m^2, wind m/s; daily API temps C, pressure Pa",
        source="data/raw/curiosity/rems/SOL_*/SOL*/*RMD*.TAB (MODRDR, 40 columns defined in PDS4 .xml labels; no .FMT shipped), nasa_weather_api/weather_msl.json",
        method="Missing -999.00 -> NaN; physical range filters; mean per (sol, LMST hour) with counts. Daily: '--' -> NaN; temps <= -100 C or > 50 C and pressure outside 300-1200 Pa dropped.",
        rows={"rmd_files": len(files), "rmd_records": int(len(d)), "malformed_lines_dropped": malformed, "hourly_rows": int(len(out)), "daily_rows": int(len(dd))},
        validation={"valid_before_filter": n0, "valid_after_filter": n1, "daily_sentinel_dropped": dropped, "campaign_daily_rows": int(len(c)),
                    "campaign_min_temp_C": float(c.min_temp.min()), "campaign_max_temp_C": float(c.max_temp.max())},
        limitations="RMD files exist only for every 5th campaign sol (4500-4705); confidence-level flags not applied; wind mostly missing.")
    print("REMS files", len(files), "records", len(d), "hourly", len(out), "daily", len(dd), "dropped", dropped, n0, n1)


# ---------------------------------------------------------------- 4 images
def images(wp):
    paths = {os.path.splitext(os.path.basename(p))[0]: p for p in glob.glob(f"{RAW}/raw_images/sol*/*/*.JPG")}
    recs = {}
    with open(f"{RAW}/raw_images/raw_image_index_msl.jsonl", encoding="utf8") as fh:
        for line in fh:
            m = re.search(r'"imageid": "([^"]+)"', line)
            if not m or m.group(1) not in paths: continue
            d = json.loads(line); recs[d["imageid"]] = d
    wps = wp.sort_values(["sol", "site", "drive"]).reset_index(drop=True)
    key = {(int(r.site), int(r.drive)): i for i, r in enumerate(wps.itertuples())}
    sols = wps.sol.values
    rows = []; cnt = {"exact": 0, "approx": 0, "no_index_record": 0, "no_waypoint": 0}
    for iid, p in paths.items():
        d = recs.get(iid)
        if d is None: cnt["no_index_record"] += 1; continue
        sol = d["sol"]; ex = d.get("extended") or {}
        if d.get("site") is not None and d.get("drive") is not None and (int(d["site"]), int(d["drive"])) in key:
            idx = key[(int(d["site"]), int(d["drive"]))]; loc = "exact"
        else:
            idx = bisect.bisect_right(sols, sol) - 1; loc = "approx"
            if idx < 0: cnt["no_waypoint"] += 1; continue
        w = wps.iloc[idx]; cnt[loc] += 1
        rows.append({"path": p.replace("\\", "/"), "imageid": iid, "sol": sol, "camera": os.path.basename(os.path.dirname(p)),
                     "date_taken": d.get("date_taken"), "lmst": ex.get("lmst"), "mast_az": ex.get("mast_az"), "mast_el": ex.get("mast_el"),
                     "site": d.get("site"), "drive": d.get("drive"), "wp_site": int(w.site), "wp_drive": int(w.drive),
                     "lon": w.lon, "lat": w.lat, "x": w.x, "y": w.y, "col": w.col, "row": w.row, "localization": loc})
    df = pd.DataFrame(rows).sort_values(["sol", "imageid"]); df.to_csv(f"{TAB}/images_index.csv", index=False)
    G.register("tables_images", file="tables/images_index.csv",
        units="lon/lat deg; x,y metres grid CRS; col,row pixels; mast_az/el deg",
        source="data/raw/curiosity/raw_images/sol*/*/*.JPG + raw_image_index_msl.jsonl (streamed)",
        method="(site,drive) matching a waypoint = exact; else last waypoint with sol <= image sol = approx (end-of-drive position of that waypoint)",
        rows={"files_on_disk": len(paths), "indexed": len(df)}, validation=cnt,
        limitations="Many index records lack site/drive so are approx; images taken before a drive later the same sol get the previous waypoint.")
    print("images files", len(paths), "indexed", len(df), cnt)


if __name__ == "__main__":
    wp = traverse(); rad(); rems(); images(wp)
