"""
SKILL（技能文件 = 系统提示词）公共读取
======================================
· 位置：`<本包>/support_llama/skills/*.txt | *.md`
· 被两个节点共用：
    - `XB_QwenPromptPreset`（🖼️ Qwen2.1提示词预设）→ 官方 Generate Text 的 system_prompt
    - `XB_ImagePromptPresetPro`（🖼️ 生图提示词预设Pro）→ LLM 反推的 system prompt
· 语义：选中后整段作为系统提示词；「不使用」= 走各自节点原有的系统提示词。

设计要点
--------
· `skill_list()` 的**第一个选项固定是「不使用」**：老工作流没有这个字段时不改变行为；
· 只按文件名（`basename`）取文件，防目录穿越；
· 按 `mtime:size` 缓存全文，`skill_sig()` 供 IS_CHANGED 用（改 txt 自动重跑）；
· 编码 utf-8-sig → utf-8 → gbk 逐个退，最后 replace 兜底（绝不抛异常）。
"""

import os
import threading
import time

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(PACKAGE_DIR, "support_llama", "skills")
SKILL_NONE = "不使用"
_SKILL_EXTS = (".txt", ".md")
_CACHE = {"key": None, "text": ""}


def skill_list():
    """技能文件列表（combo 选项；第一个是「不使用」）"""
    try:
        names = [f for f in os.listdir(SKILL_DIR) if f.lower().endswith(_SKILL_EXTS)]
    except Exception:
        return [SKILL_NONE]
    return [SKILL_NONE] + sorted(names)


def skill_path(name):
    """只允许目录内的文件名（防目录穿越）；「不使用」/ 空 → None"""
    n = os.path.basename(str(name or "").strip())
    if not n or n == SKILL_NONE:
        return None
    return os.path.join(SKILL_DIR, n)


def skill_sig(name):
    """技能文件指纹（mtime:size）→ 文件内容变了自动重跑"""
    p = skill_path(name)
    if not p:
        return "-"
    try:
        st = os.stat(p)
        return f"{st.st_mtime_ns}:{st.st_size}"
    except Exception:
        return "-"


def skill_text(name, log_prefix=""):
    """技能全文（带缓存）；读不到只打印提示并返回空串，交给调用方继续走原有逻辑"""
    p = skill_path(name)
    if not p:
        return ""
    try:
        st = os.stat(p)
        key = (p, st.st_mtime_ns, st.st_size)
        if _CACHE.get("key") == key:
            return _CACHE.get("text", "")
        raw = open(p, "rb").read()
        text = ""
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        text = text.strip()
        _CACHE.update(key=key, text=text)
        return text
    except Exception as exc:
        print(f"{log_prefix or '[XB-SKILL]'} SKILL 读取失败（{name}）：{exc}")
        return ""


# ── 「打开文件夹并弹到最前」（Windows，ctypes 零依赖）─────────────────────────
# 背景：ComfyUI 服务进程**不是前台进程** → `os.startfile` 起出来的资源管理器窗口
#       往往落在浏览器后面（用户报「会打开但不会弹到表面」）。
# 做法：① 先 AllowSetForegroundWindow(ASFW_ANY) 放行；② 起窗口后后台线程轮询
#       EnumWindows 找到该文件夹的 CabinetWClass 窗口，并用 5 招强制前台
#       （最小化还原 / AttachThreadInput / topmost 闪一下 / 模拟 ALT / SwitchToThisWindow），
#       每轮都重试（前台锁会过期，通常第 2~3 轮成功）。
_SW_RESTORE = 9
_SW_MINIMIZE = 6
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_EXPLORER_CLASSES = ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW")


def _win_allow_foreground():
    """ASFW_ANY(-1)：允许随后启动的进程抢前台（否则 SetForegroundWindow 会被静默拒绝）"""
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)
        return True
    except Exception:
        return False


def _win_explorer_windows():
    """当前所有资源管理器顶层窗口 → [(hwnd:int, 标题:str)]（失败返回 []）"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value in _EXPLORER_CLASSES:
                title = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title, 512)
                found.append((int(hwnd), title.value))
            return True

        user32.EnumWindows(proto(_cb), 0)
        return found
    except Exception:
        return []


def _win_force_foreground(hwnd):
    """把窗口强行拉到最前（返回是否成功成为前台窗口）

    Windows 有「前台锁」：后台进程直接 SetForegroundWindow 常被静默拒绝 →
    下面按强度依次尝试 5 招（实测浏览器里点按钮时，前 3 招内必成功）。
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        if _win_foreground_hwnd() == hwnd:
            return True

        # ① 最小化 → 还原：让窗口重走一次激活流程
        user32.ShowWindow(hwnd, _SW_MINIMIZE)
        user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        if _win_foreground_hwnd() == hwnd:
            return True

        # ② AttachThreadInput 解除前台锁（最经典的一招）
        fg = _win_foreground_hwnd()
        tid_fg = int(user32.GetWindowThreadProcessId(fg, None)) if fg else 0
        tid_me = int(kernel32.GetCurrentThreadId())
        attached = False
        if tid_fg and tid_fg != tid_me:
            attached = bool(user32.AttachThreadInput(tid_me, tid_fg, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(tid_me, tid_fg, False)
        if _win_foreground_hwnd() == hwnd:
            return True

        # ③ 置顶闪一下（topmost → 取消 topmost）
        user32.BringWindowToTop(hwnd)
        user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE)
        user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE)
        user32.SetForegroundWindow(hwnd)
        if _win_foreground_hwnd() == hwnd:
            return True

        # ④ 模拟按一下 ALT：系统会认为本进程刚收到输入 → 放行前台切换
        try:
            user32.keybd_event(0x12, 0, 0, 0)      # VK_MENU down
            user32.keybd_event(0x12, 0, 2, 0)      # VK_MENU up
        except Exception:
            pass
        user32.SetForegroundWindow(hwnd)
        if _win_foreground_hwnd() == hwnd:
            return True

        # ⑤ SwitchToThisWindow（未文档化但通常有效）
        try:
            user32.SwitchToThisWindow(hwnd, True)
        except Exception:
            pass
        return _win_foreground_hwnd() == hwnd
    except Exception:
        return False


