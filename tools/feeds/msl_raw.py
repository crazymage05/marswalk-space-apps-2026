"""Curiosity (MSL) raw images from NASA's public raw-image service.

Endpoint (same one rover_harvest.py used for the archive):
  https://mars.nasa.gov/api/v1/raw_image_items/?condition_1=msl:mission&order=sol desc&per_page=N
  filter by camera with condition_2=NAV_LEFT_B:instrument
Each item carries date_taken (Earth receive-time stamp of the exposure, UTC), date_received (when the
image reached the raw-image site) and site/drive (rover position index).
Rover position: https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json (lon/lat per site+drive).
Navcam images whose waypoint lies in the twin ROI become "photo" records (resized copy in demo/twin/feed/).
"""
import io, os, statistics
from PIL import Image

from _common import (FEEDS_DIR, TWIN_DIR, TwinGeo, http_get, iso, now, parse_iso, save_download)

SOURCE = {
    "id": "msl_raw",
    "name": "Curiosity raw images",
    "mission": "MSL Curiosity",
    "instrument": "Navcam (NAV_LEFT_B / NAV_RIGHT_B) + all cameras for latency",
    "kind": "images",
    "typical_latency": "about 16 h from exposure to public raw image (median of the newest 100 images, measured each poll)",
}

API = "https://mars.nasa.gov/api/v1/raw_image_items/"
WAYPOINTS = "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json"
CREDIT = "NASA/JPL-Caltech, Mars Science Laboratory raw images (public domain)"
NAVCAMS = ("NAV_LEFT_B", "NAV_RIGHT_B")
MAX_PHOTOS = 6          # photo records per poll
MAX_SEEN = 600


def _query(**p):
    q = {"condition_1": "msl:mission", "order": "sol desc", "per_page": 100, "page": 0}
    q.update(p)
    return http_get(API, params=q).json()["items"]


def _img_url(it):
    return it.get("https_url") or it.get("url")


def poll(state):
    state = dict(state or {})
    seen = list(state.get("seen", []))
    seen_set = set(seen)
    t0 = now()

    allcam = _query()
    navs = []
    for cam in NAVCAMS:
        navs += _query(condition_2=f"{cam}:instrument")

    lat = [(parse_iso(i["date_received"]) - parse_iso(i["date_taken"])).total_seconds() / 3600
           for i in allcam if i.get("date_received") and i.get("date_taken")]
    new_all = {i["imageid"]: i for i in allcam + navs if i["imageid"] not in seen_set}
    newest = max(allcam + navs, key=lambda i: (i["sol"], i["date_taken"]))
    status = {
        "newest_observed_utc": newest["date_taken"][:19] + "Z",
        "newest_available_utc": max(i["date_received"] for i in allcam + navs)[:19] + "Z",
        "items_new": len(new_all),
    }

    cand = [i for i in navs if i["imageid"] in new_all and not i.get("is_thumbnail")
            and (i.get("extended") or {}).get("sample_type") != "thumbnail" and _img_url(i)]
    records, inside, outside, no_pos = [], [], 0, 0
    geo = None
    if cand:
        geo = TwinGeo()
        raw = http_get(WAYPOINTS, timeout=90).content
        save_download(SOURCE["id"], "MSL_waypoints.json", raw, WAYPOINTS, "NASA/JPL MMGIS MSL rover waypoints")
        import json
        wp = sorted(((f["properties"]["site"], f["properties"]["drive"], f["properties"]["lon"], f["properties"]["lat"])
                     for f in json.loads(raw)["features"]))
        exact = {(s, d): (lo, la) for s, d, lo, la in wp}

        def where(it):
            key = (it["site"], it["drive"])
            if key in exact:
                return exact[key]
            prior = [w for w in wp if (w[0], w[1]) <= key]
            return prior[-1][2:] if prior else None

        for it in cand:
            pos = where(it)
            if pos is None:
                no_pos += 1
            elif geo.inside(*pos):
                inside.append((it, pos))
            else:
                outside += 1

        if inside:
            step = max(1, len(inside) // MAX_PHOTOS)
            picked = inside[::step][:MAX_PHOTOS]
            os.makedirs(os.path.join(TWIN_DIR, "feed"), exist_ok=True)
            for it, pos in picked:
                try:
                    body = http_get(_img_url(it), timeout=90).content
                    _, sha = save_download(SOURCE["id"], it["imageid"] + ".JPG", body, _img_url(it), CREDIT,
                                           extra={"sol": it["sol"], "instrument": it["instrument"]})
                    img = Image.open(io.BytesIO(body)).convert("RGB")
                    img.thumbnail((720, 720))
                    rel = f"feed/{it['imageid']}.jpg"
                    img.save(os.path.join(TWIN_DIR, rel), quality=78)
                    x, y = geo.xy(*pos)
                    records.append({
                        "id": "photo-msl-" + it["imageid"], "type": "photo", "source": SOURCE["id"],
                        "observed_utc": it["date_taken"][:19] + "Z", "available_utc": it["date_received"][:19] + "Z",
                        "ingested_utc": iso(), "sol": it["sol"], "label": "measured",
                        "photo": {"file": rel, "x": x, "y": y, "camera": it["instrument"]},
                        "provenance": {"url": _img_url(it), "sha256": sha,
                                       "method": "NASA raw-image API; position = MMGIS waypoint for site %s drive %s, "
                                                 "placed on the twin grid with the HiRISE coregistration" % (it["site"], it["drive"])},
                    })
                except Exception as e:  # one bad image must not sink the poll
                    status.setdefault("warnings", []).append(f"{it['imageid']}: {e}")

    seen = (seen + list(new_all))[-MAX_SEEN:]
    med = statistics.median(lat) if lat else None
    note = (f"{len(new_all)} new images, newest sol {newest['sol']} (site {newest['site']} drive {newest['drive']}); "
            f"{len(inside)} new Navcam frames inside the twin area ({len(records)} sent to the twin), "
            f"{outside} Navcam outside" + (f", {no_pos} without position" if no_pos else "") + ". "
            + (f"Median exposure-to-public latency {med:.1f} h over the newest {len(lat)} images "
               f"(min {min(lat):.1f}, max {max(lat):.1f})." if lat else ""))
    status.update({"status": "ok" if new_all else "no_new", "note": note,
                   "extra": {"latency_median_h": round(med, 2) if med is not None else None, "latency_n": len(lat),
                             "navcam_inside_twin": len(inside), "navcam_outside_twin": outside,
                             "newest_sol": newest["sol"]}})
    state.update({"seen": seen, "last_sol": newest["sol"], "last_poll_utc": iso(t0)})
    return records, state, status
