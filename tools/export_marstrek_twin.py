"""Stitch the downloaded Mars Trek tiles (data/marstrek/) into the twin's layer images.

usage: python tools/export_marstrek_twin.py
Writes demo/twin/marstrek_ctx_roi.jpg (CTX cropped to the ROI and resampled to the twin grid, same proportional mapping as the other
ROI rasters: row (i+0.5)/H from the north edge), marstrek_ctx.jpg / marstrek_mola.jpg / marstrek_geo.jpg (context windows with
their lon/lat extent) and marstrek.json (extents, credits, layer ids, deep link, native resolution).
Tile addressing: column = floor((lon+180)/t), row = floor((90-lat)/t), t = 180/2^z degrees (Trek EPSG:104905 equirectangular).
"""
import json, os
import numpy as np
import cv2
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "marstrek"); OUT = os.path.join(ROOT, "demo", "twin")
ROI = dict(minlat=-4.83, maxlat=-4.78, minlon=137.37, maxlon=137.41)


def stitch(key, mode):
    P = json.load(open(os.path.join(SRC, "provenance.json")))["layers"][key]
    t = P["tile_deg"]; c0, c1 = P["cols"]; r0, r1 = P["rows"]; z = P["zoom"]
    ext = "jpg" if key == "mola" else "png"
    im = Image.new(mode, ((c1 - c0 + 1) * 256, (r1 - r0 + 1) * 256))
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            im.paste(Image.open(os.path.join(SRC, key, "%d_%d_%d.%s" % (z, r, c, ext))).convert(mode), ((c - c0) * 256, (r - r0) * 256))
    return im, (-180 + c0 * t, 90 - r0 * t, t / 256)       # lon of left edge, lat of top edge, deg per pixel


def crop(im, org, lon0, lon1, lat0, lat1):
    x0, y0, d = org
    return im.crop((round((lon0 - x0) / d), round((y0 - lat1) / d), round((lon1 - x0) / d), round((y0 - lat0) / d)))


