from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
        ends_text: str = "",
        source: str = "steamgifts",
    ):
        super().__init__()
        self.setObjectName("activityCard")
        self._network = network

        colors = {
            "entered": ("#1f2a1f", "#3d5c3f", "#a3d9a5"),
            "won": ("#2a2418", "#6b552e", "#f0c674"),
            "waiting": ("#2a2618", "#6b5a2e", "#d4b86a"),
            "prompt": ("#222222", "#4a4a4a", "#d4d4d4"),
            "skipped": ("#1c1c1c", "#3a3a3a", "#9ca3af"),
            "info": ("#1c1c1c", "#333333", "#b0b0b0"),
            "error": ("#2a1a1a", "#5c3d3d", "#e8a0a0"),
        }
        bg, border, accent = colors.get(status, colors["info"])
        badge_text = {
            "entered": "ENTERED",
            "won": "WON",
            "waiting": "WAITING",
            "prompt": "SELECT",
            "skipped": "SKIPPED",
        }.get(status, status.upper())
        if status == "entered" and source == "indiegala":
            badge_text = "INDIEGALA"
        if status == "won" and source == "indiegala":
            badge_text = "INDIEGALA WIN"

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
                font-size: 12px;
            }}
            QLabel#endsLabel {{
                color: {accent};
                font-size: 11px;
                font-weight: 600;
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

        self.setFixedHeight(112 if ends_text else 96)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.image_label = QLabel()
        self.image_label.setFixedSize(184, 69)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            "background: #141414; border: 1px solid #333333; border-radius: 8px; color: #6b6b6b;"
        )
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

        self.ends_label = QLabel(ends_text)
        self.ends_label.setObjectName("endsLabel")
        self.ends_label.setWordWrap(True)
        if ends_text:
            text_col.addWidget(self.ends_label)
        else:
            self.ends_label.hide()

        layout.addLayout(text_col, stretch=1)

        if image_url and network is not None:
            self._load_image(image_url)

    def update_content(
        self, title: str, subtitle: str, ends_text: str = ""
    ) -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        if ends_text:
            self.ends_label.setText(ends_text)
            self.ends_label.show()
            self.setFixedHeight(112)
        else:
            self.ends_label.hide()
            self.setFixedHeight(96)

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
        ends_text: str = "",
        source: str = "steamgifts",
    ):
        super().__init__(
            title=title,
            subtitle=subtitle,
            image_url=image_url,
            status="prompt",
            network=network,
            ends_text=ends_text,
            source=source,
        )
        self.setFixedHeight(148 if ends_text else 132)

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
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

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
        self._layout.addWidget(self._empty)
        self._layout.addStretch(1)

        self._scroll.setWidget(self._container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)
        self._network = network
        self._waiting_card: ActivityCard | None = None

    def _insert_card(self, widget: QWidget) -> None:
        self._layout.insertWidget(self._layout.count() - 1, widget)

    def set_waiting_card(
        self,
        title: str,
        subtitle: str,
        image_url: str = "",
        ends_text: str = "",
        source: str = "steamgifts",
    ) -> None:
        self._empty.hide()
        if self._waiting_card is not None:
            self._waiting_card.update_content(title, subtitle, ends_text)
        else:
            self._waiting_card = ActivityCard(
                title=title,
                subtitle=subtitle,
                image_url=image_url,
                status="waiting",
                network=self._network,
                ends_text=ends_text,
                source=source,
            )
            self._insert_card(self._waiting_card)
        self._scroll.verticalScrollBar().setValue(0)

    def clear_waiting_card(self) -> None:
        if self._waiting_card is None:
            return
        self._layout.removeWidget(self._waiting_card)
        self._waiting_card.deleteLater()
        self._waiting_card = None
        if self._layout.count() == 2:
            self._empty.show()

    def add_card(
        self,
        title: str,
        subtitle: str,
        image_url: str = "",
        status: str = "info",
        ends_text: str = "",
        source: str = "steamgifts",
    ) -> None:
        card = ActivityCard(
            title=title,
            subtitle=subtitle,
            image_url=image_url,
            status=status,
            network=self._network,
            ends_text=ends_text,
            source=source,
        )
        self._empty.hide()
        self.clear_waiting_card()
        self._insert_card(card)
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        )

    def add_manual_card(
        self,
        title: str,
        subtitle: str,
        image_url: str,
        ends_text: str = "",
        source: str = "steamgifts",
    ) -> ManualSelectCard:
        card = ManualSelectCard(
            title=title,
            subtitle=subtitle,
            image_url=image_url,
            network=self._network,
            ends_text=ends_text,
            source=source,
        )
        self._empty.hide()
        self.clear_waiting_card()
        self._insert_card(card)
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        )
        return card

    def clear(self) -> None:
        self._waiting_card = None
        while self._layout.count() > 2:
            item = self._layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._empty.show()
        self.cleared.emit()


