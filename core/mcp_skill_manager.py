import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


class McpSkillManager:
    """
    職責：管理所有可用 Skill (技能模組) 與 MCP (Model Context Protocol) 伺服器與工具。
    支援自動掃描本機技能庫、查看描述、開關狀態，以及手動新增/編輯/測試 MCP 伺服器。
    """

    SKILL_SEARCH_DIRS = [
        Path.home() / ".gemini" / "antigravity" / "builtin" / "skills",
        Path.home() / ".gemini" / "config" / "skills",
        Path(__file__).resolve().parent.parent / "skills",
    ]

    def __init__(self, data_dir: Optional[Path] = None):
        base_dir = Path(__file__).resolve().parent.parent
        self.data_dir = data_dir or (base_dir / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.mcp_config_path = self.data_dir / "mcp_servers.json"
        self.mcp_servers: List[Dict[str, Any]] = self._load_mcp_servers()

    def _default_mcp_servers(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "filesystem",
                "name": "Local File System",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
                "enabled": True,
                "description": "讀寫本機檔案、目錄結構遍歷與搜尋",
            },
            {
                "id": "git_server",
                "name": "Git Repository Tool",
                "command": "uvx",
                "args": ["mcp-server-git"],
                "enabled": False,
                "note": "需要先安裝 uv（提供 uvx 指令）才能啟用；npm 上沒有這個套件。",
                "description": "Git 提交歷史、分支管理與 Diff 檢視",
            },
            {
                "id": "fetch_server",
                "name": "Web Content Fetcher",
                "command": "uvx",
                "args": ["mcp-server-fetch"],
                "enabled": False,
                "note": "需要先安裝 uv（提供 uvx 指令）才能啟用；npm 上沒有這個套件。",
                "description": "安全擷取外部網站內容與轉換 Markdown",
            },
            {
                "id": "chrome-devtools",
                "name": "Chrome DevTools MCP (官方網頁除錯與效能分析)",
                "command": "npx",
                "args": ["-y", "chrome-devtools-mcp@latest"],
                "enabled": False,
                "license": "Apache-2.0 (ChromeDevTools/chrome-devtools-mcp)",
                "note": "一鍵掛載 Google Chrome DevTools MCP（需本機有 Node.js/npx），提供 Console 除錯、Network/CORS 檢查、效能剖析 (LCP/INP/CLS) 與跑版檢測。",
                "description": "網頁開發與前端檢查必備：CDP 除錯、Console/Network 追蹤與 Core Web Vitals 效能剖析 (Apache-2.0)",
            },
        ]

    def ensure_recommended_mcp(self, mcp_id: str, enable: bool = True) -> bool:
        """確保推薦的 MCP 伺服器（如 chrome-devtools）已註冊於清單中，供一鍵啟用。"""
        defaults = {d["id"]: d for d in self._default_mcp_servers()}
        target = defaults.get(mcp_id)
        if not target:
            return False
        for srv in self.mcp_servers:
            if srv.get("id") == mcp_id:
                if enable:
                    srv["enabled"] = True
                    self._save_mcp_servers(self.mcp_servers)
                return True
        entry = dict(target)
        entry["enabled"] = bool(enable)
        self.mcp_servers.append(entry)
        self._save_mcp_servers(self.mcp_servers)
        return True

    def _load_mcp_servers(self) -> List[Dict[str, Any]]:
        if self.mcp_config_path.exists():
            try:
                data = json.loads(self.mcp_config_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        defaults = self._default_mcp_servers()
        self._save_mcp_servers(defaults)
        return defaults

    def _save_mcp_servers(self, servers: List[Dict[str, Any]]):
        self.mcp_config_path.write_text(
            json.dumps(servers, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_all_skills(self) -> List[Dict[str, Any]]:
        """掃描電腦上所有的 SKILL.md 技能定義"""
        skills: List[Dict[str, Any]] = []
        seen_names = set()

        for s_dir in self.SKILL_SEARCH_DIRS:
            if not s_dir.exists():
                continue
            for skill_file in s_dir.glob("*/SKILL.md"):
                try:
                    folder_name = skill_file.parent.name
                    if folder_name in seen_names:
                        continue

                    content = skill_file.read_text(encoding="utf-8", errors="replace")
                    meta, desc = self._parse_skill_md(content, default_name=folder_name)
                    seen_names.add(folder_name)

                    skills.append({
                        "id": folder_name,
                        "name": meta.get("name", folder_name),
                        "description": meta.get("description", desc[:150]),
                        "category": "Built-in" if "builtin" in str(skill_file) else "Custom",
                        "path": str(skill_file),
                        "enabled": True,
                    })
                except Exception:
                    continue

        return skills

    def _parse_skill_md(self, text: str, default_name: str) -> tuple[Dict[str, Any], str]:
        meta = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    parsed = yaml.safe_load(parts[1])
                    if isinstance(parsed, dict):
                        meta = parsed
                    body = parts[2].strip()
                except Exception:
                    pass
        # 提取第一段普通文字作為描述
        lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")]
        desc = lines[0] if lines else default_name
        return meta, desc

    def get_mcp_servers(self) -> List[Dict[str, Any]]:
        return self.mcp_servers

    def upsert_mcp_server(self, data: Dict[str, Any]) -> Dict[str, Any]:
        sid = (data.get("id") or f"mcp_{int(data.get('timestamp', 0))}").strip()
        name = (data.get("name") or sid).strip()
        command = data.get("command", "npx").strip()
        raw_args = data.get("args") or []
        if isinstance(raw_args, str):
            args = [a.strip() for a in raw_args.split() if a.strip()]
        else:
            args = list(raw_args)

        enabled = data.get("enabled", True)
        desc = data.get("description", "").strip()

        idx = next((i for i, s in enumerate(self.mcp_servers) if s["id"] == sid), None)
        item = {
            "id": sid,
            "name": name,
            "command": command,
            "args": args,
            "enabled": enabled,
            "status": "CONFIGURED",
            "description": desc,
        }
        if idx is not None:
            self.mcp_servers[idx] = item
        else:
            self.mcp_servers.append(item)

        self._save_mcp_servers(self.mcp_servers)
        return item

    def install_skill_from_folder_or_code(
        self, skill_name: str, description: str, instructions: str, scripts: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        讓 Agent 動態建立並安裝新的 Skill：
        在專案 skills 目錄下生成 SKILL.md 與可執行的 scripts/。
        """
        target_dir = Path(__file__).resolve().parent.parent / "skills" / skill_name
        target_dir.mkdir(parents=True, exist_ok=True)

        # 寫入 SKILL.md
        skill_md_content = f"""---
name: {skill_name}
description: {description}
---

# {skill_name}

{instructions}
"""
        (target_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

        # 寫入輔助 scripts
        saved_scripts = []
        if scripts:
            scripts_dir = target_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            for s_name, s_code in scripts.items():
                s_path = scripts_dir / s_name
                s_path.write_text(s_code, encoding="utf-8")
                saved_scripts.append(str(s_path))

        return {
            "ok": True,
            "skill_name": skill_name,
            "path": str(target_dir),
            "scripts": saved_scripts,
            "message": f"Skill [{skill_name}] 安裝成功！可在終端透過 run_skill_script 執行。",
        }

    async def execute_skill_script(
        self, skill_name: str, script_name: str, args: Optional[List[str]] = None, cwd: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        在終端安全執行指定 Skill 的 scripts 目錄腳本 (支援 .py, .ps1, .sh, .bat, .js)
        """
        import asyncio
        import sys

        args = args or []
        # 尋找 skill 目錄
        target_dir = None
        for s_dir in self.SKILL_SEARCH_DIRS:
            candidate = s_dir / skill_name
            if candidate.exists() and candidate.is_dir():
                target_dir = candidate
                break

        if not target_dir:
            return {"ok": False, "error": f"找不到 Skill [{skill_name}]"}

        script_path = target_dir / "scripts" / script_name
        if not script_path.exists():
            # 嘗試根目錄
            script_path = target_dir / script_name
            if not script_path.exists():
                return {"ok": False, "error": f"在 Skill [{skill_name}] 找不到腳本 [{script_name}]"}

        ext = script_path.suffix.lower()
        if ext == ".py":
            cmd = [sys.executable, str(script_path)] + args
        elif ext == ".ps1":
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)] + args
        elif ext in [".bat", ".cmd"]:
            cmd = ["cmd.exe", "/c", str(script_path)] + args
        elif ext == ".js":
            cmd = ["node", str(script_path)] + args
        else:
            cmd = [str(script_path)] + args

        work_dir = cwd or str(target_dir)

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                creationflags=creationflags,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "command": " ".join(cmd),
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"ok": False, "error": "腳本執行逾時 (超時 60 秒)"}
        except Exception as e:
            return {"ok": False, "error": f"執行腳本失敗: {str(e)}"}

    def delete_mcp_server(self, server_id: str) -> bool:
        init_len = len(self.mcp_servers)
        self.mcp_servers = [s for s in self.mcp_servers if s["id"] != server_id]
        if len(self.mcp_servers) < init_len:
            self._save_mcp_servers(self.mcp_servers)
            return True
        return False
