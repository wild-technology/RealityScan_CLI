"""Explicit, resumable per-directory installation. No RS execution or admin work.

Default action is plan (no writes/network). Install downloads only locked hashes,
then runs pip offline inside a new owned venv. See docs/INSTALLATION.md.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from modules.deployment_preflight import inspect_python, load_lock, LOCK_PATH


class BootstrapError(RuntimeError):
    """Actionable failure; no fallback to unpinned/global installation."""


class OwnershipUnconfirmed(BootstrapError):
    """A child might exist without a returned handle; never retry in place."""


def _atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def installation_lock(path):
    """OS-held lock: crash releases ownership; anchor is never unlinked."""
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BootstrapError("Another installer owns this destination; wait for it to finish.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _fingerprint(lock):
    # Ignore audit timestamp so a metadata refresh of identical inputs can resume.
    return hashlib.sha256(json.dumps({"target": lock["target"], "packages": lock["packages"]},
                                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _destination(value, *, require_parent=True):
    path = Path(value)
    if not path.is_absolute():
        raise BootstrapError("Choose an absolute installation destination.")
    path = path.resolve()
    # A selected child directory is fine; a Python installation or its ancestor
    # can never be adopted as an environment owned by this bootstrap.
    if (any(Path(p).resolve().is_relative_to(path) or path.is_relative_to(Path(p).resolve())
            for p in (sys.prefix, sys.base_prefix)) or ROOT.is_relative_to(path)):
        raise BootstrapError("Destination cannot contain the source checkout or global Python.")
    if require_parent and not path.parent.is_dir():
        raise BootstrapError(f"Create/select the parent directory first: {path.parent}. No directories were created.")
    if path.exists() and not path.is_dir():
        raise BootstrapError("Destination is not a directory.")
    return path


def _refuse_redirects(directory):
    # Never resume through a substituted symlink/junction into another tree.
    # No recursive removal is used anywhere in this installer.
    for current, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            path = Path(current) / name
            if path.is_symlink() or path.is_junction():
                raise BootstrapError(f"Refusing redirected install path: {path}")


def _identity(destination, lock):
    return {"schema": 1, "product": "ROVScan", "destination": str(destination),
            "source": str(ROOT), "lock_sha256": _fingerprint(lock),
            "base_python": str(Path(sys._base_executable).resolve())}


def _check_owner(destination, identity):
    owner = destination / "owner.json"
    if owner.exists():
        if json.loads(owner.read_text(encoding="utf-8")) != identity:
            raise BootstrapError("Destination belongs to another source/lock/interpreter. Choose a new empty directory.")
    elif destination.exists() and any(destination.iterdir()):
        raise BootstrapError("Refusing to adopt a nonempty, unowned destination. Choose an empty directory.")


def plan(destination, *, offline=False, wheelhouse=None):
    """Read-only plan; reports platform and artifact bytes, never installs."""
    lock = load_lock()
    directory = _destination(destination, require_parent=False)
    _check_owner(directory, _identity(directory, lock))
    python_report = inspect_python(require_isolation=False)
    return {"action": "install", "destination": str(directory), "python": python_report,
            "ready_to_install": python_report["ready"] and directory.parent.is_dir(),
            "required_actions": [] if directory.parent.is_dir() else [{
                "id": "create_install_parent", "path": str(directory.parent),
                "label": "Create this selected parent directory, or choose another existing parent.",
                "requires_explicit_action": True}],
            "offline": offline, "wheelhouse": str(wheelhouse) if wheelhouse else None,
            "packages": len(lock["packages"]), "artifact_bytes": sum(p["artifact"]["size"] for p in lock["packages"]),
            "lock_sha256": _fingerprint(lock), "changes_global_python": False,
            "changes_path": False, "changes_associations": False,
            "requires_explicit_action": True}


def _valid_artifact(path, artifact):
    try:
        if path.stat().st_size != artifact["size"]:
            return False
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == artifact["sha256"]
    except OSError:
        return False


def _obtain_artifact(package, destination, *, offline, wheelhouse):
    artifact = package["artifact"]
    target = destination / artifact["filename"]
    if _valid_artifact(target, artifact):
        return target
    local = Path(wheelhouse) / artifact["filename"] if wheelhouse else None
    if local and not _valid_artifact(local, artifact):
        if offline:
            raise BootstrapError(f"Offline bundle missing/corrupt: {artifact['filename']}; supply the exact locked artifact.")
        local = None
    if offline and local is None:
        raise BootstrapError(f"Offline artifact unavailable: {artifact['filename']}; supply --wheelhouse or fetch on a connected machine.")
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".part")
    try:
        source = local.open("rb") if local else urllib.request.urlopen(artifact["url"], timeout=30)
        with source, temporary.open("xb") as stream:
            size = 0
            digest = hashlib.sha256()
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > artifact["size"]:
                    raise BootstrapError(f"Artifact exceeds locked size: {artifact['filename']}")
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if size != artifact["size"] or digest.hexdigest() != artifact["sha256"]:
            raise BootstrapError(f"Artifact hash/size mismatch: {artifact['filename']}; no package installed.")
        os.replace(temporary, target)
        return target
    except OSError as exc:
        raise BootstrapError(f"Could not obtain {artifact['filename']}: {exc}. Retry this destination; verified artifacts are retained.") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _run(argv, *, env, log):
    """Argument vector only. Ctrl-C waits for the installer child to exit safely."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with log.open("ab") as output:
        try:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                     env=env, cwd=ROOT, creationflags=flags)
        except BaseException as exc:
            raise OwnershipUnconfirmed("Installer launch outcome unconfirmed; do not retry in this directory. Select a new empty destination.") from exc
        interrupted = False
        while True:
            try:
                code = child.wait()
                break
            except KeyboardInterrupt:
                interrupted = True
        if interrupted:
            raise BootstrapError("Interrupted; installer child has now exited. Retry to reconcile this environment.")
        if code:
            raise BootstrapError(f"Installer/check failed with exit {code}; see {log}. Retry unfinished install, or choose a new directory for repair.")


