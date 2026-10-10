"""XB-BOX - 🎵 YuE2 乐谱工作台 / 🎵 YuE2 翻唱准备

YuE2 与 MiniMax Music3 最大的差别：它先产出一份**可读可改的 ABC 谱面**，再据此
渲染音频（白盒生成）。官方工作流要求在投喂生成器之前先「检视 / 修正 / 去和弦 /
把旋律移到器乐轨」，而 ComfyUI 里原先只能靠 PreviewAny 看一堆文本。这两个节点把
这套符号层操作搬进图里，全部复用官方 skill 的有界方言解析器（见 yue2_abc.py）。

⚠️ 关键认知：**谱面里没有乐器**。原生 ABC 只有 Vocal / Ins 两条单声部旋律线
（Ins 是旋律线，不是钢琴伴奏谱），音色与配器只能写在 style 里 —— 用上游
「🎵 YuE2 风格提示」的「主奏乐器 / 辅助乐器」指定。

工作台（对谱面本身动手）：
  只查看 / 去掉和弦 / 人声移到器乐轨 / 用编辑框 / 编译事件
翻唱准备（生成翻唱条件）：
  保留声部 × 和声处理 → 决定 cot（去掉和弦=melody 纯翻唱、保留和弦=full 连和声一起留）

选项只写选项名，说明一律写在 widget 的 tooltip 里（悬停可见）。

两个节点都是 2 路输出：`abc`（处理后谱面）+ `报告`（中文可读，首行就是模式建议）。
都「失败不中断图」：出错时报告写明原因、`abc` 原样透传，而不是抛异常打断工作流。
报告只声明符号层结论，不代表音频效果。

CATEGORY: JZL/YuE2
"""

import json

try:
    from .yue2_abc import (
        AbcError, TOKEN, VOICES, compare_text, compile_events, convert_score,
        diff_lines, mode_suggestion, parse_abc, sha_line, strip_chords,
        summary_text, validate_instrumental,
    )
except ImportError:  # 以文件方式直接加载时的兜底
    from yue2_abc import (
        AbcError, TOKEN, VOICES, compare_text, compile_events, convert_score,
        diff_lines, mode_suggestion, parse_abc, sha_line, strip_chords,
        summary_text, validate_instrumental,
    )


# ── 工作台：操作（值即界面文案；改文案要同步 js/xb_yue2_score.js）──
OP_INSPECT = "只查看 / Inspect"
OP_STRIP = "去掉和弦 / Strip Chords"
OP_MOVE = "人声移到器乐轨 / Vocal to Ins"
OP_EDITED = "用编辑框 / Use Edited"
OP_COMPILE = "编译事件 / Compile Events"
OPERATIONS = (OP_INSPECT, OP_STRIP, OP_MOVE, OP_EDITED, OP_COMPILE)

# ── 工作台：移轨后的和声处理（说明写在 tooltip 里，见 INPUT_TYPES）──
HARMONY_KEEP = "保留和弦 / Keep Chords"
HARMONY_DROP = "去掉和弦 / Drop Chords"
HARMONY_CHOICES = (HARMONY_KEEP, HARMONY_DROP)

# ── 工作台：重叠策略（官方 --overlap vocal|error）──
OVERLAP_VOCAL = "人声优先 / Vocal Priority"
OVERLAP_ERROR = "直接报错 / Error Out"
OVERLAP_CHOICES = (OVERLAP_VOCAL, OVERLAP_ERROR)

# ── 翻唱准备：保留声部 ──
KEEP_BOTH = "两条都保留 / Keep Both"
KEEP_VOCAL = "只保留人声 / Keep Vocal"
KEEP_INS = "只保留器乐 / Keep Ins"
KEEP_CHOICES = (KEEP_BOTH, KEEP_VOCAL, KEEP_INS)

# ── 翻唱准备：和声处理（说明写在 tooltip 里）──
COVER_DROP = "去掉和弦 / Drop Chords"
COVER_KEEP = "保留和弦 / Keep Chords"
COVER_HARMONY_CHOICES = (COVER_DROP, COVER_KEEP)

CHORD_NOTE = "配器（乐器 / 音色）不在谱面里：请在上游「🎵 YuE2 风格提示」的「主奏乐器 / 辅助乐器」设定"
DISCLAIMER = "（符号层结论：不代表音频效果，也不代表歌手音色或波形被保留）"


