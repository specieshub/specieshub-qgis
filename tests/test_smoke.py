"""Imports every module and opens both dialogs offscreen with a fake client,
so a Qt 5 / Qt 6 enum or signature mistake fails here, not inside QGIS."""

import tempfile
import unittest

import qgis_env

from qgis.core import QgsVectorLayer


class FakeClient:
    def user_groups(self):
        return [{'id': '1', 'name': 'Group one', 'observationCount': 12345}, {'id': '2', 'name': 'Group two'}]

    def vocabulary(self):
        return {'types': ['Nest', 'Singing male']}

    def obs_types(self):
        return [{'_id': 't1', 'name': 'Nest'}, {'_id': 't2', 'name': 'Singing male'}, {'_id': 't3', 'name': 'Unused'}]

    def obs_type_fields(self, type_ids):
        self.last_type_ids = list(type_ids)
        rows = {'t1': [{'name': 'nest_height', 'label': 'Nest height'}, {'name': 'notes', 'label': 'Notes'}],
                't2': [{'name': 'nest_height', 'label': 'Nest height'}, {'name': 'song_type', 'label': 'Song type'}]}
        return [row for type_id in type_ids for row in rows.get(type_id, [])]


    def search_species_async(self, term, on_done):
        on_done([{'species': 'Parus major'}, {'species': 'Parus minor'}], None)

    def query(self, path, body):
        return {'rows': [], 'total': 12, 'totalCapped': False, 'hasMore': False, 'nextCursor': None}

    def query_sites_async(self, body, on_done):
        self.last_body = body
        on_done(self.query('/api/sites/query', body), None)


class FakeIface:
    """What initGui touches of QgisInterface: the Web menu, a toolbar, the window."""

    def __init__(self):
        from qgis.PyQt.QtWidgets import QMenu, QToolBar
        self.plugins_menu = QMenu('Plu&gins')
        self.toolbar = QToolBar('SpeciesHub')

    def mainWindow(self):
        return None

    def pluginMenu(self):
        return self.plugins_menu

    def addToolBar(self, name):
        return self.toolbar

    # as QGIS does it: the submenu is created on the first action, by its clean name
    def addPluginToMenu(self, name, action):
        for existing in self.plugins_menu.actions():
            if existing.menu() is not None and existing.menu().title().replace('&', '') == name.replace('&', ''):
                existing.menu().addAction(action)
                return
        submenu = self.plugins_menu.addMenu(name.replace('&', ''))
        submenu.addAction(action)

    def removePluginMenu(self, name, action):
        pass


class SmokeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        qgis_env.app()

    def test_modules_import(self):
        from specieshub import plugin, loader, api, auth, model, settings  # noqa: F401
        self.assertTrue(callable(plugin.SpeciesHubPlugin))

    def test_menu_has_logo_and_the_four_items(self):
        from specieshub.plugin import SpeciesHubPlugin
        iface = FakeIface()
        plugin = SpeciesHubPlugin(iface)
        plugin.initGui()
        submenu = plugin._plugin_menu()
        self.assertIsNotNone(submenu)
        self.assertFalse(submenu.icon().isNull())
        self.assertEqual([a.text() for a in submenu.actions()], ['Add data...', 'Refresh layer', 'Sign in...', 'About SpeciesHub'])
        self.assertTrue(submenu.actions()[0].icon().isNull())  # text only in the menu
        self.assertEqual(len(iface.toolbar.actions()), 1)
        self.assertFalse(iface.toolbar.actions()[0].icon().isNull())  # the toolbar button has the logo
        plugin.unload()

    def test_about_dialog_has_logo_version_and_slogan(self):
        from qgis.PyQt.QtWidgets import QLabel
        from specieshub.dialogs.about_dialog import AboutDialog, plugin_version
        from specieshub.settings import Settings
        dialog = AboutDialog(Settings())
        self.assertEqual(plugin_version(), '0.1.0')
        texts = ' '.join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn('Official plugin for QGIS', texts)
        self.assertIn('Home for biodiversity data', texts)
        self.assertIn('Version 0.1.0', texts)
        self.assertEqual(dialog.card_title.text(), 'Not connected')
        self.assertEqual(dialog.card_button.text(), 'Sign in')
        dialog.close()

    def test_delete_reaches_the_network_layer(self):
        # the DELETE signature differs between QGIS versions; a refused
        # connection proves the call itself is accepted
        from specieshub.api import ApiClient, ApiError
        with self.assertRaises(ApiError):
            ApiClient('http://127.0.0.1:1').delete('/api/profile/tokens/current')

    def test_language_params_follow_the_app(self):
        from specieshub.api import ApiClient
        self.assertEqual(ApiClient('https://x')._lang(), {})
        self.assertEqual(ApiClient('https://x', locale='lt', vernacular='lt')._lang(),
                         {'locale': 'lt', 'vernacularLanguage': 'lt'})
        self.assertEqual(ApiClient('https://x', vernacular='de')._lang(), {'vernacularLanguage': 'de'})

    def test_languages_come_from_the_account(self):
        from specieshub.settings import Settings
        s = Settings()
        s.remember_profile({'vernacularLanguage': 'lt', 'uiLanguage': 'lt-LT'})
        self.assertEqual((s.vernacular, s.locale), ('lt', 'lt-LT'))
        s.remember_profile({'vernacularLanguage': 'de', 'uiLanguage': 'en-US'})
        self.assertEqual((s.vernacular, s.locale), ('de', ''))
        s.remember_profile({})
        self.assertEqual(s.vernacular, s.qgis_language())
        s.clear_connection()

    def test_auth_method_is_available_in_this_qgis(self):
        from specieshub import auth
        self.assertTrue(auth.method_available())

    def test_connect_dialog_opens(self):
        from specieshub.dialogs.connect_dialog import ConnectDialog
        from specieshub.settings import Settings
        dialog = ConnectDialog(Settings())
        self.assertEqual(dialog.windowTitle(), 'SpeciesHub account')
        self.assertEqual(dialog.state(), 'signin')
        dialog.close()

    def test_pairing_resolves_a_relative_url_and_finishes_on_ok(self):
        from unittest import mock
        from specieshub.dialogs import connect_dialog
        from specieshub.settings import Settings
        answers = iter([{'status': 'pending'}, {'status': 'ok', 'token': 'shp_x', 'user': {'name': 'D', 'email': 'd@x'}}])

        class FakeApi:
            def __init__(self, *args, **kwargs):
                pass

            def pair_start(self):
                return {'deviceCode': 'dev', 'userCode': 'AB12-CD34', 'url': '/connect/AB12-CD34', 'interval': 2, 'expiresIn': 600}

            def pair_poll(self, device_code):
                assert device_code == 'dev'
                return next(answers)

        opened, finished = [], []
        with mock.patch.object(connect_dialog, 'ApiClient', FakeApi), \
             mock.patch.object(connect_dialog.ConnectDialog, '_open_browser', staticmethod(lambda url: opened.append(url) or 'opened by Qt')):
            dialog = connect_dialog.ConnectDialog(Settings())
            dialog._select_server('https://test.specieshub.io')
            dialog._finish = lambda url, token, user: finished.append((url, token, user))
            dialog._start_pairing()
            self.assertEqual(opened, ['https://test.specieshub.io/connect/AB12-CD34'])
            self.assertEqual(dialog.state(), 'waiting')
            self.assertIn('test.specieshub.io', dialog.waiting_text.text())
            self.assertIn('AB12-CD34', dialog.pairing.text())
            self.assertEqual(dialog._open_url, 'https://test.specieshub.io/connect/AB12-CD34')
            self.assertTrue(dialog._timer.isActive())
            dialog._poll()
            self.assertIn('last answer: pending', dialog.pairing.text())
            dialog._poll()
            self.assertEqual(finished, [('https://test.specieshub.io', 'shp_x', {'name': 'D', 'email': 'd@x'})])
            self.assertFalse(dialog._timer.isActive())
            dialog._stop_pairing('declined')
            self.assertEqual(dialog.state(), 'signin')
            self.assertEqual(dialog.signin_error.text(), 'declined')
            dialog.close()

    def test_add_layer_dialog_lists_groups_and_counts(self):
        from specieshub.dialogs.add_layer_dialog import AddLayerDialog
        from specieshub.settings import Settings
        from specieshub.model import CONTAINER_GROUP
        client = FakeClient()
        dialog = AddLayerDialog(client, Settings())
        dialog.load_reference_lists()
        dialog.show()  # lays the chips out: the flow layout's methods run
        self.assertEqual(dialog.container.count(), 4)
        self.assertEqual(dialog.container.itemData(2), (CONTAINER_GROUP, 'Group one'))
        self.assertEqual(dialog.container.itemText(2), 'Group one (12,345 observations)')
        self.assertEqual(dialog.container.itemText(3), 'Group two')
        self.assertEqual([dialog.obs_type.itemText(i) for i in range(dialog.obs_type.count())], ['Any observation type', 'Nest', 'Singing male'])
        dialog.species_edit.setText('Parus')
        dialog._search()
        self.assertEqual(dialog._model.stringList(), ['Parus major', 'Parus minor'])
        dialog._add_species_name('Parus major')
        dialog._add_species_name('Parus major')
        dialog._add_species_name('Sitta europaea')
        self.assertEqual(dialog._species_names(), ['Parus major', 'Sitta europaea'])
        from qgis.PyQt.QtWidgets import QToolButton
        dialog.chips._remove('Sitta europaea', dialog.chips.findChildren(QToolButton)[-1])
        self.assertEqual(dialog._species_names(), ['Parus major'])
        dialog._count()
        self.assertEqual(dialog.count_label.text(), '12 sites match')
        self.assertEqual(dialog.load.text(), 'Load 12 sites')
        self.assertEqual(client.last_body['limit'], 1)
        dialog.obs_type.setCurrentIndex(1)
        self.assertEqual(dialog._build_request().filters()[-1], {'type': 'types', 'values': ['Nest']})
        dialog.file.setText('/tmp/x')
        dialog.accept()
        self.assertEqual(dialog.request.species, ['Parus major'])
        self.assertEqual(dialog.path, '/tmp/x.gpkg')
        # the labels of every type's fields travel with the request, each field once
        self.assertEqual(client.last_type_ids, ['t1', 't2', 't3'])
        self.assertEqual(dialog.request.field_labels, [['nest_height', 'Nest height'], ['notes', 'Notes'], ['song_type', 'Song type']])
        self.assertEqual(dialog.layer_name, 'SpeciesHub - All data - Parus major - Nest')
        dialog.close()

    def test_gpkg_writer_recorded_columns_and_style(self):
        from specieshub import model
        from specieshub.loader import LoadTask
        from specieshub.plugin import style_layer, alias_recorded_fields
        path = tempfile.mktemp(suffix='.gpkg')
        request = model.LayerRequest(field_labels=[['song_type', 'Song type'], ['nest_height', 'Nest height'], ['unused', 'Unused']])
        task = LoadTask('https://x', '', '', request, path, 'sites')
        writer = task._open_writer()
        rows = model.features_from_row({'id': 'abc', 'species': 'Parus major', 'geojson': {'coordinates': [25.0, 54.0]},
                                        'observations': [{'id': 'o1', 'date': '2026-01-01', 'data': {'nest_height': '4', 'notes': 'inner'}},
                                                         {'id': 'o2', 'data': {'song_type': 'full', 'old_field': 'x'}},
                                                         {'id': 'o3'}]},
                                       task.fields, 'https://x')
        for feature, recorded in rows:
            if recorded:
                task.recorded[feature['observation_id']] = recorded
        self.assertTrue(writer.addFeatures([feature for feature, _ in rows]))
        del writer
        # the columns the data asks for: the forms' order, then the undefined ones
        task._add_recorded_columns()
        self.assertEqual(task.columns, ['song_type', 'nest_height', 'field_notes', 'old_field'])
        layer = QgsVectorLayer(path + '|layername=sites', 'sites', 'ogr')
        self.assertTrue(layer.isValid())
        self.assertEqual(layer.featureCount(), 3)
        by_id = {f['observation_id']: f for f in layer.getFeatures()}
        self.assertEqual((by_id['o1']['nest_height'], by_id['o1']['field_notes'], by_id['o1']['song_type']), ('4', 'inner', None))
        self.assertEqual((by_id['o2']['song_type'], by_id['o2']['old_field']), ('full', 'x'))
        self.assertEqual(by_id['o3']['nest_height'], None)
        self.assertEqual(next(layer.getFeatures())['species'], 'Parus major')
        style_layer(layer)
        alias_recorded_fields(layer, request)
        fields = layer.fields()
        self.assertEqual(layer.attributeAlias(fields.indexOf('song_type')), 'Song type')
        self.assertEqual(layer.attributeAlias(fields.indexOf('nest_height')), 'Nest height')
        self.assertEqual(layer.attributeAlias(fields.indexOf('old_field')), '')
        self.assertTrue(layer.labelsEnabled())
        self.assertEqual(len(layer.actions().actions()), 1)
        # overwrite the layer in place, as Refresh does: the columns follow the new data
        task2 = LoadTask('https://x', '', '', request, path, 'sites')
        writer2 = task2._open_writer()
        self.assertTrue(writer2.addFeatures([rows[2][0], rows[2][0]]))
        del writer2
        task2._add_recorded_columns()
        self.assertEqual(task2.columns, [])
        layer.dataProvider().reloadData()
        self.assertEqual(layer.featureCount(), 2)


if __name__ == '__main__':
    unittest.main()
