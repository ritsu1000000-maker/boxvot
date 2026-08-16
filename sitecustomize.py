import os
import sys
from pathlib import Path

# Render側のStart Commandが古い `python main.py` のままでも、
# 最新ランナーへ自動転送します。
# Pythonは起動時にsitecustomizeを自動importするため、main.py本体が
# bot.run()を始める前にdiagnostic_runner.pyへ切り替えられます。
try:
    script_name = Path(sys.argv[0]).name.lower() if sys.argv else ""
    disabled = os.getenv("BOXVOT_DISABLE_BOOTSTRAP", "0") == "1"

    if script_name == "main.py" and not disabled:
        target = Path(__file__).resolve().with_name("diagnostic_runner.py")
        if target.exists():
            print(
                "[bootstrap] Render started main.py; forwarding to diagnostic_runner.py",
                flush=True,
            )
            os.execv(
                sys.executable,
                [sys.executable, "-u", str(target)],
            )
        else:
            print(
                f"[bootstrap] diagnostic_runner.py not found: {target}",
                flush=True,
            )
except Exception as exc:
    # sitecustomize自体の問題でPython全体を起動不能にしない。
    print(f"[bootstrap] failed: {exc!r}", flush=True)