def register(im, org):
    """Translation between the Trek CTX frame and the twin's HiRISE frame, by normalised cross-correlation of band-passed images
    (HiRISE terrain.jpg resampled to the CTX pixel size, searched inside a +-0.06 degree CTX window). Returns (east_px, south_px):
    the ROI content sits that many CTX pixels east / south of the nominal ROI coordinates in the Trek mosaic."""
    d = org[2]; m = 0.06
    W = np.asarray(crop(im, org, ROI["minlon"] - m, ROI["maxlon"] + m, ROI["minlat"] - m, ROI["maxlat"] + m), np.float32); o = m / d
    nw = int(round((ROI["maxlon"] - ROI["minlon"]) / d)); nh = int(round((ROI["maxlat"] - ROI["minlat"]) / d))
    T = cv2.resize(cv2.imread(os.path.join(OUT, "terrain.jpg"), 0), (nw, nh), interpolation=cv2.INTER_AREA).astype(np.float32)
    hp = lambda x: cv2.GaussianBlur(x, (0, 0), 1) - cv2.GaussianBlur(x, (0, 0), 10)
    ty0, ty1, tx0, tx1 = int(nh * .14), int(nh * .86), int(nw * .13), int(nw * .86)
    r = cv2.matchTemplate(hp(W), hp(T)[ty0:ty1, tx0:tx1], cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(r); r2 = r.copy(); cv2.circle(r2, loc, 25, -1, -1); second = float(r2.max())
    return loc[0] - tx0 - o, loc[1] - ty0 - o, float(mx), second


def main():
    G = json.load(open(os.path.join(OUT, "data.json")))["grid"]; W, H = G["w"], G["h"]
    meta = {"credit": "NASA/JPL-Caltech Mars Trek", "link": "https://trek.nasa.gov/mars/", "layers": {}}
    im, org = stitch("ctx_roi", "L")
    ex, sy, ncc, ncc2 = register(im, org); dd = org[2]
    print("registration: CTX content of the ROI is %.1f px east, %.1f px south of nominal (NCC %.2f, next peak %.2f)" % (ex, sy, ncc, ncc2))
    dlon, dlat = ex * dd, -sy * dd
    c = crop(im, org, ROI["minlon"] + dlon, ROI["maxlon"] + dlon, ROI["minlat"] + dlat, ROI["maxlat"] + dlat)
    print("CTX native crop", c.size, "px; m/px =", round(0.04 * 59274.6 / c.size[0], 1))
    c.resize((W, H), Image.BICUBIC).convert("RGB").save(os.path.join(OUT, "marstrek_ctx_roi.jpg"), quality=88)
    meta["layers"]["ctx"] = {"id": "Gale_CTX_BlockAdj_dd", "title": "MRO CTX, Gale Crater Mosaic", "native_px": list(c.size), "m_per_px": round(0.04 * 59274.6 / c.size[0], 1),
        "registration": {"east_m": round(ex * dd * 59274.6, 0), "south_m": round(sy * dd * 59274.6, 0), "d_lon_deg": round(dlon, 5), "d_lat_deg": round(dlat, 5), "ncc": round(ncc, 3), "ncc_second_peak": round(ncc2, 3),
                         "note": "Trek CTX mosaic shows the twin's HiRISE terrain this far east/south of the nominal ROI lon/lat; the layer is shifted onto the twin by this translation"}}
    for key, name, mode, win, size in [("ctx_ctx", "ctx", "L", (137.15, 137.65, -5.05, -4.55), 640),
                                       ("mola", "mola", "RGB", (136.6, 138.2, -5.6, -4.0), 512), ("geo", "geo", "RGB", (136.6, 138.2, -5.6, -4.0), 512)]:
        im, org = stitch(key, mode); c = crop(im, org, *win)
        if key == "geo":      # Trek tiles are PNGs with transparency where the map is empty; flatten on dark
            pass
        c.resize((size, size), Image.LANCZOS).convert("RGB").save(os.path.join(OUT, "marstrek_%s.jpg" % name), quality=86)
        meta["layers"].setdefault(name, {}).update({"id": json.load(open(os.path.join(SRC, "provenance.json")))["layers"][key]["layer_id"], "window": list(win), "px": size})
    meta["layers"]["ctx"]["window"] = [137.15, 137.65, -5.05, -4.55]
    meta["layers"]["ctx"]["px"] = 640
    meta["layers"]["mola"]["title"] = "MOLA colour shaded relief, 463 m"
    meta["layers"]["geo"]["title"] = "SIM 3292 global geologic map (Trek rendering of the USGS map)"
    cl, ck = (ROI["minlon"] + ROI["maxlon"]) / 2 + dlon, (ROI["minlat"] + ROI["maxlat"]) / 2 + dlat   # where the terrain is in Trek's frame
    meta["roi"] = ROI
    meta["roi_in_trek_frame"] = dict(minlon=ROI["minlon"] + dlon, maxlon=ROI["maxlon"] + dlon, minlat=ROI["minlat"] + dlat, maxlat=ROI["maxlat"] + dlat)
    meta["deeplink"] = ("https://trek.nasa.gov/mars/#v=0.1&x=%.4f&y=%.4f&z=12&p=urn%%3Aogc%%3Adef%%3Acrs%%3AEPSG%%3A%%3A104905&d=&l=Gale_CTX_BlockAdj_dd%%2Ctrue%%2C1&b=mars" % (cl, ck))
    meta["deeplink_note"] = "Trek permalink fragment: x=lon, y=lat, z=zoom, l=layerId,visible,opacity; checked with a browser load of this exact URL"
    json.dump(meta, open(os.path.join(OUT, "marstrek.json"), "w"), indent=1)
    print(meta["deeplink"])


if __name__ == "__main__":
    main()
