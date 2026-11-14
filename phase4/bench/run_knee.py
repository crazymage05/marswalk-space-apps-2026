"""Risk-weight sweep for the recommended planner (16-neighbour A* + string pulling) on the campaign scenario, and the knee.
Edge cost = model cost + w x length x mean cell risk (phase4/recommended.py). Time = model time with fatigue
(A.route_resources), risk = risk-metres along the final polyline. Knee = point of maximum distance from the chord joining the
two extreme points of the normalised (time, risk) curve.
Usage: python phase4/bench/run_knee.py -> results/knee_results.json"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
from phase4 import costs as C, astronaut as A, scenarios as S, recommended as R, safety_validator as SV

WEIGHTS = [0, 0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 20, 40]


def main():
    grid = C.load_grid(); prof = A.get_profile("nominal"); sc = S.campaign_scenario(grid, prof)
    s, t = int(sc["start"]), int(sc["goal"]); pts = []
    for w in WEIGHTS:
        r = R.plan_recommended(grid, s, t, prof, smooth=True, risk_weight=w)
        v = SV.validate_polyline(r["vertices"], grid, prof)
        pts.append(dict(w=w, time_s=r["time_s"], risk_m=r["risk_m"], distance_m=r["distance_m"], energy_kj=r["energy_kj"],
                        valid=v["ok"], n_vertices=len(r["vertices"])))
        print(pts[-1], flush=True)
    T = np.array([p["time_s"] for p in pts]); K = np.array([p["risk_m"] for p in pts])
    tn = (T - T.min()) / (T.max() - T.min()); kn = (K - K.min()) / (K.max() - K.min())
    a = np.array([tn[0], kn[0]]); b = np.array([tn[-1], kn[-1]]); ab = b - a
    dist = np.abs(ab[0] * (kn - a[1]) - ab[1] * (tn - a[0])) / np.hypot(*ab)
    i = int(np.argmax(dist)); print("knee at w =", WEIGHTS[i], "chord distance", dist[i])
    json.dump(dict(points=pts, knee_w=WEIGHTS[i], knee_index=i, chord_dist=dist.tolist()),
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "knee_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