def _environment():
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PIP_", "PYTHON"))}
    # Disables user/global pip configuration; all pip work below is offline.
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def _verify(python, destination, *, log):
    _run([str(python), "-I", "-B", "-m", "pip", "check"], env=_environment(), log=log)
    _run([str(python), "-I", "-B", str(ROOT / "modules/deployment_preflight.py"),
          "--dependencies-only", "--include-tools"], env=_environment(), log=log)
    # The preflight verifies sys.prefix != base_prefix; this additionally binds
    # the executed interpreter to this destination (not an inherited command).
    if not python.resolve().is_relative_to(destination):
        raise BootstrapError("Environment interpreter escapes its owned destination.")


def install(destination, *, offline=False, wheelhouse=None, fetch_only=False):
    lock = load_lock()
    directory = _destination(destination)
    python_report = inspect_python(require_isolation=False)
    if not python_report["ready"]:
        raise BootstrapError(" ".join(python_report["diagnostics"]))
    identity = _identity(directory, lock)
    _check_owner(directory, identity)
    _refuse_redirects(directory)
    directory.mkdir(exist_ok=True)
    with installation_lock(directory / "install.lock"):
        _refuse_redirects(directory)
        owner = directory / "owner.json"
        if owner.exists():
            _check_owner(directory, identity)
        else:
            # Only our lock anchor may have appeared since the read-only check.
            if any(p.name != "install.lock" for p in directory.iterdir()):
                raise BootstrapError("Destination changed before ownership acquisition.")
            _atomic_json(owner, identity)
        environment = directory / "env"
        python = environment / "Scripts/python.exe"
        state = directory / "state.json"
        log = directory / ("install-" + uuid.uuid4().hex + ".log")
        ready = directory / "ready.json"
        if ready.exists():
            if json.loads(ready.read_text(encoding="utf-8")) != identity:
                raise BootstrapError("Ready marker does not match source/lock/interpreter.")
            _verify(python, directory, log=log)
            return {"status": "ready", "destination": str(directory), "modified_environment": False}
        if state.exists() and json.loads(state.read_text(encoding="utf-8")).get("phase") in {
                "venv", "tools", "wheels", "source", "verifying", "ownership_unconfirmed"}:
            raise BootstrapError("Previous installer child ownership is unconfirmed after an abrupt stop. "
                                 "Do not reuse this environment; choose a new empty destination.")
        try:
            artifacts = directory / "artifacts"
            artifacts.mkdir(exist_ok=True)
            _atomic_json(state, {"phase": "artifacts", "ready": False})
            for package in lock["packages"]:
                _obtain_artifact(package, artifacts, offline=offline, wheelhouse=wheelhouse)
            if fetch_only:
                _atomic_json(state, {"phase": "artifacts_verified", "ready": False})
                return {"status": "artifacts_verified", "wheelhouse": str(artifacts)}
            _atomic_json(state, {"phase": "venv", "ready": False})
            # Re-running venv without clear repairs interrupted creation without
            # ever removing the directory. Ready environments are never changed.
            venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
            for group in ("tools", "wheels", "source"):
                selected = [p for p in lock["packages"] if
                            (p["tool"] if group == "tools" else not p["tool"] and
                             (p["artifact"]["kind"] == "bdist_wheel") == (group == "wheels"))]
                requirements = directory / f"{group}.lock"
                requirements.write_text("\n".join(f"{p['name']}=={p['version']} --hash=sha256:{p['artifact']['sha256']}"
                                                    for p in selected) + "\n", encoding="utf-8")
                _atomic_json(state, {"phase": group, "ready": False})
                argv = [str(python), "-I", "-B", "-m", "pip", "install", "--no-input", "--no-index",
                        "--find-links", str(artifacts), "--no-deps", "--require-hashes", "--no-cache-dir",
                        "--force-reinstall", "--no-build-isolation", "-r", str(requirements)]
                argv.append("--no-binary=filterpy" if group == "source" else "--only-binary=:all:")
                _run(argv, env=_environment(), log=log)
            _atomic_json(state, {"phase": "verifying", "ready": False})
            _verify(python, directory, log=log)
            _atomic_json(ready, identity)
            _atomic_json(state, {"phase": "ready", "ready": True})
            return {"status": "ready", "destination": str(directory), "python": str(python), "log": str(log)}
        except OwnershipUnconfirmed as exc:
            _atomic_json(state, {"phase": "ownership_unconfirmed", "ready": False, "error": str(exc), "log": str(log)})
            raise
        except (Exception, KeyboardInterrupt) as exc:
            _atomic_json(state, {"phase": "interrupted_or_failed", "ready": False, "error": str(exc), "log": str(log)})
            raise


