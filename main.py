#!/usr/bin/python

import json
import re
import sys
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


ORANGE = "#e95420"
BACKGROUND = "#fbf6ed"
PANEL = "#fff9ef"
INK = "#181410"
SOFT = "#5a4f44"
DIM = "#9a8d80"
LINE = "#e8dfcf"
FOSS_RE = re.compile(
    r"\b(Apache-2\.0|BSD-[234]-Clause|GPL-[23]\.0|LGPL-[23]\.[01]|"
    r"AGPL-3\.0|MIT|MPL-[12]\.[01]|ISC|Unlicense|CC0-1\.0|Zlib|"
    r"BSL-1\.0|EPL-[12]\.0|Python-2\.0|WTFPL|CDDL-1\.[01]|"
    r"PostgreSQL|X11|NCSA)\b",
    re.IGNORECASE,
)


def elide(text, length=72):
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def size_text(value):
    if not value:
        return ""
    units = ("B", "KB", "MB", "GB")
    index = 0
    value = float(value)
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f}{units[index]}" if value < 10 else f"{value:.0f}{units[index]}"


class SnapCard(QFrame):
    activated = Signal(dict)

    def __init__(self, snap, parent=None):
        super().__init__(parent)
        self.snap = snap
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.icon = QLabel((snap.get("title") or snap.get("name") or "?")[0].upper())
        self.icon.setObjectName("icon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setFixedSize(56, 56)
        header.addWidget(self.icon)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title = QLabel(snap.get("title") or snap.get("name") or "Unknown")
        self.title.setObjectName("cardTitle")
        self.title.setToolTip(self.title.text())
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_box.addWidget(self.title)
        publisher_name = snap.get("developer_name") or snap.get("publisher") or "unknown"
        self.publisher = QLabel(publisher_name)
        self.publisher.setObjectName("publisher")
        self.publisher.setToolTip(publisher_name)
        self.publisher.setWordWrap(True)
        self.publisher.setMinimumWidth(0)
        self.publisher.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if snap.get("developer_validation") == "verified":
            self.publisher.setText(publisher_name + "  ✓")
        elif snap.get("developer_validation") == "starred":
            self.publisher.setText(publisher_name + "  ★")
        title_box.addWidget(self.publisher)
        header.addLayout(title_box, 1)
        layout.addLayout(header)

        self.summary = QLabel(snap.get("summary") or snap.get("description") or "—")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("summary")
        layout.addWidget(self.summary)

        metadata = QHBoxLayout()
        for arch in (snap.get("architecture") or [])[:3]:
            metadata.addWidget(self.pill(arch))
        if snap.get("confinement"):
            metadata.addWidget(self.pill(snap["confinement"], ORANGE))
        license_name = snap.get("license")
        if license_name:
            metadata.addWidget(self.pill("FOSS" if FOSS_RE.search(license_name) else "prop", "#2d6a40" if FOSS_RE.search(license_name) else DIM))
        if snap.get("binary_filesize"):
            metadata.addWidget(self.pill(size_text(snap["binary_filesize"]), DIM))
        if snap.get("ratings_average", 0) > 0:
            rating = QLabel(f"★ {snap['ratings_average']:.1f}")
            rating.setObjectName("rating")
            rating.setFixedHeight(24)
            rating.setAlignment(Qt.AlignmentFlag.AlignCenter)
            metadata.addWidget(rating)
        metadata.addStretch()
        metadata.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addLayout(metadata)
        QTimer.singleShot(0, self.refresh_text_heights)

    def refresh_text_heights(self):
        if not self.width():
            return
        text_width = max(1, self.width() - 32)
        header_width = max(1, text_width - 64)
        self.title.setMinimumHeight(max(1, self.title.heightForWidth(header_width)))
        self.publisher.setMinimumHeight(max(1, self.publisher.heightForWidth(header_width)))
        self.summary.setMinimumHeight(max(1, self.summary.heightForWidth(text_width)))

    @staticmethod
    def pill(text, color=SOFT):
        label = QLabel(text)
        label.setFixedHeight(24)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        label.setStyleSheet(f"color: {color}; background: #f5efe5; padding: 2px 5px; border-radius: 3px;")
        return label

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.snap)
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_text_heights()


