"""Virtualized review records and lazy, read-only image thumbnails."""
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRunnable, QSize, QSortFilterProxyModel, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImageReader, QPixmap
from PySide6.QtWidgets import QLabel


def _display_record_value(key, value):
    """Clarify legacy guidance without altering persisted inventory evidence."""
    text = "Unknown" if value is None else str(value)
    if key == "exception":
        text = text.replace("Unrecognised camera; assign a camera or explicitly exclude",
                            "Unsupported camera filename format; cannot include. Explicitly exclude or provide a corrected separate delivery")
        text = text.replace("No valid UTC timestamp; explicit correction or exclusion required",
                            "Unsupported or missing UTC timestamp in filename; cannot include. Explicitly exclude or provide a corrected separate delivery")
    return text


class RecordTableModel(QAbstractTableModel):
    decision_requested = Signal(str, bool)

    def __init__(self, columns, *, check_key=None, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.check_key = check_key
        self.items = []
        self.selected_paths = set()

    def set_items(self, items):
        self.beginResetModel()
        self.items = list(items)
        self.selected_paths = set()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns) + 1

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ("Include" if self.check_key else "Exclude") if section == 0 else self.columns[section - 1][0]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        item = self.items[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            if self.check_key and type(item.get(self.check_key)) is not bool:
                return None
            checked = item.get(self.check_key) is True if self.check_key else item.get("path") in self.selected_paths
            return Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole and index.column() > 0:
            key = self.columns[index.column() - 1][1]
            return _display_record_value(key, item.get(key))
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(f"{key}: {_display_record_value(key, value)}" for key, value in item.items())
        if role == Qt.ItemDataRole.ForegroundRole and (item.get("exception") or item.get("outlier")):
            return QColor("#f0bf71")
        return None

    def flags(self, index):
        flags = super().flags(index)
        if self.check_key and index.isValid() and type(self.items[index.row()].get(self.check_key)) is not bool:
            return flags
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        if not self.flags(index) & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        path = str(self.items[index.row()]["path"])
        if self.check_key is None:
            if checked:
                self.selected_paths.add(path)
            else:
                self.selected_paths.discard(path)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.decision_requested.emit(path, checked)
        return True


class RecordFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.flags_only = False
        self.query = ""

    def configure(self, *, flags_only=None, query=None):
        self.beginFilterChange()
        if flags_only is not None:
            self.flags_only = flags_only
        if query is not None:
            self.query = query.casefold()
        self.endFilterChange()

    def filterAcceptsRow(self, row, parent):
        item = self.sourceModel().items[row]
        if self.flags_only and not (item.get("exception") or item.get("outlier") or item.get("reason")):
            return False
        if self.query and not any(self.query in _display_record_value(key, item.get(key, "")).casefold()
                                  for key in ("path", "family", "camera", "kind", "exception", "reason")):
            return False
        return True


class _ThumbnailSignals(QObject):
    ready = Signal(int, object, str)


class _ThumbnailTask(QRunnable):
    def __init__(self, generation, path, signals, *, max_size=(560, 400)):
        super().__init__()
        self.generation, self.path, self.signals = generation, path, signals
        self.max_size = max_size

    def run(self):
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and self.max_size is not None:
                reader.setScaledSize(size.scaled(QSize(*self.max_size), Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            self.signals.ready.emit(self.generation, image, reader.errorString() if image.isNull() else "")
        except Exception as exc:
            self.signals.ready.emit(self.generation, None, str(exc))


def preview_path(project, path):
    """Resolve read-only preview paths against project and declared source roots."""
    target = Path(path).resolve()
    if project is None:
        raise ValueError("Open a project before previewing imagery")
    roots = [project.root.resolve()] + [Path(p).resolve() for p in project.to_dict()["sources"]]
    if not any(target == root or target.is_relative_to(root) for root in roots):
        raise ValueError("Image lies outside the project and declared read-only sources")
    return target


class LazyThumbnail(QLabel):
    """Decode only the selected image asynchronously, with Qt's allocation guard."""
    def __init__(self, parent=None):
        super().__init__("Select an image to preview", parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 160)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.project = None
        self._generation = 0
        self._signals = _ThumbnailSignals(self)
        self._signals.ready.connect(self._loaded)

    def set_project(self, project):
        self._generation += 1
        self.project = project
        self.clear()
        self.setText("Select an image to preview")

    def load_path(self, path):
        self._generation += 1
        self.clear()
        self.setText("Loading selected thumbnail…")
        try:
            target = preview_path(self.project, path)
            QThreadPool.globalInstance().start(_ThumbnailTask(self._generation, str(target), self._signals))
        except (ValueError, OSError) as exc:
            self.setText(str(exc))

    def _loaded(self, generation, image, error):
        if generation != self._generation:
            return
        if error or image is None:
            self.setText(f"Preview unavailable: {error}")
        else:
            self.setPixmap(QPixmap.fromImage(image).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation))
