"""Plugin settings in QgsSettings. The token itself is never here (auth.py)."""

from qgis.core import QgsSettings

PREFIX = 'SpeciesHub/'

# The app's language codes (languagePreferences.js) by their bare code: the
# server keys its translations by these, and the app sends nothing for English
APP_LANGUAGES = {'de': 'de-DE', 'en': 'en-US', 'es': 'es-ES', 'fr': 'fr-FR', 'lt': 'lt-LT', 'pl': 'pl-PL'}

SERVERS = [
    ('SpeciesHub', 'https://specieshub.io'),
    ('SpeciesHub test server', 'https://test.specieshub.io'),
]


class Settings:

    def _get(self, key, default=None):
        return QgsSettings().value(PREFIX + key, default)

    def _set(self, key, value):
        QgsSettings().setValue(PREFIX + key, value)

    def _remove(self, key):
        QgsSettings().remove(PREFIX + key)

    @property
    def server_url(self):
        return str(self._get('server_url', SERVERS[0][1]) or SERVERS[0][1]).rstrip('/')

    @server_url.setter
    def server_url(self, value):
        self._set('server_url', str(value).rstrip('/'))

    @property
    def authcfg(self):
        return str(self._get('authcfg', '') or '')

    @property
    def user_name(self):
        return str(self._get('user_name', '') or '')

    @property
    def user_email(self):
        return str(self._get('user_email', '') or '')

    @property
    def output_dir(self):
        return str(self._get('output_dir', '') or '')

    @output_dir.setter
    def output_dir(self, value):
        self._set('output_dir', value)

    # Both languages come from the account's settings in the app, as the app
    # itself sends them; an account that has not chosen yet gets the QGIS
    # locale's, which is what the app's first login would store.

    @property
    def vernacular(self):
        """The vernacular-name language (profile.vernacularLanguage): 'lt'."""
        return str(self._get('vernacular', '') or '') or self.qgis_language()

    @property
    def locale(self):
        """The interface language (profile.uiLanguage) for type and field names: 'lt-LT';
        '' for English, where the server's own names apply."""
        code = str(self._get('ui_language', '') or '') or APP_LANGUAGES.get(self.qgis_language(), '')
        return '' if code == 'en-US' else code

    @staticmethod
    def qgis_language():
        """The bare language of the QGIS user locale: 'lt' from 'lt_LT'."""
        raw = str(QgsSettings().value('locale/userLocale', '') or '')
        return raw.split('_')[0].lower() if raw else ''

    def is_connected(self):
        return bool(self.authcfg)

    def has_profile(self):
        """False for a connection stored before the profile's language was kept (0.1.0)."""
        return self._get('vernacular') is not None

    def remember_profile(self, profile):
        profile = profile or {}
        self._set('vernacular', profile.get('vernacularLanguage') or '')
        self._set('ui_language', profile.get('uiLanguage') or '')

    def set_connection(self, server_url, authcfg, user, profile=None):
        self.server_url = server_url
        self._set('authcfg', authcfg)
        user = user or {}
        self.remember_profile(profile or user)
        name = ' '.join(part for part in (user.get('firstname'), user.get('lastname')) if part) \
            or user.get('name') or user.get('username') or ''
        self._set('user_name', name)
        self._set('user_email', user.get('email') or '')

    def clear_connection(self):
        for key in ('authcfg', 'user_name', 'user_email', 'vernacular', 'ui_language'):
            self._remove(key)
