#!/usr/bin/env python3
"""
DAM Ingest Monitor — PySide6 floating progress window.

Launched by card_watcher as a detached subprocess when a card is inserted.
Polls ingest_status.json + tagger_status.json every 2s. Stays open until
manually closed — does not auto-close on completion.

Usage:
    python3 ingest_monitor.py --vol "Archive 2"
"""
import argparse
import json
import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from dam_config import DAM_ROOT, INGEST_STATUS_FILE, TAGGER_STATUS_FILE, THUMB_DIR

ACCENT = "#c8a96e"
REJECT = "#e05555"
BG = "#0e0e0e"
BG3 = "#1f1f1f"
BORDER = "#2a2a2a"
TEXT = "#d4d4d4"
TEXT_DIM = "#666666"

PHASE_LABELS = ["Copy", "Scan", "Thumbs", "Tag"]
LOG_FILE = DAM_ROOT / "card_watcher.log"


class PhaseDot(QLabel):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self.set_pending()

    def set_active(self):
        self.setText(f"● {self._label}")
        self.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")

    def set_done(self):
        self.setText(f"● {self._label}")
        self.setStyleSheet(f"color: {ACCENT}; font-size: 12px;")

    def set_pending(self):
        self.setText(f"○ {self._label}")
        self.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")


