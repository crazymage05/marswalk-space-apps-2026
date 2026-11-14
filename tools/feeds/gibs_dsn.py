"""Earth-side weather context for the three NASA Deep Space Network complexes, from NASA GIBS (Worldview's imagery backend).

Mars-to-Earth links end at Goldstone, Madrid and Canberra. Rain and heavy cloud at a site degrade high-frequency
(X/Ka-band) links. This source only fetches the imagery so a viewer can look at the Earth end of the link; it does not
compute link margins and it emits no twin records.

Endpoint (no key): https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi  (WMS 1.1.1, EPSG:4326)
  true colour candidates (best-covering one wins): VIIRS_NOAA21 / VIIRS_NOAA20 / VIIRS_SNPP / MODIS_Aqua / MODIS_Terra
                                                    *_CorrectedReflectance_TrueColor
  precipitation overlay:                            IMERG_Precipitation_Rate
Site coordinates: JPL "Deep Space Network Radio Astronomy User Guide" (2021), Table 1.1
  https://deepspace.jpl.nasa.gov/files/DSN_Radio_Astronomy_Users_Guide.pdf
Worldview deep links: https://worldview.earthdata.nasa.gov/?v=<west>,<south>,<east>,<north>&l=<layers>&t=<date>
"""
import io, os
from datetime import date as _date
from datetime import timedelta
from PIL import Image

from _common import TWIN_DIR, http_get, iso, now, save_download

SOURCE = {
    "id": "gibs_dsn",
    "name": "Earth side: DSN ground stations (NASA Worldview/GIBS)",
    "mission": "NASA Deep Space Network / Earth observation",
    "instrument": "VIIRS or MODIS true colour + IMERG precipitation rate (NASA GIBS)",
    "kind": "images",
    "typical_latency": "true colour a few hours after overpass; IMERG precipitation a few hours (GIBS 'best' layers); fetched once per poll",
}

WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
CREDIT = "NASA GIBS / Worldview, NASA EOSDIS (imagery: NASA/NOAA VIIRS, NASA MODIS, NASA GPM IMERG)"
LICENCE = "NASA Earth science data, free and open (NASA Earthdata open data policy)"
TRUE_COLOUR = ["VIIRS_NOAA21_CorrectedReflectance_TrueColor", "VIIRS_NOAA20_CorrectedReflectance_TrueColor",
               "VIIRS_SNPP_CorrectedReflectance_TrueColor", "MODIS_Aqua_CorrectedReflectance_TrueColor",
               "MODIS_Terra_CorrectedReflectance_TrueColor"]
PRECIP = "IMERG_Precipitation_Rate"
HALF_LON, HALF_LAT = 3.0, 2.0     # box half-size in degrees (about 540 x 440 km)
W, H = 480, 320
SITES = [  # (key, name, lat, lon) - JPL DSN Radio Astronomy User Guide Table 1.1, DMS converted to degrees
    ("goldstone", "Goldstone, California", 35 + 16 / 60 + 53 / 3600, -(116 + 46 / 60 + 44 / 3600)),
    ("madrid", "Madrid (Robledo), Spain", 40 + 25 / 60 + 45 / 3600, -(4 + 14 / 60 + 59 / 3600)),
    ("canberra", "Canberra (Tidbinbilla), Australia", -(35 + 24 / 60 + 6 / 3600), 148 + 58 / 60 + 56 / 3600),
]


def _bbox(lat, lon):
    return (round(lon - HALF_LON, 3), round(lat - HALF_LAT, 3), round(lon + HALF_LON, 3), round(lat + HALF_LAT, 3))


def _wms(layer, bbox, date, fmt):
    r = http_get(WMS, params={"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "SRS": "EPSG:4326",
                              "LAYERS": layer, "BBOX": ",".join(map(str, bbox)), "WIDTH": W, "HEIGHT": H,
                              "FORMAT": fmt, "TRANSPARENT": "TRUE", "TIME": date}, timeout=90)
    if not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError("WMS did not return an image: " + r.text[:200])
    return r.content


def _coverage(img):
    """Share of pixels that are opaque and not black (swath gaps come back transparent or black)."""
    px = img.convert("RGBA").getdata()
    n = sum(1 for r, g, b, a in px if a > 10 and (r + g + b) > 30)
    return n / (img.width * img.height)


def worldview_url(bbox, layers, date):
    return ("https://worldview.earthdata.nasa.gov/?v=%s&l=%s&t=%s-T12%%3A00%%3A00Z"
            % (",".join(map(str, bbox)), ",".join(layers), date))


