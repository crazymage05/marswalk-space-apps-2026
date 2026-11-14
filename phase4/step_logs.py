#!/usr/bin/env python3
"""
MARSWALK Phase 4 - walk step logs (docs/step_log_schema.md) -> (observation, action) pairs for behaviour cloning.

    from phase4.step_logs import load_step_logs, bc_pretrain
    pairs = load_step_logs("data/processed/roi/walk_logs/*.json")      # path, glob, dict, or list of these
    bc_pretrain(model, pairs, epochs=5)                                # model = SB3 PPO

Pair i is (observation at step i's cell, action that moved from step i to step i+1). The action recorded on step i+1 is
that move, so it labels the observation at step i. Time/energy/dose/fatigue in the observation are rebuilt with
phase4/astronaut.py (steps carry t_s and dose_uGy, used when present); the log's `sol` and `lmst_start_h` set the world
clock (defaults 4600 and 9.0). Observations are those of MarsWalkEnv (world-model channels).
Run `python phase4/step_logs.py` for a self-test on a synthetic log made from an A* route.
"""
import glob, json, math, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from phase4 import astronaut as A
from phase4.env import GridData, Walk, build_obs, W, CELL_M, DIRS, STOP, SOL_S


def _iter_docs(src):
    if isinstance(src, dict):
        yield src
    elif isinstance(src, (list, tuple)):
        for s in src:
            yield from _iter_docs(s)
    else:
        paths = sorted(glob.glob(str(src))) or [str(src)]
        for p in paths:
            d = json.load(open(p))
            yield from _iter_docs(d)


