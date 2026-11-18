from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

HELP_HTML = """
<div style="font-family:'Segoe UI','Microsoft JhengHei',sans-serif; color:#f1f5f9; line-height:1.6; font-size:13px;">
    <h2 style="color:#60a5fa; margin-bottom:6px; font-size:18px;">🔑 API Key 智慧接入與管理使用指南</h2>
    <p style="color:#94a3b8; margin-bottom:14px;">
        本系統支援同時接入多組 AI 廠商（Google Gemini、OpenAI、Claude、DeepSeek 等），具備自動特徵識別、智慧編號命名與全自訂功能。
    </p>

    <div style="background:#161922; border-left:3px solid #38bdf8; padding:10px 14px; margin-bottom:12px; border-radius:4px;">
        <strong style="color:#38bdf8; font-size:14px;">一、3 秒快速上手（最簡單用法）</strong>
        <ol style="margin-top:6px; padding-left:18px; color:#cbd5e1;">
            <li>在「<b>🔑 貼上 API Key</b>」欄位貼上你的金鑰（例如 <code>AIzaSy...</code> 或 <code>sk-ant-...</code>）。</li>
            <li>系統會<b>瞬間自動分析編碼</b>，自動識別出是哪家公司，並智慧命名為 <code>Google Gemini (金鑰 #1)</code>。</li>
            <li>直接點擊下方「<b>💾 儲存這組 API Key</b>」即完成！</li>
        </ol>
    </div>

    <div style="background:#161922; border-left:3px solid #818cf8; padding:10px 14px; margin-bottom:12px; border-radius:4px;">
        <strong style="color:#818cf8; font-size:14px;">二、自訂金鑰名稱</strong>
        <p style="margin-top:6px; color:#cbd5e1;">
            自動命名的編號只是建議，你可以<b>隨時在「名稱」欄位修改成任何你喜歡的名字</b>（例如：<code>我的主力 Gemini</code>、<code>公司帳號 Claude</code>、<code>便宜備用 DeepSeek</code>）。修改後點儲存即可。
        </p>
    </div>

    <div style="background:#161922; border-left:3px solid #22c55e; padding:10px 14px; margin-bottom:12px; border-radius:4px;">
        <strong style="color:#22c55e; font-size:14px;">三、常見各家 API Key 編碼特徵</strong>
        <table style="width:100%; border-collapse:collapse; margin-top:8px; font-size:12px; color:#cbd5e1;">
            <tr style="border-bottom:1px solid rgba(255,255,255,0.1); color:#94a3b8; text-align:left;">
                <th style="padding:4px 6px;">廠商名稱</th>
                <th style="padding:4px 6px;">Key 開頭特徵</th>
                <th style="padding:4px 6px;">自動推薦模型</th>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
                <td style="padding:5px 6px;"><b>Google Gemini</b></td>
                <td><code>AIzaSy...</code></td>
                <td>gemini-2.5-pro, gemini-2.5-flash</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
                <td style="padding:5px 6px;"><b>Anthropic Claude</b></td>
                <td><code>sk-ant-...</code></td>
                <td>claude-3-7-sonnet-latest</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
                <td style="padding:5px 6px;"><b>OpenAI</b></td>
                <td><code>sk-proj-...</code> 或 <code>sk-...</code></td>
                <td>gpt-4o, gpt-4.1, o3-mini</td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
                <td style="padding:5px 6px;"><b>DeepSeek</b></td>
                <td><code>sk-...</code> (32位十六進位)</td>
                <td>deepseek-chat, deepseek-reasoner</td>
            </tr>
            <tr>
                <td style="padding:5px 6px;"><b>Groq / OpenRouter</b></td>
                <td><code>gsk_...</code> / <code>sk-or-...</code></td>
                <td>llama-3.3-70b / 多家模型混用</td>
            </tr>
        </table>
    </div>

    <div style="background:#161922; border-left:3px solid #f59e0b; padding:10px 14px; margin-bottom:12px; border-radius:4px;">
        <strong style="color:#f59e0b; font-size:14px;">四、「進階網路選項」何時才需要填？</strong>
        <p style="margin-top:6px; color:#cbd5e1;">
            <b>使用各家官方金鑰時：完全不需要填寫，請直接留空！</b><br>
            只有在以下特殊情況才需要展開「進階網路選項」：
            <ul style="margin-top:4px; padding-left:18px; color:#94a3b8;">
                <li>你使用了自己架設的 OneAPI、NewAPI 或第三方中轉代理伺服器。</li>
                <li>你在本機執行了 Ollama / LocalAI 等本地私有模型伺服器。</li>
            </ul>
        </p>
    </div>

    <div style="background:#161922; border-left:3px solid #ec4899; padding:10px 14px; margin-bottom:12px; border-radius:4px;">
        <strong style="color:#ec4899; font-size:14px;">五、如何驗證與切換？</strong>
        <ul style="margin-top:6px; padding-left:18px; color:#cbd5e1;">
            <li><b>⚡ 測試連線</b>：填完 Key 後點擊「測試連線」，系統會發送極小 ping 請求，回傳綠色代表 Key 完全有效。</li>
            <li><b>切換使用模型</b>：關閉此對話框後，在主視窗左上角的下拉選單，就會列出所有已啟用金鑰對應的模型，隨選即用。</li>
        </ul>
    </div>
</div>
"""


class ApiHelpDialog(QDialog):
    """
    職責：展示 API Key 接入與設定的完整圖文說明指南 (落實 OOP 單一職責模式)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("❓ API Key 智慧接入與管理 — 完整說明指南")
        self.resize(680, 560)
        self.setStyleSheet("""
            QDialog {
                background-color: #0e1015;
                color: #f1f5f9;
            }
            QPushButton {
                background-color: #1e2230;
                color: #f1f5f9;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 6px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #283044;
                border-color: #60a5fa;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        browser = QTextBrowser()
        browser.setHtml(HELP_HTML)
        browser.setStyleSheet("background-color: #11141d; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 12px;")
        layout.addWidget(browser)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton("我知道了，關閉說明")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