def _site(lat, lon, date):
    """Best true-colour layer for this date, with IMERG precipitation composited on top. None if all layers are empty."""
    bbox = _bbox(lat, lon)
    got = []        # (coverage, layer, png bytes)
    for layer in TRUE_COLOUR:
        try:
            body = _wms(layer, bbox, date, "image/png")
        except Exception:
            continue
        got.append((_coverage(Image.open(io.BytesIO(body))), layer, body))
        if got[-1][0] > 0.97:
            break
    got.sort(key=lambda g: -g[0])
    if not got or got[0][0] < 0.5:
        return None
    # best-covering pass first; other passes of the same UTC day only fill its swath gaps (Worldview stacks them too)
    bg = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    used = []
    for cov_i, lyr_i, body_i in reversed(got):
        if cov_i < 0.02:
            continue
        bg.alpha_composite(Image.open(io.BytesIO(body_i)).convert("RGBA"))
        used.append(lyr_i)
    used.reverse()                      # best first
    cov, layer, body = got[0]
    cov = _coverage(bg)
    rain_share, rain_png = None, None
    try:
        rain_png = _wms(PRECIP, bbox, date, "image/png")
        rain = Image.open(io.BytesIO(rain_png)).convert("RGBA")
        rain_share = sum(1 for v in rain.getchannel("A").getdata() if v > 10) / (W * H)
        bg.alpha_composite(rain)
    except Exception:
        rain_share = None
    bright = sum(1 for r, g, b, _ in bg.getdata() if min(r, g, b) > 185) / (W * H)
    return {"bbox": bbox, "layer": layer, "layers": used, "coverage": round(cov, 3),
            "rain_share": None if rain_share is None else round(rain_share, 4),
            "bright_share": round(bright, 3), "base_png": body, "rain_png": rain_png, "image": bg.convert("RGB")}


def _precip_date(day0):
    """Newest UTC date (today back 3 days) for which GIBS already serves IMERG precipitation with any rain pixel in one of
    the three boxes. GIBS returns a blank tile (676 bytes) while a day is unpublished, so an all-dry day is
    indistinguishable from an unpublished one; we then fall back one day, never forward."""
    for back in range(0, 4):
        date = (day0 - timedelta(days=back)).isoformat()
        for _key, _name, lat, lon in SITES:
            try:
                rain = Image.open(io.BytesIO(_wms(PRECIP, _bbox(lat, lon), date, "image/png"))).convert("RGBA")
            except Exception:
                continue
            if rain.getchannel("A").getextrema()[1] > 10:
                return date
    return day0.isoformat()


def poll(state):
    state = dict(state or {})
    day0 = now().date()
    pdate = _precip_date(day0)
    out, warnings, date_used = [], [], None
    os.makedirs(os.path.join(TWIN_DIR, "feed", "gibs"), exist_ok=True)
    for key, name, lat, lon in SITES:
        res, date = None, None
        for back in range(0, 3):    # one date for all sites (the IMERG date); true colour falls back a day if the swath is empty
            date = (day0 - timedelta(days=(day0 - _date.fromisoformat(pdate)).days + back)).isoformat()
            res = _site(lat, lon, date)
            if res:
                break
        if not res:
            warnings.append(f"{key}: no usable true-colour imagery for the last 4 days")
            continue
        date_used = max(date_used or date, date)
        res["image"].save(os.path.join(TWIN_DIR, "feed", "gibs", key + ".jpg"), quality=82)
        for tag, body in (("truecolor", res["base_png"]), ("imerg", res["rain_png"])):
            if body:
                lyr = res["layer"] if tag == "truecolor" else PRECIP
                save_download(SOURCE["id"], f"{key}_{tag}_{date}.png", body, WMS + "?LAYERS=" + lyr + "&TIME=" + date,
                              CREDIT, LICENCE, extra={"site": name, "lat": lat, "lon": lon, "bbox_w_s_e_n": res["bbox"],
                                                      "layer": lyr, "date": date})
        layers = [PRECIP] + res["layers"] + ["Coastlines_15m"]
        out.append({"key": key, "name": name, "lat": round(lat, 4), "lon": round(lon, 4), "date": date,
                    "layer": res["layer"], "layers": res["layers"], "precip_layer": PRECIP, "bbox": res["bbox"], "image": "feed/gibs/" + key + ".jpg",
                    "coverage": res["coverage"], "rain_share": res["rain_share"], "bright_share": res["bright_share"],
                    "worldview": worldview_url(res["bbox"], layers, date)})
    if not out:
        raise RuntimeError("GIBS returned no usable imagery for any site: " + "; ".join(warnings))
    status = {
        "newest_observed_utc": max(o["date"] for o in out) + "T12:00:00Z",
        "newest_available_utc": iso(),
        "items_new": len(out),
        "status": "ok" if len(out) == len(SITES) else "partial",
        "note": "; ".join(f"{o['name']}: {o['layer'].split('_CorrectedReflectance')[0]} {o['date']}, rain pixels "
                          + ("n/a" if o["rain_share"] is None else f"{o['rain_share']*100:.1f}%") for o in out)
                + ". Context imagery only; no link margins are computed."
                + ((" Warnings: " + "; ".join(warnings)) if warnings else ""),
        "extra": {"sites": out, "note": "Imagery is context for the Earth end of the link; MARSWALK does not model link margins.",
                  "site_coordinates_source": "JPL DSN Radio Astronomy User Guide 2021, Table 1.1"},
    }
    state.update({"last_date": date_used, "last_poll_utc": iso(), "sites": [o["key"] for o in out]})
    return [], state, status
