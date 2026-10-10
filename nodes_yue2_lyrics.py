"""XB-BOX - 🎵 YuE2 歌词（段落标签 + 可唱性检查）

官方歌词规范：
  · 只放「要唱的词」+ 段落标签，风格/乐器/语言/实现说明一律不写进歌词；
  · 段落用 [方括号] 标记。**官方 skill 的段落词表是 8 个**（来自 ABC 的 % section 规范，
    官方 instrumental.lyric_tags() 会把它们标题化输出）：
        % intro → [Intro]            % chorus      → [Chorus]
        % verse → [Verse]            % bridge      → [Bridge]
        % pre-chorus → [Pre-Chorus]  % interlude   → [Interlude]
        % instrumental → [Instrumental]           % outro → [Outro]
    官方 ComfyUI 模板的说明只举了 [Verse]/[Chorus]/[Bridge]/[Outro] 四个，措辞是
    "such as"，并非全集；YuE2 把 [xxx] 当通用段落标记，任意标签都能用；
  · 纯音乐（无人声）必须给空歌词或「只有段落标签、没有实词」；
  · 官方对翻译/改编强调「音节 ↔ 音符对齐」，所以本节点额外给出逐行音节统计，
    用来判断同一段内的可唱性（这是 YuE2 独有的检查点，MiniMax 节点没有）。

标签快捷插入、一键纯音乐骨架、自定义标签都在 js/xb_yue2_lyrics.js 里做。

CATEGORY: JZL/YuE2
"""

import re

try:
    from .yue2_abc import OFFICIAL_SECTION_TAGS
except ImportError:  # 以文件方式直接加载时的兜底
    from yue2_abc import OFFICIAL_SECTION_TAGS


# 官方 8 个段落标签（单一数据源 = yue2_abc.OFFICIAL_SECTION_TAGS）
OFFICIAL_TAGS = tuple(OFFICIAL_SECTION_TAGS)

# 非官方的常见写法（社区惯例）：官方 skill 的 SECTIONS 词表里没有这些
COMMUNITY_TAGS = ("Post-Chorus", "Solo", "Hook", "Drop", "Breakdown", "Final Chorus")

# 编号变体（社区写法，官方示例不编号）；面板里固定列出这几个，其它编号由下面的正则兜住
NUMBERED_TAGS = ("Verse 1", "Verse 2", "Chorus 2")

# 兜底：任意 `[主歌 3]` 这类编号写法也算社区写法
NUMBERED_RE = re.compile(r"^(?:Intro|Verse|Pre-Chorus|Post-Chorus|Chorus|Bridge|Interlude|Instrumental|Outro|Solo|Hook)\s*\d+$", re.IGNORECASE)

# 疑似「实现说明」的词（命中只做提示，歌词里出现乐器词不一定就是错的）
STYLE_WORDS = (
    "bpm", "tempo", "genre", "instrument", "instrumental", "arrangement", "arrange",
    "mix", "mixing", "master", "mastering", "reverb", "delay", "chord", "chords",
    "melody", "harmony", "key of", "style prompt", "vocal style", "produce",
    "production", "钢琴", "吉他", "贝斯", "鼓组", "编曲", "混音", "母带", "和弦",
    "旋律", "调性", "速度", "曲风", "配器", "混响", "自动调音", "风格", "乐器",
)

TAG_RE = re.compile(r"\[([^\[\]\n]*)\]")
# 圆括号角色标注：官方预处理只认 [方括号]，圆括号会被当成歌词唱出来
ROUND_ROLE_RE = re.compile(r"\((?:Singer|歌手|男声|女声|男|女)[^)\n]*\)\s*[:：]?", re.IGNORECASE)


def extract_tags(text: str) -> list:
    """按出现顺序取出所有 [标签]。"""
    return [match.group(1).strip() for match in TAG_RE.finditer(text or "")]


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x2FA1F)


def syllable_count(line: str) -> int:
    """粗估音节数：CJK 每字 1 个；拉丁词按元音组近似（不追求语言学的精确）。"""
    total = 0
    for chunk in re.findall(r"[A-Za-z']+|[^\sA-Za-z']", line or ""):
        if re.fullmatch(r"[A-Za-z']+", chunk):
            groups = re.findall(r"[aeiouy]+", chunk.lower())
            total += max(1, len(groups))
        elif _is_cjk(chunk):
            total += 1
    return total


def split_sections(text: str) -> list:
    """把歌词按段落标签切分：[(标签, [歌词行…]), …]；标签前的内容归到 (None, …)。"""
    sections = []
    current_tag, current_lines = None, []
    for raw in (text or "").splitlines():
        line = raw.strip()
        tag = TAG_RE.fullmatch(line)
        if tag:
            if current_tag is not None or any(x.strip() for x in current_lines):
                sections.append((current_tag, current_lines))
            current_tag, current_lines = tag.group(1).strip(), []
            continue
        current_lines.append(raw)
    if current_tag is not None or any(x.strip() for x in current_lines):
        sections.append((current_tag, current_lines))
    return sections


