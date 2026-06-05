from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ActivityCard(QFrame):
    def __init__(
        self,
        title: str,
        subtitle: str,
        image_url: str = "",
        status: str = "info",
        network: QNetworkAccessManager | None = None,
    ):
        super().__init__()
        self.setObjectName("activityCard")
        self._network = network

        colors = {
            "entered": ("#1f2a1f", "#3d5c3f", "#a3d9a5"),
            "waiting": ("#2a2618", "#6b5a2e", "#d4b86a"),
            "prompt": ("#222222", "#4a4a4a", "#d4d4d4"),
            "skipped": ("#1c1c1c", "#3a3a3a", "#9ca3af"),
            "info": ("#1c1c1c", "#333333", "#b0b0b0"),
            "error": ("#2a1a1a", "#5c3d3d", "#e8a0a0"),
        }
        bg, border, accent = colors.get(status, colors["info"])
        badge_text = {
            "entered": "ENTERED",
            "waiting": "WAITING",
            "prompt": "SELECT",
            "skipped": "SKIPPED",
        }.get(status, status.upper())

        self.setStyleSheet(
            f"""
            QFrame#activityCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 14px;
                margin: 2px 0;
            }}
            QLabel#title {{
                color: #f0f0f0;
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#subtitle {{
                color: #9ca3af;
                font-size: 11px;
            }}
            QLabel#badge {{
                background: {border};
                color: {accent};
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: 700;
            }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)

        self.image_label = QLabel()
        self.image_label.setFixedSize(184, 69)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            "background: #141414; border: 1px solid #333333; border-radius: 8px; color: #6b6b6b;"
        )
        if status == "waiting":
            self.image_label.setText("⏳")
            self.image_label.setStyleSheet(
                "background: #1a1508; border: 2px solid #fbbf24; border-radius: 8px;"
                " color: #fbbf24; font-size: 28px;"
            )
        else:
            self.image_label.setText("…")
        layout.addWidget(self.image_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        top_row = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)
        top_row.addWidget(self.title_label, stretch=1)

        self.badge_label = QLabel(badge_text)
        self.badge_label.setObjectName("badge")
        top_row.addWidget(self.badge_label, alignment=Qt.AlignmentFlag.AlignTop)
        text_col.addLayout(top_row)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("subtitle")
        self.subtitle_label.setWordWrap(True)
        text_col.addWidget(self.subtitle_label)

        text_col.addStretch()
        layout.addLayout(text_col, stretch=1)

        if image_url and network is not None:
            self._load_image(image_url)

    def _load_image(self, image_url: str) -> None:
        request = QNetworkRequest(QUrl(image_url))
        reply = self._network.get(request)
        reply.finished.connect(lambda: self._on_image_loaded(reply))

    def _on_image_loaded(self, reply) -> None:
        if reply.error().value == 0:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.image_label.setPixmap(
                    pixmap.scaled(
                        self.image_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.image_label.setText("")
        reply.deleteLater()


class ManualSelectCard(ActivityCard):
    decided = pyqtSignal(bool)

    def __init__(
        self,
        title: str,
        subtitle: str,
        image_url: str,
        network: QNetworkAccessManager,
    ):
        super().__init__(
            title=title,
            subtitle=subtitle,
            image_url=image_url,
            status="prompt",
            network=network,
        )

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self.yes_btn = QPushButton("Yes")
        self.yes_btn.setObjectName("accentBtn")
        self.yes_btn.setFixedWidth(80)
        self.yes_btn.clicked.connect(lambda: self._decide(True))
        buttons.addWidget(self.yes_btn)

        self.no_btn = QPushButton("No")
        self.no_btn.setObjectName("dangerBtn")
        self.no_btn.setFixedWidth(80)
        self.no_btn.clicked.connect(lambda: self._decide(False))
        buttons.addWidget(self.no_btn)

        text_col = self.layout().itemAt(1).layout()
        text_col.addLayout(buttons)

    def _decide(self, enter: bool) -> None:
        self.yes_btn.setEnabled(False)
        self.no_btn.setEnabled(False)
        self.badge_label.setText("ENTERED" if enter else "SKIPPED")
        self.decided.emit(enter)


class ActivityFeed(QFrame):
    cleared = pyqtSignal()

    def __init__(self, network: QNetworkAccessManager):
        super().__init__()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(10)

        self._empty = QLabel(
            "No activity yet\n\n"
            "1. Paste your PHPSESSID and click Save\n"
            "2. Fetch Points\n"
            "3. Start Bot\n\n"
            "Entered giveaways, waiting states, and manual prompts will appear here."
        )
        self._empty.setObjectName("emptyState")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._layout.addWidget(self._empty, stretch=1)

        self._scroll.setWidget(self._container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)
        self._network = network

    def add_card(
        self,
        title: str,
        subtitle: str,
        image_url: str = "",
        status: str = "info",
    ) -> None:
        card = ActivityCard(
            title=title,
            subtitle=subtitle,
            image_url=image_url,
            status=status,
            network=self._network,
        )
        self._empty.hide()
        self._layout.addWidget(card)
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        )

    def add_manual_card(
        self,
        title: str,
        subtitle: str,
        image_url: str,
    ) -> ManualSelectCard:
        card = ManualSelectCard(
            title=title,
            subtitle=subtitle,
            image_url=image_url,
            network=self._network,
        )
        self._empty.hide()
        self._layout.addWidget(card)
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        )
        return card

    def clear(self) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._empty.show()
        self.cleared.emit()
