APP_STYLESHEET = """
QMainWindow, QWidget {
    background: #0e0e0e;
    color: #e5e5e5;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}

QFrame#sidebar {
    background: #141414;
    border-right: 1px solid #262626;
}

QScrollArea#sidebarScroll {
    background: #141414;
    border: none;
    border-right: 1px solid #262626;
}

QFrame#contentArea {
    background: #0e0e0e;
}

QLabel#appTitle {
    font-size: 18px;
    font-weight: 700;
    color: #f5f5f5;
}

QLabel#appSubtitle {
    color: #737373;
    font-size: 11px;
}

QLabel#sectionTitle {
    color: #a3a3a3;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
}

QLabel {
    background: transparent;
}

QLabel#contentHeader {
    font-size: 20px;
    font-weight: 700;
    color: #f5f5f5;
}

QLabel#contentSubheader {
    color: #737373;
    font-size: 12px;
    margin-top: -4px;
}

QLabel#contentBalances {
    color: #a3d9a5;
    font-size: 13px;
    font-weight: 600;
    padding-top: 4px;
}

QLabel#countdownLabel {
    color: #d4b86a;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 8px;
}

QComboBox {
    background: #111111;
    border: 1px solid #333333;
    border-radius: 8px;
    padding: 8px 12px;
    color: #f0f0f0;
    min-width: 120px;
}

QComboBox:hover {
    border-color: #4a4a4a;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background: #1a1a1a;
    border: 1px solid #333333;
    color: #f0f0f0;
    selection-background-color: #333333;
}

QSpinBox {
    background: #111111;
    border: 1px solid #333333;
    border-radius: 8px;
    padding: 8px 12px;
    color: #f0f0f0;
    min-width: 100px;
}

QFrame#panel {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 12px;
}

QFrame#settingsSection {
    background: #141414;
    border: 1px solid #262626;
    border-radius: 14px;
}

QFrame#settingRow {
    background: transparent;
    border: none;
}

QFrame#settingDivider {
    background: #262626;
    max-height: 1px;
    min-height: 1px;
    border: none;
}

QLabel#settingLabel {
    color: #e5e5e5;
    font-size: 13px;
    font-weight: 600;
}

QLabel#settingHint {
    color: #737373;
    font-size: 11px;
    line-height: 1.4;
}

QFrame#statCard {
    background: #1c1c1c;
    border: 1px solid #303030;
    border-radius: 10px;
}

QLabel#statValue {
    font-size: 22px;
    font-weight: 700;
    color: #e5e5e5;
}

QLabel#statLabel {
    font-size: 10px;
    color: #737373;
    letter-spacing: 0.8px;
    font-weight: 600;
}

QLabel#statusPillRunning {
    background: #1a2e1a;
    color: #86efac;
    border: 1px solid #365a36;
    border-radius: 999px;
    padding: 8px 16px;
    font-weight: 700;
    font-size: 11px;
}

QLabel#statusPillStopped {
    background: #2a1a1a;
    color: #fca5a5;
    border: 1px solid #5a3636;
    border-radius: 999px;
    padding: 8px 16px;
    font-weight: 700;
    font-size: 11px;
}

QPlainTextEdit#indiegalaCookieInput {
    background: #111111;
    border: 1px solid #333333;
    border-radius: 8px;
    padding: 8px 10px;
    color: #f0f0f0;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}

QLineEdit {
    background: #111111;
    border: 1px solid #333333;
    border-radius: 8px;
    padding: 10px 12px;
    color: #f0f0f0;
    selection-background-color: #525252;
}

QLineEdit:focus {
    border: 1px solid #666666;
}

QLineEdit:disabled {
    color: #666666;
    background: #161616;
}

QPushButton {
    background: #222222;
    border: 1px solid #383838;
    border-radius: 8px;
    padding: 10px 14px;
    color: #e5e5e5;
    font-weight: 600;
}

QPushButton:hover {
    background: #2a2a2a;
    border-color: #4a4a4a;
}

QPushButton:pressed {
    background: #1a1a1a;
}

QPushButton:disabled {
    color: #666666;
    background: #1a1a1a;
    border-color: #2a2a2a;
}

QPushButton#primaryBtn {
    background: #2e2e2e;
    border: 1px solid #525252;
    color: #ffffff;
}

QPushButton#primaryBtn:hover {
    background: #3a3a3a;
}

QPushButton#dangerBtn {
    background: #2a1f1f;
    border: 1px solid #5a4040;
    color: #f0c0c0;
}

QPushButton#accentBtn {
    background: #242424;
    border: 1px solid #404040;
    color: #d4d4d4;
}

QPushButton#sidebarBtn {
    text-align: left;
    padding-left: 14px;
}

QCheckBox {
    color: #a3a3a3;
    spacing: 8px;
    font-size: 12px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #404040;
    background: #111111;
}

QCheckBox::indicator:checked {
    background: #525252;
    border-color: #666666;
}

QTabWidget#mainTabs::pane {
    border: 1px solid #262626;
    border-radius: 14px;
    background: #111111;
    top: -1px;
    padding: 2px;
}

QTabWidget#mainTabs QTabBar::tab {
    background: transparent;
    color: #737373;
    border: none;
    border-bottom: 2px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 12px 18px;
    margin-right: 4px;
    font-weight: 600;
    font-size: 12px;
    min-width: 72px;
}

QTabWidget#mainTabs QTabBar::tab:selected {
    color: #f5f5f5;
    border-bottom: 2px solid #86efac;
    background: #161616;
}

QTabWidget#mainTabs QTabBar::tab:hover:!selected {
    color: #d4d4d4;
    background: #141414;
}

QTabBar::tab {
    background: #141414;
    color: #737373;
    border: 1px solid #262626;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 20px;
    margin-right: 3px;
    font-weight: 600;
    font-size: 12px;
}

QTabBar::tab:selected {
    background: #111111;
    color: #f5f5f5;
    border-color: #404040;
}

QTabBar::tab:hover:!selected {
    color: #d4d4d4;
}

QTextEdit#consoleLog {
    background: #0a0a0a;
    border: none;
    border-radius: 8px;
    color: #a3a3a3;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    padding: 12px;
    selection-background-color: #404040;
}

QLabel#hint {
    color: #666666;
    font-size: 11px;
}

QLabel#emptyState {
    color: #525252;
    font-size: 13px;
    line-height: 1.5;
    padding: 48px 32px;
}

QScrollBar:vertical {
    background: #111111;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #333333;
    border-radius: 4px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #444444;
}

QMenu {
    background: #1a1a1a;
    border: 1px solid #303030;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    padding: 8px 18px;
    border-radius: 6px;
}

QMenu::item:selected {
    background: #333333;
    color: #f5f5f5;
}
"""
