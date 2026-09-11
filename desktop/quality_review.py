"""Conservative screening review: suggestions never become automatic exclusions."""
import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSplitter, QTableView, QVBoxLayout, QWidget,
)

from .review_widgets import LazyThumbnail, RecordTableModel


class QualityReview(QWidget):
    scan_requested = Signal(object)
    apply_requested = Signal(str, list)
    draft_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.assessment_hash = None
        self.tolerances = {}
        self.tolerance_schema = {}
        self.editors = {}
        self._tolerance_dirty = False
        layout = QVBoxLayout(self)
        self.summary = QLabel("Run conservative screening. Images with useful partial scene content should be kept. "
                              "Candidates are suggestions; nothing is culled automatically.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.form_widget = QWidget()
        self.form = QFormLayout(self.form_widget)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setWidget(self.form_widget)
        self.form_scroll.setMaximumHeight(190)
        self.form_scroll.setVisible(False)
        layout.addWidget(self.form_scroll)
        toolbar = QHBoxLayout()
        self.scan_button = QPushButton("Run / rerun screening")
        self.scan_button.clicked.connect(self._scan)
        toolbar.addWidget(self.scan_button)
        self.apply_button = QPushButton("Apply reviewed culling…")
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(self.assessment_hash,
                                                                             sorted(self.model.selected_paths)))
        self.apply_button.setEnabled(False)
        toolbar.addWidget(self.apply_button)
        layout.addLayout(toolbar)
        self.model = RecordTableModel([("Image", "path"), ("Candidate reason", "reason"), ("Score", "score")], parent=self)
        self.model.decision_requested.connect(self._selection_changed)
        self.model.decision_requested.connect(lambda *args: self.draft_changed.emit())
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.thumbnail = LazyThumbnail()
        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(self.thumbnail)
        splitter.setSizes([650, 300])
        layout.addWidget(splitter, 1)
        self.table.selectionModel().currentRowChanged.connect(self._preview)
        self.message = QLabel("No exclusions selected")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def set_project(self, project):
        self.thumbnail.set_project(project)
        self.assessment_hash = None
        self.model.set_items([])
        self.apply_button.setEnabled(False)
        while self.form.rowCount():
            self.form.removeRow(0)
        self.tolerances = {}
        self.tolerance_schema = {}
        self.editors = {}
        self._tolerance_dirty = False
        self.form_scroll.setVisible(False)
        self.summary.setText("Run conservative screening. Useful partial scenes should be kept; candidates are never culled automatically.")
        self.message.setText("No exclusions selected")

    def set_assessment(self, event):
        self.assessment_hash = event.get("assessment_hash")
        candidates = []
        for entry in event.get("candidates", []):
            item = dict(entry)
            if "reason" not in item and "reasons" in item:
                item["reason"] = "; ".join(str(reason) for reason in item["reasons"])
            if isinstance(item.get("reason"), str):
                item["reason"] = item["reason"].replace("_", " ")
            candidates.append(item)
        self.model.set_items(candidates)
        if event.get("restored") is True:
            self.model.selected_paths = {item["path"] for item in candidates if item.get("excluded") is True}
        self.tolerances = dict(event.get("tolerances", {}))
        self.tolerance_schema = {field["key"]: field for field in event.get("tolerance_schema", [])}
        while self.form.rowCount():
            self.form.removeRow(0)
        self.editors = {}
        for key, value in self.tolerances.items():
            field = self.tolerance_schema.get(key, {})
            editor = QLineEdit(str(value))
            editor.setObjectName(f"quality:{key}")
            editor.setToolTip(field.get("help", ""))
            editor.textEdited.connect(self._edited)
            self.editors[key] = editor
            self.form.addRow(field.get("label", key.replace("_", " ").title()), editor)
        self._tolerance_dirty = False
        self.form_scroll.setVisible(bool(self.editors))
        summary = event.get("summary")
        if isinstance(summary, dict):
            summary = f"{summary.get('images', 'Unknown')} images screened · {summary.get('candidates', len(candidates))} candidates."
        self.summary.setText(str(summary or f"{len(self.model.items):,} candidates for review.") +
                             " Useful partial scenes should be kept; check only images you explicitly want excluded.")
        self._selection_changed()

    def _edited(self, *args):
        self._tolerance_dirty = True
        self.apply_button.setEnabled(False)
        self.message.setText("Tolerances changed. Rerun screening before applying a cull set.")
        self.draft_changed.emit()

    def _scan(self):
        try:
            values = {}
            for key, editor in self.editors.items():
                initial = self.tolerances[key]
                text = editor.text().strip()
                if type(initial) is bool:
                    if text.lower() not in ("true", "false"):
                        raise ValueError(f"{key}: enter true or false")
                    value = text.lower() == "true"
                elif type(initial) in (int, float):
                    value = int(text) if type(initial) is int else float(text)
                    if not math.isfinite(value):
                        raise ValueError(f"{key}: finite value required")
                    field = self.tolerance_schema.get(key, {})
                    if ("min" in field and value < field["min"]) or ("max" in field and value > field["max"]):
                        raise ValueError(f"{key}: outside the permitted range")
                else:
                    value = text
                values[key] = value
            self.scan_requested.emit(values if self.editors else None)
        except ValueError as exc:
            self.message.setText(str(exc))

    def _selection_changed(self, *args):
        self.apply_button.setEnabled(bool(self.assessment_hash) and not self._tolerance_dirty)
        self.message.setText(f"{len(self.model.selected_paths):,} exclusions selected. "
                             "Applying an empty set explicitly keeps every candidate.")

    def _preview(self, index, previous):
        if index.isValid():
            self.thumbnail.load_path(self.model.items[index.row()]["path"])
