"""
xb_skill 预设文件加载器（生图提示词预设等节点共用）
====================================================
目录约定（每个节点一个文件夹，按语言分子目录）：

    xb_skill/
      XB_ImagePromptPreset/
        ZH/  01-人物三视图.txt        02-人物四视图.txt …
        EN/  01-Character Three-View.txt  02-Character Four-View.txt …

· 一个 txt = 一个下拉选项，文件名（去掉编号前缀与 .txt）= 选项名，文件内容 = 该选项的设定词；
· 文件名前缀 `01-` / `1.` / `01_` 只用于排序，不进入选项名；
· 语言目录按 ComfyUI 系统语言自动选：中文（zh*）→ ZH，其他所有语言 → EN；
· 英文目录用**英文文件名**（可读性），但取值上仍对应中文规范档位名：`LABEL_ALIASES` 负责等价，
  所以「中文目录 + 中文档位值」与「英文目录 + 英文档位值」互相都能取到同一份文案；
· 目录不存在 / 没有 txt 时返回空，调用方自行回退到内置文案（老部署不受影响）。
"""

import json
import os
import re
import time

ROOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "xb_skill")
DEFAULT_NODE = "XB_ImagePromptPreset"

ZH = "ZH"
EN = "EN"
LANG_FOLDERS = (ZH, EN)
# 与节点「输出语言」下拉的文字一一对应（前端拿这份 key 查表）
LANG_LABELS = {ZH: "中文 [ZH]", EN: "英文 [EN]"}

_PREFIX_RE = re.compile(r"^\s*(\d+)\s*[-_.,，、．]?\s*")
_CACHE_TTL = 1.5
_cache = {}      # {绝对路径: (时间戳, [(顺序, 选项名, 路径), …])}

# 英文目录的**文件名**用英文（可读性好），但它对应的是同一个「档位」：
#   这里把英文文件名等价到中文规范档位名 —— **对外（下拉选项 / 工作流取值 / 前端查表）一律用规范名**，
#   这样中文系统与英文系统、以及互相之间打开工作流都指向同一个档位，文案不会错位或丢失。
# 新增英文预设文件时，若它有对应的中文档位，记得在这里登记（没登记也能用，只是不跨语言等价）。
LABEL_ALIASES = {
    "Character Three-View": "人物三视图",
    "Character Four-View": "人物四视图",
    "Character Five-View": "人物五视图",
    "Transparent Background": "背景纯透明",
    "Poster Layout": "图文版面",
    "Infographic": "信息图",
    "Comic Storyboard": "多格分镜",
    "Ad Storyboard": "广告分镜板",
    "Keep Subject New Scene": "保持主体换场景",
    "Local Edit": "局部编辑",
    "Photo Restoration": "老照片修复",
    "Full Image Stylize": "整图风格化",
    "360 Panorama": "360°全景",
    "Multi-Image Compose": "多图指认合成",
}
_ALIAS_LOWER = {k.strip().lower(): v for k, v in LABEL_ALIASES.items()}
_CANON_LOWER = {v.strip().lower(): v for v in LABEL_ALIASES.values()}


def canonical_label(label):
    """选项名 → 规范档位名（英文文件名 → 中文档位名；认不出就原样返回）"""
    s = str(label or "").strip()
    if not s:
        return s
    key = s.lower()
    return _ALIAS_LOWER.get(key) or _CANON_LOWER.get(key) or s


def _mtime_of_dir(folder):
    try:
        return os.stat(folder).st_mtime
    except OSError:
        return 0.0


