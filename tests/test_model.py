import unittest

import qgis_env  # noqa: F401  (sys.path)

from specieshub import model
from specieshub.api import is_secure_url


class LayerRequestTest(unittest.TestCase):

    def test_all_data_sends_no_chip(self):
        body = model.LayerRequest().body()
        self.assertEqual(body['filters'], [])
        self.assertIsNone(body['bbox'])
        self.assertIsNone(body['after'])
        self.assertEqual(body['limit'], model.PAGE_LIMIT)

    def test_private_is_the_ownership_chip(self):
        request = model.LayerRequest(container=model.CONTAINER_PRIVATE)
        self.assertEqual(request.filters(), [{'type': 'ownership', 'values': ['owner']}])

    def test_group_is_the_owned_by_chip_with_the_name(self):
        request = model.LayerRequest(container=model.CONTAINER_GROUP, group_name='Vilnius birders')
        self.assertEqual(request.filters(), [{'type': 'owned_by', 'values': ['Vilnius birders']}])

    def test_species_and_bbox_and_cursor(self):
        request = model.LayerRequest(species=['Parus major', 'Sitta europaea'],
                                     bbox={'south': 54.0, 'north': 55.0, 'west': 23.0, 'east': 26.0})
        body = request.body(after={'last_update': '2026-10-01T00:00:00.000Z', 'id': 'a' * 24}, limit=1)
        self.assertEqual(body['filters'], [{'type': 'species', 'values': ['Parus major', 'Sitta europaea']}])
        self.assertEqual(body['bbox']['north'], 55.0)
        self.assertEqual(body['after']['id'], 'a' * 24)
        self.assertEqual(body['limit'], 1)

    def test_observation_type_is_the_types_chip(self):
        self.assertEqual(model.LayerRequest(obs_type='Nest').filters(), [{'type': 'types', 'values': ['Nest']}])

    def test_label(self):
        self.assertEqual(model.LayerRequest().label(), 'SpeciesHub - All data')
        self.assertEqual(model.LayerRequest(container=model.CONTAINER_GROUP, group_name='G1', species=['A b'],
                                            bbox={'south': 0, 'north': 1, 'west': 0, 'east': 1}).label(),
                         'SpeciesHub - G1 - A b - map extent')

    def test_json_round_trip(self):
        request = model.LayerRequest(container=model.CONTAINER_GROUP, group_name='G1', species=['A b'], obs_type='Nest',
                                     bbox={'south': 0, 'north': 1, 'west': 0, 'east': 1},
                                     field_labels=[['nest_height', 'Nest height']])
        self.assertEqual(model.LayerRequest.from_json(request.to_json()), request)
        self.assertEqual(model.LayerRequest.from_json('{"container": "all"}').field_labels, [])


class FeatureTest(unittest.TestCase):

    def setUp(self):
        qgis_env.app()
        self.fields = model.build_fields()
        self.names = [f.name() for f in self.fields]

    def test_fields(self):
        self.assertEqual(self.names, [spec[0] for spec in model.FIELD_SPECS])
        # a recorded field named like a column of the table gets its own column
        self.assertEqual(model.column_name('nest_height'), 'nest_height')
        self.assertEqual(model.column_name('notes'), 'field_notes')
        self.assertEqual(model.field_name('field_notes'), 'notes')
        self.assertEqual(model.field_name('field_other'), 'field_other')

    def test_row_becomes_one_point_per_observation(self):
        row = {
            'id': '65f0c0ffee0000000000abcd', 'species': 'Parus major', 'vernacular': 'Didžioji zylė', 'species_recorded': None,
            'accuracy': 12.5, 'last_update': '2026-10-01T12:34:56.789Z',
            'geojson': {'type': 'Point', 'coordinates': [25.28, 54.69]},
            'observations': [
                {'id': 'o1', 'date': '2026-05-02', 'author': 'Danas', 'types': ['Nest', 'Singing'], 'tags': ['qa', '#two'],
                 'notes': 'two eggs', 'photos': 2, 'group': 'G1',
                 'data': {'nest_height': '4', 'notes': 'inner', 'empty': '', 'none': None, 'list': ['a', 'b'], 'n': 3}},
                {'id': 'o2', 'date': None, 'author': None, 'types': [], 'tags': [], 'notes': None, 'photos': 0, 'group': None, 'data': {}},
            ],
        }
        rows = model.features_from_row(row, self.fields, 'https://test.specieshub.io/')
        self.assertEqual(len(rows), 2)
        (first, recorded), (second, recorded2) = rows
        point = second.geometry().asPoint()
        self.assertAlmostEqual(point.x(), 25.28)
        self.assertAlmostEqual(point.y(), 54.69)
        first = dict(zip(self.names, first.attributes()))
        self.assertEqual((first['observation_id'], first['site_id'], first['species'], first['vernacular']),
                         ('o1', '65f0c0ffee0000000000abcd', 'Parus major', 'Didžioji zylė'))
        self.assertEqual((first['lat'], first['long']), (54.69, 25.28))
        self.assertEqual((first['observationTypes'], first['author'], first['date'], first['notes'], first['tags']),
                         ('Nest, Singing', 'Danas', '2026-05-02', 'two eggs', '#qa, #two'))
        self.assertEqual((first['photos'], first['group'], first['accuracy']), (2, 'G1', 12.5))
        self.assertEqual(first['last_update'].toString('yyyy-MM-dd'), '2026-10-01')
        self.assertEqual(first['url'], 'https://test.specieshub.io/sites/65f0c0ffee0000000000abcd')
        # the recorded values as text, empties left out
        self.assertEqual(recorded, {'nest_height': '4', 'notes': 'inner', 'list': 'a, b', 'n': '3'})
        self.assertEqual(recorded2, {})
        second = dict(zip(self.names, second.attributes()))
        self.assertEqual((second['date'], second['author'], second['notes'], second['tags'], second['photos']), ('', '', '', '', 0))

    def test_row_without_position_is_skipped(self):
        self.assertEqual(model.features_from_row({'id': 'x', 'geojson': None, 'observations': [{}]}, self.fields, 'https://x'), [])
        self.assertEqual(model.features_from_row({'id': 'x', 'geojson': {'coordinates': ['a', 'b']}, 'observations': [{}]}, self.fields, 'https://x'), [])
        self.assertEqual(model.features_from_row({'id': 'x', 'geojson': {'coordinates': [0, 0]}}, self.fields, 'https://x'), [])


class UrlTest(unittest.TestCase):

    def test_secure_url(self):
        self.assertTrue(is_secure_url('https://specieshub.io'))
        self.assertTrue(is_secure_url('http://localhost:3080'))
        self.assertTrue(is_secure_url('http://127.0.0.1:3081'))
        self.assertFalse(is_secure_url('http://specieshub.io'))
        self.assertFalse(is_secure_url('ftp://x'))


if __name__ == '__main__':
    unittest.main()
