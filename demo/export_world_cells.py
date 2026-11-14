#!/usr/bin/env python3
"""Export the per-cell world layers the twin's inspector shows -> demo/twin/world_cells.json.

Each layer is a [732, 585] grid (cell = row*585 + col, row 0 north, same cells as the twin and the planner) stored as
quantised integers: value = offset + code*scale, code 255 (uint8) or 65535 (uint16) = no data. Channels are zlib-compressed
then base64-coded; the page decodes them with DecompressionStream("deflate").

    python demo/export_world_cells.py        (needs data/processed/roi/world/*, phase4/world.py, demo/twin/data.json)
"""
import base64, json, os, sys, zlib
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from phase4.world import World  # noqa: E402

OUT = os.path.join(ROOT, "demo", "twin", "world_cells.json")
# name -> (source key or callable, dtype, label, units, class, note)
LAYERS = [
    ("slope_max_deg", "u1", "Steepest 1 m slope", "deg", None, "DTM slope, max of the 4x4 1 m pixels in the cell"),
    ("rough_max_m", "u2", "Roughness (5 m plane-fit residual)", "m", None, "NaN where the roughness window was invalid"),
    ("loose", "u1", "Loose ground index", "0-1", None, "THEMIS dawn temperature, about 100 m pixels"),
    ("rock_frac", "u1", "Rock area fraction", "0-1", None, "walk corridor only"),
    ("ground_type", "u1", "Ground type", "class", None, "0 bedrock, 1 sand, 2 pebbly; corridor only"),
    ("hydration", "u1", "Hydration index (CRISM)", "index", None, "CRISM, about 18 m pixels"),
    ("sulfate", "u1", "Sulfate index (CRISM)", "index", None, "CRISM, about 18 m pixels"),
    ("sky_view", "u1", "Sky-view factor", "0-1", None, "from the horizon in 32 directions"),
    ("shielding_factor", "u1", "Shielding factor (dose relative to Curiosity's track)", "x", "modelled", "sky_view / mean sky_view on Curiosity's track cells"),
    ("dtm_uncert_m", "u2", "DTM uncertainty", "m", None, "|DTM A - aligned DTM B|"),
    ("dist_to_rover_track_m", "u2", "Distance to Curiosity's track", "m", None, "registered drive path"),
    ("valid_frac", "u1", "Valid terrain fraction", "0-1", None, "share of valid 1 m pixels"),
]


def quantise(a, dt):
    a = np.asarray(a, np.float64)
    ok = np.isfinite(a)
    top = 254 if dt == "u1" else 65534
    lo, hi = (float(a[ok].min()), float(a[ok].max())) if ok.any() else (0.0, 1.0)
    scale = (hi - lo) / top if hi > lo else 1.0
    q = np.where(ok, np.round((a - lo) / scale), top + 1).astype(np.uint8 if dt == "u1" else np.uint16)
    return q, lo, scale


def main():
    w = World.load()
    S = dict(w.S)
    S["shielding_factor"] = w.dose_factor
    ground = S["ground_type"].astype(np.float32); ground[S["ground_type"] < 0] = np.nan; S["ground_type"] = ground
    H, W = S["elevation_m"].shape
    tw = json.load(open(os.path.join(ROOT, "demo", "twin", "data.json")))
    G = tw["grid"]; assert (G["w"], G["h"]) == (W, H), "twin grid differs from the world grid"
    ts = np.frombuffer(base64.b64decode(tw["slope"]), np.uint8).reshape(H, W).astype(float)
    ref = S["slope_max_deg"]; ok = np.isfinite(ref)
    print("twin slope vs world slope_max: max |diff| %.2f deg, mean %.3f" % (np.abs(ts[ok] - ref[ok]).max(), np.abs(ts[ok] - ref[ok]).mean()))
    out = {"width": W, "height": H, "cell_m": float(w.cell_m), "dose_reference": {"sky_ref": w.sky_ref}, "layers": {}}
    raw = 0
    for name, dt, label, units, cls, note in LAYERS:
        q, lo, sc = quantise(S[name], dt)
        blob = zlib.compress(q.tobytes(), 9); raw += len(blob)
        meta = w.meta["layers"].get(name, {})
        out["layers"][name] = {"label": label, "units": units, "class": cls or meta.get("cls", "derived"), "source": meta.get("source", note), "note": note,
                               "dtype": dt, "offset": lo, "scale": sc, "nodata": 255 if dt == "u1" else 65535, "data": base64.b64encode(blob).decode()}
        print("%-22s %s  %s..%s  %6.0f KB" % (name, dt, "%.4g" % lo, "%.4g" % (lo + sc * (254 if dt == "u1" else 65534)), len(blob) / 1024))
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("wrote", OUT, "%.2f MB" % (os.path.getsize(OUT) / 1e6))


if __name__ == "__main__":
    main()
