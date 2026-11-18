# -*- coding: utf-8 -*-
"""
Syntra DLC 內容加密與記憶體載入核心 (AES-256-GCM)
================================================
1. 打包階段：將明文 .py 加密為不可閱讀的二進位 `payload.enc`（AES-256-GCM），
   發布的 DLC 壓縮包內不含任何明文原始碼或解密金鑰。
2. 執行階段：僅當後端 `/api/redeem` 核銷兌換碼並通過 Ed25519 驗章後，
   才會取得對應 `dlc_id` 的金鑰，直接在記憶體中解密載入模組，不在硬碟寫出明文 .py。
"""
from __future__ import annotations

import base64
import hashlib
import os
import sys
import types
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC = b"SYNTRA_ENC1"


def generate_content_key_b64() -> str:
    """產生 256-bit (32 bytes) 隨機 AES-GCM 金鑰（Base64 URL-safe）。"""
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _decode_key(key_b64: str) -> bytes:
    raw = str(key_b64 or "").strip()
    pad = "=" * ((4 - len(raw) % 4) % 4)
    key = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
    if len(key) != 32:
        raise ValueError("DLC content key must be 32 bytes (AES-256)")
    return key


def encrypt_source_to_file(src_py: Path, out_enc: Path, key_b64: str, dlc_id: str) -> None:
    """將 Python 原始碼加密為不可閱讀的 payload.enc。"""
    key = _decode_key(key_b64)
    nonce = os.urandom(12)
    aad = dlc_id.encode("utf-8")
    plaintext = src_py.read_text(encoding="utf-8").encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    out_enc.parent.mkdir(parents=True, exist_ok=True)
    out_enc.write_bytes(_MAGIC + nonce + ct)


def decrypt_bytes(enc_path: Path, key_b64: str, dlc_id: str) -> str:
    """於記憶體中解密 payload.enc 並回傳原始碼字串（不寫入磁碟）。"""
    data = enc_path.read_bytes()
    if not data.startswith(_MAGIC) or len(data) <= len(_MAGIC) + 12:
        raise ValueError("Invalid encrypted DLC payload header")
    nonce = data[len(_MAGIC) : len(_MAGIC) + 12]
    ct = data[len(_MAGIC) + 12 :]
    key = _decode_key(key_b64)
    plaintext = AESGCM(key).decrypt(nonce, ct, dlc_id.encode("utf-8"))
    return plaintext.decode("utf-8")


def load_encrypted_module(enc_path: Path, key_b64: str, dlc_id: str, module_name: str) -> types.ModuleType:
    """解密 payload.enc 並直接在記憶體建立 Python ModuleType 物件。"""
    code_str = decrypt_bytes(enc_path, key_b64, dlc_id)
    mod = types.ModuleType(module_name)
    mod.__file__ = str(enc_path)
    mod.__package__ = ""
    sys.modules[module_name] = mod
    compiled = compile(code_str, f"<dlc:{dlc_id}>", "exec")
    exec(compiled, mod.__dict__)
    return mod


def key_fingerprint(key_b64: str) -> str:
    return hashlib.sha256(key_b64.encode("utf-8")).hexdigest()[:12]
