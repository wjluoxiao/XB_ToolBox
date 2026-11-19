"""XB_ToolBox — 「机智罗的工作流」模板数据服务
=========================================================
清单结构照抄官方 ``comfyui-workflow-templates`` 的 ``index.json`` / ``index.zh.json``：
``[{moduleName, category, title, icon, type, templates: [...]}]``。

前端「机智罗」侧栏面板只读这两个清单，按 ``category`` / ``title`` 分组渲染卡片，
点击卡片再取 ``<name>.json`` 加载工作流，预览图按官方 ``<name>-1.webp`` 约定托管。

安全：只放行清单里登记过的文件名，且解析后的路径必须仍在 ``xb_templates`` 目录内。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parent / "data"

# 面板静态资源（图标 / 样式）：由本模块单独托管，绕开 /extensions 的 24h 强缓存
WEB_DIR = Path(__file__).resolve().parent / "web"
WEB_ASSETS = (
    "xb_icon_dark.png",
    "xb_icon_light.png",
    "xb_workflow_gallery.css",
)

# 「提示词」页的文案来源：与「生图提示词预设」节点共用同一批 .txt
PROMPT_DIRS = {
    "zh": Path(__file__).resolve().parent.parent / "xb_skill" / "XB_ImagePromptPreset" / "ZH",
    "en": Path(__file__).resolve().parent.parent / "xb_skill" / "XB_ImagePromptPreset" / "EN",
}

# 清单文件名（英文 / 中文）
MANIFESTS = ("index.json", "index.zh.json")

_PROMPT_PREFIX = re.compile(r"^\d+\s*[-_.]\s*")

# 提示词分组（前端「全部类型」下拉用）：按标题关键词归类，中英文通用
PROMPT_GROUP_RULES = (
    ("image_edit", ("编辑", "修复", "风格化", "换场景", "全景", "合成",
                    "edit", "restoration", "stylize", "scene", "panorama", "compose")),
    ("text2image", ("视图", "三视", "四视", "五视", "版面", "信息图", "分镜", "透明",
                    "view", "layout", "infographic", "poster", "storyboard", "transparent")),
)
PROMPT_GROUP_FALLBACK = "text2image"

# 提示词效果图：与 .txt 同名、放同一目录（也允许放在 preview/ 子目录下）
PROMPT_IMAGE_EXTS = (".webp", ".png", ".jpg", ".jpeg", ".gif")
PROMPT_IMAGE_SUBDIR = "preview"

# 放行文件名只允许 ASCII 安全字符，天然排除 "/" 与 ".."
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _read_manifest(name: str) -> list:
    path = ROOT / name
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _allowed_files() -> set[str]:
    """清单登记过的文件名白名单（含两个 index 清单本身）。"""
    allowed = set(MANIFESTS)
    for manifest_name in MANIFESTS:
        for group in _read_manifest(manifest_name):
            if not isinstance(group, dict):
                continue
            templates = group.get("templates")
            if not isinstance(templates, list):
                continue
            for tpl in templates:
                if not isinstance(tpl, dict):
                    continue
                name = tpl.get("name")
                if isinstance(name, str) and _SAFE_NAME.match(name):
                    allowed.add(f"{name}.json")
                thumbnails = tpl.get("thumbnail")
                if isinstance(thumbnails, list):
                    for thumb in thumbnails:
                        if not isinstance(thumb, str):
                            continue
                        base = thumb.replace("\\", "/").rsplit("/", 1)[-1]
                        if _SAFE_NAME.match(base):
                            allowed.add(base)
    return allowed


def _prompt_image(folder: Path, stem: str) -> Path | None:
    """找提示词的效果图：同目录同名，其次 preview/ 子目录同名。"""
    for candidate_dir in (folder, folder / PROMPT_IMAGE_SUBDIR):
        if not candidate_dir.is_dir():
            continue
        for ext in PROMPT_IMAGE_EXTS:
            path = candidate_dir / f"{stem}{ext}"
            if path.is_file():
                return path
    return None


def _prompt_group(title: str) -> str:
    """按标题关键词归类，供前端「全部类型」下拉筛选。"""
    lowered = title.lower()
    for group, keywords in PROMPT_GROUP_RULES:
        if any(keyword in lowered for keyword in keywords):
            return group
    return PROMPT_GROUP_FALLBACK


def _load_prompts(locale: str) -> list[dict]:
    """读取提示词预设（.txt）为 [{name, title, text, image, group}]，标题去掉编号前缀。"""
    folder = PROMPT_DIRS.get(locale)
    if folder is None or not folder.is_dir():
        return []
    items = []
    for path in sorted(folder.glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text:
            continue
        image = _prompt_image(folder, path.stem)
        title = _PROMPT_PREFIX.sub("", path.stem).strip() or path.stem
        items.append({
            "name": path.stem,
            "title": title,
            "text": text,
            "image": image.name if image else "",
            "group": _prompt_group(title),
        })
    return items


def _prompt_image_files(locale: str) -> dict[str, Path]:
    """该语言下所有可用的效果图 {文件名: 路径}，用于路由白名单。"""
    folder = PROMPT_DIRS.get(locale)
    files: dict[str, Path] = {}
    if folder is None or not folder.is_dir():
        return files
    for stem_path in sorted(folder.glob("*.txt")):
        image = _prompt_image(folder, stem_path.stem)
        if image is not None:
            files[image.name] = image
    return files


def register_routes():
    from server import PromptServer

    routes = PromptServer.instance.routes

    @routes.get("/xb_toolbox/templates/{filename}")
    async def get_template_asset(request):
        filename = request.match_info.get("filename", "")
        if not _SAFE_NAME.match(filename) or filename not in _allowed_files():
            raise web.HTTPNotFound()

        target = (ROOT / filename).resolve()
        if target.parent != ROOT or not target.is_file():
            raise web.HTTPNotFound()

        is_manifest = filename in MANIFESTS
        headers = {
            # 清单必须实时反映磁盘改动，图片只做协商缓存
            "Cache-Control": "no-store" if is_manifest else "no-cache",
            "X-Content-Type-Options": "nosniff",
        }
        return web.FileResponse(target, headers=headers)

    @routes.get("/xb_toolbox/assets/{name}")
    async def get_web_asset(request):
        """面板静态资源（图标 / 样式）单独托管。

        /extensions/* 由 ComfyUI 静态托管并带 ``max-age=86400``，换图换样式后浏览器会一直用旧的；
        这里用 no-cache，让浏览器每次协商，改完普通刷新即可生效。
        """
        name = request.match_info.get("name", "")
        if name not in WEB_ASSETS:
            raise web.HTTPNotFound()
        target = WEB_DIR / name
        if not target.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(
            target,
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    @routes.get("/xb_toolbox/prompts/{locale}")
    async def get_prompts(request):
        """「提示词」页数据：直接读 xb_skill/XB_ImagePromptPreset 下的 .txt。"""
        locale = request.match_info.get("locale", "")
        if locale not in PROMPT_DIRS:
            raise web.HTTPNotFound()
        return web.json_response(
            _load_prompts(locale),
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    @routes.get("/xb_toolbox/prompts/{locale}/{filename}")
    async def get_prompt_image(request):
        """提示词效果图：只放行与某个 .txt 同名（含 preview/ 下）的图片。"""
        locale = request.match_info.get("locale", "")
        filename = request.match_info.get("filename", "")
        if locale not in PROMPT_DIRS:
            raise web.HTTPNotFound()
        target = _prompt_image_files(locale).get(filename)
        if target is None:
            raise web.HTTPNotFound()
        return web.FileResponse(
            target,
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )
