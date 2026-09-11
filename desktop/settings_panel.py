"""Typed, schema-ordered settings forms with explicit Apply and Approve actions."""
import copy
import math

from PySide6.QtCore import Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from modules.project_workspace import ProjectError


_ABSENT = object()


def read_key(values, dotted):
    current = values
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return _ABSENT
        current = current[part]
    return current


def write_key(values, dotted, value):
    parts = dotted.split(".")
    current = values
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    if value is _ABSENT:
        current.pop(parts[-1], None)
    else:
        current[parts[-1]] = value


class SettingsPanel(QWidget):
    apply_requested = Signal(str, dict)
    approve_requested = Signal(str)
    draft_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.schema = []
        self.editors = {}
        self.dirty = False
        self.has_unapplied_defaults = False
        self._rendered_block = ""
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Application settings"))
        self.blocks = QComboBox()
        self.blocks.setObjectName("settingsBlock")
        row.addWidget(self.blocks, 1)
        layout.addLayout(row)
        self.approval_label = QLabel("No project")
        self.approval_label.setWordWrap(True)
        layout.addWidget(self.approval_label)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a setting or camera, e.g. pitch accuracy…")
        self.search.textChanged.connect(self._filter_fields)
        layout.addWidget(self.search)
        self._field_rows = []
        self._form = None
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)
        actions = QHBoxLayout()
        self.apply_button = QPushButton("Apply settings")
        self.approve_button = QPushButton("Review and approve…")
        self.apply_button.clicked.connect(self._apply)
        self.approve_button.clicked.connect(lambda: self.approve_requested.emit(self.block))
        actions.addWidget(self.apply_button)
        actions.addWidget(self.approve_button)
        layout.addLayout(actions)
        self.blocks.currentIndexChanged.connect(self._switch_block)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName("warning")
        layout.addWidget(self.error_label)

    @property
    def block(self):
        return self.blocks.currentData() or ""

    def set_project(self, project, schema):
        selected = self.block
        self.project, self.schema = project, list(schema)
        names = list(dict.fromkeys(field["block"] for field in self.schema))
        if project:
            names.extend(name for name in project.to_dict()["settings"] if name not in names)
        self.blocks.blockSignals(True)
        self.blocks.clear()
        for name in names:
            self.blocks.addItem(name.replace("_", " ").title(), name)
        index = self.blocks.findData(selected)
        if index >= 0:
            self.blocks.setCurrentIndex(index)
        self.blocks.blockSignals(False)
        self.dirty = False
        self._render()

    def _switch_block(self, *args):
        if self.dirty:
            choice = QMessageBox.question(self, "Unapplied settings", "Discard these unapplied edits and change settings block?",
                                          QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if choice != QMessageBox.StandardButton.Discard:
                self.blocks.blockSignals(True)
                self.blocks.setCurrentIndex(self.blocks.findData(self._rendered_block))
                self.blocks.blockSignals(False)
                return
        self._render()

    def _mark_dirty(self, *args):
        self.dirty = True
        self.approve_button.setEnabled(False)
        self.approval_label.setText("Unapplied edits · Apply before reviewing approval")
        self.draft_changed.emit()

    def _render(self, *args):
        self.dirty = False
        self.has_unapplied_defaults = False
        self._rendered_block = self.block
        self.editors = {}
        self.error_label.clear()
        content = QWidget()
        form = QFormLayout(content)
        self._form = form
        self._field_rows = []
        seen_help = set()
        form.setSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.scroll.setWidget(content)
        block = (self.project.to_dict()["settings"].get(self.block, {}) if self.project else {})
        values = block.get("values", {})
        approved = bool(block.get("approval"))
        self.approval_label.setText("Approved for current content" if approved else
                                    "Proposed settings · Approval required before processing")
        fields = [field for field in self.schema if field["block"] == self.block]
        self.apply_button.setEnabled(bool(fields))
        self.approve_button.setEnabled(bool(block))
        if not fields:
            form.addRow(QLabel("No editable settings are available for this block."))
            return
        for field in fields:
            first_row = form.rowCount()
            key, kind = field["key"], field.get("type", "str")
            value = read_key(values, key)
            if value is _ABSENT:
                value = field.get("default", _ABSENT)
                if value is not _ABSENT:
                    self.has_unapplied_defaults = True
            label = field.get("label", key) + (" *" if field.get("required") else "")
            label_widget = QLabel(label)
            label_widget.setWordWrap(True)
            label_widget.setMinimumWidth(140)
            label_widget.setMaximumWidth(240)
            if kind in ("bool", "choice", "enum"):
                editor = QComboBox()
                editor.addItem("Not set", None)
                choices = [("Enabled", True), ("Disabled", False)] if kind == "bool" else field.get("choices", [])
                for choice in choices:
                    if isinstance(choice, dict):
                        editor.addItem(str(choice.get("label", choice["value"])), choice["value"])
                    elif isinstance(choice, (tuple, list)):
                        editor.addItem(str(choice[0]), choice[1])
                    else:
                        editor.addItem(str(choice), choice)
                if value is not _ABSENT and value is not None:
                    # QVariant equates False and zero: type must match too.
                    index = next((i for i in range(1, editor.count())
                                  if type(editor.itemData(i)) is type(value) and
                                  editor.itemData(i) == value), -1)
                    if index < 0:
                        editor.addItem(f"Stored value: {value}", value)
                        index = editor.count() - 1
                    editor.setCurrentIndex(index)
                editor.currentIndexChanged.connect(self._mark_dirty)
            else:
                editor = QLineEdit()
                editor.setPlaceholderText("Not set")
                if kind in ("int", "integer"):
                    editor.setValidator(QIntValidator(-2147483648, 2147483647, editor))
                elif kind in ("float", "number"):
                    validator = QDoubleValidator(editor)
                    validator.setNotation(QDoubleValidator.Notation.ScientificNotation)
                    editor.setValidator(validator)
                if value is not _ABSENT and value is not None:
                    editor.setText(str(value))
                editor.textEdited.connect(self._mark_dirty)
            editor.setObjectName(f"setting:{self.block}:{key}")
            editor.setToolTip(field.get("help", ""))
            self.editors[key] = (field, editor)
            if kind == "path":
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(editor)
                browse = QPushButton("Browse…")
                browse.clicked.connect(lambda checked=False, e=editor, f=field: self._browse(e, f))
                row_layout.addWidget(browse)
                form.addRow(label_widget, row)
            else:
                form.addRow(label_widget, editor)
            if field.get("help") and field["help"] not in seen_help:
                seen_help.add(field["help"])
                help_label = QLabel(field["help"])
                help_label.setWordWrap(True)
                help_label.setObjectName("muted")
                form.addRow("", help_label)
            self._field_rows.append((first_row, form.rowCount(), field))
        self._filter_fields()
        if self.has_unapplied_defaults:
            self.approval_label.setText("Proposed defaults are not saved · Apply settings before reviewing approval")
            self.approve_button.setEnabled(False)

    def _filter_fields(self, *args):
        if self._form is None:
            return
        query = self.search.text().casefold().replace("_", " ")
        for first, end, field in self._field_rows:
            haystack = (field["key"] + " " + field.get("label", "")).casefold().replace("_", " ")
            visible = all(word in haystack for word in query.split())
            for row in range(first, end):
                self._form.setRowVisible(row, visible)

    def _browse(self, editor, field):
        if field.get("path_kind") == "file":
            path, _ = QFileDialog.getOpenFileName(self, "Choose file", editor.text())
        else:
            path = QFileDialog.getExistingDirectory(self, "Choose directory", editor.text())
        if path:
            editor.setText(path)
            self._mark_dirty()

    def values(self):
        values = copy.deepcopy(self.project.to_dict()["settings"].get(self.block, {}).get("values", {}))
        for key, (field, editor) in self.editors.items():
            kind = field.get("type", "str")
            if isinstance(editor, QComboBox):
                value = editor.currentData() if editor.currentIndex() else _ABSENT
            else:
                text = editor.text().strip()
                value = text if text else _ABSENT
                if text and kind in ("int", "integer", "float", "number"):
                    try:
                        value = int(text) if kind in ("int", "integer") else float(text)
                    except ValueError as exc:
                        raise ProjectError(f"{field.get('label', key)}: invalid {kind}") from exc
                    if isinstance(value, float) and not math.isfinite(value):
                        raise ProjectError(f"{key}: finite value required")
                    if ("min" in field and value < field["min"]) or ("max" in field and value > field["max"]):
                        raise ProjectError(f"{key}: outside the permitted range")
            if field.get("required") and value is _ABSENT:
                raise ProjectError(f"{field.get('label', key)} is required")
            write_key(values, key, value)
        return values

    def _apply(self):
        try:
            self.apply_requested.emit(self.block, self.values())
        except (ValueError, TypeError) as exc:
            self.error_label.setText(str(exc))
