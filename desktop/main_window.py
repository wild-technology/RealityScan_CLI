"""Native project UI; pipeline work is exclusively owned by an injected controller."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QRunnable, QThreadPool, Signal, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QTableView, QTableWidget, QTableWidgetItem,
    QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from modules.project_workspace import ProjectDocument, ProjectError, STAGES, settings_stage
from .controller_api import UnavailableController
from .map_preview import MapPreview
from .settings_panel import SettingsPanel
from .review_widgets import RecordFilter, RecordTableModel
from .quality_review import QualityReview
from .spatial_review import SpatialReview
from .occlusion_review import OcclusionReview
from .theme import ensure_ui_font
from .setup_dialog import SetupDialog


STYLE = """
QWidget { background: #121c2b; color: #e5ecf5; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow, QDialog { background: #121c2b; }
QLabel#title { font-size: 23pt; font-weight: 650; }
QLabel#muted { color: #9cacc2; }
QLabel#warning { color: #f0bf71; }
QFrame#card { background: #1c293b; border: 1px solid #314259; border-radius: 9px; }
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {
  background: #0e1725; border: 1px solid #34445b; border-radius: 5px; padding: 7px;
  selection-background-color: #285d65;
}
QPushButton { background: #283c54; border: 1px solid #425974; border-radius: 5px; padding: 8px 15px; }
QPushButton:hover { background: #36516d; }
QPushButton:disabled { color: #748198; background: #1b2839; border-color: #28394d; }
QPushButton#primary { background: #287e78; border-color: #49b4a7; font-weight: 600; }
QListWidget::item { padding: 12px 9px; border-radius: 5px; }
QListWidget::item:selected { background: #224653; }
QHeaderView::section { background: #24354b; padding: 7px; border: none; }
QTabWidget::pane { border: 1px solid #32445c; border-radius: 5px; }
QTabBar::tab { background: #1c2b40; padding: 10px 17px; }
QTabBar::tab:selected { background: #2c485b; border-bottom: 2px solid #51c5b1; }
QProgressBar { background: #0e1725; border: 1px solid #35465d; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #39a295; border-radius: 3px; }
QToolBar { spacing: 9px; padding: 6px; border-bottom: 1px solid #34445b; }
QMenuBar, QMenu { background: #1c2a3d; }
QSplitter::handle { background: #27364c; }
"""


def human_bytes(value):
    if value is None:
        return "Unknown"
    value = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:,.1f} {unit}"
        value /= 1024


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create ROVScan project")
        self.resize(650, 340)
        layout = QVBoxLayout(self)
        intro = QLabel("Choose the working root and read-only source. Creation does not copy or process data.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.expedition = QLineEdit()
        self.expedition.setPlaceholderText("NA followed by three digits")
        self.dive = QLineEdit()
        self.dive.setPlaceholderText("H followed by four digits")
        self.root = QLineEdit()
        self.source = QLineEdit()
        form.addRow("Expedition", self.expedition)
        form.addRow("Dive", self.dive)
        for label, editor in (("Working root", self.root), ("Read-only source", self.source)):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(editor)
            button = QPushButton("Browse…")
            button.clicked.connect(lambda checked=False, e=editor: self._browse(e))
            row_layout.addWidget(button)
            form.addRow(label, row)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("warning")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.document = None

    def _browse(self, editor):
        path = QFileDialog.getExistingDirectory(self, "Choose directory", editor.text())
        if path:
            editor.setText(path)

    def _accept(self):
        try:
            self.document = ProjectDocument.create(self.expedition.text().strip(), self.dive.text().strip(),
                                                     self.root.text().strip(), [self.source.text().strip()])
            self.accept()
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))


class SourceTable(QWidget):
    decision_requested = Signal(str, bool)
    bulk_exclude_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.navigation_report = None
        layout = QVBoxLayout(self)
        self.summary = QLabel("No inventory received. Scan sources to identify files and exceptions.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        filter_row = QHBoxLayout()
        self.filter_choice = QComboBox()
        self.filter_choice.addItems(["Flags only", "All files"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter path, camera, or exception…")
        filter_row.addWidget(self.filter_choice)
        filter_row.addWidget(self.search, 1)
        layout.addLayout(filter_row)
        self.model = RecordTableModel([("Path", "path"), ("Filename family", "family"), ("Optical camera", "camera"),
                                       ("Kind", "kind"), ("Bytes", "size_bytes"),
                                       ("Exception / decision", "exception")], check_key="included", parent=self)
        self.model.decision_requested.connect(self.decision_requested)
        self.proxy = RecordFilter(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.configure(flags_only=True)
        self.filter_choice.currentIndexChanged.connect(lambda index: self.proxy.configure(flags_only=index == 0))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(lambda: self.proxy.configure(query=self.search.text()))
        self.search.textChanged.connect(lambda: self._search_timer.start())
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 130)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.exclude_selected = QPushButton("Exclude selected flagged files…")
        self.exclude_selected.setEnabled(False)
        self.exclude_selected.clicked.connect(lambda: self.bulk_exclude_requested.emit(self.selected_flagged_paths()))
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        layout.addWidget(self.exclude_selected)

    def selected_flagged_paths(self):
        paths = []
        for index in self.table.selectionModel().selectedRows():
            item = self.items[self.proxy.mapToSource(index).row()]
            if item.get("included") is True and item.get("exception") and item.get("kind") in ("image", "mask"):
                paths.append(item["path"])
        return paths

    def _selection_changed(self, *args):
        self.exclude_selected.setEnabled(bool(self.selected_flagged_paths()))

    @property
    def items(self):
        return self.model.items

    def set_items(self, items):
        self.model.set_items(items)
        self._selection_changed()
        included = sum(item.get("included") is True for item in self.items)
        exceptions = sum(bool(item.get("exception")) for item in self.items)
        self.summary.setText(f"{len(items):,} files · {included:,} included · {exceptions:,} exceptions. "
                             "All counts shown; visible rows are filtered. Inclusion changes require a reason.")
        if self.navigation_report is not None:
            report = self.navigation_report
            lines = [f"Navigation: {report.get('path', 'Unknown')}",
                     f"{report.get('rows', 'Unknown')} rows · EPSG {report.get('epsg', 'Unknown')} · "
                     f"{report.get('finite_pose_rows', 'Unknown')} finite poses",
                     f"UTC: {report.get('start_utc', 'Unknown')} to {report.get('end_utc', 'Unknown')}",
                     f"Gaps over 2 seconds: {report.get('gaps_over_2s', 'Unknown')} · "
                     f"Maximum gap: {report.get('max_gap_s', 'Unknown')} seconds",
                     f"Depth range: {report.get('depth_min_m', 'Unknown')} to {report.get('depth_max_m', 'Unknown')} m"]
            lines.extend(str(value) for value in report.get("errors", []))
            lines.extend(str(value) for value in report.get("limitations", []))
            if items:
                lines.append(f"{len(items):,} image/navigation exceptions below")
            self.summary.setText("\n".join(lines))

    def set_navigation_report(self, report):
        self.navigation_report = report
        self.set_items([])


class _ProjectCall(QRunnable):
    def __init__(self, reader, project, generation, result_signal):
        super().__init__()
        self.reader, self.project = reader, project
        self.generation, self.result_signal = generation, result_signal

    def run(self):
        try:
            self.result_signal.emit(self.generation, self.reader(self.project), "")
        except Exception as exc:
            self.result_signal.emit(self.generation, [], exc)


class MainWindow(QMainWindow):
    controller_event = Signal(dict)
    project_state_loaded = Signal(int, object, object)
    project_recovered = Signal(int, object, object)
    inventory_decided = Signal(int, object, object)

    def __init__(self, controller=None, project=None):
        super().__init__()
        ensure_ui_font()
        self.controller = controller or UnavailableController()
        self.project = None
        self._saved = None
        self._running = False
        self._cancel_requested = False
        self._cancel_mode = None
        self._can_recover = False
        self._recovering = False
        self._editing_inventory = False
        self._inventory_hash = None
        self._inventory_confirmed = False
        self._quality_confirmed = False
        self._spatial_confirmed = False
        self._unsubscribe = None
        self._setup_dialog = None
        self._load_generation = 0
        self._controller_sequence = -1
        self._logging_errors = {}
        self._hydrating = False
        self.setWindowTitle("ROVScan · Project workspace")
        self.resize(1460, 960)
        self.setMinimumSize(1040, 720)
        self.setStyleSheet(STYLE)
        self._build()
        self.controller_event.connect(self._event)
        self.project_state_loaded.connect(self._restored_project_state)
        self.project_recovered.connect(self._recovered_project)
        self.inventory_decided.connect(self._inventory_decided)
        self.inventory.bulk_exclude_requested.connect(self._exclude_flagged)
        self.navigation.bulk_exclude_requested.connect(self._exclude_flagged)
        self._unsubscribe = self.controller.subscribe(self.controller_event.emit)
        if project:
            self.set_project(project)
        else:
            self._refresh()

    def _build(self):
        toolbar = QToolBar("Project")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        menu = self.menuBar().addMenu("&File")
        self.file_actions = {}
        actions = [("New project…", self.new_project, QKeySequence.StandardKey.New),
                   ("Open project…", self.open_project, QKeySequence.StandardKey.Open),
                   ("Save", self.save_project, QKeySequence.StandardKey.Save),
                   ("Save as…", self.save_as, QKeySequence.StandardKey.SaveAs)]
        for name, callback, shortcut in actions:
            action = QAction(name, self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, fn=callback: fn())
            menu.addAction(action)
            toolbar.addAction(action)
            self.file_actions[name] = action
        toolbar.addSeparator()
        recovery = QAction("Recover interrupted run…", self)
        recovery.triggered.connect(self.recover_run)
        menu.addAction(recovery)
        self.recovery_action = recovery
        workspace_menu = self.menuBar().addMenu("&Workspace")
        setup_action = QAction("Installation and storage check…", self)
        setup_action.triggered.connect(lambda: self.show_setup())
        workspace_menu.addAction(setup_action)
        self.adopt_action = QAction("Adopt existing workspace…", self)
        self.adopt_action.triggered.connect(self.adopt_workspace)
        workspace_menu.addAction(self.adopt_action)

        center = QWidget()
        page = QVBoxLayout(center)
        page.setContentsMargins(22, 18, 22, 16)
        heading = QHBoxLayout()
        self.title = QLabel("ROVScan")
        self.title.setObjectName("title")
        heading.addWidget(self.title, 1)
        self.project_badge = QLabel("Create or open a project")
        self.project_badge.setObjectName("muted")
        heading.addWidget(self.project_badge)
        page.addLayout(heading)
        self.root_label = QLabel("A persistent workspace for survey imagery, navigation and reconstruction.")
        self.root_label.setTextFormat(Qt.TextFormat.PlainText)
        self.root_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.root_label.setObjectName("muted")
        page.addWidget(self.root_label)

        horizontal = QSplitter(Qt.Orientation.Horizontal)
        self.phases = QListWidget()
        self.phases.setMaximumWidth(250)
        self.phases.setMinimumWidth(175)
        for index, stage in enumerate(STAGES, 1):
            item = QListWidgetItem(f"{index:02d}  {stage.title()}\n       Pending")
            item.setData(Qt.ItemDataRole.UserRole, stage)
            self.phases.addItem(item)
        self.phases.setCurrentRow(0)
        self.phases.currentRowChanged.connect(lambda row: self._refresh())
        horizontal.addWidget(self.phases)
        self.tabs = QTabWidget()
        self.overview = QPlainTextEdit()
        self.overview.setReadOnly(True)
        self.tabs.addTab(self.overview, "Overview")
        self.settings = SettingsPanel()
        self.settings.apply_requested.connect(self._apply_settings)
        self.settings.approve_requested.connect(self._approve_settings)
        self.settings.draft_changed.connect(self._refresh)
        self.tabs.addTab(self.settings, "Settings")
        sources = QWidget()
        source_layout = QVBoxLayout(sources)
        scan_row = QHBoxLayout()
        self.scan_button = QPushButton("Scan read-only sources")
        self.scan_button.clicked.connect(self.scan_sources)
        scan_row.addWidget(self.scan_button)
        scan_row.addWidget(QLabel("Read-only scan highlights duplicates, masks, and dive-window exceptions."), 1)
        source_layout.addLayout(scan_row)
        mask_notice = QLabel("Existing source masks must be retired from the processing inventory; rescan older projects. "
                             "Source files remain unchanged. Optional ROV masks are generated and reviewed after Batch.")
        mask_notice.setWordWrap(True)
        source_layout.addWidget(mask_notice)
        self.source_format_help = QLabel("Unknown camera or timestamp filename formats cannot be included. "
            "Explicitly exclude flagged images, or provide a corrected separate delivery and review it. "
            "Per-file camera assignment and timestamp correction are not supported here; originals remain unchanged.")
        self.source_format_help.setWordWrap(True)
        source_layout.addWidget(self.source_format_help)
        self.camera_gate = QLabel("Camera inventory review · awaiting a source scan")
        self.camera_gate.setWordWrap(True)
        self.camera_gate.setObjectName("warning")
        source_layout.addWidget(self.camera_gate)
        self.camera_counts = QTableWidget(0, 8)
        self.camera_counts.setHorizontalHeaderLabels(["Filename family", "Optical camera", "Total", "In dive window", "Duplicates",
                                                       "Conflicts", "Unmatched", "Masks"])
        self.camera_counts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.camera_counts.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.camera_counts.setMaximumHeight(180)
        source_layout.addWidget(self.camera_counts)
        self.confirm_inventory_button = QPushButton("Confirm camera counts and inventory flags…")
        self.confirm_inventory_button.clicked.connect(self.confirm_inventory)
        self.confirm_inventory_button.setEnabled(False)
        source_layout.addWidget(self.confirm_inventory_button)
        source_tabs = QTabWidget()
        self.inventory = SourceTable()
        self.navigation = SourceTable()
        self.inventory.decision_requested.connect(self._inventory_decision)
        self.navigation.decision_requested.connect(self._inventory_decision)
        source_tabs.addTab(self.inventory, "Imagery / inventory")
        source_tabs.addTab(self.navigation, "Navigation / exceptions")
        source_layout.addWidget(source_tabs)
        self.tabs.addTab(sources, "Sources")
        self.quality = QualityReview()
        self.quality.scan_requested.connect(self.scan_quality)
        self.quality.apply_requested.connect(self.apply_quality_culling)
        self.quality.draft_changed.connect(self._quality_draft_changed)
        self.tabs.addTab(self.quality, "Image screening")
        self.spatial = SpatialReview()
        self.spatial.scan_requested.connect(self.scan_spatial)
        self.spatial.apply_requested.connect(self.apply_spatial_culling)
        self.spatial.confirm_requested.connect(self.confirm_spatial)
        self.spatial.model.decision_requested.connect(self._review_draft_changed)
        self.tabs.addTab(self.spatial, "Track / density")
        self.occlusion = OcclusionReview()
        self.occlusion.scan_requested.connect(self.scan_occlusion)
        self.occlusion.apply_requested.connect(self.apply_occlusion)
        self.occlusion.skip_requested.connect(self.skip_occlusion)
        self.occlusion.draft_changed.connect(self._refresh)
        self.tabs.addTab(self.occlusion, "ROV masks")
        self.map_preview = MapPreview()
        self.tabs.addTab(self.map_preview, "Float map")
        horizontal.addWidget(self.tabs)

        inspector = QFrame()
        inspector.setObjectName("card")
        inspector.setMinimumWidth(230)
        inspector.setMaximumWidth(310)
        side = QVBoxLayout(inspector)
        self.stage_title = QLabel("Inventory")
        self.stage_title.setStyleSheet("font-size: 16pt; font-weight: 600;")
        side.addWidget(self.stage_title)
        self.stage_status = QLabel("Pending")
        side.addWidget(self.stage_status)
        self.approval_status = QLabel()
        self.approval_status.setWordWrap(True)
        side.addWidget(self.approval_status)
        self.current_settings = QPlainTextEdit()
        self.current_settings.setReadOnly(True)
        self.current_settings.setPlaceholderText("Applied settings for the selected phase")
        side.addWidget(self.current_settings, 1)
        self.start_button = QPushButton("Start selected phase")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_selected)
        side.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop…")
        self.stop_button.clicked.connect(self.stop_run)
        side.addWidget(self.stop_button)
        self.restart_button = QPushButton("Restart phase…")
        self.restart_button.clicked.connect(self.restart_selected)
        side.addWidget(self.restart_button)
        horizontal.addWidget(inspector)
        horizontal.setSizes([200, 870, 265])

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.addWidget(horizontal)
        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 6, 0, 0)
        self.progress_label = QLabel("Idle · No worker active")
        lower_layout.addWidget(self.progress_label)
        self.logging_warning = QLabel()
        self.logging_warning.setObjectName("warning")
        self.logging_warning.setTextFormat(Qt.TextFormat.PlainText)
        self.logging_warning.setWordWrap(True)
        self.logging_warning.hide()
        lower_layout.addWidget(self.logging_warning)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        progress_row.addWidget(self.progress, 3)
        self.resources = QLabel("Disk / memory: awaiting resource measurement")
        progress_row.addWidget(self.resources, 2)
        self.reserve_gauge = QProgressBar()
        self.reserve_gauge.setFixedWidth(130)
        self.reserve_gauge.setRange(0, 100)
        self.reserve_gauge.setValue(0)
        self.reserve_gauge.setFormat("Reserve unknown")
        progress_row.addWidget(self.reserve_gauge)
        lower_layout.addLayout(progress_row)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(5000)
        self.logs.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        lower_layout.addWidget(self.logs)
        vertical.addWidget(lower)
        vertical.setSizes([650, 170])
        page.addWidget(vertical, 1)
        self.setCentralWidget(center)
        self.statusBar().showMessage("Document editing is independent of execution.")

    @property
    def selected_stage(self):
        item = self.phases.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else STAGES[0]

    @property
    def has_unsaved_changes(self):
        return bool(self.project and (self._saved != self.project.to_dict() or self.settings.dirty))

    def set_project(self, project):
        if self._running:
            raise ProjectError("Cannot change projects while worker ownership is active")
        self.project = project
        self._refresh_logging_warning()
        self._saved = project.to_dict() if project.path else None
        self._running = any(s["state"] == "running" for s in project.to_dict()["stages"].values())
        self._can_recover = self._running
        self._cancel_requested = False
        self._cancel_mode = None
        self._inventory_hash = None
        self._inventory_confirmed = False
        self._quality_confirmed = False
        self._spatial_confirmed = False
        self.quality.set_project(project)
        self.spatial.set_project(project)
        self.occlusion.set_project(project)
        self.map_preview.reset()
        self.camera_counts.setRowCount(0)
        self.camera_gate.setText("Camera inventory review · awaiting a source scan")
        self.inventory.set_items([])
        self.navigation.set_navigation_report(None)
        self.settings.set_project(project, self.controller.settings_schema(project))
        self._rebind_setup()
        self._load_generation += 1
        reader = getattr(self.controller, "load_project_state", None)
        self._hydrating = reader is not None
        if reader:
            QThreadPool.globalInstance().start(_ProjectCall(reader, project, self._load_generation,
                                                                 self.project_state_loaded))
        self._refresh()

    def _restored_project_state(self, generation, events, error):
        if generation != self._load_generation:
            return
        self._hydrating = False
        if error:
            self.logs.appendPlainText(f"Stored review state could not be loaded: {error}")
            self.statusBar().showMessage("Stored review state unavailable; rescan/review before processing.")
        else:
            running = self._running
            for event in events:
                self._event(dict(event, restored=True))
            # Persisted review acknowledgements do not release a stale running attempt.
            self._running = running
        self._refresh()

    def _refresh(self):
        project = self.project
        enabled = project is not None
        for label, action in self.file_actions.items():
            action.setEnabled(not self._running and (enabled or label.startswith(("New", "Open"))))
        self.settings.setEnabled(enabled and not self._running and not self._hydrating)
        self.inventory.setEnabled(enabled and not self._running)
        self.navigation.setEnabled(enabled and not self._running)
        self.quality.setEnabled(enabled and not self._running and not self._hydrating)
        self.spatial.setEnabled(enabled and not self._running and not self._hydrating)
        self.occlusion.set_available(self._occlusion_available())
        self.scan_button.setEnabled(enabled and not self._running and not self._hydrating)
        self.start_button.setEnabled(enabled and not self._running and not self._hydrating)
        self.stop_button.setEnabled(enabled and self._running and not self._editing_inventory and self._cancel_mode != "abort_current")
        if self._setup_dialog is not None:
            self._setup_dialog.refresh_actions()
        self.restart_button.setEnabled(enabled and not self._running)
        self.recovery_action.setEnabled(enabled and self._can_recover and not self._recovering)
        self.adopt_action.setEnabled(enabled and not self._running)
        self.confirm_inventory_button.setEnabled(enabled and not self._running and bool(self._inventory_hash)
                                                   and not self._inventory_confirmed)
        if self._inventory_hash and not self._inventory_confirmed and self.selected_stage != "inventory":
            self.start_button.setEnabled(False)
        if STAGES.index(self.selected_stage) >= STAGES.index("batch") and not (
                self._inventory_confirmed and self._quality_confirmed and self._spatial_confirmed):
            self.start_button.setEnabled(False)
        if not project:
            self.overview.setPlainText("Create or open a .rovscan project.\n\n"
                                       "The project tracks approvals, stage attempts and output fingerprints.\n"
                                       "Source files remain read-only; previews never rewrite imagery.")
            return
        if STAGES.index(self.selected_stage) >= STAGES.index("align") and not (
                self.occlusion.confirmed and project.to_dict()["stages"]["batch"]["state"] == "succeeded"):
            self.start_button.setEnabled(False)
        data = project.to_dict()
        self.title.setText(f"{data['expedition']} / {data['dive']}")
        self.root_label.setText(str(project.root))
        self.project_badge.setText("Unsaved changes" if self.has_unsaved_changes else "Saved project")
        self.setWindowTitle(f"{data['expedition']} {data['dive']} {'*' if self.has_unsaved_changes else ''} · ROVScan")
        for index, name in enumerate(STAGES):
            self.phases.item(index).setText(f"{index + 1:02d}  {name.title()}\n       {data['stages'][name]['state'].title()}")
        stage = self.selected_stage
        self.stage_title.setText(f"Selected phase: {stage.title()}")
        self.stage_title.setWordWrap(True)
        entry = data["stages"][stage]
        self.stage_status.setText(f"{entry['state'].title()} · {len(entry['attempts'])} attempts")
        requirements = getattr(self.controller, "required_settings_blocks", None)
        required = requirements(stage) if callable(requirements) else None
        missing = [name for name in (required or []) if not project.settings_approved([name])]
        self.approval_status.setText(
            "Stage approval requirements unavailable" if required is None else
            f"No settings approval required for {stage.title()}. Review gates still apply." if not required else
            "Awaiting approval: " + ", ".join(name.replace("_", " ").title() for name in missing) if missing else
            "Required settings approved for this phase")
        if STAGES.index(stage) >= STAGES.index("align") and not self.occlusion.confirmed:
            self.approval_status.setText(self.approval_status.text() +
                "\nPost-batch ROV masks: review and Apply, or explicitly Skip in the ROV masks tab.")
        if not self.settings.dirty and not self.settings.has_unapplied_defaults:
            block = data["settings"].get(self.settings.block, {})
            self.settings.approval_label.setText("Approved for current content" if block.get("approval") else
                                                 "Proposed settings · Approval required before processing")
            self.settings.approve_button.setEnabled(bool(block) and not self._running)
        lines = []
        for block in required or []:
            content = data["settings"].get(block)
            state = "not yet applied" if content is None else "approved" if project.settings_approved([block]) else "unapproved"
            lines.append(f"{block.replace('_', ' ').title()} · {state}")
            fields = {field["key"]: field for field in self.settings.schema if field["block"] == block}
            if content:
                self._flatten(content["values"], lines, fields=fields)
            lines.append("")
        if required == [] or required == ():
            lines.append("Complete the applicable review panels before continuing.\n\n"
                         "The Settings tab can display another phase without changing the selected phase.")
        self.current_settings.setPlainText("\n".join(lines))
        sources = "\n".join(f"  {source}" for source in data["sources"]) or "  None declared"
        output_count = sum(output["valid"] for output in data["outputs"])
        self.overview.setPlainText(
            f"PROJECT\n{data['expedition']} / {data['dive']}\n{project.project_id}\n\n"
            f"WORKING ROOT\n{project.root}\n\nREAD-ONLY SOURCES\n{sources}\n\n"
            "LAYOUT\nraw/ · proc/ · proc/tmp/ · logs/ · metadata/\n\n"
            f"OUTPUTS\n{output_count} current / {len(data['outputs'])} recorded\n\n"
            f"SELECTED PHASE\n{stage.title()}: {entry['state']}\n{entry['reason']}\n\n"
            "CONTROL\nSettings require explicit approval. Restart retains historical deliverables.\n"
            "Cancellation stays pending until the controller confirms terminal state and released ownership.")

    @staticmethod
    def _flatten(values, lines, prefix="", fields=None):
        for key, value in values.items():
            name = f"{prefix}{key}"
            if isinstance(value, dict):
                MainWindow._flatten(value, lines, name + ".", fields=fields)
            elif isinstance(value, list):
                label = fields.get(name, {}).get("label", name.replace("_", " ")) if fields is not None else name
                lines.append(f"  {label}: {len(value)} entries")
            else:
                field = fields.get(name, {}) if fields is not None else {}
                label = field.get("label", name.replace("_", " ")) if fields is not None else name
                display = value
                for choice in field.get("choices", []):
                    if isinstance(choice, dict):
                        item = choice
                    elif isinstance(choice, (tuple, list)):
                        item = {"label": choice[0], "value": choice[1]}
                    else:
                        item = {"label": choice, "value": choice}
                    if type(item["value"]) is type(value) and item["value"] == value:
                        display = item["label"]
                        break
                lines.append(f"  {label}: {display}")

    def _error(self, message):
        self.logs.appendPlainText(f"ERROR · {message}")
        QMessageBox.warning(self, "Action could not be completed", str(message))

    def _controller_error(self, error):
        from modules.project_runtime import OwnershipUnconfirmed
        if isinstance(error, OwnershipUnconfirmed):
            self._running = True
            self._can_recover = True
            self.progress_label.setText("Ownership unconfirmed · verify recovery before restarting")
            self._refresh()
        self._error(error)

    def _maybe_save(self):
        if self._running:
            self._error("A worker still owns this project. Wait for terminal state and released ownership.")
            return False
        if self.settings.dirty:
            choice = QMessageBox.question(self, "Unapplied settings", "Discard the unapplied settings edits?",
                                           QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                           QMessageBox.StandardButton.Cancel)
            if choice != QMessageBox.StandardButton.Discard:
                return False
            self.settings.set_project(self.project, self.controller.settings_schema(self.project))
        if not self.has_unsaved_changes:
            return True
        choice = QMessageBox.question(self, "Unsaved project", "Save project changes before continuing?",
                                       QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                       QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        return self.save_project() if choice == QMessageBox.StandardButton.Save else True

    def new_project(self):
        if not self._maybe_save():
            return
        dialog = NewProjectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_project(dialog.document)

    def open_project(self, path=None):
        if not self._maybe_save():
            return False
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "ROVScan project (*.rovscan)")
        if not path:
            return False
        try:
            project = ProjectDocument.load(path)
        except (OSError, ProjectError) as exc:
            choice = QMessageBox.question(self, "Project recovery", f"{exc}\n\nTry the previous valid backup?",
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                           QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                return False
            try:
                project = ProjectDocument.load(path, recover_backup=True)
            except (OSError, ProjectError) as recovery_error:
                self._error(recovery_error)
                return False
        self.set_project(project)
        if project.recovered_from_backup:
            self._saved = None
            self.statusBar().showMessage("Backup opened in memory. Save explicitly to repair the primary.")
            self._refresh()
        return True

    def save_project(self, path=None):
        if self.project is None or self._running:
            return False
        if self.settings.dirty:
            self._error("Apply or discard the draft settings before saving the project.")
            return False
        try:
            save = getattr(self.controller, "save_project", None)
            if save is None:
                raise ProjectError("The controller must validate workspace ownership before saving this project.")
            saved = save(self.project, path)
            self._saved = self.project.to_dict()
            self.statusBar().showMessage(f"Saved {saved}")
            self._refresh()
            return True
        except Exception as exc:
            self._controller_error(exc)
            return False

    def save_as(self):
        if not self.project or self._running:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save project as", str(self.project.root / "copy.rovscan"),
                                             "ROVScan project (*.rovscan)")
        return self.save_project(path) if path else False

    def _apply_settings(self, block, values):
        if not self.project or self._running:
            return
        try:
            previous_signature = self.project.settings_signature([block])
            apply = getattr(self.controller, "apply_settings", None)
            if apply:
                apply(self.project, block, values)
            else:
                self.project.set_settings(block, values)
            if self.project.settings_signature([block]) != previous_signature:
                affected = settings_stage(block)
                if affected in ("inventory", "navigation", "georeference", "preprocess"):
                    self._invalidate_culling()
                elif affected == "batch":
                    self.occlusion.invalidate()
            self.settings.set_project(self.project, self.controller.settings_schema(self.project))
            self._rebind_setup()
            self._refresh()
        except Exception as exc:
            self._controller_error(exc)

    def _approve_settings(self, block):
        if not self.project or self._running or self.settings.dirty:
            return
        if block == self.settings.block and self.settings.has_unapplied_defaults:
            self._error("Apply the proposed defaults before reviewing approval.")
            return
        values = self.project.to_dict()["settings"].get(block, {}).get("values", {})
        lines = []
        self._flatten(values, lines)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Approve applied settings")
        dialog.setText(f"Approve the current {block} settings for this project?")
        dialog.setInformativeText("\n".join(lines) or "This block currently has no values.")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if dialog.exec() != QMessageBox.StandardButton.Ok:
            return
        name, accepted = QInputDialog.getText(self, "Record approval", "Operator name")
        if not accepted or not name.strip():
            return
        try:
            self.project.approve_settings(block, name.strip())
            self.settings.set_project(self.project, self.controller.settings_schema(self.project))
            self._refresh()
        except ValueError as exc:
            self._controller_error(exc)

    def scan_sources(self):
        if not self.project or self._running or self._hydrating:
            return
        try:
            self.controller.scan_inventory(self.project)
        except Exception as exc:
            self._controller_error(exc)

    def confirm_inventory(self):
        if not self.project or self._running or not self._inventory_hash:
            return
        choice = QMessageBox.question(self, "Confirm camera inventory", "Confirm the displayed per-camera counts "
                                       "within the dive window and review of duplicate, conflict, unmatched and mask flags?\n"
                                       "This confirmation is bound to the current input inventory hash.",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return
        name, accepted = QInputDialog.getText(self, "Record inventory confirmation", "Operator name")
        if not accepted or not name.strip():
            return
        try:
            self.controller.confirm_inventory(self.project, self._inventory_hash, name.strip())
            self._inventory_confirmed = True
            self.camera_gate.setText("Camera counts and flags confirmed for the current inventory hash")
            self._refresh()
        except Exception as exc:
            self._controller_error(exc)

    def _inventory_decision(self, path, included):
        if not self.project or self._running:
            return
        action = "Include" if included else "Exclude"
        reason, accepted = QInputDialog.getText(self, f"{action} source", f"{path}\n\nReason for this decision")
        if accepted and reason.strip():
            try:
                self.controller.set_inventory_decision(self.project, path, included, reason.strip())
                self.occlusion.invalidate()
                self._inventory_confirmed = False
                self._quality_confirmed = False
                self._spatial_confirmed = False
                self.camera_gate.setText("Inventory decision changed · review and confirm the refreshed counts")
                for table in (self.inventory, self.navigation):
                    for item in table.items:
                        if item.get("path") == path:
                            item.update(included=included, reason=reason.strip())
            except Exception as exc:
                self._controller_error(exc)
        for table in (self.inventory, self.navigation):
            table.set_items(table.items)
        self._refresh()

    def _exclude_flagged(self, paths):
        if not self.project or self._running or self._hydrating or not paths:
            return
        apply = getattr(self.controller, "set_inventory_decisions", None)
        if not callable(apply):
            self._error("This controller does not support atomic bulk inventory decisions.")
            return
        reason, accepted = QInputDialog.getText(self, "Exclude flagged files",
            f"Exclude {len(paths):,} selected flagged files from processing? Originals remain unchanged.\n\nReason")
        if not accepted or not reason.strip():
            return
        paths = list(dict.fromkeys(paths))
        self._editing_inventory = self._running = True
        self._refresh()
        QThreadPool.globalInstance().start(_ProjectCall(
            lambda project: apply(project, paths, False, reason.strip()),
            self.project, self._load_generation, self.inventory_decided))

    def _inventory_decided(self, generation, result, error):
        if generation != self._load_generation:
            return
        self._editing_inventory = self._running = False
        if error:
            self._controller_error(error)
        else:
            self._inventory_confirmed = self._quality_confirmed = self._spatial_confirmed = False
            self.occlusion.invalidate()
            self.camera_gate.setText("Inventory decision changed · review and confirm the refreshed counts")
        self._refresh()

    def start_selected(self):
        if not self.project or self._running or self._hydrating:
            return
        if self.settings.dirty:
            self._error("Apply draft settings before starting a phase.")
            return
        if self._inventory_hash and not self._inventory_confirmed and self.selected_stage != "inventory":
            self._error("Confirm camera counts and inventory flags before continuing.")
            return
        if STAGES.index(self.selected_stage) >= STAGES.index("batch") and not (
                self._inventory_confirmed and self._quality_confirmed and self._spatial_confirmed):
            self._error("Confirm image screening, inventory, and track/density review before batching or downstream processing.")
            return
        if STAGES.index(self.selected_stage) >= STAGES.index("align") and not (
                self.occlusion.confirmed and self.project.to_dict()["stages"]["batch"]["state"] == "succeeded"):
            self._error("After batching, review and Apply optional ROV masks or explicitly Skip before alignment.")
            self.tabs.setCurrentWidget(self.occlusion)
            return
        if self.selected_stage == "batch":
            self.occlusion.invalidate("Batching changed. Review optional masks again after batch completion.")
        self._running = True
        self._can_recover = False
        self._cancel_requested = False
        self._cancel_mode = None
        self.progress_label.setText(f"Starting {self.selected_stage}…")
        self._refresh()
        try:
            self.controller.start(self.project, self.selected_stage)
        except Exception as exc:
            # Contract: synchronous start rejection occurs before ownership acquisition.
            self._running = False
            self._refresh()
            self._controller_error(exc)

    def stop_run(self):
        if not self._running or self._cancel_mode == "abort_current":
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Request stop")
        dialog.setText("How should the active operation stop?")
        dialog.setInformativeText("A stop request does not release ownership. Restart stays disabled until the controller confirms it.")
        after = dialog.addButton("After current step", QMessageBox.ButtonRole.AcceptRole)
        after.setEnabled(self._cancel_mode != "after_step")
        abort = dialog.addButton("Abort current operation", QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked not in (after, abort):
            return
        try:
            mode = "after_step" if clicked == after else "abort_current"
            self.controller.stop(mode=mode)
            if self._running:
                self._cancel_requested = True
                self._cancel_mode = mode
                self.progress_label.setText("Stop after current step requested · Abort current operation remains available"
                    if mode == "after_step" else "Abort requested · awaiting terminal state and released ownership")
            self._refresh()
        except Exception as exc:
            self._controller_error(exc)

    def restart_selected(self):
        if not self.project or self._running:
            return
        stage = self.selected_stage
        choice = QMessageBox.question(self, "Restart phase", f"Invalidate {stage} and all downstream results?\n"
                                       "Attempt history and deliverable files will be retained.",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        if choice == QMessageBox.StandardButton.Yes:
            try:
                self.project.restart_stage(stage, "Operator requested restart from desktop")
                if STAGES.index(stage) <= STAGES.index("preprocess"):
                    self._invalidate_culling()
                if stage == "batch":
                    self.occlusion.invalidate()
                if stage == "inventory":
                    self._inventory_confirmed = False
                self._refresh()
            except ValueError as exc:
                self._controller_error(exc)

    def recover_run(self):
        if not self.project or not self._can_recover or self._recovering:
            return
        recover = getattr(self.controller, "recover_project", None)
        if not callable(recover):
            self._error("Recovery remains unconfirmed: this controller cannot verify runtime ownership. "
                        "Connect a controller with recover_project before retrying; restart remains disabled.")
            return
        choice = QMessageBox.question(self, "Verify interrupted-run recovery", "Check the saved runtime evidence "
                                       "and recover only if the project's owned workers and instances are confirmed stopped?\n"
                                       "Missing evidence leaves ownership unconfirmed and restart disabled.",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        if choice == QMessageBox.StandardButton.Yes:
            self._recovering = True
            self.progress_label.setText("Verifying saved runtime ownership before recovery…")
            self._refresh()
            QThreadPool.globalInstance().start(_ProjectCall(recover, self.project, self._load_generation,
                                                           self.project_recovered))

    def _recovered_project(self, generation, result, error):
        if generation != self._load_generation:
            return
        self._recovering = False
        released = isinstance(result, dict) and result.get("ownership_released") is True
        still_running = any(stage["state"] == "running" for stage in self.project.to_dict()["stages"].values())
        if error or not released or still_running:
            message = error or (result.get("message") if isinstance(result, dict) else "")
            message = message or "Runtime proof or the recovered project state is incomplete. Inspect runtime evidence and retry recovery."
            self._running = True
            self._can_recover = True
            self.progress_label.setText("Recovery unconfirmed · restart remains disabled")
            self._refresh()
            self._error(message)
            return
        self._running = False
        self._can_recover = False
        self._cancel_requested = False
        self._cancel_mode = None
        message = result.get("message") or "Runtime ownership release verified. Interrupted stages can now be reviewed and restarted."
        self.progress_label.setText(message)
        self.statusBar().showMessage(message)
        self._refresh()

    def _event(self, event):
        if not isinstance(event, dict):
            return
        if self.project and event.get("project_id") not in (None, self.project.project_id):
            return
        sequence = event.get("sequence")
        if type(sequence) is int:
            if sequence <= self._controller_sequence:
                return
            self._controller_sequence = sequence
        kind = event.get("kind")
        if event.get("logging_error") and self.project:
            warning = str(event["logging_error"])
            previous = self._logging_errors.setdefault(self.project.project_id, set())
            if warning not in previous:
                previous.add(warning)
                self.logs.appendPlainText(f"PROJECT LOGGING FAILED · {warning}")
            self._refresh_logging_warning()
        message = str(event.get("message", ""))
        if message:
            self.logs.appendPlainText(f"{datetime.now():%H:%M:%S} · {message}")
        if kind == "progress":
            current, total = event.get("current", 0), event.get("total", 0)
            if isinstance(total, (int, float)) and total > 0 and isinstance(current, (int, float)):
                self.progress.setRange(0, 1000)
                self.progress.setValue(max(0, min(1000, int(1000 * current / total))))
            else:
                self.progress.setRange(0, 0)
            self.progress_label.setText(message or f"{event.get('stage', 'Operation')} in progress")
        elif kind == "resources":
            free, reserve = event.get("free_bytes"), event.get("reserve_bytes")
            self.resources.setText(f"Free {human_bytes(free)} · reserve {human_bytes(reserve)} · "
                                   f"RAM {human_bytes(event.get('memory_bytes'))}")
            if isinstance(free, (int, float)) and isinstance(reserve, (int, float)) and reserve > 0:
                sufficient = free >= reserve
                self.reserve_gauge.setValue(max(0, min(100, round(100 * free / reserve))))
                self.reserve_gauge.setFormat("Reserve met" if sufficient else "Below reserve")
                self.reserve_gauge.setStyleSheet("QProgressBar::chunk { background: " +
                                                 ("#39a295" if sufficient else "#cf7d5f") + "; }")
        elif kind in ("inventory", "navigation"):
            table = self.inventory if kind == "inventory" else self.navigation
            rows = event.get("items", [])
            if kind == "navigation":
                reports = [row for row in rows if "structurally_valid" in row]
                if reports:
                    table.set_navigation_report(reports[-1])
                rows = [row for row in rows if "structurally_valid" not in row]
                # Match results carry errors/timestamps; inclusion and camera
                # family remain authoritative in the current inventory.
                by_path = {row.get("path"): row for row in self.inventory.items}
                rows = [{**by_path.get(row.get("path"), {}), **row} for row in rows]
            table.set_items(rows)
            if "camera_family_summary" in event or "camera_summary" in event:
                rows = event.get("camera_family_summary", event.get("camera_summary", []))
                self.camera_counts.setRowCount(len(rows))
                keys = ("family", "camera", "total", "in_window", "identical_duplicates", "conflicting_names", "unmatched", "masks")
                legacy_keys = {"camera": "camera_type", "identical_duplicates": "duplicates", "conflicting_names": "conflicts"}
                for row, camera in enumerate(rows):
                    for column, key in enumerate(keys):
                        value = camera.get(key, camera.get(legacy_keys.get(key), "Unknown"))
                        self.camera_counts.setItem(row, column, QTableWidgetItem("Unknown" if value is None else str(value)))
            if "input_inventory_hash" in event:
                if event["input_inventory_hash"] != self._inventory_hash or not event.get("inventory_confirmed"):
                    self._invalidate_culling()
                self._inventory_hash = event["input_inventory_hash"]
                self._inventory_confirmed = event.get("inventory_confirmed") is True
                self.camera_gate.setText("Camera counts and flags confirmed for current inventory" if self._inventory_confirmed
                                         else "Required review · confirm counts by camera type within the dive window and all flags")
        elif kind == "state":
            state = event.get("state")
            if state == "review_invalid":
                if event.get("stage") in ("occlusion", "occlusion_review", "align", "batch"):
                    self.occlusion.invalidate(message or "Post-batch mask review is no longer current")
                else:
                    self._invalidate_culling(quality=event.get("stage") not in ("navigation", "preprocess"))
                if event.get("stage") == "inventory":
                    self._inventory_confirmed = False
                self.progress_label.setText(message or "Stored review needs attention before processing")
                self.statusBar().showMessage(message or "Review invalid; rebuild the affected review")
            if state == "running":
                if event.get("stage") == "batch":
                    self.occlusion.invalidate("Batching in progress; optional masks need a new review afterward.")
                self._running = True
                self._can_recover = False
            elif state == "ownership_unconfirmed":
                self._running = True
                self._can_recover = True
                self.progress_label.setText(message or "Runtime ownership unconfirmed · verify recovery before restarting")
            terminal = state in ("succeeded", "failed", "interrupted", "cancelled", "stopped", "completed", "idle",
                                 "review_ready", "quality_confirmed", "selection_confirmed")
            if terminal and event.get("ownership_released") is True and not self._recovering:
                self._running = False
                self._cancel_requested = False
                self._cancel_mode = None
                self.progress.setRange(0, 100)
                self.progress.setValue(100 if state in ("succeeded", "completed") else 0)
                self.progress_label.setText(message or f"{state.title()} · worker ownership released")
                if state == "quality_confirmed":
                    if isinstance(event.get("assessment_hash"), str) and event["assessment_hash"]:
                        self.quality.assessment_hash = event["assessment_hash"]
                    self._quality_confirmed = True
                    self._spatial_confirmed = False
                elif state == "selection_confirmed":
                    self._spatial_confirmed = True
            elif terminal:
                self.progress_label.setText("Operation ended · awaiting released ownership")
        elif kind == "error":
            self.statusBar().showMessage(message)
        elif kind == "image_quality":
            self.occlusion.invalidate()
            self.quality.set_assessment(event)
            self._quality_confirmed = event.get("culling_confirmed") is True
            self._spatial_confirmed = False
        elif kind == "spatial_review":
            self.occlusion.invalidate()
            self.spatial.set_assessment(event)
            self._spatial_confirmed = event.get("confirmed") is True
        elif kind == "occlusion_masks":
            self.occlusion.set_assessment(event)
        self._refresh()

    def _refresh_logging_warning(self):
        errors = self._logging_errors.get(self.project.project_id, set()) if self.project else set()
        self.logging_warning.setText("PROJECT LOGGING FAILED · " + "; ".join(sorted(errors)) +
                                     " · Saved history may be incomplete. Logging recovery has not been confirmed."
                                     if errors else "")
        self.logging_warning.setVisible(bool(errors))

    def _review_draft_changed(self, *args):
        self._spatial_confirmed = False
        self.occlusion.invalidate()
        self._refresh()

    def _invalidate_culling(self, *, quality=True):
        self.occlusion.invalidate()
        if quality:
            self._quality_confirmed = False
            self.quality.assessment_hash = None
            self.quality.apply_button.setEnabled(False)
        self._spatial_confirmed = False
        self.spatial.assessment_hash = None
        self.spatial._selection_changed()

    def _setup_context(self):
        values = {}
        if self.project:
            blocks = self.project.to_dict()["settings"]
            values = blocks.get("operating", blocks.get("operations", {})).get("values", {})
            if not values:
                values = {field["key"]: field["default"] for field in self.controller.settings_schema(self.project)
                          if field["block"] in ("operating", "operations") and "default" in field}
        install = values.get("install_dir", "")
        if not install:
            from modules.rs_installation import DEFAULT_INSTALL_DIR
            install = str(DEFAULT_INSTALL_DIR)
        cache = values.get("cache_dir") or values.get("cache")
        if not cache and self.project:
            cache = str(self.project.resolve_path("proc/tmp/cache"))
        project = self.project
        return dict(project=project, install_dir=install, cache_root=cache,
            reserve_gib=float(values.get("reserve_gib", 50)), controller=self.controller,
            can_create_cache=lambda: self.project is project and not self._running and not self._hydrating)

    def _rebind_setup(self):
        if self._setup_dialog is not None:
            self._setup_dialog.rebind(**self._setup_context())

    def show_setup(self):
        if self._setup_dialog is not None and self._setup_dialog.isVisible():
            self._setup_dialog.refresh_actions()
            self._setup_dialog.raise_()
            self._setup_dialog.activateWindow()
            return self._setup_dialog
        self._setup_dialog = SetupDialog(**self._setup_context(), parent=self)
        self._setup_dialog.show()
        self._setup_dialog.run_check()
        return self._setup_dialog

    def adopt_workspace(self):
        if not self.project or self._running:
            return
        choice = QMessageBox.question(self, "Adopt existing workspace", f"Associate the existing raw/proc/metadata/logs "
                                       f"under {self.project.root} with project {self.project.project_id}?\n\n"
                                       "This records ownership without erasing, copying, or migrating files. "
                                       "A folder owned by another project is refused. Existing outputs still need verification.",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        if choice == QMessageBox.StandardButton.Yes:
            try:
                self.controller.adopt_workspace(self.project)
                self.statusBar().showMessage("Workspace ownership recorded; existing data retained.")
            except Exception as exc:
                self._controller_error(exc)

    def _quality_draft_changed(self):
        self._quality_confirmed = False
        self._spatial_confirmed = False
        self.occlusion.invalidate()
        self._refresh()

    def _occlusion_available(self):
        return bool(self.project and not self._running and not self._hydrating and
                    self.project.to_dict()["stages"]["batch"]["state"] == "succeeded")

    def scan_occlusion(self, options=None):
        if not self._occlusion_available():
            return
        if self.occlusion.schema_errors:
            self._error("Controller parameter schema needs correction before generating masks.")
            return
        self.occlusion.invalidate("Generating candidates; review and Apply are still required.")
        self._refresh()
        try:
            self.controller.scan_occlusion_masks(self.project, options=options)
        except Exception as exc:
            self._controller_error(exc)

    def apply_occlusion(self, assessment_hash, accepted_block_ids):
        if not self._occlusion_available() or not assessment_hash:
            return
        if (assessment_hash != self.occlusion.assessment_hash or self.occlusion.dirty or
                self.occlusion.decision != "generated" or not self.occlusion.valid_hashes or
                not self.occlusion.reviewable_count or self.occlusion.schema_errors):
            self._error("Mask assessment changed. Rerun and review current candidates before applying.")
            return
        if not accepted_block_ids:
            self._error("No mask groups selected. Check supported groups, or explicitly Skip optional masks.")
            return
        if (not isinstance(accepted_block_ids, list) or any(not isinstance(key, str) for key in accepted_block_ids)
                or len(set(accepted_block_ids)) != len(accepted_block_ids)
                or set(accepted_block_ids) != set(self.occlusion.selected_ids)):
            self._error("Mask group selection changed. Review the checked groups before applying.")
            return
        name = self._review_operator("Apply optional ROV masks", "Apply the reviewed excluded-pixel masks "
                                     f"for {len(accepted_block_ids):,} selected groups? "
                                     f"{len(self.occlusion.model.groups) - len(accepted_block_ids):,} groups will remain unmasked. "
                                     "Excluded pixels will be ignored during both alignment and meshing. "
                                     "Blocked groups remain unmasked. Original images remain unchanged. "
                                     "The same image will use the same mask across overlapping batches.")
        if name:
            try:
                self.controller.apply_occlusion_masks(self.project, assessment_hash, name,
                                                      accepted_block_ids=list(accepted_block_ids))
            except Exception as exc:
                self._controller_error(exc)
            self._refresh()

    def skip_occlusion(self):
        if not self._occlusion_available():
            return
        reason, accepted = QInputDialog.getText(self, "Skip optional ROV masks", "Reason for processing this batch without ROV masks")
        if not accepted or not reason.strip():
            return
        name = self._review_operator("Confirm Skip", "Proceed to alignment and meshing without optional ROV masks? "
                                     "This explicit decision is bound to the current batch and image content.")
        if name:
            self.occlusion.invalidate("Recording explicit Skip; current batch confirmation is pending.")
            self._refresh()
            try:
                self.controller.skip_occlusion_masks(self.project, reason.strip(), name)
            except Exception as exc:
                self._controller_error(exc)
            self._refresh()

    def scan_quality(self, tolerances=None):
        if self.project and not self._running and not self._hydrating:
            try:
                self.controller.scan_image_quality(self.project, tolerances=tolerances)
            except Exception as exc:
                self._controller_error(exc)

    def scan_spatial(self, options=None):
        if self.project and not self._running and not self._hydrating:
            try:
                self.controller.scan_spatial_review(self.project, options=options)
            except Exception as exc:
                self._controller_error(exc)

    def _review_operator(self, title, message):
        choice = QMessageBox.question(self, title, message, QMessageBox.StandardButton.Yes |
                                       QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return None
        name, accepted = QInputDialog.getText(self, "Record review", "Operator name")
        return name.strip() if accepted and name.strip() else None

    def apply_quality_culling(self, assessment_hash, excluded_paths):
        if not self.project or self._running or not assessment_hash:
            return
        if assessment_hash != self.quality.assessment_hash or self.quality._tolerance_dirty:
            self._error("Image assessment is stale. Rerun screening before applying culling.")
            return
        name = self._review_operator("Apply image culling", f"Exclude {len(excluded_paths):,} reviewed images "
                                     "from subsequent processing? An empty set keeps every candidate.\n"
                                     "Original files are retained. Batches and downstream results must be rebuilt.")
        if name:
            try:
                self.controller.apply_image_culling(self.project, assessment_hash, excluded_paths, name)
                self._quality_confirmed = True
                self._spatial_confirmed = False
                self._refresh()
            except Exception as exc:
                self._controller_error(exc)

    def apply_spatial_culling(self, assessment_hash, excluded_paths):
        if not self.project or self._running or not assessment_hash:
            return
        if assessment_hash != self.spatial.assessment_hash:
            self._error("Spatial assessment is stale. Refresh the review before applying culling.")
            return
        name = self._review_operator("Apply spatial culling", f"Exclude {len(excluded_paths):,} selected spatial "
                                     "outliers from all later stages?\nOriginal files and historical deliverables are retained. "
                                     "Refresh and confirm density review after applying.")
        if name:
            try:
                self.controller.apply_spatial_culling(self.project, assessment_hash, excluded_paths, name)
                self._spatial_confirmed = False
                if self.spatial.assessment_hash == assessment_hash:
                    self.spatial.assessment_hash = None
                    self.spatial._selection_changed()
                self._refresh()
            except Exception as exc:
                self._controller_error(exc)

    def confirm_spatial(self, assessment_hash):
        if not self.project or self._running or not assessment_hash or self.spatial.selection_dirty:
            return
        if assessment_hash != self.spatial.assessment_hash or self.spatial.invalid_count:
            self._error("A current spatial assessment with valid positions is required.")
            return
        name = self._review_operator("Confirm density review", "Confirm the image density, dive-track coverage, "
                                     "kept/culled layers, and spatial outlier review for this assessment?")
        if name:
            try:
                self.controller.confirm_spatial_review(self.project, assessment_hash, name)
                self._spatial_confirmed = True
                self._refresh()
            except Exception as exc:
                self._controller_error(exc)

    def closeEvent(self, event: QCloseEvent):
        if not self._maybe_save():
            event.ignore()
            return
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        self._load_generation += 1
        event.accept()