def _win_foreground_hwnd():
    """当前前台窗口 handle（失败返回 0）"""
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _win_pin_topmost(hwnd, seconds=1.2):
    """最后的杀招：把窗口钉在「最前」一小会儿（到点自动取消置顶）

    比瞬间闪一下更管用（瞬间闪往往还没被系统真正前置就取消了）。
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE)
        threading.Timer(max(0.2, float(seconds)), _win_unpin, args=(hwnd,)).start()
        return True
    except Exception:
        return False


def _win_unpin(hwnd):
    """取消置顶"""
    try:
        import ctypes

        ctypes.windll.user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE)
    except Exception:
        pass


def _win_raise_folder_window(path, before=(), tries=80, interval=0.12):
    """等资源管理器窗口出现并弹到最前（后台线程调用；不阻塞节点执行/HTTP 响应）

    · 最多等 tries×interval 秒（默认 ~10 秒，网络盘/冷启动的 Explorer 起得慢）；
    · 命中判据：标题含目录名；标题还没跟上（复用已有窗口）时取「新冒出来的窗口」；
    · **每轮都重试置前**（即使上一轮失败）：前台锁/用户正在操作会让单次激活失败，
      重试几轮基本都会过；一旦成功立即结束（不跟用户后续操作抢焦点）。
    """
    base = os.path.basename(str(path).rstrip("\\/")).lower()
    before_hwnds = {int(h) for h, _ in (before or ())}
    rounds = 0
    for _ in range(max(1, int(tries))):
        time.sleep(interval)
        wins = _win_explorer_windows()
        if not wins:
            continue
        hits = [h for h, t in wins if base and base in (t or "").lower()]
        if not hits:                       # 标题还没跟上（复用窗口）→ 取新冒出来的那个
            hits = [h for h, _ in wins if h not in before_hwnds]
        if not hits:
            continue
        rounds += 1
        for hwnd in hits:
            if _win_foreground_hwnd() == hwnd:             # 已经在前台 → 收工
                return True
            if _win_force_foreground(hwnd):
                return True
        if rounds >= 12:                                   # 反复失败 → 钉最前 1.2 秒兜底
            for hwnd in hits:
                _win_pin_topmost(hwnd, 1.2)
                return True
    return False


def open_skill_folder():
    """打开技能文件夹并**弹到最前**；返回 (ok, 绝对路径 / 错误信息)"""
    try:
        os.makedirs(SKILL_DIR, exist_ok=True)
        if os.name != "nt":
            import subprocess

            subprocess.Popen(["xdg-open", SKILL_DIR])   # Linux/macOS 兜底
            return True, SKILL_DIR
        if not hasattr(os, "startfile"):                 # pragma: no cover
            return False, "当前系统不支持自动打开，请手动打开：" + SKILL_DIR
        before = _win_explorer_windows()                 # 先记下已有窗口，便于识别新窗口
        _win_allow_foreground()
        os.startfile(SKILL_DIR)                          # noqa: S606  （Windows 专用）
        # 起窗口要几百毫秒；置前放后台线程，路由立即返回（浏览器不会卡）
        threading.Thread(target=_win_raise_folder_window, args=(SKILL_DIR, before),
                         daemon=True).start()
        return True, SKILL_DIR
    except Exception as exc:
        return False, f"{exc}（手动打开：{SKILL_DIR}）"


# ── HTTP 路由：面板上的「打开 SKILL 文件夹」按钮用 ─────────────────────
# 单独注册在 /xb_toolbox/skill_folder；服务未就绪 / 独立进程导入时静默跳过（不影响节点本身）
try:
    from server import PromptServer  # type: ignore
    from aiohttp import web  # type: ignore

    @PromptServer.instance.routes.get("/xb_toolbox/skill_folder")
    async def xb_skill_folder(request):  # noqa: ANN001
        ok, info = open_skill_folder()
        return web.json_response({"ok": bool(ok), "path": SKILL_DIR, "info": info}, status=200 if ok else 500)
except Exception:  # pragma: no cover - 仅在没有运行中的 ComfyUI 时走到
    pass
