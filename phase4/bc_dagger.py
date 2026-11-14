#!/usr/bin/env python3
"""
MARSWALK Phase 4 - R1: behaviour cloning from A* + DAgger for the MaskablePPO walker (run 3).

    python phase4/bc_dagger.py selftest                       # expert field == astar.plan, expert replay in the env
    python phase4/bc_dagger.py run --out models/bc_v3        # generate expert data, BC, DAgger rounds, checks
    python phase4/bc_dagger.py check --model models/bc_v3_final.zip   # held-out accuracy / short-route success again

Expert. The label for a state is the first move of the A* route from that cell to the goal. phase4/astar.py is
single-source, so labelling every visited state would cost one A* per state; instead ONE backward Dijkstra from the goal
over the very same edge costs (astar._prep: cell_cost, climb weight, hard-blocked, no corner cutting) gives the cost-to-go
of every cell, and the expert action at any cell is argmin(edge cost + cost-to-go of the neighbour). Its total cost equals
astar.plan's (checked by `selftest`). The expert ignores time of day, fatigue and budgets, as A* does.

Data. Observations are the env's own (coarse + trail, same space as run 2), so no re-implementation can drift.
Start/goal pairs and clocks come from MarsWalkEnv.sample_pair/sample_time at curriculum levels 0-5 with training seeds
(>= 100000), not from the evaluation scenarios (scenarios.make_scenarios with seed 1).

DAgger (Ross, Gordon, Bagnell 2011). Round i: roll out the current policy (with probability beta the expert acts instead),
label every visited state with the expert action, aggregate, continue training. The last round also records discounted
returns of the policy's own rollouts, used to fit the critic (actor features frozen) so PPO fine-tuning starts from a
critic that matches the policy.
"""
import argparse, contextlib, glob, json, math, multiprocessing as mp, os, sys, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from phase4.env import MarsWalkEnv, W, H, DIRS, STOP, LEVELS
from phase4 import astar, astronaut, costs

ENV_KW = dict(coarse=True, trail=True)            # run 2's observation options (--coarse --trail), MaskablePPO
GAMMA = 0.995
LEVEL_WEIGHTS = np.array([0.05, 0.08, 0.15, 0.20, 0.25, 0.27])
SEED0 = 100_000                                    # training seeds; evaluation scenarios use rng seed 1 on a different sampler


# ------------------------------------------------------------------------------------------------ expert
class Expert:
    def __init__(self, profile="nominal"):
        from scipy.sparse import csr_matrix
        grid = costs.load_grid()
        prof = astronaut.get_profile(profile)
        blocked, mu, z = astar._prep(grid, prof)[:3]
        self.blocked, self.grid, self.prof = blocked, grid, prof
        cm, clw = grid["cell_m"], prof.climb_weight
        free = ~blocked
        self.cost = np.full((8, H, W), np.inf, np.float64)       # cost[a, r, c]: edge cost of move a from (r, c)
        rows, cols, data = [], [], []
        idx = np.arange(H * W).reshape(H, W)
        for a, (dr, dc) in enumerate(DIRS):
            r0, r1 = max(0, -dr), H - max(0, dr)
            c0, c1 = max(0, -dc), W - max(0, dc)
            sr, sc = slice(r0, r1), slice(c0, c1)
            dr_, dc_ = slice(r0 + dr, r1 + dr), slice(c0 + dc, c1 + dc)
            ok = free[sr, sc] & free[dr_, dc_]
            if dr and dc:                                          # no corner cutting (astar.py)
                ok &= free[sr, dc_] & free[dr_, sc]
            d = cm * (math.sqrt(2) if dr and dc else 1.0)
            c = d * 0.5 * (mu[sr, sc] + mu[dr_, dc_]) + clw * np.maximum(z[dr_, dc_] - z[sr, sc], 0.0)
            c = np.where(ok, c, np.inf)
            self.cost[a, sr, sc] = c
            rr, cc = np.nonzero(ok)
            rows.append(idx[sr, sc][rr, cc]); cols.append(idx[dr_, dc_][rr, cc]); data.append(c[rr, cc])
        rows, cols, data = np.concatenate(rows), np.concatenate(cols), np.concatenate(data)
        # cost-to-go from the goal = shortest path from the goal in the TRANSPOSED graph (edge i -> j costs G[i, j])
        self.gt = csr_matrix((data, (cols, rows)), shape=(H * W, H * W))

    def field(self, goal):
        from scipy.sparse.csgraph import dijkstra
        return dijkstra(self.gt, directed=True, indices=int(goal))

    def action(self, field, cell):
        """First move of the A* route from `cell` (None when the goal is unreachable or cell is the goal)."""
        r, c = divmod(int(cell), W)
        best, ba = np.inf, None
        for a, (dr, dc) in enumerate(DIRS):
            e = self.cost[a, r, c]
            if not np.isfinite(e):
                continue
            q = e + field[(r + dr) * W + (c + dc)]
            if q < best - 1e-9:
                best, ba = q, a
        return ba, (field[cell] if ba is not None else np.inf)



