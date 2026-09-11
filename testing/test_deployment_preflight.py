"""Pure offline deployment contract tests. Never install or execute RealityScan."""
import copy
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from modules import deployment_preflight as dp
from modules import rs_installation, storage_policy
from modules.realityscan_interface import realityscan_cli as rc

SPEC = importlib.util.spec_from_file_location("rovscan_bootstrap", dp.REPO / "packaging/bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


@pytest.fixture
def lock():
    content = b"fixture-wheel"
    return {"schema": 1, "target": "cp313-win_amd64", "packages": [
        {"name": "demo", "version": "1.0", "tool": False, "imports": ["demo"],
         "artifact": {"filename": "demo-1.0-py3-none-any.whl", "kind": "bdist_wheel",
                      "url": "https://files.pythonhosted.org/packages/demo.whl",
                      "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}}]}


@pytest.fixture
def locked_path(tmp_path, lock):
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


@pytest.mark.parametrize("change", [
    lambda p: p.update(name="../escape"),
    lambda p: p.update(version="1.0;malicious"),
    lambda p: p["artifact"].update(filename="../other.whl"),
    lambda p: p["artifact"].update(filename="pkg&command.whl"),
    lambda p: p["artifact"].update(url="https://files.pythonhosted.org.evil.test/pkg"),
    lambda p: p["artifact"].update(sha256="0"),
    lambda p: p["artifact"].update(size=True),
    lambda p: p["artifact"].update(kind="sdist"),
    lambda p: p.update(imports=["sys;exit()"]),
])
def test_lock_rejects_unsafe_records(lock, locked_path, change):
    change(lock["packages"][0])
    locked_path.write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        dp.load_lock(locked_path)


def test_lock_rejects_duplicate(lock, locked_path):
    lock["packages"].append(copy.deepcopy(lock["packages"][0]))
    locked_path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="duplicate"):
        dp.load_lock(locked_path)


def test_committed_lock_has_exact_transitive_closure_and_reviewable_pip_locks():
    from packaging.requirements import Requirement
    from packaging.tags import sys_tags
    from packaging.utils import parse_wheel_filename, canonicalize_name
    lock = dp.load_lock()
    packages = {p["name"]: p for p in lock["packages"]}
    assert packages["pygeomag"]["version"] == "1.1.0"
    assert "pytest" not in packages
    for package in packages.values():
        for text in package["requires"]:
            req = Requirement(text)
            dependency = packages[canonicalize_name(req.name)]
            assert dependency["version"] in req.specifier
        if package["artifact"]["kind"] == "bdist_wheel" and sys.platform == "win32" and sys.version_info[:2] == (3, 13):
            assert set(parse_wheel_filename(package["artifact"]["filename"])[3]) & set(sys_tags())
        group = "tools" if package["tool"] else "wheels" if package["artifact"]["kind"] == "bdist_wheel" else "source"
        assert f"{package['name']}=={package['version']} --hash=sha256:{package['artifact']['sha256']}" in (dp.REPO / f"packaging/{group}.lock").read_text()


def test_requirements_and_import_inventory_are_covered():
    import ast
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    locked = {p["name"]: p for p in dp.load_lock()["packages"]}
    for name in ("requirements.txt", "requirements-desktop.txt"):
        for line in (dp.REPO / name).read_text().splitlines():
            if not line.strip() or line.startswith(("#", "-r")):
                continue
            req = Requirement(line)
            assert str(req.specifier) == "==" + locked[canonicalize_name(req.name)]["version"]
    covered = {module.split('.')[0] for p in locked.values() for module in p["imports"]}
    local = {p.stem for p in dp.REPO.glob("*.py")} | {p.name for p in dp.REPO.iterdir() if p.is_dir()} | {"processors"}
    missing = set()
    for directory in ("modules", "module_base", "desktop", "integrations/rovdataconcat"):
        for path in (dp.REPO / directory).rglob("*.py"):
            if any(p in {"tests", "testing", "__pycache__"} for p in path.parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                names = [n.name.split('.')[0] for n in node.names] if isinstance(node, ast.Import) else (
                    [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
                missing.update(n for n in names if n not in sys.stdlib_module_names | local | covered)
    assert not missing


@pytest.fixture
def supported_python(monkeypatch):
    monkeypatch.setattr(dp.sys, "platform", "win32")
    monkeypatch.setattr(dp.sys, "getwindowsversion", lambda: SimpleNamespace(build=22631), raising=False)
    monkeypatch.setattr(dp.sys, "version_info", (3, 13, 5))
    monkeypatch.setattr(dp.platform, "python_implementation", lambda: "CPython")
    monkeypatch.setattr(dp.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(dp.struct, "calcsize", lambda _: 8)
    monkeypatch.setattr(dp.sysconfig, "get_config_var", lambda _: 0)
    monkeypatch.setattr(dp.sys, "prefix", "managed-prefix")
    monkeypatch.setattr(dp.sys, "base_prefix", "base-prefix")


def test_python_supported(supported_python):
    assert dp.inspect_python()["ready"]


@pytest.mark.parametrize("defect", ["version", "bits", "arm", "free_threaded", "windows10", "global", "implementation"])
def test_python_fails_closed(supported_python, monkeypatch, defect):
    if defect == "version":
        monkeypatch.setattr(dp.sys, "version_info", (3, 14, 0))
    elif defect == "bits":
        monkeypatch.setattr(dp.struct, "calcsize", lambda _: 4)
    elif defect == "arm":
        monkeypatch.setattr(dp.platform, "machine", lambda: "ARM64")
    elif defect == "free_threaded":
        monkeypatch.setattr(dp.sysconfig, "get_config_var", lambda _: 1)
    elif defect == "windows10":
        monkeypatch.setattr(dp.sys, "getwindowsversion", lambda: SimpleNamespace(build=19045))
    elif defect == "global":
        monkeypatch.setattr(dp.sys, "prefix", "base-prefix")
    else:
        monkeypatch.setattr(dp.platform, "python_implementation", lambda: "PyPy")
    assert not dp.inspect_python()["ready"]


@pytest.mark.parametrize("status", ["missing", "metadata_error", "version_mismatch", "ok", "binary_error", "import_error", "import_timeout"])
def test_dependency_failure_states(locked_path, monkeypatch, status):
    monkeypatch.setattr(dp, "inspect_python", lambda **_: {"ready": True})
    def version(_):
        if status == "missing":
            raise dp.metadata.PackageNotFoundError("demo")
        if status == "metadata_error":
            raise OSError("cannot read metadata")
        return "2.0" if status == "version_mismatch" else "1.0"
    monkeypatch.setattr(dp.metadata, "version", version)
    monkeypatch.setattr(dp, "_probe_imports", lambda _: {"status": status})
    report = dp.inspect_dependencies(lock_path=locked_path)
    assert report["packages"][0]["status"] == status
    assert report["ready"] == (status == "ok")


def test_import_probe_handles_real_stdlib_without_application():
    assert dp._probe_imports(["json", "ctypes"])["status"] == "ok"
    assert dp._probe_imports(["rovscan_missing_dependency_fixture"])["status"] == "import_error"


@pytest.mark.parametrize("kind", ["crash", "dll", "timeout", "launch_error"])
def test_probe_native_and_process_errors(monkeypatch, kind):
    def run(*args, **kwargs):
        assert args[0][1:3] == ["-I", "-B"]
        assert kwargs["env"]["MPLBACKEND"] == "Agg"
        if kind == "timeout":
            raise subprocess.TimeoutExpired(args[0], 45)
        if kind == "launch_error":
            raise OSError("access denied")
        return SimpleNamespace(returncode=2, stdout='{"status":"binary_error","message":"DLL load failed"}' if kind == "dll" else "", stderr="native error")
    monkeypatch.setattr(dp.subprocess, "run", run)
    assert dp._probe_imports(["numpy"])["status"] == {"crash": "binary_error", "dll": "binary_error", "timeout": "import_timeout", "launch_error": "probe_error"}[kind]


def test_write_probe_is_opt_in_and_cleans_up(tmp_path):
    assert dp._check_directory(tmp_path, probe_writes=False, protected_roots=())["status"] == "unconfirmed"
    assert not list(tmp_path.iterdir())
    assert dp._check_directory(tmp_path, probe_writes=True, protected_roots=())["status"] == "ok"
    assert not list(tmp_path.iterdir())


def test_protected_and_relative_paths_never_probed(tmp_path, monkeypatch):
    monkeypatch.setattr(dp.tempfile, "NamedTemporaryFile", lambda **_: pytest.fail("must not write"))
    assert dp._check_directory(tmp_path, probe_writes=True, protected_roots=[tmp_path])["status"] == "blocked"
    assert dp._check_directory("relative", probe_writes=True, protected_roots=())["status"] == "blocked"
    assert dp._check_directory(tmp_path / "missing", probe_writes=True, protected_roots=())["status"] == "blocked"


def test_project_write_probe_preserves_protected_raw_child(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    image = raw / "source.txt"
    image.write_bytes(b"immutable")
    before = image.stat().st_mtime_ns
    assert dp._check_directory(tmp_path, probe_writes=True, protected_roots=[raw])["status"] == "ok"
    assert image.read_bytes() == b"immutable" and image.stat().st_mtime_ns == before
    assert list(tmp_path.iterdir()) == [raw]
    assert dp._check_directory(raw, probe_writes=True, protected_roots=[raw])["status"] == "blocked"


@pytest.fixture
def machine_ready(monkeypatch):
    monkeypatch.setattr(dp, "inspect_dependencies", lambda **_: {"ready": True})
    monkeypatch.setattr(rs_installation, "inspect_installation", lambda root: {"ready": True, "selected": str(root)})


def test_deployment_composes_existing_apis_and_demands(tmp_path, machine_ready, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    demands = [storage_policy.StorageDemand(tmp_path, 1, "project"), storage_policy.StorageDemand(cache, 2, "cache")]
    calls = []
    monkeypatch.setattr(storage_policy, "assess_storage", lambda d, **kw: calls.append((d, kw)) or {"can_start": True})
    report = dp.inspect_deployment(install_dir="selected", project_root=tmp_path, cache_root=cache, demands=demands, probe_writes=True)
    assert report["ready"] and report["installation"]["selected"] == "selected"
    assert calls == [(demands, {"reserve_gib": 50.0})]


def test_unknown_growth_and_writes_do_not_become_ready(tmp_path, machine_ready):
    report = dp.inspect_deployment(install_dir="selected", project_root=tmp_path, cache_root=tmp_path)
    assert report["machine_ready"] and not report["ready"]
    assert not report["storage"]["can_start"]
    assert report["directories"]["project"]["status"] == "unconfirmed"
    with pytest.raises(dp.DeploymentBlocked) as error:
        dp.require_deployment(install_dir="selected")
    assert error.value.report["repair_choices"]


def test_xml_failure_blocks_machine_ready(machine_ready, monkeypatch):
    monkeypatch.setattr(rs_installation, "inspect_installation", lambda _: {"ready": False, "diagnostics": ["changed XML contract"]})
    assert not dp.inspect_deployment(install_dir="selected")["machine_ready"]


def test_demands_cannot_account_for_other_output(tmp_path, machine_ready, monkeypatch):
    monkeypatch.setattr(storage_policy, "assess_storage", lambda *a, **kw: pytest.fail("wrong paths must block"))
    demands = [storage_policy.StorageDemand(tmp_path / "other", 0, "project"), storage_policy.StorageDemand(tmp_path, 0, "cache")]
    assert not dp.inspect_deployment(install_dir="selected", project_root=tmp_path, cache_root=tmp_path, demands=demands)["storage"]["can_start"]


def test_low_space_and_unknown_volume_remain_blocked(tmp_path, machine_ready, monkeypatch):
    monkeypatch.setattr(storage_policy, "resolve_volume", lambda _: (_ for _ in ()).throw(ValueError("unknown volume")))
    demands = [storage_policy.StorageDemand(tmp_path, 0, label) for label in ("project", "cache")]
    report = dp.inspect_deployment(install_dir="selected", project_root=tmp_path, cache_root=tmp_path, demands=demands, probe_writes=True)
    assert not report["ready"]


def test_hash_locked_artifact_offline_copy_and_reuse(tmp_path, lock, monkeypatch):
    wheelhouse = tmp_path / "bundle"
    wheelhouse.mkdir()
    output = tmp_path / "owned"
    output.mkdir()
    package = lock["packages"][0]
    (wheelhouse / package["artifact"]["filename"]).write_bytes(b"fixture-wheel")
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("offline means no network"))
    target = bootstrap._obtain_artifact(package, output, offline=True, wheelhouse=wheelhouse)
    assert target.read_bytes() == b"fixture-wheel"
    assert bootstrap._obtain_artifact(package, output, offline=True, wheelhouse=None) == target


def test_corrupt_offline_artifact_never_used(tmp_path, lock):
    p = lock["packages"][0]
    (tmp_path / p["artifact"]["filename"]).write_bytes(b"tampered")
    with pytest.raises(bootstrap.BootstrapError, match="missing/corrupt"):
        bootstrap._obtain_artifact(p, tmp_path, offline=True, wheelhouse=tmp_path)


@pytest.mark.parametrize("data", [b"short", b"fixture-wheal", b"oversized artifact payload"])
def test_network_artifact_failures_leave_no_completed_artifact(tmp_path, lock, monkeypatch, data):
    import io
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(data))
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap._obtain_artifact(lock["packages"][0], tmp_path, offline=False, wheelhouse=None)
    assert not list(tmp_path.iterdir())


def test_network_failure_preserves_prior_artifacts(tmp_path, lock, monkeypatch):
    keep = tmp_path / "verified-other.whl"
    keep.write_bytes(b"keep")
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(bootstrap.BootstrapError, match="Retry"):
        bootstrap._obtain_artifact(lock["packages"][0], tmp_path, offline=False, wheelhouse=None)
    assert keep.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [keep]


def test_installer_lock_exclusion_and_release(tmp_path):
    path = tmp_path / "installer.lock"
    with bootstrap.installation_lock(path):
        with pytest.raises(bootstrap.BootstrapError, match="Another installer"):
            with bootstrap.installation_lock(path):
                pytest.fail("lock not exclusive")
    with bootstrap.installation_lock(path):
        assert path.exists()
    assert path.exists()


def test_plan_no_writes_and_unowned_destination_refusal(tmp_path, lock, monkeypatch):
    monkeypatch.setattr(bootstrap, "load_lock", lambda: lock)
    target = tmp_path / "fresh"
    report = bootstrap.plan(target)
    assert not target.exists() and not report["changes_associations"]
    target.mkdir()
    (target / "user-file").write_text("preserve")
    with pytest.raises(bootstrap.BootstrapError, match="unowned"):
        bootstrap.plan(target)
    assert (target / "user-file").read_text() == "preserve"


def test_bootstrap_refuses_global_python_location():
    with pytest.raises(bootstrap.BootstrapError, match="global Python"):
        bootstrap._destination(Path(sys.base_prefix) / "inside-global")


def test_plan_missing_parent_is_concrete_read_only_action(tmp_path, lock, monkeypatch):
    monkeypatch.setattr(bootstrap, "load_lock", lambda: lock)
    target = tmp_path / "missing-parent" / "installation"
    result = bootstrap.plan(target)
    assert not result["ready_to_install"]
    assert result["required_actions"][0]["path"] == str(target.parent)
    assert not target.parent.exists()
    with pytest.raises(bootstrap.BootstrapError, match="missing-parent"):
        bootstrap.install(target)


@pytest.fixture
def fake_install(tmp_path, lock, monkeypatch):
    monkeypatch.setattr(bootstrap, "load_lock", lambda: lock)
    monkeypatch.setattr(bootstrap, "inspect_python", lambda **_: {"ready": True})
    monkeypatch.setattr(bootstrap, "_obtain_artifact", lambda *a, **kw: None)
    monkeypatch.setattr(bootstrap.venv, "EnvBuilder", lambda **kw: SimpleNamespace(create=lambda p: p.mkdir(exist_ok=True)))
    calls = []
    monkeypatch.setattr(bootstrap, "_run", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(bootstrap, "_verify", lambda *a, **kw: calls.append(["verify"]))
    return tmp_path / "selected & safe", calls


def test_explicit_install_uses_only_venv_offline_hashes_and_no_shell(fake_install):
    target, calls = fake_install
    assert bootstrap.install(target)["status"] == "ready"
    commands = [c for c in calls if "install" in c]
    assert len(commands) == 3
    for argv in commands:
        assert argv[0] == str(target / "env/Scripts/python.exe")
        assert "--no-index" in argv and "--require-hashes" in argv and "--no-deps" in argv
        assert "--no-build-isolation" in argv and "--no-cache-dir" in argv
    assert json.loads((target / "state.json").read_text())["ready"]
    assert calls[-1] == ["verify"]


def test_interrupted_install_resumes_but_ready_environment_not_mutated(fake_install, monkeypatch):
    target, calls = fake_install
    monkeypatch.setattr(bootstrap, "_run", lambda *a, **kw: (_ for _ in ()).throw(bootstrap.BootstrapError("network/child failure")))
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.install(target)
    assert not (target / "ready.json").exists()
    assert json.loads((target / "state.json").read_text())["phase"] == "interrupted_or_failed"
    monkeypatch.setattr(bootstrap, "_run", lambda argv, **kw: calls.append(argv))
    bootstrap.install(target)
    calls.clear()
    assert bootstrap.install(target)["modified_environment"] is False
    assert calls == [["verify"]]


def test_wrong_lock_cannot_resume(fake_install, lock):
    target, _ = fake_install
    bootstrap.install(target)
    lock["packages"][0]["version"] = "2.0"
    with pytest.raises(bootstrap.BootstrapError, match="another"):
        bootstrap.install(target)


def test_abrupt_parent_death_never_reuses_possible_live_installer(fake_install):
    target, calls = fake_install
    bootstrap.install(target, fetch_only=True)
    bootstrap._atomic_json(target / "state.json", {"phase": "wheels", "ready": False})
    with pytest.raises(bootstrap.BootstrapError, match="ownership is unconfirmed"):
        bootstrap.install(target)
    assert not calls


def test_interrupted_popen_marks_ownership_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap.subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(bootstrap.OwnershipUnconfirmed):
        bootstrap._run(["fixture"], env={}, log=tmp_path / "install.log")


def test_rs_candidates_have_no_unsupported_legacy_fallback():
    assert rc.EXECUTABLE_CANDIDATES
    assert all("2.2" in value for value in rc.EXECUTABLE_CANDIDATES)


def test_ctrl_c_keeps_waiting_for_installer_child(tmp_path, monkeypatch):
    waits = iter([KeyboardInterrupt(), 0])
    def wait():
        result = next(waits)
        if isinstance(result, BaseException):
            raise result
        return result
    def popen(argv, **kw):
        assert isinstance(argv, list) and "shell" not in kw
        return SimpleNamespace(wait=wait)
    monkeypatch.setattr(bootstrap.subprocess, "Popen", popen)
    with pytest.raises(bootstrap.BootstrapError, match="child has now exited"):
        bootstrap._run([sys.executable, "path & data"], env={}, log=tmp_path / "install.log")
    with pytest.raises(StopIteration):
        next(waits)


def test_inherited_pip_settings_cannot_redirect_install(monkeypatch):
    monkeypatch.setenv("PIP_TARGET", "outside")
    monkeypatch.setenv("PIP_INDEX_URL", "https://untrusted.test")
    monkeypatch.setenv("PYTHONPATH", "outside")
    env = bootstrap._environment()
    assert "PIP_TARGET" not in env and "PIP_INDEX_URL" not in env and "PYTHONPATH" not in env
    assert env["PIP_CONFIG_FILE"] == bootstrap.os.devnull


def test_association_command_quotes_spaces_and_metacharacters(tmp_path):
    python, launcher = tmp_path / "space & amp/pythonw.exe", tmp_path / "app directory/launch.py"
    assert bootstrap.association_command(python, launcher) == f'"{python}" -I -B "{launcher}" "%1"'


@pytest.mark.parametrize("suffix", ["bad%1.py", 'bad".py', "bad\n.py"])
def test_association_rejects_shell_placeholder_paths(tmp_path, suffix):
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.association_command(tmp_path / "pythonw.exe", tmp_path / suffix)


def test_opt_in_association_preserves_default_and_uses_hkcu(fake_install, monkeypatch):
    target, _ = fake_install
    bootstrap.install(target)
    python = target / "env/Scripts/pythonw.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fixture")
    writes = []
    class Key:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def __exit__(self, *a): pass
    registry = SimpleNamespace(HKEY_CURRENT_USER="HKCU", REG_SZ=1,
        CreateKey=lambda hive, path: Key((hive, path)),
        SetValueEx=lambda handle, name, _, kind, value: writes.append((handle.path, name, kind, value)))
    monkeypatch.setitem(sys.modules, "winreg", registry)
    assert not bootstrap.associate(target)["default_changed"]
    assert all(row[0][0] == "HKCU" for row in writes)
    assert all("UserChoice" not in row[0][1] for row in writes)
    assert all(row[0][1] != r"Software\Classes\.rovscan" for row in writes)


class Settings:
    def __init__(self, executable=None): self.executable = executable
    def get(self, section, key, default=None): return self.executable if key == "executable" else default


def test_rs_explicit_project_selection_wins_and_is_pinned(tmp_path, monkeypatch):
    approved = tmp_path / "approved/RealityScan.exe"
    approved.parent.mkdir()
    approved.write_bytes(b"mock exe")
    monkeypatch.setenv("RS_EXECUTABLE", str(approved))
    calls = []
    monkeypatch.setattr(rs_installation, "validate_installation", lambda root: calls.append(root) or {
        "valid": True, "executable": str(Path(root) / "RealityScan.exe"), "diagnostics": []})
    cli = rc.RealityScanCLI(logging.getLogger("deployment-test"), Settings("old-global-2.1.exe"))
    monkeypatch.setenv("RS_EXECUTABLE", "changed-after-construction")
    assert cli.find_executable() == str(approved.resolve())
    assert cli.find_executable() == str(approved.resolve())
    assert calls == [str(approved.parent)]  # cached unchanged identity, no repeated exe hashing
    approved.write_bytes(b"changed executable")
    cli.find_executable()
    assert len(calls) == 2


def test_rs_old_binary_refused_without_fallback(tmp_path, monkeypatch):
    path = tmp_path / "RealityScan.exe"
    path.write_bytes(b"old mock exe")
    monkeypatch.setenv("RS_EXECUTABLE", str(path))
    monkeypatch.setattr(rs_installation, "validate_installation", lambda _: {"valid": False, "diagnostics": ["Only RealityScan 2.2 is supported"]})
    monkeypatch.setattr(rc, "EXECUTABLE_CANDIDATES", ["do-not-fallback"])
    cli = rc.RealityScanCLI(logging.getLogger("deployment-test"), Settings())
    with pytest.raises(FileNotFoundError, match="2.2"):
        cli.find_executable()


def test_rs_no_settings_inheritance_ignores_global(tmp_path, monkeypatch):
    path = tmp_path / "RealityScan.exe"
    path.write_bytes(b"mock")
    monkeypatch.delenv("RS_EXECUTABLE", raising=False)
    monkeypatch.setenv("RS_NO_SETTINGS_INHERITANCE", "1")
    monkeypatch.setattr(rc, "EXECUTABLE_CANDIDATES", [str(path)])
    monkeypatch.setattr(rs_installation, "validate_installation", lambda root: {"valid": True, "executable": str(path), "diagnostics": []})
    cli = rc.RealityScanCLI(logging.getLogger("deployment-test"), Settings("invalid-global"))
    assert cli.find_executable() == str(path)
    assert all("2.1" not in p and "2.0" not in p for p in rc.EXECUTABLE_CANDIDATES)


@pytest.mark.parametrize("value", ["", "relative/RealityScan.exe", "another.exe", "missing/RealityScan.exe"])
def test_rs_invalid_override_is_not_discovery_permission(monkeypatch, value):
    monkeypatch.setenv("RS_EXECUTABLE", value)
    cli = rc.RealityScanCLI(logging.getLogger("deployment-test"), Settings())
    with pytest.raises(FileNotFoundError):
        cli.find_executable()
