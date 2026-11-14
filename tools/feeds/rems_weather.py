"""Curiosity REMS daily weather summary from NASA's public weather API.

Endpoint: https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json
(the same one data/raw/curiosity/rems/nasa_weather_api/weather_msl.json came from).
It lists one record per sol: terrestrial_date, min_temp, max_temp (air, deg C), pressure (Pa).
The API publishes no timestamp of its own, so "available_utc" is the first time this poller saw a sol (an upper
bound), and the latency reported is (now - terrestrial_date of the newest sol), a lower bound on the real delay.
Only sols newer than the twin's weather table (demo/twin/data.json) become records, newest MAX_NEW first.
"""
import json, os
from datetime import datetime, timezone

from _common import TWIN_DIR, http_get, iso, now, save_download

SOURCE = {
    "id": "rems_weather",
    "name": "REMS daily weather",
    "mission": "MSL Curiosity",
    "instrument": "REMS (air temperature, pressure)",
    "kind": "weather",
    "typical_latency": "weeks to months: the newest sol on the NASA weather API trails today by the figure measured on each poll",
}
URL = "https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json"
MAX_NEW = 40


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def poll(state):
    state = dict(state or {})
    body = http_get(URL, timeout=120).content
    save_download(SOURCE["id"], "weather_msl.json", body, URL, "NASA/CAB-CSIC/FMI, REMS Curiosity weather summary")
    soles = json.loads(body)["soles"]
    rows = []
    for d in soles:
        try:
            sol = int(d["sol"])
        except (KeyError, ValueError):
            continue
        lo, hi = _num(d.get("min_temp")), _num(d.get("max_temp"))
        if lo is None or hi is None:
            continue
        rows.append((sol, d["terrestrial_date"], lo, hi, _num(d.get("pressure"))))
    rows.sort()
    twin = json.load(open(os.path.join(TWIN_DIR, "data.json"), encoding="utf-8"))["weather"]
    twin_last = max(w["sol"] for w in twin)
    first_seen = state.get("first_seen", {})
    t = iso()
    new = [r for r in rows if r[0] > twin_last][-MAX_NEW:]
    records = []
    for sol, date, lo, hi, p in new:
        fs = first_seen.setdefault(str(sol), t)
        records.append({
            "id": f"weather-msl-{sol}", "type": "weather", "source": SOURCE["id"],
            "observed_utc": date + "T00:00:00Z", "available_utc": fs, "ingested_utc": t, "sol": sol, "label": "measured",
            "weather": {"min_C": lo, "max_C": hi, "pressure_Pa": p},
            "provenance": {"url": URL, "sha256": None,
                           "method": "NASA REMS daily summary; observed_utc is the terrestrial date at 00:00 (day-level only)"},
        })
    newest = rows[-1]
    obs = datetime.strptime(newest[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    lag_d = (now() - obs).days
    prev = state.get("newest_sol", 0)
    state.update({"newest_sol": newest[0], "first_seen": {k: v for k, v in first_seen.items() if int(k) > twin_last}})
    if records:
        note = (f"Newest sol on the API: {newest[0]} ({newest[1]}), {lag_d} days behind today (lower bound on latency; no publication "
                f"timestamp exists). Twin weather table ends at sol {twin_last}; {len(records)} later sols sent as records "
                f"(sols {new[0][0]}-{new[-1][0]}).")
    else:
        note = f"Newest sol on the API: {newest[0]} ({newest[1]}), {lag_d} days behind today. Nothing newer than the twin's sol {twin_last}."
    status = {
        "newest_observed_utc": iso(obs), "newest_available_utc": first_seen.get(str(newest[0])),
        "items_new": sum(1 for r in rows if r[0] > prev) if prev else len(records),
        "status": "ok" if newest[0] > prev else "no_new", "note": note,
        "extra": {"api_lag_days": lag_d, "twin_last_sol": twin_last},
    }
    return records, state, status
