# -*- coding: utf-8 -*-
"""
智慧路由模型品牌圖標產生與解析器（Model Brand Icons）。

依據目前智慧路由實際使用的模型／服務商，在「思考中 / 處理中…」前方顯示對應品牌圖標；
若為本機模型（Ollama / LM Studio / llama.cpp / Local），則使用 Syntra 專屬設計的「本機星樞晶片徽章」。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Optional

_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "model_icons"


def resolve_model_brand(
    model_id: str = "",
    is_local: Optional[bool] = None,
    provider_info: Optional[Dict[str, Any]] = None,
) -> str:
    """依 model_id、is_local 或 provider_info 動態判斷品牌鍵值。"""
    if is_local is True:
        return "local_syntra"

    mid = (model_id or "").strip().lower()
    pname = str((provider_info or {}).get("name") or "").lower()
    burl = str((provider_info or {}).get("base_url") or "").lower()
    hay = f"{mid} {pname} {burl}"

    if any(k in hay for k in ("127.0.0.1", "localhost", "ollama", "lmstudio", "lm_studio", "llama.cpp", "llamacpp", "local")):
        return "local_syntra"
    if "gemini" in hay or "google" in hay or "generativelanguage" in hay:
        return "gemini"
    if any(k in hay for k in ("claude", "anthropic")):
        return "claude"
    if any(k in hay for k in ("openai", "gpt-", "chatgpt", "o1-", "o3-", "o4-")):
        return "openai"
    if "deepseek" in hay:
        return "deepseek"
    if "grok" in hay or "xai" in hay or "x.ai" in hay:
        return "grok"
    if "nvidia" in hay or "nim" in hay:
        return "nvidia"
    if "qwen" in hay or "dashscope" in hay or "alibaba" in hay:
        return "qwen"
    if "llama" in hay or "meta" in hay:
        return "llama"
    return "syntra_auto"


def _draw_brand_qimage(brand: str, size: int = 32, phase: float = 0.0) -> Optional[Any]:
    """使用 Qt QPainter 繪製單幀抗鋸齒向量品牌圖標（支援 phase 0.0~1.0 旋轉與呼吸光暈動畫）。"""
    try:
        from PyQt5.QtCore import QPointF, QRectF, Qt
        from PyQt5.QtGui import (
            QColor,
            QImage,
            QLinearGradient,
            QPainter,
            QPainterPath,
            QPen,
        )
    except Exception:
        return None

    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    cx, cy = size / 2.0, size / 2.0
    # 呼吸縮放與平滑旋轉參數
    pulse = 0.92 + 0.08 * math.sin(phase * 2.0 * math.pi)
    rot_deg = phase * 360.0
    r = size * 0.42 * pulse

    if brand == "local_syntra":
        # Syntra 專屬設計：深空青藍六角晶片（靜穩外框） + 內部旋轉四芒星樞核心
        hex_path = QPainterPath()
        hr = size * 0.42
        for i in range(6):
            ang = math.radians(60 * i - 30)
            pt = QPointF(cx + hr * math.cos(ang), cy + hr * math.sin(ang))
            hex_path.moveTo(pt) if i == 0 else hex_path.lineTo(pt)
        hex_path.closeSubpath()
        grad = QLinearGradient(0, 0, size, size)
        grad.setColorAt(0.0, QColor("#0f172a"))
        grad.setColorAt(1.0, QColor("#0c4a6e"))
        p.setBrush(grad)
        p.setPen(QPen(QColor("#22d3ee"), max(1.6, size * 0.06)))
        p.drawPath(hex_path)
        # 內部青藍四芒星隨 phase 平滑旋轉發光
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_deg)
        star = QPainterPath()
        ro, ri = r * 0.64, r * 0.22
        for i in range(8):
            ang = math.radians(45 * i - 90)
            rad = ro if i % 2 == 0 else ri
            pt = QPointF(rad * math.cos(ang), rad * math.sin(ang))
            star.moveTo(pt) if i == 0 else star.lineTo(pt)
        star.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#38bdf8"))
        p.drawPath(star)
        p.setBrush(QColor("#f0f9ff"))
        p.drawEllipse(QPointF(0, 0), r * 0.14, r * 0.14)
        p.restore()

    elif brand == "gemini":
        # Gemini 藍紫粉漸層四芒星（旋轉 + 呼吸）
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_deg * 0.5)
        star = QPainterPath()
        ro, ri = r * 0.98, r * 0.28
        for i in range(8):
            ang = math.radians(45 * i - 90)
            rad = ro if i % 2 == 0 else ri
            pt = QPointF(rad * math.cos(ang), rad * math.sin(ang))
            star.moveTo(pt) if i == 0 else star.lineTo(pt)
        star.closeSubpath()
        grad = QLinearGradient(-r, -r, r, r)
        grad.setColorAt(0.0, QColor("#4285F4"))
        grad.setColorAt(0.55, QColor("#9B72CB"))
        grad.setColorAt(1.0, QColor("#D96570"))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(star)
        p.restore()

    elif brand == "claude":
        # Claude 暖陶橘放射星芒旋轉
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_deg * 0.5)
        p.setPen(QPen(QColor("#D97757"), max(2.2, size * 0.085), Qt.SolidLine, Qt.RoundCap))
        for i in range(8):
            ang = math.radians(45 * i)
            p.drawLine(
                QPointF(r * 0.22 * math.cos(ang), r * 0.22 * math.sin(ang)),
                QPointF(r * 0.92 * math.cos(ang), r * 0.92 * math.sin(ang)),
            )
        p.restore()

    elif brand == "openai":
        # OpenAI 青綠圓環幾何旋轉
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_deg * 0.5)
        p.setPen(QPen(QColor("#10A37F"), max(2.0, size * 0.075)))
        p.setBrush(Qt.NoBrush)
        for i in range(6):
            ang = math.radians(60 * i)
            ox = r * 0.34 * math.cos(ang)
            oy = r * 0.34 * math.sin(ang)
            p.drawEllipse(QPointF(ox, oy), r * 0.42, r * 0.42)
        p.restore()

    elif brand == "deepseek":
        grad = QLinearGradient(0, 0, size, size)
        grad.setColorAt(0.0, QColor("#2563eb"))
        grad.setColorAt(1.0, QColor("#38bdf8"))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QPointF(cx, cy), r * 0.9, r * 0.9)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(cx + r * 0.18 * math.cos(phase * 2 * math.pi), cy - r * 0.1), r * 0.24, r * 0.24)

    elif brand == "grok":
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_deg * 0.5)
        p.setPen(QPen(QColor("#e2e8f0"), max(2.2, size * 0.08)))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), r * 0.78, r * 0.78)
        p.drawLine(QPointF(-r * 0.68, r * 0.68), QPointF(r * 0.68, -r * 0.68))
        p.restore()

    elif brand == "nvidia":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#76B900"))
        p.drawRoundedRect(QRectF(cx - r * 0.85, cy - r * 0.85, r * 1.7, r * 1.7), 6, 6)
        p.setBrush(QColor("#0f172a"))
        p.drawEllipse(QPointF(cx, cy), r * 0.36, r * 0.36)

    elif brand == "qwen":
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_deg * 0.5)
        grad = QLinearGradient(-r, -r, r, r)
        grad.setColorAt(0.0, QColor("#6366f1"))
        grad.setColorAt(1.0, QColor("#a855f7"))
        diam = QPainterPath()
        diam.moveTo(0, -r * 0.95)
        diam.lineTo(r * 0.95, 0)
        diam.lineTo(0, r * 0.95)
        diam.lineTo(-r * 0.95, 0)
        diam.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(diam)
        p.restore()

    elif brand == "llama":
        p.setPen(QPen(QColor("#0668E1"), max(2.2, size * 0.08)))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx - r * 0.36, cy), r * 0.45, r * 0.45)
        p.drawEllipse(QPointF(cx + r * 0.36, cy), r * 0.45, r * 0.45)

    else:
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_deg * 0.5)
        star = QPainterPath()
        ro, ri = r * 0.9, r * 0.32
        for i in range(8):
            ang = math.radians(45 * i - 90)
            rad = ro if i % 2 == 0 else ri
            pt = QPointF(rad * math.cos(ang), rad * math.sin(ang))
            star.moveTo(pt) if i == 0 else star.lineTo(pt)
        star.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#60a5fa"))
        p.drawPath(star)
        p.restore()

    p.end()
    return img


def _draw_brand_png(brand: str, out_path: Path, size: int = 32) -> bool:
    img = _draw_brand_qimage(brand, size=size, phase=0.0)
    if img is None:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return img.save(str(out_path), "PNG")


_ANIM_CACHE: Dict[str, list] = {}


def get_brand_animation_frames(brand: str, n_frames: int = 12, size: int = 32) -> list:
    """回傳指定品牌的多幀 QImage 動畫影格清單（快取於記憶體供 QTextDocument 零閃爍播放）。"""
    key = f"{brand}:{n_frames}:{size}"
    if key in _ANIM_CACHE:
        return _ANIM_CACHE[key]
    frames = []
    for i in range(n_frames):
        qi = _draw_brand_qimage(brand, size=size, phase=i / float(n_frames))
        if qi is not None:
            frames.append(qi)
    if frames:
        _ANIM_CACHE[key] = frames
    return frames


def get_brand_icon_path(brand: str) -> Optional[Path]:
    _ICON_DIR.mkdir(parents=True, exist_ok=True)
    fp = _ICON_DIR / f"{brand}.png"
    if fp.exists() and fp.stat().st_size > 0:
        return fp
    if _draw_brand_png(brand, fp, size=32):
        return fp
    return None


def icon_html_for_model(
    model_id: str = "",
    is_local: Optional[bool] = None,
    provider_info: Optional[Dict[str, Any]] = None,
    size: int = 15,
) -> str:
    """回傳可直接嵌入 QTextBrowser HTML 的 <img> 標籤（若非 Qt 環境則退回簡潔符號）。"""
    brand = resolve_model_brand(model_id=model_id, is_local=is_local, provider_info=provider_info)
    fp = get_brand_icon_path(brand)
    if fp is not None:
        uri = fp.resolve().as_uri()
        return f"<img src='{uri}' width='{size}' height='{size}' style='vertical-align:middle;'>"
    return "🔷" if brand == "local_syntra" else "✦"
