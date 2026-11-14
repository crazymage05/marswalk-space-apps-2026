#!/usr/bin/env python3
"""
MARSWALK data-feed poller.

Polls public NASA data sources, saves every download with provenance, and writes demo/twin/feed.json, which the
mission page (feed.js) and the twin read.

    python tools/ingest.py --once            # poll every source once (default)
    python tools/ingest.py --watch 30        # poll every 30 minutes until Ctrl-C
    python tools/ingest.py --offline         # rebuild feed.json from what is already on disk, no network
    python tools/ingest.py --source msl_raw  # only one source (repeatable)

HOW TO ADD A SOURCE
  Drop tools/feeds/<name>.py (names starting with "_" are ignored; tools/feeds/_common.py holds optional helpers:
  http_get with retries, save_download with provenance, TwinGeo for lon/lat -> twin x,y). The module exposes:

    SOURCE = {"id", "name", "mission", "instrument", "kind", "typical_latency"}    # all strings
    def poll(state: dict) -> (records: list, new_state: dict, status: dict)

  state      what the module returned last time ({} on the first run); persisted in data/feeds/state.json.
  records    list of schema records (type rad|photo|weather|hazard, see docs/data_feed.md); ids must be stable,
             because ingest de-duplicates by id.
  status     any of: newest_observed_utc, newest_available_utc, items_new, status ("ok"|"no_new"|"error"), note,
             extra (free dict shown in the panel). Missing keys keep their previous value.
  poll() may raise; ingest records status "error" with the message and carries on with the next source.

FILES
  data/feeds/<source_id>/<UTC date>/...   downloads + provenance.json (url, sha256, fetched_utc, licence, credit)
  data/feeds/state.json                   per-source state
  data/feeds/records.json                 every record ever ingested, by id
  data/feeds/sources.json                 last status of every source
  demo/twin/feed.json                     { generated_utc, sources: [...], records: [...] }   (the published result)
Nothing is ever written under data/raw.
"""
import argparse, importlib.util, json, os, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "feeds"))
from _common import FEEDS_DIR, ROOT, TWIN_DIR, iso  # noqa: E402

FEED_JSON = os.path.join(TWIN_DIR, "feed.json")
STATE = os.path.join(FEEDS_DIR, "state.json")
RECORDS = os.path.join(FEEDS_DIR, "records.json")
SOURCES = os.path.join(FEEDS_DIR, "sources.json")

STATUS_KEYS = ("newest_observed_utc", "newest_available_utc", "items_new", "status", "note", "extra")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def discover():
    """Return [(module_name, module_or_None, error_or_None)] for tools/feeds/*.py."""
    out = []
    fdir = os.path.join(HERE, "feeds")
    for fn in sorted(os.listdir(fdir)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        name = fn[:-3]
        try:
            spec = importlib.util.spec_from_file_location("marswalk_feed_" + name, os.path.join(fdir, fn))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not isinstance(getattr(mod, "SOURCE", None), dict) or not callable(getattr(mod, "poll", None)):
                raise ImportError("module must define SOURCE (dict) and poll(state)")
            out.append((name, mod, None))
        except Exception as e:  # a broken module must not stop the others
            out.append((name, None, f"{type(e).__name__}: {e}"))
    return out


def poll_all(mods, only, state, records, sources):
    for name, mod, err in mods:
        sid = mod.SOURCE["id"] if mod else name
        if only and sid not in only and name not in only:
            continue
        prev = sources.get(sid, {})
        entry = {k: prev.get(k) for k in ("newest_observed_utc", "newest_available_utc", "last_ingested_utc")}
        entry.update({"id": sid, "name": mod.SOURCE.get("name", sid) if mod else name,
                      "mission": mod.SOURCE.get("mission", "") if mod else "", "instrument": mod.SOURCE.get("instrument", "") if mod else "",
                      "kind": mod.SOURCE.get("kind", "") if mod else "", "typical_latency": mod.SOURCE.get("typical_latency", "") if mod else ""})
        entry["last_checked_utc"] = iso()
        if err:
            entry.update(status="error", items_new=0, note="could not load module: " + err)
            sources[sid] = entry
            print(f"[{sid}] error: {entry['note']}")
            continue
        try:
            recs, new_state, status = mod.poll(state.get(sid, {}))
            state[sid] = new_state
            fresh = 0
            for r in recs:
                if r["id"] not in records:
                    fresh += 1
                records[r["id"]] = r
            entry.update({k: status[k] for k in STATUS_KEYS if k in status and status[k] is not None})
            entry.setdefault("items_new", 0)
            entry.setdefault("status", "ok")
            if fresh:
                entry["last_ingested_utc"] = iso()
            entry["records_new"] = fresh
        except Exception as e:
            traceback.print_exc()
            entry.update(status="error", items_new=0, note=f"{type(e).__name__}: {e}")
        sources[sid] = entry
        print(f"[{sid}] {entry['status']}: {entry.get('note', '')}")


def write_feed(sources, records, offline=False, known=None):
    srcs = []
    for sid, s in sources.items():
        s = dict(s)
        if offline:
            s["status"] = "offline"
            s["items_new"] = 0
        srcs.append(s)
    recs = sorted(records.values(), key=lambda r: (r.get("observed_utc") or "", r["id"]))
    feed = {"generated_utc": iso(), "sources": srcs, "records": recs}
    save_json(FEED_JSON, feed)
    by_type = {}
    for r in recs:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    print(f"feed.json: {len(srcs)} sources, {len(recs)} records {by_type} -> {os.path.relpath(FEED_JSON, ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="poll once (default)")
    g.add_argument("--watch", type=float, metavar="MIN", help="poll every MIN minutes")
    g.add_argument("--offline", action="store_true", help="rebuild feed.json from disk only, no network")
    ap.add_argument("--source", action="append", help="only this source id (repeatable)")
    a = ap.parse_args()

    os.makedirs(FEEDS_DIR, exist_ok=True)
    state, records, sources = load_json(STATE, {}), load_json(RECORDS, {}), load_json(SOURCES, {})
    # records already in feed.json (written by an earlier run or by hand) are kept
    for r in load_json(FEED_JSON, {}).get("records", []):
        records.setdefault(r.get("id"), r) if r.get("id") else None

    if a.offline:
        mods = discover()
        for name, mod, err in mods:           # list known sources even if they never ran
            if mod and mod.SOURCE["id"] not in sources:
                sources[mod.SOURCE["id"]] = {**mod.SOURCE, "last_checked_utc": None, "newest_observed_utc": None,
                                              "newest_available_utc": None, "last_ingested_utc": None, "items_new": 0,
                                              "status": "offline", "note": "never polled"}
        write_feed(sources, records, offline=True)
        return 0

    while True:
        mods = discover()
        poll_all(mods, set(a.source or []), state, records, sources)
        save_json(STATE, state)
        save_json(RECORDS, records)
        save_json(SOURCES, sources)
        write_feed(sources, records)
        if not a.watch:
            return 0
        print(f"sleeping {a.watch:g} min ...", flush=True)
        try:
            time.sleep(a.watch * 60)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
