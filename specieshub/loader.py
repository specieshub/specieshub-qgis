"""Background load: the pages of one LayerRequest into a GeoPackage layer.
Runs as a QgsTask so QGIS stays responsive; progress goes to the task
manager, cancel is honoured between pages and inside a request (QgsFeedback).

The recorded fields' columns come from the data, as the app's download
spreads them: the pages are written with the table's own columns while the
observations' field values are kept aside, and once the last page is in, one
column per field that has a value somewhere is added to the file and filled.
A field nobody filled gets no column (Danas, 2026-10-28, after prod showed a
table of NULL columns from the type definitions).
"""

import os

from qgis.core import (QgsTask, QgsFeedback, QgsVectorFileWriter, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransformContext, QgsWkbTypes, QgsVectorLayer, QgsFeatureRequest)

from . import model
from .api import ApiClient, ApiError
from .compat import enum_value



class LoadTask(QgsTask):

    def __init__(self, server_url, authcfg, locale, request, path, layer_name, on_done=None, vernacular=''):
        super().__init__('SpeciesHub: loading observations', enum_value(QgsTask, 'Flag', 'CanCancel'))
        self.server_url = server_url
        self.authcfg = authcfg
        self.locale = locale
        self.vernacular = vernacular
        self.request = request
        self.path = path
        self.layer_name = layer_name
        self.on_done = on_done
        self.feedback = QgsFeedback()
        self.fields = model.build_fields()
        self.count = 0          # observations written
        self.sites = 0          # sites read, against the server's total for the progress
        self.total = None
        self.total_capped = False
        self.recorded = {}      # observation id -> {field: text}, the observations with a value
        self.columns = []       # the recorded fields' columns, in the order they are added
        self.error = ''

    def cancel(self):
        self.feedback.cancel()
        super().cancel()

    def run(self):
        try:
            if not self._write_pages():
                return False
            self._add_recorded_columns()
            self.setProgress(100.0)
            return True
        except ApiError as e:
            self.error = str(e)
            return False
        except Exception as e:  # anything else is still reported, not lost in the task
            self.error = '%s: %s' % (type(e).__name__, e)
            return False

    def _write_pages(self):
        client = ApiClient(self.server_url, self.authcfg, self.locale, feedback=self.feedback,
                           vernacular=self.vernacular)
        writer = self._open_writer()
        try:
            after = None
            while True:
                if self.isCanceled():
                    return False
                page = client.query(model.ENDPOINT, self.request.body(after))
                if self.total is None:
                    self.total = page.get('total')
                    self.total_capped = bool(page.get('totalCapped'))
                rows = page.get('rows') or []
                features = []
                for row in rows:
                    for feature, recorded in model.features_from_row(row, self.fields, self.server_url):
                        features.append(feature)
                        if recorded:
                            self.recorded[feature['observation_id']] = recorded
                if not writer.addFeatures(features):
                    raise ApiError('Could not write to ' + self.path + ': ' + writer.errorMessage())
                self.count += len(features)
                self.sites += len(rows)
                if self.total:
                    self.setProgress(min(95.0, 95.0 * self.sites / self.total))
                after = page.get('nextCursor')
                if not page.get('hasMore') or not after:
                    return True
        finally:
            del writer  # closes the file

    # The fields with a value, as columns: the forms' order first (field_labels),
    # then the rest - fields no type defines any more - by name
    def _used_fields(self):
        used = set()
        for recorded in self.recorded.values():
            used.update(recorded)
        ordered = [name for name, _label in self.request.field_labels if name in used]
        return ordered + sorted(used - set(ordered))

    def _add_recorded_columns(self):
        fields = self._used_fields()
        if not fields:
            return
        layer = QgsVectorLayer('%s|layername=%s' % (self.path, self.layer_name), self.layer_name, 'ogr')
        if not layer.isValid():
            raise ApiError('Could not reopen ' + self.path + ' to add the recorded fields.')
        provider = layer.dataProvider()
        self.columns = [model.column_name(name) for name in fields]
        if not provider.addAttributes([model.recorded_field(column) for column in self.columns]):
            raise ApiError('Could not add the recorded fields to ' + self.path)
        layer.updateFields()
        index = {name: layer.fields().indexOf(column) for name, column in zip(fields, self.columns)}
        id_index = layer.fields().indexOf('observation_id')
        request = QgsFeatureRequest().setFlags(enum_value(QgsFeatureRequest, 'Flag', 'NoGeometry')).setSubsetOfAttributes([id_index])
        changes = {}
        for feature in layer.getFeatures(request):
            recorded = self.recorded.get(feature[id_index])
            if recorded:
                changes[feature.id()] = {index[name]: value for name, value in recorded.items()}
            if len(changes) >= 5000:
                self._apply(provider, changes)
                changes = {}
            if self.isCanceled():
                return
        if changes:
            self._apply(provider, changes)
        self.setProgress(99.0)

    def _apply(self, provider, changes):
        if not provider.changeAttributeValues(changes):
            raise ApiError('Could not fill the recorded fields in ' + self.path)

    def _open_writer(self):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = self.layer_name
        options.fileEncoding = 'UTF-8'
        existing = os.path.exists(self.path)
        options.actionOnExistingFile = enum_value(
            QgsVectorFileWriter, 'ActionOnExistingFile',
            'CreateOrOverwriteLayer' if existing else 'CreateOrOverwriteFile')
        writer = QgsVectorFileWriter.create(
            self.path, self.fields, enum_value(QgsWkbTypes, 'Type', 'Point'),
            QgsCoordinateReferenceSystem('EPSG:4326'), QgsCoordinateTransformContext(), options)
        if writer.hasError() != enum_value(QgsVectorFileWriter, 'WriterError', 'NoError'):
            raise ApiError('Could not create ' + self.path + ': ' + writer.errorMessage())
        return writer

    def finished(self, result):
        if self.on_done is not None:
            self.on_done(self, result)
