# Third-Party Notices & Open-Source Attributions

Syntra uses or optionally integrates the following third-party open-source projects and libraries. All rights belong to their respective authors and copyright holders.

---

## 1. Optional Recommended MCP Integration
### Chrome DevTools MCP (`ChromeDevTools/chrome-devtools-mcp`)
- **Repository**: https://github.com/ChromeDevTools/chrome-devtools-mcp
- **License**: Apache License 2.0
- **Copyright**: Copyright Google LLC / Chrome DevTools Authors
- **Usage**: Optional MCP server (`npx -y chrome-devtools-mcp@latest`) for browser DevTools debugging, DOM/layout inspection, network/console tracing, and Core Web Vitals profiling.

---

## 2. Core Runtime Libraries (`requirements.txt` & Security Modules)
| Package | Purpose in Syntra | License |
| :--- | :--- | :--- |
| **PyQt5** | Desktop GUI framework (`desktop_app.py`, `ui/`) | GPL v3 / Riverbank Commercial |
| **windows-capture** | Zero-flicker Windows Graphics Capture (`core/wgc_capture.py`) | MIT |
| **cryptography** | Ed25519 signature verification & AES-256-GCM DLC encryption | Apache-2.0 / BSD-3-Clause |
| **FastAPI** / **Uvicorn** | Local & backend HTTP API server | MIT / BSD-3-Clause |
| **Pydantic** | Structured schema & config validation | MIT |
| **httpx** / **websockets** | Async HTTP & WebSocket transport | BSD-3-Clause / BSD-3-Clause |
| **Pillow** / **NumPy** | Image processing & screen frame conversion | HPND / BSD-3-Clause |
| **psutil** | Cross-platform process & system inspection | BSD-3-Clause |
| **pywin32** | Windows Win32 API & shortcut resolution | PSF |
| **pynput** | Input monitoring & human-like automation | LGPL-3.0 |
| **BeautifulSoup4** | HTML parsing for web content extraction | MIT |
| **PyYAML** | YAML frontmatter parsing | MIT |

---

## 3. Architectural References
- **Pathways Single-Controller Asynchronous DAG Orchestration** (`core/pathways_orchestrator.py`): Inspired by Google's Pathways single-controller architecture concepts (https://developers.googleblog.com/en/what-is-pathways-single-controller-training-for-large-models/).

---

## Apache License 2.0 Summary Notice
For components licensed under the Apache License, Version 2.0 (including `chrome-devtools-mcp` and `cryptography`):

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
