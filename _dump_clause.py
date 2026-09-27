# -*- coding: utf-8 -*-
"""列出 t2i/i2i 条款常量的原文（repr），检查有没有多余空格"""
import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"d:\AI_JZL\XB_ToolBox"
s = io.open(ROOT + r"\nodes_image_prompt_preset.py", encoding="utf-8").read()
i = s.index("IO_I2I_COMMON = {")
j = s.index("def mode_io_clause(")
block = s[i:j]
ns = {}
exec("LANG_ZH = '中文'\nOUTPUT_LANGS = ['中文', 'English']\n" + block, ns)
for name in ("IO_I2I_COMMON", "T2I_FALLBACK_TAIL", "IO_T2I_FALLBACK"):
    print("=====", name)
    for k, v in ns[name].items():
        print("  %r -> %r" % (k, v))
        for ch_i, ch in enumerate(v):
            if ch == " " and 0 < ch_i < len(v) - 1:
                a, b = v[ch_i - 1], v[ch_i + 1]
                if "\u4e00" <= a <= "\u9fff" and "\u4e00" <= b <= "\u9fff":
                    print("     !! 汉字间空格 @%d: %r" % (ch_i, v[max(0, ch_i - 12):ch_i + 12]))
