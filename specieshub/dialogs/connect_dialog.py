"""The account dialog, three pages (Danas's mockup of 2026-10-28):
connected - the account card with Disconnect; sign in - the server, Sign in
with browser over a pasted token; waiting - a spinner while the person
confirms in the browser (the pairing, PLAN.md phase 1), polled here."""

import webbrowser

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QTimer, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QLineEdit,
                                 QFrame, QWidget, QMessageBox)

from .. import auth
from ..api import ApiClient, ApiError, AuthError, NotSupportedError, is_secure_url
from ..compat import enum_value
from ..settings import SERVERS
from .style import primary, secondary, link, caption, Spinner

POLL_INTERVAL_MS = 2000
POLL_MAX_MS = 10 * 60 * 1000


def log(message, level=None):
    QgsMessageLog.logMessage(message, 'SpeciesHub', level if level is not None else Qgis.Info)


# The token ends on the server too, so Settings > Connected apps does not keep
# one row per sign-in. A server without the route (before 1.0.35), or a token
# already gone, is no reason to keep the person signed in here.
def revoke_on_server(settings, url, authcfg):
    if not authcfg:
        return
    try:
        ApiClient(url, authcfg, settings.locale).revoke_current()
        log('Token ended on %s' % url)
    except ApiError as e:
        log('Token not ended on the server (%s); removed here anyway' % e, Qgis.Warning)


# Disconnect, from this dialog or the About card: server first, then the
# auth store, then the settings
def disconnect(settings):
    revoke_on_server(settings, settings.server_url, settings.authcfg)
    auth.remove_token(settings.authcfg)
    settings.clear_connection()


def _host(url):
    return QUrl(str(url)).host() or str(url)


