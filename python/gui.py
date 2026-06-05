import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QFont, QIcon
from PyQt6.QtNetwork import QNetworkAccessManager
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bot import SteamgiftsBot
from paths import get_cookie_file, get_icon_path
from settings import load_settings, save_settings
from steamgifts_service import SteamgiftsService
from theme import APP_STYLESHEET
from widgets import ActivityFeed

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


class BotSignals(QObject):
    log = pyqtSignal(str)
    entry = pyqtSignal(str, str, int, str)
    waiting_points = pyqtSignal(str, str, int, int, int)
    manual_prompt = pyqtSignal(str, str, str, int)
    status = pyqtSignal(int, int)


class SteamgiftsWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.bot: SteamgiftsBot | None = None
        self._cached_cookie = ""
        self._cookie_visible = False
        self._points_worker: FetchPointsWorker | None = None
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
        content_layout.setSpacing(10)

        content_header = QLabel("Activity & Logs")
        content_header.setObjectName("contentHeader")
        content_layout.addWidget(content_header)

        self.tabs = QTabWidget()
        content_layout.addWidget(self.tabs, stretch=1)

        activity_tab = QWidget()
        activity_layout = QVBoxLayout(activity_tab)
        activity_layout.setContentsMargins(14, 14, 14, 14)
        activity_layout.setSpacing(0)
        self.activity_feed = ActivityFeed(self.network)
        activity_layout.addWidget(self.activity_feed)
        self.tabs.addTab(activity_tab, "Activity")

        console_tab = QWidget()
        console_layout = QVBoxLayout(console_tab)
        console_layout.setContentsMargins(14, 14, 14, 14)
        console_layout.setSpacing(8)

        console_hint = QLabel("All bot events in real time")
        console_hint.setObjectName("hint")
        console_layout.addWidget(console_hint)
        self.console_log = QTextEdit()
        self.console_log.setObjectName("consoleLog")
        self.console_log.setReadOnly(True)
        console_layout.addWidget(self.console_log)
        self.tabs.addTab(console_tab, "Console")

        root.addWidget(content, stretch=1)

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
            on_log=lambda msg: self.signals.log.emit(msg),
            on_entry=lambda giveaway, status: self.signals.entry.emit(
                giveaway.name,
                giveaway.image_url,
                giveaway.cost,
                status,
            ),
            on_status=lambda points, page: self.signals.status.emit(points, page),
            on_waiting_points=lambda giveaway, points, minutes: self.signals.waiting_points.emit(
                giveaway.name,
                giveaway.image_url,
                giveaway.cost,
                points,
                minutes,
            ),
            on_manual_prompt=lambda giveaway: self.signals.manual_prompt.emit(
                giveaway.code,
                giveaway.name,
                giveaway.image_url,
                giveaway.cost,
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

    def _on_entry(self, name: str, image_url: str, cost: int, status: str) -> None:
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
            )

    def _on_waiting_points(
        self,
        name: str,
        image_url: str,
        cost: int,
        current_points: int,
        wait_minutes: int,
    ) -> None:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.console_log.append(
            f"{timestamp} - Not enough Points for {name} ({cost}P). "
            f"Waiting {wait_minutes} minutes…"
        )
        self.activity_feed.add_card(
            title="Waiting for Points",
            subtitle=(
                f"Not enough points ({current_points}P) for \"{name}\" ({cost}P). "
                f"Waiting {wait_minutes} minutes…"
            ),
            image_url=image_url,
            status="waiting",
        )

    def _update_status(self, points: int, page: int) -> None:
        self.points_card.value_label.setText(str(points))
        self.page_card.value_label.setText(str(page))

    def _on_manual_prompt(
        self, code: str, name: str, image_url: str, cost: int
    ) -> None:
        self.tabs.setCurrentIndex(0)
        card = self.activity_feed.add_manual_card(
            title=name,
            subtitle=f"Enter this giveaway? Cost: {cost}P",
            image_url=image_url,
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
