"""
XB_ToolBox 启动清理脚本
========================
ComfyUI 启动时自动运行，清理旧版本残留文件。
每次迁移文件后，把旧路径加入 NEED_CLEAN 列表即可。
"""

import os
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))

# 旧文件路径（相对于插件根目录），用户安装新版时会被自动删除
NEED_CLEAN = [
    # 示例（将来迁移时取消注释）：
    # "nodes_minimax_h3_ref.py",
    # "js/xb_minimax_h3_ref.js",

    # 「机智罗的工作流」收拢进 jzl_workflows/ 之前的旧位置
    "xb_templates.py",
    "js/xb_workflow_gallery.js",
    "js/xb_workflow_gallery.css",
    "js/xb_icon_dark.png",
    "js/xb_icon_light.png",
]

# 需要整目录删除的旧路径
NEED_CLEAN_DIRS = [
    "xb_templates",
]

for rel_path in NEED_CLEAN:
    full = os.path.join(_HERE, rel_path)
    if os.path.isfile(full):
        os.remove(full)
        print(f"[XB_ToolBox] 清理旧文件: {rel_path}")

for rel_dir in NEED_CLEAN_DIRS:
    full_dir = os.path.join(_HERE, rel_dir)
    if os.path.isdir(full_dir):
        shutil.rmtree(full_dir, ignore_errors=True)
        print(f"[XB_ToolBox] 清理旧目录: {rel_dir}")

# 清理可能残留的旧 __pycache__
for root, dirs, files in os.walk(_HERE):
    for d in dirs:
        if d == "__pycache__":
            pycache = os.path.join(root, d)
            # 只清理没有对应 .py 的缓存
            parent = os.path.dirname(pycache)
            for cache_file in os.listdir(pycache):
                if cache_file.endswith(".pyc"):
                    name = cache_file.split(".cpython")[0] + ".py"
                    if not os.path.exists(os.path.join(parent, name)):
                        full_cache = os.path.join(pycache, cache_file)
                        os.remove(full_cache)
                        print(f"[XB_ToolBox] 清理孤立缓存: {cache_file}")
