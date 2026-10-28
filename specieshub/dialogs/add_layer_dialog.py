"""Add SpeciesHub data (Danas's mockup, 2026-10-28): What - load from,
observation type, species as chips; Where - area, save to; a running count
in the foot and a Load button that says how many sites. The load is one row
per observation, as the app's download lays the data out (2026-10-28)."""

import os

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.PyQt.QtCore import QTimer, QStringListModel, Qt, QRect, QSize, QPoint, pyqtSignal
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox, QPushButton,
                                 QLineEdit, QRadioButton, QButtonGroup, QCompleter, QMessageBox, QWidget, QFrame, QToolButton,
                                 QLayout, QFileDialog, QApplication)

from ..api import ApiError
from ..compat import enum_value
from ..model import LayerRequest, CONTAINER_ALL, CONTAINER_PRIVATE, CONTAINER_GROUP

SEARCH_DEBOUNCE_MS = 350
COUNT_DEBOUNCE_MS = 400
# The server's name search costs ~6 s for a three-letter prefix over 3.9M names
# and under a quarter of a second from four letters on (measured 2026-10-28)
MIN_SEARCH_CHARS = 4
DEFAULT_FILE = 'specieshub_observations.gpkg'
BLUE = '#00639B'


class FlowLayout(QLayout):
    """Qt's flow layout example: items wrap to the next line (the chips)."""

    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        try:
            return Qt.Orientation(0)        # Qt 6: a flag with nothing set
        except (TypeError, ValueError):
            return Qt.Orientations()        # Qt 5

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, False)
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, '_fit'):
            QTimer.singleShot(0, parent._fit)  # the box follows what was just laid out

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    # Items are gathered into lines first, so each can sit centred on its
    # line's height (a 26px chip beside an 18px field)
    def _arrange(self, rect, test_only):
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        lines, line, x = [], [], area.x()
        for item in self._items:
            width = item.sizeHint().width()
            if line and x + width > area.right() + 1:
                lines.append(line)
                line, x = [], area.x()
            line.append((item, x))
            x += width + self._spacing
        if line:
            lines.append(line)
        y = area.y()
        for line in lines:
            line_height = max(item.sizeHint().height() for item, _ in line)
            if not test_only:
                for item, item_x in line:
                    size = item.sizeHint()
                    item.setGeometry(QRect(QPoint(item_x, y + (line_height - size.height()) // 2), size))
            y += line_height + self._spacing
        return y - self._spacing - rect.y() + bottom if lines else bottom


class ChipInput(QFrame):
    """Chips with a x each and a text field after them, in one framed box."""

    changed = pyqtSignal()

    def __init__(self, placeholder, parent=None):
        super().__init__(parent)
        self.setObjectName('shChips')
        self.setStyleSheet('QFrame#shChips { border: 1px solid palette(mid); border-radius: 6px; background: palette(base); }'
                           'QFrame#shChips:focus-within { border-color: %s; }' % BLUE)
        self._names = []
        self._flow = FlowLayout(self, margin=6, spacing=6)
        self.edit = QLineEdit()
        self.edit.setFrame(False)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(160)
        self.edit.setStyleSheet('background: transparent;')
        self._flow.addWidget(self.edit)

    def names(self):
        return list(self._names)

    # The box grows with its rows: a form layout does not ask a frame for its
    # height at a width, so the frame sets its own
    def _fit(self):
        # measured at the width the layout really gets (inside the frame line),
        # or a field that just fits by a pixel wraps unseen below the box
        inner = self.contentsRect().width() if self.contentsRect().width() > 0 else self.width()
        frame = self.height() - self.contentsRect().height() if self.contentsRect().height() > 0 else 2
        self.setMinimumHeight(self._flow.heightForWidth(max(inner, 200)) + frame)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def add(self, name):
        name = str(name or '').strip()
        if not name or name in self._names:
            return
        self._names.append(name)
        # a pill: a tool button takes the radius where the native push button
        # on macOS keeps its own square look
        chip = QToolButton()
        chip.setText(name + '  \u00d7')
        chip.setFixedHeight(26)
        chip.setCursor(enum_value(Qt, 'CursorShape', 'PointingHandCursor'))
        chip.setToolTip('Remove %s' % name)
        # the font size named outright: macOS gives a 26px-high button its
        # "small" text size, and the chip must read like the field beside it
        chip.setStyleSheet('QToolButton { background: rgba(127, 127, 127, 0.16); border: 1px solid rgba(127, 127, 127, 0.16); '
                           'border-radius: 6px; padding: 0 8px; font-size: %dpt; }'
                           'QToolButton:hover { background: rgba(127, 127, 127, 0.3); }' % max(self.edit.fontInfo().pointSize(), 9))
        chip.clicked.connect(lambda _=False, n=name, c=chip: self._remove(n, c))
        # the field stays last: the chip goes in before it
        self._flow.takeAt(self._flow.count() - 1)
        self._flow.addWidget(chip)
        self._flow.addWidget(self.edit)
        # a widget not yet shown counts as empty in the layout: show it now,
        # and measure once the event loop has placed it
        if self.isVisible():
            chip.show()
        self._flow.invalidate()
        QTimer.singleShot(0, self._fit)
        self.changed.emit()

    def _remove(self, name, chip):
        if name in self._names:
            self._names.remove(name)
        self._flow.removeWidget(chip)
        chip.deleteLater()
        self._flow.invalidate()
        QTimer.singleShot(0, self._fit)
        self.changed.emit()


def _section(text):
    label = QLabel(text.upper())
    label.setStyleSheet('color: palette(mid); font-weight: 600; letter-spacing: 1px; font-size: 12px; padding-top: 6px;')
    return label


class AddLayerDialog(QDialog):

    def __init__(self, client, settings, iface=None, parent=None):
        super().__init__(parent)
        self.client = client
        self.settings = settings
        self.iface = iface
        self.request = None
        self.path = ''
        self.layer_name = ''
        self._search_serial = 0   # answers to an older search are dropped
        self._count_serial = 0
        self.total = None
        self.setWindowTitle('Add SpeciesHub data')
        self.setMinimumWidth(620)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._search)
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(COUNT_DEBOUNCE_MS)
        self._count_timer.timeout.connect(self._count)
        self._build()

    # -- layout ------------------------------------------------------------

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 20)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setLabelAlignment(enum_value(Qt, 'AlignmentFlag', 'AlignLeft'))

        form.addRow(_section('What'))

        self.container = QComboBox()
        self.container.addItem('All my data', (CONTAINER_ALL, ''))
        self.container.addItem('My private data', (CONTAINER_PRIVATE, ''))
        self.container.currentIndexChanged.connect(self._schedule_count)
        form.addRow('Load from', self.container)

        self.obs_type = QComboBox()
        self.obs_type.addItem('Any observation type', '')
        self.obs_type.setToolTip('The observation types your data holds')
        self.obs_type.currentIndexChanged.connect(self._schedule_count)
        form.addRow('Observation type', self.obs_type)

        species_box = QWidget()
        species_layout = QVBoxLayout(species_box)
        species_layout.setContentsMargins(0, 0, 0, 0)
        species_layout.setSpacing(4)
        self.chips = ChipInput('Add species...')
        self.chips.changed.connect(self._schedule_count)
        self.species_edit = self.chips.edit
        self._model = QStringListModel(self)
        completer = QCompleter(self._model, self)
        completer.setCompletionMode(enum_value(QCompleter, 'CompletionMode', 'UnfilteredPopupCompletion'))
        completer.setCaseSensitivity(enum_value(Qt, 'CaseSensitivity', 'CaseInsensitive'))
        completer.activated.connect(self._add_species_name)
        self.species_edit.setCompleter(completer)
        self.species_edit.textEdited.connect(self._on_species_typed)
        self.species_edit.returnPressed.connect(lambda: self._add_species_name(self.species_edit.text()))
        species_layout.addWidget(self.chips)
        self.search_hint = QLabel('Type %d+ letters of the scientific name. Leave empty for all species.' % MIN_SEARCH_CHARS)
        self.search_hint.setStyleSheet('color: palette(mid);')
        species_layout.addWidget(self.search_hint)
        form.addRow('Species', species_box)

        form.addRow(_section('Where'))
        area = QWidget()
        area_layout = QHBoxLayout(area)
        area_layout.setContentsMargins(0, 0, 0, 0)
        self.area_all = QRadioButton('Everywhere')
        self.area_extent = QRadioButton('Current map extent')
        self.area_all.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.area_all)
        group.addButton(self.area_extent)
        self.area_extent.toggled.connect(self._schedule_count)
        area_layout.addWidget(self.area_all)
        area_layout.addWidget(self.area_extent)
        area_layout.addStretch()
        form.addRow('Area', area)

        save = QWidget()
        save_layout = QHBoxLayout(save)
        save_layout.setContentsMargins(0, 0, 0, 0)
        self.file = QLineEdit()
        start_dir = self.settings.output_dir or os.path.expanduser('~')
        self.file.setText(os.path.join(start_dir, DEFAULT_FILE))
        self.file.setToolTip('A GeoPackage. A layer of the same name in it is replaced.')
        browse = QPushButton('Browse...')
        browse.clicked.connect(self._browse)
        save_layout.addWidget(self.file, 1)
        save_layout.addWidget(browse)
        form.addRow('Save to', save)
        layout.addLayout(form)
        layout.addStretch()
        layout.addSpacing(20)

        foot = QHBoxLayout()
        self.count_label = QLabel('')
        self.count_label.setStyleSheet('color: palette(mid);')
        self.recount = QPushButton('Recount')
        self.recount.setFlat(True)
        self.recount.setCursor(enum_value(Qt, 'CursorShape', 'PointingHandCursor'))
        self.recount.setStyleSheet('QPushButton { color: %s; border: none; padding: 0 6px; }' % BLUE)
        self.recount.clicked.connect(self._count)
        foot.addWidget(self.count_label)
        foot.addWidget(self.recount)
        foot.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        self.load = QPushButton('Load')
        self.load.setDefault(True)
        self.load.setStyleSheet('QPushButton { background: %s; color: white; border: none; border-radius: 6px; padding: 7px 18px; font-weight: 600; }'
                                'QPushButton:hover { background: #00517F; }'
                                'QPushButton:disabled { background: rgba(127, 127, 127, 0.3); }' % BLUE)
        self.load.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(self.load)
        layout.addLayout(foot)

    def load_reference_lists(self):
        """Groups and the observation types the account holds; call once after construction."""
        QApplication.setOverrideCursor(enum_value(Qt, 'CursorShape', 'WaitCursor'))
        try:
            # "Group one (12,345 observations)": the group list carries its count
            for group in self.client.user_groups():
                name = str(group.get('name') or '')
                if not name:
                    continue
                count = group.get('observationCount')
                label = name if count is None else '%s (%s observation%s)' % (name, format(int(count), ','), '' if int(count) == 1 else 's')
                self.container.addItem(label, (CONTAINER_GROUP, name))
            for name in self._type_names():
                self.obs_type.addItem(name, name)
        finally:
            QApplication.restoreOverrideCursor()
        self._schedule_count()

    # The account's own types from the search vocabulary (the words the app's
    # search box offers); every type there is when the vocabulary is still
    # being built (503)
    def _type_names(self):
        try:
            names = (self.client.vocabulary() or {}).get('types') or []
            if names:
                return [str(n) for n in names]
        except ApiError:
            pass
        return sorted({str(t.get('name') or '') for t in self.client.obs_types()} - {''})

    # -- species -----------------------------------------------------------

    def _on_species_typed(self, text):
        if len(text.strip()) < MIN_SEARCH_CHARS:
            self._search_timer.stop()
            return
        self._search_timer.start()

    def _search(self):
        term = self.species_edit.text().strip()
        if len(term) < MIN_SEARCH_CHARS:
            return
        self._search_serial += 1
        serial = self._search_serial

        def done(found, error):
            if serial != self._search_serial:
                return  # a newer search is out
            if error is not None:
                self.search_hint.setText('The search did not answer: %s' % error)
                return
            names = []
            for item in found or []:
                name = str(item.get('species') or '')
                if name and name not in names:
                    names.append(name)
            self._model.setStringList(names)
            if names:
                self.species_edit.completer().complete()

        self.client.search_species_async(term, done)

    def _add_species_name(self, name):
        name = str(name or '').strip()
        if not name:
            return
        self.chips.add(name)
        # the completer writes its pick into the field after this signal: clear after it
        QTimer.singleShot(0, self.species_edit.clear)

    def _species_names(self):
        return self.chips.names()

    # -- request and count -------------------------------------------------

    def _bbox(self):
        if not self.area_extent.isChecked() or self.iface is None:
            return None
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        source = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if source != wgs84:
            extent = QgsCoordinateTransform(source, wgs84, QgsProject.instance()).transformBoundingBox(extent)
        return {'south': extent.yMinimum(), 'north': extent.yMaximum(), 'west': extent.xMinimum(), 'east': extent.xMaximum()}

    def _build_request(self, field_labels=None):
        container, group_name = self.container.currentData()
        return LayerRequest(container=container, group_name=group_name, species=self._species_names(),
                            obs_type=self.obs_type.currentData() or '', bbox=self._bbox(),
                            field_labels=list(field_labels or []))

    # The labels (and order) of every defined field, for the recorded fields'
    # columns the load adds; which fields get a column is the data's say
    def _field_labels(self):
        ids = [str(t.get('_id') or t.get('id') or '') for t in self.client.obs_types()]
        fields, seen = [], set()
        for item in self.client.obs_type_fields([i for i in ids if i]):
            name = str(item.get('name') or '')
            if not name or name in seen:
                continue
            seen.add(name)
            fields.append([name, str(item.get('label') or name)])
        return fields

    def _schedule_count(self, *_):
        self.total = None
        self.count_label.setText('Counting...')
        self.load.setText('Load')
        self.load.setEnabled(True)
        self._count_timer.start()

    # The count runs on its own after every change (debounced) and on Recount;
    # the foot and the Load button say the number, "more than" at the server's cap
    def _count(self):
        self._count_timer.stop()
        self._count_serial += 1
        serial = self._count_serial
        self.count_label.setText('Counting...')
        request = self._build_request()

        def done(page, error):
            if serial != self._count_serial:
                return
            if error is not None:
                self.count_label.setText('Could not count: %s' % error)
                self.load.setText('Load')
                return
            total = (page or {}).get('total')
            self.total = total
            if total is None:
                self.count_label.setText('The server could not count the matches in time.')
                self.load.setText('Load')
            elif page.get('totalCapped'):
                self.count_label.setText('More than %s sites match' % format(int(total), ','))
                self.load.setText('Load %s+ sites' % format(int(total), ','))
            else:
                self.count_label.setText('%s site%s match' % (format(int(total), ','), '' if int(total) == 1 else 's'))
                self.load.setText('Load %s site%s' % (format(int(total), ','), '' if int(total) == 1 else 's'))
            self.load.setEnabled(total is None or int(total) > 0)  # nothing to load is not a button

        self.client.query_sites_async(request.body(limit=1), done)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save to', self.file.text().strip() or os.path.expanduser('~'), 'GeoPackage (*.gpkg)')
        if path:
            self.file.setText(path)

    def accept(self):
        QApplication.setOverrideCursor(enum_value(Qt, 'CursorShape', 'WaitCursor'))
        try:
            field_labels = self._field_labels()
        except ApiError as e:
            QMessageBox.warning(self, 'SpeciesHub', 'The field list could not be read: %s' % e)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.request = self._build_request(field_labels)
        self.layer_name = self.request.label()
        self.path = self.file.text().strip()
        if not self.path:
            QMessageBox.information(self, 'SpeciesHub', 'Choose a GeoPackage file to save to.')
            return
        if not self.path.lower().endswith('.gpkg'):
            self.path += '.gpkg'
        self.settings.output_dir = os.path.dirname(self.path)
        super().accept()