# ------------------------------------------------------------------------------------------------ memory guard
def free_gb():
    try:
        import psutil
        return psutil.virtual_memory().available / 2 ** 30
    except ImportError:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out) / 2 ** 20                       # kB -> GB


def ram_guard(min_gb, tag=""):
    """Block while free RAM is under min_gb (other agents share this machine)."""
    while True:
        f = free_gb()
        if f >= min_gb:
            return f
        print(f"[ram] {tag}: free {f:.1f} GB < {min_gb:.1f} GB, pausing 20 s", flush=True)
        time.sleep(20)


# ------------------------------------------------------------------------------------------------ rollouts (workers)
_G = {}


def _init(profile, threads=1):
    import torch
    torch.set_num_threads(threads)
    _G["env"] = MarsWalkEnv(level=0, seed=0, profile=profile, **ENV_KW)
    _G["expert"] = Expert(profile)
    _G["model_path"], _G["model"] = None, None


def _get_model(path):
    if _G["model_path"] != path:
        from sb3_contrib import MaskablePPO
        from phase4.train_ppo import PatchExtractor  # noqa: F401
        _G["model"] = MaskablePPO.load(path, device="cpu")
        _G["model_path"] = path
    return _G["model"]


def rollout_episode(task):
    """task = dict(seed, level, model (path or None), beta, det, stride, cap_factor). Only every `stride`-th state is stored."""
    env, ex = _G["env"], _G["expert"]
    env.set_level(task["level"])
    model = _get_model(task["model"]) if task.get("model") else None
    rng = np.random.default_rng(task["seed"] + 7)
    obs, info = env.reset(seed=task["seed"])
    fld = ex.field(env.goal)
    stride = task.get("stride", 1)
    keep0 = task["seed"] % stride
    P, V, C, M, A_, IDX, R = [], [], [], [], [], [], []
    res = dict(success=False, unsafe=False, budget=None, steps=0)
    cap = int(task.get("cap_factor", 99) * env._d(env.cell)) + 40       # policy rollouts: stop recording once far into a loop
    t = 0
    while t < cap:
        mask = env.action_masks()
        ea, _ = ex.action(fld, env.cell)
        if ea is None or not mask[ea]:                     # unreachable or night: nothing to learn here
            break
        if t % stride == keep0:
            P.append(obs["patch"].astype(np.float16)); V.append(obs["vec"]); C.append(obs["coarse"].astype(np.float16))
            M.append(mask); A_.append(ea); IDX.append(t)
        if model is None or rng.random() < task.get("beta", 0.0):
            act = ea
        else:
            act = int(model.predict(obs, action_masks=mask, deterministic=task["det"])[0])
        obs, rew, term, trunc, inf = env.step(act)
        R.append(rew); t += 1
        if term or trunc:
            res.update(success=bool(inf.get("is_success")), unsafe=bool(inf.get("unsafe")), budget=inf.get("budget_exceeded"))
            break
    res["steps"] = t
    ret = np.zeros(len(R), np.float32)
    g = 0.0
    for i in range(len(R) - 1, -1, -1):
        g = R[i] + GAMMA * g
        ret[i] = g
    if not P:
        return dict(n=0, res=res, level=task["level"], seed=task["seed"])
    return dict(n=len(P), res=res, level=task["level"], seed=task["seed"], patch=np.stack(P), vec=np.stack(V).astype(np.float32),
                coarse=np.stack(C), mask=np.stack(M), act=np.array(A_, np.int8), ret=ret[np.array(IDX)])


