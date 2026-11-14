#!/usr/bin/env python3
"""
MARSWALK Phase 4 - PPO training for the RL walker (Stable-Baselines3; NVIDIA, Apple GPU or CPU, picked automatically).

    python phase4/train_ppo.py --timesteps 3000000 --n-envs 8
    python phase4/train_ppo.py --timesteps 3000000 --resume models/ppo_marswalk_latest.zip --start-level 3

Curriculum: all envs start at --start-level; when the rolling success rate over the last 100 episodes reaches
--advance-success (0.8) and at least 100 episodes have finished since the last change, every env moves up one level
(distance bands in phase4/env.py LEVELS). Logs: runs/<name>/ (tensorboard), checkpoints: models/.
"""
import argparse, json, os, signal, sys, time
from collections import deque
import numpy as np
import torch
import torch.nn as nn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv
from phase4.env import MarsWalkEnv, LEVELS


class PatchExtractor(BaseFeaturesExtractor):
    """Small CNN on the 16(+1)x15x15 world patch + MLP on the 14-d vector -> 320 features;
    with obs["coarse"] (243 m map view) a second small CNN adds coarse_out features."""

    def __init__(self, observation_space, cnn_out=256, vec_out=64, coarse_out=128):
        has_c = "coarse" in observation_space.spaces
        super().__init__(observation_space, cnn_out + vec_out + (coarse_out if has_c else 0))
        c = observation_space["patch"].shape[0]
        self.cnn = nn.Sequential(
            nn.Conv2d(c, 32, 3, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(),      # 8x8
            nn.Conv2d(64, 64, 3, stride=2, padding=1), nn.ReLU(),      # 4x4
            nn.Flatten(), nn.Linear(64 * 4 * 4, cnn_out), nn.ReLU())
        self.mlp = nn.Sequential(nn.Linear(observation_space["vec"].shape[0], vec_out), nn.ReLU())
        self.ccnn = None
        if has_c:
            k = observation_space["coarse"].shape[0]
            self.ccnn = nn.Sequential(
                nn.Conv2d(k, 32, 3, padding=1), nn.ReLU(),
                nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(),  # 8x8
                nn.Conv2d(64, 64, 3, stride=2, padding=1), nn.ReLU(),  # 4x4
                nn.Flatten(), nn.Linear(64 * 4 * 4, coarse_out), nn.ReLU())

    def forward(self, obs):
        f = [self.cnn(obs["patch"]), self.mlp(obs["vec"])]
        if self.ccnn is not None:
            f.append(self.ccnn(obs["coarse"]))
        return torch.cat(f, dim=1)


class CoolCallback(BaseCallback):
    """Pause while the GPU is above tools/gpu_lock.MAX_C (the laptop overheats)."""

    def __init__(self, every=2048):
        super().__init__()
        self.every, self._next = every, every

    def _on_step(self):
        if self.num_timesteps >= self._next:
            self._next = self.num_timesteps + self.every
            from tools.gpu_lock import wait_cool
            wait_cool()
        return True


class CurriculumCallback(BaseCallback):
    def __init__(self, advance_success=0.8, window=100, min_eps=100, max_minutes=None, state_path=None, meta=None,
                 state_every=250_000):
        super().__init__()
        self.adv, self.win, self.min_eps = advance_success, window, min_eps
        self.hist = deque(maxlen=window)
        self.since = 0
        self.level = 0
        self.t0 = time.time()
        self.max_minutes = max_minutes
        self.state_path, self.meta, self.state_every = state_path, meta or {}, state_every
        self._next_state = state_every
        self.level_log = []                                  # (timestep, new level)

    def write_state(self):
        """Curriculum level + run options, so a checkpoint or an interrupted run can be resumed and evaluated."""
        if not self.state_path:
            return
        d = dict(self.meta, steps=int(self.num_timesteps), wall_s=time.time() - self.t0, final_level=self.level,
                 level_log=self.level_log, success_100=float(np.mean(self.hist)) if self.hist else None)
        tmp = self.state_path + ".tmp"
        json.dump(d, open(tmp, "w"), indent=1)
        os.replace(tmp, self.state_path)

    def _on_training_start(self):
        self.level = int(self.training_env.env_method("get_level", indices=[0])[0])

    def _on_step(self):
        for info, done in zip(self.locals["infos"], self.locals["dones"]):
            if done:
                self.hist.append(float(info.get("is_success", False)))
                self.since += 1
        if self.since >= self.min_eps and len(self.hist) == self.win and np.mean(self.hist) >= self.adv \
                and self.level < len(LEVELS) - 1:
            self.level += 1
            self.training_env.env_method("set_level", self.level)
            self.since = 0
            self.hist.clear()
            self.level_log.append((int(self.num_timesteps), self.level))
            print(f"[curriculum] step {self.num_timesteps}: level -> {self.level} {LEVELS[self.level]} m", flush=True)
            self.write_state()
        if self.num_timesteps >= self._next_state:
            self._next_state += self.state_every
            self.write_state()
        if self.hist:
            self.logger.record("curriculum/level", self.level)
            self.logger.record("curriculum/success_100", float(np.mean(self.hist)))
        if self.max_minutes and (time.time() - self.t0) / 60 > self.max_minutes:
            print("[train] wall-clock limit reached, stopping", flush=True)
            return False
        return True



def pick_device(want="auto"):
    """cuda (NVIDIA), mps (Apple GPU) or cpu. 'auto' = cuda if present, else mps if present, else cpu.
    Measured on an M5 Pro (1-minute runs, same code): mps 1185 / 1468 steps/s vs cpu 838 / 792 steps/s at 8 / 12 envs."""
    if want == "cuda" or (want == "auto" and torch.cuda.is_available()):
        assert torch.cuda.is_available(), "CUDA requested but not available"
        return "cuda"
    if want == "mps" or (want == "auto" and torch.backends.mps.is_available()):
        assert torch.backends.mps.is_available(), "Apple MPS requested but not available"
        return "mps"
    return "cpu"

def make_env(rank, level, seed, mask_invalid, science_bonus, **env_kw):
    """env_kw: MarsWalkEnv options (profile, visibility, forbid_shadow, forbid_night, temp_range_K, sep_stop, dyn_step_h, ...)."""
    def _f():
        return Monitor(MarsWalkEnv(level=level, mask_invalid=mask_invalid, science_bonus=science_bonus, seed=seed + rank, **env_kw),
                       info_keywords=("is_success",))
    return _f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=3_000_000)
    ap.add_argument("--n-envs", type=int, default=8)
    ap.add_argument("--n-steps", type=int, default=256, help="rollout length per env")
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--start-level", type=int, default=None,
                    help="default 0; with --resume, the final_level stored next to the resumed model (<model>.json or ppo_marswalk_latest.json)")
    ap.add_argument("--no-latest", action="store_true", help="do not overwrite models/ppo_marswalk_latest.* (for speed tests)")
    ap.add_argument("--advance-success", type=float, default=0.8)
    ap.add_argument("--mask-invalid", action="store_true", help="refuse blocked moves instead of ending the episode")
    ap.add_argument("--science-bonus", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name", default=None)
    ap.add_argument("--resume", default=None)
    ap.add_argument("--max-minutes", type=float, default=None, help="stop after this wall-clock time")
    ap.add_argument("--checkpoint-every", type=int, default=250_000, help="timesteps (total across envs)")
    ap.add_argument("--dummy", action="store_true", help="DummyVecEnv instead of SubprocVecEnv")
    ap.add_argument("--profile", default="nominal", help="astronaut profile (phase4/astronaut.py PRESETS)")
    ap.add_argument("--visibility", action="store_true", help="mask patch cells not in the walker's line of sight as unknown")
    ap.add_argument("--forbid-shadow", action="store_true", help="entering a shadowed cell ends the episode as unsafe")
    ap.add_argument("--no-forbid-night", action="store_true", help="allow walking after sunset (default: unsafe)")
    ap.add_argument("--temp-range", type=float, nargs=2, default=None, metavar=("TMIN_K", "TMAX_K"),
                    help="modelled ground-temperature limits in K (SIMULATED suit range); off by default")
    ap.add_argument("--sep-stop", action="store_true", help="train only on sols without a DONKI SEP/CME-for-Mars notice")
    ap.add_argument("--dyn-step-h", type=float, default=0.5, help="LMST hours between refreshes of the dynamic layers")
    ap.add_argument("--dose-model", default="astronaut", choices=["astronaut", "world"])
    ap.add_argument("--coarse", action="store_true", help="add the 243 m coarse map view to the observation")
    ap.add_argument("--trail", action="store_true", help="add the walk's visit counts (memory) to the observation")
    ap.add_argument("--maskable", action="store_true",
                    help="sb3-contrib MaskablePPO with env.action_masks(): blocked moves are never sampled (Huang & Ontanon 2020)")
    ap.add_argument("--init-from", default=None,
                    help="MaskablePPO/PPO zip whose policy weights (actor, critic, features) start this run, e.g. the behaviour-cloned "
                         "models/bc_v3_final.zip (phase4/bc_dagger.py); a fresh optimiser and rollout buffer are used")
    ap.add_argument("--gpu-lock", default=None, metavar="NAME",
                    help="hold tools/gpu_lock.py's GPU lock for the whole run and pause while the GPU is above 85 C")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"],
                    help="auto = NVIDIA CUDA if present, else CPU (Apple 'mps' must be asked for explicitly)")
    a = ap.parse_args()
    import contextlib
    if a.gpu_lock:
        from tools.gpu_lock import gpu_lock
        cm = gpu_lock(a.gpu_lock, poll_s=2)      # short poll: other jobs release and re-take the lock between chunks
    else:
        cm = contextlib.nullcontext()
    with cm:
        _run(a)