def _scan_folder(folder):
    """列出目录下的 txt：[(排序号, 选项名, 完整路径), …]（已按排序号 + 名字排好）

    选项名统一归一到**规范档位名**：英文目录 `01-Character Three-View.txt` 的选项名就是
    「人物三视图」——文件名只是文件，取值/查表始终是同一套名字。
    """
    items = []
    try:
        names = os.listdir(folder)
    except OSError:
        return items
    for name in names:
        if not name.lower().endswith(".txt"):
            continue
        stem = name[:-4]
        m = _PREFIX_RE.match(stem)
        order = int(m.group(1)) if m else 10 ** 6
        label = (stem[m.end():] if m else stem).strip()
        if not label:
            continue
        items.append((order, canonical_label(label), os.path.join(folder, name)))
    items.sort(key=lambda x: (x[0], x[1]))
    return items


def _list_cached(folder):
    ts, items = _cache.get(folder, (0.0, None))
    now = time.time()
    if items is not None and now - ts < _CACHE_TTL:
        return items
    items = _scan_folder(folder)
    _cache[folder] = (now, items)
    return items


def invalidate():
    """手动清缓存（测试用）"""
    _cache.clear()


def node_dir(node_name=DEFAULT_NODE, lang=EN):
    return os.path.join(ROOT_DIR, str(node_name or DEFAULT_NODE), str(lang).upper())


# ── 系统语言 ────────────────────────────────────────────────────────────
def _locale_from_settings():
    """读 ComfyUI 前端设置里的 Comfy.Locale（user/<用户>/comfy.settings.json）"""
    try:
        import folder_paths
        user_dir = folder_paths.get_user_directory()
    except Exception:
        return ""
    candidates = [os.path.join(user_dir, "default", "comfy.settings.json")]
    try:
        for name in sorted(os.listdir(user_dir)):
            path = os.path.join(user_dir, name, "comfy.settings.json")
            if os.path.isfile(path) and path not in candidates:
                candidates.append(path)
    except OSError:
        pass
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        loc = data.get("Comfy.Locale") if isinstance(data, dict) else None
        if isinstance(loc, str) and loc.strip():
            return loc.strip().lower()
    return ""


def system_locale():
    """当前 ComfyUI 语言代码（小写）。优先级：环境变量 → 前端设置 → 系统区域"""
    env = os.environ.get("XB_PRESET_LANG", "").strip().lower()
    if env:
        return env
    loc = _locale_from_settings()
    if loc:
        return loc
    try:
        import locale as _locale
        loc = (_locale.getdefaultlocale()[0] or "")
    except Exception:
        loc = ""
    return str(loc).strip().lower()


def system_lang_folder():
    """中文 → ZH；其他所有语言 → EN"""
    return ZH if system_locale().startswith("zh") else EN


# ── 读取 ────────────────────────────────────────────────────────────────
def preset_entries(node_name=DEFAULT_NODE, lang=None):
    """某语言目录下的预设：[(选项名, 完整路径), …]"""
    lang = (lang or system_lang_folder()).upper()
    return [(label, path) for _order, label, path in _list_cached(node_dir(node_name, lang))]


# ── 备份目录（ComfyUI/output/生图提示词预设）：既是备份落点，也能被「添加预设」读取 ──
BACKUP_FOLDER_NAME = "生图提示词预设"


def backup_root():
    """备份根目录：<ComfyUI>/output/生图提示词预设（取不到 output 时退回本包内）"""
    try:
        import folder_paths
        return os.path.join(folder_paths.get_output_directory(), BACKUP_FOLDER_NAME)
    except Exception:
        return os.path.join(ROOT_DIR, "_backup_" + BACKUP_FOLDER_NAME)


def backup_dir(lang=None, node_name=None):
    """备份目录：基础节点沿用 output/生图提示词预设/<语言>；
    其它节点（增强预设 / 反推预设 …）放到 output/生图提示词预设/<节点名>/<语言>，互不串味。"""
    lang = str(lang or system_lang_folder()).upper()
    name = str(node_name or "").strip()
    if not name or name == DEFAULT_NODE:
        return os.path.join(backup_root(), lang)
    return os.path.join(backup_root(), name, lang)


def backup_entries(lang=None, node_name=None):
    """备份目录里某语言的预设：[(选项名, 完整路径), …]"""
    lang = (lang or system_lang_folder()).upper()
    return [(label, path) for _order, label, path in _list_cached(backup_dir(lang, node_name))]


