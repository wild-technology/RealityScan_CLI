"""CLI project opening through the real loader, without Qt or processing."""
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

import app
from modules.project_workspace import ProjectDocument


@pytest.fixture
def entrypoint(monkeypatch):
    state = SimpleNamespace(windows=[], errors=[], scheduled=[], events=[], controllers=[])

    class Application:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            pass

        def setApplicationName(self, name):
            pass

        def setOrganizationName(self, name):
            pass

        def exec(self):
            state.events.append("event_loop")
            for _, callback in state.scheduled:
                callback()
            return 0

    class MessageBox:
        @staticmethod
        def critical(parent, title, message):
            state.errors.append((title, message))

    class Timer:
        @staticmethod
        def singleShot(delay, callback):
            state.scheduled.append((delay, callback))

    class Controller:
        def __init__(self):
            state.controllers.append(self)

        def __getattr__(self, name):
            pytest.fail(f"Opening a document must not invoke controller.{name}")

    class Window:
        def __init__(self, *, controller, project):
            self.controller, self.project = controller, project
            state.windows.append(self)

        def show(self):
            state.events.append("show")

        def show_setup(self):
            state.events.append("setup")

    modules = {
        "PySide6": {},
        "PySide6.QtWidgets": {"QApplication": Application, "QMessageBox": MessageBox},
        "PySide6.QtCore": {"QTimer": Timer},
        "desktop.main_window": {"MainWindow": Window},
        "modules.project_controller": {"ProjectController": Controller},
    }
    for name, members in modules.items():
        module = ModuleType(name)
        module.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, module)

    def forbidden(*args, **kwargs):
        pytest.fail("Opening a document must not launch processes or write project state")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(ProjectDocument, "save", forbidden)
    monkeypatch.setattr(ProjectDocument, "create_layout", forbidden)
    return state


@pytest.fixture
def project_file(tmp_path):
    # Construct only fixture data; the entrypoint must read it without saving.
    import json

    root = tmp_path / "survey workspace"
    root.mkdir()
    project = ProjectDocument.create("NA999", "H9999", root)
    path = root / "survey project.rovscan"
    path.write_text(json.dumps(project.to_dict()), encoding="utf-8")
    return path


@pytest.mark.parametrize("relative", [True, False], ids=["relative-with-spaces", "absolute"])
def test_open_project_argument(entrypoint, project_file, monkeypatch, relative):
    monkeypatch.chdir(project_file.parent.parent)
    before = project_file.read_bytes()
    argument = project_file.relative_to(project_file.parent.parent) if relative else project_file

    assert app.main([str(argument)]) == 0

    assert not entrypoint.errors
    assert len(entrypoint.windows) == 1
    assert entrypoint.windows[0].project.path == project_file
    assert entrypoint.windows[0].controller is entrypoint.controllers[0]
    assert project_file.read_bytes() == before


def test_missing_relative_project_reports_error(entrypoint, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert app.main(["missing project.rovscan"]) == 2

    assert len(entrypoint.errors) == 1
    title, message = entrypoint.errors[0]
    assert title == "Cannot open project"
    assert str(tmp_path / "missing project.rovscan") in message
    assert "Absolute native path required" not in message
    assert not entrypoint.windows
    assert not entrypoint.scheduled
    assert not entrypoint.events
    assert not (tmp_path / "missing project.rovscan").exists()


def test_open_only_shows_document_and_schedules_setup(entrypoint, project_file):
    before = project_file.read_bytes()
    entries = set(project_file.parent.rglob("*"))

    assert app.main([str(project_file)]) == 0

    assert len(entrypoint.controllers) == 1
    assert entrypoint.events == ["show", "event_loop", "setup"]
    assert [(delay, callback.__name__) for delay, callback in entrypoint.scheduled] == [(0, "show_setup")]
    assert all(stage["state"] == "pending"
               for stage in entrypoint.windows[0].project.to_dict()["stages"].values())
    assert project_file.read_bytes() == before
    assert set(project_file.parent.rglob("*")) == entries


def test_relative_path_keeps_strict_loader_traversal_guard(entrypoint, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert app.main(["../outside.rovscan"]) == 2

    assert entrypoint.errors[0][0] == "Cannot open project"
    assert "Path aliases and traversal are forbidden" in entrypoint.errors[0][1]
    assert not entrypoint.windows
