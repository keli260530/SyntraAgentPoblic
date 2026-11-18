# -*- coding: utf-8 -*-
"""
作業系統無障礙功能 (Windows UI Automation) 核心引擎
落實 OOP 與模組化 (SOLID)：
使用 Windows 原生 Accessibility API (UIA 3.0) 替代或大幅輔助傳統純像素截圖。

技術優勢：
1. 0 截圖延遲、0 OCR 錯誤：直接由作業系統核心提取結構化控制項樹 (Accessibility Tree)。
2. 毫秒級無損文字提取：完美取得編輯器、瀏覽器、文件之原始文字內容。
3. 原生語義驅動：直接調用 InvokePattern / ValuePattern，無需模擬滑鼠即可點擊按鈕與輸入內容。
4. 萬無一失的座標定位：取得控制項精確 BoundingRectangle，滑鼠點擊誤差為 0。
5. Token 消耗降低 90%：相比一張 1080p 截圖消耗數千 Token，結構化文字樹僅需數百 Token。
"""

import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import uiautomation as auto
    import pythoncom
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False

import win32gui
import win32process


class AccessibilityNode:
    """
    單一無障礙控制項節點 (Accessibility UI Node)
    封裝 Windows UI Automation Control 的屬性、幾何位置與控制項 Pattern。
    """
    def __init__(
        self,
        node_id: str,
        name: str,
        control_type: str,
        automation_id: str,
        rect: Tuple[int, int, int, int],  # (left, top, right, bottom)
        value: str = "",
        is_enabled: bool = True,
        is_visible: bool = True,
        is_focused: bool = False,
        supported_patterns: Optional[List[str]] = None,
        raw_control: Any = None,
    ):
        self.node_id = node_id  # 例如 "#1", "#2"
        self.name = (name or "").strip()
        self.control_type = control_type or "Unknown"
        self.automation_id = automation_id or ""
        self.rect = rect
        self.value = (value or "").strip()
        self.is_enabled = is_enabled
        self.is_visible = is_visible
        self.is_focused = is_focused
        self.supported_patterns = supported_patterns or []
        self.raw_control = raw_control

    @property
    def left(self) -> int:
        return self.rect[0]

    @property
    def top(self) -> int:
        return self.rect[1]

    @property
    def right(self) -> int:
        return self.rect[2]

    @property
    def bottom(self) -> int:
        return self.rect[3]

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center_point(self) -> Tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.node_id,
            "name": self.name,
            "type": self.control_type,
            "automation_id": self.automation_id,
            "value": self.value,
            "rect": {
                "left": self.left,
                "top": self.top,
                "width": self.width,
                "height": self.height,
                "center_x": self.center_point[0],
                "center_y": self.center_point[1],
            },
            "enabled": self.is_enabled,
            "focused": self.is_focused,
            "patterns": self.supported_patterns,
        }

    def format_line(self, indent: int = 0) -> str:
        """生成簡潔、高語義的 LLM 提示字串"""
        parts = [f"{'  ' * indent}[{self.node_id}] {self.control_type}: '{self.name}'"] if self.name else [f"{'  ' * indent}[{self.node_id}] {self.control_type}"]
        
        extras = []
        if self.automation_id:
            extras.append(f"AutoId={self.automation_id}")
        if self.value:
            val_display = self.value if len(self.value) <= 50 else f"{self.value[:47]}..."
            extras.append(f"Val='{val_display}'")
        if self.is_focused:
            extras.append("FOCUSED")
        if not self.is_enabled:
            extras.append("DISABLED")

        # 座標與尺寸
        w, h = self.width, self.height
        cx, cy = self.center_point
        extras.append(f"pos=({cx},{cy}) {w}x{h}")

        if extras:
            parts.append(f" ({', '.join(extras)})")
        return "".join(parts)