class IngestMonitorWindow(QDialog):
    def __init__(self, vol_name: str):
        super().__init__()
        self.vol_name = vol_name
        self.dest_root: str | None = None
        self._last_thumb_path: Path | None = None
        self._progress_anim: QPropertyAnimation | None = None
        self._opacity_anim: QPropertyAnimation | None = None
        self._opacity_anim_in: QPropertyAnimation | None = None

        self._build_ui()
        self._apply_styles()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(2000)
        self._poll()

    def _build_ui(self):
        self.setWindowTitle(f"DAM — {self.vol_name}")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setFixedWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        # Phase dots
        phase_row = QHBoxLayout()
        phase_row.setSpacing(16)
        self.phase_dots = [PhaseDot(label) for label in PHASE_LABELS]
        for dot in self.phase_dots:
            phase_row.addWidget(dot)
        phase_row.addStretch()
        root.addLayout(phase_row)

        # Thumbnail + counter/keywords
        info_row = QHBoxLayout()
        info_row.setSpacing(12)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(QSize(140, 93))
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(
            f"background: {BG3}; border: 1px solid {BORDER}; border-radius: 3px;"
        )
        self._opacity_effect = QGraphicsOpacityEffect(self.thumb_label)
        self._opacity_effect.setOpacity(1.0)
        self.thumb_label.setGraphicsEffect(self._opacity_effect)
        info_row.addWidget(self.thumb_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self.counter_label = QLabel("Starting\u2026")
        self.counter_label.setStyleSheet(f"color: {TEXT}; font-size: 13px;")
        text_col.addWidget(self.counter_label)
        self.keywords_label = QLabel("")
        self.keywords_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self.keywords_label.setWordWrap(True)
        self.keywords_label.setVisible(False)
        text_col.addWidget(self.keywords_label)
        text_col.addStretch()
        info_row.addLayout(text_col)
        root.addLayout(info_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        root.addWidget(self.progress_bar)

        # Log row
        log_row = QHBoxLayout()
        log_label = QLabel(str(LOG_FILE).replace(str(Path.home()), "~"))
        log_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        log_row.addWidget(log_label)
        log_row.addStretch()
        log_btn = QPushButton("Open in Finder")
        log_btn.setStyleSheet(
            f"QPushButton {{ color: {ACCENT}; background: transparent; border: none;"
            f" font-size: 10px; text-decoration: underline; }}"
            f"QPushButton:hover {{ color: {TEXT}; }}"
        )
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE.parent)))
        )
        log_row.addWidget(log_btn)
        root.addLayout(log_row)

    def _apply_styles(self):
        self.setStyleSheet(
            f"QDialog {{ background: {BG}; color: {TEXT}; }}"
            f"QProgressBar {{ background: {BG3}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}"
        )

    def _read_status(self, path: Path) -> dict:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _animate_progress(self, new_val: int):
        if self._progress_anim and self._progress_anim.state() == QPropertyAnimation.Running:
            self._progress_anim.stop()
        self._progress_anim = QPropertyAnimation(self.progress_bar, b"value")
        self._progress_anim.setDuration(300)
        self._progress_anim.setStartValue(self.progress_bar.value())
        self._progress_anim.setEndValue(new_val)
        self._progress_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._progress_anim.start()

    def _load_thumbnail(self, path: Path):
        if path == self._last_thumb_path or not path.exists():
            return
        self._last_thumb_path = path

        if self._opacity_anim and self._opacity_anim.state() == QPropertyAnimation.Running:
            self._opacity_anim.stop()

        fade_out = QPropertyAnimation(self._opacity_effect, b"opacity")
        fade_out.setDuration(200)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._opacity_anim = fade_out

        captured = path

        def _swap():
            pix = QPixmap(str(captured))
            if not pix.isNull():
                self.thumb_label.setPixmap(
                    pix.scaled(self.thumb_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            fade_in = QPropertyAnimation(self._opacity_effect, b"opacity")
            fade_in.setDuration(200)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade_in.start()
            self._opacity_anim_in = fade_in

        fade_out.finished.connect(_swap)
        fade_out.start()

    def _update_phase_dots(self, ingest_s: str, tagger_s: str):
        all_done = ingest_s == "idle" and tagger_s == "done"
        if tagger_s == "tagging":
            active = 3
        elif ingest_s == "thumbs":
            active = 2
        elif ingest_s == "scanning_db":
            active = 1
        elif ingest_s == "copying":
            active = 0
        else:
            active = -1

        for i, dot in enumerate(self.phase_dots):
            if all_done:
                dot.set_done()
            elif i == active:
                dot.set_active()
            elif i < active:
                dot.set_done()
            else:
                dot.set_pending()

    def _poll(self):
        ingest = self._read_status(INGEST_STATUS_FILE)
        tagger = self._read_status(TAGGER_STATUS_FILE)
        ingest_s = ingest.get("status", "")
        tagger_s = tagger.get("status", "")

        if not self.dest_root and ingest.get("dest_root"):
            self.dest_root = ingest["dest_root"]

        if ingest_s == "idle" and tagger_s == "done":
            self.setWindowTitle(f"DAM \u2014 Done \u2713  ({self.vol_name})")
        elif ingest_s == "error" or tagger_s == "error":
            self.setWindowTitle(f"DAM \u2014 Failed  ({self.vol_name})")

        self._update_phase_dots(ingest_s, tagger_s)

        is_tagging = tagger_s == "tagging"
        current = tagger.get("current") if is_tagging else ingest.get("current")
        total = tagger.get("total") if is_tagging else ingest.get("total")

        if total and total > 0:
            pct = min(100, int(round((current or 0) / total * 100)))
            if pct != self.progress_bar.value():
                self._animate_progress(pct)
            self.counter_label.setText(f"{current or 0} of {total} photos")
        else:
            self.counter_label.setText("Starting\u2026")

        if ingest_s == "idle" and tagger_s == "done":
            if self.progress_bar.value() < 100:
                self._animate_progress(100)
            self.counter_label.setText(f"Complete \u2014 {total or '?'} photos tagged")

        keywords = tagger.get("last_keywords") or []
        if is_tagging and keywords:
            self.keywords_label.setText(" \u00b7 ".join(keywords))
            self.keywords_label.setVisible(True)
        else:
            self.keywords_label.setVisible(False)

        if is_tagging and tagger.get("current_id"):
            self._load_thumbnail(THUMB_DIR / f"{tagger['current_id']}.jpg")
        elif ingest_s == "copying" and ingest.get("current_path") and self.dest_root:
            candidate = Path(self.dest_root) / ingest["current_path"]
            if candidate.suffix.lower() in (".jpg", ".jpeg"):
                self._load_thumbnail(candidate)


def main():
    parser = argparse.ArgumentParser(description="DAM Ingest Monitor")
    parser.add_argument("--vol", default="Card", help="Volume label for window title")
    args = parser.parse_args()

    qt_app = QApplication(sys.argv)
    window = IngestMonitorWindow(args.vol)
    window.show()
    # Start the Qt event loop (PySide6: QApplication.exec())
    raise SystemExit(qt_app.exec())


if __name__ == "__main__":
    main()
