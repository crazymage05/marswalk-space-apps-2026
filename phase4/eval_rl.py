#!/usr/bin/env python3
"""
MARSWALK Phase 4 - evaluate a trained PPO policy against A* on the campaign scenario + random scenarios.

    python phase4/eval_rl.py --model models/ppo_marswalk_latest.zip [--n 20] [--seed 0] [--min-km 0.3] [--max-km 1.5]

Writes data/processed/roi/routes_rl.json and docs/phase4_rl_eval.md. Deterministic policy unless --stochastic.
Every RL route (even a failed one) goes through the independent safety validator (phase4/safety_validator.py).
"""
import argparse, json, os, sys, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from phase4.env import MarsWalkEnv, W
from phase4 import astar, astronaut, costs, safety_validator, scenarios

ROI = os.path.join(ROOT, "data", "processed", "roi")


def rollout(model, env, start, goal, max_steps=None, sol=4600, lmst=9.0):
    obs, _ = env.reset(options={"start_goal": (start, goal), "sol": sol, "lmst": lmst})
    if max_steps:
        env.max_steps = max_steps
    route, info, term, trunc = [start], {}, False, False
    while not (term or trunc):
        if getattr(model, "_marswalk_maskable", False):
            act, _ = model.predict(obs, deterministic=not getattr(model, "_marswalk_stochastic", False), action_masks=env.action_masks())
        else:
            act, _ = model.predict(obs, deterministic=not getattr(model, "_marswalk_stochastic", False))
        obs, _, term, trunc, info = env.step(int(act))
        if env.cell != route[-1]:
            route.append(env.cell)
    return route, dict(reached=bool(info.get("is_success")), unsafe=bool(info.get("unsafe")), steps=env.steps,
                       unsafe_reason=info.get("unsafe_reason"), budget_exceeded=info.get("budget_exceeded"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.join(ROOT, "models", "ppo_marswalk_latest.zip"))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-km", type=float, default=0.3)
    ap.add_argument("--max-km", type=float, default=1.5)
    ap.add_argument("--profile", default="nominal")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    ap.add_argument("--max-steps", type=int, default=None, help="per-episode step cap (default: env rule, 4x geodesic + 60)")
    ap.add_argument("--out-json", default=os.path.join(ROI, "routes_rl.json"))
    ap.add_argument("--out-md", default=os.path.join(ROOT, "docs", "phase4_rl_eval.md"),
                    help="generated results table (kept apart from the hand-written docs/phase4_rl_results.md)")
    ap.add_argument("--note", default="")
    ap.add_argument("--stochastic", action="store_true", help="sample actions from the policy instead of taking the most likely one")
    ap.add_argument("--sol", type=int, default=4600, help="campaign sol of the evaluation walks (world clock)")
    ap.add_argument("--lmst", type=float, default=9.0, help="start LMST hour of every evaluation walk (daylight)")
    # env options: default = what the model was trained with (its .json); a flag given here overrides it, with a warning
    ap.add_argument("--visibility", action="store_const", const=True, default=None)
    ap.add_argument("--forbid-shadow", action="store_const", const=True, default=None)
    ap.add_argument("--no-forbid-night", action="store_const", const=True, default=None)
    ap.add_argument("--temp-range", type=float, nargs=2, default=None)
    ap.add_argument("--dose-model", default=None, choices=["astronaut", "world"])
    ap.add_argument("--mask-invalid", action="store_const", const=True, default=None)
    a = ap.parse_args()

    import torch
    from stable_baselines3 import PPO
    from phase4.train_ppo import PatchExtractor  # noqa: F401  (needed to unpickle the policy)
    from phase4.train_ppo import pick_device
    a.device = pick_device(a.device)
    print("device:", a.device, torch.cuda.get_device_name(0) if a.device == "cuda" else "", flush=True)
    meta_p = os.path.splitext(a.model)[0] + ".json"
    train_meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    if train_meta.get("algo") == "MaskablePPO":
        from sb3_contrib import MaskablePPO
        model = MaskablePPO.load(a.model, device=a.device); model._marswalk_maskable = True
    else:
        model = PPO.load(a.model, device=a.device)
    if not train_meta:
        print("WARNING: no training metadata next to the model (%s); env options come from the flags/defaults only" % meta_p, flush=True)
    te = train_meta.get("env", {})
    cli = dict(visibility=a.visibility, forbid_shadow=a.forbid_shadow,
               forbid_night=None if a.no_forbid_night is None else (not a.no_forbid_night),
               temp_range_K=a.temp_range, dose_model=a.dose_model, mask_invalid=a.mask_invalid)
    dflt = dict(visibility=False, forbid_shadow=False, forbid_night=True, temp_range_K=None, dose_model="astronaut", mask_invalid=False)
    trained = dict(te, mask_invalid=train_meta.get("mask_invalid", False))
    env_opts = {}
    for k, d in dflt.items():
        tv = trained.get(k, d)
        if isinstance(tv, list): tv = tuple(tv)
        v = tv if cli[k] is None else (tuple(cli[k]) if isinstance(cli[k], list) else cli[k])
        if cli[k] is not None and v != tv:
            print(f"WARNING: {k}={v} differs from training ({tv}); the policy will see a different environment", flush=True)
        env_opts[k] = v
    if "profile" in te and te["profile"] != a.profile:
        print(f"WARNING: --profile {a.profile} differs from training ({te['profile']})", flush=True)
    a.visibility = env_opts["visibility"]
    model._marswalk_stochastic = a.stochastic
    if a.stochastic:
        import torch as _t; _t.manual_seed(a.seed); model.set_random_seed(a.seed)
    print("env options:", env_opts, flush=True)

    grid = costs.load_grid()
    prof = astronaut.get_profile(a.profile)
    scs = scenarios.make_scenarios(grid, prof, n=a.n, seed=a.seed, min_km=a.min_km, max_km=a.max_km, include_campaign=True)
    astar_ref = {}
    ap_json = os.path.join(ROI, "routes_astar.json")
    if os.path.exists(ap_json):
        try:
            d = json.load(open(ap_json))
            lst = d.get("scenarios", d.get("routes", d)) if isinstance(d, dict) else d
            astar_ref = {s.get("id"): s for s in lst if isinstance(s, dict)}
        except Exception as e:
            print("could not read routes_astar.json:", e)
    env = MarsWalkEnv(level=5, seed=a.seed, profile=a.profile, sep_stop=te.get("sep_stop", False),
                      dyn_step_h=te.get("dyn_step_h", 0.5), coarse=te.get("coarse", False), trail=te.get("trail", False), **env_opts)
    rows = []
    for sc in scs:
        t0 = time.time()
        route, st = rollout(model, env, sc["start"], sc["goal"], a.max_steps, a.sol, a.lmst)
        m = astar.route_metrics(grid, route, prof) if len(route) > 1 else dict(distance_m=0.0, time_s=0.0, energy_kj=0.0, dose_uGy=0.0)
        v = safety_validator.validate(route, grid, prof)
        ref = astar_ref.get(sc["id"]) or {}
        # ids (rand00..) repeat across different --min-km/--max-km draws, so only reuse a stored A* route when
        # its start and goal are the same cells as this scenario; otherwise re-plan.
        r0 = ref.get("route") or []
        if not (r0 and int(r0[0]) == int(sc["start"]) and int(r0[-1]) == int(sc["goal"])):
            ref = {}
        if not ref.get("route"):
            r = astar.plan(grid, sc["start"], sc["goal"], prof)
            ref = dict(route=[int(c) for c in r["route"]], distance_m=r["distance_m"], time_s=r["time_s"],
                       energy_kj=r["energy_kj"], dose_uGy=r["dose_uGy"])
        ref_d = ref.get("distance_m") or 0.0
        rows.append(dict(
            id=sc["id"], kind=sc.get("kind"), start=int(sc["start"]), goal=int(sc["goal"]),
            straight_km=sc.get("distance_km"), reached_goal=st["reached"], hit_blocked_cell=st["unsafe"], steps=st["steps"],
            unsafe_reason=st["unsafe_reason"], budget_exceeded=st["budget_exceeded"], sol=a.sol, lmst_start_h=a.lmst,
            route=[int(c) for c in route], distance_m=float(m["distance_m"]), time_s=float(m["time_s"]),
            energy_kj=float(m["energy_kj"]), dose_uGy=float(m["dose_uGy"]),
            validator_ok=bool(v["ok"]), n_violations=int(v["summary"]["n_violations"]),
            checks_failed=v["summary"].get("checks_failed", []), violations=v["violations"][:10],
            astar=dict(route=ref.get("route", []), distance_m=ref_d, time_s=ref.get("time_s"),
                       energy_kj=ref.get("energy_kj"), dose_uGy=ref.get("dose_uGy")),
            length_ratio=(float(m["distance_m"]) / ref_d) if (st["reached"] and ref_d) else None))
        print(f"{sc['id']:>9} reached={st['reached']} unsafe={st['unsafe']} ratio={rows[-1]['length_ratio']} "
              f"valid={v['ok']} ({time.time() - t0:.1f}s)", flush=True)

    n = len(rows)
    reached = [r for r in rows if r["reached_goal"]]
    ok = [r for r in reached if r["validator_ok"]]
    ratios = [r["length_ratio"] for r in reached if r["length_ratio"]]
    summary = dict(n_scenarios=n, reached_goal=len(reached), reached_and_validated=len(ok),
                   success_rate=len(reached) / n, validated_success_rate=len(ok) / n,
                   astar_success_rate=float(np.mean([bool(r["astar"]["route"]) for r in rows])),
                   mean_length_ratio_vs_astar=float(np.mean(ratios)) if ratios else None,
                   median_length_ratio_vs_astar=float(np.median(ratios)) if ratios else None)
    doc = dict(planner="rl", algorithm="PPO (SB3, MultiInputPolicy + PatchExtractor)", model=os.path.relpath(a.model, ROOT),
               train_meta=train_meta, env_options=env_opts, profile=a.profile, seed=a.seed, min_km=a.min_km, max_km=a.max_km,
               summary=summary, scenarios=rows)
    json.dump(doc, open(a.out_json, "w"))
    print("wrote", a.out_json, summary, flush=True)

    L = ["# Phase 4 - RL walker results", "",
         f"Model `{doc['model']}`, PPO, trained {train_meta.get('steps', '?')} steps in {train_meta.get('wall_s', 0):.0f} s, "
         f"final curriculum level {train_meta.get('final_level', '?')}. Profile `{a.profile}`, scenarios: campaign + {a.n} random "
         f"(seed {a.seed}, {a.min_km}-{a.max_km} km), {'stochastic' if a.stochastic else 'deterministic'} policy, world clock sol {a.sol} LMST {a.lmst} h, visibility {a.visibility}. {a.note}", "",
         f"RL reached the goal in {len(reached)}/{n} scenarios; {len(ok)}/{n} reached it with a route that passed the safety validator. "
         f"A* found a route in {int(round(summary['astar_success_rate'] * n))}/{n}. "
         + (f"Mean RL/A* path length where RL arrived: {summary['mean_length_ratio_vs_astar']:.2f}." if ratios else "")
         + " The A* column is the reference; RL is not expected to match it on a first run.", "",
         "| scenario | straight km | RL reached | blocked cell | validator | violations | RL m | A* m | ratio | RL min | A* min | RL kJ | A* kJ | RL uGy |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda x, p=0: "-" if x is None else f"{x:.{p}f}"
    for r in rows:
        A_ = r["astar"]
        L.append(f"| {r['id']} | {f(r['straight_km'], 2)} | {'yes' if r['reached_goal'] else 'no'} | {'yes' if r['hit_blocked_cell'] else 'no'} | "
                 f"{'pass' if r['validator_ok'] else 'fail'} | {r['n_violations']} | {f(r['distance_m'])} | {f(A_['distance_m'])} | "
                 f"{f(r['length_ratio'], 2)} | {f(r['time_s'] / 60)} | {f((A_['time_s'] or 0) / 60)} | {f(r['energy_kj'])} | "
                 f"{f(A_['energy_kj'])} | {f(r['dose_uGy'], 1)} |")
    L += ["", "Routes: `data/processed/roi/routes_rl.json` (cell indices, row x 585 + col). Metrics for both planners come from "
          "`phase4/astar.route_metrics`; the validator is `phase4/safety_validator.validate` (round trip, nominal profile).", ""]
    open(a.out_md, "w", encoding="utf-8").write("\n".join(L))
    print("wrote", a.out_md)


if __name__ == "__main__":
    main()
