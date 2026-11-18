# -*- coding: utf-8 -*-
"""
Syntra 星樞 · Word 風格全域文字大小與縮放引擎 (Word-Style Font Scaler)
提供：
1. Word 標準字級清單 (8 ~ 72 pt) 與自訂字級輸入支援
2. A▲ (放大字級) / A▼ (縮小字級) 階梯調節
3. 狀態列右下角 Word 風格縮放滑桿 (50% ~ 300%) 與百分比快速選單
4. Ctrl + 滑鼠滾輪、Ctrl++/Ctrl+-/Ctrl+0、Ctrl+Shift+>/Ctrl+Shift+< 全域快捷鍵
5. 自動遞迴縮放全介面 QSS、QLabel 內嵌 HTML、QTextBrowser 對話氣泡、終端機與自繪元件 (UsageBar / AgentCanvas)
"""
from __future__ import annotations

import re
import weakref
from typing import List, Optional, Tuple

from PyQt5.QtCore import QEvent, QObject, QSettings, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence, QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QShortcut,
    QSlider,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QWidget,
)

# 預設基準字級 (13pt = 100%)
BASE_FONT_PT: float = 13.0
MIN_FONT_PT: float = 6.5    # 50%
MAX_FONT_PT: float = 72.0   # Word 最大標準字級
SLIDER_MIN_PCT: int = 50
SLIDER_MAX_PCT: int = 300

# Microsoft Word 標準字號階梯
WORD_FONT_SIZES: List[float] = [
    8, 9, 10, 10.5, 11, 12, 13, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72
]

# Word 狀態列常用縮放百分比
ZOOM_PRESETS: List[Tuple[int, str]] = [
    (50, "50% (6.5pt)"),
    (75, "75% (10pt)"),
    (90, "90% (12pt)"),
    (100, "100% 預設 (13pt)"),
    (115, "115% (15pt)"),
    (125, "125% (16pt)"),
    (150, "150% (20pt)"),
    (175, "175% (23pt)"),
    (200, "200% (26pt)"),
    (250, "250% (32.5pt)"),
    (300, "300% (39pt)"),
]

_FONT_SIZE_RE = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)\s*(px|pt)", re.IGNORECASE)


def fmt_pt(pt: float) -> str:
    """將字級格式化為乾淨字串，例如 13.0 -> '13', 10.5 -> '10.5'"""
    rounded = round(float(pt) * 2) / 2
    if abs(rounded - int(rounded)) < 1e-4:
        return str(int(rounded))
    return f"{rounded:.1f}"


def clamp_pt(pt: float) -> float:
    return max(MIN_FONT_PT, min(MAX_FONT_PT, round(float(pt) * 2) / 2))


def pt_to_scale(pt: float) -> float:
    return clamp_pt(pt) / BASE_FONT_PT


def pt_to_pct(pt: float) -> int:
    return int(round(pt_to_scale(pt) * 100))


def pct_to_pt(pct: float) -> float:
    return clamp_pt(BASE_FONT_PT * (float(pct) / 100.0))


def next_word_size(current_pt: float, step: int) -> float:
    """
    依照 Word 的 A▲ / A▼ 邏輯切換下一個或上一個字號：
    - step > 0: 跳至大於 current_pt 的下一個 WORD_FONT_SIZES
    - step < 0: 跳至小於 current_pt 的上一個 WORD_FONT_SIZES
    """
    cur = clamp_pt(current_pt)
    if step > 0:
        for s in WORD_FONT_SIZES:
            if s > cur + 0.05:
                return float(s)
        return clamp_pt(cur + step * 1.0)
    elif step < 0:
        for s in reversed(WORD_FONT_SIZES):
            if s < cur - 0.05:
                return float(s)
        return clamp_pt(cur + step * 1.0)
    return cur


def current_app_scale() -> float:
    """取得目前 QApplication 的全域字體縮放倍率（供 UsageBar / AgentCanvas 等自繪元件查詢）"""
    app = QApplication.instance()
    if app is not None:
        val = app.property("ui_font_scale")
        if isinstance(val, (int, float)) and val > 0:
            return float(val)
    return 1.0


def current_app_pt() -> float:
    app = QApplication.instance()
    if app is not None:
        val = app.property("ui_font_pt")
        if isinstance(val, (int, float)) and val > 0:
            return float(val)
    return BASE_FONT_PT


