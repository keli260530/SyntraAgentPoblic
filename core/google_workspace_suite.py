"""
core/google_workspace_suite.py
==============================
Google 全家桶 (Google Workspace Suite) 整合核心
涵蓋 Gmail、Google Drive、Google Calendar、Google Docs、Google Sheets 五大服務。
具備雙模式：
1. 官方 API 授權模式 (OAuth2 憑證快取)
2. 本機瀏覽器直接導航模式 (零配置降級備援)
"""

import os
import sys
import json
import base64
import time
from email.mime.text import MIMEText
from typing import List, Dict, Any, Optional

from types import SimpleNamespace

_GOOGLE = None


def _google():
    """延遲載入 Google API 套件（約 30MB 記憶體 / 0.4 秒）：沒設定 Google 的人完全不會載入。"""
    global _GOOGLE
    if _GOOGLE is None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload, MediaInMemoryUpload
        _GOOGLE = SimpleNamespace(Request=Request, Credentials=Credentials, InstalledAppFlow=InstalledAppFlow,
                                  build=build, MediaInMemoryUpload=MediaInMemoryUpload,
                                  MediaFileUpload=MediaFileUpload)
    return _GOOGLE

# 全套 Google Workspace 權限範圍
WORKSPACE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

class GoogleWorkspaceSuite:
    """Google Workspace 全功能套裝引擎"""

    def __init__(
        self,
        token_path: str = "data/google_token.json",
        creds_path: str = "data/credentials.json"
    ):
        self.token_path = token_path
        self.creds_path = creds_path
        self.creds: Optional[Any] = None
        self._services: Dict[str, Any] = {}
        self._try_authenticate()

    def _try_authenticate(self, interactive: bool = False) -> bool:
        """讀取現有 Token（必要時自動刷新）。interactive=True 才會開瀏覽器登入；
        啟動與工具呼叫一律不互動，避免開機卡住或突然跳出登入頁（登入請用設定頁的 Google 按鈕）。"""
        try:
            if not os.path.exists(self.token_path) and not os.path.exists(self.creds_path):
                return False  # 尚未設定 Google：不載入任何 Google 套件
            if os.path.exists(self.token_path):
                # 不指定 scopes：沿用 token 檔裡實際授權的範圍。使用者在「權限與功能」只勾部分權限時，
                # 若這裡硬塞全部 WORKSPACE_SCOPES，刷新 token 會被 Google 以 invalid_scope 拒絕。
                # 登入金鑰以 Windows DPAPI 加密保存，只有這台電腦的這個 Windows 帳號解得開
                from .secure_store import read_text as _read_secret
                self.creds = _google().Credentials.from_authorized_user_info(json.loads(_read_secret(self.token_path)))

            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(_google().Request())
                try:
                    from .secure_store import write_text as _write_secret
                    _write_secret(self.token_path, self.creds.to_json())
                except Exception:
                    pass

            if (not self.creds or not self.creds.valid) and interactive:
                if os.path.exists(self.creds_path):
                    flow = _google().InstalledAppFlow.from_client_secrets_file(self.creds_path, WORKSPACE_SCOPES)
                    self.creds = flow.run_local_server(port=0)
                    from .secure_store import write_text as _write_secret
                    _write_secret(self.token_path, self.creds.to_json())

            return bool(self.creds and self.creds.valid)
        except Exception:
            return False

    def is_authenticated(self) -> bool:
        return bool(self.creds and self.creds.valid)

    def _get_service(self, name: str, version: str):
        if not self.is_authenticated():
            if not self._try_authenticate():
                raise RuntimeError(
                    "尚未登入 Google 帳戶（或登入已過期）。請到 設定 → Google 分頁 按「使用 Google 帳戶登入」，"
                    "或改用瀏覽器直接操作模式。"
                )
        key = f"{name}_{version}"
        if key not in self._services:
            self._services[key] = _google().build(name, version, credentials=self.creds)
        return self._services[key]

    # ==========================================
    # 1. GMAIL 模組
    # ==========================================
    def gmail_list_messages(self, query: str = "label:INBOX", max_results: int = 5) -> List[Dict[str, Any]]:
        """檢索 Gmail 郵件清單 (支援 query 如 is:unread, from:boss)"""
        service = self._get_service("gmail", "v1")
        results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        messages = results.get("messages", [])

        email_list = []
        for msg in messages:
            msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()
            headers = {h["name"]: h["value"] for h in msg_data["payload"]["headers"]}
            email_list.append({
                "id": msg["id"],
                "thread_id": msg.get("threadId"),
                "subject": headers.get("Subject", "(無主旨)"),
                "from": headers.get("From", "(未知寄件人)"),
                "date": headers.get("Date", ""),
                "snippet": msg_data.get("snippet", "")
            })
        return email_list

    def gmail_read_message(self, message_id: str) -> Dict[str, Any]:
        """讀取特定郵件的詳細內文"""
        service = self._get_service("gmail", "v1")
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        
        body = ""
        payload = msg.get("payload", {})
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                        break
        elif "body" in payload and payload["body"].get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

        return {
            "id": message_id,
            "subject": headers.get("Subject", "(無主旨)"),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "body": body or msg.get("snippet", "")
        }

    def gmail_send_message(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """發送 Gmail 郵件"""
        service = self._get_service("gmail", "v1")
        message = MIMEText(body, "plain", "utf-8")
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True, "message_id": sent.get("id")}

    # ==========================================
    # 2. GOOGLE DRIVE 模組
    # ==========================================
    def gdrive_search_files(self, name_contains: str = "", mime_type: str = "", max_results: int = 10) -> List[Dict[str, Any]]:
        """檢索 Google 雲端硬碟檔案"""
        service = self._get_service("drive", "v3")
        query_parts = ["trashed = false"]
        if name_contains:
            query_parts.append(f"name contains '{name_contains}'")
        if mime_type:
            query_parts.append(f"mimeType = '{mime_type}'")
        
        q = " and ".join(query_parts)
        res = service.files().list(
            q=q,
            pageSize=max_results,
            fields="files(id, name, mimeType, modifiedTime, webViewLink, size)"
        ).execute()
        return res.get("files", [])

    def gdrive_upload_content(self, filename: str, content: str, mime_type: str = "text/markdown") -> Dict[str, Any]:
        """直接將字串內容作為檔案上傳至雲端硬碟"""
        service = self._get_service("drive", "v3")
        file_metadata = {"name": filename, "mimeType": mime_type}
        media = _google().MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type, resumable=False)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink"
        ).execute()
        return {
            "success": True,
            "id": uploaded.get("id"),
            "name": uploaded.get("name"),
            "link": uploaded.get("webViewLink")
        }

    def gdrive_upload_local_file(self, local_path: str, remote_filename: Optional[str] = None) -> Dict[str, Any]:
        """將本地磁碟檔案上傳至雲端硬碟"""
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"本地檔案不存在: {local_path}")
        
        service = self._get_service("drive", "v3")
        name = remote_filename or os.path.basename(local_path)
        file_metadata = {"name": name}
        media = _google().MediaFileUpload(local_path, resumable=True)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink"
        ).execute()
        return {
            "success": True,
            "id": uploaded.get("id"),
            "name": uploaded.get("name"),
            "link": uploaded.get("webViewLink")
        }

    # ==========================================
    # 3. GOOGLE CALENDAR 日曆模組
    # ==========================================
    def gcalendar_list_events(self, days_ahead: int = 7, max_results: int = 10) -> List[Dict[str, Any]]:
        """取得未來 N 天的日曆事件與會議清單"""
        service = self._get_service("calendar", "v3")
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        future_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + days_ahead * 86400))

        events_result = service.events().list(
            calendarId="primary",
            timeMin=now_iso,
            timeMax=future_iso,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        
        events = events_result.get("items", [])
        clean_events = []
        for e in events:
            start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date"))
            end = e.get("end", {}).get("dateTime", e.get("end", {}).get("date"))
            clean_events.append({
                "id": e.get("id"),
                "summary": e.get("summary", "(無主旨)"),
                "start": start,
                "end": end,
                "location": e.get("location", ""),
                "description": e.get("description", "")
            })
        return clean_events

    def gcalendar_create_event(
        self,
        summary: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
        location: str = ""
    ) -> Dict[str, Any]:
        """建立全新 Google 日曆行程 (時間格式: 2026-11-04T15:00:00+08:00)"""
        service = self._get_service("calendar", "v3")
        event_body = {
            "summary": summary,
            "location": location,
            "description": description,
            "start": {"dateTime": start_iso},
            "end": {"dateTime": end_iso},
        }
        created = service.events().insert(calendarId="primary", body=event_body).execute()
        return {
            "success": True,
            "id": created.get("id"),
            "summary": created.get("summary"),
            "html_link": created.get("htmlLink")
        }

    # ==========================================
    # 4. GOOGLE DOCS 文件模組
    # ==========================================
    def gdocs_create(self, title: str, initial_text: str = "") -> Dict[str, Any]:
        """建立空白或帶有初始文字的 Google Docs 文件"""
        docs_service = self._get_service("docs", "v1")
        doc = docs_service.documents().create(body={"title": title}).execute()
        doc_id = doc.get("documentId")

        if initial_text:
            requests = [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": initial_text
                    }
                }
            ]
            docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

        return {
            "success": True,
            "document_id": doc_id,
            "title": title,
            "docs_url": f"https://docs.google.com/document/d/{doc_id}/edit"
        }

    def gdocs_read(self, document_id: str) -> str:
        """讀取 Google Docs 文件的完整純文字內容"""
        docs_service = self._get_service("docs", "v1")
        doc = docs_service.documents().get(documentId=document_id).execute()
        
        text_content = []
        for item in doc.get("body", {}).get("content", []):
            if "paragraph" in item:
                elements = item.get("paragraph", {}).get("elements", [])
                for elem in elements:
                    text_run = elem.get("textRun", {})
                    if "content" in text_run:
                        text_content.append(text_run["content"])
        return "".join(text_content)

    def gdocs_append_text(self, document_id: str, text: str) -> bool:
        """在 Google Docs 文件尾部追加段落"""
        docs_service = self._get_service("docs", "v1")
        doc = docs_service.documents().get(documentId=document_id).execute()
        # 取得結尾 index
        content = doc.get("body", {}).get("content", [])
        end_index = max(1, content[-1].get("endIndex", 1) - 1)

        requests = [
            {
                "insertText": {
                    "location": {"index": end_index},
                    "text": ("\n" if not text.startswith("\n") else "") + text
                }
            }
        ]
        docs_service.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()
        return True

    # ==========================================
    # 5. GOOGLE SHEETS 試算表模組
    # ==========================================
    def gsheets_create(self, title: str) -> Dict[str, Any]:
        """建立全新 Google Sheets 試算表"""
        service = self._get_service("sheets", "v4")
        sheet = service.spreadsheets().create(body={"properties": {"title": title}}).execute()
        sheet_id = sheet.get("spreadsheetId")
        return {
            "success": True,
            "spreadsheet_id": sheet_id,
            "sheets_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
        }

    def gsheets_read(self, spreadsheet_id: str, range_name: str = "A1:Z100") -> List[List[Any]]:
        """讀取 Google Sheets 指定範圍之行與列"""
        service = self._get_service("sheets", "v4")
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        return result.get("values", [])

    def gsheets_append_row(self, spreadsheet_id: str, values: List[Any], range_name: str = "Sheet1!A1") -> Dict[str, Any]:
        """在 Google Sheets 追加資料列（例如追加工作日誌、花費、紀錄）"""
        service = self._get_service("sheets", "v4")
        body = {"values": [values]}
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        return {"success": True, "updates": result.get("updates")}

    # ==========================================
    # 6. 免 API KEY 瀏覽器直接操作模式 (Fallback)
    # ==========================================
    @staticmethod
    def get_service_url(service_name: str) -> str:
        """獲取各服務官方首頁 URL"""
        urls = {
            "gmail": "https://mail.google.com",
            "drive": "https://drive.google.com",
            "calendar": "https://calendar.google.com",
            "docs": "https://docs.google.com",
            "sheets": "https://sheets.google.com",
        }
        return urls.get(service_name.lower(), "https://myaccount.google.com")


# 全域單例
google_suite = GoogleWorkspaceSuite()
