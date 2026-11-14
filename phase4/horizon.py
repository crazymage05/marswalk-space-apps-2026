"""Horizon angles on the 4 m nav grid from the 1 m DTM (GPU ray marching, run in short chunks)."""
import time
import numpy as np
import torch

R_MARS = 3396190.0
N_AZ = 32
AZ_DEG = np.arange(N_AZ) * 360.0 / N_AZ
SENT = -1.0e9


def march_distances(max_m=2000.0, rel=0.012):
    """1 m steps near, step = rel * d farther out (1.2 % of range)."""
    d, out = 1.0, []
    while d <= max_m:
        out.append(d)
        d += max(1.0, rel * d)
    return np.array(out)


def _bilin(zf, H, W, r, c):
    """Bilinear sample of flat tensor zf [H*W] at fractional index coords (r, c); out of grid -> SENT."""
    ok = (r >= 0) & (r <= H - 1) & (c >= 0) & (c <= W - 1)
    r = r.clamp(0, H - 1.01); c = c.clamp(0, W - 1.01)
    r0 = r.floor(); c0 = c.floor(); fr = r - r0; fc = c - c0
    i = (r0.long() * W + c0.long())
    z = (zf[i] * (1 - fr) * (1 - fc) + zf[i + 1] * (1 - fr) * fc
         + zf[i + W] * fr * (1 - fc) + zf[i + W + 1] * fr * fc)
    return torch.where(ok, z, torch.full_like(z, SENT)), ok


def pick_device(want="auto"):
    """cuda (NVIDIA) if present, else mps (Apple GPU), else cpu."""
    if want != "auto":
        return want
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _sync(device):
    if str(device).startswith("cuda"): torch.cuda.synchronize()
    elif str(device) == "mps": torch.mps.synchronize()


def _empty(device):
    if str(device).startswith("cuda"): torch.cuda.empty_cache()
    elif str(device) == "mps": torch.mps.empty_cache()

def horizon_angles(dtm, rows, cols, res, eye=1.7, max_m=2000.0, chunk=12000, device="cuda", R=R_MARS,
                   pause=0.05, verbose=True):
    """dtm [H,W] float (NaN allowed); rows, cols: fractional index coords of observer ground points.
    Returns horizon_deg [N_AZ, N] float32 (0 where a ray sees no terrain) and trunc [N_AZ, N] bool
    (ray left the grid before max_m)."""
    H, W = dtm.shape
    d = np.asarray(dtm, np.float64)
    nanm = ~np.isfinite(d)
    zt = torch.tensor(np.where(nanm, SENT, d), dtype=torch.float32, device=device).reshape(-1)
    # ground height: bilinear on a NaN-filled copy (nearest valid) so a stray NaN does not poison the observer
    if nanm.any():
        from scipy.ndimage import distance_transform_edt
        idx = distance_transform_edt(nanm, return_distances=False, return_indices=True)
        filled = d[tuple(idx)]
    else:
        filled = d
    zg = torch.tensor(filled, dtype=torch.float32, device=device).reshape(-1)
    az = torch.tensor(np.radians(AZ_DEG), dtype=torch.float32, device=device)
    s, c_ = torch.sin(az)[:, None], torch.cos(az)[:, None]       # east = col+, north = row-
    dist = torch.tensor(march_distances(max_m), dtype=torch.float32, device=device)
    curv = dist ** 2 / (2 * R)
    N = len(rows)
    out = np.zeros((N_AZ, N), np.float32); trunc = np.zeros((N_AZ, N), bool)
    t0 = time.time()
    for a in range(0, N, chunk):
        rr = torch.tensor(rows[a:a + chunk], dtype=torch.float32, device=device)[None]
        cc = torch.tensor(cols[a:a + chunk], dtype=torch.float32, device=device)[None]
        z0, _ = _bilin(zg, H, W, rr, cc); z0 = z0 + eye
        best = torch.full((N_AZ, rr.shape[1]), -1e9, device=device)
        left = torch.zeros((N_AZ, rr.shape[1]), dtype=torch.bool, device=device)
        for k in range(len(dist)):
            dk = dist[k]
            r = rr - dk / res * c_; c = cc + dk / res * s
            z, ok = _bilin(zt, H, W, r, c)
            left |= ~ok
            ang = torch.atan2(z - curv[k] - z0, dk.expand_as(z))
            ang = torch.where(z > -1e8, ang, torch.full_like(ang, -1e9))
            best = torch.maximum(best, ang)
        best = torch.where(best < -1e8, torch.zeros_like(best), best)   # nothing seen -> 0
        out[:, a:a + chunk] = torch.rad2deg(best).cpu().numpy(); trunc[:, a:a + chunk] = left.cpu().numpy()
        _sync(device); time.sleep(pause)
        if verbose: print(f"  chunk {a // chunk + 1}/{(N + chunk - 1) // chunk}  {time.time() - t0:.0f}s", flush=True)
    del zt, zg
    _empty(device)
    return out, trunc


def sky_factors(h_deg):
    """h_deg [32, ...]. Horizon clamped at 0 (upper hemisphere only), horizontal receiving surface.
    sky_view  = mean_az cos^2(h)   (cosine-weighted visible fraction; flat open ground = 1)
    sky_solid = mean_az (1 - sin h) (visible fraction of the hemisphere's solid angle)"""
    h = np.radians(np.clip(np.asarray(h_deg, np.float64), 0, 90))
    return (np.cos(h) ** 2).mean(0).astype(np.float32), (1 - np.sin(h)).mean(0).astype(np.float32)
