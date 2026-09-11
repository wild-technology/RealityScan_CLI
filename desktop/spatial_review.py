"""Float64 track/density review; an explicit confirmation gate precedes batching."""
import numpy as np

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSplitter, QTableView, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from .review_widgets import LazyThumbnail, RecordTableModel


def track_segments(track, gap_distance=None):
    """Break missing samples and declared distance gaps; no guessed continuity."""
    if gap_distance is None:
        return []
    if not np.isfinite(gap_distance) or gap_distance <= 0:
        raise ValueError("Track gap distance must be finite and positive")
    segments, current = [], []
    for point in track:
        if point is None or len(point) < 2 or not np.isfinite(point[:2]).all():
            if len(current) > 1:
                segments.append(np.asarray(current, dtype=np.float64))
            current = []
            continue
        xy = np.asarray(point[:2], dtype=np.float64)
        if current and np.linalg.norm(xy - current[-1]) > gap_distance:
            if len(current) > 1:
                segments.append(np.asarray(current, dtype=np.float64))
            current = []
        current.append(xy)
    if len(current) > 1:
        segments.append(np.asarray(current, dtype=np.float64))
    return segments


class SpatialReview(QWidget):
    scan_requested = Signal(object)
    apply_requested = Signal(str, list)
    confirm_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.assessment_hash = None
        self.assessment = {}
        self._applied_exclusions = set()
        self.coordinates = np.empty((0, 2), dtype=np.float64)
        self.valid_rows = np.array([], dtype=int)
        self.invalid_count = 0
        self._colorbar = None
        layout = QVBoxLayout(self)
        self.summary = QLabel("Required before batching: inspect image density over the dive track, "
                              "review spatial outliers, then confirm the current assessment.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        self.scan_button = QPushButton("Build / refresh spatial review")
        self.scan_button.clicked.connect(lambda: self.scan_requested.emit(None))
        self.apply_button = QPushButton("Apply selected spatial culling…")
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(self.assessment_hash,
                                                                             sorted(self.model.selected_paths)))
        self.confirm_button = QPushButton("Confirm density review…")
        self.confirm_button.clicked.connect(lambda: self.confirm_requested.emit(self.assessment_hash))
        actions.addWidget(self.scan_button)
        actions.addWidget(self.apply_button)
        actions.addWidget(self.confirm_button)
        layout.addLayout(actions)
        toggles = QHBoxLayout()
        self.layers = {}
        for name in ("Kept", "Culled", "Outliers", "Density", "Track"):
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._draw)
            self.layers[name] = checkbox
            toggles.addWidget(checkbox)
        layout.addLayout(toggles)
        self.figure = Figure(facecolor="#121c2b", layout="constrained")
        self.axes = self.figure.add_subplot()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.mpl_connect("pick_event", self._picked)
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
        navigation_toolbar = NavigationToolbar2QT(self.canvas, self)
        navigation_toolbar.setStyleSheet("QToolButton { background:#cbd7e4; border:1px solid #8094ab; "
                                        "border-radius:4px; padding:3px; } QToolButton:hover { background:#eef5fc; }")
        layout.addWidget(navigation_toolbar)
        self.model = RecordTableModel([("Image", "path"), ("Camera", "camera"), ("UTC", "time"),
                                       ("Reason", "reason")], parent=self)
        self.model.decision_requested.connect(self._selection_changed)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().currentRowChanged.connect(self._preview)
        self.thumbnail = LazyThumbnail()
        bottom = QSplitter()
        bottom.addWidget(self.table)
        bottom.addWidget(self.thumbnail)
        bottom.setSizes([650, 250])
        splitter = QSplitter()
        from PySide6.QtCore import Qt
        splitter.setOrientation(Qt.Orientation.Vertical)
        splitter.addWidget(self.canvas)
        splitter.addWidget(bottom)
        splitter.setSizes([450, 230])
        layout.addWidget(splitter, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self._selection_changed()
        self._draw()

    def set_project(self, project):
        self.thumbnail.set_project(project)
        self.assessment_hash = None
        self.assessment = {}
        self._applied_exclusions = set()
        self.model.set_items([])
        self.coordinates = np.empty((0, 2), dtype=np.float64)
        self.valid_rows = np.array([], dtype=int)
        self.invalid_count = 0
        self._selection_changed()
        self._draw()

    def set_assessment(self, event):
        self.assessment = dict(event)
        self.assessment_hash = event.get("assessment_hash")
        self.model.set_items(event.get("points", []))
        self._applied_exclusions = set(event.get("spatial_excluded_paths", []))
        self.model.selected_paths = set(self._applied_exclusions)
        coordinates, rows = [], []
        for row, point in enumerate(self.model.items):
            try:
                xy = (float(point["x"]), float(point["y"]))
                if not np.isfinite(xy).all():
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            coordinates.append(xy)
            rows.append(row)
        self.coordinates = np.asarray(coordinates, dtype=np.float64).reshape(-1, 2)
        self.valid_rows = np.asarray(rows, dtype=int)
        self.invalid_count = len(self.model.items) - len(rows)
        self.summary.setText(f"{len(rows):,} located images · CRS {event.get('epsg', 'Unknown')} · "
                             f"{self.invalid_count:,} invalid positions. "
                             "Select a point to inspect its thumbnail; exclusion requires a separate explicit check.")
        self._selection_changed()
        self._draw()

    def _draw(self, *args):
        ax = self.axes
        if self._colorbar is not None:
            self._colorbar.remove()
            self._colorbar = None
        ax.clear()
        ax.set_facecolor("#0e1725")
        ax.tick_params(colors="#c6d4e5", labelsize=8)
        ax.xaxis.label.set_color("#c6d4e5")
        ax.yaxis.label.set_color("#c6d4e5")
        ax.set_xlabel("UTM Easting (m)")
        ax.set_ylabel("UTM Northing (m)")
        ax.ticklabel_format(style="plain", useOffset=False)
        ax.grid(alpha=0.15)
        if self.coordinates.size:
            excluded = np.array([self.model.items[row].get("excluded") is True for row in self.valid_rows])
            outliers = np.array([self.model.items[row].get("outlier") is True for row in self.valid_rows])
            if self.layers["Density"].isChecked() and np.count_nonzero(~excluded) > 1:
                xy = self.coordinates[~excluded]
                density = ax.hexbin(xy[:, 0], xy[:, 1], gridsize=45, mincnt=1, cmap="GnBu", alpha=0.55, linewidths=0)
                self._colorbar = self.figure.colorbar(density, ax=ax, fraction=0.04, pad=0.04)
                self._colorbar.set_label("Kept images per cell", color="#c6d4e5")
                self._colorbar.ax.tick_params(colors="#c6d4e5", labelsize=8)
            for label, selected, color, marker in (("Kept", ~excluded, "#50c8b4", "."),
                                                   ("Culled", excluded, "#a899c7", "x"),
                                                   ("Outliers", outliers, "#f4bb69", "o")):
                if self.layers[label].isChecked() and np.any(selected):
                    xy = self.coordinates[selected]
                    artist = ax.scatter(xy[:, 0], xy[:, 1], s=11 if label != "Outliers" else 27,
                                        c=color, marker=marker, alpha=0.8, picker=5, label=label,
                                        rasterized=True)
                    artist.review_rows = self.valid_rows[selected]
        if self.layers["Track"].isChecked():
            track = self.assessment.get("track", [])
            segments = self.assessment.get("track_segments")
            if segments is None:
                segments = track_segments(track, self.assessment.get("track_gap_distance"))
            for segment in segments:
                array = np.asarray(segment, dtype=np.float64)
                if array.ndim == 2 and array.shape[1] >= 2:
                    # NaNs break explicitly segmented tracks; never bridge missing coordinates.
                    array = np.where(np.isfinite(array[:, :2]), array[:, :2], np.nan)
                    ax.plot(array[:, 0], array[:, 1], color="#e4e8ef", linewidth=0.9, alpha=0.65)
            if track and not segments:
                valid = np.asarray([p[:2] for p in track if p is not None and len(p) >= 2
                                    and np.isfinite(p[:2]).all()], dtype=np.float64).reshape(-1, 2)
                if valid.size:
                    ax.scatter(valid[:, 0], valid[:, 1], color="#e4e8ef", s=2, alpha=0.5)
        ax.set_aspect("equal", adjustable="datalim")
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            legend = ax.legend(handles, labels, loc="upper right", facecolor="#203047", labelcolor="#e5ecf5")
            legend.get_frame().set_alpha(0.8)
        self.canvas.draw_idle()

    def _picked(self, event):
        rows = getattr(event.artist, "review_rows", None)
        if rows is not None and len(event.ind):
            row = int(rows[int(event.ind[0])])
            self.table.selectRow(row)
            self.table.scrollTo(self.model.index(row, 1))

    def _preview(self, index, previous):
        if index.isValid():
            point = self.model.items[index.row()]
            self.thumbnail.load_path(point["path"])
            self.message.setText(f"{point['path']} · {point.get('reason', '')}")

    @property
    def selection_dirty(self):
        return self.model.selected_paths != self._applied_exclusions

    def _selection_changed(self, *args):
        selected = len(self.model.selected_paths)
        self.apply_button.setEnabled(bool(self.assessment_hash) and self.selection_dirty)
        self.confirm_button.setEnabled(bool(self.assessment_hash) and not self.selection_dirty and not self.invalid_count)
        self.message.setText(f"{selected:,} spatial exclusions selected. Apply this replacement set before confirming density review."
                             if self.selection_dirty else f"{selected:,} applied spatial exclusions. Review the plot and confirm density review.")
