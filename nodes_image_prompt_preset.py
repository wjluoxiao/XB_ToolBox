"""XB-BOX - 🖼️ 生图提示词预设（提示词 + 空latent 一体化）。
================================================================================
一个节点顶替「提示词输入框 + 画幅比例节点 + 官方空 latent」三件套：

· 表面参数（顺序 = 节点上从上到下的显示顺序）：
    空latent类型 / 输出语言 / 预设模式 / 预设句（三视图·四视图·五视图·背景纯透明 四个模式显示）
    / 画幅比例 / 宽度 / 高度 / 生成数量
  —— 画幅比例 + 步长锁定 + 比例联动 100% 复刻本包「XB-BOX - 🖼️ 图片参数大全」
     （去掉强度(小数)/强度(整数)/缩放尺寸三项）
· 表面 6 个按钮（UI 在 js/xb_image_prompt_preset.js）：
     🏷️ 风格 ｜ 🎥 视角 ｜ 👤 主体 ｜ 🎬 姿态 ｜ 👚 装扮 ｜ 🎒 道具 ｜ 💡 光影 ｜ 🏞️ 背景
     每个按钮打开**该分类**的独立面板；面板顶部「分类签」切换子类
     （例：风格 → 真人/动画/3D/绘画插画/特殊风格），选项行 = ➕ ➖ 选项名 添加详细描述
· 输出①「提示词」= 预设句（人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明；无预设档不前置）+ 正文（节点提示词框 ↔ 面板预览框双向同步）
· 输出②「空latent」= 主流模型直接可用的空 latent（选项名 = 模型名，规格按官方 latent_format；
  通道数 / 下采样除数 / 步长 / 上下限 / batch 上限 / downscale 元数据逐项对齐）：
     · Z-image   16 通道 · /8   · 步长 16  （官方 latent_format = Flux）
     · Flux2     128 通道 · /16 · 步长 16  （官方 EmptyFlux2LatentImage）
     · Qwen-image 16 通道 · /8  · 步长 32  （官方 latent_format = Wan21，采样时自动补 T 维；按用户要求锁 32）
     · Krea2     16 通道 · /8   · 步长 16  （官方 latent_format = Wan21）
     · Anima     16 通道 · /8   · 步长 8   （官方模板用 4 通道 EmptyLatentImage，零 latent 会被自动补齐）
     · Boogu     16 通道 · /8   · 步长 8   （同上，官方 latent_format = Flux）
     · SDXL      4 通道 · /8    · 步长 8   （官方 EmptyLatentImage）
     · SD3       16 通道 · /8   · 步长 16  （官方 EmptySD3LatentImage）
     · Hunyuan   64 通道 · /32  · 步长 32  （官方 EmptyHunyuanImageLatent / HunyuanImage 2.1）
  ⚠️ 通道/步长等专业细节只写在 tooltip 与控制台日志里，**不占选项文字**（保持选项名干净）。
  ⚠️ 全零 latent 即使类型选错也能跑：comfy/sample.py:fix_empty_latent_channels 会按模型补通道
     + 按 downscale_ratio_spacial 缩放尺寸 + 自动补 T 维；但选对类型少一步转换、更稳。

配置存法（与本包风格一致，不依赖任何后端接口）：
· `manager_settings`（内部字段，由前端面板隐藏，表面不显示）只存**元素面板配置 JSON**
  （已选词条 / 自建槽位 / 补充描述 / 自动保存），随工作流保存、节点间互不影响；
· `internal_prompt`（内部字段，同上前端隐藏）存提示词正文；
· 空latent类型 / 输出语言 / 预设模式 / 预设句 都是**节点表面参数**（随工作流保存）。
"""

import json
import math

import torch
import comfy.model_management
import nodes

from .xb_skills import SKILL_NONE, skill_text

# ── 画幅比例（与本包 XB_ImageParamsMaster 完全一致的选项顺序） ──────────────
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
    return skill_text(name, "[XB-SKILL]")


