"""Bounded, read-only raster preview. Original dtype, pixels and nodata stay intact."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)


@dataclass
class RasterPreview:
    path: str
    values: np.ma.MaskedArray
    metadata: dict
    minimum: float
    maximum: float


def read_raster(path, *, band=1, max_size=1024):
    """Read one bounded nearest-neighbor preview band through rasterio, read-only."""
    import rasterio
    from rasterio.enums import Resampling

    if not isinstance(max_size, int) or max_size < 1:
        raise ValueError("Preview size must be a positive integer")
    with rasterio.open(path, "r") as dataset:
        if not 1 <= band <= dataset.count:
            raise ValueError("Band is outside the raster's band range")
        scale = min(1.0, max_size / max(dataset.width, dataset.height))
        shape = (max(1, round(dataset.height * scale)), max(1, round(dataset.width * scale)))
        values = dataset.read(band, out_shape=shape, masked=True, resampling=Resampling.nearest)
        if np.iscomplexobj(values):
            raise ValueError("Complex raster bands are not supported")
        values = np.ma.masked_invalid(values)
        count = int(values.count())
        minimum, maximum = (float(values.min()), float(values.max())) if count else (0.0, 0.0)
        metadata = {"width": dataset.width, "height": dataset.height, "bands": dataset.count,
                    "band": band, "dtype": dataset.dtypes[band - 1], "crs": str(dataset.crs or "Not set"),
                    "nodata": dataset.nodatavals[band - 1], "bounds": tuple(dataset.bounds),
                    "units": dataset.units[band - 1] or "Unspecified", "preview_valid": count,
                    "preview_pixels": values.size}
    return RasterPreview(str(Path(path)), values, metadata, minimum, maximum)


def raster_rgba(preview, minimum=None, maximum=None):
    """Colorize a display copy; invalid pixels are transparent."""
    low = preview.minimum if minimum is None else float(minimum)
    high = preview.maximum if maximum is None else float(maximum)
    if not np.isfinite(low) or not np.isfinite(high) or high < low:
        raise ValueError("Display limits must be finite and maximum must be >= minimum")
    values = preview.values.astype(np.float64).filled(low)
    scale = max(abs(low), abs(high), 1.0)
    normalized = ((values / scale - low / scale) / (high / scale - low / scale)
                  if high != low else np.full(values.shape, 0.5))
    normalized = np.clip(normalized, 0.0, 1.0)
    stops = np.array([[19, 35, 73], [31, 112, 168], [51, 203, 181], [243, 220, 104]], dtype=float)
    rgba = np.empty(values.shape + (4,), dtype=np.uint8)
    for channel in range(3):
        rgba[..., channel] = np.interp(normalized, np.linspace(0, 1, len(stops)), stops[:, channel])
    rgba[..., 3] = np.where(np.ma.getmaskarray(preview.values), 0, 255)
    return rgba


class _Result(QObject):
    done = Signal(int, object, str)


class _ReadTask(QRunnable):
    def __init__(self, generation, path, signals):
        super().__init__()
        self.generation, self.path, self.signals = generation, path, signals

    def run(self):
        try:
            self.signals.done.emit(self.generation, read_raster(self.path), "")
        except Exception as exc:
            self.signals.done.emit(self.generation, None, str(exc))


class MapPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.preview = None
        self._pixmap = None
        self._generation = 0
        self._signals = _Result(self)
        self._signals.done.connect(self._loaded)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        browse = QPushButton("Open TIFF map…")
        browse.clicked.connect(self.choose_file)
        top.addWidget(browse)
        top.addWidget(QLabel("Read-only · nodata transparent · full float values retained"), 1)
        layout.addLayout(top)
        self.summary = QLabel("Open a float TIFF or GeoTIFF to inspect its map and metadata.")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.summary)
        self.image = QLabel("No map selected")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(250, 200)
        self.image.setStyleSheet("background: #0c1320; border: 1px solid #354157; border-radius: 8px;")
        layout.addWidget(self.image, 1)
        self.legend = QLabel()
        self.legend.setFixedHeight(14)
        self.legend.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #132349,"
                                 "stop:0.33 #1f70a8,stop:0.67 #33cbb5,stop:1 #f3dc68);")
        layout.addWidget(self.legend)
        row = QHBoxLayout()
        row.addWidget(QLabel("Display minimum"))
        self.minimum = QLineEdit()
        self.maximum = QLineEdit()
        row.addWidget(self.minimum)
        row.addWidget(QLabel("Maximum"))
        row.addWidget(self.maximum)
        apply = QPushButton("Set range")
        apply.clicked.connect(self.apply_range)
        row.addWidget(apply)
        auto = QPushButton("Auto range")
        auto.clicked.connect(self.auto_range)
        row.addWidget(auto)
        layout.addLayout(row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open map", "", "TIFF maps (*.tif *.tiff);;All files (*)")
        if path:
            self.load_path(path)

    def reset(self):
        self._generation += 1
        self.preview = None
        self._pixmap = None
        self.image.clear()
        self.image.setText("No map selected")
        self.summary.setText("Open a float TIFF or GeoTIFF to inspect its map and metadata.")
        self.minimum.clear()
        self.maximum.clear()
        self.message.clear()

    def load_path(self, path, *, asynchronous=True):
        self._generation += 1
        self.message.setText("Reading a bounded map preview…")
        if asynchronous:
            QThreadPool.globalInstance().start(_ReadTask(self._generation, path, self._signals))
        else:
            try:
                self._loaded(self._generation, read_raster(path), "")
            except Exception as exc:
                self._loaded(self._generation, None, str(exc))

    def _loaded(self, generation, preview, error):
        if generation != self._generation:
            return
        if error:
            self.message.setText(f"Cannot preview map: {error}")
            return
        self.preview = preview
        m = preview.metadata
        self.summary.setText(f"{preview.path}\n{m['width']:,} × {m['height']:,} pixels · "
                             f"{m['dtype']} · band {m['band']}/{m['bands']} · CRS {m['crs']}\n"
                             f"Nodata: {m['nodata']} · units: {m['units']} · bounds: {m['bounds']}")
        self.auto_range()

    def auto_range(self):
        if self.preview is None:
            return
        self.minimum.setText(repr(self.preview.minimum))
        self.maximum.setText(repr(self.preview.maximum))
        self.apply_range()

    def apply_range(self):
        if self.preview is None:
            return
        try:
            rgba = raster_rgba(self.preview, float(self.minimum.text()), float(self.maximum.text()))
            height, width = rgba.shape[:2]
            image = QImage(rgba.data, width, height, rgba.strides[0], QImage.Format.Format_RGBA8888).copy()
            self._pixmap = QPixmap.fromImage(image)
            self._scale()
            count = self.preview.metadata["preview_valid"]
            self.message.setText(f"{count:,} valid sampled pixels; range applies to preview only."
                                 if count else "No valid pixels: this band contains only nodata/nonfinite values.")
        except (ValueError, OverflowError) as exc:
            self.message.setText(str(exc))

    def _scale(self):
        if self._pixmap:
            self.image.setPixmap(self._pixmap.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale()
