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

# 清单文件名（英文 / 中文）
MANIFESTS = ("index.json", "index.zh.json")

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
