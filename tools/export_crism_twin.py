"""Resample the CRISM mineral summary parameters onto the twin's 4.047 m planning grid -> demo/twin/crism.json.

usage: python tools/export_crism_twin.py

Georeferencing: the ROI rasters (18.2 m CRISM, 4 m DTM grid) cover the same box, and build_twin_demo.py maps any aligned ROI
raster onto the twin grid by proportion (cell centre (i+0.5)/H of the raster rows). This script uses the same proportional
mapping (bilinear instead of nearest, so local maxima are not plateaus) and, as a self-check, reproduces the existing
data.json overlays["hyd"] (BD1900_2) with the nearest-neighbour rule and requires an exact match.

Values written: for each mineral group, the mean of its parameters' percentile ranks inside the ROI (rank among the
18 m pixels, 0..1), resampled to the grid and stored as 8-bit (q/255 = rank). No detection thresholds are invented:
a pixel is "strong" only relative to the rest of this ROI.

Meanings are from Viviano-Beck et al. 2014, JGR Planets 119, 1403-1431 (summary products table, as reproduced in
Table 1 of Hare/Marin-Yaseli de la Parra et al. 2017, arXiv:1701.01726, and the CRISM PDS summary parameter reference).
BD920_2 is dropped: its meaning (Fe2+ and Fe3+ absorptions 0.4-1.02 um, separates low/high-Ca pyroxene) is not a single
mineral class, so it cannot be put in one group honestly.
"""
import base64, datetime, json, os, zlib
import numpy as np
import rasterio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIF = os.path.join(ROOT, "data", "processed", "roi", "crism_mineral_params.tif")
REG = os.path.join(ROOT, "data", "processed", "roi", "registry", "crism_mineral_params.json")
DATA = os.path.join(ROOT, "demo", "twin", "data.json")
OUT = os.path.join(ROOT, "demo", "twin", "crism.json")

# group id -> (label, parameters, what the paper's table says each parameter indicates)
GROUPS = {
    "hydrated": ("Hydrated minerals", ["BD1900_2"], "BD1900_2: 1.9 um H2O band depth; bound molecular H2O except monohydrated sulfates"),
    "sulfates": ("Hydrated sulfates", ["SINDEX2"], "SINDEX2: convexity at 2.29 um from 2.1 and 2.4 um absorptions; mono- and polyhydrated sulfates"),
    "monosulfates": ("Monohydrated sulfates", ["BD2100_2"], "BD2100_2: 2.1 um shifted H2O band; monohydrated sulfates"),
    "gypsum": ("Gypsum / alunite", ["BD1750_2"], "BD1750_2: 1.75 um H2O band depth; gypsum, alunite"),
    "femgclay": ("Fe/Mg clays", ["D2300", "BD2290"], "D2300: 2.3 um drop-off, hydroxylated Fe,Mg silicates; BD2290: 2.29 um Mg,Fe-OH band (also CO2 ice, not expected here)"),
    "alclay": ("Al clays / kaolinite", ["BD2165", "MIN2200"], "BD2165: 2.165 um Al-OH band, pyrophyllite, kaolinites; MIN2200: Si-OH doublet, kaolinites"),
    "opal": ("Silica / opal (Si-OH)", ["MIN2250"], "MIN2250: 2.21 and 2.26 um Si-OH bands; opals"),
    "ferric": ("Ferric oxides (incl. hematite)", ["BD530_2", "BD860_2"], "BD530_2 and BD860_2: Fe3+ absorptions at 0.53 and 0.86 um; together they flag crystalline hematite"),
    "olivine": ("Olivine", ["OLINDEX3"], "OLINDEX3: broad absorption near 1 um; olivines"),
    "pyroxene": ("Pyroxene", ["LCPINDEX2", "HCPINDEX2"], "LCPINDEX2: broad absorption near 1.8 um; HCPINDEX2: broad absorption near 2.12 um; low- and high-Ca pyroxene"),
}
DROPPED = {"BD920_2": "Fe2+ and Fe3+ absorptions 0.4-1.02 um, mixed meaning; not assigned to one mineral class"}


def rank01(a):
    """Percentile rank (0..1) of every pixel among the valid pixels of the ROI."""
    v = np.isfinite(a); out = np.full(a.shape, np.nan)
    order = a[v].argsort().argsort()
    out[v] = (order + 0.5) / v.sum()
    return out


