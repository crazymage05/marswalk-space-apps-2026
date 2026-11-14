"""MARSWALK Phase 2 - CRISM MTRDR summary parameters, THEMIS IR brightness temperature, MOLA context.
Run from e:\\nasa:  python phase2/spectral_thermal.py   (no flags; rerunnable, overwrites outputs)"""
import os, re, sys, glob, json, warnings
sys.path.insert(0, os.getcwd())
import numpy as np, rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import Affine
from rasterio.crs import CRS as RCRS
import marswalk_grid as G

warnings.simplefilter("ignore")
RAW = os.path.join("data", "raw")
CRISM_IDS = ["frt000058a3_07_if165j_mtr3", "frt0000b6f1_07_if165j_mtr3", "hrl0000baba_07_if182j_mtr3"]
MIN_PARAMS = ["D2300", "BD2290", "MIN2250", "BD2100_2", "BD1900_2", "BD1750_2", "SINDEX2", "MIN2200", "BD2165",
              "OLINDEX3", "LCPINDEX2", "HCPINDEX2", "BD530_2", "BD860_2", "BD920_2"]
report = {}


def warp_to(src_arr, src_tf, src_crs, factor, resamp=Resampling.bilinear):
    """src_arr (bands,h,w) float32 with NaN = invalid -> ROI grid at factor, NaN nodata."""
    p = G.profile(factor)
    out = np.full((src_arr.shape[0], p["height"], p["width"]), np.nan, np.float32)
    for i in range(src_arr.shape[0]):
        reproject(src_arr[i], out[i], src_transform=src_tf, src_crs=src_crs, src_nodata=np.nan,
                  dst_transform=p["transform"], dst_crs=G.CRS, dst_nodata=np.nan, resampling=resamp)
    return out


# ---------------------------------------------------------------- A. CRISM
def hdr_band_names(path):
    t = open(path, errors="ignore").read()
    m = re.search(r"band names\s*=\s*\{(.*?)\}", t, re.S)
    return [s.strip() for s in m.group(1).replace("\n", " ").split(",") if s.strip()]


def run_crism():
    stacks, names_ref = {}, None
    for pid in CRISM_IDS:
        d = os.path.join(RAW, "mro", "crism", pid)
        su = [f for f in glob.glob(os.path.join(d, "*_SU*_MTR3.*")) if f.upper().endswith(".LBL")][0]
        names = hdr_band_names(su[:-4] + ".HDR")
        # LBL (PDS driver) georeferencing is used: it follows the label offsets (PDS pixel-centre convention);
        # the ENVI .HDR origin is shifted by one 18 m pixel relative to it.
        with rasterio.open(su) as ds:
            assert ds.count == len(names), (ds.count, len(names))
            a = ds.read().astype("float32"); tf, crs = ds.transform, ds.crs
            shape = (ds.width, ds.height)
        a[~np.isfinite(a) | (a >= 65535) | (a < -1e30)] = np.nan
        stacks[pid] = warp_to(a, tf, crs, 1 / 18)
        names_ref = names_ref or names
        assert names == names_ref
        valid = np.isfinite(stacks[pid])
        pct_any = 100 * valid.any(0).mean()
        tag = f"crism_su_{pid.split('_')[0]}"
        G.write_tif(tag, stacks[pid], 1 / 18, np.nan,
                    {"source": os.path.basename(su), "src_crs": crs.to_proj4(), "src_size": f"{shape[0]}x{shape[1]}"}, names)
        G.register(tag, file=f"{tag}.tif", units="unitless band depth / index (CRISM summary parameters)",
                   resolution_m=G.RES * 18, source_products=[os.path.basename(su)],
                   method="PDS LBL georef, masked 65535/-1e30, bilinear warp to ROI grid factor 1/18",
                   validation=f"{pct_any:.1f}% of ROI cells valid (any band); {len(names)} bands",
                   limitations="about 1 pixel (18 m) georeference ambiguity between LBL and ENVI HDR; atmospheric/aerosol residuals in parameters")
        report[pid] = dict(crs=crs.to_proj4(), size=shape, pct_roi_valid=round(pct_any, 1), bands=len(names))
        print(pid, report[pid])
    names = names_ref
    use = [n for n in MIN_PARAMS if n in names]
    idx = [names.index(n) for n in use]
    st = np.stack([stacks[p][idx] for p in CRISM_IDS])          # (prod, band, h, w)
    med = np.nanmedian(st, axis=0).astype("float32")
    cnt = np.isfinite(st).sum(0).astype("float32")
    G.write_tif("crism_mineral_params", med, 1 / 18, np.nan, {"products": ",".join(CRISM_IDS), "stat": "median over products"}, use)
    G.write_tif("crism_mineral_params_count", cnt, 1 / 18, np.nan, {"note": "valid products per parameter"}, use)
    pm = {n: round(100 * float(np.isfinite(med[i]).mean()), 1) for i, n in enumerate(use)}
    G.register("crism_mineral_params", file="crism_mineral_params.tif", units="unitless CRISM summary parameters",
               resolution_m=G.RES * 18, source_products=CRISM_IDS, method="per-pixel nanmedian of the 3 products' SU stacks",
               validation=f"valid % by param: {pm}",
               limitations="valid-count layer in crism_mineral_params_count.tif; products differ in date/aerosol/resolution (hrl is 36 m)")
    report["mineral"] = dict(params=use, pct_valid=pm, missing=[n for n in MIN_PARAMS if n not in names], all_bands=names)
    print(report["mineral"]["params"], pm)
    return med, use