class ConnectDialog(QDialog):

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle('SpeciesHub account')
        self.setMinimumWidth(520)
        self._device_code = ''
        self._user_code = ''
        self._open_url = ''
        self._pair_elapsed = 0
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._build()
        self._show_state()

    # -- pages -------------------------------------------------------------

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 20)
        # The three pages in one column, one shown at a time: a stacked widget
        # kept the tallest page's height whatever the policies said
        self.page_connected = self._build_connected()
        self.page_signin = self._build_signin()
        self.page_waiting = self._build_waiting()
        self._current = None
        for page in (self.page_connected, self.page_signin, self.page_waiting):
            page.hide()
            layout.addWidget(page)

    def _build_connected(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName('shAccount')
        card.setStyleSheet('QFrame#shAccount { border: 1px solid palette(mid); border-radius: 8px; }')
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)
        self.avatar = QLabel()
        self.avatar.setFixedSize(44, 44)
        self.avatar.setAlignment(enum_value(Qt, 'AlignmentFlag', 'AlignCenter'))
        self.avatar.setStyleSheet('background: rgba(127, 127, 127, 0.18); border-radius: 22px; font-weight: 600;')
        row.addWidget(self.avatar)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.who = QLabel()
        self.who.setStyleSheet('font-weight: 600; font-size: 14px;')
        self.where = caption()
        texts.addWidget(self.who)
        texts.addWidget(self.where)
        row.addLayout(texts, 1)
        status = QLabel('<span style="color:#2e7d32">●</span> Connected')
        row.addWidget(status, 0, enum_value(Qt, 'AlignmentFlag', 'AlignVCenter'))
        layout.addWidget(card)
        layout.addWidget(caption('Disconnecting removes the token from QGIS. Layers you already loaded stay on your computer.'))
        layout.addStretch()
        foot = QHBoxLayout()
        self.disconnect_button = QPushButton('Disconnect')
        secondary(self.disconnect_button)
        self.disconnect_button.clicked.connect(self._disconnect)
        close = QPushButton('Close')
        primary(close)
        close.clicked.connect(self.reject)
        foot.addWidget(self.disconnect_button)
        foot.addStretch()
        foot.addWidget(close)
        layout.addLayout(foot)
        return page

    def _build_signin(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel('Connect QGIS to SpeciesHub')
        title.setStyleSheet('font-weight: 600; font-size: 15px;')
        layout.addWidget(title)
        layout.addWidget(caption('QGIS gets its own read-only access. You can revoke it at any time.'))
        layout.addSpacing(8)
        layout.addWidget(QLabel('Server'))
        self.server = QComboBox()
        self.server.setEditable(True)
        for name, url in SERVERS:
            self.server.addItem('%s · %s' % (name, _host(url)), url)
        self._select_server(self.settings.server_url)
        layout.addWidget(self.server)
        layout.addSpacing(8)
        self.sign_in = QPushButton('Sign in with browser')
        primary(self.sign_in)
        self.sign_in.clicked.connect(self._start_pairing)
        layout.addWidget(self.sign_in)
        note = caption('Opens SpeciesHub in your browser, then returns here.')
        note.setAlignment(enum_value(Qt, 'AlignmentFlag', 'AlignCenter'))
        layout.addWidget(note)
        self.signin_error = caption('')
        self.signin_error.setAlignment(enum_value(Qt, 'AlignmentFlag', 'AlignCenter'))
        layout.addWidget(self.signin_error)

        divider = QHBoxLayout()
        for side in range(2):
            line = QFrame()
            line.setFrameShape(enum_value(QFrame, 'Shape', 'HLine'))
            line.setStyleSheet('color: palette(mid);')
            if side == 0:
                divider.addWidget(line, 1)
                divider.addWidget(caption('or'))
            else:
                divider.addWidget(line, 1)
        layout.addLayout(divider)

        layout.addWidget(QLabel('Paste a token'))
        token_row = QHBoxLayout()
        self.token = QLineEdit()
        self.token.setEchoMode(enum_value(QLineEdit, 'EchoMode', 'Password'))
        self.token.setPlaceholderText('Paste token')
        self.token.returnPressed.connect(self._connect_with_token)
        self.connect_button = QPushButton('Connect')
        secondary(self.connect_button)
        self.connect_button.clicked.connect(self._connect_with_token)
        token_row.addWidget(self.token, 1)
        token_row.addWidget(self.connect_button)
        layout.addLayout(token_row)
        layout.addWidget(caption('Create one in SpeciesHub under Settings › Connected apps.'))
        layout.addStretch()
        foot = QHBoxLayout()
        foot.addStretch()
        close = QPushButton('Close')
        secondary(close)
        close.clicked.connect(self.reject)
        foot.addWidget(close)
        layout.addLayout(foot)
        return page

    def _build_waiting(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addSpacing(12)
        self.spinner = Spinner()
        layout.addWidget(self.spinner, 0, enum_value(Qt, 'AlignmentFlag', 'AlignHCenter'))
        title = QLabel('Finish signing in in your browser')
        title.setStyleSheet('font-weight: 600; font-size: 15px;')
        title.setAlignment(enum_value(Qt, 'AlignmentFlag', 'AlignCenter'))
        layout.addWidget(title)
        self.waiting_text = caption('')
        self.waiting_text.setAlignment(enum_value(Qt, 'AlignmentFlag', 'AlignCenter'))
        layout.addWidget(self.waiting_text)
        self.open_link = QPushButton("Browser didn't open? Open the sign-in page")
        link(self.open_link)
        self.open_link.clicked.connect(lambda: self._open_browser(self._open_url))
        layout.addWidget(self.open_link, 0, enum_value(Qt, 'AlignmentFlag', 'AlignHCenter'))
        # the code the page shows, and what the server last said: the one line
        # to read when something does not move
        self.pairing = caption('')
        self.pairing.setAlignment(enum_value(Qt, 'AlignmentFlag', 'AlignCenter'))
        self.pairing.setTextFormat(enum_value(Qt, 'TextFormat', 'RichText'))
        self.pairing.setOpenExternalLinks(True)
        layout.addWidget(self.pairing)
        layout.addStretch()
        foot = QHBoxLayout()
        foot.addStretch()
        cancel = QPushButton('Cancel')
        secondary(cancel)
        cancel.clicked.connect(lambda: self._stop_pairing(''))
        foot.addWidget(cancel)
        layout.addLayout(foot)
        return page

    # -- state -------------------------------------------------------------

    def state(self):
        return {self.page_connected: 'connected', self.page_signin: 'signin', self.page_waiting: 'waiting'}[self._current]

    def _show_page(self, page):
        for other in (self.page_connected, self.page_signin, self.page_waiting):
            other.setVisible(other is page)
        self._current = page
        # the layout re-reads the sizes without the hidden pages, then the dialog fits
        self.layout().activate()
        QTimer.singleShot(0, lambda: self.resize(self.sizeHint()))

    def _select_server(self, url):
        index = self.server.findData(url)
        if index >= 0:
            self.server.setCurrentIndex(index)
        else:
            self.server.setEditText(url)

    def _server_url(self):
        index = self.server.currentIndex()
        if index >= 0 and self.server.currentText() == self.server.itemText(index):
            return str(self.server.itemData(index)).rstrip('/')
        return self.server.currentText().strip().rstrip('/')

    def _show_state(self):
        connected = self.settings.is_connected() and auth.token_exists(self.settings.authcfg)
        if connected:
            name = self.settings.user_name or self.settings.user_email or 'Connected'
            self.who.setText(name)
            self.where.setText('%s · read-only access' % _host(self.settings.server_url))
            initials = ''.join(part[0] for part in name.split()[:2] if part).upper() or 'SH'
            self.avatar.setText(initials)
            self._show_page(self.page_connected)
        else:
            self._show_page(self.page_signin)

    # -- pairing -----------------------------------------------------------

    def _checked_server(self):
        url = self._server_url()
        if not is_secure_url(url):
            QMessageBox.warning(self, 'SpeciesHub', 'The server address must start with https:// (http:// is allowed for localhost only).')
            return None
        return url

    def _start_pairing(self):
        url = self._checked_server()
        if not url:
            return
        self.signin_error.setText('')
        client = ApiClient(url, '', self.settings.locale)
        try:
            start = client.pair_start() or {}
        except NotSupportedError:
            self.signin_error.setText('This server does not offer browser sign-in yet. Paste a token below.')
            return
        except ApiError as e:
            self.signin_error.setText(str(e))
            return
        self._device_code = str(start.get('deviceCode') or '')
        self._user_code = str(start.get('userCode') or '')
        open_url = start.get('url') or ''
        if not self._device_code or not open_url:
            self.signin_error.setText('The server did not return a pairing code.')
            return
        # A server without its app address configured answers a relative
        # address: the app lives on the same host as the API
        self._open_url = QUrl(url + '/').resolved(QUrl(open_url)).toString()
        self._timer.setInterval(int(start.get('interval') or 2) * 1000)
        self._pair_elapsed = 0
        opened = self._open_browser(self._open_url)
        log('Pairing started: code %s, browser %s, %s' % (self._user_code, opened, self._open_url))
        self.waiting_text.setText('Approve access for QGIS on %s. This window updates on its own.' % _host(url))
        self._show_waiting('pending')
        self._show_page(self.page_waiting)
        self._timer.start()

    # Qt's call first; Python's own opener when Qt says no (it reports the
    # launch, not the page, so the link stays either way)
    @staticmethod
    def _open_browser(url):
        if QDesktopServices.openUrl(QUrl(url)):
            return 'opened by Qt'
        try:
            return 'opened by webbrowser' if webbrowser.open(url, new=2) else 'NOT opened'
        except Exception as e:  # a missing default browser, say
            return 'NOT opened (%s)' % e

    def _poll(self):
        self._pair_elapsed += self._timer.interval()
        if self._pair_elapsed > POLL_MAX_MS:
            self._stop_pairing('The sign-in timed out. Try again.')
            return
        client = ApiClient(self._server_url(), '', self.settings.locale)
        try:
            answer = client.pair_poll(self._device_code) or {}
        except ApiError as e:
            log('Pairing poll failed: %s' % e, Qgis.Warning)
            self._stop_pairing(str(e))
            return
        status = answer.get('status')
        log('Pairing poll after %d s: %s' % (self._pair_elapsed // 1000, status))
        if status == 'pending':
            self._show_waiting(status)
            return
        if status == 'denied':
            self._stop_pairing('The sign-in was declined in the browser.')
            return
        if status != 'ok':
            self._stop_pairing('The sign-in expired. Try again.')
            return
        self._timer.stop()
        self._finish(self._server_url(), str(answer.get('token') or ''), answer.get('user'))

    def _show_waiting(self, status):
        self.pairing.setText('Code <b>%s</b> \u00b7 %d s \u00b7 last answer: %s' % (self._user_code, self._pair_elapsed // 1000, status))

    # Back to the sign-in page, with the reason when there is one
    def _stop_pairing(self, message):
        self._timer.stop()
        self._device_code = ''
        self.signin_error.setText(message)
        self._show_page(self.page_signin)

    # -- token -------------------------------------------------------------

    def _connect_with_token(self):
        url = self._checked_server()
        if not url:
            return
        token = self.token.text().strip()
        if not token:
            QMessageBox.information(self, 'SpeciesHub', 'Paste a token first.')
            return
        self._finish(url, token, None)

    def _finish(self, url, token, user):
        """Store the token, prove it with the profile, remember the connection."""
        try:
            authcfg = auth.store_token(token, 'SpeciesHub (%s)' % url)
        except auth.AuthError as e:
            QMessageBox.critical(self, 'SpeciesHub', str(e))
            return
        client = ApiClient(url, authcfg, self.settings.locale)
        try:
            profile = client.profile() or {}
        except AuthError:
            auth.remove_token(authcfg)
            QMessageBox.warning(self, 'SpeciesHub', 'The server did not accept this token.')
            return
        except ApiError as e:
            auth.remove_token(authcfg)
            QMessageBox.warning(self, 'SpeciesHub', str(e))
            return
        self.token.clear()
        self.signin_error.setText('')
        previous, previous_url = self.settings.authcfg, self.settings.server_url
        self.settings.set_connection(url, authcfg, user or profile, profile)
        if previous and previous != authcfg:
            # a sign-in over a sign-in leaves no orphan, on the server or in the auth store
            revoke_on_server(self.settings, previous_url, previous)
            auth.remove_token(previous)
        log('Signed in to %s as %s' % (url, self.settings.user_name or self.settings.user_email))
        self._show_state()

    def _disconnect(self):
        disconnect(self.settings)
        self._show_state()

    def reject(self):
        self._timer.stop()
        super().reject()