def _report(headline: str, body: str, source: str = "") -> str:
    parts = [headline, body]
    if source:
        parts.append(sha_line(source))
    return "\n\n".join(parts) + f"\n{DISCLAIMER}"


def _error_report(title: str, error: Exception) -> str:
    return (f"❌ {title}失败\n原因: {error}\n\n"
            f"建议: 谱面已原样透传、未做任何修改。先把「操作」设成「只查看」看结构能否通过；"
            f"或把修好的谱面粘进编辑框，再把「操作」设成「用编辑框」重新校验。\n"
            f"{DISCLAIMER}")


def _silence_other_voice(text: str, keep_voice: str) -> str:
    """只保留某一声部的音符，另一声部补等时值休止，但**保留和弦记号**（官方工具没有这条路径）。"""
    score = parse_abc(text)
    lines = text.splitlines(keepends=True)
    for index, name in score.music_lines.items():
        if name == keep_voice:
            continue
        lines[index] = TOKEN.sub(
            lambda m: ("z" + m.group("duration")) if m.group("note") is not None else m.group(0),
            lines[index])
    output = "".join(lines)
    result = parse_abc(output)
    if result.voices[keep_voice].notes != score.voices[keep_voice].notes:
        raise AbcError(f"{keep_voice}: 保留声部的音符被改动了")
    if result.voices[keep_voice].chords != score.voices[keep_voice].chords:
        raise AbcError(f"{keep_voice}: 保留声部的和弦记号被改动了")
    if any(v.notes for name, v in result.voices.items() if name != keep_voice):
        raise AbcError("未选中的声部没有清空")
    return output