# ---------------------------------------------------------------- B. THEMIS
def themis_meta(imgpath):
    d = os.path.dirname(imgpath); base = os.path.splitext(os.path.basename(imgpath))[0]
    xml = [f for f in glob.glob(os.path.join(d, "*.XML")) if os.path.basename(f).upper() == base.upper() + ".XML"]
    if xml:                                      # PDS4 (IRPBT4)
        t = open(xml[0], errors="ignore").read()
        g = lambda k: re.search(rf"<(?:[A-Za-z_]+:)?{k}[^>]*>\s*([^<\s]+)", t).group(1)
        h, m, s = g("local_true_solar_time").split(":")
        return dict(lst=int(h) + int(m) / 60 + float(s) / 3600, start=g("start_date_time")[:19], ls=float(g("solar_longitude")),
                    inc=float(g("incidence_angle")), band=9, ver="PBT4")
    t = open(imgpath, "rb").read(6000).decode("latin1")   # PDS3 (IRPBT2) attached label
    g = lambda k: re.search(rf"^{k}\s*=\s*\"?([^\s\"<]+)", t, re.M).group(1)
    return dict(lst=float(g("LOCAL_TIME")), start=g("START_TIME")[:19], ls=float(g("SOLAR_LONGITUDE")),
                inc=float(g("INCIDENCE_ANGLE")), band=int(g("BAND_NUMBER")), ver="PBT2")


def run_themis():
    files = [f for f in glob.glob(os.path.join(RAW, "ody", "themis", "*", "*")) if f.upper().endswith("PBT.IMG")]
    files.sort(key=lambda f: os.path.basename(f).upper())
    recs = []
    for f in files:
        pid = os.path.splitext(os.path.basename(f))[0].upper()
        m = themis_meta(f)
        with rasterio.open(f) as ds:
            a = ds.read(1).astype("float32"); crs, tf = ds.crs, ds.transform
            sc = ds.scales[0] if ds.scales else 1.0; off = ds.offsets[0] if ds.offsets else 0.0
        a = a * sc + off
        a[~np.isfinite(a) | (a < 140) | (a > 320)] = np.nan     # drops NULL=0 and -3.4e38
        w = warp_to(a[None], tf, crs, 1 / 100)[0]
        cov = 100 * float(np.isfinite(w).mean())
        m.update(pid=pid, arr=w, cov=cov, crs=crs.to_proj4(), day=6 <= m["lst"] < 18)
        recs.append(m)
        rng = f"{np.nanmin(w):.1f}-{np.nanmax(w):.1f}" if cov else "none"
        print(f"{pid} {m['ver']} {m['start']} LST={m['lst']:.2f} band{m['band']} cov={cov:.0f}% T={rng}")
    ok = [r for r in recs if r["cov"] >= 50]
    skipped = [(r["pid"], round(r["cov"])) for r in recs if r["cov"] < 50]
    out = {}
    for kind in ("day", "night"):
        sel = sorted([r for r in ok if r["day"] == (kind == "day")], key=lambda r: r["start"])
        if not sel:
            out[kind] = 0; print("NO", kind, "images"); continue
        stack = np.stack([r["arr"] for r in sel])
        names = [f"{r['pid']}_{r['start'][:10]}_LST{r['lst']:.1f}" for r in sel]
        G.write_tif(f"themis_{kind}_bt_k", stack, 1 / 100, np.nan, {"unit": "K", "band": "9 (12.57 um)"}, names)
        G.write_tif(f"themis_{kind}_median_k", np.nanmedian(stack, 0).astype("float32"), 1 / 100, np.nan,
                    {"unit": "K", "n_images": len(sel)}, [f"{kind}_median"])
        lo, hi = min(r["lst"] for r in sel), max(r["lst"] for r in sel)
        G.register(f"themis_{kind}_median_k", file=f"themis_{kind}_median_k.tif", stack_file=f"themis_{kind}_bt_k.tif",
                   units="K (brightness temperature, band 9 12.57 um)",
                   resolution_m=G.RES * 100, source_products=[r["pid"] for r in sel],
                   method="THEMIS IRPBT2/IRPBT4 sinusoidal, bilinear warp, median across images",
                   validation=f"{len(sel)} images, LST {lo:.1f}-{hi:.1f} h",
                   limitations="mixed seasons and local times: median is not a calibrated thermal inertia; LST 6-7 h or 17-18 h images are near-terminator")
        out[kind] = dict(n=len(sel), lst=(round(lo, 2), round(hi, 2)), lst_list=sorted(round(r["lst"], 1) for r in sel))
    report["themis"] = dict(total=len(recs), usable=len(ok), skipped_low_cov=skipped,
                            crs=sorted({r["crs"].split("lon_0=")[0] for r in recs}), **out)
    print(report["themis"])
    return out


