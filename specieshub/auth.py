"""The token lives in the QGIS authentication database, encrypted under the
master password (the system keychain on macOS and Windows), as an "API header"
configuration whose one header is Authorization. Requests reference it by id;
the plugin never reads the token back.
"""

from qgis.core import QgsApplication, QgsAuthMethodConfig

METHOD = 'APIHeader'  # QGIS 3.30+


class AuthError(Exception):
    pass


def _manager():
    manager = QgsApplication.authManager()
    if manager is None:
        raise AuthError('The QGIS authentication system is not available.')
    return manager


def method_available():
    try:
        return METHOD in _manager().authMethodsKeys()
    except AuthError:
        return False


def store_token(token, label):
    """Save a bearer token; returns the authentication config id."""
    if not method_available():
        raise AuthError('This QGIS build has no "API header" authentication method (QGIS 3.30 or later is needed).')
    config = QgsAuthMethodConfig(METHOD)
    config.setName(label)
    config.setConfig('Authorization', 'Bearer ' + token.strip())
    manager = _manager()
    if not manager.storeAuthenticationConfig(config):
        raise AuthError('QGIS could not store the token in its authentication database.')
    return config.id()


def remove_token(authcfg):
    if authcfg:
        try:
            _manager().removeAuthenticationConfig(authcfg)
        except AuthError:
            pass


def token_exists(authcfg):
    try:
        return bool(authcfg) and authcfg in _manager().configIds()
    except AuthError:
        return False