def scale_css_font_sizes(text: str, scale: float) -> str:
    """將 QSS 或 HTML 字串中所有 font-size: Xpx / Xpt 依比例縮放"""
    if not text or "font-size" not in text.lower():
        return text
    if abs(scale - 1.0) < 1e-3:
        return text

    def _repl(match: re.Match) -> str:
        prefix = match.group(1)
        base_val = float(match.group(2))
        unit = match.group(3)
        scaled_val = max(6.0, round(base_val * scale, 1))
        if abs(scaled_val - int(scaled_val)) < 1e-4:
            return f"{prefix}{int(scaled_val)}{unit}"
        return f"{prefix}{scaled_val:.1f}{unit}"

    return _FONT_SIZE_RE.sub(_repl, text)


def hook_text_browser_scaling(browser: QTextBrowser):
    """攔截 QTextBrowser 的 setHtml 與 append，使任何寫入對話框的 HTML 自動依目前字級縮放"""
    if getattr(browser, "_font_scaler_hooked", False):
        return
    browser._font_scaler_hooked = True
    orig_set_html = browser.setHtml
    orig_append = browser.append

    def _scaled_set_html(html_str: str):
        return orig_set_html(scale_css_font_sizes(html_str, current_app_scale()))

    def _scaled_append(html_str: str):
        return orig_append(scale_css_font_sizes(html_str, current_app_scale()))

    browser.setHtml = _scaled_set_html
    browser.append = _scaled_append


def apply_scale_to_widget_tree(root: QWidget, scale: float):
    """
    遞迴將縮放倍率套用至指定 Widget 及其所有子元件：
    - 自動記憶每個元件原始未縮放的 QSS (_orig_qss)，避免多次縮放累積誤差；
      若業務邏輯動態改了 styleSheet，也會自動偵測並以新樣式重新縮放。
    - 自動縮放 QLabel 內含 font-size 的 HTML 標籤文字。
    - 自動縮放 QPlainTextEdit / QTextEdit / QTextBrowser 的預設字型大小。
    """
    if root is None:
        return

    widgets: List[QWidget] = [root]
    widgets.extend(root.findChildren(QWidget))

    for w in widgets:
        if w.property("_skip_font_scaler"):
            continue

        if isinstance(w, QTextBrowser):
            hook_text_browser_scaling(w)

        # 1. 縮放元件本身的 QSS (styleSheet)
        try:
            cur_qss = w.styleSheet()
            if cur_qss and "font-size" in cur_qss.lower():
                last_scaled = w.property("_last_scaled_qss")
                orig_qss = w.property("_orig_qss")
                if orig_qss is None or (last_scaled is not None and cur_qss != last_scaled):
                    orig_qss = cur_qss
                    w.setProperty("_orig_qss", orig_qss)
                new_qss = scale_css_font_sizes(orig_qss, scale)
                w.setProperty("_last_scaled_qss", new_qss)
                if cur_qss != new_qss:
                    w.setStyleSheet(new_qss)
        except Exception:
            pass

        # 2. 縮放 QLabel 內嵌 HTML 的 font-size
        if isinstance(w, QLabel):
            try:
                txt = w.text()
                if txt and "font-size" in txt.lower():
                    last_html = w.property("_last_scaled_html")
                    orig_html = w.property("_orig_html")
                    if orig_html is None or (last_html is not None and txt != last_html):
                        orig_html = txt
                        w.setProperty("_orig_html", orig_html)
                    new_html = scale_css_font_sizes(orig_html, scale)
                    w.setProperty("_last_scaled_html", new_html)
                    if txt != new_html:
                        w.setText(new_html)
            except Exception:
                pass

        # 3. 縮放 QPlainTextEdit / QTextBrowser / QTextEdit 的 document defaultFont 與 Widget Font
        if isinstance(w, (QPlainTextEdit, QTextBrowser, QTextEdit)):
            try:
                f = QFont(w.font())
                base_doc_pt = w.property("_orig_doc_font_pt")
                if base_doc_pt is None:
                    pt = f.pointSizeF()
                    base_doc_pt = pt if pt > 0 else 10.0
                    w.setProperty("_orig_doc_font_pt", float(base_doc_pt))
                new_doc_pt = max(6.0, round(float(base_doc_pt) * scale, 1))
                f.setPointSizeF(new_doc_pt)
                w.setFont(f)
                if hasattr(w, "document") and w.document() is not None:
                    df = QFont(w.document().defaultFont())
                    df.setPointSizeF(max(6.0, round(10.5 * scale, 1)))
                    w.document().setDefaultFont(df)
                if w.__class__.__name__ == "PromptTextEdit" and getattr(w, "_manual_height", None) is None:
                    min_h = max(38, int(round(38 * scale)))
                    max_h = max(140, int(round(140 * scale)))
                    doc_h = int(w.document().size().height()) + int(round(14 * scale))
                    w.setFixedHeight(max(min_h, min(max_h, doc_h)))
            except Exception:
                pass

        # 4. 解除因固定高度 (setFixedHeight) 在放大字體時裁切文字的按鈕與工具列
        if isinstance(w, QPushButton) and not w.property("_skip_font_scaler"):
            try:
                base_fh = w.property("_orig_fixed_h")
                if base_fh is None and w.minimumHeight() == w.maximumHeight() and 18 <= w.minimumHeight() <= 34:
                    if w.minimumWidth() != w.maximumWidth() or w.minimumWidth() == 0:
                        base_fh = w.minimumHeight()
                        w.setProperty("_orig_fixed_h", int(base_fh))
                if base_fh is not None:
                    scaled_h = max(int(base_fh), int(round(int(base_fh) * scale)))
                    w.setFixedHeight(scaled_h)
            except Exception:
                pass


