# -*- coding: utf-8 -*-
"""纯 ASCII 输出：列出条款里每个半角空格的前后字符码点（避免控制台乱码误判）"""
import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"d:\AI_JZL\XB_ToolBox"
s = io.open(ROOT + r"\nodes_image_prompt_preset.py", encoding="utf-8").read()
i = s.index("IO_I2I_COMMON = {")
j = s.index("def mode_io_clause(")
ns = {}
exec("LANG_ZH = 'ZH'\nOUTPUT_LANGS = ['ZH', 'EN']\n" + s[i:j], ns)
CJK = lambda c: "\u4e00" <= c <= "\u9fff"
for name in ("IO_I2I_COMMON", "T2I_FALLBACK_TAIL", "IO_T2I_FALLBACK"):
    for k, v in ns[name].items():
        ks = k.encode("unicode_escape").decode("ascii")[:40]
        for idx, ch in enumerate(v):
            if ch == " ":
                p = v[idx - 1] if idx else ""
                n = v[idx + 1] if idx + 1 < len(v) else ""
                flag = "<<< CJK 间空格" if (p and n and CJK(p) and CJK(n)) else ""
                print("%-14s %s  sp@%3d prev=%s next=%s %s" % (
                    name, ks[:12], idx, hex(ord(p)) if p else "-", hex(ord(n)) if n else "-", flag))
        print("   len=%d  U+3000=%d  double-space=%d" % (
            len(v), v.count("\u3000"), v.count("  ")))