def run_batch(bt):
    """A worker runs a batch of episodes and writes ONE compressed shard; only (path, n, res) go back through the pipe."""
    parts = {k: [] for k in ("patch", "vec", "coarse", "mask", "act", "ret", "ep", "level")}
    res = []
    for t in bt["eps"]:
        e = rollout_episode(t)
        res.append(dict(level=e["level"], seed=e["seed"], **e["res"]))
        if e["n"]:
            for k in ("patch", "vec", "coarse", "mask", "act", "ret"):
                parts[k].append(e[k])
            parts["ep"].append(np.full(e["n"], t["seed"], np.int64)); parts["level"].append(np.full(e["n"], e["level"], np.int8))
    n = 0
    if bt.get("path") and parts["act"]:
        arr = {k: np.concatenate(v) for k, v in parts.items()}
        n = len(arr["act"])
        tmp = bt["path"] + ".tmp.npz"
        np.savez_compressed(tmp, res=np.array(json.dumps(res)), **arr)
        os.replace(tmp, bt["path"])                        # atomic: a shard either exists complete or not at all
    return dict(path=bt.get("path"), n=n, res=res)


def make_tasks(n, seed0, model=None, beta=0.0, mix_det=True, stride=1):
    rng = np.random.default_rng(seed0)
    levels = rng.choice(len(LEVELS), size=n, p=LEVEL_WEIGHTS / LEVEL_WEIGHTS.sum())
    return [dict(seed=seed0 + i, level=int(l), model=model, beta=beta, det=(i % 2 == 0) if mix_det else True,
                 cap_factor=2.0 if model else 99, stride=stride) for i, l in enumerate(levels)]


def summarize(res):
    summ = {}
    for L in range(len(LEVELS)):
        rs = [r for r in res if r["level"] == L]
        if rs:
            summ[L] = dict(n=len(rs), success=float(np.mean([r["success"] for r in rs])), unsafe=float(np.mean([r["unsafe"] for r in rs])),
                           budget=float(np.mean([r["budget"] is not None for r in rs])))
    summ["all"] = dict(n=len(res), success=float(np.mean([r["success"] for r in res])) if res else 0.0)
    return summ


def shard_paths(d):
    return sorted(p for p in glob.glob(os.path.join(d, "b*.npz")) if not p.endswith(".tmp.npz"))


def shard_res(p):
    with np.load(p) as z:
        return json.loads(str(z["res"]))


def collect(pool, tasks, tag, outdir=None, per_batch=12, min_free=6.0, workers=4):
    """Run the tasks in batches on the pool. With `outdir`, each batch becomes shard bNNNN.npz (existing shards are skipped, so
    the step resumes); the parent keeps only small summaries. Submission pauses while free RAM < min_free GB."""
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    batches = [dict(eps=tasks[i:i + per_batch], path=(os.path.join(outdir, f"b{i // per_batch:04d}.npz") if outdir else None))
               for i in range(0, len(tasks), per_batch)]
    todo = [b for b in batches if not (b["path"] and os.path.exists(b["path"]))]
    print(f"[{tag}] {len(batches)} batches, {len(batches) - len(todo)} already on disk, {len(todo)} to run", flush=True)
    t0, pend, done, res = time.time(), [], 0, []
    todo_it = iter(todo)
    nxt = next(todo_it, None)
    while nxt is not None or pend:
        while nxt is not None and len(pend) < workers:
            ram_guard(min_free, tag)
            pend.append(pool.apply_async(run_batch, (nxt,)))
            nxt = next(todo_it, None)
        for h in list(pend):
            if h.ready():
                r = h.get(); pend.remove(h); done += 1; res += r["res"]
                if done % 5 == 0 or done == len(todo):
                    print(f"[{tag}] {done}/{len(todo)} batches, {time.time() - t0:.0f} s, free RAM {free_gb():.1f} GB", flush=True)
        time.sleep(0.5)
    if outdir:
        res = [r for p in shard_paths(outdir) for r in shard_res(p)]      # includes shards from an earlier session
    return summarize(res)