class XB_YuE2ScoreWorkbench:
    """YuE2 乐谱工作台 — 查看 / 去和弦 / 移轨 / 校验编辑框"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "操作": (list(OPERATIONS), {
                    "default": OP_INSPECT,
                    "tooltip": ("只查看：仅校验并出报告，谱面不动。也能用来发现谱面被截断"
                                "（截断的谱面结构校验会直接失败）。\n"
                                "去掉和弦：删掉 Vocal 声部的和弦记号（下游 mode 要选 melody）。\n"
                                "人声移到器乐轨：把唱旋律搬到 Ins 轨、Vocal 清空留和弦与休止"
                                "（只搬旋律，不改乐器）。\n"
                                "用编辑框：改用手工修改的谱面并重新校验，同时列出与上游的差异。\n"
                                "编译事件：编辑框里贴官方 events.json（同 instrumental 的事件编译器），"
                                "由事件生成一份合法谱面。\n"
                                "无关选项会自动隐藏"),
                }),
                "和声处理": (list(HARMONY_CHOICES), {
                    "default": HARMONY_KEEP,
                    "tooltip": ("仅「人声移到器乐轨」时生效。\n"
                                "保留和弦 → 谱面仍带和弦，下游 mode 必须选 full（可继续改和声）。\n"
                                "去掉和弦 → 下游 mode 必须选 melody（伴奏自由发挥）。\n"
                                "配器（钢琴/吉他等）不在这里设：请用上游「🎵 YuE2 风格提示」的"
                                "「主奏乐器 / 辅助乐器」"),
                }),
                "重叠处理": (list(OVERLAP_CHOICES), {
                    "default": OVERLAP_VOCAL,
                    "tooltip": ("仅「人声移到器乐轨」时生效。\n"
                                "人声优先：Vocal 与 Ins 时间重叠时，Ins 被裁短让位（官方默认）。\n"
                                "直接报错：检测到重叠就报错，让你先手工改谱"),
                }),
                "编辑框": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": ("「用编辑框」时放谱面；「编译事件」时放 events.json。\n"
                                "events.json 格式（时间单位=四分音符，只用整数或 \"3/2\" 这类分数字符串）：\n"
                                '{"bpm":81,"key":"Bm","bars":[{"meter":"4/4","section":"verse"},{}],'
                                '"notes":[[0,1,71],[1,"1/2",74]],"chords":[[0,"Bm"]]}\n'
                                "只能单旋律、不能重叠或叠音；越界/冲突和弦/不可表达时值都会报错"),
                }),
            },
            "optional": {
                "abc": ("STRING", {"forceInput": True,
                                   "tooltip": "上游谱面：接 YuE2GenerateABC 的 abc 输出"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("abc", "报告")
    FUNCTION = "run"
    CATEGORY = "JZL/YuE2"

    def run(self, 操作, 和声处理, 重叠处理, 编辑框, abc=None):
        # 不做 strip：谱面原样透传，报告里的 SHA 才与下游收到的文本一致
        source = abc or ""

        if 操作 == OP_COMPILE:
            raw = (编辑框 or "").strip()
            if not raw:
                return ("", _error_report("读取事件", ValueError("编辑框是空的：请把 events.json 内容粘进来")))
            try:
                events = json.loads(raw)
            except json.JSONDecodeError as error:
                return ("", _error_report("解析事件 JSON", ValueError(f"{error}")))
            if not isinstance(events, dict):
                return ("", _error_report("解析事件 JSON", ValueError("events.json 顶层必须是对象")))
            try:
                output, _check = compile_events(events)
                bars = len(events.get("bars") or [])
                notes = len(events.get("notes") or [])
                chords = len(events.get("chords") or [])
                mode, reason = mode_suggestion(output)
                body = [
                    f"判定依据: {reason}", "",
                    f"本次操作: 由事件编译出谱面（官方事件编译器）—— 小节 {bars}，音符 {notes}，和弦 {chords}",
                    f"事件来源: BPM {events.get('bpm')}，调号 {events.get('key', 'C')}",
                ]
                if source.strip():
                    body.append("与上游谱面差异:")
                    body += [f"  · {item}" for item in diff_lines(source, output)]
                body += ["", summary_text(output), "", CHORD_NOTE]
                headline = f"📋 YuE2 乐谱报告　｜　模式建议: mode={mode}（在官方节点上照此选择）"
                return (output, _report(headline, "\n".join(body), output))
            except (AbcError, ValueError) as error:
                return ("", _error_report("编译事件", error))

        if 操作 == OP_EDITED:
            edited = 编辑框 or ""
            if not edited.strip():
                return (source, _error_report("读取编辑框", ValueError("编辑框是空的")))
            output = edited
        else:
            output = source
        if not output.strip():
            return ("", _error_report("读取谱面", ValueError("上游 abc 为空，且编辑框也没有内容")))

        try:
            extra = ""
            if 操作 == OP_INSPECT:
                action = "谱面未改动"
            elif 操作 == OP_STRIP:
                output = strip_chords(output, "both")
                action = f"已去掉 {len(parse_abc(source).voices['Vocal'].chords)} 个和弦记号（Vocal 声部）"
            elif 操作 == OP_MOVE:
                output, check = convert_score(
                    output,
                    overlap="error" if 重叠处理 == OVERLAP_ERROR else "vocal",
                    keep_chords=和声处理 == HARMONY_KEEP)
                validate_instrumental(output)
                action = (f"已把 {check['vocal_notes_before']} 个人声音符移到 Ins 轨"
                          f"（Vocal 只留和弦与休止）")
                extra = (f"核对: 人声音符 {check['vocal_notes_before']} → {check['vocal_notes_after']}"
                         f"（全部落到 Ins）；Ins 发声音符 {check['original_ins_notes']} → "
                         f"{check['output_ins_notes']}；原 Ins 音符未被改写 {check['unaltered_ins_notes']} 个\n"
                         f"     音高/起音/时长保留 {check['vocal_pitch_onset_duration_preserved']}    "
                         f"拍号与速度保留 {check['meter_and_tempo_preserved']}    "
                         f"和弦 {'保留' if 和声处理 == HARMONY_KEEP else '去掉'}")
            else:
                action = "使用编辑框的谱面（已重新校验）"

            mode, reason = mode_suggestion(output)
            body = [f"判定依据: {reason}", "", f"本次操作: {action}"]
            if 操作 == OP_MOVE:
                body.append(extra)
            elif 操作 == OP_STRIP:
                # 去和弦是唯一「旋律必须原封不动」的操作，比对结果才有诊断价值
                body.append("事件比对: " + compare_text(source, output).splitlines()[0])
            elif source.strip() and source != output:
                # 手工编辑：官方要求「显式审阅差异」，而不是只看一个结论
                body.append("与上游谱面差异:")
                body += [f"  · {item}" for item in diff_lines(source, output)]
            body += ["", summary_text(output), "", CHORD_NOTE]
            headline = f"📋 YuE2 乐谱报告　｜　模式建议: mode={mode}（在官方节点上照此选择）"
            return (output, _report(headline, "\n".join(body), output))
        except (AbcError, ValueError) as error:
            return (source, _error_report("处理谱面", error))


class XB_YuE2CoverPrep:
    """YuE2 翻唱准备 — 保留声部 × 和声处理 → 翻唱条件"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "保留声部": (list(KEEP_CHOICES), {
                    "default": KEEP_BOTH,
                    "tooltip": ("两条都保留：什么都不丢。\n"
                                "只保留人声 / 只保留器乐：另一条会换成等时值休止（保留和弦记号）。\n"
                                "官方提醒：不要因为叫「翻唱」就丢掉 Ins —— Ins 可能承载主题或独奏"),
                }),
                "和声处理": (list(COVER_HARMONY_CHOICES), {
                    "default": COVER_DROP,
                    "tooltip": ("去掉和弦 → 下游 mode 选 melody：谱面只给纯旋律，伴奏与和声按新风格"
                                "重新生成（官方定义的翻唱）。\n"
                                "保留和弦 → 下游 mode 选 full：连原和声一起保留，属「乐谱条件化重生成」，"
                                "更接近原版重录。\n"
                                "配器（钢琴/吉他等）不在这里设：请用上游「🎵 YuE2 风格提示」的"
                                "「主奏乐器 / 辅助乐器」"),
                }),
            },
            "optional": {
                "abc": ("STRING", {"forceInput": True,
                                   "tooltip": "原始谱面：接转谱结果或 YuE2GenerateABC 的 abc 输出"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("abc", "报告")
    FUNCTION = "run"
    CATEGORY = "JZL/YuE2"

    def run(self, 保留声部, 和声处理, abc=None):
        source = abc or ""
        if not source.strip():
            return ("", "❌ 上游 abc 为空：翻唱需要一条由转谱或计划得到的谱面\n" + DISCLAIMER)

        keep = {KEEP_BOTH: "both", KEEP_VOCAL: "Vocal", KEEP_INS: "Ins"}[保留声部]
        keep_names = {KEEP_BOTH: "两条旋律都保留", KEEP_VOCAL: "只保留人声（唱旋律）",
                      KEEP_INS: "只保留器乐（器乐旋律）"}[保留声部]

        try:
            counts = {name: len(parse_abc(source).voices[name].notes) for name in VOICES}
            if 和声处理 == COVER_KEEP:
                output = source if keep == "both" else _silence_other_voice(source, keep)
                harmony = "保留原和弦"
                route = ("保留和弦 → 谱面带着和弦符号进 YuE2，mode 必须选 full：旋律与和声一起重渲染"
                         "（官方称「乐谱条件化重生成」，不算纯翻唱）")
            else:
                output = strip_chords(source, keep)
                harmony = "去掉和弦"
                route = ("去掉和弦 → 谱面作为纯旋律条件进 YuE2，mode 必须选 melody："
                         "伴奏与和声由新风格重新生成（这才是官方定义的翻唱）")

            mode, _ = mode_suggestion(output)
            compared = VOICES if keep == "both" else (keep,)
            body = [
                f"本次设置: {keep_names} + {harmony}",
                f"路线说明: {route}",
                "事件比对: " + compare_text(source, output, compared).splitlines()[0],
                "原始音符数: " + "  ".join(f"{k}={v}" for k, v in counts.items()),
                "",
                "【官方翻唱链路】",
                "1. 音频来源：先用 SheetSage2 转谱（scripts/transcribe.py）得到原生两轨 ABC；"
                "已有 ABC 则先按原生方言检查结构与调号、拍号。",
                "2. 本节点已完成：声部保留 + 和声取舍 → 输出上面第 1 路的 abc。",
                f"3. 把 abc 接到官方 YuE2 的 ABC 输入，mode 选 {mode}；style 用「🎵 YuE2 风格提示」、"
                "歌词用「🎵 YuE2 歌词」（段落标签要与谱面结构对齐）。",
                "4. 结果校验：听感与 ASR 分开核对，不要从谱面检查推断音频质量；"
                "官方明确 melody 条件只提供符号层旋律，不保留原唱歌手音色与波形。",
                "",
                "注意: 转谱误差是独立误差来源 —— 转轨/比对只证明「转写谱」上的音符被保住，"
                "不代表转写本身忠于原录音。",
                "",
                CHORD_NOTE,
            ]
            headline = f"📋 YuE2 翻唱报告　｜　模式建议: mode={mode}（在官方节点上照此选择）"
            return (output, _report(headline, "\n".join(body), output))
        except (AbcError, ValueError) as error:
            return (source, _error_report("翻唱准备", error))
