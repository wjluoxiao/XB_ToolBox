# -*- coding: utf-8 -*-
"""给 locales/{zh,en}/nodeDefs.json 的两个节点补 io_mode 词条（行插入，不重排整文件）"""
import io
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PLAN = {
    "zh": ('"io_mode": { "name": "模版" },', "SKILL 模式"),
    "en": ('"io_mode": { "name": "Mode" },', "SKILL Mode"),
}

for lang, (add, anchor) in PLAN.items():
    path = os.path.join(ROOT, "locales", lang, "nodeDefs.json")
    with io.open(path, encoding="utf-8") as f:
        raw = f.read()
    json.loads(raw)
    if '"io_mode"' in raw:
        print(lang, "已存在，跳过")
        continue
    out, hit = [], 0
    for line in raw.split("\n"):
        out.append(line)
        if '"skill_mode"' in line and anchor in line:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(indent + add)
            hit += 1
    new = "\n".join(out)
    obj = json.loads(new)
    if hit != 2:
        raise SystemExit("%s: 插入点数量异常 %d" % (lang, hit))
    for node in ("XB_ImagePromptPresetPro", "XB_QwenPromptPreset"):
        assert obj[node]["inputs"]["io_mode"]["name"], (lang, node)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    print(lang, "插入", hit, "处，JSON 合法")
