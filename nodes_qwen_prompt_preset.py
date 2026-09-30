"""
XB-BOX - 🖼️ Qwen2.1提示词预设
==============================
「XB-BOX - 🖼️ 生图提示词预设Pro」的兄弟节点：保留生图预设与元素面板，
把「LLM 反推」换成 **官方 Load CLIP + 官方 Generate Text** 这套纯本地文本生成链路。

① 生图预设
   · 空latent类型（9 种主流模型，逐字段对齐官方 latent_format）
   · 输出语言 / 预设模式 / 设定词（三视图·四视图·五视图·背景纯透明）
   · 画幅比例 / 宽度 / 高度 / 生成数量
   · 元素面板提示词拼装（8 大类词表，前端 js/xb_qwen_prompt_preset.js）

② 文本生成（官方两个节点的参数，逐字对齐；没有开关，执行即生成）
   · 模型选择 = 官方 Load CLIP：clip_name（models/text_encoders）+ type（默认 qwen_image）+ device（默认 default）
   · 参数设置 = 官方 Generate Text 全量参数：
     max_length / sampling_mode（on·off）/ temperature / top_k / top_p / min_p /
     repetition_penalty / presence_penalty / seed / thinking / use_default_template / mtp
   * 入参 prompt = 【参考设定·设定词】+【正文】+【额外要求·追加设定】
   · 出参 = 设定词原封不动置顶 + 生成文本（与「生图提示词预设」的成句规则一致）
   · SKILL选择 = support_llama/skills 里的 txt，整段作为官方 Generate Text 的 system_prompt 送进模型
     （与官方同义：use_default_template = 关时 system_prompt 被忽略）

输出：提示词 / 空latent（只有两路；没有 提示词列表 / 提示词设定）

CATEGORY: XB_ToolBox/Image_Params
"""

import gc
import json
import math
import sys

import folder_paths
import nodes
import torch

import comfy.model_management
import comfy.sd