def association_command(python, launcher):
    # Registry commands use ShellExecute placeholder syntax, not cmd escaping.
    # Percent signs in installed code paths could be interpreted as placeholders.
    for path in (python, launcher):
        if not Path(path).is_absolute() or any(c in str(path) for c in ('"', '%', '\n', '\r', '\x00')):
            raise BootstrapError("Association paths must be absolute and contain no quotes, percent signs or newlines.")
    return f'"{python}" -I -B "{launcher}" "%1"'


def associate(destination):
    """Explicit HKCU Open With registration; preserve existing default/UserChoice."""
    directory = _destination(destination)
    identity = _identity(directory, load_lock())
    _check_owner(directory, identity)
    if json.loads((directory / "ready.json").read_text(encoding="utf-8")) != identity:
        raise BootstrapError("A verified managed environment is required for association.")
    python = directory / "env/Scripts/pythonw.exe"
    launcher = ROOT / "packaging/launch.py"
    if not python.is_file() or not launcher.is_file():
        raise BootstrapError("Installed interpreter/launcher is missing.")
    command = association_command(python, launcher)
    import winreg
    # Registration alone never steals an existing .rovscan default application.
    base = r"Software\Classes"
    for key, name, value in ((base + r"\ROVScan.Project", "", "ROVScan project"),
                             (base + r"\ROVScan.Project\shell\open\command", "", command),
                             (base + r"\.rovscan\OpenWithProgids", "ROVScan.Project", "")):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
    return {"status": "registered", "scope": "current_user", "default_changed": False,
            "next": "Use Windows Open with > Choose another app to select ROVScan as the default if desired."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "fetch", "install", "associate"), nargs="?", default="plan")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--wheelhouse")
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            result = plan(args.destination, offline=args.offline, wheelhouse=args.wheelhouse)
        elif args.action == "associate":
            result = associate(args.destination)
        else:
            result = install(args.destination, offline=args.offline, wheelhouse=args.wheelhouse,
                             fetch_only=args.action == "fetch")
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, BootstrapError, KeyboardInterrupt) as exc:
        print(json.dumps({"status": "blocked", "message": str(exc), "automatic_repair": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
