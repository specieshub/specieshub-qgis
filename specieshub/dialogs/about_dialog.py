"""About: the logo and wordmark, the version, what the plugin does, and the
connection card (Sign in or Disconnect), as Danas's mockup of 2026-10-28."""

import configparser
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap, QPalette
from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame

from .. import auth
from ..compat import enum_value
from .connect_dialog import ConnectDialog, disconnect
from .style import accent, primary as _primary, secondary as _secondary

PLUGIN_DIR = os.path.dirname(os.path.dirname(__file__))
SLOGAN = 'Home for biodiversity data'


def plugin_version():
    parser = configparser.ConfigParser()
    try:
        parser.read(os.path.join(PLUGIN_DIR, 'metadata.txt'), encoding='utf-8')
        return parser.get('general', 'version')
    except (configparser.Error, OSError):
        return ''


class AboutDialog(QDialog):

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle('About SpeciesHub')
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)

        head = QHBoxLayout()
        # The app's own wordmark (the left drawer's logo), light or dark as the theme
        logo = QLabel()
        ratio = self.devicePixelRatioF()  # crisp on a Retina screen
        pixmap = QPixmap(os.path.join(PLUGIN_DIR, 'resources', self._logo_file())) \
            .scaledToHeight(int(60 * ratio), enum_value(Qt, 'TransformationMode', 'SmoothTransformation'))
        pixmap.setDevicePixelRatio(ratio)
        logo.setPixmap(pixmap)
        head.addWidget(logo)
        head.addStretch()
        version = QLabel('Version %s' % plugin_version())
        # a translucent grey reads as a pill on a light and a dark theme alike
        version.setStyleSheet('background: rgba(127, 127, 127, 0.16); border-radius: 8px; padding: 4px 10px; font-weight: 600;')
        head.addWidget(version, 0, enum_value(Qt, 'AlignmentFlag', 'AlignTop'))
        layout.addLayout(head)

        subtitle = QLabel('Official plugin for QGIS · %s' % SLOGAN)
        subtitle.setStyleSheet('color: palette(mid); font-size: 13px;')
        layout.addWidget(subtitle)

        lead = QLabel('Load your SpeciesHub sites and observations into QGIS as a point layer.')
        lead.setWordWrap(True)
        lead.setStyleSheet('font-size: 14px; padding-top: 6px;')
        layout.addWidget(lead)
        bullets = QLabel('<ul style="margin-left: 0; -qt-list-indent: 1;">'
                         '<li>All your data or a single group</li>'
                         '<li>Filter by observation type, species and area</li>'
                         '<li>Saved as a GeoPackage you can refresh later</li></ul>')
        bullets.setTextFormat(enum_value(Qt, 'TextFormat', 'RichText'))
        layout.addWidget(bullets)

        self.card = QFrame()
        self.card.setStyleSheet('QFrame#shCard { border: 1px solid palette(mid); border-radius: 8px; }')
        self.card.setObjectName('shCard')
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        texts = QVBoxLayout()
        self.card_title = QLabel()
        self.card_title.setStyleSheet('font-weight: 600; font-size: 14px;')
        self.card_body = QLabel()
        self.card_body.setWordWrap(True)
        self.card_body.setStyleSheet('color: palette(mid);')
        texts.addWidget(self.card_title)
        texts.addWidget(self.card_body)
        card_layout.addLayout(texts, 1)
        self.card_button = QPushButton()
        self.card_button.clicked.connect(self._card_action)
        card_layout.addWidget(self.card_button, 0, enum_value(Qt, 'AlignmentFlag', 'AlignVCenter'))
        layout.addWidget(self.card)
        layout.addStretch()

        foot = QHBoxLayout()
        link = QLabel('<a href="https://specieshub.io" style="color: %s; text-decoration: none;">specieshub.io</a>' % accent(self))
        link.setOpenExternalLinks(True)
        licence = QLabel('Licence GPL-2.0-or-later')
        licence.setStyleSheet('color: palette(mid); padding-left: 10px;')
        foot.addWidget(link)
        foot.addWidget(licence)
        foot.addStretch()
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.accept)
        foot.addWidget(self.close_button)
        layout.addLayout(foot)
        self.refresh()

    def _logo_file(self):
        window = self.palette().color(enum_value(QPalette, 'ColorRole', 'Window'))
        return 'logo_dark.png' if window.lightness() < 128 else 'logo_light.png'

    def connected(self):
        return self.settings.is_connected() and auth.token_exists(self.settings.authcfg)

    # The card says where things stand; the primary blue goes to the one
    # action that matters in that state (Sign in, else Close)
    def refresh(self):
        if self.connected():
            who = self.settings.user_email or self.settings.user_name or self.settings.server_url
            self.card_title.setText('Connected as %s' % who)
            self.card_body.setText('Read-only access. You can also revoke it in SpeciesHub under Settings › Connected apps.')
            self.card_button.setText('Disconnect')
            _secondary(self.card_button)
            _primary(self.close_button)
        else:
            self.card_title.setText('Not connected')
            self.card_body.setText('Sign in once. QGIS gets its own read-only access, which you can revoke at any time.')
            self.card_button.setText('Sign in')
            _primary(self.card_button)
            _secondary(self.close_button)

    def _card_action(self):
        if self.connected():
            disconnect(self.settings)
        else:
            ConnectDialog(self.settings, self).exec()
        self.refresh()
