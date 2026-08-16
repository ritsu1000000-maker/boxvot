import os
import sys
from pathlib import Path

# RenderのStart Commandが古い `python main.py` のままでも、
# 必ず最新版のdiagnostic_runner.pyを起動します。
if __name__ == "__main__":
    target = Path(__file__).resolve().with_name("diagnostic_runner.py")
    print(
        "[main-bootstrap] forwarding main.py -> diagnostic_runner.py",
        flush=True,
    )
    os.execv(
        sys.executable,
        [sys.executable, "-u", str(target)],
    )
else:
    # runner.pyからimportされた場合は、従来のBot本体をそのまま公開します。
    from core_main import *  # noqa: F401,F403