def _run(a):
    env_kw = dict(profile=a.profile, visibility=a.visibility, forbid_shadow=a.forbid_shadow, forbid_night=not a.no_forbid_night,
                  temp_range_K=a.temp_range, sep_stop=a.sep_stop, dyn_step_h=a.dyn_step_h, dose_model=a.dose_model,
                  coarse=a.coarse, trail=a.trail)

    dev = pick_device(a.device)
    print("device:", dev, torch.cuda.get_device_name(0) if dev == "cuda" else "", "torch", torch.__version__, flush=True)
    name = a.name or time.strftime("ppo_%Y%m%d_%H%M%S")
    mdir, rdir = os.path.join(ROOT, "models"), os.path.join(ROOT, "runs")
    os.makedirs(mdir, exist_ok=True); os.makedirs(rdir, exist_ok=True)

    if a.start_level is None:
        a.start_level = 0
        if a.resume:
            base = os.path.splitext(a.resume)[0]
            for cand in (base + ".json", base.rsplit("_", 2)[0] + "_state.json" if base.endswith("_steps") else None):
                if cand and os.path.exists(cand):
                    a.start_level = int(json.load(open(cand)).get("final_level", 0))
                    print(f"[resume] curriculum level {a.start_level} from {cand}", flush=True)
                    break
            else:
                print("[resume] no metadata next to the model: starting at level 0 (pass --start-level)", flush=True)
    meta = dict(name=name, algo="MaskablePPO" if a.maskable else "PPO", levels=LEVELS, env=env_kw, mask_invalid=a.mask_invalid, science_bonus=a.science_bonus,
                seed=a.seed, n_envs=a.n_envs, resumed_from=a.resume, start_level=a.start_level,
                hyper=dict(lr=a.lr, n_steps=a.n_steps, batch_size=a.batch_size, n_epochs=4, gamma=0.995, gae_lambda=0.95,
                           ent_coef=0.01, clip_range=0.2, advance_success=a.advance_success))
    fns = [make_env(i, a.start_level, a.seed, a.mask_invalid, a.science_bonus, **env_kw) for i in range(a.n_envs)]
    venv = DummyVecEnv(fns) if a.dummy else SubprocVecEnv(fns)
    if a.maskable:
        from sb3_contrib import MaskablePPO as Algo
    else:
        Algo = PPO
    if a.resume:
        model = Algo.load(a.resume, env=venv, device=dev, tensorboard_log=rdir)
    else:
        model = Algo("MultiInputPolicy", venv, device=dev, learning_rate=a.lr, n_steps=a.n_steps,
                    batch_size=a.batch_size, n_epochs=4, gamma=0.995, gae_lambda=0.95, ent_coef=0.01,
                    clip_range=0.2, seed=a.seed, verbose=1, tensorboard_log=rdir,
                    policy_kwargs=dict(features_extractor_class=PatchExtractor,
                                       net_arch=dict(pi=[256, 256], vf=[256, 256])))
    if a.init_from:
        src = Algo.load(a.init_from, device=dev)
        model.policy.load_state_dict(src.policy.state_dict())
        print(f"[init] policy weights loaded from {a.init_from}", flush=True)
        meta["init_from"] = a.init_from
        del src
    print("policy device:", model.device, flush=True)
    meta["device"] = str(model.device)
    cur = CurriculumCallback(a.advance_success, max_minutes=a.max_minutes, state_path=os.path.join(mdir, f"{name}_state.json"),
                             meta=meta, state_every=a.checkpoint_every)
    ckpt = CheckpointCallback(max(a.checkpoint_every // a.n_envs, 1), mdir, name_prefix=name)
    t0 = time.time()
    steps0 = int(model.num_timesteps)                        # > 0 when resuming
    status = "completed"

    def _term(signum, frame):                                # `kill <pid>` saves like Ctrl-C does
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _term)
    try:
        model.learn(a.timesteps, callback=[cur, ckpt] + ([CoolCallback()] if a.gpu_lock else []), tb_log_name=name, reset_num_timesteps=not a.resume)
    except KeyboardInterrupt:
        status = "interrupted"
        print("[train] interrupted: saving the current model", flush=True)
    except Exception:
        status = "crashed"
        raise
    finally:                                                 # always leave a usable model + metadata behind
        wall = time.time() - t0
        steps = int(model.num_timesteps)
        out = os.path.join(mdir, f"{name}_final.zip")
        model.save(out)
        info = dict(meta, model=out, status=status, steps=steps, wall_s=wall, final_level=cur.level, level_log=cur.level_log,
                    success_100=float(np.mean(cur.hist)) if cur.hist else None, steps_this_run=steps - steps0, steps_per_s=(steps - steps0) / max(wall, 1e-9))
        json.dump(info, open(os.path.join(mdir, f"{name}_final.json"), "w"), indent=1)
        cur.write_state()
        if not a.no_latest:
            model.save(os.path.join(mdir, "ppo_marswalk_latest.zip"))
            json.dump(info, open(os.path.join(mdir, "ppo_marswalk_latest.json"), "w"), indent=1)
        print(f"[{status}] saved {out}; {steps} steps in {wall:.0f} s ({(steps - steps0) / max(wall, 1e-9):.0f} steps/s this run); "
              f"final level {cur.level}", flush=True)
        venv.close()


if __name__ == "__main__":
    main()
