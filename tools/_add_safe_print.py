# -*- coding: utf-8 -*-
"""把 Pro / Qwen 节点里带 emoji 的日志改成 safe_print（非 UTF-8 控制台也不会崩）+ 补齐 import"""
import io
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))

TARGETS = {
    "nodes_image_prompt_preset_pro.py": [
        ("print(f\"[XB-生图预设Pro] 🧠 ", "safe_print(f\"[XB-生图预设Pro] 🧠 "),
        ("print(\"[XB-生图预设Pro] ⚠️ 输出含对比式修改说明", "safe_print(\"[XB-生图预设Pro] ⚠️ 输出含对比式修改说明"),
        ("print(\"[XB-生图预设Pro] ✅ 重试后已得到直接的最终画面描述\")",
         "safe_print(\"[XB-生图预设Pro] ✅ 重试后已得到直接的最终画面描述\")"),
        ("print(\"[XB-生图预设Pro] ⚠️ 重试仍不合格", "safe_print(\"[XB-生图预设Pro] ⚠️ 重试仍不合格"),
    ],
    "nodes_qwen_prompt_preset.py": [
        ("print(f\"[XB-Qwen提示词预设] ⚠️", "safe_print(f\"[XB-Qwen提示词预设] ⚠️"),
    ],
}

for fname, pairs in TARGETS.items():
    path = os.path.join(ROOT, fname)
    with io.open(path, encoding="utf-8") as f:
        s = f.read()
    n = 0
    for a, b in pairs:
        if a in s:
            s = s.replace(a, b)
            n += 1
    # 确认 safe_print 已从基础模块导入
    if "safe_print" in s and "safe_print," not in s and "safe_print\n" not in s:
        m = re.search(r"from \.nodes_image_prompt_preset import \(([^)]*)\)", s)
        if m:
            body = m.group(1)
            if "safe_print" not in body:
                s = s[:m.end(1)] + "\n    safe_print," + body + s[m.end(1):]
                n += 1
        else:
            m2 = re.search(r"from \.nodes_image_prompt_preset import ([^\n]*)\n", s)
            if m2 and "safe_print" not in m2.group(1):
                s = s[:m2.end(1)] + ", safe_print" + s[m2.end(1):]
                n += 1
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    print(fname, "changed", n, "| safe_print imported:", bool(re.search(r"safe_print", s.split("class ")[0])))

# 断言：不再有裸 print 带 GBK 不可编码字符
for fname in TARGETS:
    with io.open(os.path.join(ROOT, fname), encoding="utf-8") as f:
        s = f.read()
    bad = []
    for i, line in enumerate(s.split("\n"), 1):
        if re.search(r"(?<!safe_)\bprint\(", line):
            for ch in line:
                try:
                    ch.encode("gbk")
                except Exception:
                    bad.append((i, ch))
                    break
    print("残留 emoji 裸 print:", fname, bad)
