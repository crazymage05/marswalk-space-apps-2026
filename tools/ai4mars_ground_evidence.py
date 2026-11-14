"""
I3: aggregate AI4Mars-model class shares per registered drive position onto the 4 m nav grid (585 x 732,
cell = row*585+col, 1 m position / 4) as a sparse layer, and compare with the corridor map demo/twin/material_4m.json.
Label: derived (rover camera, ML model). Output: data/processed/roi/world/rover_ground_evidence_4m.json
"""
import base64, json, os, collections
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 585, 732
d = json.load(open(os.path.join(HERE, "data/processed/roi/ai4mars_campaign_frames.json")))
CLASSES = d["classes"]
m = json.load(open(os.path.join(HERE, "demo/twin/material_4m.json")))
MW, MH = m["width"], m["height"]
mat = np.frombuffer(base64.b64decode(m["data"]), np.uint8).reshape(MH, MW)
MC = ["bedrock", "sand", "pebbly"]
OC0, OR0 = m["origin_col_1m"], m["origin_row_1m"]      # 336, 577 on the 1 m grid

# group by registered position (1 m grid coordinates, rounded to 0.01 as in the CSV)
g = collections.defaultdict(list)
used = [f for f in d["frames"] if f["camera"] == "NAV_LEFT_B"]   # Mastcam frames: dark/vignetted/sky-filled, no AI4Mars Mastcam test set -> excluded
for f in used:
    g[(round(f["col_reg"], 2), round(f["row_reg"], 2))].append(f)

cells = collections.defaultdict(list)
pos_rows = []
for (c1, r1), fr in g.items():
    lo = {c: float(np.mean([f["lower_half"][c] for f in fr])) for c in CLASSES}
    ff = {c: float(np.mean([f["full_frame"][c] for f in fr])) for c in CLASSES}
    col4, row4 = int(c1 // 4), int(r1 // 4)
    cells[row4 * W + col4].append((len(fr), lo, ff, (c1, r1), sorted({f["sol"] for f in fr})))
    # material cell containing this 1 m position
    mj, mi = int((c1 - OC0) // 4), int((r1 - OR0) // 4)
    inside = 0 <= mi < MH and 0 <= mj < MW
    pos_rows.append({"col_reg": c1, "row_reg": r1, "n_images": len(fr), "lower": lo, "full": ff, "mi": mi, "mj": mj, "inside": inside,
                     "mat": int(mat[mi, mj]) if inside else None,
                     "mat3x3": np.bincount(mat[max(0, mi - 1):mi + 2, max(0, mj - 1):mj + 2].ravel(), minlength=3).tolist() if inside else None})

layer = {}
for cell, lst in sorted(cells.items()):
    n = sum(x[0] for x in lst)
    lo = {c: sum(x[0] * x[1][c] for x in lst) / n for c in CLASSES}
    layer[str(cell)] = {"n_images": n, "n_positions": len(lst), "sand_share_near": round(lo["sand"], 4),
                        "shares_lower_half": {c: round(v, 4) for c, v in lo.items()},
                        "sols": sorted({s for x in lst for s in x[4]})}

ins = [p for p in pos_rows if p["inside"]]
print("positions", len(pos_rows), "nav cells", len(layer), "inside material map", len(ins))

# agreement tables (counts of positions): rows = material class at the rover cell, cols = dominant AI class (lower half)
def dom(sh): return max(CLASSES, key=lambda c: sh[c])
conf = np.zeros((3, 4), int); conf_img = np.zeros((3, 4), int)
for p in ins:
    conf[p["mat"], CLASSES.index(dom(p["lower"]))] += 1
    conf_img[p["mat"], CLASSES.index(dom(p["lower"]))] += p["n_images"]
sand_thr = 0.2
bi = np.zeros((2, 2), int)     # rows: material sand yes/no ; cols: AI sand share >= thr yes/no
for p in ins:
    bi[int(p["mat"] == 1), int(p["lower"]["sand"] >= sand_thr)] += 1
# also 3x3 neighbourhood: material sand share vs AI sand share
x = np.array([p["mat3x3"][1] / sum(p["mat3x3"]) for p in ins]); y = np.array([p["lower"]["sand"] for p in ins])
corr = float(np.corrcoef(x, y)[0, 1]) if len(ins) > 2 and x.std() > 0 and y.std() > 0 else None
mean_sand_by_mat = {MC[k]: (float(np.mean([p["lower"]["sand"] for p in ins if p["mat"] == k])) if any(p["mat"] == k for p in ins) else None) for k in range(3)}
out = {"label": "derived (rover camera, ML model): sand share of the lower (near-field) half of Navcam/Mastcam frames, SegFormer-B0 fine-tuned on AI4Mars; "
                "not measured ground truth. Frames look up to ~30 m ahead of the rover, so the cell is the rover position, not the cell imaged.",
       "grid": {"width": W, "height": H, "cell_m": 4.0, "cell_index": "row*585+col; col=floor(col_reg/4), row=floor(row_reg/4) (registered 1 m grid / 4)"},
       "n_frames_used": len(used), "n_frames_excluded_mastcam": d["n_images"] - len(used), "camera_used": "NAV_LEFT_B", "n_positions": len(pos_rows), "n_cells": len(layer), "cells": layer,
       "agreement_vs_material_4m": {"material_map_classes": MC, "ai_classes": CLASSES,
            "counts_positions_rows_material_cols_ai_dominant": conf.tolist(), "counts_images_same_layout": conf_img.tolist(),
            "positions_inside_material_map": len(ins), "positions_outside": len(pos_rows) - len(ins),
            "binary_sand": {"ai_sand_share_threshold": sand_thr, "rows": ["material not sand", "material sand"], "cols": ["ai < thr", "ai >= thr"], "counts": bi.tolist()},
            "pearson_r_material3x3_sand_fraction_vs_ai_sand_share": corr, "mean_ai_sand_share_by_material_class": mean_sand_by_mat,
            "alignment": f"material cell of a position = ((row_reg-{OR0})//4, (col_reg-{OC0})//4); nav cell = (row_reg//4, col_reg//4); "
                         f"origin of material map on the 4 m grid = ({OC0 / 4}, {OR0 / 4})"}}
os.makedirs(os.path.join(HERE, "data/processed/roi/world"), exist_ok=True)
json.dump(out, open(os.path.join(HERE, "data/processed/roi/world/rover_ground_evidence_4m.json"), "w"), indent=1)
print("material x ai (positions)\n", conf, "\nimages\n", conf_img, "\nbinary sand\n", bi, "\nr", corr, mean_sand_by_mat)
print("material class counts at positions", np.bincount([p["mat"] for p in ins], minlength=3))
