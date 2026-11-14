"""Perseverance (Mars 2020) raw images from NASA's public raw-image feed.

Endpoint (no key; the legacy raw_image_items API only serves Curiosity, Perseverance is on the RSS-style API):
  https://mars.nasa.gov/rss/api/?feed=raw_images&category=mars2020&feedtype=json&num=100&order=sol+desc
  camera filter: &search=NAVCAM_LEFT  /  NAVCAM_RIGHT  /  MCZ_LEFT  /  MCZ_RIGHT
Each image carries date_taken_utc (exposure) and date_received (when it reached the public raw-image site), so latency
is measured, not assumed. Credit is carried per image ("NASA/JPL-Caltech" plus instrument partners).
This source emits no twin records (Perseverance is in Jezero, not in the Gale twin); it publishes a status block with
the newest images and a few Navcam / Mastcam-Z thumbnails for the mission-control "Perseverance today" card.
"""
import io, os, statistics
from PIL import Image

from _common import TWIN_DIR, http_get, iso, now, parse_iso, save_download

SOURCE = {
    "id": "m2020_raw",
    "name": "Perseverance raw images",
    "mission": "Mars 2020 Perseverance (Jezero)",
    "instrument": "Navcam (NAVCAM_LEFT / NAVCAM_RIGHT), Mastcam-Z (MCZ_LEFT / MCZ_RIGHT) + all cameras for latency",
    "kind": "images",
    "typical_latency": "a few hours to several days from exposure to public raw image (median of the newest 100 images, measured each poll)",
}

API = "https://mars.nasa.gov/rss/api/"
CREDIT = "NASA/JPL-Caltech, Mars 2020 raw images (public domain; instrument teams credited per image)"
CAMS = ("NAVCAM_LEFT", "NAVCAM_RIGHT", "MCZ_LEFT", "MCZ_RIGHT")
N_THUMBS = 6
MAX_SEEN = 600


def _query(**p):
    q = {"feed": "raw_images", "category": "mars2020", "feedtype": "json", "num": 100, "page": 0, "order": "sol desc"}
    q.update(p)
    return http_get(API, params=q).json().get("images", [])


def _lat_h(i):
    a, b = parse_iso(i.get("date_taken_utc") and i["date_taken_utc"] + "Z"), parse_iso(i.get("date_received"))
    return None if a is None or b is None else (b - a).total_seconds() / 3600


def _row(i, file=None):
    lat = _lat_h(i)
    return {"imageid": i["imageid"], "sol": i["sol"], "camera": i["camera"]["instrument"],
            "taken_utc": i["date_taken_utc"][:19] + "Z", "received_utc": i["date_received"][:19].rstrip("Z") + "Z",
            "latency_h": None if lat is None else round(lat, 2), "credit": i.get("credit") or "NASA/JPL-Caltech",
            "page": i.get("link"), "file": file}


def poll(state):
    state = dict(state or {})
    seen = set(state.get("seen", []))
    t0 = now()
    allcam = _query()
    per_cam = {}
    for cam in CAMS:
        per_cam[cam] = [i for i in _query(search=cam, num=40) if i.get("sample_type") == "Full"]
    pool = {i["imageid"]: i for i in allcam}
    for lst in per_cam.values():
        pool.update({i["imageid"]: i for i in lst})
    items = list(pool.values())
    lat = [x for x in (_lat_h(i) for i in allcam) if x is not None]
    newest = max(items, key=lambda i: i["date_taken_utc"])
    new_ids = [i["imageid"] for i in items if i["imageid"] not in seen]

    # thumbnails: newest frame of each camera, then fill with the next newest Navcam frames from other sols/times
    picks, used = [], set()
    for cam in CAMS:
        if per_cam[cam]:
            top = max(per_cam[cam], key=lambda i: i["date_taken_utc"])
            picks.append(top)
            used.add(top["imageid"])
    rest = sorted((i for c in CAMS[:2] for i in per_cam[c] if i["imageid"] not in used),
                  key=lambda i: i["date_taken_utc"], reverse=True)
    step = max(1, len(rest) // max(1, N_THUMBS - len(picks)))
    picks += rest[::step][:N_THUMBS - len(picks)]
    picks = picks[:N_THUMBS]

    out_dir = os.path.join(TWIN_DIR, "feed", "m2020")
    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):     # keep only the current thumbnails (files this module wrote)
        if old.startswith("m2020_") and old.endswith(".jpg"):
            os.remove(os.path.join(out_dir, old))
    thumbs, warnings = [], []
    for it in picks:
        url = it["image_files"].get("medium") or it["image_files"].get("small")
        try:
            body = http_get(url, timeout=90).content
            save_download(SOURCE["id"], it["imageid"] + ".jpg", body, url, CREDIT,
                          extra={"sol": it["sol"], "instrument": it["camera"]["instrument"], "credit_image": it.get("credit"),
                                 "date_taken_utc": it["date_taken_utc"], "date_received": it["date_received"], "page": it.get("link")})
            img = Image.open(io.BytesIO(body)).convert("RGB")
            img.thumbnail((480, 480))
            rel = f"feed/m2020/m2020_{it['imageid'][:40]}.jpg"
            img.save(os.path.join(TWIN_DIR, rel), quality=78)
            thumbs.append(_row(it, rel))
        except Exception as e:
            warnings.append(f"{it['imageid']}: {e}")

    seen = list(state.get("seen", [])) + new_ids
    med = statistics.median(lat) if lat else None
    note = (f"{len(new_ids)} new images, newest sol {newest['sol']} ({newest['camera']['instrument']}, taken "
            f"{newest['date_taken_utc'][:16]}Z). "
            + (f"Median exposure-to-public latency {med:.1f} h over the newest {len(lat)} images (min {min(lat):.1f}, max {max(lat):.1f}). " if lat else "")
            + f"{len(thumbs)} Navcam / Mastcam-Z thumbnails saved." + (" Warnings: " + "; ".join(warnings) if warnings else ""))
    status = {
        "newest_observed_utc": newest["date_taken_utc"][:19] + "Z",
        "newest_available_utc": max(i["date_received"] for i in items)[:19].rstrip("Z") + "Z",
        "items_new": len(new_ids), "status": "ok" if new_ids else "no_new", "note": note,
        "extra": {"latency_median_h": round(med, 2) if med is not None else None, "latency_n": len(lat),
                  "latency_min_h": round(min(lat), 2) if lat else None, "latency_max_h": round(max(lat), 2) if lat else None,
                  "newest_sol": newest["sol"], "thumbs": thumbs,
                  "credit": "NASA/JPL-Caltech", "gallery": "https://mars.nasa.gov/mars2020/multimedia/raw-images/"},
    }
    state.update({"seen": seen[-MAX_SEEN:], "last_sol": newest["sol"], "last_poll_utc": iso(t0)})
    return [], state, status
