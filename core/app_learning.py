# -*- coding: utf-8 -*-
"""
軟體操作的「學習迴路」（App Learning）——讓代理自己學會用軟體，而不是靠人替每個軟體寫手冊。

適用任何軟體（不限 app_playbooks 裡那幾個）：

1. 認得軟體：開過／操作過的軟體會登記名稱（data/app_learning/apps.json），之後使用者提到就認得。
2. 記教訓：某個做法失敗了（不是被權限或免打擾擋下），記下「怎麼做 → 為什麼失敗」；
   同一輪後來換方法成功，連「後來怎麼成功的」一起記。下次相似要求會提醒不要重蹈覆轍。
3. 失敗過就先讀書：對相似要求失敗過、還沒成功過 → 下次動手前由系統先讀本機說明／上網查（照常經過權限），
   查到的資料會存進知識庫（app_knowledge）。
4. 使用者回饋：👎 → 忘掉那次記下的「成功做法」並記成教訓；👍 → 標成已確認的做法。
5. 成功做法本身仍由 app_experience 記錄與取用（這裡只負責讓它認得手冊以外的軟體）。

全部是本機檔案、純文字比對，不呼叫模型。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import app_experience, app_playbooks

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "app_learning"
MAX_LESSONS_PER_APP = 60
LESSON_SIMILARITY = 0.15     # 多像才把教訓拿出來提醒
STUDY_SIMILARITY = 0.30      # 多像才算「同一件事失敗過」

# 哪些工具的哪個參數是「軟體名稱」
_APP_ARG = {"launch_application": "target", "type_in_app": "app", "open_file_in_app": "app",
            "learn_app_ui": "app", "app_howto": "app", "read_app_help": "app", "research_app_howto": "app"}
# 真的動手操作的工具（失敗才值得記成教訓；純觀察、查資料的不算）
_ACTION_TOOLS = (set(app_experience._APP_TOOLS) - {"inspect_accessibility_tree"}) | {"computer_key", "computer_scroll",
                                                                                     "computer_drag"}
# 這些失敗跟「會不會用這個軟體」無關，不記
_NOT_A_LESSON = ("blocked_by_permission", "deferred_by_dnd", "免打擾", "使用者拒絕", "緊急停止", "kill switch")
_QUESTION_RE = re.compile(r"[?？]\s*$|請告訴我|請問|需要我.*嗎|請提供|請您|請再")

GUIDE = (
    "#### 🧠 操作軟體的原則（任何軟體都適用，禁止寫死）\n"
    "1. 下面有「以前成功過的做法」或「動態學習使用說明與 UI 地圖」就照做；有「失敗過的做法」就避開，不要重蹈覆轍。\n"
    "2. 沒做過或不知道軟體能做什麼、沒有操作地圖時：先呼叫 `discover_and_map_apps`（會先徵詢使用者同意再掃描建圖與實測補全），"
    "或用 `learn_app_ui`／`inspect_accessibility_tree`／`read_app_help` 了解介面；不要憑印象亂按。\n"
    "3. 若畫面主視窗被彈窗阻擋（主視窗禁用），先檢查彈窗視窗的按鈕並關閉彈窗，再操作主程式。\n"
    "4. 做完看工具回傳的結果確認真的成功（ok、verified）；失敗就換一種方法再試，"
    "不要叫使用者自己做，也不要叫使用者「再說一次」。\n"
    "5. 要求沒講細節（例如要寫什麼內容、什麼格式）時，自己擬一份合理的先做出來，再說明可以怎麼改；"
    "只有刪除、覆寫、送出這類不能復原的事才先問。\n"
)


# ---------------------------------------------------------------- 認得軟體
def slug(name: str) -> Optional[str]:
    """任何軟體名稱 → 穩定的 key（手冊裡有的用手冊 key）。"""
    raw = (name or "").strip().strip('"')
    if not raw:
        return None
    low = raw.lower()
    if low in app_playbooks.PLAYBOOKS:
        return low
    key = app_playbooks.find_app(raw)
    if key:
        return key
    if "\\" in low or "/" in low:               # 路徑 → 檔名
        low = os.path.splitext(os.path.basename(low.replace("\\", "/")))[0]
    low = re.sub(r"\.(exe|lnk)$", "", low)
    s = re.sub(r"[^0-9a-z一-鿿]+", "", low)[:40]
    return s or None


def _registry_path(data_dir: Optional[Path]) -> Path:
    return (data_dir or _DATA_DIR) / "apps.json"


def known_apps(data_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    try:
        d = json.loads(_registry_path(data_dir).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def register(name: str, data_dir: Optional[Path] = None) -> Optional[str]:
    """登記一個用過的軟體（手冊裡已有的不用登記）。"""
    key = slug(name)
    if not key or key in app_playbooks.PLAYBOOKS or len(key) < 2:
        return key
    apps = known_apps(data_dir)
    entry = apps.get(key) or {"name": name.strip()[:60], "names": [], "uses": 0}
    nm = name.strip()[:60]
    if nm and nm.lower() not in [n.lower() for n in entry["names"]]:
        entry["names"] = (entry["names"] + [nm])[-6:]
    entry["uses"] = int(entry.get("uses", 0)) + 1
    entry["last"] = time.strftime("%Y-%m-%d %H:%M:%S")
    apps[key] = entry
    p = _registry_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(apps, ensure_ascii=False, indent=1), encoding="utf-8")
    return key


def display_name(key: str, data_dir: Optional[Path] = None) -> str:
    pb = app_playbooks.PLAYBOOKS.get(key)
    if pb:
        return pb["name"]
    return (known_apps(data_dir).get(key) or {}).get("name") or key


def find_apps(text: str, data_dir: Optional[Path] = None) -> List[str]:
    """文字裡提到哪些軟體：手冊裡的 ＋ 以前用過而登記的。"""
    out = list(app_playbooks.find_apps(text))
    t = app_playbooks._norm(text)
    if not t:
        return out
    t_nospace = t.replace(" ", "")
    for key in app_playbooks.PLAYBOOKS:
        if key not in out and re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", t):
            out.append(key)
    for key, entry in known_apps(data_dir).items():
        if key in out:
            continue
        names = [n for n in (entry.get("names") or [entry.get("name", "")]) if len(n) >= 2]
        if any(app_playbooks._alias_hit(n, t, t_nospace) for n in names):
            out.append(key)
    return out


def apps_from_steps(tool_steps: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """從工具參數看這一輪操作了哪些軟體：[(key, 原始名稱)]。"""
    out: List[Tuple[str, str]] = []
    for st in tool_steps or []:
        arg = _APP_ARG.get(str(st.get("tool")))
        name = str((st.get("args") or {}).get(arg, "")).strip() if arg else ""
        key = slug(name) if name else None
        if key and key not in [k for k, _ in out]:
            out.append((key, name))
    return out


def primary_app(user_message: str, tool_steps: List[Dict[str, Any]], data_dir: Optional[Path] = None) -> Optional[str]:
    hits = find_apps(user_message, data_dir)
    if hits:
        return hits[0]
    used = apps_from_steps(tool_steps)
    return used[0][0] if used else None


# ---------------------------------------------------------------- 教訓
def _lessons_path(app: str, data_dir: Optional[Path]) -> Path:
    return (data_dir or _DATA_DIR) / f"{app}.lessons.jsonl"


def load_lessons(app: str, data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    p = _lessons_path(app, data_dir)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _save_lessons(app: str, lessons: List[Dict[str, Any]], data_dir: Optional[Path]) -> None:
    p = _lessons_path(app, data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    lessons = lessons[-MAX_LESSONS_PER_APP:]
    p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lessons), encoding="utf-8")


def _failed(step: Dict[str, Any]) -> bool:
    return bool(step.get("failed")) or app_experience._step_failed(step)


def _error_of(step: Dict[str, Any]) -> str:
    prev = str(step.get("result_preview", ""))
    try:
        d = json.loads(prev)
        if isinstance(d, dict):
            prev = str(d.get("error") or d.get("message") or prev)
    except Exception:
        m = re.search(r'"(?:error|message)"\s*:\s*"([^"]{4,200})', prev)
        if m:
            prev = m.group(1)
    return " ".join(prev.split())[:180]


def _is_lesson(step: Dict[str, Any]) -> bool:
    if step.get("tool") not in _ACTION_TOOLS or not _failed(step):
        return False
    prev = str(step.get("result_preview", "")).lower()
    return not any(w.lower() in prev for w in _NOT_A_LESSON)


_OPEN_ONLY = {"launch_application", "open_file_in_app"}


def looks_unfinished(final_text: str, tool_steps: List[Dict[str, Any]]) -> bool:
    """這一輪其實沒做完？——除了「開啟軟體」以外沒有任何成功的操作，回覆卻在反問使用者／叫使用者自己做。
    （做完之後客氣地問「還需要調整嗎？」不算。）這種回合不該被記成成功做法，而且要記成教訓。"""
    t = (final_text or "").strip()
    if not t or not _QUESTION_RE.search(t[-160:]):
        return False
    did = [s for s in (tool_steps or []) if s.get("tool") in _ACTION_TOOLS and not _failed(s)]
    return all(s.get("tool") in _OPEN_ONLY for s in did)


def record(user_message: str, tool_steps: List[Dict[str, Any]], final_ok: bool,
           sanitize: Callable[[str], str] = lambda s: s, data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """一輪結束時呼叫：登記用過的軟體、把失敗的做法記成教訓、成功時把相似的教訓標成已解決。"""
    used = apps_from_steps(tool_steps)
    for _key, name in used:
        try:
            register(name, data_dir)
        except Exception:
            pass
    app = primary_app(user_message, tool_steps, data_dir)
    if not app:
        return {"app": None, "lessons": 0}
    request = sanitize((user_message or "").strip())[:300]
    lessons = load_lessons(app, data_dir)
    added = 0
    touched = False
    steps = list(tool_steps or [])
    for i, st in enumerate(steps):
        if not _is_lesson(st):
            continue
        fix = None
        if final_ok:
            for later in steps[i + 1:]:
                if later.get("tool") in _ACTION_TOOLS and not _failed(later):
                    fix = {"tool": later["tool"], "args": app_experience._clip_args(later.get("args", {}))}
                    break
        err = sanitize(_error_of(st))
        args = json.loads(sanitize(json.dumps(app_experience._clip_args(st.get("args", {}), 100), ensure_ascii=False)))
        same = next((x for x in lessons if x.get("tool") == st["tool"] and x.get("error", "")[:50] == err[:50]
                     and app_experience.similarity(x.get("request", ""), request) >= 0.6), None)
        if same:
            same["count"] = int(same.get("count", 1)) + 1
            same["last"] = time.strftime("%Y-%m-%d %H:%M:%S")
            same["fix"] = fix or same.get("fix")
            same["resolved"] = bool(same.get("fix"))
            touched = True
        else:
            lessons.append({"app": app, "request": request, "tool": st["tool"], "args": args, "error": err,
                            "fix": fix, "resolved": bool(fix), "studied": False, "count": 1,
                            "last": time.strftime("%Y-%m-%d %H:%M:%S")})
            added += 1
    if not final_ok and not added and not any(_failed(s) for s in steps if s.get("tool") in _ACTION_TOOLS)             and any(s.get("tool") in _ACTION_TOOLS for s in steps):
        # 沒有哪一步出錯，卻沒把事情做完（例如只開了軟體就反問使用者）→ 也是教訓
        did = [s["tool"] for s in steps if s.get("tool") in _ACTION_TOOLS]
        if not any(x.get("tool") == "(沒做完)" and app_experience.similarity(x.get("request", ""), request) >= 0.6
                   for x in lessons):
            lessons.append({"app": app, "request": request, "tool": "(沒做完)", "args": {"did": did[:6]},
                            "error": "只做了前面幾步就停下來反問使用者，沒有完成要求",
                            "fix": None, "resolved": False, "studied": False, "count": 1,
                            "last": time.strftime("%Y-%m-%d %H:%M:%S")})
            added += 1
    acted_ok = final_ok and any(s.get("tool") in _ACTION_TOOLS and not _failed(s) for s in steps) \
        and not any(_is_lesson(s) for s in steps)
    if acted_ok:  # 這次順利做完 → 相似要求的舊教訓算是學會了
        for x in lessons:
            if app_experience.similarity(x.get("request", ""), request) >= STUDY_SIMILARITY:
                x["resolved"] = True
    if added or touched or acted_ok:
        _save_lessons(app, lessons, data_dir)
    return {"app": app, "lessons": added}


def relevant_lessons(app: str, request: str, k: int = 3, data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    scored = [(app_experience.similarity(x.get("request", ""), request), x) for x in load_lessons(app, data_dir)]
    scored = [(s, x) for s, x in scored if s >= LESSON_SIMILARITY]
    scored.sort(key=lambda p: (-p[0], -int(p[1].get("count", 1))))
    return [x for _, x in scored[:k]]


def render_lessons(app: str, request: str, k: int = 3, data_dir: Optional[Path] = None) -> str:
    items = relevant_lessons(app, request, k, data_dir)
    # 「沒做完」這類教訓一旦後來學會了（resolved）就不用再提醒；有記下替代做法的才留著
    items = [x for x in items if not (x.get("resolved") and not x.get("fix"))]
    if not items:
        return ""
    lines = ["#### ⚠️ 以前在這個軟體失敗過的做法（不要再這樣做）"]
    for x in items:
        if x.get("by_user") or x.get("tool") == "(沒做完)":
            # 不是哪一步出錯，而是「做一半就停」：要提醒的是把事情做完，不是避開那一步
            did = x.get("tool") if x.get("by_user") else "、".join((x.get("args") or {}).get("did", []))
            lines.append(f"- 要求「{x.get('request', '')[:50]}」：上次只做了 `{did}` 就停下來"
                         + ("，使用者說這樣不對（沒有完成要求）" if x.get("by_user") else "反問使用者，沒有完成要求")
                         + " → 這次要把整件事做完，不要只做第一步。")
            continue
        line = (f"- 要求「{x.get('request', '')[:50]}」：`{x.get('tool')}` "
                f"{json.dumps(x.get('args', {}), ensure_ascii=False)[:160]} → 失敗：{x.get('error', '')[:120]}")
        if x.get("by_user"):
            line += "（使用者說這樣不對）"
        fix = x.get("fix")
        if fix:
            line += f"；後來改用 `{fix.get('tool')}` {json.dumps(fix.get('args', {}), ensure_ascii=False)[:160]} 才成功"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------- 失敗過就先讀書
def study_target(user_message: str, data_dir: Optional[Path] = None) -> Optional[Tuple[str, str, str]]:
    """這則要求是不是「以前相似的事失敗過、還沒學會、也還沒查過資料」？是 → (app key, 顯示名稱, 要查的事)。"""
    for app in find_apps(user_message, data_dir):
        for x in load_lessons(app, data_dir):
            if x.get("resolved") or x.get("studied"):
                continue
            if app_experience.similarity(x.get("request", ""), user_message) >= STUDY_SIMILARITY:
                return app, display_name(app, data_dir), _task_words(user_message, app, data_dir)
    return None


def _task_words(user_message: str, app: str, data_dir: Optional[Path] = None) -> str:
    """把要求裡的軟體名稱和客套話拿掉，剩下「要做的事」當查詢關鍵字。"""
    t = user_message or ""
    names = [display_name(app, data_dir)] + list((app_playbooks.PLAYBOOKS.get(app) or {}).get("aliases", [])) \
        + list((known_apps(data_dir).get(app) or {}).get("names", []))
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        t = re.sub(re.escape(n), " ", t, flags=re.IGNORECASE)
    t = re.sub(r"請|幫我|幫忙|麻煩|一下|打開|開啟|然後|並且|並|在.{0,2}裡|不儲存|不存檔|不要存檔", " ", t)
    return " ".join(t.split())[:60] or (user_message or "")[:60]


def mark_studied(app: str, user_message: str, data_dir: Optional[Path] = None) -> int:
    lessons = load_lessons(app, data_dir)
    n = 0
    for x in lessons:
        if not x.get("studied") and app_experience.similarity(x.get("request", ""), user_message) >= STUDY_SIMILARITY:
            x["studied"] = True
            n += 1
    if n:
        _save_lessons(app, lessons, data_dir)
    return n


# ---------------------------------------------------------------- 使用者回饋（👍／👎）
def feedback(request: str, liked: bool, exp_dir: Optional[Path] = None, data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """使用者對某一輪按了 👍 或 👎。
    👎：那一輪如果被記成「成功做法」，忘掉它並記成教訓（下次不再照做，而且會先查資料）。
    👍：把那筆成功做法標成使用者確認過。"""
    request = (request or "").strip()
    if not request:
        return {"ok": False, "changed": 0}
    d = exp_dir or app_experience._DATA_DIR
    changed = 0
    apps = [p.stem for p in d.glob("*.jsonl")] if d.exists() else []
    for app in apps:
        entries = app_experience.load(app, d)
        keep, hit = [], []
        for e in entries:
            (hit if app_experience.similarity(e.get("request", ""), request) >= 0.85 else keep).append(e)
        if not hit:
            continue
        changed += len(hit)
        if liked:
            for e in hit:
                e["confirmed"] = True
            keep = keep + hit
        else:
            lessons = load_lessons(app, data_dir)
            for e in hit:
                first = (e.get("steps") or [{}])[0]
                lessons.append({"app": app, "request": e.get("request", request)[:300], "tool": first.get("tool", ""),
                                "args": first.get("args", {}), "error": "使用者表示這樣做的結果不對／沒有完成要求",
                                "fix": None, "resolved": False, "studied": False, "by_user": True, "count": 1,
                                "last": time.strftime("%Y-%m-%d %H:%M:%S")})
            _save_lessons(app, lessons, data_dir)
        path = d / f"{app}.jsonl"
        if keep:
            path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep), encoding="utf-8")
        elif path.exists():
            path.unlink()
    return {"ok": True, "changed": changed, "liked": liked}


# ---------------------------------------------------------------- 給提示詞用
def context_note(apps: List[str], request: str, data_dir: Optional[Path] = None) -> str:
    """提到軟體時附上：通用操作原則 ＋ 各軟體相關的教訓。"""
    if not apps:
        return ""
    parts = [GUIDE]
    for app in apps:
        txt = render_lessons(app, request, data_dir=data_dir)
        if txt:
            parts.append(f"（{display_name(app, data_dir)}）\n{txt}")
    return "\n".join(parts) + "\n"


def summary(data_dir: Optional[Path] = None, exp_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """每個軟體學了多少（成功做法數、教訓數、還沒學會的數量），給介面或除錯看。"""
    d = exp_dir or app_experience._DATA_DIR
    keys = set(known_apps(data_dir)) | ({p.stem for p in d.glob("*.jsonl")} if d.exists() else set())
    base = data_dir or _DATA_DIR
    if base.exists():
        keys |= {p.name[:-len(".lessons.jsonl")] for p in base.glob("*.lessons.jsonl")}
    out = []
    for k in sorted(keys):
        ls = load_lessons(k, data_dir)
        out.append({"app": k, "name": display_name(k, data_dir), "skills": len(app_experience.load(k, d)),
                    "lessons": len(ls), "unresolved": sum(1 for x in ls if not x.get("resolved"))})
    return out