# ------------------------------------------------------------------------------------------------ streaming data
def stream(paths, split="all", bs=512, shuffle=True, buf_shards=24, min_ep=None, seed=0):
    """Yield dict batches from shards without holding the dataset: `buf_shards` shards are mixed at a time.
    split: 'train' (episode id % 10 != 0), 'val' (== 0), 'all'. min_ep keeps only episodes with id >= min_ep."""
    rng = np.random.default_rng(seed)
    paths = list(paths)
    if shuffle:
        rng.shuffle(paths)
    for g in range(0, len(paths), buf_shards):
        chunk = []
        for p in paths[g:g + buf_shards]:
            with np.load(p) as z:
                ep = z["ep"]
                m = np.ones(len(ep), bool) if split == "all" else ((ep % 10 == 0) if split == "val" else (ep % 10 != 0))
                if min_ep is not None:
                    m &= ep >= min_ep
                if m.any():
                    chunk.append({k: z[k][m] for k in ("patch", "vec", "coarse", "mask", "act", "ret", "ep")})
        if not chunk:
            continue
        d = {k: np.concatenate([c[k] for c in chunk]) for k in chunk[0]}
        order = rng.permutation(len(d["act"])) if shuffle else np.arange(len(d["act"]))
        for i in range(0, len(order), bs):
            idx = np.sort(order[i:i + bs])
            yield {k: v[idx] for k, v in d.items()}
        del d, chunk


def count_samples(paths, split):
    n = 0
    for p in paths:
        with np.load(p) as z:
            ep = z["ep"]
            n += int(((ep % 10 == 0) if split == "val" else (ep % 10 != 0) if split == "train" else np.ones(len(ep), bool)).sum())
    return n

# ------------------------------------------------------------------------------------------------ model / training
def new_model(device):
    from stable_baselines3.common.vec_env import DummyVecEnv
    from sb3_contrib import MaskablePPO
    from phase4.train_ppo import PatchExtractor
    venv = DummyVecEnv([lambda: MarsWalkEnv(level=0, seed=0, **ENV_KW)])
    return MaskablePPO("MultiInputPolicy", venv, device=device, learning_rate=3e-4, n_steps=256, batch_size=512, n_epochs=4,
                       gamma=GAMMA, gae_lambda=0.95, ent_coef=0.01, clip_range=0.2, seed=0, verbose=0,
                       policy_kwargs=dict(features_extractor_class=PatchExtractor, net_arch=dict(pi=[256, 256], vf=[256, 256])))




def _tens(b, dev):
    import torch
    t = lambda x: torch.as_tensor(x).to(dev).float()
    return {"patch": t(b["patch"]), "vec": t(b["vec"]), "coarse": t(b["coarse"])}, b["mask"]


def accuracy(model, paths, dev, split="val", min_ep=None, bs=2048):
    import torch
    pol = model.policy
    pol.set_training_mode(False)
    hit = n = 0
    with torch.no_grad():
        for b in stream(paths, split, bs=bs, shuffle=False, buf_shards=8, min_ep=min_ep):
            obs, mask = _tens(b, dev)
            dist = pol.get_distribution(obs, action_masks=mask)
            pred = dist.distribution.probs.argmax(1).cpu().numpy()
            hit += int((pred == b["act"]).sum()); n += len(pred)
    return (hit / n if n else float("nan")), n


