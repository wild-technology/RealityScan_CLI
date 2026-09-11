"""Asynchronous deployment checks; repairs are presented, never auto-executed."""
import math

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)


def _inspect(**kwargs):
    from modules.deployment_preflight import inspect_deployment
    return inspect_deployment(**kwargs)


class _Signals(QObject):
    result = Signal(int, object, str)


class _Check(QRunnable):
    def __init__(self, inspector, kwargs, signals, generation):
        super().__init__()
        self.inspector, self.kwargs, self.signals = inspector, kwargs, signals
        self.generation = generation

    def run(self):
        try:
            self.signals.result.emit(self.generation, self.inspector(**self.kwargs), "")
        except Exception as exc:
            self.signals.result.emit(self.generation, None, str(exc))


class SetupDialog(QDialog):
    """Read-only checks by default; workspace write probes need explicit consent."""
    def __init__(self, *, project=None, install_dir="", cache_root=None, reserve_gib=50,
                 inspector=None, controller=None, can_create_cache=None, parent=None):
        super().__init__(parent)
        self.project = project
        self.inspector = inspector or _inspect
        self.controller = controller
        self.can_create_cache = can_create_cache
        self.cache_root = cache_root
        self.reserve_gib = reserve_gib
        self.report = None
        self.busy = False
        self._generation = 0
        self._signals = _Signals(self)
        self._signals.result.connect(self._result)
        self._cache_signals = _Signals(self)
        self._cache_signals.result.connect(self._cache_result)
        self.setWindowTitle("Installation and workspace readiness")
        self.resize(870, 660)
        layout = QVBoxLayout(self)
        self.summary = QLabel("Check this machine's dependencies, installation and storage. No repair or installation runs automatically.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        form = QFormLayout()
        self.install_dir = QLineEdit(str(install_dir))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.install_dir)
        row.addWidget(browse)
        form.addRow("RealityScan installation", row)
        self.root_label = QLabel(str(project.root) if project else "Select or create a project for storage checks")
        self.root_label.setWordWrap(True)
        form.addRow("Project root", self.root_label)
        self.cache_label = QLabel(str(cache_root) if cache_root else "Not selected")
        self.cache_label.setWordWrap(True)
        form.addRow("Cache", self.cache_label)
        self.reserve_label = QLabel(f"{reserve_gib:g} GiB")
        form.addRow("Reserve", self.reserve_label)
        self.project_growth = QLineEdit()
        self.cache_growth = QLineEdit()
        self.project_growth.setPlaceholderText("Unknown until estimated; do not assume zero")
        self.cache_growth.setPlaceholderText("Unknown until estimated; do not assume zero")
        form.addRow("Additional project growth (GiB)", self.project_growth)
        form.addRow("Additional cache growth (GiB)", self.cache_growth)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.check_button = QPushButton("Check installation / storage")
        self.check_button.clicked.connect(lambda: self.run_check())
        self.probe_button = QPushButton("Probe workspace write access…")
        self.probe_button.setEnabled(project is not None)
        self.probe_button.clicked.connect(self.probe_writes)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.probe_button)
        self.create_cache_button = QPushButton("Create approved cache")
        self.create_cache_button.setToolTip("Create the cache recorded in approved operating settings, then recheck readiness.")
        self.create_cache_button.clicked.connect(self.create_cache)
        buttons.addWidget(self.create_cache_button)
        layout.addLayout(buttons)
        self.checks = QTreeWidget()
        self.checks.setHeaderLabels(["Check", "State", "Details"])
        self.checks.setColumnWidth(0, 230)
        self.checks.setColumnWidth(1, 130)
        layout.addWidget(self.checks, 1)
        layout.addWidget(QLabel("Repair choices / next steps"))
        self.repairs = QPlainTextEdit()
        self.repairs.setReadOnly(True)
        self.repairs.setMaximumHeight(160)
        layout.addWidget(self.repairs)
        for editor in (self.install_dir, self.project_growth, self.cache_growth):
            editor.textChanged.connect(self._changed)
        self.refresh_actions()

    def rebind(self, *, project, install_dir, cache_root, reserve_gib, controller, can_create_cache):
        """Retain the window, discard readiness evidence from its previous context."""
        changed_project = self.project is not project
        self.project, self.controller = project, controller
        self.can_create_cache = can_create_cache
        self.cache_root, self.reserve_gib = cache_root, reserve_gib
        self.install_dir.setText(str(install_dir))
        self.root_label.setText(str(project.root) if project else "Select or create a project for storage checks")
        self.cache_label.setText(str(cache_root) if cache_root else "Not selected")
        self.reserve_label.setText(f"{reserve_gib:g} GiB")
        if changed_project:
            self.project_growth.clear()
            self.cache_growth.clear()
        self._changed()

    def _cache_allowed(self):
        return bool(self.project is not None and not self.busy
                    and callable(getattr(self.controller, "ensure_cache", None))
                    and self.project.settings_approved(["operating"])
                    and not any(stage["state"] == "running" for stage in self.project.to_dict()["stages"].values())
                    and (self.can_create_cache is None or self.can_create_cache()))

    def refresh_actions(self):
        self.create_cache_button.setEnabled(self._cache_allowed())

    def create_cache(self):
        if not self._cache_allowed():
            self.refresh_actions()
            return
        self.report = None
        self.busy = True
        self.check_button.setEnabled(False)
        self.probe_button.setEnabled(False)
        self.refresh_actions()
        self.summary.setText("Creating the approved project cache…")
        QThreadPool.globalInstance().start(_Check(self.controller.ensure_cache,
                                                 {"project": self.project}, self._cache_signals, self._generation))

    def _cache_result(self, generation, path, error):
        if generation != self._generation:
            return
        self.busy = False
        self.check_button.setEnabled(True)
        self.probe_button.setEnabled(self.project is not None)
        self.refresh_actions()
        if error:
            self.summary.setText(f"Cache creation failed: {error}")
            return
        self.cache_root = path
        self.cache_label.setText(str(path))
        self.run_check()  # Read-only; creation does not authorize write probes.

    def _changed(self, *args):
        self._generation += 1
        self.busy = False
        self.report = None
        self.checks.clear()
        self.repairs.clear()
        self.check_button.setEnabled(True)
        self.probe_button.setEnabled(self.project is not None)
        self.refresh_actions()
        self.summary.setText("Selections changed. Run readiness checks again.")

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select installation", self.install_dir.text())
        if path:
            self.install_dir.setText(path)

    def probe_writes(self):
        if self.project is None or self.busy:
            return
        answer = QMessageBox.question(self, "Explicit write-access probe", "Create and remove a temporary probe file "
                                       "inside the selected project/cache locations to verify write access?\n"
                                       "This does not process imagery or change the installation.",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.run_check(probe_writes=True)

    def run_check(self, *, probe_writes=False):
        if self.busy:
            return
        if probe_writes and self.project is None:
            self.summary.setText("A project is required for a workspace write probe.")
            return
        try:
            if self.project and self.cache_root:
                self.project.resolve_path(self.cache_root)
            demands = None
            growth = (self.project_growth.text().strip(), self.cache_growth.text().strip())
            if any(growth):
                if not all(growth) or self.project is None or not self.cache_root:
                    raise ValueError("Both project/cache growth estimates and locations are required.")
                amounts = [float(value) for value in growth]
                if any(not math.isfinite(value) or value < 0 for value in amounts):
                    raise ValueError("Growth estimates must be finite and nonnegative.")
                from modules.storage_policy import StorageDemand
                demands = [StorageDemand(self.project.root, amounts[0], "project"),
                           StorageDemand(self.cache_root, amounts[1], "cache")]
            kwargs = {"install_dir": self.install_dir.text().strip(),
                      "project_root": str(self.project.root) if self.project else None,
                      "cache_root": str(self.cache_root) if self.cache_root else None,
                      "demands": demands, "reserve_gib": self.reserve_gib, "probe_writes": probe_writes,
                      "protected_roots": tuple(self.project.to_dict()["sources"]) if self.project else ()}
            self.report = None
            self.checks.clear()
            self.repairs.clear()
            self.busy = True
            self.check_button.setEnabled(False)
            self.probe_button.setEnabled(False)
            self.refresh_actions()
            self.summary.setText("Checking readiness…")
            QThreadPool.globalInstance().start(_Check(self.inspector, kwargs, self._signals, self._generation))
        except (ValueError, OSError) as exc:
            self.summary.setText(str(exc))

    def _result(self, generation, report, error):
        if generation != self._generation:
            return
        self.busy = False
        self.check_button.setEnabled(True)
        self.probe_button.setEnabled(self.project is not None)
        self.refresh_actions()
        if error:
            self.summary.setText(f"Readiness check failed: {error}")
            return
        self.report = report
        self.summary.setText("Ready according to the completed checks. Execution rechecks readiness before starting."
                             if report.get("ready") is True else "Not ready · resolve the checks below before processing.")
        self.checks.clear()
        for section in ("checks", "dependencies", "installation", "directories", "storage"):
            value = report.get(section)
            if value is None:
                continue
            parent = QTreeWidgetItem([section.title(), "", ""])
            self.checks.addTopLevelItem(parent)
            self._append(parent, value)
            parent.setExpanded(True)
        choices = report.get("repair_choices", [])
        self.repairs.setPlainText("\n\n".join(
            str(choice.get("label") or choice.get("title") or "Repair") + "\n" +
            str(choice.get("description") or choice.get("command") or "Explicit operator action required.")
            if isinstance(choice, dict) else str(choice) for choice in choices))

    def _append(self, parent, value):
        entries = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else [("value", value)]
        for key, entry in entries:
            if isinstance(entry, dict):
                label = str(entry.get("label") or entry.get("name") or entry.get("id") or key)
                state = str(entry.get("status", entry.get("ready", entry.get("ok", ""))))
                details = str(entry.get("detail") or entry.get("message") or "")
                child = QTreeWidgetItem([label, state, details])
                parent.addChild(child)
                other = {k: v for k, v in entry.items() if k not in ("label", "name", "id", "status", "ready", "ok", "detail", "message")}
                if other:
                    self._append(child, other)
            elif isinstance(entry, list):
                child = QTreeWidgetItem([str(key), f"{len(entry)} entries", ""])
                parent.addChild(child)
                self._append(child, entry)
            else:
                parent.addChild(QTreeWidgetItem([str(key), "", str(entry)]))
