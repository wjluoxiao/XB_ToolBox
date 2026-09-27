# -*- coding: utf-8 -*-
"""扫描源文件里「汉字 + 半角空格 + 汉字」的可疑空格（中文正文里几乎不会出现）"""
import io
import os
import re

ROOT = r"d:\AI_JZL\XB_ToolBox"
CJK = r"\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
pat = re.compile(r"([%s])[ \t](?=[%s])" % (CJK, CJK))

FILES = [
    "nodes_image_prompt_preset.py",
    "nodes_qwen_prompt_preset.py",
    "nodes_image_prompt_preset_pro.py",
    "js/xb_image_prompt_preset.js",
    "js/xb_qwen_prompt_preset.js",
    "js/xb_image_prompt_preset_pro.js",
    "_xbr_qwen_block.js",
    "_xbr_pro_block.js",
]

for rel in FILES:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        print("(缺)", rel)
        continue
    s = io.open(p, encoding="utf-8").read()
    hits = list(pat.finditer(s))
    print("== %s  可疑空格 %d 处" % (rel, len(hits)))
    for m in hits[:40]:
        a = max(0, m.start() - 14)
        b = min(len(s), m.end() + 14)
        print("   L%s: ...%s..." % (s[:m.start()].count("\n") + 1, s[a:b].replace("\n", "\\n")))