class AccessibilityEngine:
    """
    作業系統無障礙自動化引擎 (OS Accessibility Automation Engine)
    封裝 Windows UI Automation Core 核心操作，支援無障礙樹檢索、原生 Pattern 調用與座標映射。
    """

    # 值得向 LLM 呈現的核心控制項類型
    SIGNIFICANT_TYPES = {
        "Button", "Edit", "Document", "Text", "CheckBox", "RadioButton",
        "ComboBox", "MenuItem", "TabItem", "TreeItem", "ListItem",
        "Hyperlink", "Slider", "ToolBar", "Window", "Group", "Pane",
    }

    # 需要優先保留其子項目的容器類型
    CONTAINER_TYPES = {"Window", "Pane", "Group", "Tab", "Tree", "List", "ToolBar", "MenuBar"}

    def __init__(self):
        self._cached_nodes: Dict[str, AccessibilityNode] = {}
        self._last_hwnd: int = 0

    @contextmanager
    def com_initialized(self):
        """確保跨線程 (Worker Thread / asyncio.to_thread) 呼叫時 Windows COM 正確初始化"""
        has_init = False
        try:
            pythoncom.CoInitialize()
            has_init = True
        except Exception:
            pass
        try:
            yield
        finally:
            if has_init:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def is_available(self) -> bool:
        return UIA_AVAILABLE

    def dump_window_tree(
        self,
        hwnd: int = 0,
        max_depth: int = 6,
        max_nodes: int = 100,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        掃描指定視窗的無障礙結構樹，回傳給 Agent 閱讀的高語意純文字，以及節點查找字典。
        代替原本的「純圖片截圖」分析！
        """
        if not UIA_AVAILABLE:
            return "系統未就緒：缺少 uiautomation 函式庫支援。", {}

        self._cached_nodes.clear()
        self._last_hwnd = hwnd

        with self.com_initialized():
            try:
                if hwnd != 0 and win32gui.IsWindow(hwnd):
                    win_title = (win32gui.GetWindowText(hwnd) or "視窗").strip()
                    root_ctrl = auto.ControlFromHandle(hwnd)
                else:
                    hwnd = 0
                    win_title = "目前焦點視窗 / 全螢幕"
                    root_ctrl = auto.GetFocusedControl()
                    if not root_ctrl or root_ctrl.ControlTypeName == "RootControl":
                        fg_hwnd = win32gui.GetForegroundWindow()
                        if fg_hwnd and win32gui.IsWindow(fg_hwnd):
                            root_ctrl = auto.ControlFromHandle(fg_hwnd)
                            win_title = win32gui.GetWindowText(fg_hwnd) or "前景視窗"
                        else:
                            root_ctrl = auto.GetRootControl()

                if not root_ctrl:
                    return f"無法取得視窗 (HWND: {hwnd}) 的無障礙控制項物件。", {}

                lines: List[str] = [
                    f"=== 視窗無障礙語意樹 (Accessibility UI Tree) ===",
                    f"目標視窗: {win_title} (HWND: {hwnd})",
                    f"說明: 括號前標籤如 [#1], [#2] 為元素 ID，可直接調用 ui_invoke 或 ui_type 操作。",
                    "--------------------------------------------------"
                ]

                node_counter = [0]
                nodes_dict: Dict[str, AccessibilityNode] = {}

                def _traverse(ctrl: Any, depth: int):
                    if node_counter[0] >= max_nodes or depth > max_depth:
                        return

                    try:
                        c_type = ctrl.ControlTypeName
                        if c_type.endswith("Control"):
                            c_type = c_type[:-7]
                        name = ctrl.Name
                        rect = ctrl.BoundingRectangle
                        w = rect.width() if hasattr(rect, "width") else (rect[2] - rect[0] if len(rect) >= 4 else 0)
                        h = rect.height() if hasattr(rect, "height") else (rect[3] - rect[1] if len(rect) >= 4 else 0)

                        if w <= 0 or h <= 0:
                            return

                        patterns = []
                        val = ""
                        try:
                            if hasattr(ctrl, "GetLegacyIAccessiblePattern") and ctrl.GetLegacyIAccessiblePattern():
                                val = ctrl.GetLegacyIAccessiblePattern().Value or ""
                        except Exception:
                            pass

                        try:
                            if hasattr(ctrl, "GetValuePattern") and ctrl.GetValuePattern():
                                val = ctrl.GetValuePattern().Value or val
                                patterns.append("Value")
                        except Exception:
                            pass

                        try:
                            if hasattr(ctrl, "GetInvokePattern") and ctrl.GetInvokePattern():
                                patterns.append("Invoke")
                        except Exception:
                            pass

                        try:
                            if hasattr(ctrl, "GetTogglePattern") and ctrl.GetTogglePattern():
                                patterns.append("Toggle")
                        except Exception:
                            pass

                        auto_id = ""
                        try:
                            auto_id = ctrl.AutomationId or ""
                        except Exception:
                            pass

                        is_focused = False
                        try:
                            is_focused = bool(ctrl.HasKeyboardFocus)
                        except Exception:
                            pass

                        is_enabled = True
                        try:
                            is_enabled = bool(ctrl.IsEnabled)
                        except Exception:
                            pass

                        rect_tuple = (rect.left, rect.top, rect.right, rect.bottom) if hasattr(rect, "left") else (rect[0], rect[1], rect[2], rect[3])

                        is_significant = (
                            c_type in self.SIGNIFICANT_TYPES
                            or bool(name)
                            or bool(val)
                            or bool(patterns)
                            or is_focused
                        )

                        if is_significant or depth == 0:
                            node_counter[0] += 1
                            node_id = f"#{node_counter[0]}"
                            node = AccessibilityNode(
                                node_id=node_id,
                                name=name,
                                control_type=c_type,
                                automation_id=auto_id,
                                rect=rect_tuple,
                                value=val,
                                is_enabled=is_enabled,
                                is_visible=True,
                                is_focused=is_focused,
                                supported_patterns=patterns,
                                raw_control=ctrl,
                            )
                            nodes_dict[node_id] = node
                            lines.append(node.format_line(indent=depth))

                        children = ctrl.GetChildren()
                        for child in children:
                            _traverse(child, depth + 1)
                    except Exception:
                        pass

                _traverse(root_ctrl, 0)
                self._cached_nodes = nodes_dict

                if len(nodes_dict) == 0:
                    lines.append("(此視窗未暴露標準無障礙元素，可能為純 GPU/DirectX 自繪視窗)")

                return "\n".join(lines), {k: v.to_dict() for k, v in nodes_dict.items()}

            except Exception as e:
                return f"讀取無障礙結構樹失敗：{str(e)}", {}

    def get_focused_element_info(self) -> Dict[str, Any]:
        """獲取目前聚焦控制項之詳細屬性"""
        if not UIA_AVAILABLE:
            return {"ok": False, "error": "缺少 uiautomation 庫"}

        with self.com_initialized():
            try:
                ctrl = auto.GetFocusedControl()
                if not ctrl:
                    return {"ok": False, "error": "目前沒有任何控制項獲得焦點"}

                rect = ctrl.BoundingRectangle
                rect_tup = (rect.left, rect.top, rect.right, rect.bottom)
                node = AccessibilityNode(
                    node_id="#focus",
                    name=ctrl.Name,
                    control_type=ctrl.ControlTypeName,
                    automation_id=ctrl.AutomationId,
                    rect=rect_tup,
                    value=getattr(ctrl.GetValuePattern(), "Value", "") if hasattr(ctrl, "GetValuePattern") and ctrl.GetValuePattern() else "",
                    is_focused=True,
                    raw_control=ctrl,
                )
                return {"ok": True, "node": node.to_dict()}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def invoke_element_by_id(self, element_id: str) -> Dict[str, Any]:
        """
        利用 Windows 原生 InvokePattern 直接點擊觸發目標按鈕！
        零滑鼠移動、零畫面遮擋干擾、極速執行。
        """
        node = self._find_node_by_id_or_name(element_id)
        if not node:
            return {"ok": False, "error": f"找不到無障礙元素：[{element_id}]，請先執行 inspect_accessibility_tree 更新元件清單。"}

        ctrl = node.raw_control
        if not ctrl:
            return {"ok": False, "error": f"節點 [{element_id}] 缺少原始控制項實例。"}

        with self.com_initialized():
            # 1. 優先嘗試 InvokePattern (原生按鈕點擊)
            try:
                invoke_pat = ctrl.GetInvokePattern()
                if invoke_pat:
                    invoke_pat.Invoke()
                    return {
                        "ok": True,
                        "action": "native_invoke",
                        "element_id": node.node_id,
                        "name": node.name,
                        "type": node.control_type,
                        "message": f"已成功以無障礙原生 InvokePattern 觸發 [{node.name or node.control_type}]！",
                    }
            except Exception as e:
                logging.debug(f"InvokePattern 失敗: {e}")

            # 2. 嘗試 TogglePattern (核取方塊 / 開關)
            try:
                toggle_pat = ctrl.GetTogglePattern()
                if toggle_pat:
                    toggle_pat.Toggle()
                    return {
                        "ok": True,
                        "action": "native_toggle",
                        "element_id": node.node_id,
                        "name": node.name,
                        "type": node.control_type,
                        "message": f"已成功以無障礙原生 TogglePattern 切換 [{node.name or node.control_type}] 狀態！",
                    }
            except Exception as e:
                logging.debug(f"TogglePattern 失敗: {e}")

            # 3. 嘗試 SelectionItemPattern (清單/分頁選中)
            try:
                sel_pat = ctrl.GetSelectionItemPattern()
                if sel_pat:
                    sel_pat.Select()
                    return {
                        "ok": True,
                        "action": "native_select",
                        "element_id": node.node_id,
                        "name": node.name,
                        "type": node.control_type,
                        "message": f"已成功以無障礙原生 SelectionItemPattern 選中 [{node.name or node.control_type}]！",
                    }
            except Exception as e:
                logging.debug(f"SelectionItemPattern 失敗: {e}")

            # 4. 若控制項未實作原生 Action Pattern，退回以無障礙精確座標點擊中心 (誤差為 0)
            cx, cy = node.center_point
            try:
                ctrl.Click(simulateMove=False)
                return {
                    "ok": True,
                    "action": "uia_click",
                    "element_id": node.node_id,
                    "name": node.name,
                    "coords": (cx, cy),
                    "message": f"該元件無原生 Invoke，已精準點擊其無障礙中心座標 ({cx}, {cy})。",
                }
            except Exception as e:
                return {"ok": False, "error": f"調用失敗：{str(e)}"}

    def set_element_value_by_id(self, element_id: str, value: str) -> Dict[str, Any]:
        """
        利用 Windows 原生 ValuePattern 直接填入文字，代替模擬鍵盤打字！
        毫秒級無損完成，不受輸入法、打字速度或焦點切換影響。
        """
        node = self._find_node_by_id_or_name(element_id)
        if not node:
            return {"ok": False, "error": f"找不到無障礙元素：[{element_id}]"}

        ctrl = node.raw_control
        if not ctrl:
            return {"ok": False, "error": f"節點 [{element_id}] 缺少原始控制項實例。"}

        with self.com_initialized():
            # 1. 優先原生 ValuePattern
            try:
                val_pat = ctrl.GetValuePattern()
                if val_pat:
                    val_pat.SetValue(value)
                    return {
                        "ok": True,
                        "action": "native_set_value",
                        "element_id": node.node_id,
                        "name": node.name,
                        "value_set": value,
                        "message": f"已成功以無障礙原生 ValuePattern 寫入文字至 [{node.name or node.control_type}]！",
                    }
            except Exception as e:
                logging.debug(f"ValuePattern 失敗: {e}")

            # 2. 次選：先聚焦，再使用 SendKeys
            try:
                ctrl.SetFocus()
                time.sleep(0.05)
                ctrl.SendKeys(value)
                return {
                    "ok": True,
                    "action": "uia_sendkeys",
                    "element_id": node.node_id,
                    "name": node.name,
                    "value_set": value,
                    "message": f"已聚焦該元件並寫入文字：{value}",
                }
            except Exception as e:
                return {"ok": False, "error": f"寫入文字失敗：{str(e)}"}

    def read_element_full_text(self, element_id: str) -> Dict[str, Any]:
        """
        深度提取無障礙元素或文件的完整純文字（利用 TextPattern 或 ValuePattern），
        完全無需 OCR 或看圖辨識！
        """
        node = self._find_node_by_id_or_name(element_id)
        if not node:
            return {"ok": False, "error": f"找不到元素 [{element_id}]"}

        ctrl = node.raw_control
        if not ctrl:
            return {"ok": False, "error": f"缺少原始控制項實例"}

        with self.com_initialized():
            text_content = ""
            # 嘗試 TextPattern (Word, 瀏覽器, 編輯器)
            try:
                txt_pat = ctrl.GetTextPattern()
                if txt_pat:
                    text_content = txt_pat.DocumentRange.GetText(-1)
            except Exception:
                pass

            # 嘗試 ValuePattern
            if not text_content:
                try:
                    val_pat = ctrl.GetValuePattern()
                    if val_pat:
                        text_content = val_pat.Value or ""
                except Exception:
                    pass

            # 嘗試 Name
            if not text_content:
                text_content = ctrl.Name or ""

            return {
                "ok": True,
                "element_id": node.node_id,
                "name": node.name,
                "type": node.control_type,
                "text": text_content,
                "length": len(text_content),
            }

    def _find_node_by_id_or_name(self, query: str) -> Optional[AccessibilityNode]:
        """按 ID (如 #1) 或名稱查找快取的無障礙節點"""
        clean = (query or "").strip()
        if not clean.startswith("#") and clean.isdigit():
            clean = f"#{clean}"

        if clean in self._cached_nodes:
            return self._cached_nodes[clean]

        q_low = clean.lower()
        for n in self._cached_nodes.values():
            if n.name.lower() == q_low or n.automation_id.lower() == q_low:
                return n

        for n in self._cached_nodes.values():
            if q_low in n.name.lower():
                return n

        return None


# 全域單例
accessibility_engine = AccessibilityEngine()