def bilinear(a, H, W):
    r, c = a.shape
    y = np.clip((np.arange(H) + 0.5) / H * r - 0.5, 0, r - 1); x = np.clip((np.arange(W) + 0.5) / W * c - 0.5, 0, c - 1)
    y0 = np.minimum(y.astype(int), r - 2); x0 = np.minimum(x.astype(int), c - 2); fy = (y - y0)[:, None]; fx = (x - x0)[None, :]
    return (a[np.ix_(y0, x0)] * (1 - fy) * (1 - fx) + a[np.ix_(y0 + 1, x0)] * fy * (1 - fx)
            + a[np.ix_(y0, x0 + 1)] * (1 - fy) * fx + a[np.ix_(y0 + 1, x0 + 1)] * fy * fx)


def main():
    meta = json.load(open(DATA)); G = meta["grid"]; W, H = G["w"], G["h"]
    ds = rasterio.open(TIF); names = list(ds.descriptions)
    P = {n: ds.read(i + 1).astype(np.float64) for i, n in enumerate(names)}
    # self-check against the existing overlay (same alignment as the shipped hydrated layer)
    ri = np.minimum(((np.arange(H) + 0.5) / H * P["BD1900_2"].shape[0]).astype(int), P["BD1900_2"].shape[0] - 1)
    ci = np.minimum(((np.arange(W) + 0.5) / W * P["BD1900_2"].shape[1]).astype(int), P["BD1900_2"].shape[1] - 1)
    a = P["BD1900_2"]; lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
    mine = np.clip(np.nan_to_num((a - lo) / (hi - lo)) * 255, 0, 255).astype(np.uint8)
    ov = meta["overlays"]["hyd"]; theirs = np.frombuffer(base64.b64decode(ov["data"]), np.uint8).reshape(ov["h"], ov["w"])
    assert theirs.shape == mine.shape and (theirs == mine).all(), "CRISM raster does not line up with the existing hydrated overlay"
    print(f"alignment check: native 8-bit BD1900_2 equals data.json overlays.hyd exactly ({mine.shape[1]}x{mine.shape[0]})")
    assert ri.max() < a.shape[0] and ci.max() < a.shape[1]

    groups = {}
    for gid, (label, params, note) in GROUPS.items():
        for p in params: assert p in P, p
        rk = np.nanmean(np.stack([rank01(P[p]) for p in params]), axis=0)
        rk = rank01(rk)                                    # re-rank the group mean so q/255 is again a percentile within the ROI
        g = np.clip(bilinear(np.nan_to_num(rk, nan=0.0), H, W), 0, 1)
        q = np.round(g * 255).astype(np.uint8)
        groups[gid] = {"label": label, "params": params, "meaning": note,
                       "data": base64.b64encode(zlib.compress(np.diff(q.astype(np.int16), axis=1, prepend=0).astype(np.uint8).tobytes(), 9)).decode()}
        print(f"{gid:13s} {','.join(params):22s} bytes(b64)={len(groups[gid]['data'])}")
    reg = json.load(open(REG))
    out = {"w": W, "h": H, "cell_m": G["cell_m"], "dtype": "u1", "encoding": "zlib+base64 of row-wise differences (mod 256), row-major, W x H; decode: inflate, then running sum mod 256 along each row",
           "scale": "q/255 = percentile rank (0..1) of the group among the ROI's 18 m CRISM pixels (mean of member-parameter ranks, re-ranked)",
           "groups": groups, "dropped": DROPPED,
           "provenance": {"source_file": "data/processed/roi/crism_mineral_params.tif", "source_products": reg.get("source_products"),
                          "source_method": reg.get("method"), "source_resolution_m": reg.get("resolution_m"),
                          "method": "percentile rank within the ROI per parameter, mean over the group's parameters, re-rank, bilinear resample of the 18 m pixels to the twin 4.047 m grid by proportional mapping (as build_twin_demo.py)",
                          "meanings": "Viviano-Beck et al. 2014, JGR Planets 119:1403-1431 (summary products table)",
                          "caveat": "CRISM maps minerals from orbit, not elements; 18 m pixels; a strong signal is a lead to check, not a confirmation. No detection threshold is applied.",
                          "generated": datetime.date.today().isoformat(), "script": "tools/export_crism_twin.py"}}
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print("wrote", OUT, f"{os.path.getsize(OUT) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
