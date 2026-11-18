# -*- coding: utf-8 -*-
"""Syntra 星樞 自動化安裝 agent。

用法：
    py -m installer                 互動模式（推薦 / 完整 / 自訂）
    py -m installer --recommended   依環境自動選擇
    py -m installer --full          完整安裝
    py -m installer --modules desktop-ui,google-workspace
    py -m installer --dry-run ...   只列出計畫，不實際安裝

安全原則：本安裝程式不讀取、不上傳、不修改 data/ 內任何檔案；
安裝狀態記錄在專案根目錄的 .syntra/install-manifest.json（已列入 .gitignore）。
"""

__version__ = "1.0.0"