class EnteredGiveawayCard(QFrame):
    remove_requested = pyqtSignal(str, str)

    def __init__(
        self,
        name: str,
        code: str,
        cost: int,
        image_url: str,
        remaining_label: str,
        entries_count: str,
        entered_label: str,
        xsrf_token: str,
        network: QNetworkAccessManager,
    ):
        super().__init__()
        self.code = code
        self.xsrf_token = xsrf_token
        self.setObjectName("activityCard")

        accent = "#7ec8e3"
        self.setStyleSheet(
            f"""
            QFrame#activityCard {{
                background: #1a2228;
                border: 1px solid #2d4a5c;
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
                font-size: 12px;
            }}
            QLabel#remainingLabel {{
                color: {accent};
                font-size: 13px;
                font-weight: 700;
            }}
            """
        )

        self.setFixedHeight(112)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.image_label = QLabel()
        self.image_label.setFixedSize(184, 69)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            "background: #141414; border: 1px solid #333333; border-radius: 8px; color: #6b6b6b;"
        )
        self.image_label.setText("…")
        layout.addWidget(self.image_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        self.title_label = QLabel(name)
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)
        text_col.addWidget(self.title_label)

        meta_parts = [f"{cost}P"]
        if entries_count:
            meta_parts.append(f"{entries_count} entries")
        if entered_label:
            meta_parts.append(f"entered {entered_label}")
        self.subtitle_label = QLabel(" · ".join(meta_parts))
        self.subtitle_label.setObjectName("subtitle")
        self.subtitle_label.setWordWrap(True)
        text_col.addWidget(self.subtitle_label)

        self.remaining_label = QLabel(remaining_label)
        self.remaining_label.setObjectName("remainingLabel")
        self.remaining_label.setWordWrap(True)
        text_col.addWidget(self.remaining_label)

        layout.addLayout(text_col, stretch=1)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("dangerBtn")
        self.remove_btn.setFixedWidth(88)
        self.remove_btn.clicked.connect(self._on_remove)
        layout.addWidget(self.remove_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        if image_url:
            request = QNetworkRequest(QUrl(image_url))
            reply = network.get(request)
            reply.finished.connect(lambda: self._on_image_loaded(reply))

    def _on_remove(self) -> None:
        self.remove_btn.setEnabled(False)
        self.remove_btn.setText("…")
        self.remove_requested.emit(self.code, self.xsrf_token)

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


class EnteredFeed(QFrame):
    refresh_requested = pyqtSignal()
    remove_requested = pyqtSignal(str, str)

    def __init__(self, network: QNetworkAccessManager):
        super().__init__()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        header = QHBoxLayout()
        self.summary_label = QLabel("Active entered giveaways")
        self.summary_label.setObjectName("hint")
        header.addWidget(self.summary_label)
        header.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("accentBtn")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_btn)
        outer.addLayout(header)

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
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty = QLabel(
            "No active entered giveaways\n\n"
            "Click Refresh to load open entries from steamgifts.com."
        )
        self._empty.setObjectName("emptyState")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._layout.addWidget(self._empty)
        self._layout.addStretch(1)

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, stretch=1)

        self._network = network
        self._cards: dict[str, EnteredGiveawayCard] = {}

    def set_loading(self, loading: bool) -> None:
        self.refresh_btn.setEnabled(not loading)
        self.refresh_btn.setText("Refreshing…" if loading else "Refresh")

    def set_giveaways(self, giveaways: list) -> None:
        for card in self._cards.values():
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        if not giveaways:
            self._empty.show()
            self.summary_label.setText("Active entered giveaways · 0 open")
            return

        self._empty.hide()
        self.summary_label.setText(
            f"Active entered giveaways · {len(giveaways)} open"
        )

        for info in giveaways:
            card = EnteredGiveawayCard(
                name=info.name,
                code=info.code,
                cost=info.cost,
                image_url=info.image_url,
                remaining_label=info.remaining_label,
                entries_count=info.entries_count,
                entered_label=info.entered_label,
                xsrf_token=info.xsrf_token,
                network=self._network,
            )
            card.remove_requested.connect(self.remove_requested.emit)
            self._cards[info.code] = card
            self._layout.insertWidget(self._layout.count() - 1, card)

    def remove_card(self, code: str) -> None:
        card = self._cards.pop(code, None)
        if card is None:
            return

        self._layout.removeWidget(card)
        card.deleteLater()

        count = len(self._cards)
        self.summary_label.setText(
            f"Active entered giveaways · {count} open"
        )
        if count == 0:
            self._empty.show()


class WinsFeed(QFrame):
    def __init__(self, network: QNetworkAccessManager):
        super().__init__()

        header = QHBoxLayout()
        self.summary_label = QLabel("Unclaimed wins · 0")
        self.summary_label.setObjectName("settingHint")
        header.addWidget(self.summary_label)
        header.addStretch()
        self.setLayout(QVBoxLayout())
        self.layout().addLayout(header)

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
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty = QLabel(
            "No unclaimed wins\n\n"
            "Only giveaways you still need to receive appear here. "
            "Already received prizes are hidden."
        )
        self._empty.setObjectName("emptyState")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._layout.addWidget(self._empty)
        self._layout.addStretch(1)

        self._scroll.setWidget(self._container)
        self.layout().addWidget(self._scroll, stretch=1)
        self._network = network

    def set_wins(self, wins: list) -> None:
        while self._layout.count() > 2:
            item = self._layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not wins:
            self._empty.show()
            self.summary_label.setText("Unclaimed wins · 0")
            return

        self._empty.hide()
        self.summary_label.setText(
            f"Unclaimed wins · {len(wins)}"
        )

        for win in wins:
            source = getattr(win, "source", "steamgifts")
            platform = "IndieGala" if source == "indiegala" else "SteamGifts"
            card = ActivityCard(
                title=win.name,
                subtitle=f"Not received yet · claim on {platform}",
                image_url=getattr(win, "image_url", ""),
                status="won",
                network=self._network,
                source=source,
            )
            self._layout.insertWidget(self._layout.count() - 1, card)