class IconSignals(QObject):
    finished = Signal(object, bytes)


class IconTask(QRunnable):
    def __init__(self, card, url, parent):
        super().__init__()
        self.card = card
        self.url = url
        self.signals = IconSignals(parent)
        self.setAutoDelete(False)

    def run(self):
        try:
            request = urllib.request.Request(self.url, headers={"User-Agent": "Snapcraft Explorer"})
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read()
            self.signals.finished.emit(self.card, data)
        except Exception:
            self.signals.finished.emit(self.card, b"")


class DetailDialog(QDialog):
    def __init__(self, snap, parent=None):
        super().__init__(parent)
        self.setWindowTitle(snap.get("title") or snap.get("name") or "Snap details")
        self.resize(720, 620)
        layout = QVBoxLayout(self)

        title = QLabel(snap.get("title") or snap.get("name") or "Unknown")
        title.setObjectName("detailTitle")
        layout.addWidget(title)
        publisher = QLabel(snap.get("developer_name") or snap.get("publisher") or "unknown")
        publisher.setObjectName("publisher")
        layout.addWidget(publisher)

        slug = snap.get("package_name") or (snap.get("name") or "").split(".")[0]
        flag = " --classic" if snap.get("confinement") == "classic" else " --devmode" if snap.get("confinement") == "devmode" else ""
        command = f"sudo snap install {slug}{flag}"
        command_box = QHBoxLayout()
        command_label = QLabel(command)
        command_label.setObjectName("command")
        command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        command_box.addWidget(command_label, 1)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(command))
        command_box.addWidget(copy)
        layout.addLayout(command_box)

        description = QLabel(snap.get("description") or snap.get("summary") or "No description provided.")
        description.setWordWrap(True)
        description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(description)

        details = []
        for key in ("version", "channel", "confinement", "base", "license"):
            if snap.get(key):
                details.append(f"<b>{key}</b>: {snap[key]}")
        if snap.get("binary_filesize"):
            details.append(f"<b>size</b>: {size_text(snap['binary_filesize'])}")
        if snap.get("architecture"):
            details.append(f"<b>architectures</b>: {' · '.join(snap['architecture'])}")
        metadata = QLabel("<br>".join(details))
        metadata.setTextFormat(Qt.TextFormat.RichText)
        metadata.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(metadata)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SearchSignals(QObject):
    finished = Signal(int, object, str)


