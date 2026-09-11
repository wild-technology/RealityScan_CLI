"""Dependency/installation gate usable before importing the desktop or pipeline.

Inspection never installs/repairs software. Import probes run in isolated Python
children (not RealityScan). Only probe_writes=True creates temporary files, in
the explicitly selected existing project/cache directories, removed immediately.
See docs/INSTALLATION.md for the controller contract and readiness scope.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
import sysconfig
import tempfile

REPO = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO / "packaging/deployment-lock.json"


class DeploymentBlocked(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__("Deployment preflight is blocked; inspect report checks and repair_choices.")


def load_lock(path=LOCK_PATH):
    """Read the bundled artifact allowlist; reject malformed/unsafe lock records."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != 1 or value.get("target") != "cp313-win_amd64":
        raise ValueError("Unsupported deployment lock schema/target")
    packages = value.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Deployment lock has no packages")
    seen = set()
    for package in packages:
        if not isinstance(package, dict) or type(package.get("tool")) is not bool:
            raise ValueError("Invalid package record/tool classification")
        name, version = package.get("name", ""), package.get("version", "")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or name in seen:
            raise ValueError("Invalid/duplicate locked package")
        seen.add(name)
        if not re.fullmatch(r"[0-9][a-zA-Z0-9.]*", version):
            raise ValueError(f"Invalid locked version: {name}")
        a = package.get("artifact", {})
        if not isinstance(a, dict):
            raise ValueError(f"Invalid artifact record: {name}")
        filename = a.get("filename", "")
        if not re.fullmatch(r"[a-zA-Z0-9_.+-]+\.(whl|zip)", filename):
            raise ValueError(f"Unsafe artifact filename: {name}")
        if not a.get("url", "").startswith("https://files.pythonhosted.org/packages/"):
            raise ValueError(f"Unapproved artifact host: {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", a.get("sha256", "")):
            raise ValueError(f"Invalid artifact hash: {name}")
        if type(a.get("size")) is not int or a["size"] <= 0:
            raise ValueError(f"Invalid artifact size: {name}")
        if a.get("kind") != "bdist_wheel" and (name, version, a.get("kind")) != ("filterpy", "1.4.5", "sdist"):
            raise ValueError("Only reviewed FilterPy 1.4.5 may build from source")
        if not isinstance(package.get("imports"), list) or any(
                not isinstance(m, str) or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", m)
                for m in package["imports"]):
            raise ValueError(f"Invalid import probe: {name}")
    return value


def inspect_python(*, require_isolation=True):
    build = sys.getwindowsversion().build if sys.platform == "win32" else None
    facts = {"executable": sys.executable, "implementation": platform.python_implementation(),
             "version": platform.python_version(), "bits": struct.calcsize("P") * 8,
             "machine": platform.machine(), "platform": sys.platform, "windows_build": build,
             "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
             "isolated_environment": sys.prefix != sys.base_prefix, "prefix": sys.prefix}
    issues = []
    if facts["implementation"] != "CPython" or sys.version_info[:2] != (3, 13):
        issues.append("Select regular CPython 3.13; this lock does not certify other minor versions.")
    if facts["bits"] != 64 or facts["machine"].lower() not in {"amd64", "x86_64"} or facts["free_threaded"]:
        issues.append("Select AMD64 64-bit CPython with the GIL; ARM64/32-bit/free-threaded builds are unsupported.")
    if sys.platform != "win32" or build < 22000:
        issues.append("Windows 11 or later Windows build >=22000 is required for this deployment target.")
    if require_isolation and not facts["isolated_environment"]:
        issues.append("Launch with the managed virtual environment; do not install into global Python.")
    return {"ready": not issues, "facts": facts, "diagnostics": issues}


