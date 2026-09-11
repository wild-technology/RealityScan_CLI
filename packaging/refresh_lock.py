"""Maintainer-only PyPI metadata audit/lock generator; never installs packages.

Run on the reviewed Windows AMD64 CPython 3.13 reference environment. Requires
the existing packaging library for PEP 440/508 and wheel tag evaluation.
"""
from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import urllib.request

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = {
    "boto3": ["boto3"], "geopandas": ["geopandas"], "inquirer": ["inquirer"],
    "matplotlib": ["matplotlib.figure"], "numpy": ["numpy.linalg"],
    "opencv-python": ["cv2"], "pandas": ["pandas"], "pillow": ["PIL.Image", "PIL._imaging"],
    "pyproj": ["pyproj"], "requests": ["requests"], "scikit-learn": ["sklearn.cluster"],
    "scipy": ["scipy.linalg", "scipy.spatial"], "seaborn": ["seaborn"],
    "shapely": ["shapely.geometry"], "tqdm": ["tqdm"], "utm": ["utm"],
    "rasterio": ["rasterio", "rasterio._base"], "filterpy": ["filterpy.kalman"],
    "pygeomag": ["pygeomag"], "pyogrio": ["pyogrio"],
    "pyside6": ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
                "matplotlib.backends.backend_qtagg"],
}
TOOLS = {"pip": "25.1.1", "setuptools": "70.2.0", "wheel": "0.45.1"}


def direct_pins(path):
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-r "):
            continue
        req = Requirement(line)
        specs = list(req.specifier)
        if len(specs) != 1 or specs[0].operator != "==" or req.marker or req.extras:
            raise ValueError(f"Expected exact direct pin: {line}")
        pins[canonicalize_name(req.name)] = specs[0].version
    return pins


def generate():
    if (sys.version_info[:2] != (3, 13) or sys.platform != "win32"
            or platform.machine().lower() not in {"amd64", "x86_64"}):
        raise RuntimeError("Generate on Windows AMD64 CPython 3.13")
    versions = direct_pins(ROOT / "requirements.txt")
    versions.update(direct_pins(ROOT / "requirements-desktop.txt"))
    direct = set(versions)
    versions.update(TOOLS)
    rank = {tag: i for i, tag in enumerate(sys_tags())}
    packages = {}

    def fetch(item):
        name, version = item
        url = f"https://pypi.org/pypi/{name}/{version}/json"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.load(response)
        requires_python = data["info"].get("requires_python") or ""
        if platform.python_version() not in SpecifierSet(requires_python):
            raise ValueError(f"{name} excludes this Python: {requires_python}")
        wheels = []
        for artifact in data["urls"]:
            if artifact.get("yanked"):
                continue
            if artifact["filename"].endswith(".whl"):
                matches = set(parse_wheel_filename(artifact["filename"])[3]) & set(rank)
                if matches:
                    wheels.append((min(rank[t] for t in matches), artifact))
        if wheels:
            artifact = min(wheels, key=lambda x: (x[0], x[1]["filename"]))[1]
        elif name == "filterpy" and version == "1.4.5":
            artifact, = [a for a in data["urls"] if a["packagetype"] == "sdist" and not a.get("yanked")]
        else:
            raise ValueError(f"No supported binary wheel: {name}=={version}")
        reqs = []
        # Legacy FilterPy metadata lacks Requires-Dist; tagged setup.py is
        # authoritative (see INSTALLATION.md). No other sdist exception.
        specs = data["info"].get("requires_dist") or (["numpy", "scipy", "matplotlib"] if name == "filterpy" else [])
        for spec in specs:
            req = Requirement(spec)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                if req.extras or req.url:
                    raise ValueError(f"Review extras/URL before locking: {name}: {spec}")
                reqs.append(str(req))
        return name, {"name": name, "version": version, "direct": name in direct,
                      "tool": name in TOOLS, "imports": IMPORTS.get(name, []),
                      "requires": reqs, "requires_python": requires_python, "metadata_url": url,
                      "artifact": {k: artifact[k] for k in ("filename", "url", "size", "upload_time_iso_8601")}
                      | {"sha256": artifact["digests"]["sha256"], "kind": artifact["packagetype"]}}

    while missing := sorted((n, v) for n, v in versions.items() if n not in packages):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for name, package in pool.map(fetch, missing):
                packages[name] = package
        for package in list(packages.values()):
            for spec in package["requires"]:
                req = Requirement(spec)
                name = canonicalize_name(req.name)
                if name not in versions:
                    versions[name] = importlib.metadata.version(name)
                if versions[name] not in req.specifier:
                    raise ValueError(f"Conflict: {package['name']} requires {spec}, pinned {versions[name]}")
    manifest = {"schema": 1, "target": "cp313-win_amd64", "python": "3.13",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "reference_python": platform.python_version(),
                "provenance": "Direct pins reviewed against local environment; transitive pins from local installed metadata, closure and artifact hashes verified against PyPI JSON. No installation performed.",
                "packages": [packages[n] for n in sorted(packages)]}
    directory = Path(__file__).resolve().parent
    (directory / "deployment-lock.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for group in ("tools", "wheels", "source"):
        selected = [p for p in manifest["packages"] if
                    (p["tool"] if group == "tools" else
                     not p["tool"] and (p["artifact"]["kind"] == "bdist_wheel") == (group == "wheels"))]
        lines = ["# Generated by packaging/refresh_lock.py; see deployment-lock.json for provenance."]
        lines += [f"{p['name']}=={p['version']} --hash=sha256:{p['artifact']['sha256']}" for p in selected]
        (directory / f"{group}.lock").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Locked {len(packages)} packages; compatible artifacts and dependency constraints checked.")


if __name__ == "__main__":
    generate()
