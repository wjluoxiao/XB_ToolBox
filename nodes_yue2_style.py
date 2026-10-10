"""XB-BOX - 🎵 YuE2 风格提示（官方 6 段式 style 前置节点）

官方 style 规范（Prompt Guide）：Language + Genre + Vocal Character + Tempo
+ Instruments + Musical Characteristics，输出为「扁平标签串 + 一句音乐特征」。

输出 STRING 直接连官方 YuE2GenerateABC / YuE2GenerateMusic 的 style 输入；
另外两路（max_duration / seed）连官方节点的同名输入：plan 与 song 用同一个
seed 才能复现同一份谱面与音频（官方文档的可复现要求）。

与 MiniMax Music3 提示词预设的差异（按 YuE2 真实能力设计，不做复刻）：
  · 不写段落结构 / 调式 / 调号 / 拍号 —— YuE2 这些信息由 ABC 谱面承担，
    style 只做与谱面一致的描述；
  · 不写实现指令 —— 官方明确禁止把 "plan a melody with chords" 之类塞进 style；
  · 语言是独立必填维度（官方 Guide 的第一段）；
  · 无「合唱团 SATB / 人声效果链」等官方范式，对唱/合唱只能靠文本弱控制。

CATEGORY: JZL/YuE2
"""

import re

try:
    from .yue2_styles import (
        BPM_HINTS, DENSITY_HINTS, GENRES, INSTRUMENT_HINTS, LANGUAGE_HINTS,
        MOOD_HINTS, RECIPES, TECHNIQUE_HINTS, TEXTURE_HINTS, TIMBRE_HINTS,
        VOCAL_FX_HINTS, VOCAL_HINTS, FOLLOW, CUSTOM, genre_options,
    )
except ImportError:  # 以文件方式直接加载时的兜底
    from yue2_styles import (
        BPM_HINTS, DENSITY_HINTS, GENRES, INSTRUMENT_HINTS, LANGUAGE_HINTS,
        MOOD_HINTS, RECIPES, TECHNIQUE_HINTS, TEXTURE_HINTS, TIMBRE_HINTS,
        VOCAL_FX_HINTS, VOCAL_HINTS, FOLLOW, CUSTOM, genre_options,
    )


# 官方器乐入口（instrumental.py）强制补齐的四个人声抑制条件，顺序也照抄
VOCAL_SUPPRESSION = ("no vocals", "no singing", "no choir", "no spoken words")


def instrumental_style(style: str) -> str:
    """按官方器乐入口处理 style（instrumental.py 的 prepare 分支）：

      · 标签行必须以 Instrumental 开头（没有就补前缀）
      · 四个抑制条件逐个补齐 —— 判断范围是**整条 style**（标签行 + 音乐特征句 + 自定义补充），
        与官方一致；已出现过的条件不重复追加
      · 标签行末尾补一个句号

    为什么必须这么做：只写「no lead vocal」不等于禁止人声 —— 哼唱、和声、
    伴唱仍可能出现。官方用这四个条件明确排除人声、拟声与念白。
    """
    lines = (style or "").split("\n")
    tags = lines[0].strip().rstrip(".,")
    rest = lines[1:]
    whole = style.lower()
    if not re.match(r"^instrumental\b", tags, re.IGNORECASE):
        tags = "Instrumental, " + tags
    for condition in VOCAL_SUPPRESSION:
        if condition not in whole:
            tags += ", " + condition
    return "\n".join([tags + "."] + rest)


UNSPECIFIED = "不指定 / Unspecified"
NO_SECONDARY = "无 / None"
INSTRUMENTAL_LANGUAGE = "纯音乐 / Instrumental"
INSTRUMENTAL_VOCAL = "无主唱 / No Vocals"
FOLLOW_TIMBRE = FOLLOW


def _cap(text: str) -> str:
    """去首尾空白与尾部句号，并把首字母大写。"""
    value = (text or "").strip().rstrip(".")
    return (value[:1].upper() + value[1:]) if value else value