def train_bc(model, paths, epochs, lr, bs, dev, tag):
    """Masked cross-entropy on the policy head (actor + shared features), streaming shards; returns history."""
    import torch
    from tools.gpu_lock import gpu_lock, wait_cool
    pol = model.policy
    opt = torch.optim.Adam(pol.parameters(), lr=lr)
    hist = []
    gpu = str(dev) != "cpu"
    with (gpu_lock("r1") if gpu else contextlib.nullcontext()):
        for ep in range(epochs):
            pol.set_training_mode(True)
            tot, n = 0.0, 0
            for k, b in enumerate(stream(paths, "train", bs=bs, seed=ep + int(time.time()) % 1000)):
                obs, mask = _tens(b, dev)
                dist = pol.get_distribution(obs, action_masks=mask)
                loss = -dist.log_prob(torch.as_tensor(b["act"].astype(np.int64), device=dev)).mean()
                opt.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(pol.parameters(), 1.0)
                opt.step()
                tot += loss.item() * len(b["act"]); n += len(b["act"])
                if gpu and k % 100 == 99:
                    wait_cool()
            acc, nv = accuracy(model, paths, dev, "val")
            hist.append(dict(epoch=ep + 1, loss=tot / max(n, 1), val_acc=acc, val_n=nv))
            print(f"[{tag}] epoch {ep + 1}/{epochs} loss {tot / max(n, 1):.4f} held-out acc {acc:.4f} (n={nv})", flush=True)
            if gpu:
                wait_cool()
    return hist


def fit_value(model, paths, epochs, dev, bs=512, lr=3e-4):
    """Regress the critic head on discounted returns of the policy's own rollouts; shared features frozen."""
    import torch
    from tools.gpu_lock import gpu_lock, wait_cool
    pol = model.policy
    params = list(pol.mlp_extractor.value_net.parameters()) + list(pol.value_net.parameters())
    opt = torch.optim.Adam(params, lr=lr)
    out = []
    gpu = str(dev) != "cpu"
    with (gpu_lock("r1") if gpu else contextlib.nullcontext()):
        for ep in range(epochs):
            tot, n = 0.0, 0
            for k, b in enumerate(stream(paths, "all", bs=bs, seed=ep)):
                obs, _ = _tens(b, dev)
                with torch.no_grad():
                    feats = pol.extract_features(obs)
                    if isinstance(feats, tuple): feats = feats[1]
                v = pol.value_net(pol.mlp_extractor.forward_critic(feats)).squeeze(-1)
                tgt = torch.as_tensor(b["ret"], device=dev).float()
                loss = torch.nn.functional.smooth_l1_loss(v, tgt)
                opt.zero_grad(); loss.backward(); opt.step()
                tot += loss.item() * len(tgt); n += len(tgt)
                if gpu and k % 100 == 99: wait_cool()
            out.append(tot / max(n, 1)); print(f"[value] epoch {ep + 1}/{epochs} huber {tot / max(n, 1):.4f}", flush=True)
    return out


def save_model(model, path, extra=None):
    model.save(path)
    meta = dict(algo="MaskablePPO", env=dict(profile="nominal", visibility=False, forbid_shadow=False, forbid_night=True,
                temp_range_K=None, sep_stop=False, dyn_step_h=0.5, dose_model="astronaut", coarse=True, trail=True),
                mask_invalid=False, final_level=0, steps=0, wall_s=0, kind="behaviour cloning + DAgger (no PPO)")
    meta.update(extra or {})
    json.dump(meta, open(os.path.splitext(path)[0] + ".json", "w"), indent=1)


