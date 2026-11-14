"""Fetch the USGS Geologic Map of Mars (Tanaka et al. 2014, SIM 3292, 1:20,000,000) unit polygons around the ROI
-> data/usgs_geology/ (+ provenance.json).

usage: python tools/fetch_usgs_geology.py

Source: the USGS Astrogeology Science Center ArcGIS feature service published through the USGS-NASA Planetary Geologic Mapping
Program hub (astrogeology-usgs.hub.arcgis.com/pages/interactive-maps-mars):
  https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Tanaka_et_al_2014_Mars_Global_Map_Features/FeatureServer/3   (Global_Geology polygons)
Requests: layer metadata (renderer = the map's own unit colours), the polygons intersecting a 0.8 x 0.8 degree window around the ROI
(returned in geographic GCS_Mars_2000_Sphere), and the legend text of every unit that occurs in the window. Nothing else is downloaded.
A search of the USGS publications warehouse and the hub found no larger-scale USGS geologic map (SIM) of Gale crater: the Mars SIMs at
1:1M or larger cover Jezero, Shalbatana, Athabasca, Nepenthes, Ladon, Candor and Olympus Mons, not Gale. So SIM 3292 is the USGS product here.
"""
import datetime, hashlib, json, os, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "usgs_geology")
UA = {"User-Agent": "marswalk-demo/1.0"}
SVC = "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Tanaka_et_al_2014_Mars_Global_Map_Features/FeatureServer/3"
GW = 'GEOGCS["GCS_Mars_2000_Sphere",DATUM["<custom>",SPHEROID["<custom>",3396190.0,0.0]],PRIMEM["Reference_Meridian",0.0],UNIT["Degree",0.0174532925199433]]'
WIN = dict(xmin=137.0, ymin=-5.2, xmax=137.8, ymax=-4.4)


def get(path, params):
    url = SVC + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        b = r.read()
    time.sleep(1)
    return url, b


def main():
    os.makedirs(OUT, exist_ok=True); prov = {"credit": "USGS Astrogeology Science Center / USGS-NASA Planetary Geologic Mapping Program; Tanaka et al. (2014), USGS SIM 3292",
        "fetched_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "user_agent": UA["User-Agent"], "files": []}
    def save(name, url, b):
        open(os.path.join(OUT, name), "wb").write(b)
        prov["files"].append({"file": name, "url": url, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)})
    url, b = get("", {"f": "json"}); save("layer_metadata.json", url, b)
    g = json.dumps(dict(WIN, spatialReference={"wkt": GW}))
    url, b = get("/query", {"f": "json", "where": "1=1", "geometry": g, "geometryType": "esriGeometryEnvelope", "spatialRel": "esriSpatialRelIntersects",
                            "outFields": "Unit,UnitDesc,UnitGroup,SphArea_km", "returnGeometry": "true", "outSR": json.dumps({"wkt": GW})})
    save("polygons_window.json", url, b)
    units = sorted({f["attributes"]["Unit"] for f in json.loads(b)["features"]})
    where = "Unit IN (%s)" % ",".join("'%s'" % u for u in units)
    url, b = get("/query", {"f": "json", "where": where, "returnGeometry": "false", "returnDistinctValues": "true",
                            "outFields": "Unit,UnitDesc,UnitGroup,PrimaryCharacteristics,AdditionalCharacteristics,Interpretation"})
    save("legend_units.json", url, b)
    prov["window_deg"] = WIN; prov["units_in_window"] = units
    json.dump(prov, open(os.path.join(OUT, "provenance.json"), "w"), indent=1)
    print("units in window:", units)


if __name__ == "__main__":
    main()