_IMPORT_PROBE = r'''
import importlib, json, sys
try:
    for name in json.loads(sys.argv[1]):
        importlib.import_module(name)
    print(json.dumps({"status": "ok"}))
except BaseException as exc:
    message = str(exc)
    binary = isinstance(exc, OSError) or any(t in message.lower() for t in
        ("dll", "binary incompat", "undefined symbol", "multiarray", "dtype size changed"))
    print(json.dumps({"status": "binary_error" if binary else "import_error",
                      "exception": type(exc).__name__, "message": message[:4000]}))
    sys.exit(2)
'''


def _probe_imports(names, *, timeout=45):
    # Separate processes identify the offending package even for a native crash.
    # Temporary matplotlib/cache paths avoid writes to an operator's config.
    with tempfile.TemporaryDirectory(prefix="rovscan-import-") as scratch:
        env = dict(os.environ)
        for key in list(env):
            if key.startswith(("PYTHON", "QT_")) or key in {"MPLBACKEND", "MPLCONFIGDIR"}:
                env.pop(key)
        env.update(MPLBACKEND="Agg", MPLCONFIGDIR=scratch, QT_QPA_PLATFORM="offscreen")
        try:
            result = subprocess.run([sys.executable, "-I", "-B", "-c", _IMPORT_PROBE, json.dumps(names)],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=timeout, env=env, cwd=scratch,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return {"status": "import_timeout", "message": f"Import exceeded {timeout}s; probe child stopped."}
        except OSError as exc:
            return {"status": "probe_error", "message": str(exc)}
        try:
            report = json.loads(result.stdout.splitlines()[-1])
            if report["status"] not in {"ok", "import_error", "binary_error"}:
                raise ValueError("Invalid import status")
            if result.returncode and report["status"] == "ok":
                raise ValueError("Nonzero exit after import")
            return report
        except (ValueError, IndexError, KeyError, TypeError):
            return {"status": "binary_error", "message": "Import child crashed or returned invalid output.",
                    "returncode": result.returncode, "stderr": result.stderr[-4000:]}


def inspect_dependencies(*, require_isolation=True, include_tools=False, lock_path=LOCK_PATH):
    """Exact distribution checks plus isolated smoke imports. JSON-ready, no pip."""
    python = inspect_python(require_isolation=require_isolation)
    try:
        lock = load_lock(lock_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"ready": False, "python": python, "packages": [], "lock_error": str(exc)}

    def inspect(package):
        row = {"name": package["name"], "expected": package["version"], "actual": None}
        try:
            row["actual"] = metadata.version(package["name"])
        except metadata.PackageNotFoundError:
            return row | {"status": "missing", "message": "Distribution metadata is missing."}
        except Exception as exc:
            return row | {"status": "metadata_error", "message": str(exc)}
        if row["actual"] != package["version"]:
            return row | {"status": "version_mismatch", "message": "Version differs from reviewed deployment lock."}
        return row | (_probe_imports(package["imports"]) if package["imports"] else {"status": "ok"})

    selected = [p for p in lock["packages"] if include_tools or not p["tool"]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        packages = list(pool.map(inspect, selected))
    return {"ready": python["ready"] and all(p["status"] == "ok" for p in packages),
            "python": python, "lock_target": lock["target"], "packages": packages}


def _check_directory(path, *, probe_writes, protected_roots):
    try:
        chosen = Path(path)
        if not chosen.is_absolute():
            raise ValueError("Select an absolute directory path.")
        resolved = chosen.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("Select an existing directory (create it explicitly first).")
        for root in protected_roots:
            protected = Path(root)
            if not protected.is_absolute():
                raise ValueError("Protected source paths must be absolute.")
            protected = protected.resolve()
            # The probe is one file directly in resolved, never a recursive
            # write. A project may legitimately contain a protected raw child.
            if resolved.is_relative_to(protected):
                raise ValueError("Selected output overlaps a protected/source directory.")
        if not probe_writes:
            return {"path": str(resolved), "status": "unconfirmed", "message": "Choose Test write access; ACL checks alone cannot establish writability."}
        with tempfile.NamedTemporaryFile(prefix=".rovscan-write-probe-", dir=resolved) as stream:
            stream.write(b"ROVScan write probe\n")
            stream.flush()
            os.fsync(stream.fileno())
        return {"path": str(resolved), "status": "ok"}
    except (OSError, ValueError, TypeError) as exc:
        return {"path": str(path), "status": "blocked", "message": str(exc)}


def inspect_deployment(*, install_dir, project_root=None, cache_root=None, demands=None,
                       reserve_gib=50.0, probe_writes=False, protected_roots=(),
                       require_isolation=True):
    """Compose existing strict RS/XML and volume budget APIs, without a launcher.

    demands is a sequence of storage_policy.StorageDemand with explicit project
    and cache labels/remaining growth. No omitted estimate becomes zero. Source
    and protected paths come from the controller, never directory inference.
    """
    from .rs_installation import inspect_installation
    from .storage_policy import assess_storage

    dependencies = inspect_dependencies(require_isolation=require_isolation)
    try:
        installation = inspect_installation(install_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        installation = {"ready": False, "diagnostics": [str(exc)]}
    directories = {label: _check_directory(path, probe_writes=probe_writes, protected_roots=protected_roots)
                   if path is not None else {"status": "unconfigured", "message": f"Select {label} directory."}
                   for label, path in (("project", project_root), ("cache", cache_root))}
    storage = {"can_start": False, "alerts": [{"level": "block", "message": "Provide project and cache growth estimates; unknown is not zero."}]}
    if demands is not None:
        try:
            demands = list(demands)
            for label, path in (("project", project_root), ("cache", cache_root)):
                matches = [d for d in demands if d.label == label]
                if path is None or len(matches) != 1 or Path(matches[0].path).resolve() != Path(path).resolve():
                    raise ValueError(f"Storage demands must include exactly one {label} matching its selected path.")
            storage = assess_storage(demands, reserve_gib=reserve_gib)
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            storage = {"can_start": False, "alerts": [{"level": "block", "message": str(exc)}]}
    machine_ready = dependencies["ready"] and installation["ready"]
    project_ready = all(d["status"] == "ok" for d in directories.values()) and storage["can_start"]
    choices = []
    if not dependencies["ready"]:
        choices.append({"id": "install_isolated_environment", "label": "Install/resume a managed environment in a selected empty directory", "requires_explicit_action": True})
    if not installation["ready"]:
        choices.extend([{"id": "select_realityscan_22", "label": "Choose installed RealityScan 2.2 directory", "requires_explicit_action": True},
                        {"id": "review_xml_repair", "label": "Review rs_installation repair proposal before applying selected XML changes", "requires_explicit_action": True}])
    if not project_ready:
        choices.append({"id": "review_storage_paths", "label": "Select output/cache paths, enter growth estimates and test write access", "requires_explicit_action": True})
    return {"schema": 1, "ready": machine_ready and project_ready, "machine_ready": machine_ready,
            "project_ready": project_ready, "dependencies": dependencies, "installation": installation,
            "directories": directories, "storage": storage, "repair_choices": choices,
            "checks": {"dependencies": dependencies["ready"], "realityscan_22_xml": installation["ready"],
                       "project_storage": project_ready}}


def require_deployment(**kwargs):
    report = inspect_deployment(**kwargs)
    if not report["ready"]:
        raise DeploymentBlocked(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependencies-only", action="store_true")
    parser.add_argument("--include-tools", action="store_true")
    parser.add_argument("--allow-unmanaged", action="store_true", help="Diagnostic only; does not certify isolation")
    args = parser.parse_args(argv)
    if not args.dependencies_only:
        parser.error("Use --dependencies-only; project/RS inspection is the typed controller API.")
    report = inspect_dependencies(require_isolation=not args.allow_unmanaged, include_tools=args.include_tools)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