# ════════════════════════════════════════════════════════════════════════════
#  本节点自带副本：预设模式 / 预设文本 / 中英双语 / 空latent 规格 / 文生图·图生图两套 / SKILL 三态
#  ⚠️ 与「生图提示词预设」「生图提示词预设Pro」**完全独立**：
#     改这里不会影响任何别的节点（也不受别的节点影响）。
# ════════════════════════════════════════════════════════════════════════════
ASPECT_RATIO_OPTIONS = ["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"]
ASPECT_RATIO_MAP = {"1:1": 1.0, "16:9": 16 / 9, "9:16": 9 / 16,
                    "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9}
SIZE_STEP = 16            # 宽高步长的兜底值（实际以「空latent类型」的官方最小步长为准：8/16/32）
SIZE_MIN = 16
BATCH_MAX = 4096          # 官方 EmptyLatentImage / EmptySD3LatentImage 的 batch 上限
MAX_RESOLUTION = int(getattr(nodes, "MAX_RESOLUTION", 16384) or 16384)

# ── 面板枚举（字符串即存储值，前端面板与后端按同一份字符串对齐） ────────────
OUTPUT_LANGS = ["中文 [ZH]", "英文 [EN]"]
# 预设模式：第 1 档 = 无预设（不前置任何设定词，只输出正文），其余按「文生图组 → 图生图组」排列
# （官方 Qwen-Image-2.1 示例库归纳）。⚠️ 这些字符串就是工作流里的存储值，改名必须同步 MODE_ALIASES
PRESET_MODES = [
    "无预设", "人物三视图", "人物四视图", "人物五视图", "背景纯透明",
    "图文版面",
    "信息图",
    "多格分镜",
    "广告分镜板",
    "保持主体换场景",
    "局部编辑",
    "老照片修复",
    "整图风格化",
    "360°全景",
    "多图指认合成",
]

LANG_ZH = OUTPUT_LANGS[0]
MODE_TEXT2IMG = PRESET_MODES[0]
MODE_THREE_VIEW = PRESET_MODES[1]
MODE_FOUR_VIEW = PRESET_MODES[2]
MODE_FIVE_VIEW = PRESET_MODES[3]
MODE_TRANSPARENT = PRESET_MODES[4]
MODE_UI = "图文版面"
MODE_INFO = "信息图"
MODE_STORYBOARD = "多格分镜"
MODE_ADBOARD = "广告分镜板"
MODE_KEEP_SUBJECT = "保持主体换场景"
MODE_LOCAL_EDIT = "局部编辑"
MODE_RESTORE = "老照片修复"
MODE_STYLIZE = "整图风格化"
MODE_PANO360 = "360°全景"
MODE_MULTI_REF = "多图指认合成"
# 需要输入图的档位（图生图组）：面板会给「必须接图」提示
MODE_NEEDS_IMAGE = [
    MODE_KEEP_SUBJECT,
    MODE_LOCAL_EDIT,
    MODE_RESTORE,
    MODE_STYLIZE,
    MODE_PANO360,
    MODE_MULTI_REF,
]


def mode_needs_image(preset_mode):
    """该预设模式是否必须接输入图（图生图组）"""
    return normalize_mode(preset_mode) in MODE_NEEDS_IMAGE


def mode_skill_hint(preset_mode):
    """该预设模式推荐搭配的 SKILL 文件（support_llama/skills；仅供面板展示，不自动改用户设置）"""
    return "system_prompt_edit.txt" if mode_needs_image(preset_mode) else "system_prompt_t2i.txt"

# ── SKILL 三态：不用 / 手动 / 自动（默认自动）────────────────────────────
# · 自动 = 按当前预设模式自动适配（图生图档 → prompt_edit，其余 → prompt_t2i）
# · 手动 = 用节点上 skill_name 选中的那一个
# · 不用 = 完全不生效（哪怕 skill_name 选了也不生效）
SKILL_MODE_AUTO = "自动"
SKILL_MODE_MANUAL = "手动"
SKILL_MODE_OFF = "不用"
SKILL_MODES = [SKILL_MODE_AUTO, SKILL_MODE_MANUAL, SKILL_MODE_OFF]


def skill_mode_of(value):
    """归一 SKILL 模式（缺失 / None / 非法 → 自动）"""
    m = _as_str(value).strip()
    return m if m in SKILL_MODES else SKILL_MODE_AUTO


def effective_skill_name(skill_mode, skill_name, preset_mode):
    """本次实际会用到的 SKILL 文件名（供日志 / IS_CHANGED 用；不用 → 不使用）"""
    m = skill_mode_of(skill_mode)
    if m == SKILL_MODE_OFF:
        return SKILL_NONE
    if m == SKILL_MODE_MANUAL:
        return _as_str(skill_name).strip() or SKILL_NONE
    return mode_skill_hint(preset_mode)


def effective_skill_text(skill_mode, skill_name, preset_mode, use_default_template=True):
    """本次实际要送进模型的 SKILL 全文（不用 / 缺模型 / 关内置模板 → 空串）"""
    if not bool(use_default_template):
        return ""
    name = effective_skill_name(skill_mode, skill_name, preset_mode)
    if not name or name == SKILL_NONE:
        return ""
    return _read_skill_text(name, "[XB-Qwen提示词预设]")


def safe_print(msg):
    """安全打印：控制台不是 UTF-8（如 Windows GBK 控制台）时把不可编码字符降级为 ? ，

    绝不因为一行带 emoji 的日志把节点执行搞崩（ComfyUI 官方启动器不一定切 UTF-8 代码页）。
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(str(msg).encode(enc, "replace").decode(enc, "replace"))


# ── 主流模型的空 latent 规格表（逐项抄自 ComfyUI：comfy/latent_formats.py + 官方空 latent 节点）──
# 选项文字 = 模型名（干净，不带专业参数；细节放 tooltip 与日志）；规格仍完整保留以保证对得上模型：
#   每行： (选项名, 通道数, 下采样除数_h, _w, 尺寸步长, 最小, 最大, batch上限, downscale_ratio_spacial)
#   · 尺寸步长 = 各模型**官方最小步长**（= 下采样 × patch2）：
#     Anima/Boogu/SDXL = 8（/8）、Flux2 = 16（/16）、Krea2/SD3/Z-image = 16（/8×patch2）、
#     Qwen-image = 32（用户指定：Qwen 系工作流习惯锁 32）、Hunyuan = 32（/32）。
#     不做全局统一的 32，避免把 1080 这类尺寸无谓地顶到 1088。
#   · downscale_ratio_spacial = 官方 EmptyLatentImage/EmptySD3 带回的元数据（供
#     comfy/sample.py:fix_empty_latent_channels 判断是否需要缩放尺寸）
_OFFICIAL_LATENT_ROWS = [
    ("Anima",       16, 8,  8,  8,  16, MAX_RESOLUTION, 4096, 8),
    ("Boogu",       16, 8,  8,  8,  16, MAX_RESOLUTION, 4096, 8),
    ("Flux2",      128, 16, 16, 16, 16, MAX_RESOLUTION, 4096, 16),
    ("Hunyuan",     64, 32, 32, 32, 64, MAX_RESOLUTION, 4096, 32),
    ("Krea2",       16, 8,  8,  16, 16, MAX_RESOLUTION, 4096, 8),
    ("Qwen-image",  16, 8,  8,  32, 32, MAX_RESOLUTION, 4096, 8),
    ("SD3",         16, 8,  8,  16, 16, MAX_RESOLUTION, 4096, 8),
    ("SDXL",        4,  8,  8,  8,  16, MAX_RESOLUTION, 4096, 8),
    ("Z-image",     16, 8,  8,  16, 16, MAX_RESOLUTION, 4096, 8),
]

LATENT_KINDS = [row[0] for row in _OFFICIAL_LATENT_ROWS]
LATENT_KIND_SPEC = {
    row[0]: {
        "label": row[0], "channels": row[1], "h_div": row[2], "w_div": row[3],
        "step": row[4], "min": row[5], "max": row[6], "batch_max": row[7],
        "downscale": row[8],
    }
    for row in _OFFICIAL_LATENT_ROWS
}
# 默认值固定为 Z-image（不随选项排序变化，保证老工作流/默认体验不变）
DEFAULT_LATENT_KIND = "Z-image"
# 各预设模式的默认预设句（可编辑字段 three_view_text 的默认值）：按「预设模式 × 输出语言」给。
# · 无预设 = 不前置设定词（原样输出正文，用户完全可控）
# · 人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明 = 成句时自动把预设句拼在正文前（中文「。」/英文 ". "）
PRESET_TEXT = {
    MODE_THREE_VIEW: {
        LANG_ZH: "生成平行排列的角色概念设计图，画面从左到右由四个独立面板组成："
                 "第一个面板是角色面部的精细特写肖像，第二个面板是人物正面全身站姿，"
                 "第三个面板是人物侧面全身站姿，第四个面板是人物背面全身站姿。",
        OUTPUT_LANGS[1]: "Generate a character concept design sheet arranged in parallel panels, "
                         "the image is composed of four separate panels from left to right: "
                         "the first panel is a finely detailed close-up portrait of the character's face, "
                         "the second panel is a full-body front standing pose, "
                         "the third panel is a full-body side standing pose, "
                         "the fourth panel is a full-body back standing pose.",
    },
    MODE_FOUR_VIEW: {
        LANG_ZH: "生成四宫格排列的角色概念设计图，画面左上角面板是角色面部的精细特写肖像，"
                 "画面右上角面板是角色面部侧面的的精细特写肖像，"
                 "画面左下角面板是无头部人物正面衣着展示图，画面右下角面板是人物背面全身站姿。",
        OUTPUT_LANGS[1]: "Generate a character concept design sheet arranged in a 2x2 grid, "
                         "the top-left panel is a finely detailed close-up portrait of the character's face, "
                         "the top-right panel is a finely detailed close-up profile portrait of the character's face, "
                         "the bottom-left panel is a headless front-facing outfit display view, "
                         "the bottom-right panel is a full-body back standing pose.",
    },
    MODE_FIVE_VIEW: {
        LANG_ZH: "生成五宫格排列的角色概念设计图，画面左上角面板是角色面部的精细特写肖像，"
                 "画面右上角面板是角色面部侧面的的精细特写肖像，"
                 "画面下方左侧面板是无头部人物正面衣着展示图，画面下方中间面板是无头部人物侧面衣着展示图，"
                 "画面下方右侧面板是人物背面全身站姿。",
        OUTPUT_LANGS[1]: "Generate a character concept design sheet arranged in five panels, "
                         "the top-left panel is a finely detailed close-up portrait of the character's face, "
                         "the top-right panel is a finely detailed close-up profile portrait of the character's face, "
                         "the bottom-left panel is a headless front-facing outfit display view, "
                         "the bottom-middle panel is a headless side-facing outfit display view, "
                         "the bottom-right panel is a full-body back standing pose.",
    },
    MODE_TRANSPARENT: {
        LANG_ZH: "生成一张具有透明度的 RGBA 格式图像，包含 Alpha 通道，背景为纯透明。",
        OUTPUT_LANGS[1]: "Generate an RGBA image with an alpha channel and a fully transparent background.",
    },
    MODE_UI: {
        LANG_ZH: "这是一张完整的平面版面设计图，画面边缘即版面边缘，全出血排版，无多余边框与水印。【版面结构】按层级自上而下组织：① 顶部信息区（标题栏/状态栏，界面类需含时间、信号、电量等图标）；② 主体内容区（卡片、栏位、区块，边距统一、圆角一致、层级分明、网格对齐）；③ 底部信息区（按钮、标签、脚注）。【文字】画面中所有文字必须逐字使用我给出的原文，不得增删改字，不得生成任何我未指定的文字；字体清晰端正、字号字重按层级区分，无错字无乱码无伪文字。【风格】排版精致、留白充足、有呼吸感，配色统一克制；任何元素都不得遮挡文字。",
        OUTPUT_LANGS[1]: "Produce one complete flat print layout: the image edge is the layout edge, full bleed, no extra frame or watermark. Structure top to bottom: (1) top information zone (title bar / status bar, with clock, signal and battery icons for UI); (2) main content zone (cards, columns and blocks with uniform margins, consistent corner radii, clear hierarchy, grid-aligned); (3) bottom information zone (buttons, tags, footnotes). All text must use my wording word for word, with no additions, deletions or substitutions, and no text I did not specify; crisp legible type, size and weight distinguished by hierarchy, no typos, no gibberish. Refined layout, generous breathing space, restrained unified palette; nothing may cover the text.",
    },
    MODE_INFO: {
        LANG_ZH: "这是一张信息图/科普拆解图，版式整洁、以信息可读性优先，具有教学与数据可视化气质。【版面】① 顶部标题栏（主标题 + 副标题/卷号/徽标）；② 主体由多个信息模块组成，按需包含：结构拆解图、局部放大详图、编号引线说明、图例、参数表、色卡、雷达图、时间轴、关键词云；③ 模块之间用细分割线或留白分隔，网格对齐、边距统一。【编号与引线】主体图形用圆形编号点标注，旁侧以细引线连接简短说明，编号连续、不重复、不跳号。【文字】所有文字逐字使用我给出的原文，不得生成任何我未指定的文字，无错字无乱码。",
        OUTPUT_LANGS[1]: "Produce an infographic / annotated explanation card: tidy layout, information legibility first, a teaching and data-visualisation feel. Layout: (1) a top title bar (main title plus subtitle, volume number or badge); (2) a body made of several information modules, optionally including a structural cutaway, zoomed detail views, numbered leader-line callouts, a legend, a parameter table, a colour swatch strip, a radar chart, a timeline and a keyword cloud; (3) modules separated by hairline rules or whitespace, grid-aligned with uniform margins. Numbering: mark the main graphic with circular numbered dots and connect short captions with thin leader lines; numbers are continuous and never repeated. All text must use my wording word for word, with no unspecified text, no typos, no gibberish.",
    },
    MODE_STORYBOARD: {
        LANG_ZH: "生成一张由多个连续分镜格组成的叙事插画，输出为一张完整拼合的扁平整图，不要输出多张分离图片。【版面硬性要求】① 格数与我要求一致，所有格等宽等高；② 严格按我要求的排布方式（单横排或网格），不得擅自拆格、并格或改行数；③ 每格是独立取景，格与格之间用细边框或清晰留白分隔；④ 每格左上角标注圆形数字编号，编号连续、不重复、不跳号不缺号。【内容硬性要求】每一格都必须画出主体本人在做该格的动作，主体清晰完整、占该格画面主体；严禁出现只有背景没有人物的空格；所有格的画风、光影、色彩与主体外观保持一致，仅姿势、表情、动作与场景变化。【文字】除编号外不要生成任何文字、字幕或水印。",
        OUTPUT_LANGS[1]: "Produce a narrative illustration made of several sequential storyboard panels, delivered as one fully composited flat sheet, not multiple separate files. Layout (mandatory): (1) exactly the panel count I ask for, all panels equal in width and height; (2) strictly the arrangement I ask for (single horizontal row or grid), never splitting, merging or re-flowing panels; (3) each panel is its own framing, separated by thin borders or clear gutters; (4) a circular number badge in the top-left of every panel, continuous, never repeated or skipped. Content (mandatory): every panel must show the subject itself performing that panel's action, clearly and completely, occupying the panel's main subject; never leave a panel with only background and no character; painting style, lighting, colour and the subject's look stay consistent across panels, only pose, expression, action and setting change. No text, captions or watermarks other than the numbers.",
    },
    MODE_ADBOARD: {
        LANG_ZH: "生成一张商业广告分镜板/脚本视觉板，像专业品牌团队制作的提案板：既有分镜画面，也带脚本信息。【版面】① 顶部标题区（项目名/产品名 + 副标题 + 品牌标识感排版）；② 主体横向排列若干连续分镜画面，每格独立取景、格间清晰分隔；③ 每格下方或侧方配栏目文字：镜头序号、时长或时间轴、镜头说明、字幕/台词、转场提示；④ 底部可放时间轴条与总时长。【风格】排版统一精致、配色克制高级，画面具有电影感与广告质感。【文字】画面中所有文字必须逐字使用我给出的原文，不得生成任何我未指定的文字，不得出现乱码、错字或伪文字。",
        OUTPUT_LANGS[1]: "Produce a commercial advertising storyboard / script visual board, like a real brand team's pitch board: storyboard frames plus script information. Layout: (1) a top title zone (project or product name, subtitle, brand-like typography); (2) a body of several sequential storyboard frames in a row, each its own framing with clear separation; (3) caption blocks under or beside each frame with shot number, duration or timeline, shot description, subtitle or dialogue and transition note; (4) an optional timeline bar and total duration at the bottom. Style: unified refined layout, restrained premium palette, cinematic advertising quality. All text must use my wording word for word, with no unspecified text, no gibberish and no fake typography.",
    },
    MODE_KEEP_SUBJECT: {
        LANG_ZH: "以输入图像中的主体为唯一依据：先完整识别它的全部外观细节，再把它放入新的场景中。【必须保持】主体的外形、比例、结构、材质、颜色、文字与标识、磨损与光泽等全部细节与新画面完全一致；不得改造、不得美化、不得替换、不得增减部件；主体是人物时保持面容、五官、发型、体型与肤色不变。【必须移除】输入图中的摄影棚背景、手持、支架、阴影底板等非主体元素，以及任何不属于最终画面的杂物。【新画面】按我的要求重建场景、构图、光线与景深；主体与新场景的光影、透视、色温自然统一，接触面有合理投影，看起来就是在该空间里真实拍摄的一张画面。",
        OUTPUT_LANGS[1]: "Treat the subject in the input image as the single source of truth: read every appearance detail first, then place it into a new scene. Must keep: shape, proportions, structure, material, colour, printed text and logos, wear and gloss identical to the input; do not redesign, beautify, replace, add or remove parts; for a person, keep face, features, hairstyle, build and skin tone. Must remove: studio backdrop, hands, stands, shadow board and any other non-subject elements or clutter. New frame: rebuild setting, composition, lighting and depth of field as I ask; the subject must match the new scene in light, perspective and colour temperature, sit on believable contact shadows, and look like a real photograph taken in that space.",
    },
    MODE_LOCAL_EDIT: {
        LANG_ZH: "只修改我指定或标记的区域，其余部分与输入图保持完全一致（包含构图、透视、光线、色调与清晰度）。【编辑范围】仅限我指定/标记的区域或部位；未标记的内容一律不得改动、不得重绘、不得重新打光、不得改变材质。【标记优先】若输入包含标记图、掩码图或涂抹标注，则以标注范围为准，只在该范围内操作。【过渡】修改区域与周边必须在材质、纹理与光影方向上自然衔接，边界不得出现生硬接缝、色块、描边或亮度跳变。【输出】只输出修改后的一整张完整画面，不要输出对比图、标注框、箭头或任何说明文字。",
        OUTPUT_LANGS[1]: "Change only the region or part I specify or mark; everything else stays exactly as in the input (composition, perspective, lighting, colour and sharpness). Scope: only my specified or marked region; anything unmarked must not be altered, repainted, relit or re-materialised. Marking wins: if the input includes an annotated, masked or painted region, operate strictly inside it. Blending: the edit must match its surroundings in material, texture and light direction, with no hard seams, colour patches, outlines or brightness jumps. Output one single finished image only, with no comparison view, boxes, arrows or explanatory text.",
    },
    MODE_RESTORE: {
        LANG_ZH: "把输入的老照片修复成清晰、自然、真实的彩色照片，并保持原照片的内容与人物五官解剖完全不变。【修复】去除噪点、划痕、斑点、折痕、褪色与颗粒，恢复细节与层次、平衡高光与阴影；不得过度锐化，不得出现塑料感、蜡感或油画涂抹感。【上色】按真实肤色与材质自然上色，色调统一可信，不做夸张调色。【保持】人物面部结构、皱纹、神态、视线、头部角度、手部与持物关系、服装材质与褶皱、背景陈设与景深关系均不得改变。【输出】只输出修复后的一整张完整画面，不加边框、不加文字或水印。",
        OUTPUT_LANGS[1]: "Restore the input vintage photograph into a sharp, natural, realistically colourised photo, keeping the original content and facial anatomy unchanged. Repair: remove noise, scratches, spots, creases, fading and grain; recover detail and tonal range and balance highlights and shadows; never oversharpen, never produce waxy, plastic or painterly skin. Colour: natural believable skin and material tones, unified grading, no exaggerated stylisation. Keep: facial structure, wrinkles, expression, gaze, head angle, hands and how they hold objects, garment material and folds, background props and depth of field. Output one single finished image with no border, text or watermark.",
    },
    MODE_STYLIZE: {
        LANG_ZH: "把输入图整张转换为指定的视觉媒介与画风，转换必须覆盖整幅画面，不得只做局部滤镜或只改一部分物体。【保持】原图的构图、画幅比例、视角、主体位置与姿态、景物之间的空间关系、已有文字与招牌的位置及可读内容不得改变；不得新增标语、字幕或水印。【转换】按我要求的画风重绘每一个物体：笔触、色层、材质表现与光色关系统一；光的方向与原图一致。【输出】只输出转换后的一整张完整画面。",
        OUTPUT_LANGS[1]: "Convert the whole input image into the requested visual medium and style; the conversion must cover the entire frame, not a local filter or only some objects. Keep: composition, aspect ratio, viewpoint, subject placement and pose, spatial relations between objects, and the position and legible content of existing signage and text; add no slogans, captions or watermarks. Convert: repaint every object in the requested style with consistent brushwork, colour layering, material rendering and light-colour relationships; light direction matches the original. Output one single converted image.",
    },
    MODE_PANO360: {
        LANG_ZH: "把输入的单视角照片扩展成一张完整的 360 度全景图。【投影】使用真正的等距圆柱投影（equirectangular），水平覆盖 360 度、垂直覆盖 180 度，包含头顶天空与脚下地面；左右两端无缝衔接，形成一张连续完整的场景。【补全】以输入图为基础，把相机背后的环境合理延伸（地面、墙体、植被、天空，光照方向一致），不得出现重复、断裂或接缝。【保持】输入图中的主体只出现一次，其外观、姿态以及与周围景物的相对关系保持原样，不得镜像或复制。【输出】严格 2:1 画幅比例，例如 2880x1440。",
        OUTPUT_LANGS[1]: "Extend the input single-view photograph into a complete 360-degree panorama. Projection: true equirectangular, covering 360 degrees horizontally and 180 degrees vertically, including the sky overhead and the ground below; left and right edges must join seamlessly into one continuous scene. Completion: extend the environment behind the camera plausibly (ground, walls, vegetation, sky, consistent light direction) with no repeated or broken areas. Keep: the subject appears exactly once, with its appearance, pose and relationship to surrounding objects unchanged, never mirrored or duplicated. Output at exactly a 2:1 aspect ratio, for example 2880x1440.",
    },
    MODE_MULTI_REF: {
        LANG_ZH: "按图号使用我提供的多张参考图，合成一张全新画面。【指认规则】场景与环境取自我指定的那一张图；其余各图分别提供角色外观或物件本体；我未指认的图不参与画面。【保持】被引用的角色保持面容、发型与体型一致；被引用的物件保持形状、材质、颜色与标识文字一致；不得替换、美化或增减部件。【重建】按我的要求安排构图、站位、光线与景深，所有元素统一在同一空间的光影与透视中，接触关系与投影合理。【文字】除我明确要求的外，不生成任何文字或水印。",
        OUTPUT_LANGS[1]: "Use the reference images I provide by their index numbers and composite one brand-new image. Mapping: the scene and environment come from the image I designate; the other images supply either character likeness or an object itself; images I do not reference do not appear. Keep: referenced characters keep the same face, hairstyle and build; referenced objects keep the same shape, material, colour and printed text; no replacement, beautifying, additions or removals. Rebuild: arrange composition, staging, lighting and depth of field as I ask; all elements share one consistent space with matching light, perspective, contact and shadows. No text or watermark unless I explicitly ask for it.",
    },
}

# 兼容旧引用（三视图预设句）
THREE_VIEW_TEXT = PRESET_TEXT[MODE_THREE_VIEW]

# ============================================================================
# 配置读写（None / 缺字段 / 非法值一律安全兜底）
# ============================================================================
def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _as_str(value, default=""):
    return value if isinstance(value, str) else default


def _pick(options, value, default):
    """把配置值归一到合法枚举（缺失/None/非法 → default）。"""
    v = _as_str(value).strip()
    return v if v in options else default


# ============================================================================
# 画幅比例 + 步长联动（与 XB_ImageParamsMaster.process 逐行等价）
# ============================================================================
def _round_step(value, step=SIZE_STEP, min_size=SIZE_MIN, max_size=MAX_RESOLUTION):
    """按 step 四舍五入并钳制上下限。

    ⚠️ 必须用 `floor(x + 0.5)` 而不是 Python 内置 `round()`：
    Python 的 round 是「银行家舍入」（round-half-to-even，`round(62.5) == 62`），
    而前端用的是 JS `Math.round`（`Math.round(62.5) == 63`，四舍五入）。
    两者在 x.5 处会差一个步长（1000px → Python 992 / JS 1008），会让节点表面与
    执行结果不一致（同一工作流重跑一次尺寸就变）。这里统一按 JS 语义，保证所见即所得。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = step
    if v != v:  # NaN
        v = step
    n = int(math.floor(v / step + 0.5)) * step
    return max(min_size, min(max_size, n))


def latent_kind_spec(label):
    """下拉值 → 官方规格 dict（未知值/缺省/None → 默认 4 通道，老工作流不会崩）。"""
    return LATENT_KIND_SPEC.get(str(label or ""), LATENT_KIND_SPEC[DEFAULT_LATENT_KIND])


def latent_step_of(label):
    """该空 latent 类型的尺寸步长（前端画幅联动用同一套值）。"""
    return int(latent_kind_spec(label)["step"])


def latent_shape_of(label, width, height, batch_size=1):
    """该模型下最终 latent 张量形状（元组；只用于日志与自测，不参与计算）。"""
    spec = latent_kind_spec(label)
    w = _round_step(width, spec["step"], spec["min"], spec["max"])
    h = _round_step(height, spec["step"], spec["min"], spec["max"])
    b = max(1, min(spec["batch_max"], int(batch_size or 1)))
    return (b, spec["channels"], max(1, h // spec["h_div"]), max(1, w // spec["w_div"]))


def normalize_size(aspect_ratio, width, height, step=SIZE_STEP,
                   min_size=SIZE_MIN, max_size=MAX_RESOLUTION):
    """按画幅比例归一宽高：Free 只做步长锁定；固定比例以「输入中较大的一边」为基准反算另一边。

    与前端 js/xb_image_prompt_preset.js 的 snapFromWidth/snapFromHeight 结果一致（幂等）：
    前端负责「按你正在改的那一边为基准」即时联动，后端只做无方向归一，两者对已联动过的
    数值不产生二次改动。step/min/max 由当前空 latent 类型决定（官方各节点步长并不相同）。
    """
    w = _round_step(width, step, min_size, max_size)
    h = _round_step(height, step, min_size, max_size)
    if "Free" in _as_str(aspect_ratio):
        return w, h
    ratio = ASPECT_RATIO_MAP.get(_as_str(aspect_ratio).strip())
    if not ratio:
        return w, h
    if w >= h:
        safe_w = w
        safe_h = _round_step(safe_w / ratio, step, min_size, max_size)
    else:
        safe_h = h
        safe_w = _round_step(safe_h * ratio, step, min_size, max_size)
    return safe_w, safe_h


def build_empty_latent(latent_kind, width, height, batch_size=1):
    """主流模型的空 latent（形状/下采样/步长/上下限逐项对齐官方 latent_format）。

    形状恒为 [B, C, H//h_div, W//w_div]，并带回 `downscale_ratio_spacial`（官方
    EmptyLatentImage / EmptySD3LatentImage 同款元数据），让
    `comfy/sample.py:fix_empty_latent_channels` 能正确判断尺寸是否需要缩放：
      · 尺寸与模型声明一致 → 不缩放；选错类型则按比例自动缩放（全零 latent 可自由转换）
      · 通道数不一致时官方会把零通道 repeat 到模型通道数 → 选错也不会崩
    零张量 dtype 不影响结果（采样器统一 cast），统一用 intermediate_device。
    """
    spec = latent_kind_spec(latent_kind)
    step, min_size, max_size = spec["step"], spec["min"], spec["max"]
    w = _round_step(width, step, min_size, max_size)
    h = _round_step(height, step, min_size, max_size)
    b = max(1, min(int(spec["batch_max"]), int(batch_size or 1)))
    z = torch.zeros(
        [b, int(spec["channels"]),
         max(1, h // int(spec["h_div"])), max(1, w // int(spec["w_div"]))],
        device=comfy.model_management.intermediate_device(),
    )
    out = {"samples": z}
    if spec["downscale"]:
        out["downscale_ratio_spacial"] = int(spec["downscale"])
    return out


# ============================================================================
# 提示词拼装
# ============================================================================
# 兼容：早期版本档位名带表情 / 旧名（工作流里可能存着旧值）→ 归一为当前档位名，避免静默回落
MODE_ALIASES = {
    "常规文生图": "无预设",          # 0.10.x 旧名 → 新名（语义完全一致）
    "📱 图文版面": "图文版面",
    "📊 信息图": "信息图",
    "🎞 多格分镜": "多格分镜",
    "🎬 广告分镜板": "广告分镜板",
    "🛍 保持主体换场景": "保持主体换场景",
    "✏️ 局部编辑": "局部编辑",
    "🧹 老照片修复": "老照片修复",
    "🎨 整图风格化": "整图风格化",
    "🌐 360°全景": "360°全景",
    "🗂 多图指认合成": "多图指认合成",
}

def normalize_mode(preset_mode):
    """把各种历史/非法值归一为当前档位名（认不出来就保持原样，由上层 _pick 兜底）"""
    m = _as_str(preset_mode).strip()
    return MODE_ALIASES.get(m, m)


# ═══════════════════════════════════════════════════════════════
#  t2i / i2i 两套模版：按「有没有接输入图」自动选用（自测会断言与前端 JS 逐字一致）
# ═══════════════════════════════════════════════════════════════

# 文生图档（图文版面 / 信息图 / 多格分镜 / 广告分镜板 / 三·四·五视图 / 背景纯透明）
# **接了输入图**时追加：以输入图为准，规格只作用于组织与重建
IO_I2I_COMMON = {LANG_ZH: "【本次接了输入图】以输入图为唯一依据：保持输入图中被保留部分的原样不变（人物保持面容、发型、体型与气质；物件保持外形、比例、材质、颜色与文字标识），不得改动、美化、替换或增减我未指定的部分；本档规格只作用于画面的组织与重建区域。", OUTPUT_LANGS[1]: "Attached input image(s) are the single source of truth: keep everything kept from them unchanged — for people: face, hairstyle, build and character; for objects: shape, proportions, material, colour and printed text — and never alter, beautify, replace, add or remove anything I did not ask for. This mode's spec only governs how the frame is organised and rebuilt."}

# ── 模版：文生图 / 图生图（决定用哪一份「设定词」）─────────────────────────
# · 自动 = 按有没有接参考图判断（没接 → 文生图，接了 → 图生图）
# · 每个预设模式都有「文生图」与「图生图」两份设定词：
#     图生图档（6 档）的原始文本就是图生图版，下面 PRESET_TEXT_T2I 是它的文生图版；
#     文生图档（8 档）的原始文本就是文生图版，「图生图」版 = 原文 + IO_I2I_COMMON 条款。
IO_MODE_AUTO = "自动"
IO_MODE_T2I = "文生图"
IO_MODE_I2I = "图生图"
IO_MODES = [IO_MODE_AUTO, IO_MODE_T2I, IO_MODE_I2I]


def io_mode_of(value):
    """归一模版参数（缺失 / None / 非法 → 自动）"""
    m = _as_str(value).strip()
    return m if m in IO_MODES else IO_MODE_AUTO


def resolve_io_mode(io_mode, has_image):
    """把「自动」按有没有接参考图解析成 文生图 / 图生图"""
    m = io_mode_of(io_mode)
    if m == IO_MODE_T2I:
        return IO_MODE_T2I
    if m == IO_MODE_I2I:
        return IO_MODE_I2I
    return IO_MODE_I2I if has_image else IO_MODE_T2I


def mode_default_io(preset_mode):
    """没接图也没显式指定时该档的默认模版（图生图档默认图生图，其余默认文生图）"""
    return IO_MODE_I2I if mode_needs_image(preset_mode) else IO_MODE_T2I


# 图生图档的「文生图版」设定词（zh/en 各一份；与 PRESET_TEXT 里的图生图版一一对应）
PRESET_TEXT_T2I = {
    MODE_KEEP_SUBJECT: {
        LANG_ZH: "生成一张主体清晰的画面：先完整确定主体的全部外观细节，再把它放进我要求的新场景中。"
                 "【必须保持】主体的外形、比例、结构、材质、颜色、文字与标识、磨损与光泽等全部细节前后一致、"
                 "符合真实物理；不得改造、不得美化、不得替换、不得增减部件；主体是人物时保持面容、五官、"
                 "发型、体型与肤色自然可信。【必须干净】画面中不得出现摄影棚背景、手持、支架、阴影底板等杂物，"
                 "也不得有任何不属于最终画面的元素。【新画面】按我的要求营造场景、构图、光线与景深；"
                 "主体与新场景的光影、透视、色温自然统一，接触面有合理投影，"
                 "看起来就是在该空间里真实拍摄的一张画面。",
        OUTPUT_LANGS[1]: "Generate a frame with a clearly defined subject: first settle every appearance detail of the subject, "
                         "then place it into the new scene I ask for. Must keep: shape, proportions, structure, material, "
                         "colour, printed text and logos, wear and gloss stay self-consistent and physically believable; "
                         "do not redesign, beautify, replace, add or remove parts; for a person, keep face, features, "
                         "hairstyle, build and skin tone natural and convincing. Must be clean: no studio backdrop, hands, "
                         "stands, shadow board or any element that does not belong in the final frame. New frame: build the "
                         "setting, composition, lighting and depth of field as I ask; the subject must match the scene in "
                         "light, perspective and colour temperature, sit on believable contact shadows, and look like a real "
                         "photograph taken in that space.",
    },
    MODE_LOCAL_EDIT: {
        LANG_ZH: "生成一张完整画面，并把我的改动直接做进画面里。【改动范围】只按我的要求改我指定的部位，"
                 "其余内容保持稳定一致：不得顺手重绘、不得重新打光、不得改变材质与配色。"
                 "【过渡】改动区域与周边必须在材质、纹理与光影方向上自然衔接，"
                 "边界不得出现生硬接缝、色块、描边或亮度跳变。【输出】只输出最终的一整张完整画面，"
                 "不要输出对比图、标注框、箭头或任何说明文字。",
        OUTPUT_LANGS[1]: "Generate one complete frame with my change built directly into the image. Scope: change only the part "
                         "I ask for; keep everything else stable and consistent — do not incidentally repaint, relight, or "
                         "alter materials and palette. Blending: the changed area must match its surroundings in material, "
                         "texture and light direction, with no hard seams, colour patches, outlines or brightness jumps. "
                         "Output one single finished frame only, with no comparison view, boxes, arrows or explanatory text.",
    },
    MODE_RESTORE: {
        LANG_ZH: "直接生成一张清晰、自然、细节完整的照片，并带有老照片翻新后的质感。【画面】主体与场景按我的描述生成，"
                 "人物面部结构、五官解剖与比例自然准确，手部与持物关系合理。【修复感】不要噪点、划痕、斑点、折痕、"
                 "褪色与颗粒，细节与层次完整、高光与阴影平衡；不得过度锐化，不得出现塑料感、蜡感或油画涂抹感。"
                 "【色彩】按真实肤色与材质自然上色，色调统一可信，不做夸张调色。【输出】只输出一整张完整画面，"
                 "不加边框、不加文字或水印。",
        OUTPUT_LANGS[1]: "Generate directly a sharp, natural, fully detailed photograph with the look of a restored vintage print. "
                         "Frame: build the subject and setting from my description, with natural accurate facial structure, "
                         "anatomy and proportions, and believable hands and grip. Restoration feel: no noise, scratches, spots, "
                         "creases, fading or grain; complete detail and tonal range, balanced highlights and shadows; never "
                         "oversharpen, never produce waxy, plastic or painterly skin. Colour: natural believable skin and "
                         "material tones, unified grading, no exaggerated stylisation. Output one single finished image with no "
                         "border, text or watermark.",
    },
    MODE_STYLIZE: {
        LANG_ZH: "生成一张完整的全新画面，并整体转换成我要求的视觉媒介与画风，转换必须覆盖整幅画面，"
                 "不得只做局部滤镜或只改一部分物体。【画面】构图、画幅比例、视角与主体由我的描述决定，"
                 "主体位置与姿态清晰合理。【转换】画面里的每一个物体都按该画风重绘：笔触、色层、材质表现与"
                 "光色关系统一；光的方向明确一致。【文字】除我明确要求的外不生成任何文字、标语、字幕或水印。"
                 "【输出】只输出一整张完整画面。",
        OUTPUT_LANGS[1]: "Generate one complete new frame and convert the whole of it into the requested visual medium and style; "
                         "the conversion must cover the entire frame, not a local filter or only some objects. Frame: "
                         "composition, aspect ratio, viewpoint and subject come from my description, with the subject clearly "
                         "and plausibly placed and posed. Convert: repaint every object in that style with consistent "
                         "brushwork, colour layering, material rendering and light-colour relationships; keep one clear light "
                         "direction. Text: no text, slogans, captions or watermarks unless I explicitly ask for them. Output "
                         "one single complete frame.",
    },
    MODE_PANO360: {
        LANG_ZH: "生成一张完整的 360 度全景图。【投影】使用真正的等距圆柱投影（equirectangular），"
                 "水平覆盖 360 度、垂直覆盖 180 度，包含头顶天空与脚下地面；左右两端无缝衔接，"
                 "形成一张连续完整的场景。【补全】以输入图为基础，把相机背后的环境合理延伸"
                 "（地面、墙体、植被、天空，光照方向一致），不得出现重复、断裂或接缝。"
                 "【保持】输入图中的主体只出现一次，其外观、姿态以及与周围景物的相对关系保持原样，"
                 "不得镜像或复制。【输出】严格 2:1 画幅比例，例如 2880x1440。",
        OUTPUT_LANGS[1]: "Generate a complete 360-degree panorama. Projection: true equirectangular, covering 360 degrees "
                         "horizontally and 180 degrees vertically, including the sky overhead and the ground below; left and "
                         "right edges must join seamlessly into one continuous scene. Completion: extend the environment behind "
                         "the camera plausibly (ground, walls, vegetation, sky, consistent light direction) with no repeated or "
                         "broken areas. Keep: the subject appears exactly once, with its appearance, pose and relationship to "
                         "surrounding objects unchanged, never mirrored or duplicated. Output at exactly a 2:1 aspect ratio, for "
                         "example 2880x1440.",
    },
    MODE_MULTI_REF: {
        LANG_ZH: "直接按我的描述生成一张全新画面。【画面】按我的要求安排主体、场景、构图、站位、光线与景深，"
                 "所有元素统一在同一空间的光影与透视中，接触关系与投影合理。【一致性】同一主体在各处的外观"
                 "保持一致，不得替换、美化或增减部件。【文字】除我明确要求的外，不生成任何文字或水印。",
        OUTPUT_LANGS[1]: "Generate one brand-new image directly from my description. Frame: arrange subjects, setting, "
                         "composition, staging, lighting and depth of field as I ask; all elements share one consistent space "
                         "with matching light, perspective, contact and shadows. Consistency: keep each subject's look "
                         "identical everywhere, with no replacement, beautifying, additions or removals. Text: no text or "
                         "watermark unless I explicitly ask for it.",
    },
}


def preset_text_for(preset_mode, output_lang=None, io_mode=None):
    """某预设模式在指定模版下的**默认**设定词（无预设 → 永远 ""）。

    io_mode 可传「自动」（按该档默认）、「文生图」或「图生图」。
    · 无预设：无论接不接图、哪个模版 → **都是空**（不前置任何设定词，也不加「以输入图为准」条款）
    · 文生图模版：图生图档 → PRESET_TEXT_T2I；其余文生图档 → PRESET_TEXT
    · 图生图模版：图生图档 → PRESET_TEXT；其余文生图档 → PRESET_TEXT + IO_I2I_COMMON 条款
    """
    mode = normalize_mode(preset_mode)
    lg = output_lang if output_lang in OUTPUT_LANGS else LANG_ZH
    if not mode or mode == MODE_TEXT2IMG:
        return ""
    texts = PRESET_TEXT.get(mode, {})
    io = io_mode_of(io_mode)
    if io == IO_MODE_AUTO:
        io = mode_default_io(mode)
    if io == IO_MODE_T2I:
        return PRESET_TEXT_T2I.get(mode, texts).get(lg, texts.get(lg, ""))
    txt = texts.get(lg, "")
    if mode in MODE_NEEDS_IMAGE:
        return txt
    clause = IO_I2I_COMMON.get(lg, "")
    return (txt + " " + clause).strip() if txt else clause


def all_default_texts(preset_mode):
    """该模式**所有模版 × 所有语言**的默认设定词（用于判断用户是否没改过 → 见 preset_text_of）

    · 无预设档额外算「默认」的还有：IO_I2I_COMMON 条款（早期版本在「图生图模版」下把它当
      设定词写进了 widget / 存档）+ **所有内置预设句**（节点上 three_view_text 的老默认值就是
      三视图预设句 → 无预设档必须把它当空白，不能当成用户的「自定义」继续前置）。
    """
    out = []
    for lg in OUTPUT_LANGS:
        for io in (IO_MODE_T2I, IO_MODE_I2I):
            t = preset_text_for(preset_mode, lg, io).strip()
            if t:
                out.append(t)
        if normalize_mode(preset_mode) == MODE_TEXT2IMG:
            c = _as_str(IO_I2I_COMMON.get(lg, "")).strip()
            if c:
                out.append(c)
    if normalize_mode(preset_mode) == MODE_TEXT2IMG:
        for table in (PRESET_TEXT, PRESET_TEXT_T2I):
            for texts in table.values():
                for t in texts.values():
                    t = _as_str(t).strip()
                    if t and t not in out:
                        out.append(t)
    return out


def preset_text_of(preset_mode, output_lang, three_view_text, io_mode=None, has_image=False):
    """最终生效的设定词：用户改过的优先；没改过（等于任一默认）则按当前模版取默认。

    ⚠️ 为什么要判「没改过」：老工作流里 widget 存的是**另一套模版**的默认文本
    （例如没接图但存着 360°全景 的图生图版）→ 直接照用就会把「把输入的单视角照片扩展成…」
    送进文生图，用户看到的正是这个 bug。
    """
    txt = _as_str(three_view_text).strip()
    io = resolve_io_mode(io_mode, has_image)
    now = preset_text_for(preset_mode, output_lang, io)
    if not txt:
        return now
    for cand in all_default_texts(preset_mode):
        if txt == cand:
            return now
    return txt


def mode_io_clause(preset_mode, has_image, output_lang=None):
    """该档在「当前有没有接图」下需要追加的条款（仅「文生图档 + 有图」 → 以输入图为准；其余 → ""）

    ⚠️ 无预设档（MODE_TEXT2IMG）永远返回""：用户要求「接不接图，无预设的设定词都是空白」。
    """
    lg = output_lang if output_lang in OUTPUT_LANGS else LANG_ZH
    m = normalize_mode(preset_mode)
    if not m or m == MODE_TEXT2IMG or mode_needs_image(m):
        return ""
    return IO_I2I_COMMON.get(lg, "") if has_image else ""


def with_io_clause(preset_text, preset_mode, has_image, output_lang=None):
    """把模版条款追加到设定词上（仅文生图档 + 有图；其余原样）"""
    clause = mode_io_clause(preset_mode, has_image, output_lang)
    t = _as_str(preset_text).strip()
    if not clause:
        return t
    return (t + " " + clause).strip() if t else clause


def build_prompt(lang, preset_mode, three_view_text, body, has_image=None, io_mode=None):
    """设定词 + 正文，按输出语言使用合适的分句符。

    · 正文 = 节点表面提示词框（也等于面板预览框，两者双向同步）；
    · 设定词 = preset_text_of(...)：改过的用改过的，没改过则按「当前模版（文生图/图生图）」取默认；
    · 无预设档：接不接图、哪个模版 → 设定词都是空串（只输出正文）；
    · has_image=None（基础节点不传）时按文生图处理，行为与旧版一致。
    """
    core = (body if isinstance(body, str) else "").strip()
    mode = _pick(PRESET_MODES, preset_mode, PRESET_MODES[0])
    lg = _pick(OUTPUT_LANGS, lang, LANG_ZH)
    preset = preset_text_of(mode, lg, three_view_text, io_mode=io_mode,
                            has_image=bool(has_image))
    if not preset:
        return core
    if not core:
        return preset
    if lg == OUTPUT_LANGS[1]:
        return preset.rstrip(".").rstrip() + ". " + core
    return preset.rstrip("。．.").rstrip() + "。" + core


# ============================================================================
# 节点
# ============================================================================
from .xb_skills import SKILL_NONE as _SKILL_NONE
from .xb_skills import skill_list as _skill_lister
from .xb_skills import skill_path as _skill_pather
from .xb_skills import skill_sig as _skill_signer
from .xb_skills import skill_text as _read_skill_text

DEFAULT_LANG = OUTPUT_LANGS[0]
# 用户要求：本节点的空latent类型默认 Qwen-image（与节点定位一致）
DEFAULT_LATENT = "Qwen-image" if "Qwen-image" in LATENT_KINDS else DEFAULT_LATENT_KIND

# ══════════════════════════════════════════════════════════════
#  SKILL（技能文件 = 官方 Generate Text 的 system_prompt）
#  读取器在 xb_skills.py（与「生图提示词预设Pro」共用一份）
# ══════════════════════════════════════════════════════════════

SKILL_NONE = _SKILL_NONE                       # combo 第一项 = 不接技能（与旧工作流行为一致）


def skill_list():
    return _skill_lister()


def _skill_path(name):
    return _skill_pather(name)


def _skill_sig(name):
    return _skill_signer(name)


def _skill_text(name):
    return _read_skill_text(name, "[XB-Qwen提示词预设]")

# ═══════════════════════════════════════════════════════════════
#  官方节点参数表（逐字复制，升级 ComfyUI 后如果官方枚举变了只需改这里）
# ═══════════════════════════════════════════════════════════════

# nodes.py::CLIPLoader 的 type 枚举
CLIP_TYPES = [
    "stable_diffusion", "stable_cascade", "sd3", "stable_audio", "mochi", "ltxv", "pixart",
    "cosmos", "lumina2", "wan", "hidream", "chroma", "ace", "omnigen2", "qwen_image",
    "hunyuan_image", "flux2", "ovis", "longcat_image", "cogvideox", "lens", "pixeldit",
    "ideogram4", "boogu", "krea2", "joyimage", "mage", "minimax", "yue2",
]
DEFAULT_CLIP_TYPE = "qwen_image"     # 用户要求：类型默认 Qwen_image
CLIP_DEVICES = ["default", "cpu"]    # nodes.py::CLIPLoader 的 device 枚举
DEFAULT_DEVICE = "default"           # 用户要求：设备默认 default

# comfy_extras/nodes_textgen.py::TextGenerate 的参数
SAMPLING_MODES = ["on", "off"]
MTP_MODES = ["auto", "off", "2", "3", "4", "5"]
_SEED_MAX = 0xFFFFFFFFFFFFFFFF

# 输出语言提示（拼进送模型的 prompt；本节点不依赖其它模块，自己留一份）
_LANG_HINT = {
    "中文 [ZH]": "【输出语言】请始终使用中文输出。",
    "英文 [EN]": "【Output language】Always respond in English.",
}

_SETTING_KEYS = ("latent_kind", "output_lang", "preset_mode", "io_mode", "three_view_text", "aspect_ratio",
                 "width", "height", "batch_size", "clip_name", "clip_type", "device",
                 "max_length", "sampling_mode", "temperature", "top_k", "top_p", "min_p",
                 "repetition_penalty", "presence_penalty", "seed", "thinking",
                 "use_default_template", "mtp", "skill_name", "skill_mode", "internal_prompt")


def text_encoder_list():
    """官方 Load CLIP 的模型列表（models/text_encoders）"""
    try:
        return folder_paths.get_filename_list("text_encoders")
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
#  配置解析（None / 缺失 / 非法一律安全回落）
# ═══════════════════════════════════════════════════════════════

DEFAULT_SETTINGS = {
    "extra_settings": "",                       # 追加设定
}


def parse_settings(raw):
    """manager_settings（JSON 字符串 / 字典 / None）→ 完整配置

    配置段在 `manager_settings.qwen` 下（与前端 xbrParseQwen / xbrSaveJson 对齐）；
    为兼容早期写在顶层的写法，两处都读，qwen 优先。
    ⚠️ `extra_settings`（追加设定）的**面板入口已按用户要求删除**，这里保留读取只为兼容
       旧工作流里已经填过的值（新节点永远是空串，等于不追加【额外要求】）。
    """
    data = {}
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    sec = data.get("qwen") if isinstance(data.get("qwen"), dict) else {}
    extra = sec.get("extra_settings")
    if extra is None:
        extra = data.get("extra_settings")      # 兼容：早期版本写在顶层
    return {"extra_settings": str(extra or "")}


def _file_sig(name):
    """模型文件的 大小 + 修改时间（换文件即失效，不必手动清缓存）"""
    try:
        path = folder_paths.get_full_path("text_encoders", name)
        if not path:
            return ""
        import os
        st = os.stat(path)
        return f"{st.st_size}:{int(st.st_mtime)}"
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
#  提示词组装（与「生图提示词预设」一致：设定词原封不动置顶）
# ═══════════════════════════════════════════════════════════════

def _preset_text_of(preset_mode, output_lang, three_view_text, io_mode=None, has_image=False):
    """当前预设模式的设定词（按模版分两套）

    · 用户改过 → 用改过的；
    · 没改过（等于任一默认）→ 按当前模版（文生图 / 图生图）取默认，
      避免老工作流把「图生图版」文本（如 360°全景 的「把输入的单视角照片扩展成…」）带进文生图。
    """
    return preset_text_of(preset_mode, output_lang, three_view_text,
                          io_mode=io_mode, has_image=has_image)


def build_model_prompt(body, preset_text, extra_settings, output_lang, with_lang_hint=True):
    """送给 Generate Text 的 prompt：「参考设定 + 正文 + 额外要求」三段式

    `with_lang_hint=False`（选中了 SKILL 时）不叠加语言提示——技能文件自带语言决策，
    再叠一条「始终用中文」会直接违背技能（与「生图提示词预设Pro」的处理一致）。
    """
    parts = []
    ref = (preset_text or "").strip()
    if ref:
        parts.append("【参考设定】\n" + ref
                     + "\n（上面这段设定会被原样加在最终提示词最顶端，不需要你复述或改写它）")
    parts.append("【正文】\n" + ((body or "").strip() or ""))
    extra = (extra_settings or "").strip()
    if extra:
        parts.append("【额外要求】\n" + extra)
    if with_lang_hint:
        parts.append(_LANG_HINT.get(output_lang, _LANG_HINT[DEFAULT_LANG]))
    return "\n\n".join([p for p in parts if p])


# ═══════════════════════════════════════════════════════════════
#  CLIP 加载（逐行对齐官方 nodes.py::CLIPLoader）+ 单条缓存
# ═══════════════════════════════════════════════════════════════

_CLIP_CACHE = {"key": None, "clip": None}


def _load_clip(clip_name, clip_type, device):
    clip_type_value = getattr(comfy.sd.CLIPType, str(clip_type).upper(), comfy.sd.CLIPType.STABLE_DIFFUSION)
    model_options = {}
    if device == "cpu":
        model_options["load_device"] = model_options["offload_device"] = torch.device("cpu")
    clip_path = folder_paths.get_full_path_or_raise("text_encoders", clip_name)
    return comfy.sd.load_clip(
        ckpt_paths=[clip_path],
        embedding_directory=folder_paths.get_folder_paths("embeddings"),
        clip_type=clip_type_value,
        model_options=model_options,
    )


def get_clip(clip_name, clip_type, device):
    """取 CLIP：同参数复用缓存，换参数才重新加载（只留 1 份，避免显存里堆一堆文本编码器）"""
    key = (str(clip_name or ""), str(clip_type or ""), str(device or ""))
    if _CLIP_CACHE["clip"] is not None and _CLIP_CACHE["key"] == key:
        return _CLIP_CACHE["clip"]
    if not key[0]:
        raise ValueError(
            "[XB-Qwen提示词预设] 未找到文本编码器模型\n"
            "请把文本编码器（例如 Qwen-Image 的 text encoder）放进 ComfyUI/models/text_encoders，\n"
            "再点节点上的「🤖 LLM设置」→ 模型选择 里选它。"
        )
    if _CLIP_CACHE["clip"] is not None:
        _CLIP_CACHE["clip"] = None
        gc.collect()
        try:
            import comfy.model_management
            comfy.model_management.soft_empty_cache()
        except Exception:
            pass
    clip = _load_clip(key[0], key[1], key[2])
    _CLIP_CACHE["key"] = key
    _CLIP_CACHE["clip"] = clip
    return clip


# ═══════════════════════════════════════════════════════════════
#  节点
# ═══════════════════════════════════════════════════════════════

class XB_QwenPromptPreset:
    """Qwen2.1提示词预设：生图预设（提示词拼装 + 空latent）+ 官方 Load CLIP + 官方 Generate Text。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # ══ ① 生图预设（与「🖼️ 生图提示词预设」一致）══
                "latent_kind": (list(LATENT_KINDS), {
                    "default": DEFAULT_LATENT,
                    "tooltip": "空latent类型：选你正在用的模型即可（自动适配形状/下采样/步长）",
                }),
                "output_lang": (list(OUTPUT_LANGS), {
                    "default": DEFAULT_LANG,
                    "tooltip": "输出语言：决定词表与设定词按哪种语言加载、生成文本的语言",
                }),
                "io_mode": (list(IO_MODES), {
                    "default": IO_MODE_AUTO,
                    "tooltip": "模版：自动 = 按有没有接参考图判断；文生图 / 图生图 = 手动指定。"
                               "每个预设模式都有两套设定词，按它自动选用（模板切换会直接把设定词换成对应那套）",
                }),
                "preset_mode": (list(PRESET_MODES), {
                    "default": PRESET_MODES[0],
                    "tooltip": "预设模式：无预设=不前置任何设定词，只输出正文；其余档位把该档设定词置顶到最终提示词最顶端（设定词分文生图 / 图生图两套）",
                }),
                "three_view_text": ("STRING", {
                    "default": THREE_VIEW_TEXT[DEFAULT_LANG], "multiline": True,
                    "tooltip": "设定词：预设模式对应的设定文本；改过的按「模式 + 语言」记进节点，换模式 / 换语言都不会丢",
                }),
                "skill_mode": (list(SKILL_MODES), {
                    "default": SKILL_MODE_AUTO,
                    "tooltip": "SKILL 模式：自动 = 按预设模式适配（图生图档 → prompt_edit，其余 → prompt_t2i）；"
                               "手动 = 用下面选中的那一个；不用 = SKILL 完全不生效（哪怕选了也不生效）",
                }),
                "skill_name": (skill_list(), {
                    "default": SKILL_NONE,
                    "tooltip": "SKILL选择：support_llama/skills 里的 txt，整段作为模型自带的系统提示词（官方 Generate Text 的 system_prompt）；"
                               "仅在「SKILL 模式 = 手动」时生效；「使用内置模板」关闭时也不生效",
                }),
                "aspect_ratio": (list(ASPECT_RATIO_OPTIONS), {
                    "default": "Free",
                    "tooltip": "画幅比例：Free=自由（仅按步长锁定）；固定比例时按较大的一边反算另一边",
                }),
                "width": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION, "step": SIZE_STEP,
                    "tooltip": "图片宽度（步长按「空latent类型」的官方最小步长 8/16/32）",
                }),
                "height": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION, "step": SIZE_STEP,
                    "tooltip": "图片高度（步长按「空latent类型」的官方最小步长 8/16/32）",
                }),
                "batch_size": ("INT", {
                    "default": 1, "min": 1, "max": BATCH_MAX,
                    "tooltip": "一次生成的图片数量（空 latent 的 batch 维度）",
                }),

                # ══ ② 官方 Load CLIP（模型选择）══
                "clip_name": (text_encoder_list(), {
                    "tooltip": "文本编码器（models/text_encoders）。与官方 Load CLIP 同一个列表。",
                }),
                "clip_type": (list(CLIP_TYPES), {
                    "default": DEFAULT_CLIP_TYPE,
                    "tooltip": "类型：与官方 Load CLIP 一致；Qwen-Image 系文本编码器选 qwen_image",
                }),
                "device": (list(CLIP_DEVICES), {
                    "default": DEFAULT_DEVICE,
                    "tooltip": "设备：与官方 Load CLIP 一致；default=自动，cpu=放内存",
                }),

                # ══ ③ 官方 Generate Text（参数设置，全量）══
                "max_length": ("INT", {
                    "default": 512, "min": 1, "max": 32768,
                    "tooltip": "Generate Text · max_length：最大生成长度",
                }),
                "sampling_mode": (list(SAMPLING_MODES), {
                    "default": "on",
                    "tooltip": "Generate Text · Sampling Mode：on=按下面的采样参数生成；off=贪心解码，下面的采样参数不生效",
                }),
                "temperature": ("FLOAT", {
                    "default": 0.7, "min": 0.01, "max": 2.0, "step": 0.000001,
                    "tooltip": "Generate Text · temperature",
                }),
                "top_k": ("INT", {
                    "default": 64, "min": 0, "max": 1000,
                    "tooltip": "Generate Text · top_k",
                }),
                "top_p": ("FLOAT", {
                    "default": 0.95, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Generate Text · top_p",
                }),
                "min_p": ("FLOAT", {
                    "default": 0.05, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Generate Text · min_p",
                }),
                "repetition_penalty": ("FLOAT", {
                    "default": 1.05, "min": 0.0, "max": 5.0, "step": 0.01,
                    "tooltip": "Generate Text · repetition_penalty",
                }),
                "presence_penalty": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 5.0, "step": 0.01,
                    "tooltip": "Generate Text · presence_penalty",
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": _SEED_MAX,
                    "tooltip": "Generate Text · seed：生成种子（节点表面可点 🔁 切换生成后控制）",
                }),
                "thinking": ("BOOLEAN", {
                    "default": False,
                    "label_on": "🧠 思考模式 开", "label_off": "🧠 思考模式 关",
                    "tooltip": "Generate Text · thinking：模型支持时以思考模式生成（思考内容不会进入输出）",
                }),
                "use_default_template": ("BOOLEAN", {
                    "default": True,
                    "label_on": "使用内置模板", "label_off": "不使用内置模板",
                    "tooltip": "Generate Text · use_default_template：使用模型自带的系统提示词 / 对话模板",
                }),
                "mtp": (list(MTP_MODES), {
                    "default": "auto",
                    "tooltip": "Generate Text · mtp：多 token 预测投机解码；没有 MTP 权重时无效",
                }),

                # ══ ④ 内部字段（节点表面由前端面板隐藏）══
                "internal_prompt": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "节点内拼装/编辑的提示词正文（随工作流保存）",
                }),
                "manager_settings": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "本节点配置 JSON：元素面板 elements + 追加设定 extra_settings + 生成后控制 run",
                }),
            },
            "optional": {
                "text": ("STRING", {
                    "forceInput": True,
                    "tooltip": "外接提示词（优先于节点上的提示词框；接上线后提示词框锁定）",
                }),
                "images": ("IMAGE", {
                    "tooltip": "外接图像：一批图 = N 张参考图（官方图像编辑最多 10 张，提示词里可引用「第 N 张图」）。"
                               "用「📦 批量图像」等多图节点直接接这里即可。",
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "LATENT")
    RETURN_NAMES = ("提示词", "空latent")
    OUTPUT_IS_LIST = (False, False)
    FUNCTION = "generate"
    CATEGORY = "XB_ToolBox/Image_Params"
    DESCRIPTION = ("Qwen2.1提示词预设：生图预设（空latent类型/输出语言/预设模式/画幅参数 + 8 大类元素面板拼装）"
                   "＋ 官方 Load CLIP 与官方 Generate Text（纯本地文本生成，无开关，执行即生成）。"
                   "输出：提示词 / 空latent。")

    @classmethod
    def IS_CHANGED(cls, clip_name="", skill_name=SKILL_NONE, skill_mode=SKILL_MODE_AUTO,
                   preset_mode="", **kwargs):
        sig = {k: kwargs.get(k) for k in _SETTING_KEYS}
        used = effective_skill_name(skill_mode, skill_name, preset_mode)
        return f"{json.dumps(sig, sort_keys=True, ensure_ascii=False, default=str)}|{_file_sig(clip_name)}|{_skill_sig(used)}"

    def generate(self, latent_kind, output_lang, preset_mode, three_view_text, aspect_ratio,
                 width, height, batch_size,
                 clip_name, clip_type, device,
                 max_length, sampling_mode, temperature, top_k, top_p, min_p,
                 repetition_penalty, presence_penalty, seed, thinking, use_default_template, mtp,
                 internal_prompt="", manager_settings="", text="", images=None, unique_id=None,
                 skill_name=SKILL_NONE, skill_mode=SKILL_MODE_AUTO, io_mode=IO_MODE_AUTO):
        # ① 画幅归一 + 空 latent（与「🖼️ 生图提示词预设」逐行一致）
        spec = latent_kind_spec(latent_kind)
        w, h = normalize_size(aspect_ratio, width, height, spec["step"], spec["min"], spec["max"])
        latent = build_empty_latent(latent_kind, w, h, batch_size)

        # ② 组装送模型的 prompt（设定词只作参考，输出时节点自己置顶）
        st = parse_settings(manager_settings)
        lang = output_lang if output_lang in OUTPUT_LANGS else DEFAULT_LANG
        # 有没有接输入图 + 模版（自动/文生图/图生图）→ 决定用哪一套设定词
        has_img = False
        try:
            has_img = images is not None and hasattr(images, "shape") and len(images) > 0
        except Exception:
            has_img = False
        io_eff = resolve_io_mode(io_mode, has_img)          # 文生图 / 图生图
        base_prompt = build_prompt(lang, preset_mode, three_view_text, internal_prompt,
                                   has_image=has_img, io_mode=io_mode)
        preset_eff = _preset_text_of(preset_mode, lang, three_view_text,
                                     io_mode=io_mode, has_image=has_img)   # 送模型 / 置顶都用这一份
        body = (text or "").strip() or (internal_prompt or "").strip()
        # SKILL：不用 / 手动 / 自动（默认自动，按预设模式适配）
        skill_text = effective_skill_text(skill_mode, skill_name, preset_mode, use_default_template)
        skill_used = effective_skill_name(skill_mode, skill_name, preset_mode)
        # 选中 SKILL 时不再叠加语言提示（技能自带语言决策，叠加会互相打架）
        model_prompt = build_model_prompt(body or base_prompt, preset_eff, st["extra_settings"], lang,
                                          with_lang_hint=not bool(skill_text))

        # ③ 官方 Load CLIP + 官方 Generate Text（参数与调用方式逐字对齐官方节点）
        clip = get_clip(clip_name, clip_type, device)
        # 官方 image 输入：一批图 = N 张参考图（官方图像编辑最多 10 张，提示词可引用「第 N 张图」）
        # ⚠️ 不能把多帧当 video：Qwen-Image-2.1 的文本编码器链里**没人读 video**
        #    （qwen_image21/qwen3vl/sd1_clip 全程不碰 video，全库只有 gemma4 那个 tokenizer 认），
        #    一旦当成 video 传，图片会被静默丢弃 → 模型只看得到文字。
        image_arg = images if (images is not None and hasattr(images, "shape")) else None
        img_count = 0
        try:
            if image_arg is not None:
                img_count = int(len(image_arg))
        except Exception:
            img_count = 0
        if mode_needs_image(preset_mode) and img_count == 0:
            safe_print(f"[XB-Qwen提示词预设] ⚠️ 当前档位「{preset_mode}」属于图生图，但没有接参考图"
                  f"（🖼️ 图像，多张按批接即可）→ 本次按「文生图」设定词纯文字生成")
        try:                                              # 日志留痕：看得见“到底送了什么给文本编码器”
            print(f"[XB-Qwen提示词预设] 送模型 prompt（{len(model_prompt)} 字）："
                  f"{model_prompt[:120].replace(chr(10), ' / ')}" + ("…" if len(model_prompt) > 120 else ""))
        except Exception:
            pass
        # SKILL 已在上方读入 skill_text，并在那里决定了要不要叠加语言提示
        tokens = clip.tokenize(
            model_prompt,
            image=image_arg,
            skip_template=not bool(use_default_template),
            min_length=1,
            thinking=bool(thinking),
            system_prompt=skill_text,
        )
        _mtp = False if mtp == "off" else (True if mtp == "auto" else int(mtp))
        generated_ids = clip.generate(
            tokens,
            do_sample=(sampling_mode == "on"),
            max_length=int(max_length),
            temperature=float(temperature),
            top_k=int(top_k),
            top_p=float(top_p),
            min_p=float(min_p),
            repetition_penalty=float(repetition_penalty),
            presence_penalty=float(presence_penalty),
            seed=int(seed),
            mtp=_mtp,
        )
        raw = clip.decode(generated_ids) or ""

        # 思考段分离（与官方 TextGenerate 完全一致：不闭合时整段都算正文）
        reasoning, _, gen_text = raw.partition("</think>")
        if not reasoning.lstrip().startswith("<think>") and not model_prompt.rstrip().endswith("<think>"):
            gen_text = raw
        gen_text = gen_text.strip()

        # ④ 设定词原封不动置顶（与未生成时的成句规则一致；t2i/i2i 模版条款同样进最终提示词）
        final_prompt = build_prompt(lang, preset_mode, three_view_text, gen_text,
                                    has_image=has_img, io_mode=io_mode)

        try:
            shape = tuple(latent.get("samples").shape)
        except Exception:
            shape = ()
        print(f"[XB-Qwen提示词预设] {spec['label']} 丨 {w}x{h}（{aspect_ratio}·步长 {spec['step']}）"
              f"丨数量 {shape[0] if shape else batch_size}丨空latent {shape}"
              f"丨CLIP {clip_name}（{clip_type}·{device}）"
              f"丨Text 最大长度 {max_length}·采样 {sampling_mode}·思考 {'开' if thinking else '关'}"
              f"丨SKILL {skill_used}（{len(skill_text)} 字·{skill_mode_of(skill_mode)}）"
              f"丨模式 {preset_mode}丨模版 {io_eff}"
              f"{'（自动' + ('：检测到参考图' if has_img else '：未接参考图') + '）' if io_mode_of(io_mode) == IO_MODE_AUTO else ''}"
              f"丨参考图 {img_count} 张"
              f"丨种子 {seed}丨设定词 {'有' if preset_eff else '无'}丨生成 {len(gen_text)} 字丨输出 {len(final_prompt)} 字")

        ui = {
            "text": [final_prompt],
            "model": [str(clip_name or "-")],
            "gen_len": [len(gen_text)],
        }
        # 种子回写不在后端做：节点上的 seed widget 由 ComfyUI 原生的
        # control_after_generate 机制自动游走（与官方采样节点一致，避免双头写）
        return {"ui": ui, "result": (final_prompt, latent)}


NODE_CLASS_MAPPINGS = {
    "XB_QwenPromptPreset": XB_QwenPromptPreset,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_QwenPromptPreset": "XB-BOX - 🖼️ Qwen2.1提示词预设",
}
