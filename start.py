import signal
import subprocess
import sys
import time

STOPPING = False
child = None

MIN_DELAY = 3
MAX_DELAY = 60
STABLE_SECONDS = 120


def handle_stop(signum, frame):
    global STOPPING, child
    STOPPING = True
    print(f"[watchdog] stop signal: {signum}", flush=True)

    if child is not None and child.poll() is None:
        try:
            child.terminate()
        except Exception as exc:
            print(f"[watchdog] terminate error: {exc!r}", flush=True)


signal.signal(signal.SIGTERM, handle_stop)
signal.signal(signal.SIGINT, handle_stop)

delay = MIN_DELAY

while not STOPPING:
    started = time.monotonic()
    print("[watchdog] starting diagnostic_runner.py", flush=True)

    try:
        child = subprocess.Popen(
            [sys.executable, "-u", "diagnostic_runner.py"],
            stdout=None,
            stderr=None,
        )
        exit_code = child.wait()
    except Exception as exc:
        exit_code = -1
        print(f"[watchdog] failed to launch: {exc!r}", flush=True)

    runtime = time.monotonic() - started

    if STOPPING:
        break

    if runtime >= STABLE_SECONDS:
        delay = MIN_DELAY

    print(
        f"[watchdog] diagnostic_runner.py exited ({exit_code}) after {int(runtime)}s. "
        f"restart in {delay}s",
        flush=True,
    )

    end = time.monotonic() + delay
    while time.monotonic() < end and not STOPPING:
        time.sleep(0.5)

    delay = min(delay * 2, MAX_DELAY)

print("[watchdog] stopped", flush=True)
