"""Managed desktop entry point; uses app.py/controller's existing planner/lane."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))


def main():
    from modules.deployment_preflight import inspect_dependencies
    report = inspect_dependencies()
    if not report["ready"]:
        message = "ROVScan dependency preflight failed. Use packaging/bootstrap.py in a console to inspect/repair.\n" + json.dumps(report, ensure_ascii=True)
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message[:16000], "ROVScan installation", 0x10)
        return 2
    from app import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
