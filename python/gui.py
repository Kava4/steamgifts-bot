import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QFont, QIcon
from PyQt6.QtNetwork import QNetworkAccessManager
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bot import SteamgiftsBot
from paths import get_cookie_file, get_icon_path
from settings import REFRESH_MINUTE_OPTIONS, load_settings, save_settings
from steamgifts_service import (
    EnteredGiveawayInfo,
    SteamgiftsService,
    format_giveaway_ends,
)
from theme import APP_STYLESHEET
from widgets import ActivityFeed, EnteredFeed

try:
    import windows_startup

    WINDOWS_STARTUP_AVAILABLE = True
except ImportError:
    WINDOWS_STARTUP_AVAILABLE = False

def load_app_icon() -> QIcon:
    icon_path = get_icon_path()
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()


class FetchPointsWorker(QThread):
    finished = pyqtSignal(int, str)
    failed = pyqtSignal(str)

    def __init__(self, cookie: str):
        super().__init__()
        self.cookie = cookie

    def run(self) -> None:
        try:
            info = SteamgiftsService(self.cookie).fetch_points_timer()
            self.finished.emit(info.points, info.username)
        except Exception as error:
            self.failed.emit(str(error))


class FetchEnteredWorker(QThread):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, cookie: str):
        super().__init__()
        self.cookie = cookie

    def run(self) -> None:
        try:
            giveaways = SteamgiftsService(self.cookie).fetch_entered_giveaways()
            self.finished.emit(giveaways)
        except Exception as error:
            self.failed.emit(str(error))


class RemoveEntryWorker(QThread):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str, str)

    def __init__(self, cookie: str, code: str, xsrf_token: str):
        super().__init__()
        self.cookie = cookie
        self.code = code
        self.xsrf_token = xsrf_token

    def run(self) -> None:
        try:
            SteamgiftsService(self.cookie).remove_entry(self.code, self.xsrf_token)
            self.finished.emit(self.code)
        except Exception as error:
            self.failed.emit(self.code, str(error))


class BotSignals(QObject):
    log = pyqtSignal(str)
    entry = pyqtSignal(str, str, int, str, str)
    waiting_points = pyqtSignal(str, str, int, int, int, str)
    manual_prompt = pyqtSignal(str, str, str, int, str)
    status = pyqtSignal(int, int)
    countdown = pyqtSignal(str, int)


class SteamgiftsWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.bot: SteamgiftsBot | None = None
        self._cached_cookie = ""
        self._cookie_visible = False
        self._points_worker: FetchPointsWorker | None = None
        self._entered_worker: FetchEnteredWorker | None = None
        self._remove_worker: RemoveEntryWorker | None = None
        self._entered_tab_index = -1
        self._force_quit = False
        self.settings = load_settings()
        self._app_icon = load_app_icon()

        self.network = QNetworkAccessManager(self)
        self.signals = BotSignals()
        self.signals.log.connect(self._on_system_log)
        self.signals.entry.connect(self._on_entry)
        self.signals.waiting_points.connect(self._on_waiting_points)
        self.signals.manual_prompt.connect(self._on_manual_prompt)
        self.signals.status.connect(self._update_status)
        self.signals.countdown.connect(self._on_countdown)

        self._build_ui()
        self._setup_tray()
        self._load_cookie()
        self._apply_settings_to_ui()
        self._show_welcome_if_needed()

    def _build_ui(self) -> None:
        self.setWindowTitle("SteamGifts Bot")
        if not self._app_icon.isNull():
            self.setWindowIcon(self._app_icon)
        self.setMinimumSize(1100, 720)
        self.resize(1200, 800)
        self.setStyleSheet(APP_STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("sidebarScroll")
        sidebar_scroll.setFixedWidth(320)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)

        sidebar_inner = QWidget()
        sidebar_inner.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar_inner)
        sidebar_layout.setContentsMargins(20, 22, 20, 20)
        sidebar_layout.setSpacing(14)

        title = QLabel("SteamGifts Bot")
        title.setObjectName("appTitle")
        sidebar_layout.addWidget(title)

        subtitle = QLabel("Auto-entry · steamgifts.com")
        subtitle.setObjectName("appSubtitle")
        sidebar_layout.addWidget(subtitle)

        self.status_pill = QLabel("STOPPED")
        self.status_pill.setObjectName("statusPillStopped")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(self.status_pill)

        self.countdown_label = QLabel("")
        self.countdown_label.setObjectName("countdownLabel")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_label.hide()
        sidebar_layout.addWidget(self.countdown_label)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.points_card = self._create_stat_card("POINTS", "-")
        self.page_card = self._create_stat_card("PAGE", "-")
        stats_row.addWidget(self.points_card)
        stats_row.addWidget(self.page_card)
        sidebar_layout.addLayout(stats_row)

        sidebar_layout.addWidget(self._section_label("SESSION"))

        cookie_panel = QFrame()
        cookie_panel.setObjectName("panel")
        cookie_layout = QVBoxLayout(cookie_panel)
        cookie_layout.setContentsMargins(12, 12, 12, 12)
        cookie_layout.setSpacing(8)

        cookie_hint = QLabel("PHPSESSID from DevTools → Cookies")
        cookie_hint.setObjectName("hint")
        cookie_hint.setWordWrap(True)
        cookie_layout.addWidget(cookie_hint)

        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("PHPSESSID")
        self.cookie_input.setEchoMode(QLineEdit.EchoMode.Password)
        cookie_layout.addWidget(self.cookie_input)

        cookie_btns = QHBoxLayout()
        cookie_btns.setSpacing(8)
        self.show_cookie_btn = QPushButton("Show")
        self.show_cookie_btn.clicked.connect(self._toggle_cookie_visibility)
        self.save_cookie_btn = QPushButton("Save")
        self.save_cookie_btn.clicked.connect(self._save_cookie)
        cookie_btns.addWidget(self.show_cookie_btn)
        cookie_btns.addWidget(self.save_cookie_btn)
        cookie_layout.addLayout(cookie_btns)
        sidebar_layout.addWidget(cookie_panel)

        sidebar_layout.addWidget(self._section_label("CONTROLS"))

        self.fetch_points_btn = QPushButton("Fetch Points")
        self.fetch_points_btn.setObjectName("accentBtn sidebarBtn")
        self.fetch_points_btn.clicked.connect(self._fetch_points)
        sidebar_layout.addWidget(self.fetch_points_btn)

        self.start_btn = QPushButton("Start Bot")
        self.start_btn.setObjectName("primaryBtn sidebarBtn")
        self.start_btn.clicked.connect(self._start_bot)
        sidebar_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop Bot")
        self.stop_btn.setObjectName("dangerBtn sidebarBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_bot)
        sidebar_layout.addWidget(self.stop_btn)

        self.clear_log_btn = QPushButton("Clear Logs")
        self.clear_log_btn.setObjectName("sidebarBtn")
        self.clear_log_btn.clicked.connect(self._clear_logs)
        sidebar_layout.addWidget(self.clear_log_btn)

        sidebar_layout.addWidget(self._section_label("SETTINGS"))

        settings_panel = QFrame()
        settings_panel.setObjectName("panel")
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(12, 10, 12, 10)
        settings_layout.setSpacing(10)

        self.tray_close_checkbox = QCheckBox("Minimize to tray on close")
        self.tray_close_checkbox.setToolTip(
            "Closing the window (X) hides the app to the system tray "
            "and the bot keeps running. Use tray → Quit to exit."
        )
        self.tray_close_checkbox.toggled.connect(self._on_tray_close_toggled)
        settings_layout.addWidget(self.tray_close_checkbox)

        if WINDOWS_STARTUP_AVAILABLE:
            self.startup_checkbox = QCheckBox("Start with Windows")
            self.startup_checkbox.toggled.connect(self._on_startup_toggled)
            settings_layout.addWidget(self.startup_checkbox)

        self.manual_select_checkbox = QCheckBox("Manual select")
        self.manual_select_checkbox.toggled.connect(self._on_manual_select_toggled)
        settings_layout.addWidget(self.manual_select_checkbox)

        sidebar_layout.addWidget(settings_panel)
        sidebar_layout.addStretch()
        sidebar_scroll.setWidget(sidebar_inner)
        root.addWidget(sidebar_scroll)

        content = QFrame()
        content.setObjectName("contentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(6)

        header_block = QVBoxLayout()
        header_block.setSpacing(2)
        self.content_header = QLabel("Activity")
        self.content_header.setObjectName("contentHeader")
        header_block.addWidget(self.content_header)
        self.content_subheader = QLabel("Giveaway entries and bot status")
        self.content_subheader.setObjectName("contentSubheader")
        header_block.addWidget(self.content_subheader)
        content_layout.addLayout(header_block)
        content_layout.addSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        content_layout.addWidget(self.tabs, stretch=1)

        activity_tab = QWidget()
        activity_layout = QVBoxLayout(activity_tab)
        activity_layout.setContentsMargins(14, 14, 14, 14)
        activity_layout.setSpacing(0)
        self.activity_feed = ActivityFeed(self.network)
        activity_layout.addWidget(self.activity_feed)
        self._activity_tab_index = self.tabs.addTab(activity_tab, "Activity")

        entered_tab = QWidget()
        entered_layout = QVBoxLayout(entered_tab)
        entered_layout.setContentsMargins(14, 14, 14, 14)
        entered_layout.setSpacing(0)
        self.entered_feed = EnteredFeed(self.network)
        self.entered_feed.refresh_requested.connect(self._refresh_entered)
        self.entered_feed.remove_requested.connect(self._remove_entered)
        entered_layout.addWidget(self.entered_feed)
        self._entered_tab_index = self.tabs.addTab(entered_tab, "Entered")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        console_tab = QWidget()
        console_layout = QVBoxLayout(console_tab)
        console_layout.setContentsMargins(14, 14, 14, 14)
        console_layout.setSpacing(0)
        self.console_log = QTextEdit()
        self.console_log.setObjectName("consoleLog")
        self.console_log.setReadOnly(True)
        console_layout.addWidget(self.console_log)
        self._console_tab_index = self.tabs.addTab(console_tab, "Console")

        settings_tab = QWidget()
        settings_tab_layout = QVBoxLayout(settings_tab)
        settings_tab_layout.setContentsMargins(18, 18, 18, 18)
        settings_tab_layout.setSpacing(16)

        bot_settings_panel = QFrame()
        bot_settings_panel.setObjectName("settingsSection")
        bot_settings_layout = QVBoxLayout(bot_settings_panel)
        bot_settings_layout.setContentsMargins(20, 18, 20, 18)
        bot_settings_layout.setSpacing(0)

        bot_settings_title = QLabel("BOT BEHAVIOR")
        bot_settings_title.setObjectName("sectionTitle")
        bot_settings_layout.addWidget(bot_settings_title)
        bot_settings_layout.addSpacing(14)

        self.refresh_combo = QComboBox()
        for minutes in REFRESH_MINUTE_OPTIONS:
            self.refresh_combo.addItem(f"{minutes} min", minutes)
        self.refresh_combo.setFixedWidth(148)
        self.refresh_combo.currentIndexChanged.connect(self._on_refresh_changed)
        bot_settings_layout.addWidget(
            self._create_setting_row(
                "List refresh interval",
                "Wait time after scanning all pages before starting again from page 1.",
                self.refresh_combo,
            )
        )

        divider = QFrame()
        divider.setObjectName("settingDivider")
        divider.setFixedHeight(1)
        bot_settings_layout.addSpacing(14)
        bot_settings_layout.addWidget(divider)
        bot_settings_layout.addSpacing(14)

        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 50)
        self.max_pages_spin.setSuffix(" pages")
        self.max_pages_spin.setFixedWidth(148)
        self.max_pages_spin.valueChanged.connect(self._on_max_pages_changed)
        bot_settings_layout.addWidget(
            self._create_setting_row(
                "Max pages to scan",
                "How many search pages the bot processes each cycle (page 1 through N).",
                self.max_pages_spin,
            )
        )

        settings_tab_layout.addWidget(
            bot_settings_panel, alignment=Qt.AlignmentFlag.AlignTop
        )
        bot_settings_panel.setMaximumWidth(640)
        settings_tab_layout.addStretch()
        self._settings_tab_index = self.tabs.addTab(settings_tab, "Settings")

        root.addWidget(content, stretch=1)

    def _format_ends_text(
        self, ends_label: str = "", ends_at: int | None = None
    ) -> str:
        text = format_giveaway_ends(ends_at, ends_label)
        return f"Ends · {text}" if text else ""

    def _create_setting_row(
        self, title: str, description: str, control: QWidget
    ) -> QFrame:
        row = QFrame()
        row.setObjectName("settingRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("settingLabel")
        text_col.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setObjectName("settingHint")
        desc_label.setWordWrap(True)
        text_col.addWidget(desc_label)

        layout.addLayout(text_col, stretch=1)
        layout.addWidget(control, alignment=Qt.AlignmentFlag.AlignTop)

        return row

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _create_stat_card(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("statCard")
        card.setFixedHeight(68)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)

        value_label = QLabel(value)
        value_label.setObjectName("statValue")
        card_layout.addWidget(value_label)

        name_label = QLabel(label)
        name_label.setObjectName("statLabel")
        card_layout.addWidget(name_label)

        card.value_label = value_label
        return card

    def _setup_tray(self) -> None:
        tray_icon = (
            self._app_icon
            if not self._app_icon.isNull()
            else self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )
        self.tray = QSystemTrayIcon(tray_icon, self)
        self.tray.setToolTip("SteamGifts Bot")

        tray_menu = QMenu()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self._show_from_tray)
        tray_menu.addAction(show_action)

        self.tray_start_action = QAction("Start Bot", self)
        self.tray_start_action.triggered.connect(self._start_bot)
        tray_menu.addAction(self.tray_start_action)

        self.tray_stop_action = QAction("Stop Bot", self)
        self.tray_stop_action.triggered.connect(self._stop_bot)
        self.tray_stop_action.setEnabled(False)
        tray_menu.addAction(self.tray_stop_action)

        tray_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _apply_settings_to_ui(self) -> None:
        self.tray_close_checkbox.setChecked(self.settings["minimize_to_tray_on_close"])
        self.manual_select_checkbox.setChecked(self.settings["manual_select_giveaways"])

        refresh_minutes = self.settings.get("refresh_delay_minutes", 10)
        refresh_index = REFRESH_MINUTE_OPTIONS.index(refresh_minutes)
        self.refresh_combo.blockSignals(True)
        self.refresh_combo.setCurrentIndex(refresh_index)
        self.refresh_combo.blockSignals(False)

        self.max_pages_spin.blockSignals(True)
        self.max_pages_spin.setValue(self.settings.get("max_pages", 5))
        self.max_pages_spin.blockSignals(False)

        if WINDOWS_STARTUP_AVAILABLE:
            actual_startup = windows_startup.is_startup_enabled()
            self.settings["start_with_windows"] = actual_startup
            self.startup_checkbox.setChecked(actual_startup)

    def _persist_settings(self) -> None:
        save_settings(self.settings)

    def _on_tray_close_toggled(self, checked: bool) -> None:
        self.settings["minimize_to_tray_on_close"] = checked
        self._persist_settings()

    def _on_manual_select_toggled(self, checked: bool) -> None:
        self.settings["manual_select_giveaways"] = checked
        self._persist_settings()
        if self.bot:
            self.bot.set_manual_select(checked)

    def _on_refresh_changed(self) -> None:
        minutes = self.refresh_combo.currentData()
        self.settings["refresh_delay_minutes"] = minutes
        self._persist_settings()
        if self.bot:
            self.bot.apply_bot_settings(
                minutes, self.settings.get("max_pages", 5)
            )

    def _on_max_pages_changed(self, value: int) -> None:
        self.settings["max_pages"] = value
        self._persist_settings()
        if self.bot:
            self.bot.apply_bot_settings(
                self.settings.get("refresh_delay_minutes", 10), value
            )

    def _on_startup_toggled(self, checked: bool) -> None:
        if not WINDOWS_STARTUP_AVAILABLE:
            return

        try:
            windows_startup.set_startup_enabled(checked)
            self.settings["start_with_windows"] = checked
            self._persist_settings()
            self._append_console(
                "Start with Windows enabled"
                if checked
                else "Start with Windows disabled"
            )
        except OSError as error:
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(not checked)
            self.startup_checkbox.blockSignals(False)
            QMessageBox.warning(self, "Startup", f"Failed: {error}")

    def _toggle_cookie_visibility(self) -> None:
        self._cookie_visible = not self._cookie_visible
        self.cookie_input.setEchoMode(
            QLineEdit.EchoMode.Normal
            if self._cookie_visible
            else QLineEdit.EchoMode.Password
        )
        self.show_cookie_btn.setText("Hide" if self._cookie_visible else "Show")

    def _load_cookie(self) -> None:
        cookie_file = get_cookie_file()
        if cookie_file.exists():
            cookie = cookie_file.read_text(encoding="utf-8").strip()
            if cookie:
                self.cookie_input.setText(cookie)
                self._cached_cookie = cookie
                self._append_console(f"Loaded cookie from {cookie_file}")

    def _show_welcome_if_needed(self) -> None:
        if self.console_log.toPlainText():
            return
        if self.cookie_input.text().strip():
            self._append_console("Ready. Click Fetch Points or Start Bot.")
        else:
            self._append_console(
                "Welcome! Paste your PHPSESSID in the sidebar, click Save, "
                "then Start Bot."
            )

    def _save_cookie(self, silent: bool = False) -> None:
        cookie = self.cookie_input.text().strip()
        if not cookie:
            if not silent:
                QMessageBox.warning(self, "Cookie", "Enter PHPSESSID first.")
            return

        cookie_file = get_cookie_file()
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        cookie_file.write_text(cookie, encoding="utf-8")
        self._cached_cookie = cookie
        if not silent:
            self._append_console(f"Cookie saved to {cookie_file}")
            QMessageBox.information(self, "Cookie", "Saved successfully.")

    def _fetch_points(self) -> None:
        cookie = self.cookie_input.text().strip()
        if not cookie:
            QMessageBox.warning(self, "Points", "Enter PHPSESSID first.")
            return

        if self._points_worker and self._points_worker.isRunning():
            return

        self.fetch_points_btn.setEnabled(False)
        self.fetch_points_btn.setText("Fetching…")

        self._points_worker = FetchPointsWorker(cookie)
        self._points_worker.finished.connect(self._on_points_fetched)
        self._points_worker.failed.connect(self._on_points_failed)
        self._points_worker.finished.connect(
            lambda: self.fetch_points_btn.setEnabled(True)
        )
        self._points_worker.finished.connect(
            lambda: self.fetch_points_btn.setText("Fetch Points")
        )
        self._points_worker.failed.connect(
            lambda: self.fetch_points_btn.setEnabled(True)
        )
        self._points_worker.failed.connect(
            lambda: self.fetch_points_btn.setText("Fetch Points")
        )
        self._points_worker.start()

    def _on_points_fetched(self, points: int, username: str) -> None:
        self.points_card.value_label.setText(str(points))
        user_part = f" ({username})" if username else ""
        msg = f"Fetched points: {points}{user_part}"
        self._append_console(msg)
        if self.tray.isVisible():
            self.tray.showMessage(
                "SteamGifts Bot",
                f"Points: {points}",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )

    def _on_points_failed(self, message: str) -> None:
        self._append_console(f"Fetch points failed: {message}")
        QMessageBox.warning(self, "Points", message)

    def _on_tab_changed(self, index: int) -> None:
        headers = {
            self._activity_tab_index: (
                "Activity",
                "Giveaway entries and bot status",
            ),
            self._entered_tab_index: (
                "Entered",
                "Active giveaways you joined on SteamGifts",
            ),
            self._console_tab_index: (
                "Console",
                "All bot events in real time",
            ),
            self._settings_tab_index: (
                "Settings",
                "Bot scan interval and pagination",
            ),
        }
        title, subtitle = headers.get(index, ("SteamGifts Bot", ""))
        self.content_header.setText(title)
        self.content_subheader.setText(subtitle)

        if index == self._entered_tab_index:
            self._refresh_entered()

    def _refresh_entered(self) -> None:
        cookie = self.cookie_input.text().strip()
        if not cookie:
            QMessageBox.warning(self, "Entered", "Enter PHPSESSID first.")
            return

        if self._entered_worker and self._entered_worker.isRunning():
            return

        self.entered_feed.set_loading(True)
        self._entered_worker = FetchEnteredWorker(cookie)
        self._entered_worker.finished.connect(self._on_entered_fetched)
        self._entered_worker.failed.connect(self._on_entered_failed)
        self._entered_worker.finished.connect(
            lambda: self.entered_feed.set_loading(False)
        )
        self._entered_worker.failed.connect(
            lambda: self.entered_feed.set_loading(False)
        )
        self._entered_worker.start()

    def _on_entered_fetched(self, giveaways: list[EnteredGiveawayInfo]) -> None:
        self.entered_feed.set_giveaways(giveaways)
        self._append_console(
            f"Loaded {len(giveaways)} active entered giveaway(s)"
        )

    def _on_entered_failed(self, message: str) -> None:
        self._append_console(f"Entered list failed: {message}")
        QMessageBox.warning(self, "Entered", message)

    def _remove_entered(self, code: str, xsrf_token: str) -> None:
        cookie = self.cookie_input.text().strip()
        if not cookie:
            QMessageBox.warning(self, "Entered", "Enter PHPSESSID first.")
            return

        if self._remove_worker and self._remove_worker.isRunning():
            return

        self._remove_worker = RemoveEntryWorker(cookie, code, xsrf_token)
        self._remove_worker.finished.connect(self._on_entry_removed)
        self._remove_worker.failed.connect(self._on_entry_remove_failed)
        self._remove_worker.start()

    def _on_entry_removed(self, code: str) -> None:
        self.entered_feed.remove_card(code)
        self._append_console(f"Removed entry: {code}")

    def _on_entry_remove_failed(self, code: str, message: str) -> None:
        self._append_console(f"Remove failed ({code}): {message}")
        QMessageBox.warning(self, "Remove", message)
        self._refresh_entered()

    def _start_bot(self) -> None:
        cookie = self.cookie_input.text().strip()
        if not cookie:
            QMessageBox.warning(self, "Cookie", "Enter PHPSESSID before starting.")
            return

        if self.bot and self.bot.is_running:
            return

        self.bot = SteamgiftsBot(
            cookie=cookie,
            manual_select=self.settings.get("manual_select_giveaways", False),
            refresh_delay_minutes=self.settings.get("refresh_delay_minutes", 10),
            max_pages=self.settings.get("max_pages", 5),
            on_log=lambda msg: self.signals.log.emit(msg),
            on_entry=lambda giveaway, status: self.signals.entry.emit(
                giveaway.name,
                giveaway.image_url,
                giveaway.cost,
                status,
                self._format_ends_text(giveaway.ends_label, giveaway.ends_at),
            ),
            on_status=lambda points, page: self.signals.status.emit(points, page),
            on_countdown=lambda label, seconds: self.signals.countdown.emit(
                label, seconds
            ),
            on_waiting_points=lambda giveaway, points, minutes: self.signals.waiting_points.emit(
                giveaway.name,
                giveaway.image_url,
                giveaway.cost,
                points,
                minutes,
                self._format_ends_text(giveaway.ends_label, giveaway.ends_at),
            ),
            on_manual_prompt=lambda giveaway: self.signals.manual_prompt.emit(
                giveaway.code,
                giveaway.name,
                giveaway.image_url,
                giveaway.cost,
                self._format_ends_text(giveaway.ends_label, giveaway.ends_at),
            ),
        )
        self.bot.start()

        self._set_running_state(True)
        self._append_console("Bot started")

        if self.tray.isVisible():
            self.tray.showMessage(
                "SteamGifts Bot",
                "Bot started — running in background",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _stop_bot(self) -> None:
        if self.bot:
            self.bot.stop()

        self._set_running_state(False)
        self._append_console("Bot stopped")

    def _set_running_state(self, running: bool) -> None:
        if running:
            self.status_pill.setText("RUNNING")
            self.status_pill.setObjectName("statusPillRunning")
        else:
            self.status_pill.setText("STOPPED")
            self.status_pill.setObjectName("statusPillStopped")
            self.countdown_label.hide()
            self.countdown_label.setText("")
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)

        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.cookie_input.setEnabled(not running)
        self.save_cookie_btn.setEnabled(not running)
        self.tray_start_action.setEnabled(not running)
        self.tray_stop_action.setEnabled(running)

    def _clear_logs(self) -> None:
        self.console_log.clear()
        self.activity_feed.clear()
        self._append_console("Logs cleared")

    def _append_console(self, message: str) -> None:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.console_log.append(f"{timestamp} - {message}")

    def _on_system_log(self, message: str) -> None:
        self.console_log.append(message)

    def _on_entry(
        self, name: str, image_url: str, cost: int, status: str, ends_text: str
    ) -> None:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.console_log.append(
            f"{timestamp} - Entering giveaway: {name} ({cost}P)"
        )
        if not self.settings.get("manual_select_giveaways"):
            self.activity_feed.add_card(
                title=name,
                subtitle=f"Entered · cost {cost}P",
                image_url=image_url,
                status="entered",
                ends_text=ends_text,
            )

    def _on_waiting_points(
        self,
        name: str,
        image_url: str,
        cost: int,
        current_points: int,
        wait_minutes: int,
        ends_text: str,
    ) -> None:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.console_log.append(
            f"{timestamp} - Not enough Points for {name} ({cost}P). "
            f"Waiting {wait_minutes} minutes…"
        )
        self.activity_feed.set_waiting_card(
            title=name,
            subtitle=(
                f"Need {cost}P · have {current_points}P · "
                f"waiting {wait_minutes} min for more points"
            ),
            image_url=image_url,
            ends_text=ends_text,
        )

    def _update_status(self, points: int, page: int) -> None:
        self.points_card.value_label.setText(str(points))
        self.page_card.value_label.setText(str(page))

    def _on_countdown(self, label: str, seconds: int) -> None:
        if seconds <= 0 or not label:
            self.countdown_label.hide()
            self.countdown_label.setText("")
            return

        minutes, secs = divmod(seconds, 60)
        time_text = f"{minutes}:{secs:02d}"
        if label == "refresh":
            text = f"Next refresh in {time_text}"
        elif label == "points":
            text = f"Waiting for points · {time_text}"
        else:
            text = time_text

        self.countdown_label.setText(text)
        self.countdown_label.show()

    def _on_manual_prompt(
        self, code: str, name: str, image_url: str, cost: int, ends_text: str
    ) -> None:
        self.tabs.setCurrentIndex(0)
        card = self.activity_feed.add_manual_card(
            title=name,
            subtitle=f"Enter this giveaway? Cost: {cost}P",
            image_url=image_url,
            ends_text=ends_text,
        )
        card.decided.connect(
            lambda enter, giveaway_code=code: self._submit_manual_decision(enter)
        )
        self._append_console(f"Waiting manual decision for: {name} ({cost}P)")

    def _submit_manual_decision(self, enter: bool) -> None:
        if self.bot:
            self.bot.submit_manual_decision(enter)
        self._append_console("Manual decision: Yes" if enter else "Manual decision: No")

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _quit_app(self) -> None:
        self._force_quit = True
        if self.bot and self.bot.is_running:
            self.bot.stop()
        QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_quit:
            event.accept()
            return

        if (
            self.settings.get("minimize_to_tray_on_close")
            and self.tray.isVisible()
        ):
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "SteamGifts Bot",
                "App is running in the tray. Double-click to open.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return

        if self.bot and self.bot.is_running:
            self.bot.stop()

        self._force_quit = True
        QApplication.instance().quit()
        event.accept()


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(
            None,
            "System Tray",
            "System tray is not available on this system.",
        )

    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = SteamgiftsWindow()
    window.show()

    sys.exit(app.exec())
