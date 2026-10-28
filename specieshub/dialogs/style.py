"""The few looks the dialogs share: the SpeciesHub blue, the two button
styles, a muted caption, and a spinner."""

from qgis.PyQt.QtCore import QTimer, Qt, QRectF
from qgis.PyQt.QtGui import QPainter, QPen, QColor, QPalette
from qgis.PyQt.QtWidgets import QWidget, QLabel

from ..compat import enum_value

BLUE = '#00639B'
BLUE_DARK = '#00517F'
# The blue as text or a thin line on a dark theme: #00639B is unreadable there
BLUE_ON_DARK = '#93CCFF'


def accent(widget):
    """The blue for text and lines on this widget's background."""
    window = widget.palette().color(enum_value(QPalette, 'ColorRole', 'Window'))
    return BLUE_ON_DARK if window.lightness() < 128 else BLUE


def primary(button):
    button.setStyleSheet('QPushButton { background: %s; color: white; border: none; border-radius: 6px; padding: 7px 18px; font-weight: 600; }'
                         'QPushButton:hover { background: %s; }'
                         'QPushButton:disabled { background: rgba(127, 127, 127, 0.3); }' % (BLUE, BLUE_DARK))


def secondary(button):
    button.setStyleSheet('QPushButton { border: 1px solid palette(mid); border-radius: 6px; padding: 7px 18px; background: palette(base); }'
                         'QPushButton:hover { background: palette(alternate-base); }')


def link(button):
    button.setFlat(True)
    button.setCursor(enum_value(Qt, 'CursorShape', 'PointingHandCursor'))
    button.setStyleSheet('QPushButton { color: %s; border: none; padding: 0 4px; }' % accent(button))


def caption(text=''):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet('color: palette(mid);')
    return label


class Spinner(QWidget):
    """An arc going round, in the theme's blue; runs only while shown."""

    def __init__(self, parent=None, size=32):
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._angle = (self._angle + 8) % 360
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(enum_value(QPainter, 'RenderHint', 'Antialiasing'))
        pen = QPen(QColor(accent(self)))
        pen.setWidth(3)
        pen.setCapStyle(enum_value(Qt, 'PenCapStyle', 'RoundCap'))
        painter.setPen(pen)
        rect = QRectF(3, 3, self.width() - 6, self.height() - 6)
        painter.drawArc(rect, int(-self._angle * 16), 110 * 16)
        painter.end()
