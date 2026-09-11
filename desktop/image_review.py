"""Read-only, allocation-guarded full-resolution review with scroll and zoom."""
from PySide6.QtCore import QRectF, Qt, QThreadPool
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from .review_widgets import _ThumbnailSignals, _ThumbnailTask, preview_path


class _ImageCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None

    def paintEvent(self, event):
        if self.image is not None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            # Paint into the clipped viewport without allocating a zoomed bitmap.
            painter.drawImage(QRectF(self.rect()), self.image)


class ImageReviewDialog(QDialog):
    def __init__(self, project, path, *, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1120, 900)
        self._generation = 0
        self._signals = _ThumbnailSignals(self)
        self._signals.ready.connect(self._loaded)
        layout = QVBoxLayout(self)
        help_text = QLabel("Temporal review: first / middle / last sampled frames. Original on the left; "
                           "red candidate exclusions on the right. Scroll or zoom to inspect each row. "
                           "Viewing this evidence does not select or approve masks.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        controls = QHBoxLayout()
        self.fit_button = QPushButton("Fit")
        self.actual_button = QPushButton("100%")
        self.zoom = QSpinBox()
        self.zoom.setRange(10, 400)
        self.zoom.setSuffix("%")
        self.zoom.setValue(100)
        self.zoom.valueChanged.connect(self._zoom)
        self.fit_button.clicked.connect(self._fit)
        self.actual_button.clicked.connect(lambda: self.zoom.setValue(100))
        for control in (self.fit_button, self.actual_button, self.zoom):
            controls.addWidget(control)
            control.setEnabled(False)
        controls.addStretch()
        layout.addLayout(controls)
        self.status = QLabel("Loading full-resolution review…")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.canvas = _ImageCanvas()
        self.scroll.setWidget(self.canvas)
        layout.addWidget(self.scroll, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.close)
        layout.addWidget(close)
        try:
            target = preview_path(project, path)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Preview unavailable: {exc}")
        else:
            self._generation += 1
            # QImageReader's allocation limit remains enabled and unchanged.
            QThreadPool.globalInstance().start(_ThumbnailTask(
                self._generation, str(target), self._signals, max_size=None))

    def _loaded(self, generation, image, error):
        if generation != self._generation:
            return
        if error or image is None or image.isNull():
            self.status.setText(f"Preview unavailable: {error or 'Image could not be decoded'}")
            return
        self.canvas.image = image
        for control in (self.fit_button, self.actual_button, self.zoom):
            control.setEnabled(True)
        self._fit()

    def _fit(self):
        image = self.canvas.image
        if image is None:
            return
        size = self.scroll.viewport().size()
        percent = int(100 * min(size.width() / image.width(), size.height() / image.height(), 1))
        self.zoom.setValue(max(10, percent))
        self._zoom(self.zoom.value())

    def _zoom(self, percent):
        image = self.canvas.image
        if image is None:
            return
        self.canvas.setFixedSize(max(1, round(image.width() * percent / 100)),
                                 max(1, round(image.height() * percent / 100)))
        self.canvas.update()
        self.status.setText(f"Read-only preview · {image.width():,} × {image.height():,} pixels · {percent}%")

    def closeEvent(self, event):
        self._generation += 1  # Ignore a late decode after this viewer is closed.
        self.canvas.image = None
        self.canvas.setFixedSize(0, 0)
        super().closeEvent(event)
