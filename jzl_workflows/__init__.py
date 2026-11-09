"""「机智罗的工作流」— 侧栏入口 + 居中弹窗的模板库

全部实现集中在 ``jzl_workflows/`` 一个目录里：

    jzl_workflows/
      __init__.py   本文件：对外只暴露 register_routes()
      routes.py     后端路由（清单 / 工作流 / 预览图 / 图标与样式）
      data/         index*.json 清单 + 工作流 JSON + 预览图
      web/          面板样式与深浅两套图标

前端脚本只有 ``js/jzl_workflows/xb_workflow_gallery.js`` 留在 ``js/`` 下，
因为 ComfyUI 只加载 ``WEB_DIRECTORY`` 内的 js（该目录会递归扫描子文件夹）。
"""

from .routes import register_routes

__all__ = ["register_routes"]
