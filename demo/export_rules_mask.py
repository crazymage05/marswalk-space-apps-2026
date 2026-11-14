"""Per-cell flight-rule flags for the twin's in-page validator: demo/twin/rules_mask.json.

The twin's world_cells.json stores slope in 0.311 deg steps, so 154 cells just under 25 deg decoded above it (the page
was stricter than phase4/safety_validator.py there). This file carries the validator's own per-cell tests, computed
here from the full-precision nav grid for the nominal profile, so the page's GO/NO-GO equals Python's:
bit 0 slope_max_deg > max_slope_deg (CS-01), bit 1 rough_max_m > rough_max_m or boulder footprint cell (CS-02, phase4 costs.boulder_blocked), bit 2 slope NaN, bit 3 roughness
NaN (CS-03), bit 4 valid_frac NaN or < valid_frac_min (CS-04). uint8 per cell, row-major (cell = row*585 + col),
zlib + base64 (DecompressionStream("deflate") in the page). Run from the repo root.
"""
import sys, os, json, base64, zlib
sys.path.insert(0, os.getcwd())
import numpy as np
from phase4 import costs, astronaut as A

g = costs.load_grid(); P = A.get_profile("nominal")
S, RO, VF = g["slope_max_deg"], g["rough_max_m"], g["valid_frac"]
BOUL = costs.boulder_blocked(g) if P.avoid_boulders else np.zeros_like(RO, bool)
with np.errstate(invalid="ignore"):
    m = ((np.nan_to_num(S, nan=-1) > P.max_slope_deg) * 1 | ((np.nan_to_num(RO, nan=-1) > P.rough_max_m) | BOUL) * 2 | np.isnan(S) * 4
         | np.isnan(RO) * 8 | (np.isnan(VF) | (np.nan_to_num(VF, nan=0) < P.valid_frac_min)) * 16).astype(np.uint8)
blob = zlib.compress(m.tobytes(), 9)
out = dict(w=g["width"], h=g["height"], profile=dict(name=P.name, max_slope_deg=P.max_slope_deg, rough_max_m=P.rough_max_m, valid_frac_min=P.valid_frac_min),
           bits={"1": "CS-01 slope", "2": "CS-02 roughness or boulder footprint", "4": "CS-03 slope unknown", "8": "CS-03 roughness unknown", "16": "CS-04 data confidence"},
           source="demo/export_rules_mask.py from data/processed/roi/nav_grid_4m.npz", data=base64.b64encode(blob).decode())
json.dump(out, open("demo/twin/rules_mask.json", "w"))
print("cells flagged:", {k: int(((m & int(k)) > 0).sum()) for k in out["bits"]}, "| file", round(len(blob) / 1e3), "kB compressed")
