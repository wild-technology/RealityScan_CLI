"""Optional post-batch hardware masks; generation never implies approval."""
import math
from collections import Counter
from datetime import datetime, timezone

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTableView, QVBoxLayout, QWidget,
)

from .review_widgets import LazyThumbnail
from .image_review import ImageReviewDialog


def _utc_interval(group):
    start, duration = group.get("start_unix"), group.get("block_seconds")
    if (type(start) not in (int, float) or type(duration) not in (int, float)
            or not math.isfinite(start) or not math.isfinite(duration) or duration <= 0):
        return ""
    try:
        first = datetime.fromtimestamp(start, timezone.utc)
        last = datetime.fromtimestamp(start + duration, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return ""
    return f"{first:%Y-%m-%d %H:%M:%S}\n→ {last:%Y-%m-%d %H:%M:%S} UTC"


class GroupModel(QAbstractTableModel):
    selection_changed = Signal()
    columns = [("Use / UTC interval", "group_id"), ("Camera", "camera"),
               ("Family", "family"), ("Status", "display_status"),
               ("Blockers / why unmasked", "blockers"), ("Images", "image_count"),
               ("Samples", "sample_count"), ("Excluded fraction", "excluded_fraction")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups = []
        self.checked = set()
        self.editable = False

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.groups)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            group = self.groups[index.row()]
            if group.get("selectable"):
                return Qt.CheckState.Checked if group["group_id"] in self.checked else Qt.CheckState.Unchecked
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            key = self.columns[index.column()][1]
            value = self.groups[index.row()].get(key)
            if key == "group_id" and self.groups[index.row()].get("utc_interval"):
                interval = self.groups[index.row()]["utc_interval"]
                return (interval + f"\nEnd exclusive. Stable group: {value}"
                        if role == Qt.ItemDataRole.ToolTipRole else interval)
            if key == "blockers":
                if isinstance(value, list):
                    value = "; ".join(str(item).replace("_", " ") for item in value)
                return str(value or "None reported")
            if key == "group_id" and isinstance(value, str) and len(value) > 18 and role == Qt.ItemDataRole.DisplayRole:
                return value[:15] + "…"
            return "Unknown" if value is None else str(value)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section][0]

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0 and self.editable and self.groups[index.row()].get("selectable"):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (role != Qt.ItemDataRole.CheckStateRole or not index.isValid() or index.column() != 0
                or not self.editable or not self.groups[index.row()].get("selectable")):
            return False
        key = self.groups[index.row()]["group_id"]
        if value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value:
            self.checked.add(key)
        elif value == Qt.CheckState.Unchecked or value == Qt.CheckState.Unchecked.value:
            self.checked.discard(key)
        else:
            return False
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.selection_changed.emit()
        return True

    def set_groups(self, groups, checked=()):
        self.beginResetModel()
        self.groups = list(groups)
        self.checked = set(checked)
        self.endResetModel()