def merged_entries(node_name=DEFAULT_NODE, lang=None):
    """预设目录 + 备份目录合并（同名以预设目录为准，备份里独有的也能被读到）

    「同名」按**规范档位名**判断：英文目录的 `Character Three-View.txt` 与备份里的
    `人物三视图.txt` 视为同一个档位，不会重复出现。
    """
    lang = (lang or system_lang_folder()).upper()
    out = list(preset_entries(node_name, lang))
    seen = {canonical_label(label) for label, _p in out}
    for label, path in backup_entries(lang, node_name):
        key = canonical_label(label)
        if key not in seen:
            out.append((label, path))
            seen.add(key)
    return out


def preset_labels(node_name=DEFAULT_NODE, lang=None):
    """选项名（顺序 = 预设目录编号，其次是备份目录）"""
    return [label for label, _path in merged_entries(node_name, lang)]


def preset_text(node_name, label, lang=None):
    """某选项在该语言下的设定词（预设目录优先，其次备份目录；都没有 → ""）

    ⚠️ 按**规范档位名**匹配：传给本函数的既可能是中文档位名（中文系统 / 老工作流），
       也可能是英文文件名（英文系统），两者都能命中同一份文案。
    """
    want = canonical_label(label)
    for name, path in merged_entries(node_name, lang):
        if canonical_label(name) == want:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    return f.read().strip()
            except Exception:
                return ""
    return ""


