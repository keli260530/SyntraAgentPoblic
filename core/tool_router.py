# -*- coding: utf-8 -*-
"""
工具選擇器 (Tool Router) — 在本機訓練的小模型，幫本機大模型先挑出「這次最可能用到的工具」

問題：Agent 有七十多個工具，本機的 12B / 20B 模型一次看到全部時常常選錯、亂填參數，
而且光是工具定義就吃掉好幾千 tokens 的上下文。
做法：把使用者的話用本機嵌入模型（Ollama bge-m3）算成向量，再用一個在這台電腦上訓練出來的
線性分類層（softmax，純 numpy）替每個工具打分數，只把分數最高的十幾個工具交給本機模型。

安全設計（寧可不篩，也不要篩錯）：
- 沒有訓練過的模型檔、嵌入服務沒開、逾時、把握太低 → 回傳 None，照舊給完整工具清單。
- 只篩「訓練時看過的工具」；MCP、團隊協作等沒看過的工具一律保留。
- 被篩掉的工具仍然可以執行：模型硬是叫了清單外的工具，ToolGuard 認得就照常執行。
- 雲端大模型不套用（它們處理完整清單沒問題）。
- 環境變數 SYNTRA_TOOL_ROUTER=0 可整個關閉。

訓練：python scripts/train_tool_router.py
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from . import semantic_intent as _si

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "tool_router"
MODEL_PATH = DATA_DIR / "model.npz"
META_PATH = DATA_DIR / "model.json"
USAGE_PATH = DATA_DIR / "usage.jsonl"
SEED_PATH = Path(__file__).resolve().parent / "tool_router_seeds.json"

NONE_LABEL = "__none__"          # 純聊天、不需要工具
TOP_K = 10                       # 分數最高的幾個工具
FAMILY_TRIGGER_RANK = 4          # 同家族成員排進前幾名，就整個家族一起帶上
MIN_CONFIDENCE = 0.12            # 最高機率低於此值 → 沒把握，不篩
RUNTIME_EMBED_TIMEOUT = float(os.environ.get("SYNTRA_TOOL_ROUTER_TIMEOUT", "4"))

# 不管分數如何都保留的基本工具（查資料、看畫面、跑指令、開軟體）
ALWAYS_KEEP = (
    "web_search", "web_fetch", "run_background_shell", "list_windows", "capture_desktop_screen",
    "read_local_file", "search_local_files", "list_installed_software", "launch_application",
    "app_howto", "write_text_file", "open_file_in_app",  # 軟體操作知識庫：操作軟體前先查、寫檔一步完成
    "research_app_howto", "type_in_app",  # 上網查操作方法；在已開啟的軟體裡輸入文字（read_app_help／save_app_knowledge 沒列出也照樣能執行）
)
# 一起用才有意義的工具家族
FAMILIES: Dict[str, Sequence[str]] = {
    "ui": ("list_windows", "inspect_accessibility_tree", "ui_invoke", "ui_type", "ui_click", "ui_read_text"),
    "screen": ("capture_desktop_screen", "click_screen", "type_text", "ocr_screen",
               "computer_key", "computer_scroll", "computer_drag", "computer_wait"),
    "browser": ("browser_navigate", "browser_screenshot", "browser_extract", "browser_click",
                "browser_type", "browser_close"),
    "gmail": ("gmail_list_messages", "gmail_read_message", "gmail_send_message"),
    "gcalendar": ("gcalendar_list_events", "gcalendar_create_event"),
    "gdrive": ("gdrive_search_files", "gdrive_upload_file"),
    "skills": ("list_installed_skills", "run_skill_script", "install_skill"),
}
_FAMILY_OF = {tool: fam for fam, tools in FAMILIES.items() for tool in tools if tool != "list_windows"
              and tool != "capture_desktop_screen"}

_state: Dict[str, Any] = {"mtime": None, "model": None}


def enabled() -> bool:
    return np is not None and os.environ.get("SYNTRA_TOOL_ROUTER", "1").strip().lower() not in ("0", "off", "false")


# ---------------------------------------------------------------- 嵌入
def embed(texts: Sequence[str], timeout: float = 60.0) -> Optional["np.ndarray"]:
    """用本機 Ollama 嵌入模型把文字算成向量。失敗回傳 None。"""
    if np is None or not texts:
        return None
    try:
        body = json.dumps({"model": _si.OLLAMA_EMBED_MODEL, "input": list(texts),
                           "keep_alive": _si._EMBED_KEEP_ALIVE}).encode("utf-8")
        req = urllib.request.Request(_si.OLLAMA_EMBED_URL, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        embs = data.get("embeddings")
        if not embs or len(embs) != len(texts):
            return None
        return np.asarray(embs, dtype=np.float32)
    except Exception:
        return None


def featurize(vecs: "np.ndarray", mu: "np.ndarray") -> "np.ndarray":
    """去掉共通成分後正規化（中文短句的向量彼此太像，減掉平均才拉得開）。"""
    x = np.asarray(vecs, dtype=np.float32) - mu
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-8)


# ---------------------------------------------------------------- 訓練
def train_classifier(X: "np.ndarray", Y: "np.ndarray", sample_weight: Optional["np.ndarray"] = None,
                     epochs: int = 400, lr: float = 0.05, weight_decay: float = 1e-3,
                     scale: float = 16.0, seed: int = 0):
    """多標籤 softmax 線性分類層，Adam 全批次梯度下降。
    X: (N, D) 已 featurize；Y: (N, L) 每列是目標分布（多個正確工具就平均分）。回傳 (W, b)。"""
    rng = np.random.default_rng(seed)
    n, d = X.shape
    l = Y.shape[1]
    W = (rng.standard_normal((d, l)) * 0.01).astype(np.float32)
    b = np.zeros(l, dtype=np.float32)
    sw = np.ones(n, dtype=np.float32) if sample_weight is None else np.asarray(sample_weight, dtype=np.float32)
    sw = sw / sw.sum()
    mW, vW, mb, vb = np.zeros_like(W), np.zeros_like(W), np.zeros_like(b), np.zeros_like(b)
    b1, b2, eps = 0.9, 0.999, 1e-8
    for t in range(1, epochs + 1):
        logits = scale * (X @ W) + b
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(axis=1, keepdims=True)
        g = (p - Y) * sw[:, None]
        gW = scale * (X.T @ g) + weight_decay * W
        gb = g.sum(axis=0)
        mW = b1 * mW + (1 - b1) * gW
        vW = b2 * vW + (1 - b2) * gW * gW
        mb = b1 * mb + (1 - b1) * gb
        vb = b2 * vb + (1 - b2) * gb * gb
        W -= lr * (mW / (1 - b1 ** t)) / (np.sqrt(vW / (1 - b2 ** t)) + eps)
        b -= lr * (mb / (1 - b1 ** t)) / (np.sqrt(vb / (1 - b2 ** t)) + eps)
    return W, b


def predict_proba(X: "np.ndarray", W: "np.ndarray", b: "np.ndarray", scale: float = 16.0) -> "np.ndarray":
    logits = scale * (X @ W) + b
    logits = logits - logits.max(axis=-1, keepdims=True)
    p = np.exp(logits)
    return p / p.sum(axis=-1, keepdims=True)


def save_model(W, b, mu, labels: List[str], meta: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_PATH.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, W=W.astype(np.float16), b=b.astype(np.float32), mu=mu.astype(np.float32))
    os.replace(tmp, MODEL_PATH)
    META_PATH.write_text(json.dumps({**meta, "labels": labels, "embed_model": _si.OLLAMA_EMBED_MODEL},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    _state["mtime"] = None


def load_model() -> Optional[Dict[str, Any]]:
    """讀取訓練好的模型（檔案更新會自動重讀）。沒有或不相容回傳 None。"""
    if np is None:
        return None
    try:
        mtime = MODEL_PATH.stat().st_mtime
    except OSError:
        return None
    if _state["mtime"] == mtime:
        return _state["model"]
    model = None
    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        with np.load(MODEL_PATH) as z:
            W, b, mu = z["W"].astype(np.float32), z["b"].astype(np.float32), z["mu"].astype(np.float32)
        labels = list(meta["labels"])
        if meta.get("embed_model") == _si.OLLAMA_EMBED_MODEL and W.shape == (mu.shape[0], len(labels)):
            model = {"W": W, "b": b, "mu": mu, "labels": labels, "meta": meta}
    except Exception:
        model = None
    _state["mtime"], _state["model"] = mtime, model
    return model


# ---------------------------------------------------------------- 挑工具
def pick_from_ranking(ranked: List[str], available: Iterable[str], trained: Iterable[str],
                      keep: Iterable[str] = (), top_k: int = TOP_K) -> List[str]:
    """ranked：依分數高到低的工具名稱（可含 NONE_LABEL）。回傳要給模型看的工具名稱（維持 available 原順序）。"""
    available = list(available)
    avail = set(available)
    trained = set(trained)
    chosen = {t for t in available if t not in trained}            # 沒訓練過的一律保留
    chosen.update(t for t in ALWAYS_KEEP if t in avail)
    chosen.update(t for t in keep if t in avail)
    tools_ranked = [t for t in ranked if t != NONE_LABEL and t in avail]
    chatty = bool(ranked) and ranked[0] == NONE_LABEL                # 看起來只是聊天：少挑一點
    chosen.update(tools_ranked[:max(3, top_k // 2) if chatty else top_k])
    for t in tools_ranked[:FAMILY_TRIGGER_RANK]:
        fam = _FAMILY_OF.get(t)
        if fam:
            chosen.update(m for m in FAMILIES[fam] if m in avail)
    return [t for t in available if t in chosen]


def rank_sync(text: str, timeout: float = RUNTIME_EMBED_TIMEOUT) -> Optional[Dict[str, Any]]:
    """回傳 {"ranked": [工具名稱…], "probs": {名稱: 機率}, "confidence": 最高機率}；不可用回傳 None。"""
    model = load_model()
    if model is None or not (text or "").strip():
        return None
    vec = embed([text.strip()[:2000]], timeout=timeout)
    if vec is None or vec.shape[1] != model["mu"].shape[0]:
        return None
    p = predict_proba(featurize(vec, model["mu"]), model["W"], model["b"],
                      float(model["meta"].get("scale", 16.0)))[0]
    order = np.argsort(p)[::-1]
    labels = model["labels"]
    return {"ranked": [labels[int(i)] for i in order],
            "probs": {labels[int(i)]: float(p[int(i)]) for i in order[:15]},
            "confidence": float(p[int(order[0])])}


async def select_specs(text: str, specs: List[Dict[str, Any]], keep: Iterable[str] = ()
                       ) -> Optional[Dict[str, Any]]:
    """替這句話挑工具。回傳 {"specs": 篩選後清單, "top": 前幾名, "confidence"}；
    不該篩（沒模型、沒把握、省不了多少）時回傳 None。"""
    if not enabled() or load_model() is None:
        return None
    try:
        res = await asyncio.to_thread(rank_sync, text)
    except Exception:
        res = None
    if not res or res["confidence"] < MIN_CONFIDENCE:
        return None
    names = [s["name"] for s in specs]
    picked = set(pick_from_ranking(res["ranked"], names, load_model()["labels"], keep, top_k=TOP_K))
    if len(picked) > len(names) * 0.7:      # 幾乎沒省到，不值得讓模型的提示詞快取失效
        return None
    return {"specs": [s for s in specs if s["name"] in picked],
            "top": [t for t in res["ranked"] if t != NONE_LABEL and t in picked][:5],
            "confidence": res["confidence"]}


# ---------------------------------------------------------------- 使用紀錄（之後重新訓練用）
def log_usage(text: str, tool_steps: List[Dict[str, Any]], sanitize=None) -> None:
    """把「使用者說了什麼 → 實際成功用了哪些工具」記到本機，下次訓練時當教材。只存在這台電腦。"""
    if not enabled():
        return
    try:
        ok_tools: List[str] = []
        for s in tool_steps or []:
            name, preview = s.get("tool"), str(s.get("result_preview") or "")
            if not name or s.get("status") != "DONE" or preview.lstrip()[:1] in ("❌", "🛑", "🔁", "⚠"):
                continue
            if '"ok": false' in preview[:80].lower() or name in ok_tools:
                continue
            ok_tools.append(name)
        text = (text or "").strip()
        if not ok_tools or not text or len(text) > 400:
            return
        if sanitize:
            text = sanitize(text)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(USAGE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"text": text, "tools": ok_tools, "ts": int(time.time())},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 教材
def builtin_specs() -> List[Dict[str, Any]]:
    """Agent 內建的全部工具定義（不含 MCP）。訓練與評測用。"""
    from .agent_brain import AgentBrain
    from .tool_schemas import build_tool_specs
    from .local_tools import TOOL_SPECS as local_specs
    from .computer_use import TOOL_SPECS as cu_specs
    from .long_term_memory import TOOL_SPECS as mem_specs
    return build_tool_specs(AgentBrain.SYSTEM_PROMPT) + list(mem_specs) + list(local_specs) + list(cu_specs)


def load_examples(specs: List[Dict[str, Any]], include_usage: bool = True, usage_limit: int = 2000
                  ) -> List[Dict[str, Any]]:
    """組出訓練教材：[{"text", "tools": [...], "weight", "source"}]。
    來源：① 每個工具自己的說明文字 ② 人工寫的例句 (tool_router_seeds.json) ③ 本機實際使用紀錄。"""
    names = {s["name"] for s in specs}
    out: List[Dict[str, Any]] = []
    for s in specs:
        desc = (s.get("description") or "").strip()
        if desc:
            out.append({"text": desc[:300], "tools": [s["name"]], "weight": 1.0, "source": "description"})
    seeds = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for tool, sents in (seeds.get("single") or {}).items():
        if tool != NONE_LABEL and tool not in names:
            continue
        for t in sents:
            out.append({"text": t, "tools": [tool], "weight": 1.0, "source": "seed"})
    for item in seeds.get("multi") or []:
        tools = [t for t in item.get("tools", []) if t in names]
        if tools and item.get("text"):
            out.append({"text": item["text"], "tools": tools, "weight": 1.0, "source": "seed"})
    if include_usage and USAGE_PATH.exists():
        rows = []
        for line in USAGE_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        seen = set()
        for r in reversed(rows[-usage_limit:]):
            tools = [t for t in r.get("tools", []) if t in names]
            text = str(r.get("text") or "").strip()
            if tools and text and text not in seen:
                seen.add(text)
                out.append({"text": text, "tools": tools, "weight": 0.5, "source": "usage"})
    return out