def with_io_clause(preset_text, preset_mode, has_image, output_lang=None):
    """把 t2i / i2i 模版条款追加到设定词上（送模型的那一份与置顶的那一份保持一致）"""
    clause = mode_io_clause(preset_mode, has_image, output_lang)
    t = _as_str(preset_text).strip()
    if not clause:
        return t
    return (t + " " + clause).strip() if t else clause


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

# 元素分类白名单（必须与 js/xb_image_prompt_preset.js 的 CATEGORIES 顺序逐字一致；
# 自测会断言两者相等）。这里只用来过滤配置里的脏数据。
# 顺序 = 节点上 8 个按钮的顺序：风格 / 视角 / 主体 / 姿态 / 装扮 / 道具 / 光影 / 背景
# （必须与 js/xb_image_prompt_preset.js 的 CAT_ORDER 完全一致，自测会断言）
ELEMENT_CATEGORIES = ("prefix", "angle", "subject", "action", "clothes", "props", "environment", "background")


# ============================================================================
# 配置读写（None / 缺字段 / 非法值一律安全兜底）
# ============================================================================
def _default_settings():
    """节点默认配置（与前端 js/xb_image_prompt_preset.js 的 defaultSettings() 一一对应）。

    ⚠️ 自 0.9.x 起：输出语言 / 预设模式 / 预设句 / 空latent类型 已上提为**节点表面参数**，
    不再存在这份 JSON 里（JSON 只留元素面板配置 + 自动保存开关）。
    """
    return {
        "auto_save": True,
        "elements": {
            "selected": {},   # {分类: [词条 key, ...]}（有序，决定「按选择重建」的拼接顺序）
            "custom": {},     # {分类: [{"key":..., "zh":..., "en":...}, ...]} 用户自建槽位
            "noted": {},      # {"分类|key": "用户补充描述"}（稀疏：只存非空）
        },
    }


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


