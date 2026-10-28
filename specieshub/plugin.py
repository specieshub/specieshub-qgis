"""Menu, toolbar, the hand-off to the background loader, and the layer the
load ends in (style, "Open in SpeciesHub" action, remembered request)."""

import os

from qgis.core import (Qgis, QgsApplication, QgsProject, QgsVectorLayer, QgsMarkerSymbol, QgsSingleSymbolRenderer,
                       QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling, QgsAction, QgsProviderRegistry)
from qgis.PyQt.QtGui import QIcon
try:
    from qgis.PyQt.QtGui import QAction      # Qt 6
except ImportError:
    from qgis.PyQt.QtWidgets import QAction  # Qt 5

from . import auth
from .api import ApiClient, ApiError, AuthError
from .compat import enum_value
from .dialogs.about_dialog import AboutDialog
from .dialogs.add_layer_dialog import AddLayerDialog
from .dialogs.connect_dialog import ConnectDialog
from .loader import LoadTask
from .model import LayerRequest, REQUEST_PROPERTY, SERVER_PROPERTY, COLUMN_NAMES, field_name
from .settings import Settings

PLUGIN_DIR = os.path.dirname(__file__)
MENU = '&SpeciesHub'


class SpeciesHubPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.settings = Settings()
        self.actions = []
        self.toolbar = None
        self._tasks = []  # keeps running tasks alive

    # -- QGIS plugin interface ----------------------------------------------

    def initGui(self):
        icon = QIcon(os.path.join(PLUGIN_DIR, 'resources', 'icon.svg'))
        self.toolbar = self.iface.addToolBar('SpeciesHub')
        self.toolbar.setObjectName('SpeciesHubToolbar')
        # The logo sits on the toolbar button and on the submenu; the menu item
        # is text. macOS shows a menu action's icon whatever
        # setIconVisibleInMenu says, so the toolbar gets an action of its own.
        self._add_action(None, 'Add data...', self.add_layer)
        self.toolbar_action = QAction(icon, 'Add data...', self.iface.mainWindow())
        self.toolbar_action.triggered.connect(self.add_layer)
        self.toolbar.addAction(self.toolbar_action)
        self._add_action(None, 'Refresh layer', self.refresh_layer)
        # One item for the connection: "Sign in..." until there is one, then
        # who is signed in (the dialog behind it holds Disconnect)
        self.account_action = self._add_action(None, 'Sign in...', self.connect)
        self._add_action(None, 'About SpeciesHub', self.about)
        menu = self._plugin_menu()
        if menu is not None:
            menu.setIcon(icon)
            menu.aboutToShow.connect(self._refresh_account_action)
        self._refresh_account_action()

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(MENU, action)
            if self.toolbar is not None:
                self.toolbar.removeAction(action)
        self.actions = []
        if self.toolbar is not None:
            self.toolbar.deleteLater()
            self.toolbar = None
        self.toolbar_action = None

    # QGIS builds the submenu named MENU inside the Plugins menu on the first
    # addPluginToMenu; found by title (QGIS may keep or drop the '&') so the
    # logo can go on it
    def _plugin_menu(self):
        plugins_menu = self.iface.pluginMenu() if hasattr(self.iface, 'pluginMenu') else None
        if plugins_menu is None:
            return None
        wanted = MENU.replace('&', '')
        for action in plugins_menu.actions():
            if action.menu() is not None and action.menu().title().replace('&', '') == wanted:
                return action.menu()
        return None

    def _refresh_account_action(self):
        if self.settings.is_connected() and auth.token_exists(self.settings.authcfg):
            who = self.settings.user_name or self.settings.user_email or self.settings.server_url
            self.account_action.setText('Signed in as %s' % who)
        else:
            self.account_action.setText('Sign in...')

    def _add_action(self, icon, text, slot, toolbar=False):
        action = QAction(icon, text, self.iface.mainWindow()) if icon is not None else QAction(text, self.iface.mainWindow())
        action.triggered.connect(slot)
        self.iface.addPluginToMenu(MENU, action)
        if toolbar and self.toolbar is not None:
            self.toolbar.addAction(action)
        self.actions.append(action)
        return action

    # -- commands -----------------------------------------------------------

    def connect(self):
        ConnectDialog(self.settings, self.iface.mainWindow()).exec()
        self._refresh_account_action()

    def about(self):
        AboutDialog(self.settings, self.iface.mainWindow()).exec()
        self._refresh_account_action()  # the card can sign in or out

    def add_layer(self):
        if not self._ensure_connected():
            return
        dialog = AddLayerDialog(self._client(), self.settings, self.iface, self.iface.mainWindow())
        try:
            dialog.load_reference_lists()
        except AuthError as e:
            self._message(str(e), 'warning')
            self.connect()
            return
        except ApiError as e:
            self._message(str(e), 'critical')
            return
        if not dialog.exec():
            return
        self._start(dialog.request, dialog.path, dialog.layer_name)

    def refresh_layer(self):
        layer = self.iface.activeLayer()
        stored = layer.customProperty(REQUEST_PROPERTY) if layer is not None else None
        if not stored:
            self._message('Select a SpeciesHub layer first.', 'info')
            return
        parts = QgsProviderRegistry.instance().decodeUri('ogr', layer.source())
        path, layer_name = parts.get('path') or '', parts.get('layerName') or layer.name()
        if not path:
            self._message('The layer file could not be found.', 'warning')
            return
        if not self._ensure_connected():
            return
        self._start(LayerRequest.from_json(str(stored)), path, layer_name, existing=layer)

    # -- loading ------------------------------------------------------------

    def _start(self, request, path, layer_name, existing=None):
        task = LoadTask(self.settings.server_url, self.settings.authcfg, self.settings.locale, request, path, layer_name,
                        on_done=lambda t, ok: self._done(t, ok, existing), vernacular=self.settings.vernacular)
        self._tasks.append(task)
        QgsApplication.taskManager().addTask(task)
        self._message('Loading %s ...' % layer_name, 'info')

    def _done(self, task, ok, existing):
        if task in self._tasks:
            self._tasks.remove(task)
        if not ok:
            if task.isCanceled():
                self._message('Loading cancelled.', 'warning')
            else:
                self._message(task.error or 'Loading failed.', 'critical')
            return
        if existing is not None:
            existing.dataProvider().reloadData()
            existing.triggerRepaint()
            self._message('%s refreshed: %s observations.' % (existing.name(), format(task.count, ',')), 'success')
            return
        layer = QgsVectorLayer('%s|layername=%s' % (task.path, task.layer_name), task.layer_name, 'ogr')
        if not layer.isValid():
            self._message('The loaded layer could not be opened.', 'critical')
            return
        style_layer(layer)
        alias_recorded_fields(layer, task.request)
        layer.setCustomProperty(REQUEST_PROPERTY, task.request.to_json())
        layer.setCustomProperty(SERVER_PROPERTY, task.server_url)
        QgsProject.instance().addMapLayer(layer)
        self._message('%s observations loaded.' % format(task.count, ','), 'success')

    # -- helpers ------------------------------------------------------------

    def _client(self):
        return ApiClient(self.settings.server_url, self.settings.authcfg, self.settings.locale,
                         vernacular=self.settings.vernacular)

    def _ensure_connected(self):
        if self.settings.is_connected() and auth.token_exists(self.settings.authcfg):
            if not self.settings.has_profile():
                # a sign-in from before the plugin kept the account's language: read it once
                try:
                    self.settings.remember_profile(self._client().profile())
                except ApiError:
                    pass
            return True
        self.settings.clear_connection()
        self.connect()
        return self.settings.is_connected()

    def _message(self, text, level):
        bar = self.iface.messageBar()
        levels = {'info': 'Info', 'success': 'Success', 'warning': 'Warning', 'critical': 'Critical'}
        bar.pushMessage('SpeciesHub', text, enum_value(Qgis, 'MessageLevel', levels[level]), 8)