def backup_presets(node_name=DEFAULT_NODE):
    """一键备份：把预设目录里 ZH / EN 的 txt 全部复制到 output/生图提示词预设 下。"""
    total = 0
    for lang in LANG_FOLDERS:
        src_dir = node_dir(node_name, lang)
        items = _scan_folder(src_dir)
        if not items:
            continue
        dst_dir = backup_dir(lang, node_name)
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            return 0, f"备份目录创建失败：{e}"
        for _order, label, path in items:
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    text = f.read()
            except Exception:
                continue
            target = os.path.join(dst_dir, os.path.basename(path))
            try:
                with open(target, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                total += 1
            except OSError:
                continue
    if total:
        for lg in LANG_FOLDERS:
            _cache.pop(backup_dir(lg, node_name), None)
    return total, None


_ILLEGAL_CHARS = '\\/:*?"<>|'


def save_preset(node_name, label, text, lang=None):
    """写入 / 覆盖一个预设文件（同名覆盖，新名新建 → 自动排到末尾）。

    返回 (最终选项名, 错误信息)。label 里的非法文件名字符会被剔除。
    """
    lang = (lang or system_lang_folder()).upper()
    raw = str(label or "").strip()
    safe = "".join(c for c in raw if c not in _ILLEGAL_CHARS).strip()
    if not safe:
        return None, "预设名称不能为空（且不能只包含文件名非法字符）"
    folder = node_dir(node_name, lang)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        return None, f"目录创建失败：{e}"

    target = None
    want = canonical_label(safe)
    for name, path in preset_entries(node_name, lang):
        if name == safe or canonical_label(name) == want:
            target = path
            break
    if target is None:
        used = [order for order, _l, _p in _scan_folder(folder)]
        nxt = (max(used) + 1) if used else 1
        target = os.path.join(folder, f"{nxt:02d}-{safe}.txt")

    try:
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(str(text or "").strip() + "\n")
    except OSError as e:
        return None, f"写入失败：{e}"
    invalidate()
    return safe, None


def delete_preset(node_name, label, lang=None):
    """删除一个预设文件（用于编辑预设时清理）"""
    lang = (lang or system_lang_folder()).upper()
    safe = str(label or "").strip()
    for name, path in preset_entries(node_name, lang):
        if name == safe:
            try:
                os.remove(path)
            except OSError as e:
                return f"删除失败：{e}"
            invalidate()
            return None
    return "预设不存在"


def all_preset_texts(node_name=DEFAULT_NODE):
    """{"选项名": {"中文 [ZH]": 文本, "英文 [EN]": 文本}}（预设目录 + 备份目录都读）

    · 中英两个目录按**规范档位名**归并（英文目录的 `Character Three-View.txt` 与中文目录的
      `人物三视图.txt` 是同一个档位，各自补上自己那份语言文案）；
    · 某档位缺某种语言时用另一语言补上，避免「英文系统 + 中文输出语言」时取不到文案。
    """
    out = {}
    for lang in LANG_FOLDERS:
        for label, path in merged_entries(node_name, lang):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    text = f.read().strip()
            except Exception:
                continue
            out.setdefault(canonical_label(label), {})[LANG_LABELS[lang]] = text
    for by_lang in out.values():
        first = next(iter(by_lang.values()), "")
        for lg in LANG_LABELS.values():
            by_lang.setdefault(lg, first)
    return out


def snapshot(node_name=DEFAULT_NODE):
    """一次性交出前端需要的全部信息"""
    lang = system_lang_folder()
    primary = [label for label, _p in preset_entries(node_name, lang)]
    backup_only = [label for label, _p in backup_entries(lang, node_name) if label not in primary]
    return {
        "node": str(node_name or DEFAULT_NODE),
        "locale": system_locale(),
        "lang": lang,
        "dir": node_dir(node_name, lang),
        "root": ROOT_DIR,
        "exists": os.path.isdir(node_dir(node_name, lang)),
        "backup_dir": backup_dir(lang, node_name),
        "backup_exists": os.path.isdir(backup_dir(lang, node_name)),
        "backup_only": backup_only,
        "modes": preset_labels(node_name, lang),
        "texts": all_preset_texts(node_name),
        "lang_labels": dict(LANG_LABELS),
    }


# ── 前端查询端点 ────────────────────────────────────────────────────────
def _register_routes():
    try:
        import server
        from aiohttp import web
    except Exception:
        return

    routes = server.PromptServer.instance.routes

    @routes.get("/xb/presets")
    async def xb_presets(request):
        name = request.rel_url.query.get("node", DEFAULT_NODE)
        return web.json_response(snapshot(name))

    @routes.post("/xb/presets/save")
    async def xb_presets_save(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "JSON 解析失败"}, status=400)
        data = body if isinstance(body, dict) else {}
        name = str(data.get("node") or DEFAULT_NODE)
        lang = str(data.get("lang") or "").upper() or None
        if lang not in (ZH, EN):
            lang = None
        label, err = save_preset(name, data.get("label"), data.get("text"), lang)
        if err:
            return web.json_response({"ok": False, "error": err}, status=400)
        return web.json_response({"ok": True, **snapshot(name)})

    @routes.post("/xb/presets/delete")
    async def xb_presets_delete(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "JSON 解析失败"}, status=400)
        data = body if isinstance(body, dict) else {}
        name = str(data.get("node") or DEFAULT_NODE)
        lang = str(data.get("lang") or "").upper() or None
        if lang not in (ZH, EN):
            lang = None
        err = delete_preset(name, data.get("label"), lang)
        if err:
            return web.json_response({"ok": False, "error": err}, status=400)
        return web.json_response({"ok": True, **snapshot(name)})

    @routes.post("/xb/presets/backup")
    async def xb_presets_backup(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        data = body if isinstance(body, dict) else {}
        name = str(data.get("node") or DEFAULT_NODE)
        count, err = backup_presets(name)
        if err:
            return web.json_response({"ok": False, "error": err}, status=400)
        return web.json_response({"ok": True, "count": count,
                                  "backup_dir": backup_dir(None, name), **snapshot(name)})


try:
    _register_routes()
except Exception as e:      # 路由重复注册 / 非 ComfyUI 环境 → 只影响前端读取，不影响节点
    print(f"[XB-BOX] 预设文件端点未注册：{e}")