def check_lyrics(text: str) -> str:
    """生成中文检查报告（节点「检查」输出）。"""
    body = text or ""
    lines = [(i + 1, line) for i, line in enumerate(body.splitlines()) if line.strip()]
    sections = split_sections(body)
    tags = extract_tags(body)
    words = [re.sub(r"\[[^\[\]\n]*\]", " ", line) for _, line in lines]
    sung_lines = [(number, text) for (number, text), stripped in zip(lines, words) if stripped.strip()]

    notes, warnings = [], []
    if not body.strip():
        warnings.append("歌词为空：YuE2 会按纯器乐/无人声处理；如果要唱，请补上实词")

    if tags:
        notes.append(f"段落标签 {len(tags)} 个：" + " ".join(f"[{t}]" for t in tags))
        plain = [t for t in tags if ":" not in t]
        official = [t for t in plain if t in OFFICIAL_TAGS]
        community = [t for t in plain if t not in OFFICIAL_TAGS
                     and (t in COMMUNITY_TAGS or t in NUMBERED_TAGS or NUMBERED_RE.match(t))]
        custom = [t for t in plain if t not in official + community]
        if official:
            notes.append("其中官方词表内：" + " ".join(f"[{t}]" for t in official))
        if community:
            notes.append("非官方写法（社区惯例，YuE2 能用但官方未定义）："
                         + " ".join(f"[{t}]" for t in community))
        if custom:
            notes.append("自定义标签（官方接受任意 [标记]，属弱控制）："
                         + " ".join(f"[{t}]" for t in custom))
    else:
        warnings.append("没有段落标签：YuE2 用官方 8 个段落标签描述结构"
                        "（[Intro]/[Verse]/[Pre-Chorus]/[Chorus]/[Bridge]/[Interlude]/[Instrumental]/[Outro]），"
                        "缺标签会让编曲缺少段落线索")

    empty = [tag for tag, content in sections if tag and not any(x.strip() for x in content)]
    if empty:
        notes.append("空段落标签（无实词）：" + " ".join(f"[{t}]" for t in empty)
                     + "；纯音乐/间奏可以这样写，需要人声则要补词")

    for number, line in sung_lines:
        lowered = line.lower()
        hit = next((word for word in STYLE_WORDS if word in lowered), None)
        if hit:
            warnings.append(f"第 {number} 行疑似混入风格/实现说明（命中 “{hit}”）："
                            f"官方要求只放要唱的词，风格与乐器请写进 style")
        if ROUND_ROLE_RE.search(line):
            warnings.append(f"第 {number} 行用了圆括号角色标注：YuE2 只把 [方括号] 当标签，"
                            f"圆括号内容可能被当成歌词唱出来")

    for tag, content in sections:
        counts = [syllable_count(line) for line in content if line.strip()]
        if len(counts) >= 2:
            notes.append(f"[{tag or '无标签'}] 每行音节 ≈ " + "/".join(str(c) for c in counts)
                         + f"（共 {len(counts)} 行）")
            if max(counts) - min(counts) >= 4:
                notes.append(f"  ↳ 同一段内音节起伏较大（{min(counts)}–{max(counts)}），"
                             f"官方强调音节与音符对齐，建议让同段各行音节数接近")
    if not sung_lines and body.strip():
        notes.append("只有段落标签，没有实词：正好对应官方纯音乐工作流的歌词写法")

    head = ["【YuE2 歌词检查】",
            f"有效行 {len(sung_lines)}   段落 {len(sections)}   标签 {len(tags)}"]
    if warnings:
        head += ["", "⚠️ 需要确认："] + [f"· {item}" for item in warnings]
    if notes:
        head += ["", "ℹ️ 结构信息："] + [f"· {item}" for item in notes]
    if not warnings:
        head += ["", "✅ 未发现明显问题（只做文本层检查，不代表演唱效果）"]
    return "\n".join(head)


class XB_YuE2Lyrics:
    """YuE2 歌词 — 段落标签 + 可唱性检查"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lyrics_text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": (
                        "歌词正文 + 段落标签。官方 skill 的段落词表是 8 个："
                        "[Intro]/[Verse]/[Pre-Chorus]/[Chorus]/[Bridge]/[Interlude]/[Instrumental]/[Outro]，"
                        "点上方「添加元素」插入；也能自己填任意 [自定义标签]（YuE2 接受任意 [标记]）。"
                        "⚠️ 只放要唱的词：风格、乐器、语言、速度都写进 style，不要写进歌词。\n"
                        "进阶：官方的「规划用歌词」可以只给段落标签（不写实词）喂给规划器，"
                        "实词另接给 YuE2GenerateMusic 的 lyrics —— 两个节点的 lyrics 可以不同。\n"
                        "不要把音节/音素对齐写进这里：官方要求对齐记录放 sidecar，"
                        "也不要用 w: 字段（会被当作非法记谱拒绝）"
                    ),
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("lyrics", "检查")
    FUNCTION = "build"
    CATEGORY = "JZL/YuE2"

    def build(self, lyrics_text):
        return (lyrics_text, check_lyrics(lyrics_text))