def _leg(g, a, b):
    """(3D distance, grade) of the move a -> b, as env.step computes it."""
    pd = CELL_M * math.hypot(b // W - a // W, b % W - a % W)
    dz = float(g.z[b // W, b % W] - g.z[a // W, a % W])
    return math.hypot(pd, dz), (dz / pd if pd else 0.0)


class _Tracker:
    """Energy, fatigue and retrace-leg totals along a logged walk, with the same astronaut.py rules as the env."""

    def __init__(self, g):
        self.g, self.p = g, g.profile
        self.energy = self.fatigue = self.ret_t = self.ret_e = 0.0

    def move(self, a, b):
        dist3, grade = _leg(self.g, a, b)
        if dist3 <= 0:
            return
        e = A.step_energy_kj(self.p, dist3, grade)
        self.energy += e
        self.fatigue = A.fatigue_update(self.p, self.fatigue, e)
        self.ret_t += dist3 / A.step_speed_mps(self.p, -grade, 0.0)
        self.ret_e += A.step_energy_kj(self.p, dist3, -grade)

    def margin(self, t_s):
        p = self.p
        keep = 1.0 - p.return_reserve_frac
        return 1.0 - max((t_s + self.ret_t) / (p.eva_time_h * 3600.0 * keep),
                         (self.energy + self.ret_e) / (p.energy_budget_kj * keep),
                         A.dose_uGy(t_s + self.ret_t) / p.dose_budget_uGy)


def load_step_logs(src, min_steps=2, cfg=None, profile="nominal"):
    """Return a list of (obs_dict, action) pairs. obs matches MarsWalkEnv.observation_space."""
    g = GridData.get(profile)
    pairs = []
    for doc in _iter_docs(src):
        steps = doc.get("steps", [])
        if len(steps) < min_steps:
            continue
        goal = int(doc["goal_cell"])
        sol, lmst0 = int(doc.get("sol", 4600)), float(doc.get("lmst_start_h", 9.0))
        trk = _Tracker(g)

        def obs_at(st):
            t = float(st.get("t_s", 0.0))
            wk = Walk(t_s=t, energy_kj=trk.energy, dose_uGy=float(st.get("dose_uGy", A.dose_uGy(t))), fatigue=trk.fatigue,
                      margin=trk.margin(t), sol=sol, lmst0=lmst0)
            return build_obs(g, st["cell"], goal, wk, cfg)

        for cur, nxt in zip(steps[:-1], steps[1:]):
            a = nxt.get("action")
            if a is None:
                continue
            pairs.append((obs_at(cur), int(a)))
            trk.move(cur["cell"], nxt["cell"])
        if doc.get("outcome") == "goal":                           # final step: STOP at the goal if the walk reached it
            pairs.append((obs_at(steps[-1]), STOP))
    return pairs


def action_between(a, b):
    dr, dc = b // W - a // W, b % W - a % W
    return DIRS.index((dr, dc))


def make_synthetic_log(route, session_id="synthetic-astar", sol=4600, lmst_start_h=9.0, profile="nominal", dyn_step_h=0.5):
    """Build a schema-conformant log from a list of cells (tests and A*-route demonstrations). Every step carries the
    world values of its cell (docs/step_log_schema.md); dynamic ones are evaluated at the env's dyn_step_h bins."""
    g = GridData.get(profile)
    w, p = g.world, g.profile
    steps, t, dose, trk = [], 0.0, 0.0, _Tracker(g)
    for i, c in enumerate(route):
        act = None
        if i:
            act = action_between(route[i - 1], c)
            dist3, grade = _leg(g, route[i - 1], c)
            t += dist3 / A.step_speed_mps(p, grade, trk.fatigue)
            dose = A.dose_uGy(t)
            trk.move(route[i - 1], c)
        sol_i, lmst_i = g.clock(sol, lmst_start_h, t)
        lm_q = (round(lmst_i / dyn_step_h) * dyn_step_h) % 24.0
        wc = w.cell(c, sol_i, lm_q)
        v = lambda k: wc[k]["value"]
        steps.append(dict(i=i, t_s=t, cell=int(c), row=int(c // W), col=int(c % W), action=act,
                          slope_deg=float(g.slope[c // W, c % W]), rough_m=float(g.rough[c // W, c % W]),
                          loose=float(g.loose[c // W, c % W]), dz_m=0.0, off_route_m=0.0, dose_uGy=dose,
                          events=["in_shadow"] if v("in_shadow") else [],
                          sol=sol_i, lmst_h=lmst_i, sun_el_deg=wc["sun_el"]["value"], in_shadow=bool(v("in_shadow")),
                          insolation_Wm2=v("insolation"), ground_temp_K=v("ground_temp_K"),
                          dose_rate_uGy_h=v("dose_rate_uGy_h"), ground_type=v("ground_type"), rock_frac=v("rock_frac"),
                          science=v("science"), sep_alert=bool(v("sep_alert")), energy_kj=trk.energy, fatigue=trk.fatigue,
                          return_margin=trk.margin(t)))
    return dict(session_id=session_id, mode="auto", planner="astar", sol=sol, lmst_start_h=lmst_start_h,
                profile=dict(name=p.name, max_slope_deg=p.max_slope_deg, rough_max_m=p.rough_max_m),
                start_cell=int(route[0]), goal_cell=int(route[-1]), planned_route=[int(c) for c in route], steps=steps,
                outcome="goal", summary=dict(distance_m=0, time_s=t, dose_uGy=dose, n_violations=0))


def bc_pretrain(model, pairs, epochs=5, batch_size=256, lr=1e-4, verbose=True):
    """Behaviour-cloning stub: cross-entropy of the PPO policy's action logits against logged actions.
    Works with an SB3 PPO model (uses model.policy.get_distribution). Returns the per-epoch mean loss list."""
    import torch
    from stable_baselines3.common.utils import obs_as_tensor
    if not pairs:
        return []
    pol = model.policy
    opt = torch.optim.Adam(pol.parameters(), lr=lr)
    patches = np.stack([p[0]["patch"] for p in pairs]); vecs = np.stack([p[0]["vec"] for p in pairs])
    acts = np.array([p[1] for p in pairs], np.int64)
    losses, n = [], len(pairs)
    pol.set_training_mode(True)
    for ep in range(epochs):
        perm = np.random.permutation(n)
        tot = 0.0
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            obs = obs_as_tensor({"patch": patches[idx], "vec": vecs[idx]}, model.device)
            dist = pol.get_distribution(obs)
            loss = -dist.log_prob(torch.as_tensor(acts[idx], device=model.device)).mean()
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item() * len(idx)
        losses.append(tot / n)
        if verbose:
            print(f"[bc] epoch {ep + 1}/{epochs} loss {losses[-1]:.4f}")
    pol.set_training_mode(False)
    return losses


if __name__ == "__main__":
    from phase4 import astar, costs, scenarios
    grid = costs.load_grid(); prof = A.get_profile("nominal")
    sc = scenarios.make_scenarios(grid, prof, n=3, seed=0, min_km=0.3, max_km=1.0)[0]
    r = astar.plan(grid, sc["start"], sc["goal"], prof)
    log = make_synthetic_log([int(c) for c in r["route"]])
    json.dump(log, open(os.path.join(ROOT, "data", "processed", "roi", "synthetic_walk_log.json"), "w"))
    pairs = load_step_logs(log)
    print(f"route {len(r['route'])} cells -> {len(pairs)} pairs; obs patch {pairs[0][0]['patch'].shape}, vec {pairs[0][0]['vec'].shape}")
    from phase4.env import MarsWalkEnv
    env = MarsWalkEnv()
    env.reset(options={"start_goal": (log["start_cell"], log["goal_cell"]), "sol": log["sol"], "lmst": log["lmst_start_h"]})
    o0 = env._obs()
    assert np.allclose(o0["patch"], pairs[0][0]["patch"]) and np.allclose(o0["vec"], pairs[0][0]["vec"], atol=1e-5)
    # replay the pairs' actions in the env: must reach the goal without touching a blocked cell
    for _, a in pairs[:-1]:
        _, _, term, trunc, info = env.step(a)
    print("replay reached goal:", info["is_success"], "unsafe:", info["unsafe"], "budget:", info["budget_exceeded"])
    from stable_baselines3 import PPO
    from phase4.train_ppo import PatchExtractor, make_env
    from stable_baselines3.common.vec_env import DummyVecEnv
    m = PPO("MultiInputPolicy", DummyVecEnv([make_env(0, 0, 0, False, 0.0)]), device="cuda",
            policy_kwargs=dict(features_extractor_class=PatchExtractor))
    print("bc losses:", [round(x, 3) for x in bc_pretrain(m, pairs, epochs=3, verbose=False)])