# ---------------------------------------------------------------- C. MOLA
def run_mola():
    f = os.path.join(RAW, "mgs", "mola", "megt90n000fb", "MEGT90N000FB.IMG")
    with rasterio.open(f) as ds:
        a = ds.read(1)
    # MEGDR: 32 px/deg, west edge 0 E, north edge 90 N. Georef built explicitly (label vs HDR origins disagree by ~3 px).
    sph = RCRS.from_proj4("+proj=longlat +R=3396190 +no_defs")
    r0, r1, c0, c1 = int(93 * 32), int(97 * 32), int(135 * 32), int(140 * 32)
    sub = a[r0:r1, c0:c1].astype("float32")
    tf2 = Affine(1 / 32, 0, c0 / 32, 0, -1 / 32, 90 - r0 / 32)
    w = warp_to(sub[None], tf2, sph, 1 / 100)[0]
    G.write_tif("mola_context_m", w, 1 / 100, np.nan, {"datum": "MOLA areoid", "native_res_m": 1853}, ["elevation_m"])
    mean = float(np.nanmean(w))
    G.register("mola_context_m", file="mola_context_m.tif", units="m above MOLA areoid", resolution_m=G.RES * 100,
               source_products=["MEGT90N000FB"], method="32 ppd MEGDR, bilinear to 101 m grid (interpolated, no new detail)",
               validation=f"ROI mean {mean:.1f} m, range {np.nanmin(w):.0f}..{np.nanmax(w):.0f}",
               limitations="native ~1.85 km: regional context only")
    rep = dict(mean=round(mean, 1), min=float(np.nanmin(w)), max=float(np.nanmax(w)))
    dtm = os.path.join(G.OUT, "elevation_m.tif")
    if os.path.exists(dtm):
        with rasterio.open(dtm) as d:
            e = d.read(1, out_shape=(d.height // 8, d.width // 8)).astype("float32")
            if d.nodata is not None and not np.isnan(d.nodata): e[e == d.nodata] = np.nan
        rep["hirise_dtm_mean"] = round(float(np.nanmean(e)), 1)
        rep["mola_minus_dtm"] = round(mean - rep["hirise_dtm_mean"], 1)
    else:
        rep["hirise_dtm_mean"] = None
    report["mola"] = rep; print(rep)


# ---------------------------------------------------------------- quicklook
def quicklook(med, use, th):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    items = [(f"CRISM {n} (median)", med[use.index(n)]) for n in ["D2300", "BD1900_2", "OLINDEX3", "BD530_2"] if n in use]
    for kind in ("day", "night"):
        p = os.path.join(G.OUT, f"themis_{kind}_median_k.tif")
        if th.get(kind):
            items.append((f"THEMIS {kind} median K", rasterio.open(p).read(1)))
    items.append(("MOLA elevation m", rasterio.open(os.path.join(G.OUT, "mola_context_m.tif")).read(1)))
    n = len(items); nc = (n + 1) // 2
    fig, ax = plt.subplots(2, nc, figsize=(3.6 * nc, 9)); ax = ax.ravel()
    for a_, (t, arr) in zip(ax, items):
        v = arr[np.isfinite(arr)]
        im = a_.imshow(arr, cmap="viridis", vmin=np.percentile(v, 2) if v.size else 0, vmax=np.percentile(v, 98) if v.size else 1)
        a_.set_title(t, fontsize=9); a_.set_xticks([]); a_.set_yticks([]); plt.colorbar(im, ax=a_, fraction=0.04)
    for a_ in ax[n:]: a_.axis("off")
    plt.tight_layout(); os.makedirs(os.path.join(G.OUT, "quicklook"), exist_ok=True)
    plt.savefig(os.path.join(G.OUT, "quicklook", "spectral_thermal.png"), dpi=110); plt.close()


if __name__ == "__main__":
    med, use = run_crism()
    th = run_themis()
    run_mola()
    quicklook(med, use, th)
    os.makedirs(G.REGISTRY, exist_ok=True)
    json.dump(report, open(os.path.join(G.REGISTRY, "spectral_thermal_report.json"), "w"), indent=1, default=str)
    print("done")
