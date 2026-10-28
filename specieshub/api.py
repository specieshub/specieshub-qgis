"""HTTP client on the QGIS network stack.

QgsBlockingNetworkRequest runs on any thread (the loader's QgsTask included),
honours the QGIS proxy and certificate settings, and applies the stored
authentication config itself, so the token never passes through this code.
"""

import json
import socket
import time

from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager, QgsApplication
from qgis.PyQt.QtCore import QUrl, QUrlQuery, QByteArray
from qgis.PyQt.QtNetwork import QNetworkRequest, QNetworkReply

from .compat import enum_value

USER_AGENT = 'SpeciesHub-QGIS/0.1.2'
RETRY_STATUSES = (429, 503)
DEFAULT_RETRY_AFTER_S = 5
MAX_RETRIES = 4


class ApiError(Exception):

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class AuthError(ApiError):
    """401: the token is missing, expired or revoked."""


class NotSupportedError(ApiError):
    """404 on an endpoint this server does not have yet (pairing before phase 1)."""


class ApiClient:

    def __init__(self, base_url, authcfg='', locale='', feedback=None, vernacular=''):
        self.base_url = str(base_url).rstrip('/')
        self.authcfg = authcfg or ''
        self.locale = locale or ''
        self.vernacular = vernacular or ''  # the account's vernacular-name language, from the profile
        self.feedback = feedback  # QgsFeedback: a cancelled task aborts the request

    # -- endpoints -------------------------------------------------------

    def profile(self):
        return self.get('/api/profile')

    def user_groups(self):
        return self.get('/api/user_groups') or []

    def vocabulary(self):
        """The account's search words: {species, tags, authors, types, ...}; 503 while being built."""
        return self.get('/api/sites/vocabulary', self._lang()) or {}

    def obs_types(self):
        """Every type, named in the viewer's language (server 1.0.36; older servers answer in the original)."""
        return self.get('/api/obs_types', self._lang()) or []

    def obs_type_fields(self, type_ids):
        """The defined fields of these types, in the forms' order: [{name, label, type, ...}]."""
        if not type_ids:
            return []
        return self.get('/api/obs_types/fields', dict({'id': list(type_ids)}, **self._lang())) or []

    def query(self, path, body):
        """One page of a sites read: the list's query (the count) or the GIS observations read (the load)."""
        return self.post(path, dict(body, **self._lang()))

    def search_species_async(self, term, on_done):
        """GET /api/species/search without blocking the dialog; on_done(rows, error)."""
        return self.get_async('/api/species/search', dict({'term': term}, **self._lang()), on_done)

    def query_sites_async(self, body, on_done):
        """POST /api/sites/query without blocking (the dialog's running count)."""
        return self.post_async('/api/sites/query', dict(body, **self._lang()), on_done)

    def revoke_current(self):
        """End this token on the server (Disconnect): the one write a token may make."""
        return self.delete('/api/profile/tokens/current')

    def pair_start(self):
        """The server's deviceCode (polled here), userCode and the url to open in the browser."""
        try:
            device = socket.gethostname()
        except OSError:
            device = ''
        try:
            return self.post('/api/gis/pair/start', {'client': USER_AGENT, 'device': device})
        except ApiError as e:
            if e.status == 404:
                raise NotSupportedError('This server does not offer browser sign-in yet.', 404)
            raise

    def pair_poll(self, device_code):
        """{'status': 'pending' | 'ok' | 'denied' | 'expired'}, with token and user on ok."""
        return self.get('/api/gis/pair/' + device_code)

    def _lang(self):
        """The language params the app sends: UI locale, and the account's vernacular language."""
        lang = {}
        if self.locale:
            lang['locale'] = self.locale
        if self.vernacular:
            lang['vernacularLanguage'] = self.vernacular
        return lang

    # -- transport -------------------------------------------------------

    def get(self, path, params=None):
        return self._request('GET', path, params=params)

    def post(self, path, body=None):
        return self._request('POST', path, body=body)

    def delete(self, path):
        return self._request('DELETE', path)

    def _build_request(self, path, params=None, body=None):
        url = QUrl(self.base_url + path)
        if params:
            query = QUrlQuery()
            for key, value in params.items():
                if value is None or value == '':
                    continue
                for item in (value if isinstance(value, (list, tuple)) else [value]):
                    query.addQueryItem(key, str(item))  # a repeated key is a list to Express
            url.setQuery(query)
        request = QNetworkRequest(url)
        request.setRawHeader(b'Accept', b'application/json')
        request.setRawHeader(b'User-Agent', USER_AGENT.encode())
        data = None
        if body is not None:
            request.setHeader(enum_value(QNetworkRequest, 'KnownHeaders', 'ContentTypeHeader'), 'application/json')
            data = QByteArray(json.dumps(body).encode('utf-8'))
        return request, data

    # A request that returns at once and calls on_done(result, error) from the
    # event loop: for the species search while the person types. The stored
    # auth config is applied here (updateNetworkRequest), as the blocking path
    # does by itself.
    def get_async(self, path, params, on_done):
        return self._async('GET', path, params, None, on_done)

    def post_async(self, path, body, on_done):
        return self._async('POST', path, None, body, on_done)

    def _async(self, method, path, params, body, on_done):
        request, data = self._build_request(path, params, body)
        if self.authcfg:
            QgsApplication.authManager().updateNetworkRequest(request, self.authcfg)
        manager = QgsNetworkAccessManager.instance()
        reply = manager.post(request, data) if method == 'POST' else manager.get(request)

        def finished():
            try:
                content = bytes(reply.readAll())
                if reply.error() == enum_value(QNetworkReply, 'NetworkError', 'NoError'):
                    on_done(self._decode(content), None)
                else:
                    status = reply.attribute(enum_value(QNetworkRequest, 'Attribute', 'HttpStatusCodeAttribute'))
                    on_done(None, ApiError(reply.errorString(), int(status) if status is not None else None))
            except ApiError as e:
                on_done(None, e)
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)
        return reply

    def _request(self, method, path, params=None, body=None):
        request, data = self._build_request(path, params, body)

        for attempt in range(MAX_RETRIES + 1):
            blocking = QgsBlockingNetworkRequest()
            if self.authcfg:
                blocking.setAuthCfg(self.authcfg)
            if method == 'GET':
                code = blocking.get(request, False, self.feedback)
            elif method == 'DELETE':
                code = blocking.deleteResource(request, self.feedback)  # no forceRefresh argument here
            else:
                code = blocking.post(request, data, False, self.feedback)
            reply = blocking.reply()
            status = reply.attribute(enum_value(QNetworkRequest, 'Attribute', 'HttpStatusCodeAttribute'))
            status = int(status) if status is not None else None
            content = bytes(reply.content())

            if code == enum_value(QgsBlockingNetworkRequest, 'ErrorCode', 'NoError'):
                return self._decode(content)
            if status in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(self._retry_after(reply))
                continue
            text = content.decode('utf-8', 'replace').strip() or blocking.errorMessage()
            if status == 401:
                raise AuthError('Not signed in, or the token was revoked. Sign in again.', 401)
            if status == 428:
                raise ApiError('The server asks for a fresh sign-in before this request (step-up).', 428)
            if status is None:
                raise ApiError('No connection to ' + self.base_url + ': ' + blocking.errorMessage())
            raise ApiError('%s %s: %s' % (status, path, text[:300]), status)

    @staticmethod
    def _retry_after(reply):
        try:
            value = reply.rawHeader(b'Retry-After')
            seconds = int(bytes(value).decode() or DEFAULT_RETRY_AFTER_S)
            return max(1, min(seconds, 30))
        except (ValueError, TypeError):
            return DEFAULT_RETRY_AFTER_S

    @staticmethod
    def _decode(content):
        if not content:
            return None
        try:
            return json.loads(content.decode('utf-8'))
        except ValueError:
            raise ApiError('The server did not answer with JSON.')


def is_secure_url(url):
    """HTTPS only, except a local development server."""
    parsed = QUrl(str(url))
    if not parsed.isValid() or not parsed.host():
        return False
    if parsed.scheme() == 'https':
        return True
    return parsed.scheme() == 'http' and parsed.host() in ('localhost', '127.0.0.1', '[::1]', '::1')