def _parse_settings(raw):
    """manager_settings(JSON 字符串) → 完整配置；任何异常都退回默认，绝不让节点崩。"""
    cfg = _default_settings()
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw) if (raw or "").strip() else {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    if isinstance(data.get("auto_save"), bool):
        cfg["auto_save"] = data["auto_save"]

    el = _as_dict(data.get("elements"))
    sel = {}
    for cat, keys in _as_dict(el.get("selected")).items():
        # 只认白名单分类 + 只收字符串 key + 去重（脏数据一律丢，不让它影响拼装）
        if str(cat) not in ELEMENT_CATEGORIES:
            continue
        seq = []
        for k in _as_list(keys):
            if not isinstance(k, str):
                continue
            k = k.strip()
            if k and k not in seq:
                seq.append(k)
        if seq:
            sel[str(cat)] = seq
    cfg["elements"]["selected"] = sel

    cus = {}
    for cat, items in _as_dict(el.get("custom")).items():
        if str(cat) not in ELEMENT_CATEGORIES:
            continue
        seq = []
        seen = set()
        for it in _as_list(items):
            if not isinstance(it, dict):
                continue
            k = _as_str(it.get("key")).strip()
            if not k or k in seen:
                continue
            seen.add(k)
            seq.append({"key": k, "zh": _as_str(it.get("zh")), "en": _as_str(it.get("en"))})
        if seq:
            cus[str(cat)] = seq
    cfg["elements"]["custom"] = cus

    noted = {}
    for key, desc in _as_dict(el.get("noted")).items():
        d = _as_str(desc).strip()
        if d:
            noted[str(key)] = d
    cfg["elements"]["noted"] = noted
    return cfg


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
class XB_ImagePromptPreset:
    """XB-BOX - 🖼️ 生图提示词预设：画幅参数 + 提示词拼装 + 官方空 latent 一体化。

    · 表面参数顺序 = 输出语言 / 预设模式 / 空latent类型 / 预设句（三视图·四视图·五视图·背景纯透明 显示）
      / 画幅比例 / 宽度 / 高度 / 生成数量；
    · 「提示词」输出 = 预设句（人物三视图）+ 节点提示词框正文；
    · 「空latent」输出 = 官方空 latent（见 LATENT_KINDS，共 9 种，逐字段对齐，选项按首字母排列）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # ── 空latent 类型放最顶（用户要求）──
                "latent_kind": (list(LATENT_KINDS), {
                    "default": DEFAULT_LATENT_KIND,
                    "tooltip": "空latent类型：选你正在用的模型即可（自动适配形状/下采样/步长）。\n"
                               "Z-image 16ch·/8·16　Flux2 128ch·/16·16　Qwen-image 16ch·/8·32\n"
                               "Krea2 16ch·/8·16　Anima 16ch·/8·8　Boogu 16ch·/8·8\n"
                               "SDXL 4ch·/8·8　SD3 16ch·/8·16　Hunyuan 64ch·/32·32\n"
                               "（步长 = 各模型官方最小步长，仅 Qwen-image 按需求锁 32；通道/下采样同样按官方 latent_format）",
                }),
                # ── 以下 3 项由原「⚙️ 输出设置」面板上提为节点表面参数 ──
                "output_lang": (list(OUTPUT_LANGS), {
                    "default": LANG_ZH,
                    "tooltip": "输出语言：影响预设句、元素拼装分隔符（面板里新加入的词条也按此语言）",
                }),
                "preset_mode": (list(PRESET_MODES), {
                    "default": PRESET_MODES[0],
                    "tooltip": "预设模式：无预设=不前置任何设定词，只输出正文（完全可控）；"
                               "人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明 = 成句自动在正文前加对应预设句"
                               "（下方预设句框仅这三个模式显示，切模式时未改过的默认句会自动跟随）",
                }),
                "three_view_text": ("STRING", {
                    "default": THREE_VIEW_TEXT[LANG_ZH], "multiline": True,
                    "tooltip": "预设句 / 设定词（人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明 四个模式生效；无预设时本框自动隐藏）\n"
                               "· 用户改过的设定词按「模式 + 语言」存进本节点（换模式 / 换语言都不会丢）；\n"
                               "· 最终提示词输出时它会被原封不动加在正文最顶端",
                }),
                "aspect_ratio": (list(ASPECT_RATIO_OPTIONS), {
                    "default": "Free",
                    "tooltip": "画幅比例：Free=自由（仅按步长锁定）；固定比例时以输入中较大的一边为基准，"
                               "自动反算另一边并锁定到步长倍数（与「图片参数大全」完全一致）",
                }),
                "width": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION, "step": SIZE_STEP,
                    "tooltip": "图片宽度（像素）。固定比例下改宽度会按比例重算高度；步长按「空latent类型」的官方最小步长"
                               "（SDXL/Anima/Boogu=8，Flux2/Krea2/SD3/Z-image=16，Qwen-image/Hunyuan=32）",
                }),
                "height": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION, "step": SIZE_STEP,
                    "tooltip": "图片高度（像素）。固定比例下改高度会按比例重算宽度；步长按「空latent类型」的官方最小步长（8/16/32）",
                }),
                "batch_size": ("INT", {
                    "default": 1, "min": 1, "max": BATCH_MAX,
                    "tooltip": "一次生成的图片数量（空 latent 的 batch 维度）",
                }),
                # ↓ 两个内部字段：节点表面由前端面板（js/xb_image_prompt_preset.js 的 hideInternal）隐藏。
                #   不再用 advanced=True —— 它会让前端在节点底部挂一个「显示高级输入」开关，
                #   而那里面只有这两个已被隐藏的字段，点了没有任何可见变化（用户反馈纯碍眼）。
                "internal_prompt": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "节点内编辑的提示词正文（与元素面板的预览框双向同步，随工作流保存）。"
                               "人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明模式下，本字段前面会自动拼上对应预设句",
                }),
                "manager_settings": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "本节点独立保存的元素面板配置 JSON（已选词条 / 自建槽位 / 补充描述），"
                               "随工作流保存，节点间互不影响",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "LATENT")
    RETURN_NAMES = ("提示词", "空latent")
    FUNCTION = "generate"
    CATEGORY = "XB_ToolBox/Image_Params"
    DESCRIPTION = ("生图提示词预设：空latent类型（主流模型一键适配 Z-image/Flux2/Qwen-image/Krea2/"
                   "Anima/Boogu/SDXL/SD3/Hunyuan）+ 输出语言/预设模式 + 画幅比例/宽度/高度/生成数量"
                   "（步长按各模型官方最小步长 8/16/32 + 比例联动）＋ 提示词拼装（8 大类：风格/视角/主体/姿态/穿搭/道具/光影/背景）。"
                   "输出：①提示词 ②空latent。")

    @classmethod
    def IS_CHANGED(cls, manager_settings="", **kwargs):
        """任一表面参数/提示词/配置变化都让缓存失效（保证改参数即重跑）。"""
        keys = ("output_lang", "preset_mode", "latent_kind", "three_view_text",
                "aspect_ratio", "width", "height", "batch_size", "internal_prompt")
        sig = {k: kwargs.get(k) for k in keys}
        return f"{manager_settings}|{sig}"

    def generate(self, output_lang, preset_mode, latent_kind, three_view_text, aspect_ratio,
                 width, height, batch_size, internal_prompt="", manager_settings=""):
        # ① 画幅归一：步长/上下限按当前空 latent 类型（官方各节点并不一致）
        spec = latent_kind_spec(latent_kind)
        w, h = normalize_size(aspect_ratio, width, height,
                              spec["step"], spec["min"], spec["max"])

        # ② 空 latent（官方同款张量）
        latent = build_empty_latent(latent_kind, w, h, batch_size)

        # ③ 提示词（预设句 + 正文）
        prompt = build_prompt(output_lang, preset_mode, three_view_text, internal_prompt)

        # ④ 控制台日志（节点表面不再有信息行，调试信息只打日志）
        try:
            shape = tuple(latent.get("samples").shape)
        except Exception:
            shape = ()
        print(f"[XB-生图提示词预设] {spec['label']} 丨 {w}x{h}（{aspect_ratio}·步长 {spec['step']}）"
              f"丨数量 {shape[0] if shape else batch_size}丨空latent {shape}"
              f"丨模式 {preset_mode}丨语言 {output_lang}丨提示词 {len(prompt)} 字")
        if prompt:
            print(f"[XB-生图提示词预设] 提示词：{prompt[:200]}{'…' if len(prompt) > 200 else ''}")

        return (prompt, latent)


# 供自测脚本直接调用（避免依赖私有名）
__all__ = [
    "XB_ImagePromptPreset",
    "ASPECT_RATIO_OPTIONS", "ASPECT_RATIO_MAP", "SIZE_STEP", "SIZE_MIN", "MAX_RESOLUTION",
    "BATCH_MAX", "MODE_FIVE_VIEW", "OUTPUT_LANGS", "PRESET_MODES", "PRESET_TEXT", "THREE_VIEW_TEXT",
    "LATENT_KINDS", "LATENT_KIND_SPEC", "DEFAULT_LATENT_KIND", "ELEMENT_CATEGORIES",
    "default_settings", "parse_settings", "round_step", "normalize_size",
    "latent_kind_spec", "latent_step_of", "latent_shape_of",
    "build_empty_latent", "build_prompt",
]

# 别名：公开名与私有名同体（自测脚本可读，节点内部继续用下划线短名）
default_settings = _default_settings
parse_settings = _parse_settings
round_step = _round_step
