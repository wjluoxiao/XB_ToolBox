"""
XB-ToolBox 模型加载器 —— 遗留公共函数
============================================
原 V1/V2/V3「模型加载大全」节点已删除；此处只保留 __init__.py 的模型刷新
接口仍在调用的 _filter_by_keyword（按关键词扫描模型目录）。
"""

import os

import folder_paths


def _filter_by_keyword(folder_type, keyword: str):
    """扫描模型目录，仅返回子文件夹名包含 keyword 的文件。"""
    if not keyword or not keyword.strip():
        return ["(请先输入模型类型)"]
    kw = keyword.strip().lower()
    base_dirs = folder_paths.get_folder_paths(folder_type)
    result = []
    valid_exts = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            rel = os.path.relpath(root, base_dir)
            if rel == ".":
                continue
            parts = rel.replace("\\", "/").split("/")
            if not any(kw in p.lower() for p in parts):
                continue
            for f in files:
                if os.path.splitext(f)[1].lower() in valid_exts:
                    result.append(os.path.join(rel, f).replace("\\", "/"))
    result.sort()
    return result if result else ["(无匹配模型)"]