def _dot(text: str) -> str:
    """去首尾空白，并保证句尾有句号。"""
    value = (text or "").strip()
    if not value:
        return ""
    return value if value.endswith(".") else value + "."


class XB_YuE2StylePrompt:
    """YuE2 风格提示 — 6 段维度 → 官方风格串"""

    _RECIPES = RECIPES

    _GENRES = GENRES

    def _apply_recipe(self, params: dict) -> dict:
        """配方 != 自定义 时用配方值覆盖对应参数（后端也覆盖，不依赖前端）。"""
        overrides = self._RECIPES.get(params.get("配方", CUSTOM))
        if not overrides:
            return params
        merged = dict(params)
        for key, value in overrides.items():
            if key in merged:
                merged[key] = value
        return merged

    # 历史工作流里可能残留旧版下拉值，未知值一律按「未指定」处理，
    # 因此这几个输入声明为免校验，避免组合校验直接拒掉整个 prompt。
    @classmethod
    def VALIDATE_INPUTS(cls, 音乐风格=None, 风格融合=None, 人声编制=None, 人声音色=None,
                        人声唱法=None, 人声效果=None, 速度=None, 情绪氛围=None,
                        主奏乐器=None, 辅助乐器=None, 编曲密度=None, 制作质感=None,
                        演唱语言=None):
        return True

    @classmethod
    def INPUT_TYPES(cls):
        genres = genre_options()
        fusion_list = [UNSPECIFIED] + genres
        instrument_list = list(INSTRUMENT_HINTS.keys())
        return {
            "required": {
                "配方": (list(cls._RECIPES.keys()), {
                    "default": CUSTOM,
                    "tooltip": "一键配方：切换后自动回填下方全部维度（官方 Guide 的六段搭配），仍可手动微调；切走再切回即可恢复配方值",
                }),
                "演唱语言": (list(LANGUAGE_HINTS.keys()), {
                    "default": "中文 / Chinese",
                    "tooltip": ("官方 Guide 的第一段（语言）。\n"
                                "选「纯音乐」会自动省略人声段，并按官方器乐入口补齐四个抑制条件："
                                "no vocals / no singing / no choir / no spoken words（哼唱与念白也排除）。\n"
                                "⚠️ 光靠 style 不足以去掉人声：官方纯音乐链路必须同时做两件事 ——\n"
                                "  ① 谱面里 Vocal 不能有发声音符（用「🎵 YuE2 乐谱工作台」的「人声移到器乐轨」）；\n"
                                "  ② 歌词为空或只有段落标签（用「🎵 YuE2 歌词」的「纯音乐骨架」）。\n"
                                "官方明确：文件检查不能证明没有人声泄漏，最终要听音确认"),
                }),
                "音乐风格": (genres, {
                    "default": genres[0],
                    "tooltip": "官方 Genre 段。选「跟随风格」的乐器 / 制作质感 / 音乐特征都取自这里",
                }),
                "风格融合": (fusion_list, {
                    "default": UNSPECIFIED,
                    "tooltip": "官方允许多曲风融合：副风格会以「with … influences」并入 Genre 段",
                }),
                "人声编制": (list(VOCAL_HINTS.keys()), {
                    "default": "女声独唱 / Female Lead",
                    "tooltip": ("官方 Vocal Character 段。\n"
                                "选「无主唱」等价于纯音乐（人声段整段省略）。\n"
                                "⚠️ YuE2 原生 Vocal 只有一条单声部旋律线：对唱 / 合唱属于文本弱控制，"
                                "不保证真的分成两个声部。\n"
                                "⚠️ 要做纯音乐必须把谱面的 Vocal 旋律移到 Ins 轨，否则谱面里本来就有唱旋律 → 会被人声唱/哼出来"),
                }),
                "人声音色": ([FOLLOW_TIMBRE] + [k for k in TIMBRE_HINTS if k != FOLLOW_TIMBRE], {
                    "default": FOLLOW_TIMBRE,
                    "tooltip": "官方 Vocal Character 段里的音色描述（warm / breathy / clear bright…）",
                }),
                "人声唱法": ([FOLLOW_TIMBRE] + [k for k in TECHNIQUE_HINTS if k != FOLLOW_TIMBRE], {
                    "default": FOLLOW_TIMBRE,
                    "tooltip": "咬字/律动/技法。官方示例里的 clear diction 属于这一段",
                }),
                "人声效果": ([FOLLOW_TIMBRE] + [k for k in VOCAL_FX_HINTS if k != FOLLOW_TIMBRE], {
                    "default": FOLLOW_TIMBRE,
                    "tooltip": "人声后期。YuE2 没有官方人声效果范式，这里只写进 style 做弱控制",
                }),
                "速度": (list(BPM_HINTS.keys()), {
                    "default": UNSPECIFIED,
                    "tooltip": "档位措辞；想写官方式精确值请填下面的 BPM数值（填了以后档位不参与拼接）",
                }),
                "BPM数值": ("INT", {
                    "default": 0, "min": 0, "max": 300, "step": 1,
                    "tooltip": "0 = 不使用。官方示例写法是「96 BPM」，填了就按精确值输出，并要求与谱面的 Q:1/4 一致",
                }),
                "情绪氛围": (list(MOOD_HINTS.keys()), {
                    "default": UNSPECIFIED,
                    "tooltip": "音乐特征句开头的情绪定语（如「Melancholic and wistful.」）。留空则只输出曲风的特征句",
                }),
                "主奏乐器": ([FOLLOW_TIMBRE] + instrument_list, {
                    "default": FOLLOW_TIMBRE,
                    "tooltip": "官方 Instruments 段的主奏乐器；「跟随风格」取所选曲风的默认编制",
                }),
                "辅助乐器": ([FOLLOW_TIMBRE, NO_SECONDARY] + instrument_list, {
                    "default": FOLLOW_TIMBRE,
                    "tooltip": "官方 Instruments 段的辅助乐器。选「无」+主奏乐器=独奏编制（输出 solo <乐器>）。\n"
                               "⚠️ 这是唯一能指定乐器的地方：ABC 谱面里没有乐器字段，"
                               "「人声移到器乐轨」也不会替你选乐器",
                }),
                "编曲密度": (list(DENSITY_HINTS.keys()), {
                    "default": FOLLOW_TIMBRE,
                    "tooltip": "配器的疏密（极简留白 / 标准 / 饱满丰富 / 密集推进）。留空则交由模型按曲风处理",
                }),
                "制作质感": (list(TEXTURE_HINTS.keys()), {
                    "default": FOLLOW_TIMBRE,
                    "tooltip": "官方 Musical Characteristics 里的制作质感描述",
                }),
                "音乐特征": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "官方示例的第二句（Catchy and energetic, with an uplifting summer atmosphere…）；留空则用曲风的默认特征句",
                }),
                "自定义补充": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "长尾词，直接追加到音乐特征句后面（如「现场鼓组、观众和声」）",
                }),
                "max_duration": ("FLOAT", {
                    "default": 120.0, "min": 1.0, "max": 900.0, "step": 1.0,
                    "tooltip": "官方 YuE2GenerateMusic 的 max_duration（秒）：上限而非目标，模型可能提前结束。\n"
                               "不需要可编辑谱面时：不接 YuE2GenerateABC、abc 留空，官方节点会自动进入 off 模式",
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 0x7FFFFFFFFFFFFFFF,
                    "tooltip": "官方节点的 seed。规划器与生成器必须喂同一个 seed，才能复现同一份谱面与音频",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT", "INT")
    RETURN_NAMES = ("style", "max_duration", "seed")
    FUNCTION = "build"
    CATEGORY = "JZL/YuE2"

    def build(self, 配方, 演唱语言, 音乐风格, 风格融合, 人声编制, 人声音色, 人声唱法,
              人声效果, 速度, BPM数值, 情绪氛围, 主奏乐器, 辅助乐器, 编曲密度,
              制作质感, 音乐特征, 自定义补充, max_duration, seed):
        params = self._apply_recipe({k: v for k, v in locals().items() if k != "self"})
        genre = self._GENRES.get(params["音乐风格"]) or {}
        instrumental = (params["演唱语言"] == INSTRUMENTAL_LANGUAGE
                        or params["人声编制"] == INSTRUMENTAL_VOCAL)

        def term(table: dict, label: str) -> str:
            """标签 → 英文术语；未知/「跟随风格」回落为空串。"""
            return table.get(label, "")

        def genre_instrument(label: str) -> str:
            """曲风条目里存的是乐器标签，需要再映射成英文术语。"""
            return INSTRUMENT_HINTS.get(label, "")

        # ── ① 语言（官方 Guide 第一段）──
        language = LANGUAGE_HINTS.get(params["演唱语言"], "")

        # ── ② 曲风（含官方允许的双曲风融合）──
        genre_terms = genre.get("terms") or ""
        fusion = params["风格融合"]
        if fusion not in (UNSPECIFIED, params["音乐风格"]):
            fusion_terms = (self._GENRES.get(fusion) or {}).get("terms") or ""
            if fusion_terms:
                genre_terms = f"{genre_terms} with {fusion_terms} influences".strip()

        # ── ③ 人声（编制 + 音色 + 唱法 + 效果）；纯音乐整段省略 ──
        vocal = []
        if not instrumental:
            vocal = [term(VOCAL_HINTS, params["人声编制"]),
                     term(TIMBRE_HINTS, params["人声音色"]),
                     term(TECHNIQUE_HINTS, params["人声唱法"]),
                     term(VOCAL_FX_HINTS, params["人声效果"])]

        # ── ④ 速度：精确 BPM 优先（官方示例写法），否则用档位措辞 ──
        bpm = int(params["BPM数值"])
        tempo = f"{bpm} BPM" if bpm > 0 else term(BPM_HINTS, params["速度"])

        # ── ⑤ 乐器（主奏 + 辅助；辅助「无」= 主奏独奏）──
        primary = (genre_instrument(genre.get("primary", ""))
                   if params["主奏乐器"] == FOLLOW_TIMBRE
                   else term(INSTRUMENT_HINTS, params["主奏乐器"]))
        secondary_label = genre.get("secondary", "") if params["辅助乐器"] == FOLLOW_TIMBRE else params["辅助乐器"]
        secondary = "" if secondary_label == NO_SECONDARY else (
            genre_instrument(secondary_label) if params["辅助乐器"] == FOLLOW_TIMBRE
            else term(INSTRUMENT_HINTS, secondary_label))
        instruments = []
        if primary and secondary == primary:
            secondary = ""
        if primary and not secondary:
            instruments = [f"solo {primary}"]
        elif primary or secondary:
            instruments = [x for x in (primary, secondary) if x]

        # ── ⑥ 制作质感 + 编曲密度 ──
        if params["制作质感"] == FOLLOW_TIMBRE:
            texture = term(TEXTURE_HINTS, genre.get("texture", ""))
        else:
            texture = term(TEXTURE_HINTS, params["制作质感"])
        production = ", ".join(x for x in (texture, term(DENSITY_HINTS, params["编曲密度"])) if x)

        head = [language, genre_terms, ", ".join(x for x in vocal if x), tempo,
                ", ".join(instruments), production]
        style_line = ", ".join(x for x in head if x)

        # ── 音乐特征句（官方示例第二句）──
        mood = _cap(term(MOOD_HINTS, params["情绪氛围"]))
        character = params["音乐特征"].strip() or genre.get("character", "")
        tail = " ".join(x for x in (_dot(mood), _dot(character)) if x)
        if params["自定义补充"].strip():
            tail = (tail + " " + params["自定义补充"].strip()).strip()

        style = style_line + ("\n" + tail if tail else "")
        if instrumental:
            # 纯音乐：照官方器乐入口补齐 Instrumental 前缀与四个人声抑制条件
            # （判断范围含音乐特征句与自定义补充，避免重复追加）
            style = instrumental_style(style)
        return (style, float(params["max_duration"]), int(params["seed"]))