class WordFontSizeToolbarWidget(QWidget):
    """
    Word 風格頂部工具列字級控制組件：
    [ 🔤 ] [ 字號下拉/手輸框 (8~72) ▾ ] [ A▲ ] [ A▼ ]
    """
    sig_font_pt_changed = pyqtSignal(float)
    sig_step_requested = pyqtSignal(int)

    def __init__(self, initial_pt: float = BASE_FONT_PT, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("_skip_font_scaler", True)
        self._updating = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(3)

        lbl_icon = QLabel("🔤")
        lbl_icon.setProperty("_skip_font_scaler", True)
        lbl_icon.setToolTip("全域文字大小 (Word 字級調節：可直接輸入數字或點選，亦支援 Ctrl + 滑鼠滾輪)")
        lbl_icon.setStyleSheet("background: transparent; font-size: 13px; padding: 0 2px;")
        layout.addWidget(lbl_icon)

        # Word 可編輯字號下拉選單
        self.combo_size = QComboBox()
        self.combo_size.setProperty("_skip_font_scaler", True)
        self.combo_size.setEditable(True)
        self.combo_size.setInsertPolicy(QComboBox.NoInsert)
        self.combo_size.setFixedWidth(64)
        self.combo_size.setFixedHeight(28)
        self.combo_size.setToolTip(
            "文字大小 (pt)\n"
            "• 像 Word 一樣直接點選字號 (8 ~ 72)\n"
            "• 或直接輸入任意數字後按 Enter\n"
            "• 快捷鍵：Ctrl + 滑鼠滾輪 / Ctrl++ / Ctrl+- / Ctrl+0"
        )
        for s in WORD_FONT_SIZES:
            self.combo_size.addItem(fmt_pt(s))

        self.combo_size.setStyleSheet("""
            QComboBox {
                background: #1b1f2a;
                color: #f1f5f9;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 6px;
                padding: 2px 18px 2px 6px;
                font-weight: 600;
                font-size: 12.5px;
            }
            QComboBox:hover {
                border-color: #60a5fa;
                background: #222838;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 16px;
                border: none;
            }
            QComboBox QAbstractItemView {
                background: #161922;
                color: #f1f5f9;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.15);
                font-size: 12.5px;
            }
        """)

        self.combo_size.activated[str].connect(self._on_combo_text_committed)
        if self.combo_size.lineEdit():
            self.combo_size.lineEdit().returnPressed.connect(
                lambda: self._on_combo_text_committed(self.combo_size.currentText())
            )
            self.combo_size.lineEdit().editingFinished.connect(
                lambda: self._on_combo_text_committed(self.combo_size.currentText())
            )
        layout.addWidget(self.combo_size)

        btn_qss = """
            QToolButton {
                background: #1b1f2a;
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 6px;
                padding: 2px 6px;
                font-weight: 700;
                font-size: 12px;
            }
            QToolButton:hover {
                background: #283044;
                color: #60a5fa;
                border-color: #60a5fa;
            }
            QToolButton:pressed {
                background: #1a1f2c;
            }
        """

        # Word 風格 A▲ (增大字型)
        self.btn_inc = QToolButton()
        self.btn_inc.setProperty("_skip_font_scaler", True)
        self.btn_inc.setText("A▲")
        self.btn_inc.setFixedHeight(28)
        self.btn_inc.setCursor(Qt.PointingHandCursor)
        self.btn_inc.setToolTip("放大文字 (Ctrl + Shift + > 或 Ctrl + +)")
        self.btn_inc.setStyleSheet(btn_qss)
        self.btn_inc.clicked.connect(lambda: self.sig_step_requested.emit(1))
        layout.addWidget(self.btn_inc)

        # Word 風格 A▼ (縮小字型)
        self.btn_dec = QToolButton()
        self.btn_dec.setProperty("_skip_font_scaler", True)
        self.btn_dec.setText("A▼")
        self.btn_dec.setFixedHeight(28)
        self.btn_dec.setCursor(Qt.PointingHandCursor)
        self.btn_dec.setToolTip("縮小文字 (Ctrl + Shift + < 或 Ctrl + -)")
        self.btn_dec.setStyleSheet(btn_qss)
        self.btn_dec.clicked.connect(lambda: self.sig_step_requested.emit(-1))
        layout.addWidget(self.btn_dec)

        self.set_font_pt(initial_pt)

    def set_font_pt(self, pt: float):
        self._updating = True
        try:
            txt = fmt_pt(pt)
            idx = self.combo_size.findText(txt)
            self.combo_size.blockSignals(True)
            if idx >= 0:
                self.combo_size.setCurrentIndex(idx)
            if self.combo_size.lineEdit():
                self.combo_size.lineEdit().setText(txt)
            self.combo_size.blockSignals(False)
        finally:
            self._updating = False

    def _on_combo_text_committed(self, text: str):
        if self._updating:
            return
        raw = (text or "").strip().lower().replace("pt", "").replace("px", "").strip()
        if not raw:
            return
        try:
            if raw.endswith("%"):
                pct = float(raw[:-1].strip())
                val = pct_to_pt(pct)
            else:
                val = clamp_pt(float(raw))
        except ValueError:
            self.set_font_pt(current_app_pt())
            return
        self.sig_font_pt_changed.emit(val)


class WordStatusZoomWidget(QWidget):
    """
    Word 風格右下角狀態列縮放滑桿組件：
    [ － ] ────●──── [ ＋ ] [ 100% (13pt) ]
    """
    sig_font_pt_changed = pyqtSignal(float)
    sig_step_requested = pyqtSignal(int)

    def __init__(self, initial_pt: float = BASE_FONT_PT, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setProperty("_skip_font_scaler", True)
        self._updating = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(4)

        btn_style = """
            QToolButton {
                background: transparent;
                color: #94a3b8;
                border: 1px solid transparent;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                padding: 0 4px;
            }
            QToolButton:hover {
                background: #1e2230;
                color: #60a5fa;
                border-color: rgba(255,255,255,0.12);
            }
        """

        self.btn_minus = QToolButton()
        self.btn_minus.setProperty("_skip_font_scaler", True)
        self.btn_minus.setText("－")
        self.btn_minus.setFixedSize(22, 20)
        self.btn_minus.setCursor(Qt.PointingHandCursor)
        self.btn_minus.setToolTip("縮小文字 (Ctrl + -)")
        self.btn_minus.setStyleSheet(btn_style)
        self.btn_minus.clicked.connect(lambda: self.sig_step_requested.emit(-1))
        layout.addWidget(self.btn_minus)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setProperty("_skip_font_scaler", True)
        self.slider.setRange(SLIDER_MIN_PCT, SLIDER_MAX_PCT)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.slider.setFixedWidth(110)
        self.slider.setFixedHeight(18)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setToolTip("拖曳無段調整全介面文字縮放比例 (50% ~ 300%)")
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #1e293b;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #60a5fa;
                border: 1px solid #93c5fd;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #93c5fd;
            }
        """)
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider)

        self.btn_plus = QToolButton()
        self.btn_plus.setProperty("_skip_font_scaler", True)
        self.btn_plus.setText("＋")
        self.btn_plus.setFixedSize(22, 20)
        self.btn_plus.setCursor(Qt.PointingHandCursor)
        self.btn_plus.setToolTip("放大文字 (Ctrl + +)")
        self.btn_plus.setStyleSheet(btn_style)
        self.btn_plus.clicked.connect(lambda: self.sig_step_requested.emit(1))
        layout.addWidget(self.btn_plus)

        self.btn_pct = QToolButton()
        self.btn_pct.setProperty("_skip_font_scaler", True)
        self.btn_pct.setPopupMode(QToolButton.InstantPopup)
        self.btn_pct.setCursor(Qt.PointingHandCursor)
        self.btn_pct.setFixedHeight(20)
        self.btn_pct.setToolTip("點擊快速選擇縮放比例或重設為 100% (13pt)")
        self.btn_pct.setStyleSheet("""
            QToolButton {
                background: transparent;
                color: #cbd5e1;
                border: 1px solid transparent;
                border-radius: 4px;
                font-size: 11.5px;
                font-weight: 600;
                padding: 0 6px;
            }
            QToolButton:hover {
                background: #1e2230;
                color: #60a5fa;
                border-color: rgba(255,255,255,0.12);
            }
            QToolButton::menu-indicator { image: none; width: 0px; }
        """)

        menu = QMenu(self.btn_pct)
        act_reset = menu.addAction("🔄 重設為預設 100% (13pt)  [Ctrl+0]")
        act_reset.triggered.connect(lambda: self.sig_font_pt_changed.emit(BASE_FONT_PT))
        menu.addSeparator()
        for pct, label in ZOOM_PRESETS:
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, p=pct: self.sig_font_pt_changed.emit(pct_to_pt(p)))
        self.btn_pct.setMenu(menu)
        layout.addWidget(self.btn_pct)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(120)
        self._pending_pt: float = initial_pt
        self._debounce_timer.timeout.connect(lambda: self.sig_font_pt_changed.emit(self._pending_pt))
        self.set_font_pt(initial_pt)

    def set_font_pt(self, pt: float):
        self._updating = True
        try:
            pct = pt_to_pct(pt)
            self.slider.blockSignals(True)
            self.slider.setValue(max(SLIDER_MIN_PCT, min(SLIDER_MAX_PCT, pct)))
            self.slider.blockSignals(False)
            self.btn_pct.setText(f"{pct}% ({fmt_pt(pt)}pt)")
        finally:
            self._updating = False

    def _on_slider_changed(self, pct: int):
        if self._updating:
            return
        pt = pct_to_pt(pct)
        self._pending_pt = pt
        self.btn_pct.setText(f"{pct}% ({fmt_pt(pt)}pt)")
        self._debounce_timer.start()


class _AppWheelAndShowFilter(QObject):
    """
    全域事件過濾器：
    1. 攔截 Ctrl + 滑鼠滾輪 (QEvent.Wheel)，同步無段縮放整個應用程式的所有文字大小（如同 Word）。
    2. 攔截新開啟的 QDialog / QMenu (QEvent.Show)，自動套用當前全域字級縮放。
    """
    def __init__(self, host_window, app_parent=None):
        super().__init__(app_parent)
        self._host_ref = weakref.ref(host_window)

    def eventFilter(self, obj, event):
        host = self._host_ref()
        if host is None:
            return False
        et = event.type()
        if et == QEvent.Wheel:
            try:
                if event.modifiers() & Qt.ControlModifier:
                    delta = event.angleDelta().y()
                    if delta != 0:
                        host.step_ui_font_size(1 if delta > 0 else -1)
                        event.accept()
                        return True
            except Exception:
                pass
        elif et == QEvent.Show and isinstance(obj, (QDialog, QMenu)):
            try:
                apply_scale_to_widget_tree(obj, current_app_scale())
            except Exception:
                pass
        return False


class WordFontScaleMixin:
    """
    掛載於 MainWindow (透過 AgentTeamMixin 繼承) 的 Word 風格全域文字縮放控制器。
    無需動到受防竄改鎖保護的檔案，即可完整接管頂部工具列、右下角狀態列、選單、快捷鍵與對話框文字縮放。
    """

    def _font_scaler_setup(self):
        self.ui_font_pt: float = self._load_saved_font_pt()
        self._sync_app_font_properties(self.ui_font_pt)
        self._wrap_host_html_methods()
        QTimer.singleShot(0, self._font_scaler_late_init)

    def _load_saved_font_pt(self) -> float:
        try:
            st = QSettings("Syntra", "SyntraDesktop")
            val = st.value("ui/font_pt")
            if val is not None:
                return clamp_pt(float(val))
        except Exception:
            pass
        try:
            if hasattr(self, "settings_manager") and self.settings_manager:
                val = self.settings_manager.get("ui_font_pt")
                if val is not None:
                    return clamp_pt(float(val))
        except Exception:
            pass
        return BASE_FONT_PT

    def _save_font_pt(self, pt: float):
        try:
            st = QSettings("Syntra", "SyntraDesktop")
            st.setValue("ui/font_pt", float(pt))
        except Exception:
            pass
        try:
            if hasattr(self, "settings_manager") and self.settings_manager:
                self.settings_manager.update_settings({"ui_font_pt": float(pt)})
        except Exception:
            pass

    def _sync_app_font_properties(self, pt: float):
        pt = clamp_pt(pt)
        scale = pt_to_scale(pt)
        app = QApplication.instance()
        if app is not None:
            app.setProperty("ui_font_pt", pt)
            app.setProperty("ui_font_scale", scale)

    def _wrap_host_html_methods(self):
        """包裝 MainWindow 的即時工作區塊與選單方法，使其自動套用當前字級並掛上選單項"""
        if getattr(self, "_font_methods_wrapped", False):
            return
        self._font_methods_wrapped = True

        # 1. 包裝 _work_live_html 讓「思考中 / 處理中」步驟文字跟隨縮放
        if hasattr(self, "_work_live_html"):
            orig_work_live = self._work_live_html
            self._work_live_html = lambda work: scale_css_font_sizes(orig_work_live(work), current_app_scale())

        # 2. 包裝 _append_console_block 讓「!指令」終端區塊跟隨縮放
        if hasattr(self, "_append_console_block"):
            orig_console = self._append_console_block

            def _scaled_console_block(slot, command: str, output: str, ok: bool = True):
                slot = slot or self.agent_slots.get(self.active_agent_id)
                browser = slot.chat_browser if slot else self.chat_browser
                hook_text_browser_scaling(browser)
                import html as _html
                color = "#e2e8f0" if ok else "#fca5a5"
                raw_block = (
                    "<table width='100%' cellspacing='0' cellpadding='10' bgcolor='#0b0d12' "
                    "style='border:1px solid #262b33; margin:8px 0;'><tr><td>"
                    f"<div style='color:#60a5fa; font-family:Consolas,monospace; font-size:12.5px;'>$ {_html.escape(command)}</div>"
                    f"<pre style='color:{color}; font-family:Consolas,\"Microsoft JhengHei\",monospace; font-size:12.5px; margin:6px 0 0 0;'>"
                    f"{_html.escape(output or '（沒有輸出）')}</pre></td></tr></table>"
                )
                scaled_block = scale_css_font_sizes(raw_block, current_app_scale())
                self._append_left_block(browser)
                cur = QTextCursor(browser.document())
                cur.movePosition(QTextCursor.End)
                cur.insertHtml(scaled_block)
                sb = browser.verticalScrollBar()
                sb.setValue(sb.maximum())

            self._append_console_block = _scaled_console_block

        # 3. 包裝 _create_menu_bar 與 _populate_system_menu，在切換語言重繪選單時自動保留「🔤 文字大小」子選單
        if hasattr(self, "_create_menu_bar"):
            orig_menu_bar = self._create_menu_bar

            def _wrapped_menu_bar():
                orig_menu_bar()
                self._inject_font_menu_items()

            self._create_menu_bar = _wrapped_menu_bar

        if hasattr(self, "_populate_system_menu"):
            orig_sys_menu = self._populate_system_menu

            def _wrapped_sys_menu():
                orig_sys_menu()
                self._inject_system_button_font_menu()

            self._populate_system_menu = _wrapped_sys_menu

    def _font_scaler_late_init(self):
        """在 MainWindow._init_ui 完成後掛載快捷鍵與選單（字體大小控制項已移至『⚙️ 設定 → 一般設定』，不再占用主視窗頂部與底部狀態列避免卡頓）"""
        if getattr(self, "_font_scaler_initialized", False):
            return
        self._font_scaler_initialized = True

        # 建立隱藏同步實例（實際視覺控制器已移至『⚙️ 設定 → 一般設定』，此處保留隱藏實例供 API 與測試同步，不加進頂部與底部狀態列以避免卡頓）
        self.word_font_toolbar = WordFontSizeToolbarWidget(self.ui_font_pt, self)
        self.word_font_toolbar.hide()
        self.word_font_toolbar.sig_font_pt_changed.connect(self.set_ui_font_size)
        self.word_font_toolbar.sig_step_requested.connect(self.step_ui_font_size)

        self.word_status_zoom = WordStatusZoomWidget(self.ui_font_pt, self)
        self.word_status_zoom.hide()
        self.word_status_zoom.sig_font_pt_changed.connect(self.set_ui_font_size)
        self.word_status_zoom.sig_step_requested.connect(self.step_ui_font_size)

        # 解除 topBar 與 agent_bar_widget 固定高度限制，避免大字體時裁切
        top_bar = self.findChild(QFrame, "topBar")
        if top_bar is not None:
            top_bar.setMinimumHeight(46)
            top_bar.setMaximumHeight(16777215)
        if hasattr(self, "agent_bar_widget") and self.agent_bar_widget is not None:
            self.agent_bar_widget.setMinimumHeight(36)
            self.agent_bar_widget.setMaximumHeight(16777215)

        # 選單注入
        self._inject_font_menu_items()
        self._inject_system_button_font_menu()

        # 4. 快捷鍵註冊 (Ctrl++, Ctrl+-, Ctrl+0, Ctrl+Shift+>, Ctrl+Shift+<, Ctrl+], Ctrl+[)
        self._font_shortcuts: List[QShortcut] = []
        for seq in ("Ctrl++", "Ctrl+=", "Ctrl+Shift+>", "Ctrl+Shift+.", "Ctrl+]"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(lambda: self.step_ui_font_size(1))
            self._font_shortcuts.append(sc)
        for seq in ("Ctrl+-", "Ctrl+_", "Ctrl+Shift+<", "Ctrl+Shift+,", "Ctrl+["):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(lambda: self.step_ui_font_size(-1))
            self._font_shortcuts.append(sc)
        sc_reset = QShortcut(QKeySequence("Ctrl+0"), self)
        sc_reset.activated.connect(lambda: self.set_ui_font_size(BASE_FONT_PT))
        self._font_shortcuts.append(sc_reset)

        # 5. 全域 Ctrl + 滑鼠滾輪與彈窗自動縮放過濾器
        app = QApplication.instance()
        if app is not None and not hasattr(self, "_app_wheel_filter"):
            self._app_wheel_filter = _AppWheelAndShowFilter(self, app)
            app.installEventFilter(self._app_wheel_filter)

        # 6. 為所有既有代理的 chat_browser 掛載自動縮放並套用初始字級
        for slot in getattr(self, "agent_slots", {}).values():
            if getattr(slot, "chat_browser", None):
                hook_text_browser_scaling(slot.chat_browser)
        self.set_ui_font_size(self.ui_font_pt, save=False, announce=False)

    def _build_word_font_submenu(self, parent_menu: QMenu) -> QMenu:
        sub = parent_menu.addMenu("🔤 文字大小 (Word 字級與縮放)")
        act_inc = sub.addAction("A▲ 放大文字 (Ctrl + +)")
        act_inc.triggered.connect(lambda: self.step_ui_font_size(1))
        act_dec = sub.addAction("A▼ 縮小文字 (Ctrl + -)")
        act_dec.triggered.connect(lambda: self.step_ui_font_size(-1))
        act_reset = sub.addAction("🔄 重設預設 13pt / 100% (Ctrl + 0)")
        act_reset.triggered.connect(lambda: self.set_ui_font_size(BASE_FONT_PT))
        sub.addSeparator()
        for s in WORD_FONT_SIZES:
            pct = pt_to_pct(s)
            tag = " (預設)" if abs(s - BASE_FONT_PT) < 0.05 else ""
            act = sub.addAction(f"{fmt_pt(s)} pt  ({pct}%){tag}")
            act.setCheckable(True)
            act.setChecked(abs(self.ui_font_pt - s) < 0.1)
            act.triggered.connect(lambda _=False, pt=s: self.set_ui_font_size(float(pt)))
        return sub

    def _inject_font_menu_items(self):
        menu_settings = getattr(self, "menu_settings", None)
        if menu_settings is not None:
            menu_settings.addSeparator()
            self._build_word_font_submenu(menu_settings)

    def _inject_system_button_font_menu(self):
        btn_sys = getattr(self, "btn_system_menu", None)
        if btn_sys is not None and btn_sys.menu() is not None:
            m = btn_sys.menu()
            m.addSeparator()
            self._build_word_font_submenu(m)

    def step_ui_font_size(self, step: int):
        """按 Word 字級階梯放大 (+1) 或縮小 (-1) 全域文字"""
        new_pt = next_word_size(getattr(self, "ui_font_pt", BASE_FONT_PT), step)
        self.set_ui_font_size(new_pt)

    def set_ui_font_size(self, pt: float, save: bool = True, announce: bool = True):
        """設定全域文字大小 (pt)，立即同步所有元件、對話氣泡、終端、分頁與自繪畫布"""
        pt = clamp_pt(pt)
        self.ui_font_pt = pt
        scale = pt_to_scale(pt)
        pct = pt_to_pct(pt)
        self._sync_app_font_properties(pt)

        # 1. 同步頂部與底部 Word 控制項顯示
        if hasattr(self, "word_font_toolbar") and self.word_font_toolbar is not None:
            self.word_font_toolbar.set_font_pt(pt)
        if hasattr(self, "word_status_zoom") and self.word_status_zoom is not None:
            self.word_status_zoom.set_font_pt(pt)

        # 2. 更新頂部與代理分頁列高度
        top_bar = self.findChild(QFrame, "topBar")
        if top_bar is not None:
            top_bar.setMinimumHeight(max(46, int(round(46 * scale))))
        if hasattr(self, "agent_bar_widget") and self.agent_bar_widget is not None:
            self.agent_bar_widget.setMinimumHeight(max(36, int(round(36 * scale))))

        # 3. 暫停畫面重繪以批次縮放主視窗與所有已開啟視窗/對話框的 QSS，徹底消除重繪卡頓
        self.setUpdatesEnabled(False)
        try:
            apply_scale_to_widget_tree(self, scale)
            app = QApplication.instance()
            if app is not None:
                for top_w in app.topLevelWidgets():
                    if top_w is not self and top_w.isVisible():
                        apply_scale_to_widget_tree(top_w, scale)

            # 4. 重新渲染所有代理對話框 (QTextBrowser) 的氣泡與歡迎詞
            self._rerender_all_chat_browsers()

            # 5. 刷新分頁列、UsageBar 與 AgentCanvas
            if hasattr(self, "_refresh_agent_tab_bar"):
                self._refresh_agent_tab_bar()
            for slot in getattr(self, "agent_slots", {}).values():
                if getattr(slot, "usage_bar", None) is not None:
                    slot.usage_bar.update()
            if hasattr(self, "agent_canvas") and self.agent_canvas is not None:
                self.agent_canvas.viewport().update()
        finally:
            self.setUpdatesEnabled(True)

        if save:
            self._save_font_pt(pt)

        if announce:
            try:
                self.statusBar().showMessage(
                    f"🔤 全域文字大小已設為 {fmt_pt(pt)} pt ({pct}%)  — 可用頂部字號框、右下角滑桿或 Ctrl+滾輪調節",
                    3500,
                )
            except Exception:
                pass

    def _rerender_all_chat_browsers(self):
        """將所有代理分頁內的對話氣泡或歡迎畫面依最新字級重新繪製"""
        scale = current_app_scale()
        for aid, slot in list(getattr(self, "agent_slots", {}).items()):
            browser = getattr(slot, "chat_browser", None)
            if browser is None:
                continue
            hook_text_browser_scaling(browser)
            # 若該代理正在串流輸出中，不重繪整頁，僅更新 document 預設字級
            if aid in getattr(self, "_work", {}) or aid in getattr(self, "_stream_start", {}):
                continue
            if slot.messages:
                if hasattr(self, "_rerender_conversation"):
                    self._rerender_conversation(slot)
            else:
                if hasattr(self, "_append_welcome_message_to_slot"):
                    self._append_welcome_message_to_slot(slot)
