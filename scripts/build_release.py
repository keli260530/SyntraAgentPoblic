# -*- coding: utf-8 -*-
"""
打包可以發給別人下載的 Syntra（乾淨版 zip）。

    python scripts/build_release.py              → dist/Syntra-YYYYMMDD.zip
    python scripts/build_release.py --check      → 只檢查會打包哪些檔、有沒有金鑰外洩，不產生 zip

保護隱私的規則：
1. data/ 只帶白名單：credentials.json（OAuth 用戶端憑證，桌面 App 本來就要隨程式發佈）與 mcp_servers.json（預設設定）。
   你的 Google 登入金鑰、API Key、Discord 設定、對話紀錄、長期記憶、稽核紀錄、瀏覽器資料…全部不會被帶走。
2. 排除快取、測試樣本、錄影、log、建置產物。
3. 打包前掃描每個檔案的內容，發現 API Key / Token / 私鑰就中止，並列出檔名與行號（不印出金鑰本身）。
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterator, List, Tuple

ROOT = Path(__file__).resolve().parents[1]

DATA_ALLOWLIST = {"credentials.json"}

EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".git", ".github", ".venv", ".venv_train", "venv", "env", "node_modules",
    "dist", "build", "training", ".syntra", ".claude", ".idea", ".vscode", "website", ".wrangler",
    ".agents", "skills", "user_profile", "dlc", "official_security_shield", "guardian", "modules",
    "supabase", "deploy", "tests",
}
EXCLUDE_FILES = [
    "*.pyc", "*.pyo", "*.log", "*.jsonl", "*.tmp", "*.bak", "*.dpapi",
    "@AutomationLog.txt", "test_anti_tamper.txt", "temp_malware_sample_*", "debug_screen.png",
    "Syntra_Setup.exe", "wrangler.jsonc", ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12",
    "google_token.json", "api_providers.json", "settings.json", "long_term_memory.json",
    "mcp_servers.json", "dlc_licenses.json", "dlc_content_keys.json",
    "render_server.py", "requirements-render.txt", "build_protected_dlc.py",
    "train_tool_router.py", "eval_tool_calling.py", "totp_bind.py", "watchdog_immortal.py",
    "apply_custom_icon.py", "訓練_工具選擇器.bat", "開啟_Gemini_Agent.bat", "self_defense_immortal.py", "*wfx-docs*", "*dependency*audit*",
    "gemini_icon.ico", "gemini_icon.png", "custom_agent_icon_original.jpg",
    "antivirus_scanner.py", "active_network_guard.py", "hyper_antivirus_sentinel.py",
    "file_integrity_guard.py", "kernel_driver_bridge.py", "mass_malware_storm_shield.py",
    "anti_takeover_guard.py", "memory_injection_sentinel.py", "predictive_immune_engine.py",
    "threat_hunter_tracer.py", "doomsday_data_citadel.py", "self_healing_regenerator.py",
    "counter_strike_offensive.py", "os_resuscitation_cpr.py", "byovd_and_kernel_sentinel.py",
    "totp_authenticator_guard.py", "totp_bind_dialog.py", "adaptive_symbiotic_guardian.py",
]

# (名稱, 規則)；只回報檔名與行號，不輸出命中的內容
SECRET_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("Google API Key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("OpenAI 類 API Key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}")),
    ("NVIDIA API Key", re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}")),
    ("GitHub Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("Slack Token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("Discord Bot Token", re.compile(r"\b[MNO][A-Za-z\d_\-]{23,27}\.[A-Za-z\d_\-]{6}\.[A-Za-z\d_\-]{27,40}\b")),
    ("Discord Webhook", re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]{30,}")),
    ("Google OAuth 存取權杖", re.compile(r"\bya29\.[A-Za-z0-9_\-]{20,}")),
    ("Google OAuth 更新權杖", re.compile(r"\b1//0[A-Za-z0-9_\-]{30,}")),
    ("私鑰", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----")),
    ("Google OAuth 用戶端密碼", re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}")),
]
# 用戶端密碼只允許出現在 OAuth 憑證檔（桌面 App 的這個值依 Google 設計不算機密）
ALLOWED_SECRET_FILES = {"Google OAuth 用戶端密碼": {"data/credentials.json"}}

TEXT_SUFFIXES = {".py", ".json", ".md", ".txt", ".bat", ".ps1", ".vbs", ".ini", ".cfg", ".toml", ".yaml",
                 ".yml", ".html", ".js", ".css", ".spec", ".iss", ".sh", ".env", ".xml", ".csv"}


def _excluded(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return True
    if parts[0] == "data":
        return not (len(parts) == 2 and parts[1] in DATA_ALLOWLIST)
    name = parts[-1]
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_FILES)


def iter_release_files(root: Path = ROOT) -> Iterator[Path]:
    for p in sorted(root.rglob("*")):
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        rel = p.relative_to(root)
        if not _excluded(rel):
            yield rel


def scan_secrets(root: Path, files: List[Path]) -> List[str]:
    problems = []
    for rel in files:
        if rel.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            problems.append(f"{rel}: 無法讀取（{e}）")
            continue
        posix = rel.as_posix()
        for label, pat in SECRET_PATTERNS:
            if posix in ALLOWED_SECRET_FILES.get(label, set()):
                continue
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"{posix}:{line}  疑似 {label}")
    return problems


def build(out: Path, root: Path = ROOT) -> Tuple[int, int]:
    files = list(iter_release_files(root))
    out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            z.write(root / rel, Path("Syntra") / rel)
            total += (root / rel).stat().st_size
        # 空的 data/ 說明檔：首次啟動時程式會自動建立預設設定
        z.writestr("Syntra/data/README.txt",
                   "這個資料夾存放你個人的設定與登入資料（API Key、Google 登入、對話紀錄）。\n"
                   "請勿把這個資料夾分享給別人。\n")
    return len(files), total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="打包乾淨、不含個人資料的 Syntra 發佈檔")
    ap.add_argument("--check", action="store_true", help="只檢查，不產生 zip")
    ap.add_argument("--out", default=None, help="輸出 zip 路徑")
    args = ap.parse_args(argv)

    files = list(iter_release_files())
    data_files = [f.as_posix() for f in files if f.parts[0] == "data"]
    print(f"將打包 {len(files)} 個檔案；data/ 只包含：{', '.join(data_files) or '（無）'}")

    if "data/credentials.json" not in data_files:
        print("⚠️ 找不到 data/credentials.json：使用者將無法用 Google 登入（請先放入 OAuth 用戶端憑證）")

    problems = scan_secrets(ROOT, files)
    if problems:
        print("\n❌ 發現疑似金鑰，已中止打包（請移除後再試）：")
        for p in problems:
            print("   ", p)
        return 2
    print("✅ 金鑰掃描通過：沒有發現 API Key / Token / 私鑰")
    if args.check:
        return 0

    out = Path(args.out) if args.out else ROOT / "dist" / f"Syntra-{datetime.date.today():%Y%m%d}.zip"
    n, size = build(out)
    print(f"✅ 已產生 {out}（{n} 個檔案，原始大小 {size / 1_048_576:.1f} MB，壓縮後 {out.stat().st_size / 1_048_576:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
