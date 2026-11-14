#!/usr/bin/env python3
"""
Shrink the NASA GLB models' embedded textures (max 1024 px, JPEG) and pack each GLB as base64 inside
JSON, because the artifact host serves .json but not .glb. The page decodes and parses it with
THREE.GLTFLoader.parse.   python demo/pack_models.py
"""
import base64, io, json, os, struct
from PIL import Image

D = "demo/twin/models"
for name in ("curiosity_msl_nasa", "markIII_suit_plain", "markIII_suit_walk"):
    b = open(os.path.join(D, name + ".glb"), "rb").read()
    jl = struct.unpack("<I", b[12:16])[0]; j = json.loads(b[20:20 + jl])
    bl = struct.unpack("<I", b[20 + jl:24 + jl])[0]; binc = b[28 + jl:28 + jl + bl]
    views = j["bufferViews"]; img_views = {im["bufferView"]: k for k, im in enumerate(j.get("images", [])) if "bufferView" in im}
    out, new_views = bytearray(), []
    for vi, v in enumerate(views):
        data = binc[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
        if vi in img_views:
            im = Image.open(io.BytesIO(data)); has_a = im.mode in ("RGBA", "LA") and im.getextrema()[-1][0] < 255
            im.thumbnail((1024, 1024)); buf = io.BytesIO()
            if has_a: im.save(buf, "PNG", optimize=True); mime = "image/png"
            else: im.convert("RGB").save(buf, "JPEG", quality=85); mime = "image/jpeg"
            data = buf.getvalue(); j["images"][img_views[vi]]["mimeType"] = mime
        while len(out) % 4: out.append(0)
        nv = {k: val for k, val in v.items() if k != "byteOffset"}; nv["byteOffset"] = len(out); nv["byteLength"] = len(data)
        out += data; new_views.append(nv)
    while len(out) % 4: out.append(0)
    j["bufferViews"] = new_views; j["buffers"][0]["byteLength"] = len(out)
    js = json.dumps(j, separators=(",", ":")).encode(); js += b" " * ((4 - len(js) % 4) % 4)
    glb = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(out)) + struct.pack("<I", len(js)) + b"JSON" + js + struct.pack("<I", len(out)) + b"BIN\x00" + bytes(out)
    json.dump({"glb": base64.b64encode(glb).decode()}, open(os.path.join(D, name + ".glb.json"), "w"))
    print(f"{name}: {len(b) / 1e6:.1f} MB -> {len(glb) / 1e6:.1f} MB glb, {os.path.getsize(os.path.join(D, name + '.glb.json')) / 1e6:.1f} MB json")
