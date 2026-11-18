"""
本地模型接入詢問對話框：列出偵測到的新本地模型，讓使用者勾選要接入 Agent 的項目。
"""

from typing import Any, Dict, List, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

# 對話框結果
RESULT_ADD = 1
RESULT_LATER = 0
RESULT_NEVER = 2


class LocalModelConsentDialog(QDialog):
    def __init__(self, services: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.services = services
        self.choice = RESULT_LATER
        self.setWindowTitle("🖥️ 偵測到本機模型")
        self.resize(520, 420)

        lay = QVBoxLayout(self)
        total = sum(len(s["models"]) for s in services)
        intro = QLabel(
            f"<b>在這台電腦上找到 {total} 個尚未接入的本地模型。</b><br>"
            "<span style='color:#94a3b8;'>勾選要加入 Agent 的模型。本地模型免 API Key、資料不外傳，"
            "一般任務會優先使用。</span>"
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.list = QListWidget()
        for si, svc in enumerate(services):
            header = QListWidgetItem(f"── {svc['name']}  ({svc['base_url']})")
            header.setFlags(Qt.NoItemFlags)
            self.list.addItem(header)
            for model in svc["models"]:
                it = QListWidgetItem(f"    {model}")
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked)
                it.setData(Qt.UserRole, (si, model))
                self.list.addItem(it)
        lay.addWidget(self.list, stretch=1)

        btns = QHBoxLayout()
        btn_add = QPushButton("✅ 加入勾選的模型")
        btn_add.setStyleSheet("background-color: #059669; color: white; font-weight: 600; padding: 6px 12px;")
        btn_later = QPushButton("稍後再說")
        btn_never = QPushButton("不再詢問這些模型")
        btn_add.clicked.connect(lambda: self._finish(RESULT_ADD))
        btn_later.clicked.connect(lambda: self._finish(RESULT_LATER))
        btn_never.clicked.connect(lambda: self._finish(RESULT_NEVER))
        btns.addWidget(btn_never)
        btns.addStretch(1)
        btns.addWidget(btn_later)
        btns.addWidget(btn_add)
        lay.addLayout(btns)
        btn_add.setDefault(True)

    def _finish(self, choice: int):
        self.choice = choice
        self.accept()

    def selections(self, checked: bool = True) -> List[Tuple[Dict[str, Any], List[str]]]:
        """回傳 [(service, [models...])]；checked=False 時回傳未勾選的項目"""
        picked: Dict[int, List[str]] = {}
        for i in range(self.list.count()):
            it = self.list.item(i)
            data = it.data(Qt.UserRole)
            if not data:
                continue
            if (it.checkState() == Qt.Checked) == checked:
                si, model = data
                picked.setdefault(si, []).append(model)
        return [(self.services[si], models) for si, models in picked.items()]
