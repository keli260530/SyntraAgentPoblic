"""
core/ui_automation_driver.py
============================
Windows 原生 UI Automation (UIA) 語意驅動引擎
取代傳統「CV 截圖 + OCR + 座標盲點」的脆弱自動化模式。
直接掛鉤 Windows 輔助技術樹 (Accessibility Tree)，實現毫秒級、無焦點、抗解析度縮放的精確 GUI 操控。
"""

import time
from typing import Optional, List, Dict, Any, Union
import uiautomation as auto

class UIAutomationDriver:
    def __init__(self, default_search_depth: int = 8, search_timeout: float = 2.0):
        self.default_search_depth = default_search_depth
        self.search_timeout = search_timeout
        auto.SetGlobalSearchTimeout(search_timeout)

    def find_window(
        self,
        name_regex: Optional[str] = None,
        class_name: Optional[str] = None,
        process_id: Optional[int] = None
    ) -> Optional[auto.WindowControl]:
        """尋找頂層視窗"""
        params = {"searchDepth": 1}
        if name_regex:
            params["RegexName"] = name_regex
        if class_name:
            params["ClassName"] = class_name
        if process_id:
            params["ProcessId"] = process_id

        win = auto.WindowControl(**params)
        if win.Exists(maxSearchSeconds=self.search_timeout):
            return win
        return None

    def find_element(
        self,
        parent: Optional[auto.Control] = None,
        control_type: Optional[str] = None,
        name: Optional[str] = None,
        name_regex: Optional[str] = None,
        automation_id: Optional[str] = None,
        search_depth: Optional[int] = None
    ) -> Optional[auto.Control]:
        """
        在父視窗/元素下精準查找控制項
        """
        depth = search_depth or self.default_search_depth
        parent_ctrl = parent or auto.GetRootControl()

        query = {"searchDepth": depth}
        if control_type:
            query["ControlType"] = getattr(auto.ControlType, f"{control_type}Control", None) or control_type
        if name:
            query["Name"] = name
        if name_regex:
            query["RegexName"] = name_regex
        if automation_id:
            query["AutomationId"] = automation_id

        target = parent_ctrl.Control(**query)
        if target.Exists(maxSearchSeconds=self.search_timeout):
            return target
        return None

    def invoke_button(
        self,
        window_name_regex: str,
        button_name: Optional[str] = None,
        automation_id: Optional[str] = None
    ) -> bool:
        """
        後台精準點擊按鈕：
        優先使用 UIA InvokePattern 瞬發（不搶滑鼠），
        若目標不支持 Invoke 則退回瞬發 Click(simulateMove=False)。
        """
        win = self.find_window(name_regex=window_name_regex)
        if not win:
            return False

        btn = self.find_element(
            parent=win,
            control_type="Button",
            name=button_name,
            automation_id=automation_id
        )
        if not btn:
            return False

        try:
            pattern = btn.GetInvokePattern()
            if pattern:
                pattern.Invoke()
                return True
        except Exception:
            pass

        try:
            btn.Click(simulateMove=False)
            return True
        except Exception:
            return False

    def set_edit_text(
        self,
        window_name_regex: str,
        text: str,
        edit_name: Optional[str] = None,
        automation_id: Optional[str] = None
    ) -> bool:
        """
        後台精準寫入文字欄位（Edit / Document）：
        使用 ValuePattern 或 SendKeys，無需游標手動選中。
        """
        win = self.find_window(name_regex=window_name_regex)
        if not win:
            return False

        edit_ctrl = self.find_element(
            parent=win,
            control_type="Edit",
            name=edit_name,
            automation_id=automation_id
        )
        if not edit_ctrl:
            edit_ctrl = self.find_element(
                parent=win,
                control_type="Document",
                name=edit_name,
                automation_id=automation_id
            )
        if not edit_ctrl:
            return False

        try:
            val_pattern = edit_ctrl.GetValuePattern()
            if val_pattern:
                val_pattern.SetValue(text)
                return True
        except Exception:
            pass

        try:
            edit_ctrl.SendKeys(text, waitTime=0.01)
            return True
        except Exception:
            return False

    def get_element_text(
        self,
        window_name_regex: str,
        control_name: Optional[str] = None,
        automation_id: Optional[str] = None
    ) -> Optional[str]:
        """抓取目標控制項的值或文字內容"""
        win = self.find_window(name_regex=window_name_regex)
        if not win:
            return None

        ctrl = self.find_element(
            parent=win,
            name=control_name,
            automation_id=automation_id
        )
        if not ctrl:
            return None

        # 嘗試讀取 ValuePattern
        try:
            val_pattern = ctrl.GetValuePattern()
            if val_pattern:
                return val_pattern.Value
        except Exception:
            pass

        # 嘗試 Name 或 TextPattern
        try:
            return ctrl.Name
        except Exception:
            return None

    def dump_control_tree(
        self,
        window_name_regex: str,
        max_depth: int = 3
    ) -> List[Dict[str, Any]]:
        """
        導出指定視窗的階層式控制項樹結構，便於 Agent 自適應感知介面架構
        """
        win = self.find_window(name_regex=window_name_regex)
        if not win:
            return []

        tree_nodes = []

        def _traverse(ctrl, current_depth):
            if current_depth > max_depth:
                return
            try:
                node = {
                    "type": ctrl.ControlTypeName,
                    "name": ctrl.Name,
                    "automation_id": ctrl.AutomationId,
                    "depth": current_depth,
                    "rect": [ctrl.BoundingRectangle.left, ctrl.BoundingRectangle.top,
                             ctrl.BoundingRectangle.right, ctrl.BoundingRectangle.bottom]
                }
                tree_nodes.append(node)
                for child in ctrl.GetChildren():
                    _traverse(child, current_depth + 1)
            except Exception:
                pass

        _traverse(win, 1)
        return tree_nodes


# 全域單例
uia_driver = UIAutomationDriver()