class SearchTask(QRunnable):
    def __init__(self, request_id, params, parent):
        super().__init__()
        self.request_id = request_id
        self.params = params
        self.signals = SearchSignals(parent)
        self.setAutoDelete(False)

    def run(self):
        query = urllib.parse.urlencode({key: value for key, value in self.params.items() if value})
        url = f"https://api.snapcraft.io/api/v1/snaps/search?{query}"
        request = urllib.request.Request(url, headers={"Accept": "application/hal+json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            self.signals.finished.emit(self.request_id, data, "")
        except Exception as error:
            self.signals.finished.emit(self.request_id, None, str(error))


class Explorer(QMainWindow):
    categories = [
        ("featured", "featured"), ("", "all"), ("development", "development"),
        ("productivity", "productivity"), ("games", "games"), ("utilities", "utilities"),
        ("photo-and-video", "photo & video"), ("music-and-audio", "music & audio"),
        ("entertainment", "entertainment"), ("social", "social"), ("art-and-design", "art & design"),
        ("education", "education"), ("finance", "finance"), ("science", "science"),
        ("security", "security"), ("server-and-cloud", "server & cloud"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Snapcraft Explorer")
        self.resize(1440, 980)
        self.thread_pool = QThreadPool.globalInstance()
        self.tasks = {}
        self.icon_tasks = set()
        self.results = []
        self.page = 0
        self.total = 0
        self.loading = False
        self.request_id = 0
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.search)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        brand = QLabel("<b>Snapcraft <i>Explorer</i></b><br><small>browse the linux snap store</small>")
        brand.setObjectName("brand")
        toolbar_layout.addWidget(brand)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("search the snap store — firefox, vlc, blender…")
        self.search_input.textChanged.connect(lambda: self.debounce.start(300))
        toolbar_layout.addWidget(self.search_input, 1)
        self.arch = QComboBox()
        self.arch.addItems(["amd64", "arm64", "armhf", "i386", "ppc64el", "s390x", "riscv64"])
        self.arch.currentTextChanged.connect(self.search)
        toolbar_layout.addWidget(self.arch)
        self.confinement = QComboBox()
        self.confinement.addItems(["any confine", "strict", "classic", "devmode"])
        self.confinement.currentIndexChanged.connect(self.search)
        toolbar_layout.addWidget(self.confinement)
        self.promoted = self.toggle("promoted", True)
        self.free = self.toggle("FOSS only", False)
        toolbar_layout.addWidget(self.promoted)
        toolbar_layout.addWidget(self.free)
        outer.addWidget(toolbar)

        categories = QScrollArea()
        categories.setWidgetResizable(True)
        categories.setFixedHeight(58)
        category_widget = QWidget()
        category_layout = QHBoxLayout(category_widget)
        category_layout.setContentsMargins(16, 8, 16, 8)
        self.category_buttons = []
        for category, label in self.categories:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked, value=category: self.set_category(value))
            category_layout.addWidget(button)
            self.category_buttons.append((category, button))
        category_layout.addStretch()
        categories.setWidget(category_widget)
        outer.addWidget(categories)

        status_row = QHBoxLayout()
        self.status = QLabel("loading featured snaps…")
        status_row.addWidget(self.status)
        status_row.addStretch()
        status_row.addWidget(QLabel("native app · direct API"))
        outer.addLayout(status_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setMinimumWidth(0)
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 8, 0, 24)
        self.grid.setSpacing(16)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)
        self.load_more = QPushButton("Load more snaps")
        self.load_more.clicked.connect(self.load_next_page)
        self.load_more.hide()
        outer.addWidget(self.load_more)

        self.promoted.clicked.connect(self.search)
        self.free.clicked.connect(self.search)
        self.set_category("featured")
        self.apply_styles()
        self.search()

    def toggle(self, text, checked):
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setChecked(checked)
        return button

    def set_category(self, category):
        self.category = category
        for value, button in self.category_buttons:
            button.setChecked(value == category)
        self.search()

    def search(self):
        self.request_id += 1
        self.loading = False
        self.page = 0
        self.results = []
        self.clear_cards()
        self.load_page()

    def load_next_page(self):
        if not self.loading and self.page:
            self.load_page()

    def load_page(self):
        if self.loading:
            return
        self.loading = True
        self.request_id += 1
        request_id = self.request_id
        self.status.setText("searching the Snap Store…")
        params = {
            "size": 24,
            "page": self.page + 1,
            "section": self.category,
            "q": self.search_input.text().strip(),
            "confinement": "" if self.confinement.currentIndex() == 0 else self.confinement.currentText(),
        }
        if self.promoted.isChecked():
            params["promoted"] = "true"
        if self.free.isChecked():
            params["exclude_non_free"] = "true"
        task = SearchTask(request_id, params, self)
        task.signals.finished.connect(self.finish_request)
        self.tasks[request_id] = task
        self.thread_pool.start(task)

    def finish_request(self, request_id, data, error):
        self.tasks.pop(request_id, None)
        if request_id != self.request_id:
            return
        self.loading = False
        if error:
            self.status.setText(f"Could not reach the Snap Store: {error}")
            return
        incoming = data.get("_embedded", {}).get("clickindex:package", [])
        arch = self.arch.currentText()
        filtered = [snap for snap in incoming if arch in snap.get("architecture", [])]
        existing = {snap.get("name") for snap in self.results}
        added = [snap for snap in filtered if snap.get("name") not in existing]
        self.results.extend(added)
        self.page += 1
        self.total = data.get("total", len(self.results))
        self.render_cards(added)
        self.status.setText(f"showing {len(self.results)} of {self.total} · {arch}")
        self.load_more.setVisible(bool(data.get("_links", {}).get("next")) and bool(incoming))

    def clear_cards(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def render_cards(self, snaps):
        viewport_width = max(1, self.scroll.viewport().width())
        self.content.setFixedWidth(max(1, viewport_width - 20))
        columns = max(1, viewport_width // 280)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        for index, snap in enumerate(snaps):
            card = SnapCard(snap)
            card.activated.connect(self.show_details)
            self.grid.addWidget(card, (self.grid.count()) // columns, (self.grid.count()) % columns)
            icon_url = snap.get("icon_url")
            if icon_url:
                task = IconTask(card, icon_url, self)
                task.signals.finished.connect(self.finish_icon)
                self.icon_tasks.add(task)
                self.thread_pool.start(task)

    def finish_icon(self, card, data):
        for task in tuple(self.icon_tasks):
            if task.card is card:
                self.icon_tasks.remove(task)
                break
        if not data:
            return
        try:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                card.icon.setPixmap(pixmap.scaled(
                    card.icon.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                card.icon.setText("")
        except RuntimeError:
            pass

    def show_details(self, snap):
        DetailDialog(snap, self).exec()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.reflow_grid)

    def reflow_grid(self):
        if self.results:
            self.clear_cards()
            self.render_cards(self.results)
        else:
            self.content.setFixedWidth(max(1, self.scroll.viewport().width()))

    def apply_styles(self):
        self.setStyleSheet(
            f"""
            QWidget {{ background: {BACKGROUND}; color: {INK}; font-family: 'Source Sans 3', sans-serif; font-size: 14px; }}
            QLabel {{ background: transparent; }}
            #toolbar {{ background: rgba(251,246,237,0.96); border-bottom: 1px solid {LINE}; padding: 8px; }}
            #brand {{ font-family: Newsreader, serif; font-size: 20px; min-width: 190px; }}
            #brand i {{ color: {ORANGE}; font-weight: normal; }}
            #brand small {{ color: {DIM}; font-family: monospace; font-size: 10px; text-transform: uppercase; }}
            QLineEdit, QComboBox, QToolButton, QPushButton {{ background: white; border: 1px solid {LINE}; padding: 8px; }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ORANGE}; }}
            QToolButton:checked, QPushButton:checked {{ background: {ORANGE}; color: white; }}
            QScrollArea {{ border: none; background: transparent; }}
            #card {{ background: white; border: 1px solid {LINE}; border-radius: 4px; }}
            #card:hover {{ border: 1px solid {ORANGE}; }}
            #icon {{ background: {BACKGROUND}; border: 1px solid {LINE}; color: {ORANGE}; font-family: Newsreader; font-size: 22px; font-weight: bold; }}
            #cardTitle {{ font-family: Newsreader; font-size: 16px; font-weight: bold; }}
            #publisher, #summary {{ color: {SOFT}; }}
            #summary {{ min-height: 42px; }}
            #rating {{ color: #d4a90a; }}
            #detailTitle {{ font-family: Newsreader; font-size: 28px; font-weight: bold; }}
            #command {{ background: {INK}; color: white; padding: 12px; font-family: monospace; }}
            """
        )

    def closeEvent(self, event):
        self.thread_pool.waitForDone(2000)
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = Explorer()
    window.show()
    sys.exit(app.exec())
