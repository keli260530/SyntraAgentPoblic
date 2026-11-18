#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
語意意圖分類器 (Semantic Intent Classifier) — 向量版，取代關鍵字 NLU
=====================================================================
定位：這是「最差情況」的意圖判別層。正常路徑由大語言模型 (LLM) 判意圖；
當 LLM 無法使用或失敗時，改用「向量語意相似度」判別，而不是用一堆
容易誤觸發的關鍵字（例如「記憶體 / 行程 / 安全」會害每次提問都去掃毒）。

做法：
  1. 把使用者提示詞與各「意圖原型句」各自算成向量 (embedding)。
  2. 用 cosine 相似度找最接近的意圖類別。
  3. 回傳類別字串，交給 task_orchestrator 對應到實際的任務規劃。

嵌入來源（免金鑰、離線優先）：
  - 本地 Ollama 的嵌入模型（預設 nomic-embed-text），端點 /api/embed。
  - 本地不可用時回傳 None => 呼叫端安全退回「一般對話」，絕不自動掃毒。

★ 刻意不依賴專案的資安模組，也不需要 API 金鑰；只用標準庫 + numpy。
"""

import json
import os
import asyncio
import urllib.request
import urllib.error

try:
    import numpy as np
    _HAVE_NUMPY = True
except Exception:
    _HAVE_NUMPY = False

# 可用環境變數覆寫（預設本地 Ollama 的輕量嵌入模型）
OLLAMA_EMBED_URL = os.environ.get("SYNTRA_EMBED_URL", "http://127.0.0.1:11434/api/embed")
# 預設 bge-m3：多語、對中文短句意圖辨別力遠勝 nomic-embed-text（實測零誤判掃毒）。
# 若未安裝可 `ollama pull bge-m3`，或用環境變數改回其他模型。
OLLAMA_EMBED_MODEL = os.environ.get("SYNTRA_EMBED_MODEL", "bge-m3")
# 逾時要夠長以容納『首次冷啟動載入模型』(可能數秒~十幾秒)；之後呼叫很快。
_EMBED_TIMEOUT = float(os.environ.get("SYNTRA_EMBED_TIMEOUT", "30"))
# 讓嵌入模型常駐記憶體，之後的 fallback 判別近乎即時。
_EMBED_KEEP_ALIVE = os.environ.get("SYNTRA_EMBED_KEEP_ALIVE", "30m")

# 意圖類別 -> 代表性原型句（多句取平均，提升穩健度）。
# 類別字串需與 task_orchestrator._semantic_decompose 的對應表一致。
# 設計要點（針對中文短句嵌入辨別力弱）：
#   - CHAT 原型避免用「幫我…」這種動作句（會把動作型提問吸過來）。
#   - SECURITY 放入裸詞「掃毒」等，GOOGLE 放入「排行程/日曆」以免排程被誤判資安。
INTENT_PROTOTYPES = {
    "CHAT": [
        "你好嗎",
        "謝謝你的說明",
        "解釋一下什麼是量子力學",
        "今天天氣如何",
        "推薦一本好書",
        "一加一等於多少",
        "這個名詞是什麼意思",
    ],
    "SECURITY": [
        "掃毒",
        "電腦中毒了",
        "有沒有病毒",
        "偵測木馬與勒索軟體",
        "清除惡意程式",
        "殺掉可疑的進程",
        "掃描記憶體注入",
        "防毒巡檢",
    ],
    "GOOGLE": [
        "看 gmail 的信",
        "寄一封郵件",
        "我的日曆今天有什麼",
        "排今天的行程",
        "打開雲端硬碟",
        "讀取 google 試算表",
    ],
    "DESKTOP": [
        "看一下我的畫面",
        "點這個視窗的按鈕",
        "操作這個軟體介面",
        "在應用程式裡輸入文字",
    ],
    "AI_DISPATCH": [
        "打開 claude 輸入提示",
        "叫 vscode 的 ai 送出提示詞",
        "把需求派送給 cursor",
        "在 antigravity 下提示詞",
    ],
    "CODE": [
        "修這個 bug",
        "跑 pytest 測試",
        "改一段程式碼",
        "用 git 看狀態",
        "整理資料夾檔案",
    ],
    "WEB": [
        "上網搜尋最新消息",
        "查一下資料",
        "打開這個網址",
        "查產品官網",
        "找 api 文件",
    ],
}

# 信心門檻（用 top1 與 top2 的『相對差距』margin，而非絕對分數，較穩健）。
# SECURITY 門檻刻意更嚴：誤判成掃毒（over-scan）是使用者最在意的痛點，
# 寧可漏判（降級時退回一般對話）也不要誤觸發掃毒。
_MARGIN_GENERAL = float(os.environ.get("SYNTRA_INTENT_MARGIN", "0.08"))
_MARGIN_SECURITY = float(os.environ.get("SYNTRA_INTENT_MARGIN_SEC", "0.14"))

# 原型向量快取（第一次用到才算，之後重用）：mean-centered 中心、全域平均、類別標籤
_proto_cache = {"vecs": None, "mu": None, "labels": None}


def _embed_sync(texts):
    """呼叫本地 Ollama /api/embed 取得一批文字的向量。
    失敗（模型未安裝、服務未開、逾時）回傳 None，讓呼叫端安全降級。"""
    if not texts:
        return None
    try:
        body = json.dumps({"model": OLLAMA_EMBED_MODEL, "input": list(texts),
                           "keep_alive": _EMBED_KEEP_ALIVE}).encode("utf-8")
        req = urllib.request.Request(
            OLLAMA_EMBED_URL, data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_EMBED_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        embs = data.get("embeddings")
        if not embs or not isinstance(embs, list):
            # 相容舊欄位
            one = data.get("embedding")
            embs = [one] if one else None
        if not embs:
            return None
        return embs
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    except Exception:
        return None


def _ensure_prototypes():
    """確保原型句向量已算好並快取。做兩件關鍵處理以提升中文短句辨別力：
      1) mean-centering：減去所有原型句向量的全域平均（去掉共通成分，拉開區別度）。
      2) 每類別取『mean-centered 後』原型句向量的平均為該類別中心。"""
    if _proto_cache["vecs"] is not None:
        return _proto_cache["vecs"] is not False
    labels = []
    flat = []
    spans = []
    for label, sents in INTENT_PROTOTYPES.items():
        start = len(flat)
        flat.extend(sents)
        spans.append((label, start, len(flat)))
    embs = _embed_sync(flat)
    if not embs or len(embs) != len(flat) or not _HAVE_NUMPY:
        _proto_cache["vecs"] = False     # 標記不可用，避免反覆重試
        return False
    arr = np.asarray(embs, dtype=np.float32)
    mu = arr.mean(axis=0)                 # 全域平均（共通成分）
    arr_mc = arr - mu
    centroids = []
    for label, s, e in spans:
        centroids.append(arr_mc[s:e].mean(axis=0))
        labels.append(label)
    _proto_cache["vecs"] = np.vstack(centroids)
    _proto_cache["mu"] = mu
    _proto_cache["labels"] = labels
    return True


def _rank(qvec):
    """回傳依 cosine 相似度排序的 [(label, score), ...]（已做 mean-centering）。"""
    q = np.asarray(qvec, dtype=np.float32) - _proto_cache["mu"]
    q = q / (np.linalg.norm(q) + 1e-8)
    C = _proto_cache["vecs"]
    Cn = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-8)
    sims = Cn @ q
    order = np.argsort(sims)[::-1]
    labels = _proto_cache["labels"]
    return [(labels[int(i)], float(sims[int(i)])) for i in order]


def classify_sync(prompt):
    """同步版語意分類。用 top1 與 top2 的相對差距(margin)當信心；
    不足門檻 => 回 (None, margin)，交呼叫端走安全預設(一般對話)。
    SECURITY 門檻更嚴，避免降級時誤觸發掃毒。"""
    if not prompt or not prompt.strip():
        return None, 0.0
    if not _HAVE_NUMPY:
        return None, 0.0
    if not _ensure_prototypes():
        return None, 0.0
    q = _embed_sync([prompt.strip()])
    if not q:
        return None, 0.0
    ranked = _rank(q[0])
    top_label, top_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top_score - second
    need = _MARGIN_SECURITY if top_label == "SECURITY" else _MARGIN_GENERAL
    if margin < need:
        return None, margin
    return top_label, margin


async def classify(prompt):
    """非同步包裝：把阻塞的網路嵌入呼叫丟到執行緒，不卡事件迴圈。"""
    try:
        return await asyncio.to_thread(classify_sync, prompt)
    except Exception:
        return None, 0.0


def available():
    """嵌入來源是否可用（本地 Ollama 嵌入模型是否就緒）。"""
    return _ensure_prototypes()