def alias_recorded_fields(layer, request):
    """The recorded fields' columns show the form's label in the attribute
    table; the column itself keeps the field's name for expressions."""
    labels = {str(name): str(label) for name, label in request.field_labels if label}
    for index, field in enumerate(layer.fields()):
        column = field.name()
        if column in COLUMN_NAMES or column == 'fid':
            continue
        label = labels.get(field_name(column))
        if label and label != column:
            layer.setFieldAlias(index, label)


def style_layer(layer):
    """Green points with a white rim, species labels when zoomed in, and the
    "Open in SpeciesHub" action on the url field."""
    symbol = QgsMarkerSymbol.createSimple({'name': 'circle', 'color': '#2e7d32', 'outline_color': '#ffffff',
                                           'outline_width': '0.4', 'size': '2.6'})
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))

    labels = QgsPalLayerSettings()
    labels.fieldName = 'species'
    labels.enabled = True
    text = QgsTextFormat()
    text.setSize(9)
    labels.setFormat(text)
    labels.scaleVisibility = True
    labels.minimumScale = 50000
    labels.maximumScale = 0
    try:
        labels.placement = enum_value(Qgis, 'LabelPlacement', 'AroundPoint')
    except AttributeError:
        labels.placement = QgsPalLayerSettings.AroundPoint
    layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
    layer.setLabelsEnabled(True)

    action = QgsAction(enum_value(QgsAction, 'ActionType', 'OpenUrl'), 'Open in SpeciesHub', '[% "url" %]', False)
    layer.actions().addAction(action)