# ------------------------------------------------------------------------------------------------ commands
def cmd_selftest(a):
    ex = Expert()
    grid, prof = ex.grid, ex.prof
    from phase4 import scenarios
    scs = scenarios.make_scenarios(grid, prof, n=a.n, seed=5, min_km=0.1, max_km=1.5)
    worst = 0.0
    for sc in scs:
        ref = astar.plan(grid, sc["start"], sc["goal"], prof)
        fld = ex.field(sc["goal"])
        c, tot, n = sc["start"], 0.0, 0
        while c != sc["goal"] and n < 5000:
            act, _ = ex.action(fld, c)
            tot += ex.cost[act, c // W, c % W]
            dr, dc = DIRS[act]; c = (c // W + dr) * W + (c % W + dc); n += 1
        rel = abs(tot - ref["cost"]) / ref["cost"]
        worst = max(worst, rel)
        assert c == sc["goal"] and rel < 1e-6, (sc, tot, ref["cost"])
    print(f"[selftest] expert path cost == astar.plan cost on {len(scs)} routes (worst rel diff {worst:.2e})")
    env = MarsWalkEnv(level=0, seed=1, **ENV_KW)
    assert (env.g.blocked == ex.blocked).all(), "env blocked mask differs from astar's"
    print("[selftest] env.g.blocked == astar hard-blocked mask")
    ok = 0
    for i, L in enumerate([0, 1, 2, 3, 4, 5] * (a.n // 6 + 1)):
        env.set_level(L); obs, _ = env.reset(seed=SEED0 + 900000 + i); fld = ex.field(env.goal)
        while True:
            act, _ = ex.action(fld, env.cell)
            obs, _, te, tr, inf = env.step(act)
            if te or tr: break
        ok += bool(inf["is_success"])
        if i + 1 >= a.n: break
    print(f"[selftest] expert replayed inside the env reached the goal in {ok}/{a.n} episodes")




def load_model(path, dev):
    from sb3_contrib import MaskablePPO
    from phase4.train_ppo import PatchExtractor  # noqa: F401
    return MaskablePPO.load(path, device=dev)


def make_pool(workers):
    workers = max(1, min(int(workers), 4))               # hard cap: shared machine
    ram_guard(6.0, "pool start")
    return mp.get_context("spawn").Pool(workers, initializer=_init, initargs=("nominal", 1)), workers


def cmd_run(a):
    from phase4.train_ppo import pick_device
    dev = pick_device(a.device)
    data = os.path.join(ROOT, a.out + "_data")
    logp = os.path.join(ROOT, a.out + "_log.json")
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    log = json.load(open(logp)) if (os.path.exists(logp) and a.resume) else dict(args=vars(a), rounds=[])
    done_rounds = {r["iteration"] for r in log["rounds"]}
    t_all = time.time()
    pool, nw = make_pool(a.workers)
    try:
        # 1. expert shards (resumable)
        exp_dir = os.path.join(data, "expert")
        summ = collect(pool, make_tasks(a.episodes, SEED0, stride=a.stride), "expert", exp_dir, a.per_batch, a.min_free_gb, nw)
        paths = shard_paths(exp_dir)
        log["expert_data"] = dict(episodes=a.episodes, stride=a.stride, replay_success=summ, samples=count_samples(paths, "all"))
        print(f"[expert] {log['expert_data']['samples']} samples; A* replay {summ['all']}", flush=True)
        log["split"] = dict(train=count_samples(paths, "train"), heldout=count_samples(paths, "val"))
        # 2. behaviour cloning
        mp_ = os.path.join(ROOT, a.out + "_bc0.zip")
        if os.path.exists(mp_):
            model = load_model(mp_, dev); print("[bc] resuming from", mp_, flush=True)
        else:
            model = new_model(dev)
            log["bc"] = train_bc(model, paths, a.epochs, a.lr, a.batch, dev, "bc")
            log["bc_expert_heldout_acc"] = accuracy(model, paths, dev, "val")[0]
            save_model(model, mp_)
            json.dump(log, open(logp, "w"), indent=1)
        # 3. DAgger rounds
        last_dir = None
        for it in range(1, a.dagger_iters + 1):
            beta = a.beta * (0.5 ** (it - 1)) if it < a.dagger_iters else 0.0
            d_dir = os.path.join(data, f"dagger{it}")
            mi = os.path.join(ROOT, a.out + f"_dagger{it}.zip")
            last_dir = d_dir
            if os.path.exists(mi):
                model = load_model(mi, dev); mp_ = mi; print(f"[dagger {it}] done earlier, loaded", flush=True); continue
            t0 = time.time()
            summ = collect(pool, make_tasks(a.dagger_episodes, SEED0 + 200000 * it, model=mp_, beta=beta, stride=a.dagger_stride),
                           f"dagger{it}", d_dir, a.per_batch, a.min_free_gb, nw)
            paths = shard_paths(exp_dir) + [p for j in range(1, it + 1) for p in shard_paths(os.path.join(data, f"dagger{j}"))]
            print(f"[dagger {it}] beta {beta:.2f}: policy rollouts {summ['all']}; per level "
                  f"{ {k: round(v['success'], 2) for k, v in summ.items() if k != 'all'} }", flush=True)
            h = train_bc(model, paths, a.dagger_epochs, a.lr * 0.5, a.batch, dev, f"dagger{it}")
            dag_acc = accuracy(model, paths, dev, "val", min_ep=SEED0 + 200000)
            log["rounds"] = [r for r in log["rounds"] if r["iteration"] != it]
            log["rounds"].append(dict(iteration=it, beta=beta, rollout_success=summ, new_samples=count_samples(shard_paths(d_dir), "all"),
                                      total_samples=count_samples(paths, "all"), train=h, heldout_acc_all=h[-1]["val_acc"],
                                      heldout_acc_dagger_states=dag_acc[0], heldout_dagger_n=dag_acc[1], minutes=(time.time() - t0) / 60))
            mp_ = mi
            save_model(model, mp_)
            json.dump(log, open(logp, "w"), indent=1)
        # 4. critic on the last (pure-policy) round
        final = os.path.join(ROOT, a.out + "_final.zip")
        if not os.path.exists(final):
            if last_dir and a.value_epochs:
                log["value_huber"] = fit_value(model, shard_paths(last_dir), a.value_epochs, dev)
            save_model(model, final, dict(bc_samples=log["rounds"][-1]["total_samples"] if log["rounds"] else log["expert_data"]["samples"]))
        log["pure_bc_check"] = check_policy(pool, final, a.check_episodes, nw)
        log["wall_min"] = (time.time() - t_all) / 60
        json.dump(log, open(logp, "w"), indent=1)
        print("[done]", json.dumps(log["pure_bc_check"]), f"{log['wall_min']:.1f} min", flush=True)
    finally:
        pool.terminate()


def check_policy(pool, model_path, n_per_level, workers=4):
    out = {}
    for det in (True, False):
        tasks = []
        for L in (0, 1, 2, 3, 5):
            tasks += [dict(seed=SEED0 + 5_000_000 + 1000 * L + i, level=L, model=model_path, beta=0.0, det=det, cap_factor=99)
                      for i in range(n_per_level)]
        out["deterministic" if det else "stochastic"] = collect(pool, tasks, "check-" + ("det" if det else "stoch"), None, 5, 6.0, workers)
    return out


def cmd_check(a):
    pool, nw = make_pool(a.workers)
    try:
        r = check_policy(pool, os.path.join(ROOT, a.model) if not os.path.isabs(a.model) else a.model, a.check_episodes, nw)
        print(json.dumps(r, indent=1))
    finally:
        pool.terminate()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("selftest"); s.add_argument("--n", type=int, default=12)
    r = sp.add_parser("run")
    r.add_argument("--out", default="models/bc_v3", help="prefix of the saved models/log (shards go to <out>_data/)")
    r.add_argument("--episodes", type=int, default=1200, help="expert (A*) episodes over curriculum levels 0-5")
    r.add_argument("--stride", type=int, default=3, help="keep every n-th expert state (neighbouring states are near duplicates)")
    r.add_argument("--dagger-stride", type=int, default=3)
    r.add_argument("--epochs", type=int, default=12)
    r.add_argument("--dagger-iters", type=int, default=3)
    r.add_argument("--dagger-episodes", type=int, default=400)
    r.add_argument("--dagger-epochs", type=int, default=4)
    r.add_argument("--beta", type=float, default=0.3, help="expert-action probability in DAgger round 1, halved per round, 0 in the last")
    r.add_argument("--value-epochs", type=int, default=3)
    r.add_argument("--lr", type=float, default=3e-4)
    r.add_argument("--batch", type=int, default=512)
    r.add_argument("--workers", type=int, default=4, help="worker processes (capped at 4)")
    r.add_argument("--per-batch", type=int, default=12, help="episodes per shard")
    r.add_argument("--min-free-gb", type=float, default=6.0, help="pause worker submission while free RAM is below this")
    r.add_argument("--check-episodes", type=int, default=40)
    r.add_argument("--resume", action="store_true", help="keep the existing log (shards and models already on disk are always reused)")
    r.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    c = sp.add_parser("check"); c.add_argument("--model", required=True); c.add_argument("--check-episodes", type=int, default=40)
    c.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    {"selftest": cmd_selftest, "run": cmd_run, "check": cmd_check}[a.cmd](a)
