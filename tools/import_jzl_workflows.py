# -*- coding: utf-8 -*-
"""把「机智罗的工作流」源目录同步进 jzl_workflows/data/。

用法::

    python tools/import_jzl_workflows.py "Y:\\ComfyUI_LX\\workflows\\0"

源目录结构::

    <root>/<分类目录>/<编号>-<标题>.json
    <root>/界面图.png            # 统一预览图（可选，缺省则保留旧图）

输出::

    jzl_workflows/data/<slug>.json         工作流本体（slug 为 ASCII，如 qwen2511_01）
    jzl_workflows/data/<slug>-1.webp       预览图
    jzl_workflows/data/index.json          英文清单
    jzl_workflows/data/index.zh.json       中文清单

脚本会先清空 data/ 里的旧 json/webp，再全量重建，所以是「覆盖式」同步。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import date

from PIL import Image

SLUGS = {
    "Anima": "anima",
    "Boogu-image": "boogu",
    "Flux-2": "flux2",
    "Flux-3": "flux3",
    "Krea-2": "krea2",
    "MiniMax-H3": "minimaxh3",
    "MiniMax-Music": "minimaxmusic",
    "MiniMax-image": "minimaximage",
    "Moss-image": "mossimage",
    "Qwen-image-2.1": "qwen21",
    "Qwen-image-2511": "qwen2511",
    "Qwen-image-2512": "qwen2512",
    "RelayVSR": "relayvsr",
    "SeeThrough": "seethrough",
    "YuE2": "yue2",
    "Z-image": "zimage",
}

# 分类 → 面板「类型」：未登记的一律按图片处理
CATEGORY_TYPES = {
    "MiniMax-H3": "video",
    "RelayVSR": "video",
    "MiniMax-Music": "music",
    "YuE2": "music",
}

# 英文标题用的术语表；长词在前，避免「文生图」先吃掉「文生图基础工作流」
TERMS = [
    ("歌曲创作（单人）", "Song Creation (Solo)"),
    ("歌曲创作（双人）", "Song Creation (Duet)"),
    ("歌曲创作", "Song Creation"),
    ("歌曲翻唱", "Song Cover"),
    ("文生图基础工作流", "Text to Image Basics"),
    ("局部重绘基础工作流", "Inpainting Basics"),
    ("无限时长视频放大", "Infinite-Length Video Upscale"),
    ("多模态控制生图", "Multimodal Controlled Generation"),
    ("18风格切换文生图", "18-Style Switch Text to Image"),
    ("十种风格 Lora 切换", "10-Style LoRA Switch"),
    ("风格复刻文生图", "Style Replication Text to Image"),
    ("姿态控制工作流", "Pose Control"),
    ("多参考生视频", "Multi-Reference Video"),
    ("文图生视频", "Text/Image to Video"),
    ("全景文生图", "Panorama Text to Image"),
    ("控制文生图", "Controlled Text to Image"),
    ("96视角生成", "96-View Generation"),
    ("单视角切换", "Single-View Switch"),
    ("多Lora切换", "Multi-LoRA Switch"),
    ("SelfLift 二次采样", "SelfLift Second Pass"),
    ("常规二次采样", "Standard Second Pass"),
    ("视频放大", "Video Upscale"),
    ("图层拆解", "Layer Decomposition"),
    ("多图编辑 进阶", "Multi-Image Edit Advanced"),
    ("多图编辑", "Multi-Image Edit"),
    ("双图编辑", "Two-Image Edit"),
    ("三图编辑", "Three-Image Edit"),
    ("单图编辑", "Single Image Edit"),
    ("图片编辑", "Image Edit"),
    ("图像多角度编辑", "Multi-Angle Image Edit"),
    ("96视角切换", "96-View Switch"),
    ("文生视频", "Text to Video"),
    ("图生图", "Image to Image"),
    ("文生图工作流", "Text to Image Workflow"),
    ("文生图 进阶", "Text to Image Advanced"),
    ("文生图 4步加速", "Text to Image 4-Step Accelerated"),
    ("文生图", "Text to Image"),
    ("控制生图", "Controlled Generation"),
    ("局部重绘", "Inpainting"),
    ("图片扩展", "Outpainting"),
    ("手绘生图", "Sketch to Image"),
    ("换脸", "Face Swap"),
    ("工作流", " Workflow"),
    ("（带放大）", " with Upscale"),
    ("测试-", "Test - "),
    ("Qwe-Image", "Qwen-Image"),
]

NUMBER_PREFIX = re.compile(r"^\d+\s*-\s*")
CJK = re.compile(r"[\u3400-\u9fff]")


def english_title(stem: str) -> str:
    text = NUMBER_PREFIX.sub("", stem)
    for zh, en in TERMS:
        text = text.replace(zh, en)
    text = text.replace("（", " (").replace("）", ")")
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text


def display_title(stem: str) -> str:
    """中文展示标题：保留编号，顺手修正源文件名里的 “Qwe-Image” 笔误。"""
    return stem.replace("Qwe-Image", "Qwen-Image")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/import_jzl_workflows.py <source_dir> [--dry-run]")
        return 2
    source = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "jzl_workflows", "data")
    if not os.path.isdir(data_dir):
        print(f"data dir not found: {data_dir}")
        return 2

    categories = [name for name in sorted(os.listdir(source))
                  if os.path.isdir(os.path.join(source, name)) and name in SLUGS]
    if not categories:
        print(f"no known category folders under {source}")
        return 2

    thumb_source = None
    for name in sorted(os.listdir(source)):
        if name.lower().endswith(".png"):
            thumb_source = os.path.join(source, name)
            break

    today = date.today().isoformat()
    groups = []           # [(category, [entry, ...])]
    copied, skipped = [], []
    unresolved = []

    for category in categories:
        slug_base = SLUGS[category]
        files = sorted(f for f in os.listdir(os.path.join(source, category))
                       if f.lower().endswith(".json"))
        entries = []
        seen_en = {}
        for index, filename in enumerate(files, start=1):
            stem = os.path.splitext(filename)[0]
            slug = f"{slug_base}_{index:02d}"
            en = english_title(stem)
            if CJK.search(en):
                unresolved.append((filename, en))
            # 去掉编号后英文标题可能重名，补 #2 便于区分
            seen_en[en] = seen_en.get(en, 0) + 1
            if seen_en[en] > 1:
                en = f"{en} #{seen_en[en]}"
            entries.append({
                "slug": slug,
                "source": os.path.join(source, category, filename),
                "zh": display_title(stem),
                "en": en,
                "category": category,
            })
            copied.append(f"{category}/{filename} -> {slug}.json")
        groups.append((category, entries))

    if dry_run:
        for category, entries in groups:
            print(f"[{category}] {len(entries)}")
            for entry in entries:
                print(f"  {entry['slug']:<16} zh={entry['zh']}")
                print(f"  {'':<16} en={entry['en']}")
        if unresolved:
            print("\n!! 仍有中文残留（需补术语表）:")
            for filename, en in unresolved:
                print(f"  {filename} -> {en}")
        return 0

    for name in os.listdir(data_dir):
        if name.lower().endswith((".json", ".webp")) and not name.startswith("index"):
            os.remove(os.path.join(data_dir, name))
            skipped.append(name)

    thumb_bytes = None
    if thumb_source:
        image = Image.open(thumb_source).convert("RGBA")
        tmp = os.path.join(data_dir, "__thumb.webp")
        image.save(tmp, "WEBP", quality=88, method=6)
        with open(tmp, "rb") as handle:
            thumb_bytes = handle.read()
        os.remove(tmp)

    def build(locale: str, username: str):
        payload = []
        for category, entries in groups:
            templates = []
            for entry in entries:
                templates.append({
                    "name": entry["slug"],
                    "date": today,
                    "openSource": True,
                    "minComfyUIVersion": "0.0.0",
                    "thumbnail": [f"{entry['slug']}-1.webp"],
                    "tags": [category],
                    "title": entry["zh"] if locale == "zh" else entry["en"],
                    "description": entry["zh"] if locale == "zh" else entry["en"],
                    "username": username,
                })
            payload.append({
                "moduleName": "jzl",
                "category": "机智罗的工作流" if locale == "zh" else "JZL Workflows",
                "title": category,
                "icon": "icon-[lucide--image]",
                "type": CATEGORY_TYPES.get(category, "image"),
                "templates": templates,
            })
        return payload

    for category, entries in groups:
        for entry in entries:
            shutil.copyfile(entry["source"], os.path.join(data_dir, f"{entry['slug']}.json"))
            if thumb_bytes:
                with open(os.path.join(data_dir, f"{entry['slug']}-1.webp"), "wb") as handle:
                    handle.write(thumb_bytes)

    for locale, filename in (("en", "index.json"), ("zh", "index.zh.json")):
        payload = build(locale, "JZL" if locale == "en" else "机智罗")
        with open(os.path.join(data_dir, filename), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    total = sum(len(entries) for _, entries in groups)
    print(f"categories: {len(groups)}  workflows: {total}")
    print(f"thumbnails regenerated: {'yes' if thumb_bytes else 'no (kept none)'}")
    if unresolved:
        print("WARNING: 以下英文标题仍有中文，请补术语表:")
        for filename, en in unresolved:
            print(f"  {filename} -> {en}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
