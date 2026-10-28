"""One headless QgsApplication for the tests, and the plugin root on sys.path."""

import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from qgis.core import QgsApplication  # noqa: E402

_app = None


def app():
    global _app
    if _app is None:
        _app = QgsApplication([], True)
        _app.initQgis()
    return _app
