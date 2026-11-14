"""THEMIS images inside the REMS window: metadata (UTC, LTST), pixel-block averages of the world model. Helper for calibrate/validate."""
import glob, os, re, sys, datetime as dt
import numpy as np, rasterio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from phase4 import world as wm
ROI = wm.ROI


def themis_images():
    out = []
    for f in ("themis_day_bt_k", "themis_night_bt_k"):
        ds = rasterio.open(os.path.join(ROI, f + ".tif"))
        for b, name in enumerate(ds.descriptions, 1):
            pid, date, lst = name.split("_"); lst = float(lst[3:])
            xml = glob.glob(os.path.join(ROOT, "data", "raw", "ody", "themis", pid.lower(), pid + ".XML"))
            t = open(xml[0], errors="ignore").read() if xml else ""
            m = re.search(r"start_date_time>\s*([0-9T:\-\.]+)Z", t); l = re.search(r"local_true_solar_time>\s*([0-9:\.]+)", t); s = re.search(r"solar_longitude[^>]*>\s*([0-9\.]+)", t)
            utc = dt.datetime.fromisoformat(m.group(1)) if m else None
            h, mi, se = (l.group(1).split(":") if l else (0, 0, 0))
            out.append(dict(id=pid, date=date, lst_name=lst, utc=utc, ltst=int(h) + int(mi) / 60 + float(se) / 3600 if l else lst, ls_label=float(s.group(1)) if s else None,
                            bt=ds.read(b).astype(np.float64)))
    return out


def block25(a, fn=np.nanmean):
    """25x25-cell (101 m) blocks, THEMIS pixel footprints, from the top-left; only complete blocks."""
    h, w = a.shape[0] // 25, a.shape[1] // 25
    return fn(a[:h * 25, :w * 25].reshape(h, 25, w, 25), axis=(1, 3))
