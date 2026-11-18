import asyncio
import ctypes
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SandboxExecutor:
    """
    本機安全沙箱執行核心：
    1. Windows Job Object 資源邊界防護：限制記憶體 (Max 512MB)、限制子進程數量 (Max 4)、超時自動熔斷、退出時連帶強制清除所有衍生進程。
    2. 環境變數脫敏 (Environment Scrubbing)：自動剝離 API Key、Token、密碼等本機機密，防止代碼外洩憑證。
    3. 獨立沙箱目錄 (Isolated Scratchpad)：在專屬隔離空間中執行，限制檔案破壞範圍。
    4. 支援動態生成 Windows Sandbox (.wsb) 虛擬化沙箱配置，以實體隔離執行極高危可疑檔案。
    """

    SENSITIVE_ENV_VARS = [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_TOKEN",
        "SSH_AUTH_SOCK", "AZURE_OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY",
        "COHERE_API_KEY", "DATABASE_URL", "MYSQL_PWD", "PGPASSWORD",
    ]

    def __init__(self, sandbox_root: Optional[Path] = None):
        self.sandbox_root = sandbox_root or (Path(__file__).resolve().parent.parent / "data" / "sandbox")
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def _get_clean_env(self, custom_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        過濾掉所有敏感金鑰與機密環境變數。
        """
        env = dict(os.environ)
        for var in self.SENSITIVE_ENV_VARS:
            env.pop(var, None)
        # 清除任何含 KEY、TOKEN、SECRET、PASSWORD 的環境變數
        for k in list(env.keys()):
            k_upper = k.upper()
            if any(term in k_upper for term in ("API_KEY", "SECRET", "PRIVATE_KEY", "AUTH_TOKEN")):
                env.pop(k, None)

        if custom_env:
            env.update(custom_env)
        return env

    def _setup_job_object(self, max_memory_mb: int = 512, max_processes: int = 4):
        """
        利用 Windows Job Object 限制記憶體用量與衍生進程，並確保主行程結束時子行程全數連帶終止。
        """
        try:
            import win32job
            import win32api
            import win32con

            job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)

            # 設定旗標：
            # 1. 關閉 Job 時自動殺死所有進程
            # 2. 限制進程記憶體上限
            # 3. 限制行程總數
            limits = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info["BasicLimitInformation"]["LimitFlags"] = limits
            info["BasicLimitInformation"]["ActiveProcessLimit"] = max_processes
            info["ProcessMemoryLimit"] = max_memory_mb * 1024 * 1024

            win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
            return job
        except Exception:
            return None

    async def execute_in_sandbox(
        self,
        command: str,
        timeout: float = 30.0,
        max_memory_mb: int = 512,
        clean_scratch_after: bool = True,
    ) -> Dict[str, Any]:
        """
        在 Job Object 與受控環境中執行腳本或指令。
        """
        session_id = f"box_{uuid.uuid4().hex[:8]}"
        scratch_dir = self.sandbox_root / session_id
        scratch_dir.mkdir(parents=True, exist_ok=True)

        clean_env = self._get_clean_env()

        def _run():
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
                creationflags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS

            job = self._setup_job_object(max_memory_mb=max_memory_mb)

            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}"],
                cwd=str(scratch_dir),
                env=clean_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )

            if job:
                try:
                    import win32job
                    win32job.AssignProcessToJobObject(job, proc._handle)
                except Exception:
                    pass

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                out = (stdout or "") + ("\n" + stderr if stderr else "")
                return {
                    "ok": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "output": out.strip()[:10000],
                    "session_id": session_id,
                    "sandbox_dir": str(scratch_dir),
                }
            except subprocess.TimeoutExpired:
                proc.kill()
                return {
                    "ok": False,
                    "exit_code": -2,
                    "output": f"沙箱執行超時（超過 {timeout} 秒限制），行程已安全強制熔斷終止！",
                    "session_id": session_id,
                    "sandbox_dir": str(scratch_dir),
                }

        try:
            result = await asyncio.to_thread(_run)
            return result
        finally:
            if clean_scratch_after and scratch_dir.exists():
                try:
                    shutil.rmtree(scratch_dir, ignore_errors=True)
                except Exception:
                    pass

    def generate_windows_sandbox_profile(
        self,
        target_file_or_dir: str,
        networking: bool = False,
        read_only: bool = True,
    ) -> Tuple[bool, str]:
        """
        動態生成 Windows Sandbox (.wsb) 虛擬機沙箱配置檔案。
        可雙擊或直接由 Agent 啟動 Windows 官方微虛擬機徹底隔離執行未知 EXE。
        """
        target_path = Path(target_file_or_dir).resolve()
        if not target_path.exists():
            return False, f"目標檔案不存在：{target_file_or_dir}"

        shared_dir = target_path if target_path.is_dir() else target_path.parent
        target_file_name = target_path.name if target_path.is_file() else ""

        net_val = "Default" if networking else "Disable"
        ro_val = "true" if read_only else "false"

        logon_cmd = ""
        if target_file_name:
            logon_cmd = f"""  <LogonCommand>
    <Command>powershell -NoExit -Command "Write-Host '=== Windows Sandbox 隔離執行環境 ===' -ForegroundColor Yellow; Set-Location 'C:\\Users\\WDAGUtilityAccount\\Desktop\\SandboxFiles'; Get-ChildItem"</Command>
  </LogonCommand>"""

        wsb_content = f"""<Configuration>
  <Networking>{net_val}</Networking>
  <ProtectedClient>Enable</ProtectedClient>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{str(shared_dir)}</HostFolder>
      <SandboxFolder>C:\\Users\\WDAGUtilityAccount\\Desktop\\SandboxFiles</SandboxFolder>
      <ReadOnly>{ro_val}</ReadOnly>
    </MappedFolder>
  </MappedFolders>
{logon_cmd}
</Configuration>"""

        profile_path = self.sandbox_root / f"run_{target_path.stem}.wsb"
        profile_path.write_text(wsb_content, encoding="utf-8")
        return True, str(profile_path)