class OcclusionReview(QWidget):
    scan_requested = Signal(object)
    apply_requested = Signal(str, list)
    skip_requested = Signal()
    draft_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.assessment_hash = None
        self.batch_fingerprint = None
        self.confirmed = False
        self.decision = "pending"
        self.dirty = False
        self.valid_hashes = False
        self.reviewable_count = 0
        self.editors = {}
        self.schema_errors = []
        self._available = False
        self._previews = []
        self._overlay_path = None
        self._review_viewer = None
        layout = QVBoxLayout(self)
        intro = QLabel("Optional ROV hardware masking · AFTER Batch, BEFORE Align. Generate candidates, "
                       "review original images beside the excluded-pixel overlay, check the groups to use, then Apply; or explicitly Skip. "
                       "Applied masks make excluded pixels ignored during both alignment and meshing. "
                       "Original imagery is retained. The same image uses the same mask in every overlapping batch.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.selection_label = QLabel()
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)
        form_widget = QWidget()
        self.form = QFormLayout(form_widget)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setWidget(form_widget)
        self.form_scroll.setMaximumHeight(165)
        self.form_scroll.hide()
        layout.addWidget(self.form_scroll)
        toolbar = QHBoxLayout()
        self.scan_button = QPushButton("Generate / rerun masks")
        self.apply_button = QPushButton("Apply reviewed masks…")
        self.skip_button = QPushButton("Skip optional masks…")
        self.scan_button.clicked.connect(lambda: self.scan_requested.emit(self.options()))
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(self.assessment_hash, self.selected_ids))
        self.skip_button.clicked.connect(self.skip_requested)
        for button in (self.scan_button, self.apply_button, self.skip_button):
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.model = GroupModel(self)
        self.model.selection_changed.connect(self._selection_changed)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 240), (1, 95), (2, 140), (3, 145), (5, 65), (6, 75), (7, 135)):
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setMaximumHeight(160)
        layout.addWidget(self.table)
        self.sample_choice = QComboBox()
        self.sample_choice.currentIndexChanged.connect(self._preview)
        layout.addWidget(self.sample_choice)
        previews = QSplitter()
        self.original = LazyThumbnail()
        self.overlay = LazyThumbnail()
        self.open_review_button = QPushButton("Open enlarged temporal review…")
        self.open_review_button.setEnabled(False)
        self.open_review_button.clicked.connect(self.open_temporal_review)
        for title, thumbnail in (("First sampled original (read-only)", self.original),
                                 ("Temporal review: first / middle / last", self.overlay)):
            box = QWidget()
            column = QVBoxLayout(box)
            column.addWidget(QLabel(title))
            if thumbnail is self.overlay:
                column.addWidget(self.open_review_button)
            column.addWidget(thumbnail, 1)
            previews.addWidget(box)
        layout.addWidget(previews, 1)
        self.table.selectionModel().currentRowChanged.connect(self._group_changed)
        self.invalidate()

    def set_project(self, project):
        self.original.set_project(project)
        self.overlay.set_project(project)
        self.model.set_groups([])
        self.sample_choice.clear()
        self._previews = []
        self.batch_fingerprint = None
        self.editors = {}
        self.schema_errors = []
        while self.form.rowCount():
            self.form.removeRow(0)
        self.form_scroll.hide()
        self.invalidate()

    def invalidate(self, message="Complete batching, then generate and review masks or explicitly Skip."):
        self._close_temporal_review()
        self._overlay_path = None
        self.open_review_button.setEnabled(False)
        self.confirmed = False
        self.assessment_hash = None
        self.decision = "pending"
        self.dirty = False
        self.valid_hashes = False
        self.reviewable_count = 0
        self.model.set_groups([dict(group, display_status="Previous assessment · not current")
                               for group in self.model.groups])
        self.summary.setText(message)
        self.set_available(self._available)

    def set_available(self, available):
        self._available = available
        self.model.editable = bool(available and self.valid_hashes and self.decision == "generated"
                                   and not self.dirty and not self.schema_errors)
        self.scan_button.setEnabled(available and not self.schema_errors)
        self.skip_button.setEnabled(available)
        self.form_scroll.setEnabled(available)
        self.apply_button.setEnabled(available and self.valid_hashes and
                                     bool(self.selected_ids) and self.decision == "generated" and
                                     not self.dirty and not self.schema_errors)
        selected = len(self.selected_ids)
        self.selection_label.setText(
            f"{selected:,} groups selected; {len(self.model.groups) - selected:,} groups remain unmasked. "
            "Only checked groups will be applied." if self.decision == "generated" and selected else
            "No groups selected. Check supported groups to Apply, or choose Skip optional masks."
            if self.decision == "generated" else
            "To change applied group choices, generate/rerun and review a new selection, or explicitly Skip."
            if self.decision == "applied" else "")

    @property
    def selected_ids(self):
        return [group["group_id"] for group in self.model.groups
                if group.get("selectable") and group["group_id"] in self.model.checked]

    def _selection_changed(self):
        self.confirmed = False
        self.set_available(self._available)
        self.draft_changed.emit()

    def set_assessment(self, event):
        self.assessment_hash = event.get("assessment_hash")
        self.batch_fingerprint = event.get("batch_fingerprint")
        self.decision = event.get("decision", "pending")
        self.valid_hashes = all(isinstance(value, str) and len(value) == 64 and
                           all(c in "0123456789abcdef" for c in value)
                           for value in (self.assessment_hash, self.batch_fingerprint))
        self.confirmed = (self.valid_hashes and event.get("confirmed") is True and
                          self.decision in ("applied", "skipped"))
        self.dirty = False
        groups = [dict(group) for group in event.get("groups", [])]
        keys = [group.get("group_id") for group in groups]
        duplicates = {key for key, count in Counter(key for key in keys if isinstance(key, str)).items() if count > 1}
        mappings = event.get("mappings", [])
        applied_valid = isinstance(mappings, list) and all(
            isinstance(row, dict) and isinstance(row.get("group_id"), str) for row in mappings)
        applied_ids = {row["group_id"] for row in mappings} if applied_valid else set()
        self.reviewable_count = 0
        for group in groups:
            group["utc_interval"] = _utc_interval(group)
            supported = (group.get("status") in ("candidate_review_required", "applied") and not group.get("blockers")
                         and isinstance(group.get("group_id"), str) and bool(group["group_id"])
                         and group["group_id"] not in duplicates)
            group["selectable"] = supported
            self.reviewable_count += supported
            group["display_status"] = (
                "Skipped · unmasked" if self.decision == "skipped" and self.confirmed else
                "Applied" if self.decision == "applied" and self.confirmed and supported and group["group_id"] in applied_ids else
                "Not selected · unmasked" if self.decision == "applied" and supported else
                "Review required" if supported else "Unmasked · blocked" if group.get("blockers") else
                str(group.get("status") or "Unknown · unmasked").replace("_", " "))
        if self.decision == "applied" and not (applied_valid and applied_ids and applied_ids <= {
                group["group_id"] for group in groups if group["selectable"]}):
            self.confirmed = False
            for group in groups:
                group["display_status"] = "Unconfirmed · mapping unavailable"
        self.model.set_groups(groups, applied_ids if self.confirmed and self.decision == "applied" else ())
        self.sample_choice.clear()
        self.original.set_project(self.original.project)
        self.overlay.set_project(self.overlay.project)
        self.editors = {}
        self.schema_errors = []
        while self.form.rowCount():
            self.form.removeRow(0)
        values = event.get("parameters", {})
        for field in event.get("parameter_schema", []):
            key = field["key"]
            value = values.get(key, field.get("default"))
            kind = field.get("type")
            if value is None:
                continue
            if kind in ("int", "integer", "float", "number"):
                lo = field.get("min", 0)
                hi = field.get("max", 2147483647 if kind in ("int", "integer") else 1e12)
                valid = (type(value) in (int, float) and math.isfinite(value) and
                         type(lo) in (int, float) and type(hi) in (int, float) and
                         math.isfinite(lo) and math.isfinite(hi) and lo <= value <= hi)
                if kind in ("int", "integer"):
                    valid = valid and type(value) is int and lo <= hi and -2147483648 <= lo and hi <= 2147483647
                if not valid:
                    self.schema_errors.append(f"{key}: proposed value {value!r} is incompatible with the controller schema")
                    self.form.addRow(field.get("label", key), QLabel(str(value) + " · Schema mismatch"))
                    continue
            if kind in ("int", "integer"):
                editor = QSpinBox()
                editor.setRange(int(field.get("min", 0)), int(field.get("max", 2147483647)))
                editor.setSingleStep(int(field.get("step", 1)))
                editor.setValue(int(value))
                editor.valueChanged.connect(self._edited)
            elif kind in ("float", "number"):
                editor = QDoubleSpinBox()
                editor.setDecimals(6)
                editor.setRange(float(field.get("min", 0)), float(field.get("max", 1e12)))
                editor.setValue(float(value))
                editor.valueChanged.connect(self._edited)
            elif kind in ("bool", "boolean"):
                editor = QCheckBox()
                editor.setChecked(bool(value))
                editor.toggled.connect(self._edited)
            else:
                self.schema_errors.append(f"{key}: unsupported control type {kind!r}")
                continue
            if not isinstance(editor, QCheckBox) and editor.value() != value:
                self.schema_errors.append(f"{key}: control cannot represent the proposed value exactly")
                self.form.addRow(field.get("label", key), QLabel(str(value) + " · Schema precision mismatch"))
                editor.deleteLater()
                continue
            editor.setObjectName(f"occlusion:{key}")
            editor.setToolTip(field.get("help", ""))
            self.editors[key] = editor
            self.form.addRow(field.get("label", key.replace("_", " ").title()), editor)
        self.form_scroll.setVisible(bool(self.form.rowCount()))
        if self.schema_errors:
            self.confirmed = False
        state = ("Applied masks confirmed" if self.decision == "applied" else "Explicit Skip confirmed") if self.confirmed else (
            "Generated candidates need review and Apply" if self.decision == "generated" else "Mask choice needs confirmation")
        masked = len(applied_ids) if self.confirmed and self.decision == "applied" else 0
        counts = (f"{masked:,} masked / {len(groups) - masked:,} unmasked groups. "
                  f"{self.reviewable_count:,} groups with supported candidates.")
        if self.decision == "skipped" and not groups:
            counts = "All batch images remain unmasked; group counts unavailable without an assessment."
        if self.decision == "generated" and not self.reviewable_count:
            counts += " No supported candidate: adjust sampling/tolerances and rerun, or explicitly Skip."
        self.summary.setText(f"{state} · {counts}\n" +
                             str(event.get("message") or event.get("reason") or ""))
        if self.schema_errors:
            self.summary.setText("Controller parameter schema needs correction; generation and Apply are disabled.\n" +
                                 "\n".join(self.schema_errors))
        if self.model.groups:
            self.table.selectRow(0)
        self.set_available(self._available)

    def options(self):
        if self.schema_errors:
            raise ValueError("Controller parameter schema needs correction; proposed values were not changed")
        return {key: editor.isChecked() if isinstance(editor, QCheckBox) else editor.value()
                for key, editor in self.editors.items()} or None

    def _edited(self, *args):
        self.dirty = True
        self.confirmed = False
        self.summary.setText("Generation parameters changed. Rerun and review masks, or explicitly Skip, before alignment.")
        self.set_available(self._available)
        self.draft_changed.emit()

    def _group_changed(self, index, previous):
        self._previews = self.model.groups[index.row()].get("previews", []) if index.isValid() else []
        self.sample_choice.blockSignals(True)
        self.sample_choice.clear()
        self.sample_choice.addItems([f"Sample {i + 1}: {sample.get('image_path', 'Unavailable')}"
                                    for i, sample in enumerate(self._previews)])
        self.sample_choice.blockSignals(False)
        self._preview(self.sample_choice.currentIndex())

    def _preview(self, index):
        self._close_temporal_review()
        self._overlay_path = None
        self.open_review_button.setEnabled(False)
        self.original.set_project(self.original.project)
        self.overlay.set_project(self.overlay.project)
        if 0 <= index < len(self._previews):
            sample = self._previews[index]
            self._overlay_path = sample.get("overlay_path")
            self.open_review_button.setEnabled(bool(self._overlay_path))
            for field, thumbnail in (("image_path", self.original), ("overlay_path", self.overlay)):
                if sample.get(field):
                    thumbnail.load_path(sample[field])
                else:
                    thumbnail.setText("Preview unavailable")

    def _close_temporal_review(self):
        if self._review_viewer is not None:
            self._review_viewer.close()

    def open_temporal_review(self):
        if not self._overlay_path or self.overlay.project is None:
            return
        if self._review_viewer is not None and self._review_viewer.isVisible():
            self._review_viewer.raise_()
            self._review_viewer.activateWindow()
            return
        index = self.table.currentIndex()
        group = self.model.groups[index.row()] if index.isValid() else {}
        context = group.get("utc_interval") or group.get("group_id", "")
        self._review_viewer = ImageReviewDialog(self.overlay.project, self._overlay_path,
            title="Temporal review: first / middle / last · " + str(context).replace("\n", " "), parent=self)
        self._review_viewer.show()
