"""What the dialog asks for (LayerRequest), as the server's query takes it,
and a query row as QgsFeatures: one per observation on its site's point, the
way the app's download (sites export) lays the data out - the observation's
own values and its recorded fields spread as columns. Server 1.0.36's
POST /api/gis/observations carries the notes and field values the list leaves out.
"""

import json
from dataclasses import dataclass, field, asdict

from qgis.core import QgsFeature, QgsFields, QgsField, QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import QDateTime, Qt, QVariant

from .compat import enum_value

PAGE_LIMIT = 500  # the server's cap for one page
ENDPOINT = '/api/gis/observations'
CONTAINER_ALL = 'all'
CONTAINER_PRIVATE = 'private'
CONTAINER_GROUP = 'group'
REQUEST_PROPERTY = 'specieshub/request'
SERVER_PROPERTY = 'specieshub/server'


@dataclass
class LayerRequest:
    container: str = CONTAINER_ALL
    group_name: str = ''
    species: list = field(default_factory=list)
    obs_type: str = ''        # one observation type name, as the account's vocabulary lists it
    bbox: dict = None         # {south, north, west, east} in EPSG:4326
    # [name, label] of every defined field, in the forms' order: the labels the
    # recorded fields' columns show, and their order. Which columns the table
    # gets is decided by the data (loader.py): a field with at least one value.
    field_labels: list = field(default_factory=list)

    def filters(self):
        chips = []
        if self.container == CONTAINER_PRIVATE:
            chips.append({'type': 'ownership', 'values': ['owner']})
        elif self.container == CONTAINER_GROUP and self.group_name:
            chips.append({'type': 'owned_by', 'values': [self.group_name]})
        if self.species:
            chips.append({'type': 'species', 'values': [str(name) for name in self.species]})
        if self.obs_type:
            chips.append({'type': 'types', 'values': [str(self.obs_type)]})
        return chips

    def body(self, after=None, limit=PAGE_LIMIT):
        body = {'filters': self.filters(), 'bbox': self.bbox or None, 'after': after, 'limit': int(limit)}
        return body

    def label(self):
        if self.container == CONTAINER_PRIVATE:
            where = 'Private'
        elif self.container == CONTAINER_GROUP:
            where = self.group_name or 'Group'
        else:
            where = 'All data'
        parts = [where]
        if self.species:
            parts.append(', '.join(self.species[:3]) + (' ...' if len(self.species) > 3 else ''))
        if self.obs_type:
            parts.append(self.obs_type)
        if self.bbox:
            parts.append('map extent')
        return 'SpeciesHub - ' + ' - '.join(parts)

    def to_json(self):
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text):
        data = json.loads(text)
        keys = ('container', 'group_name', 'species', 'obs_type', 'bbox', 'field_labels')
        return cls(**{key: data.get(key) for key in keys if key in data})


# The table's own columns (name, kind, length): the export's species, lat,
# long, observationTypes, author, date, notes, tags, then what GIS use adds
# (ids, the vernacular, counts, the group, GPS accuracy, the site link). The
# recorded fields follow, one string column each, as the export spreads them:
# only the fields with a value somewhere in the load (loader.py adds them).
FIELD_SPECS = [
    ('observation_id', 'str', 24),
    ('site_id', 'str', 24),
    ('species', 'str', 0),
    ('vernacular', 'str', 0),
    ('species_recorded', 'str', 0),
    ('lat', 'double', 0),
    ('long', 'double', 0),
    ('observationTypes', 'str', 0),
    ('author', 'str', 0),
    ('date', 'str', 10),
    ('notes', 'str', 0),
    ('tags', 'str', 0),
    ('photos', 'int', 0),
    ('group', 'str', 0),
    ('accuracy', 'double', 0),
    ('last_update', 'datetime', 0),
    ('url', 'str', 0),
]


def _field(name, kind, length):
    try:
        from qgis.PyQt.QtCore import QMetaType
        kinds = {'str': 'QString', 'int': 'Int', 'bool': 'Bool', 'double': 'Double', 'datetime': 'QDateTime'}
        return QgsField(name, enum_value(QMetaType, 'Type', kinds[kind]), '', length)
    except (ImportError, AttributeError, TypeError):
        kinds = {'str': 'String', 'int': 'Int', 'bool': 'Bool', 'double': 'Double', 'datetime': 'DateTime'}
        return QgsField(name, enum_value(QVariant, 'Type', kinds[kind]), '', length)


COLUMN_NAMES = {spec[0] for spec in FIELD_SPECS}


def column_name(field_name):
    """A recorded field's column: its own name unless the table already has it."""
    name = str(field_name)
    return name if name not in COLUMN_NAMES else 'field_' + name


def field_name(column):
    """The recorded field a column holds (the inverse of column_name)."""
    if column.startswith('field_') and column[6:] in COLUMN_NAMES:
        return column[6:]
    return column


def recorded_field(name, kind='str'):
    return _field(name, kind, 0)


def build_fields():
    fields = QgsFields()
    for name, kind, length in FIELD_SPECS:
        fields.append(_field(name, kind, length))
    return fields


def _joined(values):
    return ', '.join(str(v) for v in (values or []) if v not in (None, ''))


def _tags(values):
    """As the export writes them: '#tag, #other'."""
    return ', '.join(v if v.startswith('#') else '#' + v for v in (str(v) for v in (values or []) if v not in (None, '')))


def _datetime(value):
    if not value:
        return None
    parsed = QDateTime.fromString(str(value), enum_value(Qt, 'DateFormat', 'ISODateWithMs'))
    if not parsed.isValid():
        parsed = QDateTime.fromString(str(value), enum_value(Qt, 'DateFormat', 'ISODate'))
    return parsed if parsed.isValid() else None


def _text(value):
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        return _joined(value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _position(row):
    geo = row.get('geojson') or {}
    coords = geo.get('coordinates') or []
    try:
        return float(coords[0]), float(coords[1])
    except (IndexError, TypeError, ValueError):
        return None


def site_url(server_url, site_id):
    return '%s/sites/%s' % (str(server_url).rstrip('/'), site_id)


def features_from_row(row, fields, server_url):
    """One query row (a site with its observations) as (feature, recorded) per
    observation - the feature with the table's own columns, `recorded` the
    observation's field values that are not empty, as text - or nothing when
    the site has no position."""
    position = _position(row)
    if position is None:
        return []
    lng, lat = position
    site_id = str(row.get('id') or '')
    accuracy = row.get('accuracy')
    names = [f.name() for f in fields]
    features = []
    for obs in row.get('observations') or []:
        feature = QgsFeature(fields)
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lng, lat)))
        values = {
            'observation_id': str(obs.get('id') or ''),
            'site_id': site_id,
            'species': row.get('species') or '',
            'vernacular': row.get('vernacular') or '',
            'species_recorded': row.get('species_recorded') or '',
            'lat': lat,
            'long': lng,
            'observationTypes': _joined(obs.get('types')),
            'author': obs.get('author') or '',
            'date': str(obs.get('date') or '')[:10],
            'notes': obs.get('notes') or '',
            'tags': _tags(obs.get('tags')),
            'photos': int(obs.get('photos') or 0),
            'group': obs.get('group') or '',
            'accuracy': float(accuracy) if accuracy is not None else None,
            'last_update': _datetime(row.get('last_update')),
            'url': site_url(server_url, site_id),
        }
        feature.setAttributes([values.get(name) for name in names])
        data = obs.get('data') or {}
        recorded = {str(key): _text(value) for key, value in data.items() if key and value not in (None, '', [], {})}
        features.append((feature, recorded))
    return features
