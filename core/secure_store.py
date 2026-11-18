# -*- coding: utf-8 -*-
"""
用 Windows DPAPI 加密保存敏感檔（目前用於 Google 登入金鑰 data/google_token.json）。

- 只有「同一台電腦上的同一個 Windows 使用者」解得開：檔案被複製到別台電腦、或被別的 Windows 帳號讀到，都只是亂碼。
- 舊版的明文檔第一次讀取時會自動改寫成加密檔（遷移）。
- 非 Windows 環境（例如測試機）退回明文，並在檔頭標明，不會假裝有加密。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

MAGIC = b"SYNTRA-DPAPI-1\n"
PLAIN_MAGIC = b"SYNTRA-PLAIN-1\n"  # 沒有 DPAPI 時的明文格式（僅非 Windows）
_ENTROPY = b"Syntra-secure-store-v1"
_DESC = "Syntra protected secret"

PathLike = Union[str, os.PathLike]


class SecureStoreError(RuntimeError):
    pass


def _dpapi():
    try:
        import win32crypt  # pywin32
        return win32crypt
    except Exception:
        return None


def is_available() -> bool:
    return _dpapi() is not None


def protect(data: bytes) -> bytes:
    w = _dpapi()
    if w is None:
        return PLAIN_MAGIC + data
    # CRYPTPROTECT_UI_FORBIDDEN = 0x1
    return MAGIC + w.CryptProtectData(data, _DESC, _ENTROPY, None, None, 0x1)


def unprotect(blob: bytes) -> bytes:
    if blob.startswith(MAGIC):
        w = _dpapi()
        if w is None:
            raise SecureStoreError("這個檔案是在 Windows 上加密的，目前環境無法解密")
        try:
            _desc, data = w.CryptUnprotectData(blob[len(MAGIC):], _ENTROPY, None, None, 0x1)
        except Exception as e:
            raise SecureStoreError("無法解密：檔案可能是從別台電腦或別的 Windows 帳號複製來的，請重新登入") from e
        return data
    if blob.startswith(PLAIN_MAGIC):
        return blob[len(PLAIN_MAGIC):]
    raise SecureStoreError("不是 Syntra 加密檔")


def is_protected_file(path: PathLike) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def write_text(path: PathLike, text: str):
    """加密後寫入（原子寫入，不會留下寫一半的檔案）。"""
    _atomic_write(Path(path), protect(text.encode("utf-8")))


def read_text(path: PathLike, migrate: bool = True) -> Optional[str]:
    """
    讀取並解密；檔案不存在回傳 None。
    舊版明文檔（不是 Syntra 格式）會原樣回傳，migrate=True 時順便改寫成加密檔。
    解密失敗丟 SecureStoreError（例如檔案是從別台電腦複製來的）。
    """
    p = Path(path)
    if not p.exists():
        return None
    blob = p.read_bytes()
    if blob.startswith(MAGIC) or blob.startswith(PLAIN_MAGIC):
        return unprotect(blob).decode("utf-8")
    text = blob.decode("utf-8-sig")
    if migrate and is_available():
        try:
            write_text(p, text)
        except OSError:
            pass
    return text


def delete(path: PathLike):
    p = Path(path)
    if p.exists():
        p.unlink()
