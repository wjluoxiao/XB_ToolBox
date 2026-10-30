"""XB-BOX 参考图库内核（姿态 / 穿搭）—— 绑定目录、素材清单读取、图片端点、节点取图
==============================================================================
· 「姿态图库」「穿搭图库」两套库**分开绑定**：各一个目录，各自带「使用确认」标记；
· 支持两种目录形态（同一套代码自动识别，用户绑什么就用什么）：
    ① 带素材清单的图库：目录下有 ``data/*.json``（数组，每项含 ``id`` 与
       ``原图`` / ``大图`` 字段）→ 读取清单得到 体系 / 分类 / 角度 / 标签 等筛选维度，
       前端做筛选 + 分组 + 视角条界面；
    ② 普通图片文件夹：没有清单 → 递归扫描图片，前端按文件名多宫格展示；
· 绑定信息只落机器本地 ``<user_dir>/xb_toolbox/gallery.json``，不进 Git、不进工作流；
  工作流里只存「库内相对路径 + 展示名」，不外发、不携带本机磁盘路径。

节点侧只需要 ``load_reference(kind, ref)``：返回 [1,H,W,3] float32 0~1 的 IMAGE 张量。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

KINDS = {"pose": "姿态图库", "costume": "穿搭图库"}

# 「禁用」参考图时用它把该输出整条链路阻断（等同于 mute：下游节点直接不执行，也不报错）
try:
    from comfy_execution.graph_utils import ExecutionBlocker
except Exception:      # 极老版本没有该机制 → 退化为白色占位图（保证不崩）
    ExecutionBlocker = None
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
# 显式声明 Content-Type：配合 nosniff 时，返回 octet-stream 会让浏览器拒绝渲染图片
MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}
ANGLE_ORDER = ("正面", "斜侧", "侧面", "俯视", "仰视")
THUMB_MAX = 384
FOLDER_TTL = 5.0            # 普通文件夹扫描缓存（秒）
PACKAGE_ROOT = Path(__file__).resolve().parent

_cache_lock = threading.Lock()
_manifest_cache: dict = {}     # {(root, mtime, size): catalogue}
_folder_cache: dict = {}       # {root: (ts, catalogue)}


class GalleryError(ValueError):
    """可直接展示给用户的中文错误。"""


# ── 绑定设置（机器本地，不进工作流） ────────────────────────────────────
def settings_path() -> Path:
    try:
        import folder_paths
        base = Path(folder_paths.get_user_directory())
    except Exception:
        base = PACKAGE_ROOT / ".xb_user"
    return base / "xb_toolbox" / "gallery.json"


def read_settings() -> dict:
    path = settings_path()
    raw = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
    out = {}
    for kind in KINDS:
        entry = raw.get(kind) if isinstance(raw, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        out[kind] = {
            "directory": str(entry.get("directory") or ""),
            "accepted": bool(entry.get("accepted")),
        }
    return out


def save_settings(kind: str, directory: str, accepted: bool) -> dict:
    """绑定 / 更换图库目录（绑定前先完整校验一遍，坏目录不落盘）。"""
    if kind not in KINDS:
        raise GalleryError("未知图库类型。")
    directory = str(directory or "").strip()
    if directory:
        root = Path(directory).expanduser()
        if not root.is_absolute():
            raise GalleryError("请填写 ComfyUI 所在电脑上的绝对路径（例如 D:\\XB图库\\pose）。")
        root = root.resolve()
        if not root.is_dir():
            raise GalleryError(f"目录不存在或不可访问：{root}")
        if not accepted:
            raise GalleryError("绑定图库前请先勾选「我已确认合法获得该图库的使用权」。")
        build_catalogue(root)          # 校验清单 / 图片是否可用
        directory = str(root)
    data = read_settings()
    data[kind] = {"directory": directory, "accepted": bool(accepted) and bool(directory)}
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return data


def bound_root(kind: str) -> Path:
    cfg = read_settings().get(kind) or {}
    label = KINDS.get(kind, "图库")
    if not cfg.get("accepted"):
        raise GalleryError(f"尚未绑定{label}：请先在图库窗口里选择目录并勾选使用确认。")
    directory = cfg.get("directory") or ""
    if not directory:
        raise GalleryError(f"尚未绑定{label}目录。")
    root = Path(directory)
    if not root.is_dir():
        raise GalleryError(f"{label}目录不存在或已移动：{directory}")
    return root.resolve()


# ── 路径安全（只允许库内相对路径 + 图片后缀） ─────────────────────────
def safe_rel(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GalleryError("素材路径不能为空。")
    text = value.replace("\\", "/").lstrip("/")
    if re.match(r"^[a-zA-Z]:", text) or ".." in text.split("/"):
        raise GalleryError(f"素材须使用库内的相对路径：{value}")
    if Path(text).suffix.lower() not in IMAGE_EXT:
        raise GalleryError(f"不是支持的图片格式：{value}")
    return text


def resolve_image(root: Path, rel: str) -> Path:
    path = (root / safe_rel(rel)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise GalleryError(f"素材路径越界：{rel}") from exc
    if not path.is_file():
        raise GalleryError(f"图片文件缺失：{rel}（请检查图库是否完整）")
    return path


# ── 清单适配器（pose / costume 字段不同，统一归一成同一套 item） ────────
def _natural_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def _find_manifest(root: Path):
    data = root / "data"
    if not data.is_dir():
        return None
    preferred = [data / "pose-zh.json", data / "costume-zh.json"]
    candidates = [p for p in preferred if p.is_file()]
    candidates += [p for p in sorted(data.glob("*.json")) if p not in candidates]
    for path in candidates:
        try:
            rows = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and rows[0].get("id"):
            return path, rows
    return None


def _library_item(row: dict) -> dict | None:
    item_id = str(row.get("id") or "").strip()
    if not item_id:
        return None
    original = str(row.get("原图") or row.get("大图") or "").strip()
    if not original:
        return None
    thumb = str(row.get("缩略图") or "").strip()
    tags = row.get("标签") if isinstance(row.get("标签"), list) else []
    keywords = " ".join(
        str(x) for x in (row.get("关键词"), row.get("关键词中文"), " ".join(map(str, tags))) if x
    )
    search = str(row.get("检索") or "").strip().lower() or " ".join([
        item_id,
        str(row.get("姿势名称") or ""),
        str(row.get("分类") or ""),
        str(row.get("体系") or ""),
        str(row.get("角度") or ""),
        keywords,
    ]).lower()
    return {
        "id": item_id,
        "name": str(row.get("姿势名称") or row.get("名称") or row.get("关键词中文") or item_id),
        "category": str(row.get("分类") or ""),
        "system": str(row.get("体系") or ""),
        "angle": str(row.get("角度") or ""),
        "group": str(row.get("姿势编号") or ""),
        "tags": [str(t) for t in tags],
        "path": safe_rel(original),
        "thumb": safe_rel(thumb) if thumb else "",
        "search": search,
    }


def _folder_item(root: Path, path: Path) -> dict:
    rel = path.relative_to(root).as_posix()
    return {
        "id": rel,
        "name": path.stem,
        "category": "" if path.parent == root else path.parent.name,
        "system": "",
        "angle": "",
        "group": "",
        "tags": [],
        "path": rel,
        "thumb": "",
        "search": rel.lower(),
    }


def build_catalogue(root: Path) -> dict:
    """扫描目录 → 统一结构 {mode, manifest, count, items, facets}。"""
    found = _find_manifest(root)
    if found:
        manifest, rows = found
        items = [it for it in (_library_item(row) for row in rows if isinstance(row, dict)) if it]
        if not items:
            raise GalleryError(f"清单 {manifest.name} 里没有可用条目（需含 id 与 原图/大图 字段）。")
        angles = [a for a in ANGLE_ORDER if any(i["angle"] == a for i in items)]
        angles += sorted({i["angle"] for i in items} - set(angles) - {""})
        tag_rank: dict = {}
        for item in items:
            for tag in item["tags"]:
                tag_rank[tag] = tag_rank.get(tag, 0) + 1
        return {
            "mode": "library",
            "manifest": manifest.relative_to(root).as_posix(),
            "count": len(items),
            "items": items,
            "facets": {
                "system": sorted({i["system"] for i in items if i["system"]}),
                "category": sorted({i["category"] for i in items if i["category"]}),
                "angle": angles,
                "tag": [t for t, _n in sorted(tag_rank.items(), key=lambda kv: -kv[1])[:48]],
            },
        }

    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXT:
            continue
        rel = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        files.append(path)
    if not files:
        raise GalleryError(f"目录里没有图片：{root}（支持 png/jpg/webp/bmp/gif）")
    files.sort(key=lambda p: _natural_key(p.relative_to(root).as_posix()))
    items = [_folder_item(root, p) for p in files]
    return {
        "mode": "folder",
        "manifest": "",
        "count": len(items),
        "items": items,
        "facets": {
            "system": [],
            "category": sorted({i["category"] for i in items if i["category"]}),
            "angle": [],
            "tag": [],
        },
    }


def catalogue_for(kind: str) -> dict:
    """读当前绑定的图库（整套库按清单 mtime 缓存；普通文件夹按 5 秒 TTL 缓存）。"""
    root = bound_root(kind)
    found = _find_manifest(root)
    if found:
        manifest, _rows = found
        stat = manifest.stat()
        key = (str(root), stat.st_mtime_ns, stat.st_size)
        with _cache_lock:
            cached = _manifest_cache.get(key)
        if cached is None:
            cached = build_catalogue(root)
            with _cache_lock:
                _manifest_cache.clear()
                _manifest_cache[key] = cached
        return cached
    with _cache_lock:
        ts, cached = _folder_cache.get(str(root), (0.0, None))
    if cached is not None and time.time() - ts < FOLDER_TTL:
        return cached
    cached = build_catalogue(root)
    with _cache_lock:
        _folder_cache[str(root)] = (time.time(), cached)
    return cached


def invalidate() -> None:
    """手动清缓存（换绑目录 / 测试用）。"""
    with _cache_lock:
        _manifest_cache.clear()
        _folder_cache.clear()


# ── 缩略图（普通文件夹没有 thumbs/ → 现生成并缓存到用户目录） ──────────
def _thumb_cache_path(path: Path) -> Path:
    stat = path.stat()
    key = hashlib.sha1(f"{path}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()
    return settings_path().parent / "thumbs" / f"{key}.jpg"


def thumbnail_of(root: Path, rel: str, thumb_rel: str = "") -> Path:
    """优先用清单里的缩略图；没有就现场切 384px JPEG 并缓存（只读素材目录）。"""
    if thumb_rel:
        try:
            return resolve_image(root, thumb_rel)
        except GalleryError:
            pass
    path = resolve_image(root, rel)
    cached = _thumb_cache_path(path)
    if cached.is_file():
        return cached
    try:
        from PIL import Image, ImageOps

        cached.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((THUMB_MAX, THUMB_MAX), Image.Resampling.LANCZOS)
            image.save(cached, "JPEG", quality=86, optimize=True)
        return cached
    except Exception:
        # 缩略图失败不影响预览：直接回原图
        return path


# ── 节点取图（IMAGE 张量规格：[1,H,W,3] float32，值域 0~1） ────────────
def _ref_meta(ref) -> dict:
    """内部字段解析：{"path","name","disabled"} JSON 或纯相对路径字符串。"""
    text = str(ref or "").strip()
    if not text:
        return {"path": "", "name": "", "disabled": False}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            return {"path": "", "name": "", "disabled": False}
        if not isinstance(data, dict):
            return {"path": "", "name": "", "disabled": False}
        return {
            "path": str(data.get("path") or "").strip(),
            "name": str(data.get("name") or "").strip(),
            "disabled": bool(data.get("disabled")),
        }
    return {"path": text, "name": "", "disabled": False}


def _ref_path_of(ref) -> str:
    return _ref_meta(ref)["path"]


def load_reference(kind: str, ref, placeholder: int = 64):
    """读取一张参考图 → IMAGE 张量。

    · 已勾选「禁用」：返回 ``ExecutionBlocker(None)`` —— 等同于 mute：
      本输出**不产出任何数据**，凡是接在这条输出上的下游节点会被 ComfyUI 直接跳过（不执行、不报错）；
    · 未选择：输出 placeholder×placeholder 白色占位图（下游不断流）；
    · 选了图但文件丢了：抛错并给出中文提示。
    """
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    label = KINDS.get(kind, kind)
    meta = _ref_meta(ref)
    if meta["disabled"]:
        if ExecutionBlocker is not None:
            print(f"[XB-生图预设] {label} 已禁用 → 该输出不做任何输出（下游节点将被跳过）")
            return ExecutionBlocker(None)
        print(f"[XB-生图预设] {label} 已禁用（当前 ComfyUI 不支持阻断执行）→ 输出占位图")
        arr = np.full((placeholder, placeholder, 3), 1.0, dtype=np.float32)
        return torch.from_numpy(arr).unsqueeze(0)
    rel = meta["path"]
    if not rel:
        arr = np.full((placeholder, placeholder, 3), 1.0, dtype=np.float32)
        print(f"[XB-生图预设] {label} 未选择 → 输出 {placeholder}x{placeholder} 白色占位图")
        return torch.from_numpy(arr).unsqueeze(0)
    try:
        root = bound_root(kind)
        path = resolve_image(root, rel)
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            arr = np.asarray(image, dtype=np.float32) / 255.0
    except (GalleryError, OSError, ValueError) as exc:
        raise RuntimeError(f"[XB-生图预设] {label}读取失败：{exc}") from exc
    print(f"[XB-生图预设] {label}：{path.name} → {arr.shape[1]}x{arr.shape[0]}")
    return torch.from_numpy(arr).unsqueeze(0)


def fingerprint(kind: str, ref) -> str:
    """IS_CHANGED 用：文件被替换/改动、或「禁用」开关变化 → 让节点重跑。"""
    meta = _ref_meta(ref)
    if meta["disabled"]:
        return "disabled"
    rel = meta["path"]
    if not rel:
        return ""
    try:
        stat = resolve_image(bound_root(kind), rel).stat()
        return f"{rel}:{stat.st_mtime_ns}:{stat.st_size}"
    except (GalleryError, OSError):
        return f"{rel}:missing"


# ── HTTP 端点 ─────────────────────────────────────────────────────────
def _register_routes():
    try:
        import server
        from aiohttp import web
    except Exception:
        return

    routes = server.PromptServer.instance.routes

    def same_origin(request) -> bool:
        origin = request.headers.get("Origin")
        return not origin or urlsplit(origin).netloc == request.host

    @routes.get("/xb_toolbox/gallery/settings")
    async def gallery_get_settings(request):
        return web.json_response({"settings": read_settings()}, headers={"Cache-Control": "no-store"})

    @routes.post("/xb_toolbox/gallery/settings")
    async def gallery_set_settings(request):
        # 目录变更必须来自本 UI，不能由其它网站触发（防跨站改本地路径）
        if not same_origin(request):
            return web.json_response({"error": "图库绑定仅接受同站请求。"}, status=403)
        if request.content_type != "application/json":
            return web.json_response({"error": "请使用 JSON 提交图库设置。"}, status=415)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "JSON 解析失败。"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "请求须为对象。"}, status=400)
        try:
            data = save_settings(str(body.get("kind") or ""), body.get("directory") or "",
                                 bool(body.get("accepted")))
            invalidate()
            return web.json_response({"settings": data})
        except GalleryError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except OSError:
            return web.json_response({"error": "无法保存设置，请检查 ComfyUI 用户目录的写入权限。"}, status=500)

    @routes.get("/xb_toolbox/gallery/catalogue")
    async def gallery_catalogue(request):
        import asyncio
        kind = request.rel_url.query.get("kind", "pose")
        try:
            cat = await asyncio.to_thread(catalogue_for, kind)
            return web.json_response({"kind": kind, **cat}, headers={"Cache-Control": "no-cache"})
        except GalleryError as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @routes.get("/xb_toolbox/gallery/image")
    async def gallery_image(request):
        import asyncio
        kind = request.rel_url.query.get("kind", "pose")
        rel = request.rel_url.query.get("path", "")
        thumb_rel = request.rel_url.query.get("thumb_path", "")
        thumb = request.rel_url.query.get("thumb") == "1"
        try:
            def resolve():
                root = bound_root(kind)
                return thumbnail_of(root, rel, thumb_rel) if thumb else resolve_image(root, rel)
            path = await asyncio.to_thread(resolve)
            mime = MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
            return web.FileResponse(path, headers={"Cache-Control": "no-cache",
                                                   "Content-Type": mime,
                                                   "X-Content-Type-Options": "nosniff"})
        except GalleryError as exc:
            return web.json_response({"error": str(exc)}, status=404)

    print("[XB-BOX] 参考图库端点已注册：/xb_toolbox/gallery/{settings,catalogue,image}")


try:
    _register_routes()
except Exception as _exc:      # 路由重复注册 / 非 ComfyUI 环境 → 只影响前端读取
    print(f"[XB-BOX] 参考图库端点未注册：{_exc}")
