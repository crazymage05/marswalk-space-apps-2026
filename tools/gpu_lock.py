"""
One GPU job at a time on machine B (the laptop overheats), with a temperature guard.

    from tools.gpu_lock import gpu_lock, gpu_temp_c, wait_cool
    with gpu_lock("ai4mars-train"):          # blocks until no other job holds the GPU
        ...                                  # call wait_cool() between epochs / chunks

    python tools/gpu_lock.py status          # who holds the lock, GPU temperature

The lock is a file (<repo root>/.gpu_lock) created exclusively; a lock whose owner process is gone is
taken over. wait_cool() sleeps while the GPU is above MAX_C and resumes below RESUME_C.
"""
import contextlib, json, os, subprocess, sys, time

LOCK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".gpu_lock")
MAX_C, RESUME_C = 85, 75


def gpu_temp_c():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().split(",")
        return int(out[0]), int(out[1])
    except Exception:
        return None, None


def _alive(pid):
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
            return str(pid) in out
        os.kill(pid, 0); return True
    except Exception:
        return False


def holder():
    try:
        return json.load(open(LOCK))
    except Exception:
        return None


@contextlib.contextmanager
def gpu_lock(name, poll_s=30):
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"name": name, "pid": os.getpid(), "since": time.strftime("%Y-%m-%d %H:%M:%S")}).encode()); os.close(fd)
            break
        except FileExistsError:
            h = holder()
            if h and not _alive(h.get("pid", -1)):
                os.remove(LOCK); continue                      # stale lock: owner died
            print(f"[gpu_lock] {name} waiting for {h}", flush=True); time.sleep(poll_s)
    try:
        yield
    finally:
        try:
            if (holder() or {}).get("pid") == os.getpid(): os.remove(LOCK)
        except FileNotFoundError:
            pass


def wait_cool(max_c=MAX_C, resume_c=RESUME_C, poll_s=20):
    t, _ = gpu_temp_c()
    if t is None or t < max_c: return t
    print(f"[gpu_lock] GPU {t} C >= {max_c} C, pausing until {resume_c} C", flush=True)
    while True:
        time.sleep(poll_s); t, _ = gpu_temp_c()
        if t is None or t <= resume_c: return t


if __name__ == "__main__":
    if sys.argv[1:] == ["status"]:
        print("holder:", holder(), "| GPU temp C, util %:", gpu_temp_c())
