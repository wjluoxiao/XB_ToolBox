/**
 * XB-BOX - 🖼️ 生图提示词预设 — 前端面板
 * ============================================================
 * 节点：XB_ImagePromptPreset（后端 nodes_image_prompt_preset.py，V1 经典 API）
 * 表面：空latent类型 / 输出语言 / 预设模式 / （三视图/四视图/五视图预设句）/ 画幅比例 / 宽度 / 高度 / 生成数量
 *       ＋ 节点提示词框 ＋ 8 个分类按钮（4 列 × 2 行）：🏷️ 风格 ｜ 🎥 视角 ｜ 👤 主体 ｜ 🎬 姿态 ｜ 👚 装扮 ｜ 🎒 道具 ｜ 💡 光影 ｜ 🏞️ 背景
 *       每个按钮一个面板，面板顶部「分类签」切子类；选项行整行可点（加入 → 变蓝 ✔ / 再点移除）
 *       道具类点行会先弹「与主体的关系」多宫格标签窗（30 个关系词）
 *
 * 界面逻辑与「短剧导演台」（ComfyUI-JZL-MiniMax-H3/js/asset_manager.js）一致：
 *   · 容器 width/height:100% + overflow:hidden，提示词框 flex:1 1 auto 吃剩余高（CSS 排版，零 JS 高度计算）
 *   · refreshSize 只在「初始化 / 工作流加载」跑几次，用 computeSize 做下限保护，只增不减
 *   · 打字 / 面板保存 / onResize 一律不 setSize、不重排（否则 setSize→onResize→setSize 抖动 → 界面卡顿）
 *
 * 配置一律存在节点的 `manager_settings` widget（JSON 字符串）里 ——
 * 随工作流保存、节点间互不影响、不需要任何后端接口。
 * 提示词正文存在 `internal_prompt` widget（advanced 字段，节点表面不显示），
 * 由「节点提示词框 ↔ 面板预览框」双向同步。
 *
 * 本文件只 import xb_compat.js 的 2.0 兼容助手（其余是模块私有函数），自带十来个无状态 UI 助手。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { installNodes2BoxResize } from "./xb_compat.js";

const NODE_TYPE = "XB_ImagePromptPresetPro";

// ── 枚举（必须与 nodes_image_prompt_preset.py 的常量逐字一致） ─────────
const LANG_ZH = "中文 [ZH]";
const LANG_EN = "英文 [EN]";
const LANGS = [LANG_ZH, LANG_EN];
const MODE_TP = "常规文生图";
const MODE_3V = "人物三视图";
const MODE_4V = "人物四视图";
const MODE_5V = "人物五视图";
const MODE_RGBA = "背景纯透明";
const MODES = [MODE_TP, MODE_3V, MODE_4V, MODE_5V, MODE_RGBA];

const ASPECT_MAP = { "1:1": 1, "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9 };
const SIZE_STEP = 16;      // width/height 的兜底步长（实际以「空latent类型」的官方最小步长为准）
const SIZE_MIN = 16;
const SIZE_MAX = 16384;
const BATCH_MAX = 4096;

// ── 主流模型的空 latent（选项名 = 模型名，规格按官方 latent_format；必须与后端 _OFFICIAL_LATENT_ROWS 逐字一致）──
// 选项按首字母（A→Z，不区分大小写）排列；DEFAULT_LATENT_KIND 固定 Z-image，不受排序影响。
const LATENT_KINDS = [
  "Anima", "Boogu", "Flux2", "Hunyuan", "Krea2", "Qwen-image", "SD3", "SDXL", "Z-image",
];
// 每项：channels(通道) / hDiv・wDiv(下采样除数) / step(尺寸步长 = 各模型官方最小步长) / min・max / batchMax / downscale / desc(悬停说明)
// 步长 = 下采样 × patch2：Anima/Boogu/SDXL = 8、Flux2 = 16、Krea2/SD3/Z-image = 16、Qwen-image = 32（按需求锁 32）、Hunyuan = 32
const LATENT_KIND_SPEC = {
  "Anima": { channels: 16, hDiv: 8, wDiv: 8, step: 8, min: 16, max: 16384, batchMax: 4096, downscale: 8, desc: "Anima：16 通道 · /8 · 步长 8（官方模板用 4 通道 EmptyLatentImage，零 latent 会被自动补齐）" },
  "Boogu": { channels: 16, hDiv: 8, wDiv: 8, step: 8, min: 16, max: 16384, batchMax: 4096, downscale: 8, desc: "Boogu：16 通道 · /8 · 步长 8（同上，官方 latent_format = Flux）" },
  "Flux2": { channels: 128, hDiv: 16, wDiv: 16, step: 16, min: 16, max: 16384, batchMax: 4096, downscale: 16, desc: "Flux2：128 通道 · /16 · 步长 16（官方 EmptyFlux2LatentImage）" },
  "Hunyuan": { channels: 64, hDiv: 32, wDiv: 32, step: 32, min: 64, max: 16384, batchMax: 4096, downscale: 32, desc: "Hunyuan：64 通道 · /32 · 步长 32（官方 EmptyHunyuanImageLatent / HunyuanImage 2.1）" },
  "Krea2": { channels: 16, hDiv: 8, wDiv: 8, step: 16, min: 16, max: 16384, batchMax: 4096, downscale: 8, desc: "Krea2：16 通道 · /8 · 步长 16（官方 latent_format = Wan21）" },
  "Qwen-image": { channels: 16, hDiv: 8, wDiv: 8, step: 32, min: 32, max: 16384, batchMax: 4096, downscale: 8, desc: "Qwen-image：16 通道 · /8 · 步长 32（官方 latent_format = Wan21，采样时自动补 T 维；按需求锁 32）" },
  "SD3": { channels: 16, hDiv: 8, wDiv: 8, step: 16, min: 16, max: 16384, batchMax: 4096, downscale: 8, desc: "SD3：16 通道 · /8 · 步长 16（官方 EmptySD3LatentImage）" },
  "SDXL": { channels: 4, hDiv: 8, wDiv: 8, step: 8, min: 16, max: 16384, batchMax: 4096, downscale: 8, desc: "SDXL：4 通道 · /8 · 步长 8（官方 EmptyLatentImage）" },
  "Z-image": { channels: 16, hDiv: 8, wDiv: 8, step: 16, min: 16, max: 16384, batchMax: 4096, downscale: 8, desc: "Z-image：16 通道 · /8 · 步长 16（官方 latent_format = Flux）" },
};
const DEFAULT_LATENT_KIND = "Z-image";

/** 各预设模式的默认预设句（可编辑字段 three_view_text）；常规文生图 = 无预设句（原样输出正文） */
const PRESET_TEXT_DEFAULT = {
  [MODE_3V]: {
    [LANG_ZH]: "生成平行排列的角色概念设计图，画面从左到右由四个独立面板组成：第一个面板是角色面部的精细特写肖像，第二个面板是人物正面全身站姿，第三个面板是人物侧面全身站姿，第四个面板是人物背面全身站姿。",
    [LANG_EN]: "Generate a character concept design sheet arranged in parallel panels, the image is composed of four separate panels from left to right: the first panel is a finely detailed close-up portrait of the character's face, the second panel is a full-body front standing pose, the third panel is a full-body side standing pose, the fourth panel is a full-body back standing pose.",
  },
  [MODE_4V]: {
    [LANG_ZH]: "生成四宫格排列的角色概念设计图，画面左上角面板是角色面部的精细特写肖像，画面右上角面板是角色面部侧面的的精细特写肖像，画面左下角面板是无头部人物正面衣着展示图，画面右下角面板是人物背面全身站姿。",
    [LANG_EN]: "Generate a character concept design sheet arranged in a 2x2 grid, the top-left panel is a finely detailed close-up portrait of the character's face, the top-right panel is a finely detailed close-up profile portrait of the character's face, the bottom-left panel is a headless front-facing outfit display view, the bottom-right panel is a full-body back standing pose.",
  },
  [MODE_5V]: {
    [LANG_ZH]: "生成五宫格排列的角色概念设计图，画面左上角面板是角色面部的精细特写肖像，画面右上角面板是角色面部侧面的的精细特写肖像，画面下方左侧面板是无头部人物正面衣着展示图，画面下方中间面板是无头部人物侧面衣着展示图，画面下方右侧面板是人物背面全身站姿。",
    [LANG_EN]: "Generate a character concept design sheet arranged in five panels, the top-left panel is a finely detailed close-up portrait of the character's face, the top-right panel is a finely detailed close-up profile portrait of the character's face, the bottom-left panel is a headless front-facing outfit display view, the bottom-middle panel is a headless side-facing outfit display view, the bottom-right panel is a full-body back standing pose.",
  },
  [MODE_RGBA]: {
    [LANG_ZH]: "生成一张具有透明度的 RGBA 格式图像，包含 Alpha 通道，背景为纯透明。",
    [LANG_EN]: "Generate an RGBA image with an alpha channel and a fully transparent background.",
  },
};
/** 某模式某语言下的默认预设句（无预设句的模式 → 空串） */
const defaultPresetOf = (mode, lang) => ((PRESET_TEXT_DEFAULT[mode] || {})[lang] || "");
/** 兼容旧引用：三视图预设句 */
const THREE_VIEW_DEFAULT = PRESET_TEXT_DEFAULT[MODE_3V];

/**
 * ── 预设句（设定词）档案 ─────────────────────────────────────────────
 * 需求：预设模式（三视图 / 四视图 / 五视图 / 背景纯透明）的设定词可编辑，且**改过就存进节点、
 *       换模式 / 换语言都不丢**（切换时取「存档 → 默认」，绝不把用户改过的冲掉）。
 * 存档位置 = manager_settings.preset_texts（JSON 字符串随工作流一起保存）：
 *   { "人物三视图|中文 [ZH]": "用户改过的设定词", … }   ← 只存与默认不同的那条
 * 键里带语言：默认设定词本身就是中英两套，用户改的哪一套就记哪一套。
 */
const presetKeyOf = (mode, lang) => `${mode}|${lang}`;
function parsePresetTexts(raw) {
  const out = {};
  if (!raw || typeof raw !== "object") return out;
  for (const [k, v] of Object.entries(raw)) {
    const seg = String(k).split("|");
    if (seg.length !== 2 || !MODES.includes(seg[0]) || !LANGS.includes(seg[1])) continue;
    if (typeof v !== "string" || !v.trim()) continue;
    out[`${seg[0]}|${seg[1]}`] = v;    // 保留原文（含换行 / 尾随空格）
  }
  return out;
}

const SEP = { [LANG_ZH]: "，", [LANG_EN]: ", " };

/* ============================================================
 *  元素词表（自研原创 · 中英双语 · 六分类）
 *  [[key, 中文, English], ...]；配置里只存 key —— 改文案不会让
 *  老工作流的「已选 / 描述」失效。
 * ============================================================ */
/* ============================================================
 *  元素词表（自研原创 · 中英双语）
 *  · WORDS      = 词条本体 [[key, 中文, English], ...]（配置里只存 key）
 *  · CATEGORIES = 6 大类 + 每类的「子分类」（面板顶部用分类签切换）
 *                 subs[].keys = 该子类包含哪些词条 key（顺序 = 面板显示顺序）
 * ============================================================ */
const CATEGORY_DEFS = {
  prefix: {
    id: "prefix", btn: "🏷️ 风格", label: "🏷️ 风格",
    tip: "画面风格与媒介：真人摄影 / 动画 / 3D / 绘画插画 / 特殊风格",
    subs: [
      { id: "real", label: "真人", keys: [
        "photo_hd", "snapshot_amateur", "documentary", "cinematic", "commercial", "studio_portrait",
        "fashion_editorial", "vintage_film", "polaroid", "bw_photo", "long_exposure", "macro",
        "aerial", "wide_angle", "fisheye", "tilt_shift", "infrared", "double_exposure",
        "high_speed", "phone_night", "product_still", "food_photo",
        "guofeng_hanfu_photo"] },
      { id: "anime", label: "动画", keys: [
        "anime_frame", "anime_movie", "comic_panel", "manga_line",
        "anime_sakuga", "anime_tv", "anime_lite", "galgame_cg", "chibi", "webtoon", "us_comic", "ink_comic"] },
      { id: "cg3d", label: "3D", keys: [
        "cg3d_toon", "pixar3d", "low_poly",
        "ue5_render", "blender_pbr", "clay_render", "isometric", "voxel", "miniature", "game_cinematic", "toy_render"] },
      { id: "paint", label: "绘画插画", keys: [
        "oil_painting", "watercolor", "ink_wash", "pencil_sketch", "charcoal", "colored_pencil",
        "crayon", "concept_art", "game_keyart", "character_sheet", "flat_vector", "cyberpunk_art",
        "steampunk_art", "gongbi",
        "gouache", "acrylic", "pastel", "ink_line",
        "gongbi_heavy"] },
      { id: "special", label: "特殊风格", keys: [
        "stop_motion_clay", "paper_cutout", "pixel_art", "vaporwave", "pop_art", "art_nouveau",
        "ukiyo_e", "dunhuang", "porcelain", "shadow_puppet",
        "risograph", "collage_art", "neon_sign", "glass_art",
        "guochao_illustration", "qinglv_shanshui", "xianxia_film"] },
    ],
  },
  angle: {
    id: "angle", btn: "🎥 视角", label: "🎥 视角",
    tip: "机位与构图：视点 / 构图 / 特写",
    subs: [
      { id: "view", label: "视点", keys: [
        "front_view", "side_view", "three_quarter", "back_view", "top_down", "low_angle",
        "dutch_angle", "over_shoulder", "from_above", "worm_eye", "eye_level", "overhead_45",
        "pov_first_person"] },
      { id: "frame", label: "构图", keys: [
        "wide_shot", "half_body", "full_body", "rule_of_thirds", "symmetrical_comp", "center_comp",
        "leading_lines", "frame_in_frame", "reflection_view", "silhouette_view", "foreground_blur",
        "liubai_composition"] },
      { id: "detail", label: "特写", keys: [
        "close_up", "extreme_close", "hand_detail", "prop_detail"] },
    ],
  },
  clothes: {
    id: "clothes", btn: "👚 装扮", label: "👚 装扮",
    tip: "从头到脚的外观：头饰 / 妆容 / 上装 / 下装 / 鞋履 / 包袋 / 配饰",
    subs: [
      { id: "head", label: "头饰", keys: [
        "hat", "baseball_cap", "beanie", "bucket_hat", "straw_hat", "fedora", "witch_hat", "crown",
        "hair_clip", "hairband", "hair_tie", "hair_ribbon",
        "hairpin_jade", "buyao", "guan_jin", "mo_e", "zan_hua"] },
      { id: "makeup", label: "妆容", keys: [
        "makeup_natural", "makeup_red_lip", "makeup_smoky", "makeup_goth", "makeup_geisha",
        "makeup_freckles", "makeup_glitter", "makeup_blush", "face_tattoo", "face_paint",
        "lip_gloss", "korean_idol",
        "huadian", "dai_mei", "taohua_zhuang"] },
      { id: "top", label: "上装", keys: [
        "casual", "dress", "long_dress", "short_dress", "shirt", "white_shirt", "blouse", "plaid_shirt",
        "striped_top", "sweater", "turtleneck", "cardigan", "hoodie", "jacket", "leather_jacket",
        "denim_jacket", "embroidered_jacket", "coat", "trench_coat", "down_jacket", "suit", "vest",
        "tank_top", "tshirt", "crop_top", "lace_top", "overalls", "jumpsuit", "swimsuit", "swim_trunks",
        "tracksuit", "school_uniform", "military_uniform", "nurse_uniform", "maid_outfit", "kimono",
        "yukata", "hanfu", "cheongsam", "tang_suit", "hanbok", "period_robe", "floor_robe", "monk_robe",
        "nun_habit", "wizard_robe", "knight_armor", "leather_armor", "cloak", "cape", "space_suit",
        "mecha_suit", "diving_suit", "hazmat_suit", "hospital_gown", "bathrobe", "pajamas",
        "wedding_dress", "evening_gown", "tailcoat", "silk_gown", "off_shoulder", "backless_dress",
        "corset_dress", "floral_dress",
        "hanfu_top", "daopao", "xiake_robe", "daxiushan", "ruqun", "armor_chinese", "hechang"] },
      { id: "bottom", label: "下装", keys: [
        "skirt", "layered_skirt", "jeans", "ripped_jeans", "trousers", "cargo_pants", "shorts",
        "sweatpants", "loose_sweatpants", "leggings", "socks", "stockings", "tights",
        "mamian_skirt", "baizhe_skirt", "denglong_ku"] },
      { id: "shoes", label: "鞋履", keys: [
        "sneakers", "canvas_shoes", "leather_shoes", "high_heels", "boots", "knee_boots",
        "combat_boots", "suede_boots", "sandals", "slippers", "geta", "snow_boots", "rain_boots",
        "yuntou_lv", "xiuhua_shoes"] },
      { id: "bag", label: "包袋", keys: [
        "backpack", "handbag", "crossbody", "tote", "briefcase", "leather_satchel", "waist_pack",
        "school_bag", "basket_bag", "pouch", "luggage", "quiver"] },
      { id: "acc", label: "配饰", keys: [
        "scarf", "fur_shawl", "gloves", "mittens", "belt", "apron", "necktie", "bow_tie", "necklace",
        "choker", "pendant", "earring", "ring", "bracelet", "watch", "brooch", "lace_trim",
        "xiapi"] },
    ],
  },
  props: {
    id: "props", btn: "🎒 道具", label: "🎒 道具",
    tip: "独立于主体的器物：兵器 / 法器 / 文房雅器 / 日用器物（点道具会先选「与主体的关系」）",
    subs: [
      { id: "weapon", label: "兵器", keys: [
        "sword_chinese", "spear_chinese", "sabre_chinese", "dagger", "whip", "bow_arrow",
        "hidden_dart", "round_shield", "halberd", "iron_staff"] },
      { id: "magic", label: "法器", keys: [
        "fuchen", "talisman_paper", "spirit_pearl", "ruyi_jade", "bronze_mirror", "ritual_bell",
        "prayer_beads", "wooden_fish"] },
      { id: "refine", label: "文房雅器", keys: [
        "folding_fan", "tuan_shan", "jade_pendant", "xiangnang", "ink_brush", "scroll_painting",
        "bamboo_flute", "go_board"] },
      { id: "daily", label: "日用器物", keys: [
        "lantern_paper", "wine_pot", "gourd_flask", "tea_set", "food_box", "bamboo_case",
        "oil_silk_umbrella", "copper_coins"] },
    ],
  },
  subject: {
    id: "subject", btn: "👤 主体", label: "👤 主体",
    tip: "画面主体：人类 / 动物 / 植物 / 物品 / 幻想生物",
    subs: [
      { id: "human", label: "人类", keys: [
        "man", "woman", "young_man", "young_woman", "handsome_man", "beautiful_woman", "elderly",
        "boy", "girl", "baby", "suit_man", "cheongsam_woman", "wuxia_swordsman", "hanfu_girl", "maid",
        "nurse", "doctor", "officer", "soldier", "teacher", "scientist", "wizard", "witch", "knight",
        "princess", "prince", "king", "ninja", "samurai", "assassin", "mechanic", "programmer", "chef",
        "dancer", "singer", "musician", "athlete", "astronaut",
        "daoshi", "xiannv", "nvxia", "shusheng"] },
      { id: "animal", label: "动物", keys: [
        "cat", "dog", "fox", "wolf", "tiger", "rabbit", "bird", "horse", "whale", "butterfly",
        "crane", "jade_rabbit", "sika_deer", "panda"] },
      { id: "plant", label: "植物", keys: [
        "bouquet", "tree_pine", "cherry_blossom", "rose", "sunflower", "lotus", "tropical_leaf",
        "moss", "vine", "bonsai", "maple_leaf", "wheat", "succulent",
        "plum_blossom", "orchid", "chrysanthemum", "peony", "ginkgo"] },
      { id: "object", label: "物品", keys: [
        "puppet", "toy", "product", "buddha", "statue", "abstract_shapes",
        "book_stack", "coffee_cup", "vintage_camera", "crystal_gem", "lantern_object", "paper_plane",
        "vinyl_record", "pocket_watch", "sword_object", "food_dish", "car_object", "potion_bottle",
        "incense_burner", "guqin", "oil_paper_umbrella", "porcelain_vase", "weiqi_board"] },
      { id: "fantasy", label: "幻想生物", keys: [
        "cyborg", "robot", "dragon", "phoenix", "monster", "fairy", "ghost",
        "angel", "demon", "elf", "orc", "slime", "mecha", "undead", "kirin", "nine_tail_fox",
        "spirit_beast", "golem", "alien",
        "dragon_east", "mountain_spirit"] },
    ],
  },
  action: {
    id: "action", btn: "🎬 姿态", label: "🎬 姿态",
    tip: "表情 / 姿势 / 动作",
    subs: [
      { id: "expression", label: "表情", keys: [
        "look_viewer", "look_away", "look_up", "look_down", "look_back", "mouth_open", "mouth_half",
        "mouth_closed", "eyes_open", "eyes_half", "eyes_closed", "wink", "squint", "smile", "laugh",
        "smile_soft", "sad", "angry", "surprised", "pensive", "blank", "frown", "blush", "teary",
        "bite_lip", "glance_smile",
        "stern_look", "angry_glare", "calm_smile"] },
      { id: "pose", label: "姿势", keys: [
        "standing", "sitting", "sitting_side", "lying", "bent", "kneeling", "crouching", "leaning_back",
        "lean_wall", "crossed_arms", "hands_hips", "hands_pockets", "chin_hand", "touch_hair",
        "facing_away",
        "meditate_lotus", "hands_behind", "stand_sword", "cupped_fist",
        "bow_salute", "kneel_one_knee", "tai_chi", "hands_sleeves"] },
      { id: "motion", label: "动作", keys: [
        "walking", "running", "jumping", "climbing", "swimming", "flying", "falling", "floating",
        "dancing", "spinning", "reaching", "waving", "clapping", "thumbs_up", "heart_hands",
        "shade_eyes", "hold_cup", "clench_fist", "reading", "using_phone", "typing", "drawing_art",
        "playing_instrument", "raise_weapon", "draw_sword", "swing_sword", "aim_gun", "cast_spell",
        "draw_bow", "frozen_sprint",
        "sword_dance", "sword_slash", "cast_seal", "fly_sword", "sleeve_sweep",
        "ride_horse", "sword_point", "sheath_sword", "twin_swords", "spear_thrust", "palm_strike",
        "flying_kick", "martial_stance", "fan_dance", "playing_guqin", "ink_calligraphy",
        "drink_wine", "carry_umbrella", "leap_air", "meditate_float", "blink_flash",
        "run_sprint", "walk_away", "shadow_step"] },
    ],
  },
  environment: {
    id: "environment", btn: "💡 光影", label: "💡 光影",
    tip: "自然光 / 人造光 / 特效光 / 氛围色调",
    subs: [
      { id: "natural", label: "自然光", keys: [
        "window_sun", "golden_hour", "natural_light", "rim_light", "backlight", "top_light",
        "side_light", "moonlight", "moon_curtain", "starlight", "aurora", "lightning", "stormy_sky",
        "foggy_dawn", "morning_rays", "sunrise_mountain", "sunset_sea", "desert_evening", "dusk_beach",
        "twilight", "snow_dusk", "autumn_forest",
        "snow_glow", "plum_light"] },
      { id: "artificial", label: "人造光", keys: [
        "soft_studio", "studio_softbox", "spotlight", "fluorescent", "industrial", "candle",
        "fireplace", "campfire", "lantern", "neon_city", "neon_rain", "warm_neon", "blue_neon",
        "police_lights", "emergency_red", "home_bedroom",
        "palace_lantern", "temple_candle", "oil_lamp"] },
      { id: "fx", label: "特效光", keys: [
        "cyberpunk_glow", "magic_lit", "enchanted_forest", "ethereal", "bioluminescence",
        "underwater_glow", "fireflies", "crystal_cave", "stained_glass", "apocalyptic",
        "sword_qi", "spirit_flow", "magic_array", "buddha_halo"] },
      { id: "tone", label: "氛围色调", keys: [
        "low_key", "high_key", "chiaroscuro", "light_shadow", "shadow_window", "cozy_warm",
        "forge_embers",
        "warm_tone", "cool_tone", "high_saturation", "morandi", "faded_film", "teal_orange",
        "ink_wash_tone"] },
    ],
  },
  background: {
    id: "background", btn: "🏞️ 背景", label: "🏞️ 背景",
    tip: "自然 / 建筑 / 室内 / 抽象纯色",
    subs: [
      { id: "nature", label: "自然", keys: [
        "village_rural", "village_mountain", "farmland", "vineyard", "wildflower", "meadow",
        "forest_mist", "forest_dense", "redwoods", "bamboo", "mountain_range", "snow_mountains",
        "desert_dunes", "desert_night", "ocean_storm", "beach_palm", "lake_mountain", "lake_misty",
        "river_sunset", "waterfall", "coral_reef", "underwater_reef", "ice_cave", "frozen_lake",
        "cave_entrance", "zen_garden", "greenhouse", "starry_sky", "cloud_sea",
        "bamboo_forest", "peach_grove", "immortal_mountain", "lotus_pond", "snow_pine_peak"] },
      { id: "architecture", label: "建筑", keys: [
        "street_old", "street_rain", "alley_graffiti", "alley_dark", "market", "night_market",
        "city_future", "skyscrapers", "city_skyline", "train_station", "subway", "harbor",
        "fishing_village", "castle_dark", "castle_courtyard", "palace_hall", "ballroom", "temple_ruins",
        "ruins_ancient", "warehouse", "theme_park", "museum",
        "jiangnan_watertown", "palace_red_wall", "paifang_gate", "garden_corridor", "ancient_inn", "bamboo_pavilion"] },
      { id: "indoor", label: "室内", keys: [
        "cozy_bed", "living_room", "bedroom_cozy", "kitchen", "cafe", "bar_vintage", "restaurant",
        "office", "control_room", "lab", "library", "bookshelves", "workshop", "spaceship",
        "space_station", "flower_shop", "clothing_store",
        "ancient_study", "shrine_hall", "ancient_bedroom", "tea_room"] },
      { id: "abstract", label: "抽象纯色", keys: [
        "studio_room", "white_backdrop", "black_backdrop", "gradient_backdrop", "bokeh_city",
        "bokeh_nature", "paper_texture",
        "seamless_paper", "studio_gray", "concrete_wall", "gradient_neon", "bokeh_lights",
        "water_ripple", "silk_fold", "glass_frost", "star_gradient", "geometric_bg", "mirror_room",
        "petals_bokeh", "xuan_paper", "ink_splash"] },
    ],
  },
};

/** 显示 / 拼装顺序（改这一行即可调整节点上 8 个按钮的顺序与成句顺序）
 *  当前：风格 → 视角 → 主体 → 姿态 → 装扮 → 道具 → 光影 → 背景（用户指定） */
const CAT_ORDER = ["prefix", "angle", "subject", "action", "clothes", "props", "environment", "background"];
const CATEGORIES = CAT_ORDER.map((id) => CATEGORY_DEFS[id]);
const ALL_CATS = CATEGORIES.map((c) => c.id);
const catOf = (id) => CATEGORIES.find((c) => c.id === id) || CATEGORIES[0];

/** 道具 ↔ 主体的关系词（6 列 × 5 行 = 30 个，多宫格标签式选择）
 *  中文前置（手拿折扇）、英文后置（a folding fan, held in the hand）→ 两种语言都通顺 */
const RELATIONS = [
  ["hold", "手拿", "held in the hand"],
  ["embrace", "怀抱", "cradled in the arms"],
  ["carry_back", "背负", "carried on the back"],
  ["step_on", "脚踩", "underfoot"],
  ["head_top", "头顶", "balanced on the head"],
  ["shoulder", "扛在肩上", "resting on the shoulder"],
  ["bite", "嘴叼", "held in the mouth"],
  ["both_hands", "双手捧", "cupped in both hands"],
  ["one_hand", "单手拎", "dangling from one hand"],
  ["chest", "抱在胸前", "held against the chest"],
  ["waist", "挂在腰间", "hanging at the waist"],
  ["back_waist", "佩在身后", "strapped behind the waist"],
  ["lift_high", "高举过头", "raised high overhead"],
  ["point_forward", "指向前方", "pointing forward"],
  ["on_ground", "立于地面", "standing on the ground"],
  ["stuck_ground", "插在地上", "stuck into the ground"],
  ["lean_wall", "靠墙而立", "leaning against a wall"],
  ["on_table", "摆在桌上", "lying on a table"],
  ["arm_pit", "夹在腋下", "tucked under the arm"],
  ["finger_spin", "指间旋转", "spinning between the fingers"],
  ["hang_side", "垂在身侧", "hanging at the side"],
  ["cross_body", "斜挎身上", "slung across the body"],
  ["writing", "掭笔在手", "held in the writing hand"],
  ["playing", "正在演奏", "being played"],
  ["pour", "倾壶而倒", "tilted to pour"],
  ["open_fan", "展开在手", "opened in the hand"],
  ["sheathed", "收入鞘中", "sheathed"],
  ["drawn", "拔出持握", "drawn from its sheath"],
  ["scatter", "扬手撒出", "scattered"],
  ["support", "杵地支撑", "planted as a support"],
];
const REL_MAP = RELATIONS.reduce((m, [id, zh, en]) => (m[id] = { id, zh, en }, m), {});
/** 取子类对象（subId 非法/缺失 → 第一个子类） */
const subOf = (cat, subId) => {
  const subs = (cat && cat.subs) || [];
  return subs.find((s) => s.id === subId) || subs[0] || { id: "", label: "", keys: [] };
};
// 节点表面的 6 个按钮 = 6 个分类各自一个面板
const PANEL_BUTTONS = CATEGORIES.map((c) => ({ key: c.id, label: c.btn, panel: c.id }));

const WORDS = {
  prefix: [
    ["photo_hd", "高清细节照片", "detailed high-resolution photo of"],
    ["snapshot_amateur", "业余快照风格", "candid amateur snapshot of"],
    ["documentary", "纪实摄影", "documentary photograph of"],
    ["cinematic", "电影质感剧照", "cinematic film still of"],
    ["commercial", "商业广告摄影", "commercial advertising shot of"],
    ["studio_portrait", "影棚人像", "studio portrait of"],
    ["fashion_editorial", "时尚杂志大片", "fashion editorial photo of"],
    ["vintage_film", "复古胶片摄影", "vintage analog film photograph of"],
    ["polaroid", "宝丽来即时成像", "polaroid instant photo of"],
    ["bw_photo", "黑白摄影", "black and white photograph of"],
    ["long_exposure", "长曝光摄影", "long exposure photograph of"],
    ["macro", "微距摄影", "macro photograph of"],
    ["aerial", "无人机航拍", "aerial drone shot of"],
    ["wide_angle", "广角镜头", "wide-angle lens shot of"],
    ["fisheye", "鱼眼镜头", "fisheye lens shot of"],
    ["tilt_shift", "移轴摄影", "tilt-shift photograph of"],
    ["infrared", "红外摄影", "infrared photograph of"],
    ["double_exposure", "双重曝光", "double exposure photo of"],
    ["high_speed", "高速运动摄影", "high-speed action photo of"],
    ["phone_night", "夜间手机拍摄", "night phone snapshot of"],
    ["anime_frame", "日式动画赛璐璐", "cel-shaded anime frame of"],
    ["anime_movie", "动画电影剧照", "animated feature film still of"],
    ["comic_panel", "美式漫画分镜", "american comic book panel of"],
    ["manga_line", "漫画黑白线稿", "manga line art illustration of"],
    ["cg3d_toon", "3D 卡通渲染", "3D toon-shaded render of"],
    ["pixar3d", "皮克斯风格渲染", "Pixar-style 3D render of"],
    ["cyberpunk_art", "赛博朋克插画", "cyberpunk illustration of"],
    ["steampunk_art", "蒸汽朋克插画", "steampunk illustration of"],
    ["oil_painting", "油画布面", "oil painting on canvas of"],
    ["watercolor", "水彩插画", "watercolor illustration of"],
    ["ink_wash", "水墨写意", "ink wash painting of"],
    ["pencil_sketch", "铅笔素描", "pencil sketch of"],
    ["charcoal", "炭笔速写", "charcoal sketch of"],
    ["colored_pencil", "彩铅手绘", "colored pencil drawing of"],
    ["crayon", "蜡笔涂鸦", "crayon doodle of"],
    ["concept_art", "概念设定图", "concept art of"],
    ["game_keyart", "游戏原画", "game key art of"],
    ["character_sheet", "角色设定图", "character design sheet of"],
    ["stop_motion_clay", "粘土定格动画", "claymation stop-motion still of"],
    ["paper_cutout", "剪纸拼贴", "paper cutout collage of"],
    ["flat_vector", "矢量扁平插画", "flat vector illustration of"],
    ["pixel_art", "像素风", "pixel art of"],
    ["low_poly", "低多边形", "low-poly render of"],
    ["vaporwave", "蒸汽波美学", "vaporwave aesthetic image of"],
    ["pop_art", "波普艺术海报", "pop art poster of"],
    ["art_nouveau", "新艺术运动装饰", "art nouveau decorative artwork of"],
    ["ukiyo_e", "浮世绘木刻版画", "ukiyo-e woodblock print of"],
    ["dunhuang", "敦煌壁画", "Dunhuang mural style artwork of"],
    ["porcelain", "青花瓷纹样", "blue-and-white porcelain pattern artwork of"],
    ["gongbi", "工笔重彩", "gongbi fine-brush painting of"],
    ["shadow_puppet", "皮影戏造型", "shadow puppet style artwork of"],
    ["product_still", "产品静物摄影", "product still-life photograph of"],
    ["food_photo", "美食摄影", "food photography of"],
  ],
  subject: [
    ["man", "一位男性", "a man"],
    ["woman", "一位女性", "a woman"],
    ["young_man", "一位青年男子", "a young man"],
    ["young_woman", "一位青年女子", "a young woman"],
    ["handsome_man", "一位英俊男子", "a handsome man"],
    ["beautiful_woman", "一位美丽女子", "a beautiful woman"],
    ["elderly", "一位老人", "an elderly person"],
    ["boy", "一个男孩", "a boy"],
    ["girl", "一个女孩", "a girl"],
    ["baby", "一名婴儿", "a baby"],
    ["suit_man", "一位西装男士", "a man in a suit"],
    ["cheongsam_woman", "一位旗袍女子", "a woman in a cheongsam"],
    ["wuxia_swordsman", "一位古装侠客", "a wuxia swordsman in period costume"],
    ["hanfu_girl", "一位汉服少女", "a young woman in hanfu"],
    ["maid", "一位女仆", "a maid"],
    ["nurse", "一位护士", "a nurse"],
    ["doctor", "一位医生", "a doctor"],
    ["officer", "一位警察", "a police officer"],
    ["soldier", "一位军人", "a soldier"],
    ["teacher", "一位教师", "a teacher"],
    ["scientist", "一位科学家", "a scientist"],
    ["wizard", "一位魔法师", "a wizard"],
    ["witch", "一位女巫", "a witch"],
    ["knight", "一位骑士", "a knight"],
    ["princess", "一位公主", "a princess"],
    ["prince", "一位王子", "a prince"],
    ["king", "一位国王", "a king"],
    ["ninja", "一位忍者", "a ninja"],
    ["samurai", "一位武士", "a samurai"],
    ["assassin", "一位刺客", "an assassin"],
    ["mechanic", "一位机械师", "a mechanic"],
    ["programmer", "一位程序员", "a programmer"],
    ["chef", "一位厨师", "a chef"],
    ["dancer", "一位舞者", "a dancer"],
    ["singer", "一位歌手", "a singer"],
    ["musician", "一位乐手", "a musician"],
    ["athlete", "一位运动员", "an athlete"],
    ["astronaut", "一位宇航员", "an astronaut"],
    ["cyborg", "一位半机械人", "a cyborg"],
    ["robot", "一个机器人", "a robot"],
    ["cat", "一只猫", "a cat"],
    ["dog", "一只狗", "a dog"],
    ["fox", "一只狐狸", "a fox"],
    ["wolf", "一只狼", "a wolf"],
    ["tiger", "一只老虎", "a tiger"],
    ["dragon", "一条龙", "a dragon"],
    ["phoenix", "一只凤凰", "a phoenix"],
    ["rabbit", "一只兔子", "a rabbit"],
    ["bird", "一只小鸟", "a small bird"],
    ["horse", "一匹马", "a horse"],
    ["whale", "一头鲸鱼", "a whale"],
    ["butterfly", "一只蝴蝶", "a butterfly"],
    ["monster", "一个怪物", "a monster"],
    ["fairy", "一个妖精", "a fairy"],
    ["ghost", "一个幽灵", "a ghost"],
    ["puppet", "一个木偶", "a puppet"],
    ["toy", "一个玩具", "a toy"],
    ["product", "一件产品", "a product"],
    ["buddha", "一尊佛像", "a buddha statue"],
    ["bouquet", "一束花", "a bouquet of flowers"],
    ["statue", "一座雕像", "a statue"],
    ["abstract_shapes", "一组抽象形体", "abstract shapes"],
  ],
  action: [
    ["look_viewer", "看向镜头", "looking at the viewer"],
    ["look_away", "望向别处", "looking away"],
    ["look_up", "抬头仰望", "looking up"],
    ["look_down", "低头俯视", "looking down"],
    ["look_back", "回头回望", "looking back over the shoulder"],
    ["mouth_open", "张着嘴", "open mouth"],
    ["mouth_half", "微张着嘴", "slightly parted lips"],
    ["mouth_closed", "紧闭双唇", "closed mouth"],
    ["eyes_open", "睁大双眼", "eyes wide open"],
    ["eyes_half", "半闭双眼", "half-closed eyes"],
    ["eyes_closed", "闭着眼睛", "closed eyes"],
    ["wink", "眨眼", "winking"],
    ["squint", "眯着眼睛", "squinting"],
    ["smile", "微笑", "smiling"],
    ["laugh", "大笑", "laughing out loud"],
    ["smile_soft", "微笑不语", "a gentle smile"],
    ["sad", "悲伤的神情", "a sad expression"],
    ["angry", "愤怒的神情", "an angry expression"],
    ["surprised", "惊讶的神情", "a surprised expression"],
    ["pensive", "沉思的神情", "a pensive expression"],
    ["blank", "面无表情", "an expressionless face"],
    ["frown", "皱着眉头", "frowning"],
    ["blush", "脸红", "blushing"],
    ["teary", "眼中含泪", "tearing up"],
    ["bite_lip", "咬着嘴唇", "biting the lip"],
    ["standing", "站立", "standing"],
    ["sitting", "端坐", "sitting"],
    ["sitting_side", "侧坐", "sitting sideways"],
    ["lying", "躺卧", "lying down"],
    ["bent", "俯身", "bent forward"],
    ["kneeling", "单膝跪地", "kneeling on one knee"],
    ["walking", "行走", "walking"],
    ["running", "奔跑", "running"],
    ["jumping", "跳跃", "jumping"],
    ["climbing", "攀爬", "climbing"],
    ["swimming", "游泳", "swimming"],
    ["flying", "飞翔", "flying"],
    ["falling", "下落", "falling"],
    ["floating", "漂浮", "floating"],
    ["dancing", "舞蹈", "dancing"],
    ["spinning", "旋转", "spinning"],
    ["leaning_back", "后仰", "leaning back"],
    ["reaching", "伸手", "reaching out a hand"],
    ["waving", "挥手", "waving"],
    ["crossed_arms", "抱臂", "crossing the arms"],
    ["hands_hips", "叉腰", "hands on hips"],
    ["hands_pockets", "双手插兜", "hands in pockets"],
    ["chin_hand", "托腮", "resting the chin on one hand"],
    ["touch_hair", "撩头发", "adjusting the hair"],
    ["raise_weapon", "举起武器", "raising a weapon"],
    ["draw_sword", "拔剑", "drawing a sword"],
    ["swing_sword", "挥剑", "swinging a sword"],
    ["aim_gun", "举枪瞄准", "aiming a gun"],
    ["cast_spell", "施放魔法", "casting a spell"],
    ["draw_bow", "拉弓射箭", "drawing a bow"],
    ["clench_fist", "握拳", "clenching a fist"],
    ["clapping", "击掌", "clapping"],
    ["thumbs_up", "竖起大拇指", "giving a thumbs up"],
    ["heart_hands", "比心", "making a heart with both hands"],
    ["shade_eyes", "手搭凉棚", "shading the eyes with one hand"],
    ["hold_cup", "捧着杯子", "holding a cup"],
    ["reading", "低头阅读", "reading a book"],
    ["using_phone", "操作手机", "using a phone"],
    ["typing", "敲击键盘", "typing on a keyboard"],
    ["drawing_art", "执笔绘画", "drawing"],
    ["playing_instrument", "弹奏乐器", "playing an instrument"],
    ["glance_smile", "回眸一笑", "glancing back with a smile"],
    ["lean_wall", "靠着墙壁", "leaning against a wall"],
    ["crouching", "蹲下", "crouching"],
    ["facing_away", "背对镜头", "facing away from the camera"],
    ["frozen_sprint", "奔跑中的定格瞬间", "frozen mid-sprint"],
  ],
  clothes: [
    ["casual", "日常便装", "casual wear"],
    ["dress", "连衣裙", "a dress"],
    ["long_dress", "长裙", "a long dress"],
    ["short_dress", "短连衣裙", "a short dress"],
    ["skirt", "半身裙", "a skirt"],
    ["layered_skirt", "层叠裙摆", "a layered skirt"],
    ["shirt", "衬衫", "a shirt"],
    ["white_shirt", "白衬衫", "a white shirt"],
    ["blouse", "女式衬衣", "a blouse"],
    ["plaid_shirt", "格纹衬衫", "a plaid shirt"],
    ["striped_top", "条纹上衣", "a striped top"],
    ["sweater", "毛衣", "a sweater"],
    ["turtleneck", "高领毛衣", "a turtleneck"],
    ["cardigan", "针织开衫", "a knit cardigan"],
    ["hoodie", "连帽卫衣", "a hoodie"],
    ["jacket", "夹克", "a jacket"],
    ["leather_jacket", "皮夹克", "a leather jacket"],
    ["denim_jacket", "牛仔外套", "a denim jacket"],
    ["embroidered_jacket", "刺绣外套", "an embroidered jacket"],
    ["coat", "大衣", "a coat"],
    ["trench_coat", "风衣", "a trench coat"],
    ["down_jacket", "羽绒服", "a down jacket"],
    ["suit", "西装套装", "a tailored suit"],
    ["vest", "马甲", "a vest"],
    ["tank_top", "背心", "a tank top"],
    ["tshirt", "T 恤", "a T-shirt"],
    ["crop_top", "短款上衣", "a crop top"],
    ["lace_top", "蕾丝上衣", "a lace top"],
    ["jeans", "牛仔裤", "jeans"],
    ["ripped_jeans", "破洞牛仔裤", "ripped jeans"],
    ["trousers", "长裤", "trousers"],
    ["cargo_pants", "工装裤", "cargo pants"],
    ["shorts", "短裤", "shorts"],
    ["sweatpants", "运动裤", "sweatpants"],
    ["loose_sweatpants", "宽松卫裤", "loose sweatpants"],
    ["leggings", "打底裤", "leggings"],
    ["overalls", "背带裤", "overalls"],
    ["jumpsuit", "连体服", "a jumpsuit"],
    ["swimsuit", "泳装", "a swimsuit"],
    ["swim_trunks", "泳裤", "swim trunks"],
    ["tracksuit", "运动服", "a tracksuit"],
    ["school_uniform", "校服", "a school uniform"],
    ["military_uniform", "军装", "a military uniform"],
    ["nurse_uniform", "护士服", "a nurse uniform"],
    ["maid_outfit", "女仆装", "a maid outfit"],
    ["kimono", "和服", "a kimono"],
    ["yukata", "浴衣", "a yukata"],
    ["hanfu", "汉服", "hanfu"],
    ["cheongsam", "旗袍", "a cheongsam"],
    ["tang_suit", "唐装", "a tang suit"],
    ["hanbok", "韩服", "a hanbok"],
    ["period_robe", "古装长袍", "a period robe"],
    ["floor_robe", "拖地长袍", "a floor-length robe"],
    ["monk_robe", "僧袍", "a monk's robe"],
    ["nun_habit", "修女服", "a nun's habit"],
    ["wizard_robe", "法师长袍", "a wizard robe"],
    ["knight_armor", "骑士铠甲", "knight armor"],
    ["leather_armor", "轻型皮甲", "light leather armor"],
    ["cloak", "斗篷", "a cloak"],
    ["cape", "披风", "a cape"],
    ["scarf", "围巾", "a scarf"],
    ["fur_shawl", "皮草披肩", "a fur shawl"],
    ["gloves", "手套", "gloves"],
    ["mittens", "连指手套", "mittens"],
    ["belt", "腰带", "a belt"],
    ["apron", "花边围裙", "a frilled apron"],
    ["necktie", "领带", "a necktie"],
    ["bow_tie", "领结", "a bow tie"],
    ["necklace", "项链", "a necklace"],
    ["choker", "项圈", "a choker"],
    ["pendant", "吊坠", "a pendant"],
    ["earring", "耳环", "earrings"],
    ["ring", "戒指", "a ring"],
    ["bracelet", "手镯", "a bracelet"],
    ["watch", "手表", "a wristwatch"],
    ["brooch", "胸针", "a brooch"],
    ["hat", "帽子", "a hat"],
    ["baseball_cap", "棒球帽", "a baseball cap"],
    ["beanie", "针织帽", "a beanie"],
    ["bucket_hat", "渔夫帽", "a bucket hat"],
    ["straw_hat", "草帽", "a straw hat"],
    ["fedora", "礼帽", "a fedora"],
    ["witch_hat", "尖顶女巫帽", "a pointed witch hat"],
    ["crown", "皇冠", "a crown"],
    ["hair_clip", "发夹", "a hair clip"],
    ["hairband", "发带", "a hairband"],
    ["hair_tie", "发绳", "a hair tie"],
    ["hair_ribbon", "蝴蝶结发饰", "a hair ribbon"],
    ["socks", "袜子", "socks"],
    ["stockings", "长筒袜", "stockings"],
    ["tights", "连裤袜", "tights"],
    ["sneakers", "运动鞋", "sneakers"],
    ["canvas_shoes", "帆布鞋", "canvas shoes"],
    ["leather_shoes", "皮鞋", "leather shoes"],
    ["high_heels", "高跟鞋", "high heels"],
    ["boots", "靴子", "boots"],
    ["knee_boots", "长筒靴", "knee-high boots"],
    ["combat_boots", "马丁靴", "combat boots"],
    ["suede_boots", "麂皮长靴", "suede boots"],
    ["sandals", "凉鞋", "sandals"],
    ["slippers", "拖鞋", "slippers"],
    ["geta", "木屐", "geta sandals"],
    ["snow_boots", "雪地靴", "snow boots"],
    ["rain_boots", "防水雨靴", "rain boots"],
    ["wedding_dress", "婚纱", "a wedding dress"],
    ["evening_gown", "晚礼服", "an evening gown"],
    ["tailcoat", "燕尾服", "a tailcoat"],
    ["silk_gown", "丝绸礼服", "a silk gown"],
    ["off_shoulder", "露肩礼服", "an off-shoulder dress"],
    ["backless_dress", "露背礼服", "a backless dress"],
    ["corset_dress", "束腰长裙", "a corset dress"],
    ["floral_dress", "印花连衣裙", "a floral dress"],
    ["lace_trim", "蕾丝边饰", "lace trim"],
    ["space_suit", "太空服", "a space suit"],
    ["mecha_suit", "机甲驾驶服", "a mecha pilot suit"],
    ["diving_suit", "潜水服", "a diving suit"],
    ["hazmat_suit", "防护服", "a hazmat suit"],
    ["hospital_gown", "病号服", "a hospital gown"],
    ["bathrobe", "睡袍", "a bathrobe"],
    ["pajamas", "睡衣", "pajamas"],
  ],
  environment: [
    ["window_sun", "窗外阳光", "sunshine from the window"],
    ["golden_hour", "黄金时刻", "golden hour lighting"],
    ["natural_light", "自然光", "natural lighting"],
    ["soft_studio", "柔和影棚光", "soft studio lighting"],
    ["rim_light", "轮廓逆光", "rim backlight"],
    ["backlight", "逆光剪影", "backlit silhouette"],
    ["top_light", "顶光", "top lighting"],
    ["side_light", "侧光", "side lighting"],
    ["low_key", "低调暗光", "low-key lighting"],
    ["high_key", "高调亮光", "high-key lighting"],
    ["chiaroscuro", "明暗对照", "chiaroscuro lighting"],
    ["light_shadow", "光影交错", "light and shadow interplay"],
    ["shadow_window", "窗棂投影", "shadow cast from the window"],
    ["candle", "烛光", "candlelight"],
    ["fireplace", "壁炉暖光", "warm light from a fireplace"],
    ["campfire", "篝火光", "campfire light"],
    ["lantern", "灯笼光", "lantern light"],
    ["neon_city", "霓虹夜色", "neon night in the city"],
    ["neon_rain", "雨中霓虹", "neon reflections in the rain"],
    ["warm_neon", "暖调霓虹", "neon lighting with a warm cinematic tone"],
    ["cyberpunk_glow", "赛博朋克辉光", "sci-fi RGB glowing light"],
    ["blue_neon", "蓝色霓虹", "blue neon light"],
    ["police_lights", "警灯闪烁", "red and blue police lights in the rain"],
    ["emergency_red", "应急红光", "red glow from emergency lights"],
    ["fluorescent", "荧光灯", "fluorescent office lighting"],
    ["industrial", "冷硬工业光", "harsh industrial lighting"],
    ["spotlight", "聚光灯", "a harsh spotlight in a dark room"],
    ["studio_softbox", "柔光箱", "softbox studio lighting"],
    ["moonlight", "月光", "moonlight"],
    ["moon_curtain", "月光透过窗帘", "moonlight through the curtains"],
    ["starlight", "星光", "starlight"],
    ["aurora", "极光", "aurora borealis glow"],
    ["lightning", "闪电瞬间", "a lightning flash in a storm"],
    ["stormy_sky", "暴风雨天光", "stormy sky lighting"],
    ["foggy_dawn", "雾中黎明", "foggy forest at dawn"],
    ["morning_rays", "清晨光束", "early morning rays"],
    ["sunrise_mountain", "山间日出", "sunrise in the mountains"],
    ["sunset_sea", "海上日落", "sunset over the sea"],
    ["desert_evening", "沙漠黄昏", "evening glow in the desert"],
    ["dusk_beach", "黄昏海滩", "dusky evening on a beach"],
    ["twilight", "黄昏微光", "mysterious twilight with heavy mist"],
    ["fireflies", "萤火微光", "fireflies lighting up a summer night"],
    ["underwater_glow", "水下光斑", "underwater glow from the deep sea"],
    ["bioluminescence", "生物荧光", "bioluminescent glow"],
    ["magic_lit", "魔法光辉", "magic lit ambience"],
    ["enchanted_forest", "幽光森林", "mystical glow in an enchanted forest"],
    ["ethereal", "空灵光晕", "ethereal glow"],
    ["cozy_warm", "温馨暖调", "cozy warm ambience"],
    ["home_bedroom", "居家卧室暖光", "warm atmosphere at home in a bedroom"],
    ["stained_glass", "彩窗透光", "soft light through stained glass"],
    ["apocalyptic", "末世烟尘光", "apocalyptic smoky atmosphere"],
    ["snow_dusk", "雪天暮色", "gentle snowfall at dusk"],
    ["autumn_forest", "秋日林间光", "vibrant autumn lighting in a forest"],
    ["crystal_cave", "水晶洞穴反光", "crystal reflections in a cave"],
    ["forge_embers", "锻炉余烬", "glowing embers from a forge"],
  ],
  background: [
    ["cozy_bed", "温馨床铺与台灯", "a cozy bed and a lamp"],
    ["living_room", "现代客厅与壁炉", "a modern living room with a fireplace"],
    ["bedroom_cozy", "舒适卧室", "a cozy bedroom"],
    ["kitchen", "明亮厨房", "a bright kitchen"],
    ["cafe", "热闹咖啡馆", "a bustling cafe"],
    ["bar_vintage", "复古酒吧", "a dimly lit vintage bar"],
    ["restaurant", "精致餐厅", "an elegant restaurant"],
    ["office", "现代办公室", "a modern office"],
    ["control_room", "高科技控制室", "a high-tech control room"],
    ["lab", "发光屏幕实验室", "a futuristic lab with glowing screens"],
    ["library", "安静图书馆一角", "a peaceful library corner"],
    ["bookshelves", "书架与绿植", "bookshelves and plants"],
    ["street_old", "老石板街", "an old cobblestone street"],
    ["street_rain", "雨中街道", "a bustling urban street in the rain"],
    ["alley_graffiti", "涂鸦小巷", "a narrow alley with graffiti walls"],
    ["alley_dark", "昏暗小巷", "a dark narrow alley"],
    ["market", "热闹集市", "a bustling marketplace"],
    ["night_market", "露天夜市", "a bustling open-air night market"],
    ["city_future", "未来都市", "a futuristic cityscape"],
    ["skyscrapers", "高楼霓虹", "tall skyscrapers and neon signs"],
    ["city_skyline", "城市天际线", "a city skyline"],
    ["train_station", "蒸汽火车站", "an old train station with steam"],
    ["subway", "地铁站台", "a subway platform"],
    ["harbor", "繁忙港湾", "a bustling harbor with boats"],
    ["fishing_village", "码头小渔村", "a small fishing village on a pier"],
    ["village_rural", "宁静乡村", "a quiet rural village"],
    ["village_mountain", "山间村庄", "a quiet mountain village at dawn"],
    ["farmland", "起伏农田", "rolling hills and farmland"],
    ["vineyard", "乡间葡萄园", "a vineyard in the countryside"],
    ["wildflower", "野花原野", "a sprawling field of wildflowers"],
    ["meadow", "阳光草甸", "a sunlit meadow"],
    ["forest_mist", "薄雾林间空地", "a forest clearing with mist"],
    ["forest_dense", "茂密丛林", "a dense jungle filtering sunlight"],
    ["redwoods", "巨杉森林", "a dense forest of towering redwoods"],
    ["bamboo", "竹林小径", "a bamboo forest path"],
    ["mountain_range", "连绵山脉", "a picturesque mountain range"],
    ["snow_mountains", "远处雪山", "snow-capped mountains in the distance"],
    ["desert_dunes", "沙漠沙丘", "rolling sand dunes in a desert"],
    ["desert_night", "沙漠星空", "a starry sky over the desert"],
    ["ocean_storm", "暴风海浪", "a stormy ocean with crashing waves"],
    ["beach_palm", "棕榈海滩", "a sandy beach with palm trees"],
    ["lake_mountain", "群山湖泊", "a tranquil lake with mountains"],
    ["lake_misty", "雾中湖泊", "a misty lake surrounded by trees"],
    ["river_sunset", "日落河岸", "a serene riverbank at sunset"],
    ["waterfall", "林间瀑布", "a tranquil waterfall surrounded by trees"],
    ["coral_reef", "珊瑚礁", "a vibrant coral reef"],
    ["underwater_reef", "海底世界", "an underwater reef with colorful fish"],
    ["ice_cave", "冰晶洞窟", "an ice cave with sparkling crystals"],
    ["frozen_lake", "结冰湖面", "a frozen lake with ice formations"],
    ["cave_entrance", "神秘洞口", "a mysterious cave entrance"],
    ["castle_dark", "阴暗古堡", "a dark abandoned castle"],
    ["castle_courtyard", "月下城堡庭院", "a castle courtyard under moonlight"],
    ["palace_hall", "华丽宫殿大厅", "an ornate palace hall"],
    ["ballroom", "优雅舞厅", "an elegant grand ballroom"],
    ["temple_ruins", "古庙遗迹", "an ancient temple in ruins"],
    ["ruins_ancient", "远古文明废墟", "the ruins of an ancient civilization"],
    ["warehouse", "废弃仓库", "an abandoned warehouse"],
    ["theme_park", "废弃游乐园", "an abandoned theme park"],
    ["workshop", "杂乱工坊", "the cluttered workshop of an inventor"],
    ["spaceship", "未来飞船内部", "the interior of a futuristic spaceship"],
    ["space_station", "空间站舷窗", "a space station window"],
    ["zen_garden", "枯山水庭院", "a peaceful zen garden with a koi pond"],
    ["greenhouse", "玻璃温室", "a glass greenhouse"],
    ["flower_shop", "街角花店", "a corner flower shop"],
    ["clothing_store", "时装店橱窗", "a fashion boutique window"],
    ["museum", "博物馆展厅", "a museum gallery"],
    ["studio_room", "摄影棚背景", "a photography studio backdrop"],
    ["white_backdrop", "纯白背景", "a plain white background"],
    ["black_backdrop", "纯黑背景", "a plain black background"],
    ["gradient_backdrop", "渐变色背景", "a smooth gradient backdrop"],
    ["bokeh_city", "都市虚化光斑", "a blurry city bokeh background"],
    ["bokeh_nature", "自然虚化背景", "a blurred natural bokeh background"],
    ["paper_texture", "纸纹背景", "a textured paper background"],
    ["starry_sky", "繁星夜空", "a starry night sky"],
    ["cloud_sea", "云海之上", "above a sea of clouds"],
  ],
};

/* ============================================================
 *  新增词条（补充各子类，老词条与它们的 key 全部保持不变）
 *  合并规则：同上 key 已存在则保留老词条（不会重复、不会覆盖）
 * ============================================================ */
const WORDS_ADD = {
  prefix: [
    ["anime_sakuga", "日式作画爆点", "an explosive anime sakuga key frame"],
    ["anime_tv", "番剧截图", "a TV anime screenshot"],
    ["anime_lite", "轻小说插画", "a light-novel style illustration"],
    ["galgame_cg", "日式游戏立绘", "a visual-novel character CG"],
    ["chibi", "Q 版造型", "a chibi style character"],
    ["webtoon", "韩式网漫", "a Korean webtoon panel"],
    ["us_comic", "美漫厚涂", "a western comic painted style"],
    ["ink_comic", "国漫水墨线描", "a Chinese manhua ink style"],
    ["ue5_render", "虚幻引擎写实渲染", "a photoreal Unreal Engine 5 render"],
    ["blender_pbr", "三维 PBR 渲染", "a PBR-rendered 3D scene"],
    ["clay_render", "黏土材质渲染", "a clay-material 3D render"],
    ["isometric", "等距视角 3D", "an isometric 3D illustration"],
    ["voxel", "体素方块风", "a voxel art style"],
    ["miniature", "微缩模型效果", "a miniature model look"],
    ["game_cinematic", "游戏 CG 过场", "a cinematic game CG frame"],
    ["toy_render", "手办质感渲染", "a resin figure product render"],
    ["gouache", "水粉画", "a gouache painting"],
    ["acrylic", "丙烯厚涂", "an acrylic painting"],
    ["pastel", "粉彩画", "a soft pastel drawing"],
    ["ink_line", "钢笔线描", "an ink pen line drawing"],
    ["risograph", "孔版印刷风", "a risograph print style"],
    ["collage_art", "拼贴艺术", "a mixed-media collage"],
    ["neon_sign", "霓虹灯管造型", "a neon sign style"],
    ["glass_art", "琉璃工艺风", "a stained-glass art style"],
    ["guofeng_hanfu_photo", "国风汉服写真", "a Chinese hanfu portrait photograph of"],
    ["gongbi_heavy", "工笔重彩", "a Chinese gongbi heavy-color painting of"],
    ["guochao_illustration", "国潮插画", "a Chinese guochao illustration of"],
    ["qinglv_shanshui", "青绿山水", "a Chinese blue-green shanshui landscape painting of"],
    ["xianxia_film", "仙侠特效大片", "a Chinese xianxia fantasy film still of"],
  ],
  clothes: [
    ["makeup_natural", "裸妆", "a clean natural makeup look"],
    ["makeup_red_lip", "红唇浓妆", "bold red lips"],
    ["makeup_smoky", "烟熏眼妆", "a smoky eye makeup"],
    ["makeup_goth", "哥特暗黑妆", "a gothic makeup look"],
    ["makeup_geisha", "艺伎白面妆", "a geisha white makeup"],
    ["makeup_freckles", "雀斑妆", "freckled makeup"],
    ["makeup_glitter", "亮片闪粉眼妆", "glittery eye makeup"],
    ["makeup_blush", "腮红妆", "flushed blush makeup"],
    ["face_tattoo", "面部纹身", "facial tattoos"],
    ["face_paint", "战术油彩脸谱", "face paint"],
    ["lip_gloss", "唇釉水光", "glossy lips"],
    ["korean_idol", "韩系爱豆妆", "a K-pop idol makeup"],
    ["backpack", "双肩背包", "a backpack"],
    ["handbag", "手提包", "a handbag"],
    ["crossbody", "斜挎小包", "a crossbody bag"],
    ["tote", "帆布托特包", "a canvas tote bag"],
    ["briefcase", "公文包", "a briefcase"],
    ["leather_satchel", "皮质邮差包", "a leather satchel"],
    ["waist_pack", "腰包", "a waist pack"],
    ["school_bag", "学生书包", "a school backpack"],
    ["basket_bag", "竹编提篮", "a woven basket"],
    ["pouch", "随身小袋", "a small pouch"],
    ["luggage", "旅行箱", "a rolling suitcase"],
    ["quiver", "箭袋", "a quiver"],
    ["hairpin_jade", "玉簪子", "a jade hairpin"],
    ["buyao", "步摇", "a golden buyao hair ornament"],
    ["guan_jin", "束发金冠", "a golden hair crown"],
    ["mo_e", "抹额", "an embroidered forehead band"],
    ["zan_hua", "簪花", "a flower hairpin"],
    ["huadian", "花钿", "a huadian forehead ornament"],
    ["dai_mei", "远山黛眉", "distant-mountain dark eyebrows"],
    ["taohua_zhuang", "桃花妆", "a peach-blossom makeup"],
    ["hanfu_top", "交领汉服上衣", "a crossed-collar hanfu robe"],
    ["daopao", "道袍", "a Chinese Daoist robe"],
    ["xiake_robe", "侠客劲装", "a fitted wuxia warrior robe"],
    ["daxiushan", "大袖衫", "a wide-sleeved Chinese gown"],
    ["ruqun", "齐胸襦裙", "a Chinese ruqun dress"],
    ["armor_chinese", "中国甲胄", "Chinese lamellar armor"],
    ["hechang", "鹤氅", "a crane-feather cloak"],
    ["mamian_skirt", "马面裙", "a Chinese mamian skirt"],
    ["baizhe_skirt", "百褶裙", "a pleated Chinese skirt"],
    ["denglong_ku", "灯笼裤", "Chinese lantern pants"],
    ["yuntou_lv", "云头履", "Chinese cloud-toe shoes"],
    ["xiuhua_shoes", "绣花鞋", "embroidered Chinese shoes"],
    ["xiapi", "霞帔", "an embroidered xiapi shawl"],
  ],
  subject: [
    ["tree_pine", "高大松树", "a tall pine tree"],
    ["cherry_blossom", "盛开的樱花", "blooming cherry blossoms"],
    ["rose", "玫瑰花", "a blooming rose"],
    ["sunflower", "向日葵", "a sunflower"],
    ["lotus", "荷花", "a lotus flower"],
    ["tropical_leaf", "热带阔叶", "tropical broad leaves"],
    ["moss", "苔藓", "moss"],
    ["vine", "藤蔓", "hanging vines"],
    ["bonsai", "盆栽", "a bonsai tree"],
    ["maple_leaf", "枫叶", "maple leaves"],
    ["wheat", "金色麦穗", "golden wheat ears"],
    ["succulent", "多肉植物", "a succulent plant"],
    ["book_stack", "一摞旧书", "a stack of old books"],
    ["coffee_cup", "咖啡杯", "a coffee cup"],
    ["vintage_camera", "复古相机", "a vintage camera"],
    ["crystal_gem", "水晶宝石", "a glowing crystal gem"],
    ["lantern_object", "一盏灯笼", "a paper lantern"],
    ["paper_plane", "纸飞机", "a paper plane"],
    ["vinyl_record", "黑胶唱片", "a vinyl record"],
    ["pocket_watch", "怀表", "a pocket watch"],
    ["sword_object", "一把长剑", "a longsword"],
    ["food_dish", "一盘食物", "a plated dish"],
    ["car_object", "一辆汽车", "a car"],
    ["potion_bottle", "魔法药水瓶", "a potion bottle"],
    ["angel", "天使", "an angel"],
    ["demon", "恶魔", "a demon"],
    ["elf", "精灵", "an elf"],
    ["orc", "兽人", "an orc"],
    ["slime", "史莱姆", "a slime creature"],
    ["mecha", "巨型机甲", "a giant mecha"],
    ["undead", "亡魂战士", "an undead warrior"],
    ["kirin", "麒麟", "a kirin"],
    ["nine_tail_fox", "九尾狐", "a nine-tailed fox"],
    ["spirit_beast", "白虎灵兽", "a spirit beast"],
    ["golem", "岩石傀儡", "a stone golem"],
    ["alien", "外星生物", "an alien creature"],
    ["daoshi", "道人", "a Chinese Daoist priest"],
    ["xiannv", "仙子", "a Chinese fairy maiden"],
    ["nvxia", "江湖女侠", "a jianghu swordswoman"],
    ["shusheng", "古风书生", "a Chinese scholar in robes"],
    ["crane", "白鹤", "a white crane"],
    ["jade_rabbit", "玉兔", "a jade rabbit"],
    ["sika_deer", "梅花鹿", "a sika deer"],
    ["panda", "熊猫", "a giant panda"],
    ["plum_blossom", "梅花", "plum blossoms"],
    ["orchid", "兰花", "an orchid"],
    ["chrysanthemum", "菊花", "chrysanthemums"],
    ["peony", "牡丹", "a peony"],
    ["ginkgo", "银杏叶", "ginkgo leaves"],
    ["incense_burner", "青铜香炉", "a bronze incense burner"],
    ["guqin", "古琴", "a guqin zither"],
    ["oil_paper_umbrella", "油纸伞", "an oil-paper umbrella"],
    ["porcelain_vase", "青花瓷瓶", "a blue-and-white porcelain vase"],
    ["weiqi_board", "围棋盘", "a go board"],
    ["dragon_east", "东方神龙", "a Chinese dragon"],
    ["mountain_spirit", "山中精怪", "a mountain spirit"],
  ],
  action: [
    ["stern_look", "溼然神色", "a stern resolute expression"],
    ["angry_glare", "嗔怒冷眼", "a cold angry glare"],
    ["calm_smile", "淡然浅笑", "a calm faint smile"],
    ["meditate_lotus", "盘膝打坐", "sitting cross-legged in meditation"],
    ["hands_behind", "负手而立", "standing with hands clasped behind the back"],
    ["stand_sword", "执剑而立", "standing upright holding a sword"],
    ["cupped_fist", "抱拳行礼", "a cupped-fist martial salute"],
    ["bow_salute", "拱手长揖", "a deep Chinese bow with hands clasped"],
    ["kneel_one_knee", "单膝跪地", "kneeling on one knee"],
    ["tai_chi", "打太极", "practicing tai chi"],
    ["hands_sleeves", "双手拢袖", "both hands tucked into the sleeves"],
    ["sword_dance", "舞剑", "performing a sword dance"],
    ["sword_slash", "挥剑劈砍", "swinging a sword downward"],
    ["cast_seal", "掉诀施法", "casting a spell with hand seals"],
    ["fly_sword", "御剑飞行", "flying on a sword"],
    ["sleeve_sweep", "拂袖", "a sweeping sleeve gesture"],
    ["ride_horse", "策马奔腾", "galloping on horseback"],
    ["sword_point", "剑指前方", "pointing a sword forward"],
    ["sheath_sword", "收剑入鞘", "sheathing the sword"],
    ["twin_swords", "双手双剑", "wielding twin swords"],
    ["spear_thrust", "挺枪突刺", "thrusting a spear"],
    ["palm_strike", "挥掌击出", "a palm strike"],
    ["flying_kick", "飞身踢击", "a flying kick"],
    ["martial_stance", "武术起手式", "a martial arts ready stance"],
    ["fan_dance", "舞扇", "dancing with a fan"],
    ["playing_guqin", "抚琴", "plucking a guqin"],
    ["ink_calligraphy", "挥毫泼墨", "writing calligraphy with a brush"],
    ["drink_wine", "举杯饮酒", "raising a cup of wine"],
    ["carry_umbrella", "撑伞而行", "walking while holding an oil-paper umbrella"],
    ["leap_air", "飞身跃起", "leaping into the air"],
    ["meditate_float", "凌空打坐", "meditating while levitating"],
    ["blink_flash", "身形一闪", "blurring away in a flash"],
    ["run_sprint", "全力奔跑", "sprinting at full speed"],
    ["walk_away", "转身离去", "walking away from the camera"],
    ["shadow_step", "踏影而行", "gliding with weightless shadow steps"],
  ],
  angle: [
    ["front_view", "正面视角", "a straight-on front view"],
    ["side_view", "侧面视角", "a side profile view"],
    ["three_quarter", "四分之三侧脸", "a three-quarter view"],
    ["back_view", "背面视角", "a rear view"],
    ["top_down", "俯视", "a top-down view"],
    ["low_angle", "仰视", "a low-angle view"],
    ["dutch_angle", "倾斜构图", "a dutch angle shot"],
    ["close_up", "面部特写", "a close-up on the face"],
    ["extreme_close", "极近特写", "an extreme close-up"],
    ["half_body", "半身构图", "a half-body framing"],
    ["full_body", "全身构图", "a full-body framing"],
    ["over_shoulder", "越肩视角", "an over-the-shoulder view"],
    ["from_above", "从高处向下", "viewed from above"],
    ["worm_eye", "虫眼贴地视角", "a worm's-eye view"],
    ["wide_shot", "广角远景", "a wide shot"],
    ["liubai_composition", "国风留白构图", "a traditional Chinese negative-space composition"],
    ["eye_level", "平视视角", "an eye-level view"],
    ["overhead_45", "45 度俯拍", "a 45-degree overhead shot"],
    ["hand_detail", "手部特写", "a close-up on the hands"],
    ["prop_detail", "道具特写", "a close-up on a prop"],
    ["reflection_view", "倒影构图", "framed through a reflection"],
    ["silhouette_view", "剪影构图", "a backlit silhouette composition"],
    ["frame_in_frame", "框中框构图", "a frame-within-a-frame composition"],
    ["foreground_blur", "前景虚化遮挡", "a blurred foreground element"],
    ["pov_first_person", "第一人称视角", "a first-person POV shot"],
    ["rule_of_thirds", "三分法构图", "a rule-of-thirds composition"],
    ["symmetrical_comp", "对称构图", "a symmetrical composition"],
    ["center_comp", "中心构图", "a centered composition"],
    ["leading_lines", "引导线构图", "leading-lines composition"],
  ],
  environment: [
    ["warm_tone", "暖色调", "a warm color tone"],
    ["cool_tone", "冷色调", "a cool color tone"],
    ["high_saturation", "高饱和鲜艳", "highly saturated colors"],
    ["morandi", "低饱和莫兰迪", "muted Morandi tones"],
    ["faded_film", "胶片褪色", "faded film colors"],
    ["teal_orange", "青橙电影调", "a teal and orange grade"],
    ["snow_glow", "雪地反光", "soft snow-bounce light"],
    ["plum_light", "梅枝疏影光", "dappled light through plum branches"],
    ["palace_lantern", "宫灯暖光", "warm palace lantern light"],
    ["temple_candle", "佛前烛光", "candlelight before a temple shrine"],
    ["oil_lamp", "油灯昏黄", "the dim glow of an oil lamp"],
    ["sword_qi", "剑气寒光", "cold sword-energy glow"],
    ["spirit_flow", "灵气流光", "flowing spiritual-energy light"],
    ["magic_array", "法阵辉光", "a glowing magic-array circle"],
    ["buddha_halo", "佛光金芒", "a golden halo of Buddha light"],
    ["ink_wash_tone", "水墨淡雅", "a muted ink-wash palette"],
  ],
  background: [
    ["seamless_paper", "无缝纸背景", "a seamless paper backdrop"],
    ["studio_gray", "中性灰棚拍", "a neutral gray studio backdrop"],
    ["concrete_wall", "水泥墙", "a concrete wall backdrop"],
    ["gradient_neon", "霓虹渐变", "a neon gradient background"],
    ["bokeh_lights", "虚化灯串", "blurred string-light bokeh"],
    ["water_ripple", "水波纹背景", "a water-ripple backdrop"],
    ["silk_fold", "丝绸褶皱", "a draped silk backdrop"],
    ["glass_frost", "磨砂玻璃", "a frosted glass backdrop"],
    ["star_gradient", "星空渐变", "a starry gradient sky"],
    ["geometric_bg", "几何色块", "a geometric color-block background"],
    ["mirror_room", "镜面反射房间", "a mirrored room"],
    ["petals_bokeh", "花瓣虚化", "falling petal bokeh"],
    ["bamboo_forest", "竹林秘境", "a dense bamboo grove"],
    ["peach_grove", "桃花林", "a peach blossom grove"],
    ["immortal_mountain", "云海仙山", "a misty immortal mountain above a sea of clouds"],
    ["lotus_pond", "荷塘", "a lotus pond"],
    ["snow_pine_peak", "雪松峰", "snow-covered pine peaks"],
    ["jiangnan_watertown", "江南水乡", "a Jiangnan water town with canals"],
    ["palace_red_wall", "红墙金瓦宫殿", "a Chinese palace with red walls and golden tiles"],
    ["paifang_gate", "仙门牌坊", "a Chinese ceremonial paifang gate"],
    ["garden_corridor", "园林回廊", "a Chinese garden corridor"],
    ["ancient_inn", "古时客栈", "an ancient Chinese inn"],
    ["bamboo_pavilion", "竹林凉亭", "a pavilion in a bamboo grove"],
    ["ancient_study", "古风书房", "a traditional Chinese study room"],
    ["shrine_hall", "佛堂", "a Chinese shrine hall"],
    ["ancient_bedroom", "古风卧房", "a traditional Chinese bedchamber"],
    ["tea_room", "茶室", "a Chinese tea room"],
    ["xuan_paper", "宣纸底纹", "a rice-paper texture backdrop"],
    ["ink_splash", "泼墨晕染", "an ink-splash wash backdrop"],
  ],
  props: [
    ["sword_chinese", "宝剑", "a Chinese straight sword (jian)"],
    ["spear_chinese", "长枪", "a Chinese spear"],
    ["sabre_chinese", "中国大刀", "a Chinese broadsword"],
    ["dagger", "匕首", "a dagger"],
    ["whip", "长鞭", "a long whip"],
    ["bow_arrow", "弓箭", "a bow and arrows"],
    ["hidden_dart", "暗器", "a concealed throwing dart"],
    ["round_shield", "圆盾", "a round shield"],
    ["halberd", "方天画戟", "a Chinese halberd"],
    ["iron_staff", "铁棍", "an iron staff"],
    ["fuchen", "拂尘", "a Daoist fly whisk"],
    ["talisman_paper", "符箓", "a Daoist paper talisman"],
    ["spirit_pearl", "灵珠", "a glowing spirit pearl"],
    ["ruyi_jade", "玉如意", "a jade ruyi scepter"],
    ["bronze_mirror", "铜镜", "a bronze mirror"],
    ["ritual_bell", "法铃", "a ritual bell"],
    ["prayer_beads", "念珠", "prayer beads"],
    ["wooden_fish", "木鱼", "a wooden fish drum"],
    ["folding_fan", "折扇", "a folding fan"],
    ["tuan_shan", "团扇", "a round silk fan"],
    ["jade_pendant", "玉佩", "a jade pendant"],
    ["xiangnang", "香囊", "an embroidered sachet"],
    ["ink_brush", "毛笔", "a Chinese ink brush"],
    ["scroll_painting", "画轴", "a hanging scroll painting"],
    ["bamboo_flute", "竹笛", "a bamboo flute"],
    ["go_board", "棋盘", "a go board with stones"],
    ["lantern_paper", "灯笼", "a hanging paper lantern"],
    ["wine_pot", "酒壶", "a wine pot"],
    ["gourd_flask", "酒葫芦", "a gourd flask"],
    ["tea_set", "茶具", "a Chinese tea set"],
    ["food_box", "食盒", "a tiered food box"],
    ["bamboo_case", "竹书箱", "a bamboo book case"],
    ["oil_silk_umbrella", "油纸伞", "an oil-paper umbrella"],
    ["copper_coins", "铜钱串", "a string of copper coins"],
  ],
};

// 合并（老词条不动；key 已存在则跳过 → 不重复、不覆盖）
for (const cat of ALL_CATS) {
  for (const item of (WORDS_ADD[cat] || [])) {
    const arr = WORDS[cat] || (WORDS[cat] = []);
    if (!arr.some((x) => x[0] === item[0])) arr.push(item);
  }
}

/** 词表完整性自检：返回问题清单（空数组 = 全部正常）。
 *  检查：① 每个子类的 key 都能在词表里找到 ② 同一 key 不重复出现在多个子类
 *  ③ 词表里的词条都被某个子类收录（不留孤儿） ④ 子类 key 全局唯一
 */
function verifyWordTable() {
  const bad = [];
  const owner = new Map();          // key -> "cat|sub"
  const seen = new Set();           // 词表里出现的 key
  for (const cat of ALL_CATS) {
    for (const [k] of (WORDS[cat] || [])) {
      if (seen.has(k)) bad.push(`词表内重复 key：${cat}|${k}`);
      seen.add(k);
    }
    for (const sub of (catOf(cat).subs || [])) {
      for (const k of (sub.keys || [])) {
        if (owner.has(k)) bad.push(`key 出现在多个子类：${k}（${owner.get(k)} 与 ${cat}|${sub.id}）`);
        else owner.set(k, `${cat}|${sub.id}`);
        if (!seen.has(k)) bad.push(`子类引用了不存在的词条：${cat}|${sub.id}|${k}`);
      }
    }
  }
  for (const k of seen) if (!owner.has(k)) bad.push(`词条未被任何子类收录：${k}`);
  return bad;
}

/** 词条索引：cat -> Map(key -> {key, zh, en, custom}) */
function buildIndex(words) {
  const idx = {};
  for (const cat of ALL_CATS) {
    const m = new Map();
    for (const [k, zh, en] of (WORDS[cat] || [])) m.set(k, { key: k, zh, en, custom: false });
    for (const it of (((words || {}).custom || {})[cat] || [])) {
      m.set(it.key, { key: it.key, zh: it.zh || "", en: it.en || "", custom: true });
    }
    idx[cat] = m;
  }
  return idx;
}

/* ============================================================
 *  无状态 UI 助手（与 asset_manager.js 同款观感）
 * ============================================================ */
function el(tag, css, text) {
  const e = document.createElement(tag);
  if (css) e.style.cssText = css;
  if (text !== undefined) e.textContent = text;
  return e;
}

const BOX_CSS = "background:#1d1d1d;color:#ccc;border:1px solid #444;border-radius:4px;padding:5px 8px;font-size:12px;box-sizing:border-box;font-family:inherit;";

function makeSectionTitle(text) {
  return el("div", "font-size:13px;font-weight:600;color:#9fc3e8;margin:14px 0 8px;padding-bottom:5px;border-bottom:1px solid #333;", text);
}

function field(labelText, control) {
  const g = el("div", "display:flex;align-items:center;gap:12px;margin-bottom:10px;");
  const lab = el("label", "flex:0 0 160px;font-size:13px;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;", labelText);
  control.style.flex = "1 1 0";
  control.style.minWidth = "0";
  g.append(lab, control);
  return g;
}

function selectControl(options, value, onChange) {
  const s = el("select", BOX_CSS + "min-width:0;");
  for (const o of options) {
    const v = (typeof o === "object" && o !== null && o.value !== undefined) ? String(o.value) : String(o);
    const t = (typeof o === "object" && o !== null && o.label) ? String(o.label) : String(o);
    const op = el("option", "", t);
    op.value = v;
    if (v === String(value)) op.selected = true;
    s.append(op);
  }
  s.addEventListener("change", () => onChange(s.value));
  return s;
}

function radioRow(options, value, onChange) {
  const row = el("div", "display:flex;align-items:center;gap:16px;flex-wrap:wrap;min-width:0;");
  const boxes = [];
  for (const o of options) {
    const val = (typeof o === "object" && o !== null && o.value !== undefined) ? String(o.value) : String(o);
    const label = (typeof o === "object" && o !== null && o.label) ? String(o.label) : String(o);
    const lab = el("label", "display:flex;align-items:center;gap:6px;font-size:13px;color:#999;cursor:pointer;user-select:none;");
    const c = el("input", "width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;");
    c.type = "checkbox";
    c.checked = String(value) === val;
    c.addEventListener("change", () => {
      if (c.checked) {
        boxes.forEach((x) => { if (x !== c) x.checked = false; });
        onChange(val);
      } else if (boxes.every((x) => !x.checked)) {
        c.checked = true;   // 至少保留一个选中
      }
    });
    lab.append(c, el("span", "", label));
    row.append(lab);
    boxes.push(c);
  }
  return row;
}

function textareaControl(value, onChange, css) {
  const t = el("textarea", BOX_CSS + "min-height:60px;resize:vertical;line-height:1.6;" + (css || ""));
  t.value = value || "";
  t.addEventListener("change", () => onChange(t.value));
  return t;
}

function checkboxControl(value, labelText, onChange, tip) {
  const w = el("label", "display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12px;color:#ddd;user-select:none;");
  const c = el("input", "width:16px;height:16px;accent-color:#f59e0b;cursor:pointer;");
  c.type = "checkbox";
  c.checked = !!value;
  if (tip) c.title = tip;
  c.addEventListener("change", () => onChange(c.checked));
  w.append(c, el("span", "", labelText));
  return w;
}

function smallBtn(text, css, tip, onClick) {
  const b = el("button", "border-radius:4px;padding:4px 9px;font-size:11px;cursor:pointer;white-space:nowrap;font-family:inherit;" + (css || ""), text);
  if (tip) b.title = tip;
  b.addEventListener("mousedown", (e) => e.stopPropagation());
  b.addEventListener("click", (e) => { e.stopPropagation(); if (onClick) onClick(e); });
  return b;
}

// ── 轻量通知 ──────────────────────────────────────────────
let toastBox = null;
function notify(msg, type = "success") {
  try {
    if (!toastBox) {
      toastBox = el("div", "position:fixed;right:16px;bottom:16px;z-index:100000;display:flex;flex-direction:column;gap:8px;align-items:flex-end;pointer-events:none;");
      document.body.appendChild(toastBox);
    }
    const palette = {
      success: ["#1f3d2a", "#7fd6a0", "#4caf50"],
      error: ["#3d1f1f", "#f0a0a0", "#e05555"],
      warning: ["#3d3520", "#f0d79a", "#d9a13b"],
    };
    const c = palette[type] || palette.success;
    const t = el("div", `background:${c[0]};color:${c[1]};border:1px solid ${c[2]};border-radius:6px;padding:8px 14px;font-size:12px;box-shadow:0 6px 20px rgba(0,0,0,.5);max-width:420px;white-space:pre-wrap;`, msg);
    toastBox.appendChild(t);
    setTimeout(() => { try { t.remove(); } catch (_) {} }, 2600);
  } catch (_) {}
}

// ── 字号 / 界面缩放（独立记忆，不与 asset_manager 共用） ──
const ZOOM_MIN = 8, ZOOM_MAX = 40;
let __zoom = null;
function zoomGet() {
  if (__zoom == null) {
    try { const v = parseInt(localStorage.getItem("xb_ipp_text_zoom") || "", 10); if (Number.isFinite(v)) __zoom = v; } catch (_) {}
  }
  return __zoom;
}
function zoomDisplay() { return zoomGet() == null ? 12 : zoomGet(); }
function zoomSet(v) {
  __zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(v)));
  try { localStorage.setItem("xb_ipp_text_zoom", String(__zoom)); } catch (_) {}
}
function zoomApplyContainer(root) {
  if (!root || !root.querySelectorAll || zoomGet() == null) return;
  root.querySelectorAll("textarea").forEach((e) => { e.style.fontSize = zoomGet() + "px"; });
}
function zoomSync(root) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll(".ipp-zoom-val").forEach((e) => { e.textContent = String(zoomDisplay()); });
}
function buildZoomRow(root) {
  const row = el("span", "display:inline-flex;align-items:center;gap:4px;user-select:none;");
  const minus = smallBtn("A−", "border:1px solid #5b9bd5;background:#2a4a6a;color:#cfe3f7;width:22px;height:22px;padding:0;line-height:1;", "缩小编辑字号（Ctrl/⌘+滚轮 也可）");
  const val = el("span", "min-width:26px;text-align:center;font-size:12px;color:#e8a87c;font-variant-numeric:tabular-nums;", String(zoomDisplay()));
  val.classList.add("ipp-zoom-val");
  const plus = smallBtn("A+", "border:1px solid #5b9bd5;background:#2a4a6a;color:#cfe3f7;width:22px;height:22px;padding:0;line-height:1;", "放大编辑字号（Ctrl/⌘+滚轮 也可）");
  const step = (d) => {
    zoomSet((zoomGet() == null ? 12 : zoomGet()) + d);
    zoomApplyContainer(root);
    zoomSync(root);
  };
  minus.addEventListener("click", () => step(-1));
  plus.addEventListener("click", () => step(1));
  row.append(minus, val, plus);
  return row;
}

const UI_STEP = 0.05, UI_MIN = 0.5, UI_MAX = 3.0;
let __uiZoom = null;
function uiGet() {
  if (__uiZoom == null) {
    try { const v = parseFloat(localStorage.getItem("xb_ipp_ui_zoom") || ""); if (Number.isFinite(v) && v > 0) __uiZoom = v; } catch (_) {}
  }
  return __uiZoom == null ? 1 : __uiZoom;
}
function uiSet(v) {
  __uiZoom = Math.max(UI_MIN, Math.min(UI_MAX, Math.round(v / UI_STEP) * UI_STEP));
  __uiZoom = Math.round(__uiZoom * 100) / 100;
  try { localStorage.setItem("xb_ipp_ui_zoom", String(__uiZoom)); } catch (_) {}
}
function uiApply(target) {
  if (!target) return;
  const z = uiGet();
  target.dataset.ippUi = "1";
  if (target.dataset.ippMaxH == null) {
    const cs = parseFloat(getComputedStyle(target).maxHeight);
    target.dataset.ippMaxH = Number.isFinite(cs) ? String(cs) : "none";
  }
  target.style.zoom = String(z);
  const orig = parseFloat(target.dataset.ippMaxH);
  const cap = Math.round((window.innerHeight * 0.92) / z);
  target.style.maxHeight = (Number.isFinite(orig) ? Math.min(orig, cap) : cap) + "px";
}
window.addEventListener("resize", () => {
  document.querySelectorAll("[data-ipp-ui]").forEach((e) => { try { uiApply(e); } catch (_) {} });
});
function buildUIRow(target) {
  const row = el("span", "display:inline-flex;align-items:center;gap:4px;user-select:none;");
  row.append(el("span", "font-size:11px;color:#888;white-space:nowrap;", "界面"));
  const minus = smallBtn("−", "border:1px solid #8a6d3b;background:#5a4a2a;color:#ffd98a;width:22px;height:22px;padding:0;line-height:1;font-size:13px;", "缩小整个界面（Ctrl/⌘+滚轮 也可）");
  const val = el("span", "min-width:42px;text-align:center;font-size:12px;color:#ffd98a;font-variant-numeric:tabular-nums;", Math.round(uiGet() * 100) + "%");
  val.classList.add("ipp-ui-val");
  const plus = smallBtn("+", "border:1px solid #8a6d3b;background:#5a4a2a;color:#ffd98a;width:22px;height:22px;padding:0;line-height:1;font-size:13px;", "放大整个界面（Ctrl/⌘+滚轮 也可）");
  const step = (d) => {
    uiSet(uiGet() + d * UI_STEP);
    uiApply(target);
    target.querySelectorAll(".ipp-ui-val").forEach((e) => { e.textContent = Math.round(uiGet() * 100) + "%"; });
  };
  minus.addEventListener("click", () => step(-1));
  plus.addEventListener("click", () => step(1));
  row.append(minus, val, plus);
  return row;
}
function bindWheelZoom(root) {
  root.addEventListener("wheel", (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    e.stopPropagation();
    // 光标在文本框里 → 调字号；在别处 → 调界面缩放
    if (e.target && e.target.closest && e.target.closest("textarea")) {
      zoomSet((zoomGet() == null ? 12 : zoomGet()) + (e.deltaY < 0 ? 1 : -1));
      zoomApplyContainer(root);
      zoomSync(root);
    } else {
      uiSet(uiGet() + (e.deltaY < 0 ? 1 : -1) * UI_STEP);
      uiApply(root);
      root.querySelectorAll(".ipp-ui-val").forEach((x) => { x.textContent = Math.round(uiGet() * 100) + "%"; });
    }
  }, { passive: false });
}

/* ============================================================
 *  配置读写
 * ============================================================ */
function defaultSettings() {
  // ⚠️ 自 0.9.x 起：输出语言 / 预设模式 / 预设句 / 空latent类型 已上提为**节点表面参数**，
  //    不再存在这份 JSON 里；JSON 只留元素面板配置 + 自动保存开关。
  return {
    auto_save: true,
    elements: { selected: {}, custom: {}, noted: {}, rel: {} },
    preset_texts: {},   // 用户改过的预设句（设定词）：{"模式|语言": "文本"}（换模式/换语言不丢）
    llm: xbrLlmDefaults(),          // 融合「✨ 提示词增强反推」的 LLM 配置段
  };
}

function readWidgetValue(w) { return w ? (w._state?.value ?? w.value) : undefined; }
function setWidgetValue(w, val) {
  if (!w) return;
  w.value = val;
  if (w._state) w._state.value = val;
  w._node?.setDirtyCanvas?.(true, true);
}
function findWidget(node, name) { return (node?.widgets || []).find((w) => w.name === name); }

/**
 * Nodes 2.0 可见性刷新
 * ⚠️ 实测（前端 1.52.7）：在 onNodeCreated 阶段把 widget 改成 type="hidden" / hidden=true / options.hidden=true，
 *    数据都对，但 Vue 侧不会重渲染（DOM 里依然看得见、依旧占高度）；
 *    触发 node:slot-label:changed（内部事件）会让前端重新抽取节点数据 → 立即生效。
 *    经典模式（Nodes 1.0）下这些操作等价于无效动作，无副作用。
 */
function refreshNodes2View(node) {
  try { if (node && Array.isArray(node.widgets)) node.widgets = node.widgets.slice(); } catch (_) {}
  try { node?.graph?.trigger?.("node:slot-label:changed", { nodeId: node.id, slotType: 2 }); } catch (_) {}
  try { node?.setDirtyCanvas?.(true, true); } catch (_) {}
}

/** 容错解析：任何异常都退回默认（绝不让面板打不开） */
function parseSettings(raw) {
  const cfg = defaultSettings();
  let data = {};
  if (raw && typeof raw === "object") data = raw;
  else if (typeof raw === "string" && raw.trim()) { try { data = JSON.parse(raw) || {}; } catch (_) { data = {}; } }
  if (typeof data.auto_save === "boolean") cfg.auto_save = data.auto_save;
  cfg.preset_texts = parsePresetTexts(data.preset_texts);

  const e0 = (data.elements && typeof data.elements === "object") ? data.elements : {};
  const sel = {};
  if (e0.selected && typeof e0.selected === "object") {
    for (const cat of ALL_CATS) {
      const seq = Array.isArray(e0.selected[cat]) ? e0.selected[cat].filter((k) => typeof k === "string" && k) : [];
      if (seq.length) sel[cat] = seq;
    }
  }
  cfg.elements.selected = sel;
  const cus = {};
  if (e0.custom && typeof e0.custom === "object") {
    for (const cat of ALL_CATS) {
      const seq = [];
      for (const it of (Array.isArray(e0.custom[cat]) ? e0.custom[cat] : [])) {
        if (!it || typeof it !== "object") continue;
        const k = typeof it.key === "string" ? it.key.trim() : "";
        if (!k) continue;
        seq.push({ key: k, zh: typeof it.zh === "string" ? it.zh : "", en: typeof it.en === "string" ? it.en : "" });
      }
      if (seq.length) cus[cat] = seq;
    }
  }
  cfg.elements.custom = cus;
  const noted = {};
  if (e0.noted && typeof e0.noted === "object") {
    for (const [k, v] of Object.entries(e0.noted)) {
      if (typeof v === "string" && v.trim()) noted[String(k)] = v;
    }
  }
  cfg.elements.noted = noted;
  const rel = {};
  if (e0.rel && typeof e0.rel === "object") {
    for (const [k, v] of Object.entries(e0.rel)) {
      if (typeof v !== "string" || !REL_MAP[v]) continue;
      const seg = String(k).split("|");
      if (seg.length !== 2 || !ALL_CATS.includes(seg[0]) || !seg[1]) continue;
      rel[`${seg[0]}|${seg[1]}`] = v;
    }
  }
  cfg.elements.rel = rel;
  cfg.llm = xbrParseLlm(data.llm);   // 融合「✨ 提示词增强反推」的 LLM 配置段
  return cfg;
}

function loadSettings(node) { return parseSettings(readWidgetValue(findWidget(node, "manager_settings"))); }
function persistSettings(node, settings) { setWidgetValue(findWidget(node, "manager_settings"), JSON.stringify(settings)); }

/* ============================================================
 *  提示词拼装 / 数值逻辑（与后端逐条对齐）
 * ============================================================ */
function sepOf(lang) { return SEP[lang] || "，"; }
function wordOf(entry, lang) {
  const v = (lang === LANG_EN) ? entry.en : entry.zh;
  return (v && v.trim()) ? v.trim() : (entry.zh || entry.en || "");
}
function snippetOf(entry, lang, desc, rel) {
  const w = wordOf(entry, lang);
  const d = (desc || "").trim();
  if (!w) return "";
  const base = rel
    ? ((lang === LANG_EN) ? `${w}, ${rel.en}` : `${rel.zh}${w}`)
    : w;
  if (!d) return base;
  return (lang === LANG_EN) ? `${base} (${d})` : `${base}（${d}）`;
}
/** 取某个词条已选的关系词（道具用；没设过 → null） */
function relPair(settings, cat, key) {
  const m = (settings && settings.elements && settings.elements.rel) || {};
  const id = m[`${cat}|${key}`];
  return id ? (REL_MAP[id] || null) : null;
}
/** 词条当前片段（自动带上详细描述与道具关系） */
function snipOf(settings, cat, key, entry, lang) {
  if (!entry) return "";
  return snippetOf(entry, lang, (settings.elements.noted || {})[`${cat}|${key}`], relPair(settings, cat, key));
}
function appendSnippet(body, snip, lang) {
  const s = (snip || "").trim();
  if (!s) return body || "";
  const t = String(body || "").replace(/[，,、\s]+$/, "");
  return t ? t + sepOf(lang) + s : s;
}
function removeSnippet(body, snips, lang) {
  let t = String(body || "");
  for (const s of snips) { if (s) t = t.split(s).join(""); }
  const sep = sepOf(lang);
  t = t.split(sep).map((x) => x.trim()).filter(Boolean).join(sep);
  return t.replace(/^[，,、\s]+/, "").replace(/[，,、\s]+$/, "");
}
function rebuildBody(settings, index, lang) {
  const parts = [];
  for (const cat of ALL_CATS) {
    for (const key of (settings.elements.selected[cat] || [])) {
      const entry = index[cat] && index[cat].get(key);
      if (!entry) continue;
      const snip = snipOf(settings, cat, key, entry, lang);
      if (snip) parts.push(snip);
    }
  }
  return parts.join(sepOf(lang));
}
/** 最终成句（与后端 build_prompt 逐行一致：预设句 + 正文）—— 三个值均来自节点表面参数 */
function finalPrompt(mode, presetText, lang, body) {
  const core = String(body || "").trim();
  if (!PRESET_TEXT_DEFAULT[mode]) return core;          // 常规文生图 → 无预设句
  const preset = String(presetText || "").trim() || defaultPresetOf(mode, lang);
  if (!core) return preset;
  if (lang === LANG_EN) return preset.replace(/[.\s]+$/, "") + ". " + core;
  return preset.replace(/[。．.\s]+$/, "") + "。" + core;
}

/** 空 latent 规格（未知值 → 默认 4 通道；与后端 latent_kind_spec 一致） */
function latentSpec(kind) {
  return LATENT_KIND_SPEC[String(kind || "")] || LATENT_KIND_SPEC[DEFAULT_LATENT_KIND];
}
/** 把任意值归一到合法枚举（缺失/None/非法 → 默认） */
function pickOpt(options, value, def) {
  const v = (value == null) ? "" : String(value).trim();
  return options.includes(v) ? v : def;
}
/** 步长锁定（与后端 _round_step 一致：floor(v/step + 0.5)；step/min/max 由空latent类型决定） */
function roundStep(v, step = SIZE_STEP, minSize = SIZE_MIN, maxSize = SIZE_MAX) {
  const n = Math.floor((Number(v) || 0) / step + 0.5) * step;
  return Math.max(minSize, Math.min(maxSize, n));
}
/** 以「宽度」为基准反算高度（改宽度 / 改比例时用）→ 对齐 js/xb_video.js 的 sW() */
function snapFromWidth(ar, w, opt) {
  const o = opt || {};
  const sw = roundStep(w, o.step, o.min, o.max);
  if (String(ar).includes("Free")) return [sw, null];
  const r = ASPECT_MAP[String(ar)];
  if (!r) return [sw, null];
  return [sw, roundStep(sw / r, o.step, o.min, o.max)];
}
/** 以「高度」为基准反算宽度（改高度时用）→ 对齐 js/xb_video.js 的 sH() */
function snapFromHeight(ar, h, opt) {
  const o = opt || {};
  const sh = roundStep(h, o.step, o.min, o.max);
  if (String(ar).includes("Free")) return [null, sh];
  const r = ASPECT_MAP[String(ar)];
  if (!r) return [null, sh];
  return [roundStep(sh * r, o.step, o.min, o.max), sh];
}
/** 无方向时的归一（节点加载 / 后端镜像）：以较大的一边为基准，幂等 */
function normalizeSize(ar, w, h, opt) {
  const o = opt || {};
  let sw = roundStep(w, o.step, o.min, o.max), sh = roundStep(h, o.step, o.min, o.max);
  if (String(ar).includes("Free")) return [sw, sh];
  const r = ASPECT_MAP[String(ar)];
  if (!r) return [sw, sh];
  if (sw >= sh) sh = roundStep(sw / r, o.step, o.min, o.max);
  else sw = roundStep(sh * r, o.step, o.min, o.max);
  return [sw, sh];
}

function copyText(text) {
  if (!text) { notify("没有可复制的内容", "warning"); return; }
  const done = () => notify("已复制提示词", "success");
  const fallback = () => {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.cssText = "position:fixed;top:-999px;opacity:0;";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    } catch (_) {}
  };
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => { fallback(); done(); });
    } else { fallback(); done(); }
  } catch (_) { fallback(); done(); }
}

/* ============================================================
 *  面板外壳（吸顶预览框 + footer：自动保存/字号/界面/取消/保存）
 * ============================================================ */
let modal = null;

function openPanel(ctx, panelId) {
  closePanel();
  const node = ctx.node;
  const settings = ctx.settings;
  const surf = ctx.surface || {};
  const cat = catOf(panelId);
  const title = `${cat.label} 元素`;

  const overlay = el("div", "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;display:flex;align-items:center;justify-content:center;overflow:auto;");
  const dialog = el("section", "background:#1c1c1e;border:1px solid #333;border-radius:8px;width:880px;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 40px rgba(0,0,0,.6);flex:0 0 auto;color:#ddd;font-size:13px;");

  const header = el("div", "padding:16px 20px 12px;border-bottom:1px solid #444;");
  const titleEl = el("div", "font-size:18px;font-weight:700;color:#eee;", title);
  header.append(titleEl);
  header.append(el("div", "font-size:12px;color:#999;margin-top:5px;", "点选项行即加入提示词（变蓝），再点一下移除（变灰）；点【添加详细描述】会在新窗口里给该词条写补充描述（悬停行可看）。配置随工作流保存，改完重新执行节点即生效。"));
  dialog.append(header);

  const panelBox = el("div", "padding:14px 20px;overflow-y:auto;flex:1;min-height:280px;");

  // ── 吸顶预览框（不受滚动条约束，始终在画面内） ──
  const sticky = el("div", "position:sticky;top:0;z-index:6;background:#1c1c1e;padding:2px 0 10px;margin:-2px 0 6px;border-bottom:1px solid #333;");
  const head = el("div", "display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;");
  head.append(el("span", "font-size:12px;font-weight:600;color:#9fc3e8;", "📝 提示词预览（与节点提示词框实时同步，可直接编辑）"));
  const headCount = el("span", "font-size:11px;color:#888;", "");
  head.append(headCount);
  const presetChip = el("div", "font-size:11px;color:#f0d79a;background:#2a2416;border:1px dashed #8a6d3b;border-radius:4px;padding:4px 8px;margin-bottom:6px;white-space:pre-wrap;line-height:1.5;display:none;");
  const preview = el("textarea", BOX_CSS + "width:100%;min-height:74px;max-height:210px;resize:vertical;line-height:1.65;font-size:12px;");
  preview.spellcheck = false;
  preview.placeholder = "点左侧 ＋ 添加元素，或直接在这里手写提示词…";
  sticky.append(head, presetChip, preview);
  panelBox.append(sticky);

  const refreshPreview = (fromEl) => {
    const body = ctx.body.get();
    if (fromEl !== preview) preview.value = body;
    headCount.textContent = `${body.length} 字 → 成句 ${finalPrompt(surf.mode, surf.presetText, surf.lang, body).length} 字`;
    const hasPreset = !!PRESET_TEXT_DEFAULT[surf.mode];
    presetChip.style.display = hasPreset ? "block" : "none";
    if (hasPreset) {
      const t = String(surf.presetText || "") || defaultPresetOf(surf.mode, surf.lang);
      presetChip.textContent = `📌 自动前置（${surf.mode}设定词，可在节点表面「预设句」框里改；改过的按模式记住、换模式不丢）：` + (t.length > 150 ? t.slice(0, 150) + "…" : t);
    }
  };
  preview.addEventListener("input", () => { ctx.body.set(preview.value); refreshPreview(preview); });

  // ── 内容 ──
  //    分类内容放在自己的容器里：面板内的 8 个分类按钮可以「就地换页」，
  //    不用关面板再开另一个（keep 吸顶预览框不被清掉）
  const catHost = el("div", "");
  panelBox.append(catHost);
  const api = {
    node, settings, ctx, panelBox, surf,
    refreshPreview,
    fromText: (v) => { preview.value = v; refreshPreview(preview); },
    switchCategory: (id) => {
      const c = catOf(id);
      try { catHost.innerHTML = ""; } catch (_) {}
      try { titleEl.textContent = `${c.label} 元素`; } catch (_) {}
      try { renderCategoryPanel(catHost, api, c.id); } catch (err) { console.error("[XB-生图提示词预设]", err); }
    },
  };
  renderCategoryPanel(catHost, api, cat.id);
  dialog.append(panelBox);

  // ── 底部 ──
  const error = el("div", "color:#e55;font-size:12px;margin:0 20px;min-height:16px;");
  const footer = el("div", "padding:12px 20px;border-top:1px solid #444;display:flex;justify-content:flex-end;gap:10px;background:#18181a;border-bottom-left-radius:8px;border-bottom-right-radius:8px;");
  const cancelBtn = el("button", "background:transparent;border:1px solid #555;color:#fff;border-radius:4px;padding:8px 20px;font-size:14px;cursor:pointer;font-family:inherit;", "取消");
  const saveBtn = el("button", "background:#2d5a88;color:#fff;border:none;border-radius:4px;padding:8px 20px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;", "💾 保存");
  const autoRow = el("label", "display:flex;align-items:center;gap:6px;font-size:13px;color:#999;cursor:pointer;user-select:none;");
  const autoCb = el("input", "width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;");
  autoCb.type = "checkbox";
  autoCb.checked = settings.auto_save !== false;
  autoCb.addEventListener("change", () => { settings.auto_save = autoCb.checked; });
  autoRow.append(autoCb, el("span", "", "自动保存"));
  const zoomRow = buildZoomRow(dialog);
  zoomRow.title = "调整面板文本编辑字号（与本节点其它面板共享记忆）";
  const uiRow = buildUIRow(dialog);
  uiRow.title = "调整整个弹窗界面大小（不缩放网页/画布）";
  const left = el("div", "display:flex;align-items:center;gap:16px;margin-right:auto;flex-wrap:wrap;");
  left.append(autoRow, zoomRow, uiRow);
  footer.append(left, cancelBtn, saveBtn);
  dialog.append(error, footer);

  overlay.append(dialog);
  document.body.append(overlay);
  zoomApplyContainer(dialog);
  uiApply(dialog);
  bindWheelZoom(dialog);

  const close = () => {
    clearTimeout(timer);          // 关键：取消/关窗后不能再让防抖定时器把改动写回去
    delete node.__ippDraft;       // 丢弃未保存草稿，信息行回退到已持久化配置
    try { ctx.refreshNode(); } catch (_) {}
    try { overlay.remove(); } catch (_) {}
    modal = null;
  };
  let timer = null;
  const doSave = (silent) => {
    try {
      persistSettings(node, settings);
      ctx.refreshNode();
      if (!silent) notify("配置已保存（随工作流保存），重新执行节点生效");
      return true;
    } catch (e) {
      error.textContent = "保存失败：" + ((e && e.message) || e);
      return false;
    }
  };
  saveBtn.addEventListener("click", () => { if (doSave(false)) close(); });
  cancelBtn.addEventListener("click", close);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  // 面板内任一控件变化：先当成草稿同步给节点表面（生成详情 / 按钮状态即时联动），
  // 再按「自动保存」防抖写回节点配置。
  const applyDraft = () => {
    node.__ippDraft = settings;
    try { ctx.refreshNode(); } catch (_) {}
  };
  panelBox.addEventListener("change", applyDraft);
  panelBox.addEventListener("change", () => {
    if (settings.auto_save === false) return;
    clearTimeout(timer);
    timer = setTimeout(() => doSave(true), 1000);
  });

  refreshPreview(null);
  // 面板打开期间：节点提示词框被外部改动时把内容拉过来（低频兜底）
  const poll = setInterval(() => {
    if (!document.body.contains(overlay)) { clearInterval(poll); return; }
    const cur = ctx.body.get();
    if (cur !== preview.value && document.activeElement !== preview) { preview.value = cur; refreshPreview(preview); }
  }, 400);
  overlay.__ippPoll = poll;

  modal = { overlay, close };
}

function closePanel() {
  try { if (modal) { clearInterval(modal.overlay.__ippPoll); modal.close(); } } catch (_) {}
  modal = null;
}

/* ============================================================
 *  🧩 元素分类面板（6 个）
 *  每个按钮一个面板，里面只列该分类的词条；选项行 = ➕ ➖ 选项名 【添加详细描述】
 * ============================================================ */
const CAT_UI = {};   // 会话级：cat -> { collapsed, onlySel, keyword }（不写进工作流）

/* ============================================================
 *  ❓ 统一确认窗
 *  以前用的是浏览器原生 confirm（系统弹窗，跟节点其它弹窗长得不一样）→ 全部换成 modal
 * ============================================================ */
function openConfirm(title, message, onOk, okText) {
  const overlay = el("div", "position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:10200;display:flex;align-items:center;justify-content:center;");
  const box = el("section", "background:#1c1c1e;border:1px solid #333;border-radius:8px;width:460px;max-width:92vw;box-shadow:0 20px 40px rgba(0,0,0,.6);padding:18px;box-sizing:border-box;color:#ddd;font-size:13px;");
  box.dataset.ippModal = "confirm";
  box.append(el("div", "font-size:15px;font-weight:700;color:#eee;margin-bottom:8px;", title || "确认"));
  box.append(el("div", "font-size:13px;color:#bbb;line-height:1.8;white-space:pre-wrap;margin-bottom:14px;", message || ""));
  const row = el("div", "display:flex;gap:10px;justify-content:flex-end;");
  const cancelBtn = el("button", "background:transparent;border:1px solid #555;color:#fff;border-radius:4px;padding:7px 18px;font-size:13px;cursor:pointer;font-family:inherit;", "取消");
  const okBtn = el("button", "background:#8a3a2a;border:1px solid #c2604a;color:#ffe7df;border-radius:4px;padding:7px 18px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;", okText || "确定");
  const close = () => { try { overlay.remove(); } catch (_) {} };
  cancelBtn.addEventListener("click", (e) => { e.stopPropagation(); close(); });
  okBtn.addEventListener("click", (e) => { e.stopPropagation(); close(); try { onOk && onOk(); } catch (_) {} });
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close(); } });
  row.append(cancelBtn, okBtn);
  box.append(row);
  overlay.append(box);
  document.body.append(overlay);
  return box;
}

/* ============================================================
 *  🎒 道具 ↔ 主体关系选择（30 个关系词，6 列 × 5 行 多宫格标签）
 * ============================================================ */
function openRelPicker(node, nameText, lang, current, onPick) {
  const overlay = el("div", "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:10200;display:flex;align-items:center;justify-content:center;");
  const box = el("section", "background:#1c1c1e;border:1px solid #333;border-radius:8px;width:780px;max-width:94vw;max-height:92vh;overflow:auto;box-shadow:0 20px 40px rgba(0,0,0,.6);padding:18px;box-sizing:border-box;color:#ddd;font-size:13px;");
  box.dataset.ippModal = "rel";
  box.append(el("div", "font-size:15px;font-weight:700;color:#eee;margin-bottom:4px;", "🎒 道具与主体的关系"));
  box.append(el("div", "font-size:12px;color:#8a97a5;margin-bottom:12px;line-height:1.7;",
    `道具：${nameText}\n选一个关系词，拼进提示词时它会加在道具前面（例：手拿折扇 / a folding fan, held in the hand）。`));
  const grid = el("div", "display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-bottom:14px;");
  const close = () => { try { overlay.remove(); } catch (_) {} };
  for (const [id, zh, en] of RELATIONS) {
    const on = id === current;
    const b = el("button", `display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;min-height:46px;border-radius:6px;cursor:pointer;font-family:inherit;padding:4px 2px;box-sizing:border-box;border:1px solid ${on ? "#7fb3e0" : "#4a4a4a"};background:${on ? "#2d5a88" : "#262626"};color:${on ? "#eaf4ff" : "#ddd"};`);
    b.dataset.rel = id;
    b.title = `${zh} / ${en}`;
    b.append(el("span", "font-size:13px;line-height:1.2;", zh));
    b.append(el("span", "font-size:9px;line-height:1.2;color:#9fb6cc;text-align:center;word-break:break-word;", en));
    b.addEventListener("mouseenter", () => { if (!on) b.style.background = "#333"; });
    b.addEventListener("mouseleave", () => { if (!on) b.style.background = "#262626"; });
    b.addEventListener("click", (e) => { e.stopPropagation(); close(); try { onPick && onPick(id); } catch (_) {} });
    grid.append(b);
  }
  box.append(grid);
  const row = el("div", "display:flex;gap:10px;justify-content:flex-end;");
  const noneBtn = el("button", "background:#2a4a6a;border:1px solid #5b9bd5;color:#cfe3f7;border-radius:4px;padding:7px 16px;font-size:13px;cursor:pointer;font-family:inherit;", "不加关系（只加道具词）");
  const cancelBtn = el("button", "background:transparent;border:1px solid #555;color:#fff;border-radius:4px;padding:7px 18px;font-size:13px;cursor:pointer;font-family:inherit;", "取消");
  noneBtn.addEventListener("click", (e) => { e.stopPropagation(); close(); try { onPick && onPick(""); } catch (_) {} });
  cancelBtn.addEventListener("click", (e) => { e.stopPropagation(); close(); });
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close(); } });
  row.append(noneBtn, cancelBtn);
  box.append(row);
  overlay.append(box);
  document.body.append(overlay);
  return box;
}

/* ============================================================
 *  📝 详细描述编辑窗
 *  照抄短剧导演台 openTextZoomEditor 的交互：独立小弹窗 + 文本编辑框 + 取消/保存
 * ============================================================ */
function openDescEditor(node, entry, nameText, value, onSave) {
  const overlay = el("div", "position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:10100;display:flex;align-items:center;justify-content:center;");
  const box = el("section", "background:#1c1c1e;border:1px solid #333;border-radius:8px;width:600px;max-width:92vw;box-shadow:0 20px 40px rgba(0,0,0,.6);padding:18px;box-sizing:border-box;color:#ddd;font-size:13px;");
  box.dataset.ippModal = "desc";   // 稳定锤点（便于定位/自动化测试）
  box.append(el("div", "font-size:15px;font-weight:700;color:#eee;margin-bottom:4px;", "📝 添加详细描述"));
  box.append(el("div", "font-size:12px;color:#8a97a5;margin-bottom:10px;line-height:1.7;white-space:pre-wrap;",
    `词条：${nameText}\n`
    + "写在这里的内容会以「词条（描述）」的形式拼进提示词（例：一位女性（银灰色短发）），"
    + "所以只写要补的细节即可 —— 不用重复词条本身，也别写整句话。"));
  const ta = el("textarea", BOX_CSS + "width:100%;min-height:150px;resize:vertical;line-height:1.7;font-size:13px;");
  ta.spellcheck = false;
  ta.value = value || "";
  ta.placeholder = "例：银灰色短发、微笑、正面半身、柔和自然光";
  box.append(ta);
  const tip = el("div", "font-size:11px;color:#777;margin-top:6px;", "Esc = 取消　·　Ctrl/⌘ + Enter = 保存");
  box.append(tip);
  const row = el("div", "display:flex;justify-content:flex-end;gap:10px;margin-top:14px;");
  const cancelBtn = el("button", "background:transparent;border:1px solid #555;color:#fff;border-radius:4px;padding:7px 18px;font-size:13px;cursor:pointer;font-family:inherit;", "取消");
  const clrBtn = el("button", "background:transparent;border:1px solid #844;color:#ffb0b0;border-radius:4px;padding:7px 14px;font-size:13px;cursor:pointer;font-family:inherit;margin-right:auto;", "🗑 清除描述");
  const okBtn = el("button", "background:#2d5a88;color:#fff;border:none;border-radius:4px;padding:7px 20px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;", "✅ 保存描述");
  row.append(clrBtn, cancelBtn, okBtn);
  box.append(row);
  overlay.append(box);

  const close = () => { try { overlay.remove(); } catch (_) {} };
  const commit = (v) => { close(); try { onSave && onSave(v); } catch (e) { console.error("[XB-生图提示词预设]", e); } };
  cancelBtn.addEventListener("click", close);
  clrBtn.addEventListener("click", () => commit(""));
  okBtn.addEventListener("click", () => commit(ta.value));
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  // 独立弹窗的键盘处理必须吃掉事件：否则 Esc 会连带把下层分类面板一起关掉
  overlay.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close(); }
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.stopPropagation(); e.preventDefault(); commit(ta.value); }
  });
  document.body.append(overlay);
  try { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } catch (_) {}
  return overlay;
}

/** 自建槽位的「中/英名称」编辑窗（同样是一个小弹窗） */
function openSlotNameEditor(zhValue, enValue, onSave) {
  const overlay = el("div", "position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:10100;display:flex;align-items:center;justify-content:center;");
  const box = el("section", "background:#1c1c1e;border:1px solid #333;border-radius:8px;width:520px;max-width:92vw;box-shadow:0 20px 40px rgba(0,0,0,.6);padding:18px;box-sizing:border-box;color:#ddd;font-size:13px;");
  box.dataset.ippModal = "slotname";   // 稳定锤点
  box.append(el("div", "font-size:15px;font-weight:700;color:#eee;margin-bottom:10px;", "✎ 自建槽位名称（中 / 英）"));
  const mk = (label, val, ph) => {
    box.append(el("div", "font-size:11px;color:#8a97a5;margin:6px 0 3px;", label));
    const i = el("input", BOX_CSS + "width:100%;font-size:13px;padding:6px 8px;");
    i.type = "text";
    i.value = val || "";
    i.placeholder = ph;
    box.append(i);
    return i;
  };
  const zh = mk("中文词条（中文 [ZH] 输出时用）", zhValue, "例：银灰色短发");
  const en = mk("English word（英文 [EN] 输出时用）", enValue, "e.g. silver-gray short hair");
  const row = el("div", "display:flex;justify-content:flex-end;gap:10px;margin-top:14px;");
  const cancelBtn = el("button", "background:transparent;border:1px solid #555;color:#fff;border-radius:4px;padding:7px 18px;font-size:13px;cursor:pointer;font-family:inherit;", "取消");
  const okBtn = el("button", "background:#2d5a88;color:#fff;border:none;border-radius:4px;padding:7px 20px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;", "✅ 保存名称");
  row.append(cancelBtn, okBtn);
  box.append(row);
  overlay.append(box);
  const close = () => { try { overlay.remove(); } catch (_) {} };
  const commit = () => { const z = zh.value.trim(), e2 = en.value.trim(); close(); try { onSave && onSave(z, e2); } catch (err) { console.error("[XB-生图提示词预设]", err); } };
  cancelBtn.addEventListener("click", close);
  okBtn.addEventListener("click", commit);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  overlay.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close(); }
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.stopPropagation(); e.preventDefault(); commit(); }
  });
  document.body.append(overlay);
  try { zh.focus(); } catch (_) {}
  return overlay;
}

function renderCategoryPanel(box, api, catId) {
  const s = api.settings;
  const surf = api.surf || {};
  let index = api.ctx.index;
  const lang = () => surf.lang;
  const bodyGet = () => api.ctx.body.get();
  const bodySet = (t) => { api.ctx.body.set(t); api.fromText(t); };
  const fire = () => box.dispatchEvent(new Event("change", { bubbles: true }));

  // ── 顶部工具条（所有分类面板共用同一套提示词工具）──
  box.append(makeSectionTitle("提示词工具"));

  // ── 8 个分类切换按钮（与节点表面完全一致）：点一下就地换到另一个分类面板 ──
  const catRow = el("div", "display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;");
  catRow.dataset.ippCatRow = "1";
  for (const c of CATEGORIES) {
    const on = c.id === catId;
    const b = el("button", `box-sizing:border-box;height:30px;display:flex;align-items:center;justify-content:center;border-radius:6px;border:2px solid ${on ? "#7fb3e0" : "#5b9bd5"};background:${on ? "#2d5a88" : "#3a3a3a"};color:${on ? "#eaf4ff" : "#eee"};font-size:13px;cursor:pointer;font-family:inherit;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;`, c.label);
    b.dataset.cat = c.id;
    if (on) b.dataset.catActive = "1";
    b.title = `切到「${c.label}」面板 —— ${c.tip}`;
    b.addEventListener("mouseenter", () => { if (!on) b.style.background = "#4a4a4a"; });
    b.addEventListener("mouseleave", () => { if (!on) b.style.background = "#3a3a3a"; });
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!on && api.switchCategory) api.switchCategory(c.id);
    });
    catRow.append(b);
  }
  box.append(catRow);
  const bar = el("div", "display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px;");
  bar.append(
    smallBtn("🧹 清空提示词", "border:1px solid #a44;background:#7a2a2a;color:#ffd0d0;padding:6px 12px;", "清空正文（同时清掉所有元素的「已选」状态）", () => {
      openConfirm("🧹 清空提示词", "确定清空提示词正文？\n（所有元素的「已选」状态也会一起清掉）", () => {
        s.elements.selected = {};
        s.elements.rel = {};
        bodySet("");
        rerenderAll();
        fire();
        notify("已清空提示词", "success");
      });
    }),
    smallBtn("🔧 按选择重建", "border:1px solid #5b9bd5;background:#2a4a6a;color:#cfe3f7;padding:6px 12px;", "按「已选元素 + 固定分类顺序（风格→视角→主体→姿态→装扮→道具→光影→背景）+ 当前语言」重排正文（手工改乱了就用它）", () => {
      const t = rebuildBody(s, index, lang());
      bodySet(t);
      fire();
      notify(t ? "已按已选元素重建正文" : "当前没有已选元素（重建后正文为空）", t ? "success" : "warning");
    }),
    smallBtn("📋 复制成句", "border:1px solid #555;background:#2a2a2a;color:#ccc;padding:6px 12px;", "复制最终成句（三视图模式下含预设句）", () => {
      copyText(finalPrompt(surf.mode, surf.presetText, surf.lang, bodyGet()));
    }),
    smallBtn("⬆️ 导出词表", "border:1px solid #6b9b5b;background:#3a5a2a;color:#d7f0c8;padding:6px 12px;", "把「自建槽位 + 已选 + 描述」导出成 JSON 备份", () => exportJson(s)),
    smallBtn("⬇️ 导入词表", "border:1px solid #6b9b5b;background:#3a5a2a;color:#d7f0c8;padding:6px 12px;", "从 JSON 恢复「自建槽位 + 已选 + 描述」（合并，不覆盖内置词表）", () => importJson((obj) => {
      if (!obj || typeof obj !== "object") return;
      for (const k of ["custom", "noted", "selected"]) {
        if (obj[k] && typeof obj[k] === "object") s.elements[k] = Object.assign({}, s.elements[k], obj[k]);
      }
      s.elements = parseSettings(s).elements;   // 归一化（过滤导入文件里的脏数据）
      index = buildIndex(s.elements);
      api.ctx.index = index;
      rerenderAll();
      fire();
    }))
  );
  box.append(bar);
  box.append(el("div", "font-size:11px;color:#888;margin-bottom:10px;line-height:1.7;",
    "顶部「分类签」切换子类（例：风格 → 真人 / 动画 / 3D / 绘画插画 / 特殊风格）；搜索与「全部加入」只作用于**当前子类**。\n" +
    "【点选项行】= 加入提示词（行变蓝、前面出现 ✔）；再点一下 = 移除（变回灰色）；【添加详细描述】开新窗口编辑补充描述（悬停行可直接查看）。\n" +
    "道具类：点行会先弹「与主体的关系」标签窗（如 手拿 / 怀抱 / 背负 …），选完再加入；行上「🔗 关系」可随时换。\n" +
    "搜索 / 只看已选 / 当前子类 属会话状态，不写进工作流；配置随工作流保存。"));

  const catBox = el("div", "");
  box.append(catBox);

  /** 只渲染当前分类（面板已按分类拆分，不再需要「全部展开/折叠」） */
  function rerenderAll() {
    catBox.innerHTML = "";
    catBox.append(renderCategory(catOf(catId)));
  }

  function renderCategory(cat) {
    // 436 条词条只在第一次渲染时建 DOM；标题栏仍可点一下收起（纯会话状态）
    if (!CAT_UI[cat.id]) CAT_UI[cat.id] = { collapsed: false, onlySel: false, keyword: "", sub: "" };
    const ui = CAT_UI[cat.id];
    const wrap = el("div", "border:1px solid #333;border-radius:6px;margin-bottom:8px;background:#191919;overflow:hidden;");
    const selOf = () => (s.elements.selected[cat.id] || []);
    const selArr = () => (s.elements.selected[cat.id] || (s.elements.selected[cat.id] = []));
    const rebuild = () => { wrap.innerHTML = ""; build(); };

    /** 当前可见（受「当前子类」+ 关键词 + 只看已选约束） */
    const visibleEntries = () => {
      const sel = new Set(selOf());
      const kw = (ui.keyword || "").trim().toLowerCase();
      const out = [];
      for (const k of (subOf(cat, ui.sub).keys || [])) {
        const e = index[cat.id] && index[cat.id].get(k);
        if (!e) continue;
        const desc = s.elements.noted[`${cat.id}|${e.key}`] || "";
        if (ui.onlySel && !sel.has(e.key)) continue;
        if (kw && !`${e.zh} ${e.en} ${desc} ${e.key}`.toLowerCase().includes(kw)) continue;
        out.push(e);
      }
      return out;
    };

    /** 设置/清除某个道具的关系词（存在 settings.elements.rel） */
    const setRel = (key, relId) => {
      const m = s.elements.rel || (s.elements.rel = {});
      if (relId && REL_MAP[relId]) m[`${cat.id}|${key}`] = relId;
      else delete m[`${cat.id}|${key}`];
    };

    const addKey = (key, relId) => {
      const entry = index[cat.id] && index[cat.id].get(key);
      if (!entry) return false;
      if (relId !== undefined) setRel(key, relId);
      const snip = snipOf(s, cat.id, key, entry, lang());
      if (!snip) { notify("该词条中/英文案都是空的（自建槽位请先填内容）", "warning"); return false; }
      let t = bodyGet();
      if (t.includes(snip)) notify("提示词里已经有这一条了（已跳过）", "warning");
      else { t = appendSnippet(t, snip, lang()); bodySet(t); }
      const arr = selArr();
      if (!arr.includes(key)) arr.push(key);
      return true;
    };

    const removeKeys = (keys) => {
      const snips = [];
      for (const k of keys) {
        const entry = index[cat.id] && index[cat.id].get(k);
        if (!entry) continue;
        const snip = snipOf(s, cat.id, k, entry, lang());
        if (snip) snips.push(snip);
        const bare = wordOf(entry, lang());
        if (bare && bare !== snip) snips.push(bare);   // 描述/关系被改过时兜底
      }
      bodySet(removeSnippet(bodyGet(), snips, lang()));
      const arr = s.elements.selected[cat.id] || [];
      for (const k of keys) { const i = arr.indexOf(k); if (i >= 0) arr.splice(i, 1); }
      if (!arr.length) delete s.elements.selected[cat.id];
    };

    const countText = () => {
      const sub = subOf(cat, ui.sub);
      const total = (cat.subs || []).reduce((n, x) => n + (x.keys || []).length, 0);
      return `（${sub.label} ${(sub.keys || []).length} 条 / 本类 ${total} 条 · 已选 ${selOf().length}）`;
    };

    /** 分类内容：首次展开时才构建 */
    function buildBody(body, cnt) {
      const updateCnt = () => { cnt.textContent = countText(); };

      // ── 子分类签（可点击切换；会话状态，不写进工作流）──
      const chips = el("div", "display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;");
      const chipRefs = [];
      const syncChips = () => {
        const cur = subOf(cat, ui.sub).id;
        for (const c of chipRefs) {
          const on = c.dataset.sub === cur;
          c.style.background = on ? "#2d5a88" : "#2a2a2a";
          c.style.borderColor = on ? "#7fb3e0" : "#555";
          c.style.color = on ? "#eaf4ff" : "#bbb";
          c.style.fontWeight = on ? "600" : "400";
        }
      };
      for (const sub of (cat.subs || [])) {
        const b = el("button", "border:1px solid #555;border-radius:14px;padding:4px 14px;font-size:12px;cursor:pointer;font-family:inherit;white-space:nowrap;", `${sub.label}（${(sub.keys || []).length}）`);
        b.dataset.sub = sub.id;
        b.title = `切到「${sub.label}」子类（${(sub.keys || []).length} 条）`;
        b.addEventListener("mousedown", (e) => e.stopPropagation());
        b.addEventListener("click", (e) => {
          e.stopPropagation();
          ui.sub = sub.id;
          ui.keyword = "";
          search.value = "";
          syncChips();
          renderRows();
          updateCnt();
        });
        chipRefs.push(b);
        chips.append(b);
      }
      syncChips();
      body.append(chips);

      // ── 分类工具条 ──
      const tb = el("div", "display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;");
      const search = el("input", BOX_CSS + "flex:1 1 130px;min-width:110px;");
      search.type = "text";
      search.placeholder = "🔍 搜索本分类（中/英/描述）…";
      search.value = ui.keyword || "";
      // 打字防抖 140ms：本分类最多 120 行，逐键全量重建 DOM 会明显卡（面板内打字发涩）
      let _kwTimer = null;
      search.addEventListener("input", () => {
        ui.keyword = search.value;
        clearTimeout(_kwTimer);
        _kwTimer = setTimeout(() => { try { renderRows(); } catch (_) {} }, 140);
      });
      tb.append(search);
      tb.append(checkboxControl(!!ui.onlySel, "只看已选", (v) => { ui.onlySel = v; renderRows(); }, "只显示已经加进提示词的词条"));
      // 加入当前可见的全部词条（超过 60 条时先弹 modal 确认）
      const addAllNow = (list) => {
        let t = bodyGet();
        const arr = selArr();
        let n = 0;
        for (const e of list) {
          const snip = snipOf(s, cat.id, e.key, e, lang());
          if (!snip) continue;
          if (!t.includes(snip)) { t = appendSnippet(t, snip, lang()); n++; }
          if (!arr.includes(e.key)) arr.push(e.key);
        }
        bodySet(t);
        rebuild();
        fire();
        notify(n ? `已加入 ${n} 条` : "这些词条都已在提示词里", n ? "success" : "warning");
      };
      tb.append(smallBtn("＋ 全部加入", "border:1px solid #5b9bd5;background:#2a4a6a;color:#cfe3f7;", "把本分类当前可见的词条全部追加进提示词", () => {
        const list = visibleEntries();
        if (!list.length) { notify("没有可加入的词条", "warning"); return; }
        if (list.length > 60) {
          openConfirm("加入大量词条", `将加入 ${list.length} 条词条，提示词会很长，确定？`, () => addAllNow(list));
          return;
        }
        addAllNow(list);
      }));
      tb.append(smallBtn("🗑 全部移除", "border:1px solid #a44;background:#5a2a2a;color:#ffd0d0;", "把本分类已选词条全部从提示词移除", () => {
        const keys = selOf().slice();
        if (!keys.length) { notify("本分类还没有已选词条", "warning"); return; }
        removeKeys(keys);
        rebuild();
        fire();
        notify(`已移除 ${keys.length} 条`, "success");
      }));
      body.append(tb);

      const rowBox = el("div", "");
      body.append(rowBox);

      function renderRows() {
        rowBox.innerHTML = "";
        const list = visibleEntries();
        if (!list.length) {
          rowBox.append(el("div", "font-size:12px;color:#777;padding:6px 2px;",
            ui.keyword ? "没有匹配的词条" : (ui.onlySel ? "本分类还没有已选词条（关掉「只看已选」可看全部）" : "本分类暂无词条")));
        } else {
          for (const e of list) rowBox.append(makeWordRow(e));
        }
        updateCnt();
      }

      /** 单条词：整行就是开关 —— 点一下加入（变蓝），再点一下移除（变灰）；右侧【添加详细描述】 */
      function makeWordRow(entry) {
        const selected = selOf().includes(entry.key);
        const descKey = `${cat.id}|${entry.key}`;
        const desc = s.elements.noted[descKey] || "";
        const row = el("div", `display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:5px;margin-bottom:3px;box-sizing:border-box;cursor:pointer;user-select:none;background:${selected ? "#22456b" : "#242424"};border:1px solid ${selected ? "#3f86d0" : "#3a3a3a"};`);
        // 悬停整行 → 显示完整词条、当前状态与详细描述（原生 tooltip）
        row.title = `${entry.zh || "（空）"} ／ ${entry.en || "（空）"}`
          + (entry.custom ? "\n（自建槽位）" : "")
          + `\n${selected ? "已加入提示词 —— 再点一下移除" : "点一下加入提示词"}`
          + "\n\n详细描述：" + (desc || "（还没有，点右侧【添加详细描述】写一条）");
        row.addEventListener("click", () => {
          if (selOf().includes(entry.key)) { removeKeys([entry.key]); renderRows(); fire(); return; }
          if (cat.id === "props") {
            // 道具：先弹「与主体的关系」多宫格标签，选完再加入提示词
            openRelPicker(api.node, `${entry.zh || entry.key} / ${entry.en || ""}`, lang(),
              (relPair(s, cat.id, entry.key) || {}).id || "",
              (relId) => { addKey(entry.key, relId || ""); renderRows(); fire(); });
            return;
          }
          addKey(entry.key);
          renderRows();
          fire();
        });
        if (entry.custom) row.append(el("span", "font-size:10px;color:#f0d79a;border:1px solid #8a6d3b;border-radius:3px;padding:0 3px;flex:0 0 auto;", "自建"));
        const rel = relPair(s, cat.id, entry.key);
        if (rel) row.append(el("span", "font-size:10px;color:#9fe0c0;border:1px solid #3f7a5f;border-radius:3px;padding:0 3px;flex:0 0 auto;", rel.zh));
        const nm = el("span", `flex:1 1 auto;min-width:0;font-size:12px;line-height:1.4;color:${selected ? "#eaf4ff" : "#c8c8c8"};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`,
          `${selected ? "✔ " : ""}${entry.zh || "（空）"} ／ ${entry.en || "（空）"}`);
        row.append(nm);
        if (cat.id === "props") {
          row.append(smallBtn(rel ? `🔗 ${rel.zh}` : "🔗 关系", "border:1px solid #5b9bd5;background:#2a4a6a;color:#cfe3f7;padding:4px 10px;flex:0 0 auto;", "选择/更换这个道具与主体的关系词（先移旧片段再加新片段）", () => {
            openRelPicker(api.node, `${entry.zh || entry.key} / ${entry.en || ""}`, lang(),
              (relPair(s, cat.id, entry.key) || {}).id || "",
              (relId) => {
                if (selOf().includes(entry.key)) removeKeys([entry.key]);
                addKey(entry.key, relId || "");
                renderRows();
                fire();
              });
          }));
        }
        const descBtn = smallBtn(desc ? "📝 详细描述" : "添加详细描述",
          `border:1px solid ${desc ? "#8a6d3b" : "#555"};background:${desc ? "#3a2f16" : "#2a2a2a"};color:${desc ? "#ffd98a" : "#9fc3e8"};padding:4px 10px;flex:0 0 auto;`,
          desc ? "编辑该词条的详细描述（新窗口）" : "为该词条添加详细描述（新窗口）",
          () => openDescEditor(api.node, entry, `${entry.zh || entry.en || entry.key}`, desc, (text) => {
            const v = String(text || "").trim();
            const oldSnip = snippetOf(entry, lang(), desc, relPair(s, cat.id, entry.key));
            if (v) s.elements.noted[descKey] = v; else delete s.elements.noted[descKey];
            // 已加入提示词的话，把正文里的旧片段原地换成新片段（位置不跳）
            if (selected) {
              const newSnip = snippetOf(entry, lang(), v, relPair(s, cat.id, entry.key));
              const cur = bodyGet();
              if (oldSnip && newSnip && oldSnip !== newSnip && cur.includes(oldSnip)) bodySet(cur.split(oldSnip).join(newSnip));
            }
            renderRows();
            api.refreshPreview(null);
            fire();
          }));
        row.append(descBtn);
        return row;
      }

      renderRows();

      // ── 自建槽位 ──
      body.append(makeSectionTitle("🛠 自建槽位（本分类专属）"));
      const cusBox = el("div", "");
      body.append(cusBox);

      function renderCustom() {
        cusBox.innerHTML = "";
        const list = s.elements.custom[cat.id] || [];
        if (!list.length) {
          cusBox.append(el("div", "font-size:11px;color:#777;padding:2px 0 6px;", "还没有自建槽位 —— 点下面「＋ 新增槽位」加一个（点【编辑名称】填中/英，再点该行即加入提示词）。"));
          return;
        }
        list.forEach((it, i) => {
          const entry = index[cat.id] && index[cat.id].get(it.key);
          const selected = selOf().includes(it.key);
          const descKey = `${cat.id}|${it.key}`;
          const desc = s.elements.noted[descKey] || "";
          const row = el("div", `display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:5px;margin-bottom:3px;box-sizing:border-box;cursor:pointer;user-select:none;background:${selected ? "#22456b" : "#242424"};border:1px solid ${selected ? "#3f86d0" : "#3a3a3a"};`);
          row.title = `${it.zh || "（未填中文）"} ／ ${it.en || "（未填英文）"}\n（自建槽位）`
            + `\n${selected ? "已加入提示词 —— 再点一下移除" : "点一下加入提示词"}`
            + "\n\n详细描述：" + (desc || "（还没有，点【添加详细描述】写一条）");
          row.addEventListener("click", () => {
            if (selOf().includes(it.key)) removeKeys([it.key]);
            else addKey(it.key);
            rebuild();
            fire();
          });
          row.append(el("span", "font-size:10px;color:#f0d79a;border:1px solid #8a6d3b;border-radius:3px;padding:0 3px;flex:0 0 auto;", "自建"));
          row.append(el("span", `flex:1 1 auto;min-width:0;font-size:12px;color:${selected ? "#eaf4ff" : "#c8c8c8"};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`,
            `${selected ? "✔ " : ""}${it.zh || "（未填中文）"} ／ ${it.en || "（未填英文）"}`));
          row.append(smallBtn("✎ 编辑名称", "border:1px solid #555;background:#2a2a2a;color:#9fc3e8;padding:4px 10px;flex:0 0 auto;", "新窗口编辑该槽位的中/英词条", () => {
            openSlotNameEditor(it.zh, it.en, (z, e2) => {
              it.zh = z; it.en = e2;
              if (entry) { entry.zh = z; entry.en = e2; }
              rebuild();
              api.refreshPreview(null);
              fire();
            });
          }));
          row.append(smallBtn(desc ? "📝 详细描述" : "添加详细描述",
            `border:1px solid ${desc ? "#8a6d3b" : "#555"};background:${desc ? "#3a2f16" : "#2a2a2a"};color:${desc ? "#ffd98a" : "#9fc3e8"};padding:4px 10px;flex:0 0 auto;`,
            desc ? "编辑该自建词条的详细描述（新窗口）" : "为该自建词条添加详细描述（新窗口）",
            () => openDescEditor(api.node, entry || { key: it.key, zh: it.zh, en: it.en }, `${it.zh || it.en || it.key}`, desc, (text) => {
              const v = String(text || "").trim();
              const oldSnip = snippetOf(entry || it, lang(), desc);
              if (v) s.elements.noted[descKey] = v; else delete s.elements.noted[descKey];
              if (selected && entry) {
                const newSnip = snippetOf(entry, lang(), v);
                const cur = bodyGet();
                if (oldSnip && newSnip && oldSnip !== newSnip && cur.includes(oldSnip)) bodySet(cur.split(oldSnip).join(newSnip));
              }
              rebuild();
              api.refreshPreview(null);
              fire();
            })));
          row.append(smallBtn("🗑", "border:1px solid #a44;background:#3a2020;color:#ffb0b0;width:24px;height:24px;padding:0;line-height:1;flex:0 0 auto;", "删除这个自建槽位", () => {
            openConfirm("删除自建槽位", `删除自建槽位「${it.zh || it.en || it.key}」？`, () => {
              removeKeys([it.key]);
              delete s.elements.noted[`${cat.id}|${it.key}`];
              list.splice(i, 1);
              if (!list.length) delete s.elements.custom[cat.id];
              index = buildIndex(s.elements);
              api.ctx.index = index;
              rebuild();
              fire();
            });
          }));
          cusBox.append(row);
        });
      }
      renderCustom();

      const cusBar = el("div", "display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;");
      cusBar.append(smallBtn("＋ 新增槽位", "border:1px dashed #5b9bd5;background:#2a3a4a;color:#9fc3e8;padding:6px 12px;", "新增一个自定义词条槽位（中/英各填一个）", () => {
        const arr = s.elements.custom[cat.id] || (s.elements.custom[cat.id] = []);
        arr.push({ key: `c${Date.now().toString(36)}${Math.floor(Math.random() * 46656).toString(36)}`, zh: "", en: "" });
        index = buildIndex(s.elements);
        api.ctx.index = index;
        rebuild();
        fire();
      }));
      cusBar.append(smallBtn("🗑 删除槽位", "border:1px solid #a44;background:#5a2a2a;color:#ffd0d0;padding:6px 12px;", "删除本分类最后一个自建槽位（要删指定的，用该行右侧的 🗑）", () => {
        const arr = s.elements.custom[cat.id] || [];
        if (!arr.length) { notify("本分类还没有自建槽位", "warning"); return; }
        const last = arr[arr.length - 1];
        openConfirm("删除最后一个自建槽位", `删除最后一个自建槽位「${last.zh || last.en || last.key}」？`, () => {
          removeKeys([last.key]);
          delete s.elements.noted[`${cat.id}|${last.key}`];
          arr.pop();
          if (!arr.length) delete s.elements.custom[cat.id];
          index = buildIndex(s.elements);
          api.ctx.index = index;
          rebuild();
          fire();
        });
      }));
      body.append(cusBar);

      updateCnt();
    }

    /** 分类外壳：标题栏总是建，内容懒建（展开才建） */
    function build() {
      wrap.innerHTML = "";
      const headRow = el("div", "display:flex;align-items:center;gap:8px;padding:8px 10px;background:#20242a;cursor:pointer;flex-wrap:wrap;");
      const arrow = el("span", "font-size:11px;color:#9fc3e8;width:12px;flex:0 0 12px;", ui.collapsed ? "▶" : "▼");
      const cnt = el("span", "font-size:11px;color:#8a97a5;", countText());
      headRow.append(arrow, el("span", "font-size:13px;font-weight:600;color:#cfe3f7;", cat.label), cnt,
        el("span", "font-size:11px;color:#6f7c8a;flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", cat.tip || ""));
      const body = el("div", "padding:8px 10px;");
      body.style.display = ui.collapsed ? "none" : "block";
      let bodyBuilt = false;
      const ensureBody = () => { if (!bodyBuilt) { bodyBuilt = true; buildBody(body, cnt); } };
      headRow.addEventListener("click", (e) => {
        if (e.target && e.target.closest && e.target.closest("input,button,select,textarea,label")) return;
        ui.collapsed = !ui.collapsed;
        body.style.display = ui.collapsed ? "none" : "block";
        arrow.textContent = ui.collapsed ? "▶" : "▼";
        if (!ui.collapsed) ensureBody();
      });
      wrap.append(headRow, body);
      if (!ui.collapsed) ensureBody();
    }

    build();
    return wrap;
  }

  rerenderAll();
}

function exportJson(settings) {
  try {
    const payload = {
      app: "XB-ImagePromptPreset",
      version: 1,
      custom: settings.elements.custom || {},
      noted: settings.elements.noted || {},
      selected: settings.elements.selected || {},
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    a.download = `生图元素_${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}.json`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { try { URL.revokeObjectURL(a.href); a.remove(); } catch (_) {} }, 1000);
    notify("已导出词表 JSON", "success");
  } catch (e) { notify("导出失败：" + ((e && e.message) || e), "error"); }
}

function importJson(onDone) {
  try {
    if (!document.__ippImportInput) {
      const inp = document.createElement("input");
      inp.type = "file";
      inp.accept = ".json,application/json";
      inp.style.display = "none";
      document.body.appendChild(inp);
      document.__ippImportInput = inp;
    }
    const inp = document.__ippImportInput;
    inp.value = "";
    inp.onchange = async () => {
      const file = inp.files && inp.files[0];
      if (!file) return;
      try {
        const text = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result || "");
          r.onerror = () => rej(r.error);
          r.readAsText(file, "utf-8");
        });
        onDone(JSON.parse(text));
        notify("已导入词表（自建槽位 / 已选 / 描述）", "success");
      } catch (e) { notify("导入失败：" + ((e && e.message) || e), "error"); }
    };
    inp.click();
  } catch (e) { notify("导入失败：" + ((e && e.message) || e), "error"); }
}

/* ============================================================
 *  节点挂载
 * ============================================================ */
function setupNode(node) {
  const widgetState = new WeakMap();   // 隐藏 widget 前的原样（type/computeSize/hidden），供 showWidget 原样恢复
  const wAR = findWidget(node, "aspect_ratio");
  const wW = findWidget(node, "width");
  const wH = findWidget(node, "height");
  const wB = findWidget(node, "batch_size");
  const wLang = findWidget(node, "output_lang");
  const wMode = findWidget(node, "preset_mode");
  const wKind = findWidget(node, "latent_kind");
  const w3v = findWidget(node, "three_view_text");
  const ipWidget = findWidget(node, "internal_prompt");
  if (!wAR || !wW || !wH || !ipWidget) return;

  // ── 内部字段从节点表面隐藏 ────────────────────────────────────────
  // ⚠️ 实测教训：后端只写 "advanced": True 在本前端版本里**不会**把 V1 widget 从节点表面藏起来，
  //    internal_prompt / manager_settings 会真的显示成两个 86px 高的文本框并把节点撑高
  //    （实测节点 420x314 → 550x570）。这里沿用本包既有做法（xb_audio_slicer_v3.js:30、
  //    xb_digital_human_dual.js:83）：type="hidden" + computeSize=[0,-4]。
  const hideWidget = (w) => {
    if (!w) return;
    try {
      // 记下原样（type / computeSize / hidden），以便必要时原样恢复（如三视图预设句框）
      if (!widgetState.has(w)) {
        widgetState.set(w, {
          type: w.type, computeSize: w.computeSize, hidden: w.hidden,
          optHidden: w.options ? w.options.hidden : undefined,
        });
      }
      if (w.element) w.element.style.display = "none";
      if (w.inputEl) w.inputEl.style.display = "none";
      w.type = "hidden";
      w.hidden = true;
      if (w.options) w.options.hidden = true;
      w.computeSize = () => [0, -4];
    } catch (_) {}
  };
  const showWidget = (w) => {
    if (!w) return;
    try {
      const st = widgetState.get(w);
      if (w.element) w.element.style.display = "";
      if (w.inputEl) w.inputEl.style.display = "";
      if (st) {
        // 只在确有存档时还原 type/computeSize
        if (st.type) w.type = st.type;
        w.hidden = !!st.hidden;
        if (w.options) w.options.hidden = st.optHidden;
        if (st.computeSize) w.computeSize = st.computeSize; else { try { delete w.computeSize; } catch (_) {} }
      } else {
        // ⚠️ 没有存档（从未 hideWidget 过，如加载「预设模式=三视图」的工作流直接就 show）时
        // 绝不能写 w.type —— 旧写法 `(st && st.type) || "text"` 会把原生的多行
        // customtext/textarea 预设句框改成单行 type="text"，界面上变成一个一行输入栏。
        w.hidden = false;
        if (w.options) w.options.hidden = false;
      }
    } catch (_) {}
  };
  // 提前为「会被 show/hide 的原生框」存一份原样（预设句框在部分工作流里从未被 hide 过）
  const snapshotWidget = (w) => {
    if (!w || widgetState.has(w)) return;
    try {
      widgetState.set(w, {
        type: w.type, computeSize: w.computeSize, hidden: w.hidden,
        optHidden: w.options ? w.options.hidden : undefined,
      });
    } catch (_) {}
  };
  snapshotWidget(w3v);

  // ── 预设句（设定词）存档：用户改过的那条按「模式|语言」存进节点 ──────────────
  // 切换模式 / 切换语言一律取「该键的存档 → 该键的默认」，所以用户改过的设定词不会被冲掉。
  // ⚠️ 写入用「原样 JSON 合并」——不能走 persistSettings（那会丢掉 Pro 的 llm 段等其它键）。
  let lastAppliedPreset = String(readWidgetValue(w3v) ?? "");
  const presetStoreOf = () => {
    try { return parsePresetTexts(parseSettings(readWidgetValue(findWidget(node, "manager_settings"))).preset_texts); }
    catch (_) { return {}; }
  };
  const savedPresetOf = (mode, lang) => presetStoreOf()[presetKeyOf(mode, lang)] || "";
  /** 该「模式 × 语言」最终生效的设定词：用户改过的存档优先，否则用默认 */
  const presetTextFor = (mode, lang) => savedPresetOf(mode, lang) || defaultPresetOf(mode, lang);
  /** 存 / 清一条设定词存档（与默认一致 → 清掉存档，保持工作流干净） */
  const writePresetStore = (mode, lang, text) => {
    try {
      let data = {};
      try { data = JSON.parse(String(readWidgetValue(findWidget(node, "manager_settings")) || "{}")) || {}; }
      catch (_) { data = {}; }
      if (!data || typeof data !== "object") data = {};
      const store = parsePresetTexts(data.preset_texts);
      const key = presetKeyOf(mode, lang);
      const t = String(text ?? "");
      if (!t.trim() || t === defaultPresetOf(mode, lang)) delete store[key];
      else store[key] = t;
      if (Object.keys(store).length) data.preset_texts = store; else delete data.preset_texts;
      setWidgetValue(findWidget(node, "manager_settings"), JSON.stringify(data));
      try { node.__ippRefreshInfo?.(); } catch (_) {}
    } catch (_) {}
  };

  const hideInternal = () => {
    hideWidget(findWidget(node, "internal_prompt"));
    hideWidget(findWidget(node, "manager_settings"));
    // 融合「✨ 提示词增强反推」：这些参数只在弹窗里配置（节点表面不暴露）
    hideWidget(findWidget(node, "backend"));
    hideWidget(findWidget(node, "preset"));
    hideWidget(findWidget(node, "task_preset"));
    hideWidget(findWidget(node, "open_api_settings"));
    hideWidget(findWidget(node, "output_lang"));     // 语言只留：LLM设置 里的「输出语言」
    hideWidget(findWidget(node, "latent_kind"));     // → 「✨ 增强预设」弹窗
    hideWidget(findWidget(node, "preset_mode"));     // → 「✨ 增强预设」弹窗
    hideWidget(findWidget(node, "three_view_text")); // 设定词 → 只在「✨ 增强预设」弹窗里编辑（用户要求：不在节点表面显示）
    refreshNodes2View(node);
    node.setDirtyCanvas?.(true, true);
  };
  hideInternal();

  // ── 节点表面 DOM：结构照抄「短剧导演台」（js/asset_manager.js）──
  // ① 容器 = 满高 flex 列（width/height:100% + overflow:hidden），高度完全交给前端 overlay 布局；
  //    提示词框 flex:1 1 auto 吃掉剩余高度。全程零 JS 高度计算 → 不可能出现
  //    「容器高 ↔ 节点高」互相反馈（之前读到 1675 的怪物高度）或被裁掉底部。
  //    ⚠️ 绝不读容器的 scrollHeight / offsetHeight（任何 DOM 尺寸实测都不读），也绝不在打字时 setSize/重排。
  // 容器必须自带不透明的节点底色：容器里的 padding / 行间距本来透明，
  // 节点原生 widget 滚动时会从这些缝隙里透出来（用户报的「提示词预览上方有缝隙、滚动时漏内容」）。
  let nodeBg = "#353535";
  try { nodeBg = node.bgcolor || (window.LiteGraph && window.LiteGraph.NODE_DEFAULT_BGCOLOR) || nodeBg; } catch (_) {}
  const container = el("div", `width:100%;height:100%;display:flex;flex-direction:column;gap:6px;padding:8px;box-sizing:border-box;overflow:hidden;background:${nodeBg};border-bottom-left-radius:8px;border-bottom-right-radius:8px;`);

  // ② 按钮区放最上面（对齐短剧导演台：紧贴节点原生参数下方，不随内容高度上下浮动）
  //    8 个按钮 = 8 个元素分类，每个按钮只打开该分类的面板（4 列 × 2 行）
  const btnRow = el("div", "display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:30px;gap:6px;flex:0 0 auto;");
  for (const b of PANEL_BUTTONS) {
    const cat = catOf(b.panel);
    const btn = el("button", "width:100%;height:30px;box-sizing:border-box;display:flex;align-items:center;justify-content:center;border-radius:6px;border:2px solid #5b9bd5;background:#3a3a3a;color:#eee;font-size:13px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:inherit;", b.label);
    btn.title = `打开「${cat.label}」元素面板 —— ${cat.tip}\\n（里面：点选项行加入/移除提示词，【添加详细描述】写补充描述）`;
    btn.addEventListener("mousedown", (e) => e.stopPropagation());
    btn.addEventListener("mouseenter", () => { btn.style.background = "#4a4a4a"; });
    btn.addEventListener("mouseleave", () => { btn.style.background = "#3a3a3a"; });
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const settings = loadSettings(node);
      const index = buildIndex(settings.elements);
      const ctx = {
        node, settings, index,
        surface: surfaceOf(),
        body: {
          get: () => String(readWidgetValue(ipWidget) ?? ""),
          set: (v) => { setWidgetValue(ipWidget, v); if (promptBox.value !== v) promptBox.value = v; },
        },
        refreshNode: () => syncPromptBoxFromWidget(),
      };
      openPanel(ctx, b.panel);
    });
    btnRow.append(btn);
  }
  // 第 1 行按钮（融合「✨ 提示词增强反推」）：🤖 LLM设置 ｜ ✨ 增强预设 ｜ 📖 使用说明
  container.appendChild(xbrBuildButtonRow(node));
  // 第 2 行：8 个元素分类按钮
  container.appendChild(btnRow);

  // ③ 提示词框（flex:1 1 auto 吃掉剩余高度；原来的「生成详情」状态行已按要求删除）
  const promptBox = el("textarea", BOX_CSS + "width:100%;flex:1 1 auto;min-height:300px;resize:none;line-height:1.6;font-size:12px;overflow-y:auto;");
  promptBox.spellcheck = false;
  promptBox.placeholder = "点上方按钮开面板、点选项行加入元素，或直接在这里写提示词…\n接了「🖼️ 图像」时：这里写的是修改要求，例：把背景换成草地 → 最终只输出修改后的画面提示词\n「📝 提示词」端口接线后本框锁定";
  // 标题行（左标签 + 右「📋 复制」）+ 参数设定显示（Pro 新增；同时挂上端口锁定与执行回写）
  const xbrHeadAndInfo = xbrBuildPromptHeader(node, promptBox);
  container.append(xbrHeadAndInfo[0], promptBox, xbrHeadAndInfo[1]);

  // ── 提示词框 ↔ internal_prompt ──
  const syncPromptBoxFromWidget = () => {
    const v = String(readWidgetValue(ipWidget) ?? "");
    if (promptBox.value !== v && document.activeElement !== promptBox) promptBox.value = v;
  };
  promptBox.addEventListener("input", () => { setWidgetValue(ipWidget, promptBox.value); });

  // ── 表面参数（原「⚙️ 输出设置」面板的 4 项已上提到节点表面）──
  const surfaceOf = () => ({
    lang: pickOpt(LANGS, readWidgetValue(wLang), LANG_ZH),
    mode: pickOpt(MODES, readWidgetValue(wMode), MODE_TP),
    kind: pickOpt(LATENT_KINDS, readWidgetValue(wKind), DEFAULT_LATENT_KIND),
    presetText: String(readWidgetValue(w3v) ?? ""),
  });
  /** 当前空latent类型对应的步长/上下限（后端按同一张表算，保证所见即所得） */
  const sizeOpt = () => {
    const sp = latentSpec(surfaceOf().kind);
    return { step: sp.step, min: sp.min, max: sp.max };
  };

  // 三视图预设句框是 ComfyUI 原生 textarea（自带 h-full w-full 与默认圆角），
  // 必须手动对齐节点表面提示词框：同宽（容器左右各 8px 内边距）+ 同样的圆角 / 配色
  const nodeEl = () => document.querySelector(`[data-node-id="${node.id}"]`);
  const markNodeEl = () => { try { nodeEl()?.setAttribute("data-xb-ipp", "1"); } catch (_) {} };
  // Nodes 2.0：原生 widget 的 DOM 是 Vue 重建的，`w3v.element / inputEl` 是**已脱离文档**的老元素
  // （实测 connected=false），真正显示的那个 textarea 用的是前端 Textarea 组件，
  // class 带 scrollbar-gutter-stable，默认 min-height 只有 4rem 且 overflow-y:hidden
  // → 预设句较长时直接截断、也拉不高。这里单独给它放宽（面板自己的预览框没有这个 class，不受影响）。
  const IPP_STYLE_ID = "xb-ipp-preset-textarea-style";
  const ensurePresetBoxStyle = () => {
    try {
      if (document.getElementById(IPP_STYLE_ID)) return;
      const st = document.createElement("style");
      st.id = IPP_STYLE_ID;
      st.textContent = `
        [data-xb-ipp] textarea[class*="scrollbar-gutter-stable"] {
          min-height: 132px;
          max-height: 360px;
          overflow-y: auto !important;
          resize: vertical;
        }`;
      document.head.appendChild(st);
    } catch (_) {}
  };
  const livePresetBox = () => {
    try {
      const el = nodeEl();
      if (!el) return null;
      const cands = Array.from(el.querySelectorAll('textarea[class*="scrollbar-gutter-stable"]'));
      if (!cands.length) return null;
      const val = String(readWidgetValue(w3v) ?? "");
      return cands.find((t) => String(t.value || "") === val) || cands[0];
    } catch (_) { return null; }
  };
  const stylePresetTextBox = () => {
    try {
      ensurePresetBoxStyle();
      markNodeEl();
      // 1.0（canvas 里的 DOM widget）：按老做法修边
      if (w3v) for (const box of [w3v.element, w3v.inputEl]) {
        if (!box || !box.style) continue;
        box.style.width = "calc(100% - 16px)";
        box.style.margin = "0 8px";
        box.style.boxSizing = "border-box";
        box.style.borderRadius = "4px";
        box.style.border = "1px solid #444";
        box.style.background = "#1d1d1d";
        box.style.color = "#ccc";
        box.style.padding = "5px 8px";
        box.style.fontSize = "12px";
        box.style.lineHeight = "1.6";
        box.style.fontFamily = "inherit";
      }
      // 2.0：把“活的”多行框调成够看、可滚、可拉高
      const live = livePresetBox();
      // 用户在这个原生框里手改设定词 → 立刻存档（换模式 / 换语言时不丢）
      if (live && !live.__ippBound) {
        live.__ippBound = true;
        const commitUserEdit = () => {
          try {
            const v = String(live.value ?? "");
            if (v === lastAppliedPreset) return;          // 程序化写入的回声 → 忽略
            lastAppliedPreset = v;
            setWidgetValue(w3v, v);
            writePresetStore(surfaceOf().mode, surfaceOf().lang, v);
          } catch (_) {}
        };
        live.addEventListener("change", commitUserEdit);
        live.addEventListener("blur", commitUserEdit);
      }
      if (live && live.style) {
        live.style.minHeight = "132px";
        live.style.maxHeight = "360px";
        live.style.overflowY = "auto";
        live.style.resize = "vertical";
        live.style.whiteSpace = "pre-wrap";
        live.style.lineHeight = "1.6";
      }
    } catch (_) {}
  };

  /** 写预设句：同时写 widget 值 + textarea（新版前端 customtext 把值存在 DOM 上，只手写 widget 可能不刷新显示）
   *  lastAppliedPreset 记下「程序写进去的值」→ 回调里只有不等于它的才算用户手改（防回声被误存档） */
  const setPresetText = (txt) => {
    const v = String(txt ?? "");
    lastAppliedPreset = v;
    try { setWidgetValue(w3v, v); } catch (_) {}
    try { if (w3v && w3v.element && "value" in w3v.element) w3v.element.value = v; } catch (_) {}
    try { node.setDirtyCanvas?.(true, true); } catch (_) {}
  };

  // 预设句输入框：常规文生图以外的 4 个模式（三视图/四视图/五视图/背景纯透明）都显示（一次性隐藏/显示，不做任何 setSize，不会抖动）
  const applyPresetTextVisibility = () => {
    try {
      // Pro：设定词只在「✨ 增强预设」弹窗里编辑 → 节点表面始终隐藏（不把选项参数暴露在外面）
      hideWidget(w3v);
    } catch (_) {}
    refreshNodes2View(node);
    // 2.0 下 Vue 可能稍后才把原生 widget 的 DOM 挂上/重建 → 几个时机各补一次样式与节点标记
    [0, 60, 200, 600].forEach((d) => setTimeout(() => {
      ensurePresetBoxStyle();
      markNodeEl();
      try { if (PRESET_TEXT_DEFAULT[surfaceOf().mode]) stylePresetTextBox(); } catch (_) {}
    }, d));
    node.setDirtyCanvas?.(true, true);
  };

  // 空latent类型 → 同步 width/height/batch 的原生 step & 上下限（箭头/拖动按官方步长走）
  const applyKindLimits = () => {
    const sp = latentSpec(surfaceOf().kind);
    for (const w of [wW, wH]) {
      if (w && w.options) { w.options.step = sp.step; w.options.min = sp.min; w.options.max = sp.max; }
    }
    if (wB && wB.options) wB.options.max = sp.batchMax;
    if (wKind && wKind.options) wKind.options.tooltip = `空latent类型（${sp.desc}）\n尺寸步长 ${sp.step}，batch 上限 ${sp.batchMax}。\n选你正在用的模型即可，形状/下采样/步长会自动适配。`;
    const b = parseInt(readWidgetValue(wB), 10) || 1;
    if (b > sp.batchMax) setWidgetValue(wB, sp.batchMax);
  };

  // ── 画幅比例 + 步长联动（语义对齐 js/xb_video.js；步长按当前空latent类型） ──
  let syncing = false;
  const snapByWidth = () => {
    if (syncing) return;
    const [nw, nh] = snapFromWidth(String(readWidgetValue(wAR) ?? "Free"), readWidgetValue(wW), sizeOpt());
    syncing = true;
    try {
      if (nw != null && nw !== parseInt(readWidgetValue(wW), 10)) setWidgetValue(wW, nw);
      if (nh != null && nh !== parseInt(readWidgetValue(wH), 10)) setWidgetValue(wH, nh);
    } finally { syncing = false; }
  };
  const snapByHeight = () => {
    if (syncing) return;
    const [nw, nh] = snapFromHeight(String(readWidgetValue(wAR) ?? "Free"), readWidgetValue(wH), sizeOpt());
    syncing = true;
    try {
      if (nh != null && nh !== parseInt(readWidgetValue(wH), 10)) setWidgetValue(wH, nh);
      if (nw != null && nw !== parseInt(readWidgetValue(wW), 10)) setWidgetValue(wW, nw);
    } finally { syncing = false; }
  };
  const hook = (w, fn) => {
    if (!w) return;
    const orig = w.callback;
    w.callback = function (...args) {
      const r = orig ? orig.apply(this, args) : undefined;
      try { fn(); } catch (e) { console.error("[XB-生图提示词预设]", e); }
      return r;
    };
  };
  hook(wAR, snapByWidth);
  hook(wW, snapByWidth);
  hook(wH, snapByHeight);
  hook(wKind, () => { applyKindLimits(); snapByWidth(); });                     // 换类型 → 按新步长重新归一宽高
  // 2.0：注入「原生多行框放宽」样式 + 给节点元素打标记（数据属性是 CSS 作用域的锚点；
  //     Vue 重建节点 DOM 后会丢，所以拖后几次重打）
  ensurePresetBoxStyle();
  markNodeEl();
  [0, 300, 1200].forEach((d) => setTimeout(() => { ensurePresetBoxStyle(); markNodeEl(); }, d));
  hook(w3v, () => {                                                            // 用户手改设定词 → 立刻存进节点
    const cur = String(readWidgetValue(w3v) ?? "");
    if (cur === lastAppliedPreset) return;                                     // 程序化写入的回声 → 忽略
    lastAppliedPreset = cur;
    writePresetStore(surfaceOf().mode, surfaceOf().lang, cur);
  });
  hook(wMode, () => {                                                          // 换模式 = 显/隐预设句框 +
    const { mode, lang } = surfaceOf();                                        //   取该模式的「用户存档 → 默认」
    if (defaultPresetOf(mode, lang)) setPresetText(presetTextFor(mode, lang)); //   （改过的设定词不会被冲掉）
    applyPresetTextVisibility();
  });
  hook(wLang, () => {                                                          // 换语言 = 同模式按下语言取「存档 → 默认」
    const { mode, lang } = surfaceOf();
    if (defaultPresetOf(mode, lang)) setPresetText(presetTextFor(mode, lang));
  });
  hook(wB, () => {                                                             // batch 超出当前类型上限 → 就近钳制
    const sp = latentSpec(surfaceOf().kind);
    const cur = parseInt(readWidgetValue(wB), 10) || 1;
    if (cur > sp.batchMax) setWidgetValue(wB, sp.batchMax);
    else if (cur < 1) setWidgetValue(wB, 1);
  });

  // ── 隐藏字段的幽灵端口清理（V1 没有 socketless，高级字段也可能冒出端口） ──
  const killGhost = () => {
    try {
      for (const nm of ["internal_prompt", "manager_settings", "backend", "preset", "task_preset",
                         "open_api_settings", "output_lang", "latent_kind", "preset_mode", "three_view_text"]) {
        const idx = (node.inputs || []).findIndex((i) => i.name === nm);
        if (idx < 0) continue;
        if (typeof node.removeInput === "function") node.removeInput(idx);
        else { node.inputs.splice(idx, 1); node.inputs.forEach((it, k) => { it.slot = k; }); }
      }
      node.setDirtyCanvas?.(true, true);
    } catch (_) {}
  };
  [0, 150, 500, 1200].forEach((d) => setTimeout(killGhost, d));

  // ── DOM widget（对齐短剧导演台：宽度钉死 + 高度自适应 + 每帧宽度同步） ──
  const MIN_W = 420;
  let refreshSize = () => {};   // 真实实现稍后赋值（需等 DOM widget 建好）
  const widget = node.addDOMWidget?.("xb_image_preset", "XB_IMAGE_PRESET", container, {
    serialize: false,
    hideOnZoom: false,
  });
  // ComfyUI 用 widget.width ?? node.width 算 overlay 宽度：只依赖 node.width，
  // 在属性面板/重排时会被算窄 → 视觉上就是「内容与按钮漂移」。
  const syncDomWidth = () => {
    try {
      const fullW = Number.isFinite(node.size?.[0]) ? node.size[0] : 0;
      if (widget && fullW && widget.width !== fullW) widget.width = fullW;
    } catch (_) {}
  };
  const lockMinWidth = () => {
    try {
      const w = Number.isFinite(node.size?.[0]) ? node.size[0] : 0;
      if (w >= MIN_W) return;
      node.setSize?.([MIN_W, Math.max(node.size?.[1] || 240, 240)]);
    } catch (_) {}
  };
  // 高度常量（提前声明：widget 的布局回调可能在后面才被调用，避免 TDZ）
  const TEXT_MIN_H = 300;   // 提示词框最小高度（节点再小也不低于它；节点变大则跟随）
  const DOM_FIXED_H = 308;  // Pro：按钮区 3 行(102) + 标签(17) + 信息区(150+6) + 内边距/间距(≈33)
  const DOM_MIN_H = 603;    // Pro：DOM 区最小高度 = 按钮区 102 + 间距 12 + 标签 17 + 输入框 300 + 信息区 156 + 内边距 16
  if (widget) {
    try { delete widget.computeSize; } catch (_) { widget.computeSize = undefined; }
    widget.options = widget.options || {};
    widget.options.serialize = false;
    // DOM 区的最小高度 = 按钮区 2 行(66) + 标签(17) + 提示词框最小(500) + 内边距/间距(≈28)
    widget.options.getMinHeight = () => DOM_MIN_H;
    widget.options.getHeight = () => "100%";
    widget.computeLayoutSize = () => ({ minHeight: DOM_MIN_H, maxHeight: undefined, minWidth: MIN_W });
    widget.options.onDraw = () => syncDomWidth();
    widget.options.afterResize = () => syncDomWidth();
  }
  node.min_width = MIN_W;
  node.minWidth = MIN_W;
  node._xbDomWidget = widget;
  node._xbSyncWidth = syncDomWidth;   // 供 canvas.onDrawForeground 每帧调用

  // 尺寸刷新 —— 照抄短剧导演台 `refreshSize`：
  //   ① 用 LiteGraph 自己的 computeSize() 算高度（不读任何 DOM 尺寸 → 无反馈环）
  //   ② 只做「下限保护」：未设置 / 小于下限时才 setSize，绝不覆盖用户拖拽出来的高度
  //   ③ 只在「初始化(3 次) + 工作流加载(configure)」调用，打字 / 面板保存 / onResize 一律不调
  // ⚠️ 这就是「整个界面卡顿」的隔离带：一旦在打字或 onResize 里调它，
  //    setSize → onResize → setSize 会形成抖动环，每帧整画布重绘 → 全界面卡。
  // 下限 = 标题 + 各可见 widget 实际高度（多行 STRING 会更高）+ DOM 固定行 + 提示词框最小高度。
  // 这样 4 个或 8 个表面参数（三视图预设句框显/隐）都自适应，不用手写魔数。
  const widgetRowH = (w) => {
    try {
      const s = w && w.computeSize ? w.computeSize(node.size?.[0] || 420) : null;
      if (Array.isArray(s) && Number.isFinite(s[1]) && s[1] > 0) return s[1];
    } catch (_) {}
    return (w && (w.type === "hidden" || w.hidden)) ? 0 : 26;
  };
  const minNodeHeight = () => {
    let h = 30;   // 节点标题
    for (const w of (node.widgets || [])) h += widgetRowH(w);
    return Math.max(420, Math.round(h + DOM_FIXED_H + TEXT_MIN_H));
  };
  refreshSize = () => {
    try {
      lockMinWidth();
      syncDomWidth();
      const size = node.computeSize?.();
      const computed = (Array.isArray(size) && Number.isFinite(size[1])) ? size[1] : 0;
      const need = Math.max(computed, minNodeHeight());   // 取「原生计算」与「DOM 需求」的较大值
      if (!node.size || !Number.isFinite(node.size[1]) || node.size[1] < need) {
        node.setSize?.([node.size?.[0] || MIN_W, need]);
      }
    } catch (_) {}
    node.setDirtyCanvas?.(true, true);
  };
  refreshSize();
  requestAnimationFrame(refreshSize);
  setTimeout(refreshSize, 60);
  setTimeout(refreshSize, 1200);   // 兜底：加载工作流后 widget 才铺完时再校正一次（只增不减）
  node._xbRefreshSize = refreshSize;
  node._xbEl = container;   // 调试/自动化定位用

  // Nodes 2.0：面板里的提示词框不会自己长高（节点高度由 DOM 内容主导，flex:1 停在 min-height）
  //   → 默认 300px；用户拖节点尺寸手柄时按指针位移实时跟随（两个方向都跟手）；
  //   切回经典模式自动还原原样，交回原有 flex 布局。
  try {
    node._xbUninstallBoxResize = installNodes2BoxResize(node, promptBox, {
      min: TEXT_MIN_H, max: 4000, deflt: TEXT_MIN_H,
    });
  } catch (e) { console.warn("[XB-生图提示词预设] 2.0 高度跟随安装失败", e); }

  // 节点 resize：立即同步 overlay 宽度 + 重绘；防抖后只校正「最小宽度 / 最小高度」。
  // ⚠️ 高度下限是硬约束（输入框永远 ≥500px）：拖小节点时一次性拉回，
  //    拉回后尺寸已等于下限 → 不会再次触发 setSize，不会形成抖动环。
  let _xbResizeTimer = null;
  let _xbClamping = false;
  const prevOnResize = node.onResize;
  node.onResize = function (...args) {
    const rr = prevOnResize?.apply(this, args);
    try {
      syncDomWidth();
      if (!_xbClamping) {
        const need = minNodeHeight();
        const cur = Number.isFinite(node.size?.[1]) ? node.size[1] : 0;
        if (cur < need) {
          _xbClamping = true;
          try { node.setSize?.([node.size?.[0] || MIN_W, need]); } finally { _xbClamping = false; }
        }
      }
      node.setDirtyCanvas?.(true, true);
      clearTimeout(_xbResizeTimer);
      _xbResizeTimer = setTimeout(() => { lockMinWidth(); syncDomWidth(); node.setDirtyCanvas?.(true, true); }, 200);
    } catch (_) {}
    return rr;
  };

  // 每帧绘制前景时同步本节点 overlay 宽度（对齐短剧导演台的 canvas.onDrawForeground patch）：
  // 属性面板/任何画布重排触发重绘后，下一帧即把 widget.width 纠正为节点宽度，杜绝挤压漂移
  try {
    const cv = node.graph?.canvas ?? window.app?.canvas;
    if (cv && !cv.__xbDomWidthPatch) {
      cv.__xbDomWidthPatch = true;
      const prevDraw = cv.onDrawForeground;
      cv.onDrawForeground = function (ctx) {
        const r = prevDraw?.apply(this, arguments);
        try {
          const g = window.app?.graph;
          const ns = g ? (g._nodes || g.nodes || []) : [];
          for (const n of ns) if (n && n._xbDomWidget && n._xbSyncWidth) n._xbSyncWidth();
        } catch (_) {}
        return r;
      };
    }
  } catch (_) {}

  // ── 旧版配置一次性迁移：老工作流把语言/模式/预设句/通道存在 manager_settings.output 里，
  //    现在这四项都是节点表面参数了 → 迁到 widget 上，并把 output 从 JSON 里删掉（只迁一次）。
  const migrateLegacyOutput = () => {
    try {
      const raw = readWidgetValue(findWidget(node, "manager_settings"));
      if (!raw || typeof raw !== "string" || !raw.trim()) return;
      let data = null;
      try { data = JSON.parse(raw); } catch (_) { return; }
      if (!data || typeof data !== "object") return;
      const out = data.output;
      const untouched = pickOpt(LANGS, readWidgetValue(wLang), LANG_ZH) === LANG_ZH
        && pickOpt(MODES, readWidgetValue(wMode), MODE_TP) === MODE_TP
        && String(readWidgetValue(w3v) ?? "").trim() === THREE_VIEW_DEFAULT[LANG_ZH];
      if (out && typeof out === "object" && untouched) {
        if (LANGS.includes(out.lang)) setWidgetValue(wLang, out.lang);
        if (MODES.includes(out.preset_mode)) setWidgetValue(wMode, out.preset_mode);
        if (typeof out.three_view_text === "string" && out.three_view_text.trim()) setWidgetValue(w3v, out.three_view_text);
        if (String(out.latent_channels || "").startsWith("16")) setWidgetValue(wKind, LATENT_KINDS[1]);
        notify("已把旧版「输出设置」里的语言/模式/预设句/空latent类型迁到节点表面参数", "success");
      }
      if (out !== undefined) {
        delete data.output;
        setWidgetValue(findWidget(node, "manager_settings"), JSON.stringify(data));
      }
    } catch (_) {}
  };

  // ── 载入 / 执行后的对齐 ──
  const boot = () => {
    hideInternal();          // 工作流加载后 widget 可能被重建 → 重新藏
    migrateLegacyOutput();
    syncPromptBoxFromWidget();
    applyKindLimits();       // 按当前空latent类型同步 step / 上下限
    applyPresetTextVisibility();
    // 预设句：以「用户存档 → 默认」为准（widget 值本就随工作流存着；这里兜底空值 / 被清空的情况）
    {
      const m = surfaceOf().mode, l = surfaceOf().lang;
      if (defaultPresetOf(m, l) && !String(readWidgetValue(w3v) ?? "").trim()) setPresetText(presetTextFor(m, l));
    }
    const ar = String(readWidgetValue(wAR) ?? "Free");
    const [nw, nh] = normalizeSize(ar, readWidgetValue(wW), readWidgetValue(wH), sizeOpt());
    if (nw !== parseInt(readWidgetValue(wW), 10) || nh !== parseInt(readWidgetValue(wH), 10)) {
      syncing = true;
      try { setWidgetValue(wW, nw); setWidgetValue(wH, nh); } finally { syncing = false; }
    }
    refreshSize();
  };
  node._xbEl = container;   // 调试 / 自动化定位锚点
  node.__ippSyncPromptBox = syncPromptBoxFromWidget;
  // 供 Pro 弹窗（✨ 增强预设）读写设定词：取「存档 → 默认」/ 写 widget / 存进节点
  node.__ippPresetTextFor = presetTextFor;
  node.__ippSetPreset = setPresetText;
  node.__ippWritePreset = writePresetStore;
  setTimeout(boot, 0);
  setTimeout(boot, 200);

  const prevConfigure = node.onConfigure;
  node.onConfigure = function (...args) {
    const r = prevConfigure?.apply(this, args);
    setTimeout(boot, 60);
    setTimeout(killGhost, 200);
    return r;
  };

  const prevRemoved = node.onRemoved;
  node.onRemoved = function (...args) {
    closePanel();
    return prevRemoved?.apply(this, args);
  };
}

/* ============================================================================
 *  ✨ 提示词增强反推（融合进「🖼️ 生图提示词预设Pro」）
 *  ---------------------------------------------------------------------------
 *  节点表面新增：3 个按钮（🤖 大语言模型配置 ｜ ✨ 提示词增强预设 ｜ 📖 使用说明）
 *                + 「✅ 启用 LLM 反推」开关（节点表面参数，默认关）
 *                + 提示词框标题行（右侧「📋 复制」）+ 参数设定显示（只读摘要）
 *                + 「📝 提示词」端口接线 → 提示词框锁定（二选一）
 *  弹窗：导演台同款二级弹窗（底部：自动保存 + 字号 + 界面缩放 + 取消/💾 保存）
 *  配置：manager_settings.llm = { model, run, params, extra_system }（与后端 _llm_section 对齐）
 *  说明：本块所有标识符统一 xbr/XBR 前缀，避免与生图预设面板既有函数/常量重名。
 * ========================================================================== */

const XBR_DEFAULT_PROVIDER = "OpenAI 兼容 (OpenAI/DeepSeek/Qwen/GLM/Kimi/Ollama/vLLM/LM Studio)";
const XBR_API_DEFAULTS = {
  provider: XBR_DEFAULT_PROVIDER,
  model: "deepseek-v4-flash-vision-exp",
  api_key: "",
  base_url: "https://api.deepseek.com/v1",
  temperature: 0.6,
  max_tokens: 8192,
  thinking: "disabled",
};
const XBR_BACKENDS = [
  { value: "本地模型", label: "本地模型 [local]" },
  { value: "在线 API", label: "在线API [api]" },
];
const XBR_INFERENCE_MODES = ["one by one", "images", "video"];
const XBR_SEED_MODES = ["randomize", "fixed", "increment", "decrement"];
const XBR_SEED_LABEL = { randomize: "随机", fixed: "固定", increment: "增加", decrement: "减少" };
const XBR_PANEL_BUTTONS = [
  { id: "llm", label: "🤖 LLM设置", title: "🤖 LLM设置", subtitle: "LLM 反推的后端与推理配置；本弹窗里的「输出语言」是全节点唯一的语言设置（决定词表加载语言 + 最终提示词语言）。" },
  { id: "preset", label: "✨ 增强预设", title: "✨ 增强预设", subtitle: "空latent类型 / 预设模式 / 增强预设（= 提示词设定）/ 反推预设 / 追加设定。提示词正文在节点上的提示词框里编辑。" },
  { id: "help", label: "📖 使用说明", title: "📖 使用说明", subtitle: "端口 / 按钮 / 保存说明。" },
];
const XBR_API_ENDPOINT = "/xb_toolbox/llm_api_settings";

/* ── 数值 / 解析助手 ─────────────────────────────────────── */
function xbrNum(v, d, lo, hi) {
  let x = Number(v);
  if (!Number.isFinite(x)) x = d;
  if (lo !== undefined) x = Math.max(lo, x);
  if (hi !== undefined) x = Math.min(hi, x);
  return x;
}
function xbrInt(v, d, lo, hi) { return Math.round(xbrNum(v, d, lo, hi)); }
function xbrFlag(v, d) {
  if (v === undefined || v === null || v === "") return d;
  return (typeof v === "string") ? ["1", "true", "yes", "on", "开启"].includes(v.trim().toLowerCase()) : !!v;
}
function xbrPick(v, allowed, d) { return allowed.includes(v) ? v : d; }

const XBR_INFERENCE_MODES_ = XBR_INFERENCE_MODES;
function xbrLlmDefaults() {
  return {
    model: { model: "", mmproj: "None", chat_handler: "None", n_ctx: 8192, vram_limit: -1, image_min_tokens: 0, image_max_tokens: 0 },
    run: { inference_mode: "one by one", max_frames: 24, max_size: 256, seed: 0, seed_control: "randomize", force_offload: false, save_states: false, strip_thinking: true },
    params: {
      max_tokens: 6144, top_k: 40, top_p: 0.9, min_p: 0.05, typical_p: 1.0, temperature: 0.6,
      repeat_penalty: 1.12, frequency_penalty: 0.0, present_penalty: 0.0,
      mirostat_mode: 0, mirostat_eta: 0.1, mirostat_tau: 5.0, state_uid: -1,
    },
    extra_system: "",
  };
}
/** 解析 manager_settings.llm（缺失/非法一律安全回落） */
function xbrParseLlm(raw) {
  const d = (raw && typeof raw === "object") ? raw : {};
  const cfg = xbrLlmDefaults();
  const m = (d.model && typeof d.model === "object") ? d.model : {};
  cfg.model.model = String(m.model ?? "");
  cfg.model.mmproj = String(m.mmproj ?? "None");
  cfg.model.chat_handler = String(m.chat_handler ?? "None");
  cfg.model.n_ctx = xbrInt(m.n_ctx, cfg.model.n_ctx, 1024, 327680);
  cfg.model.vram_limit = xbrInt(m.vram_limit, cfg.model.vram_limit, -1, 1024);
  cfg.model.image_min_tokens = xbrInt(m.image_min_tokens, 0, 0, 4096);
  cfg.model.image_max_tokens = xbrInt(m.image_max_tokens, 0, 0, 4096);

  const r = (d.run && typeof d.run === "object") ? d.run : {};
  cfg.run.inference_mode = xbrPick(r.inference_mode, XBR_INFERENCE_MODES, cfg.run.inference_mode);
  cfg.run.max_frames = xbrInt(r.max_frames, cfg.run.max_frames, 2, 1024);
  cfg.run.max_size = xbrInt(r.max_size, cfg.run.max_size, 128, 16384);
  cfg.run.seed = xbrInt(r.seed, cfg.run.seed, 0, Number.MAX_SAFE_INTEGER);
  cfg.run.seed_control = xbrPick(r.seed_control, XBR_SEED_MODES, cfg.run.seed_control);
  cfg.run.force_offload = xbrFlag(r.force_offload, cfg.run.force_offload);
  cfg.run.save_states = xbrFlag(r.save_states, cfg.run.save_states);
  cfg.run.strip_thinking = xbrFlag(r.strip_thinking, cfg.run.strip_thinking);   // 模型输出思考过程时自动过滤

  const p = (d.params && typeof d.params === "object") ? d.params : {};
  cfg.params.max_tokens = xbrInt(p.max_tokens, cfg.params.max_tokens, 0, 262144);
  cfg.params.top_k = xbrInt(p.top_k, cfg.params.top_k, 0, 1000);
  cfg.params.top_p = xbrNum(p.top_p, cfg.params.top_p, 0, 1);
  cfg.params.min_p = xbrNum(p.min_p, cfg.params.min_p, 0, 1);
  cfg.params.typical_p = xbrNum(p.typical_p, cfg.params.typical_p, 0, 1);
  cfg.params.temperature = xbrNum(p.temperature, cfg.params.temperature, 0, 2);
  cfg.params.repeat_penalty = xbrNum(p.repeat_penalty, cfg.params.repeat_penalty, 0, 10);
  cfg.params.frequency_penalty = xbrNum(p.frequency_penalty, cfg.params.frequency_penalty, 0, 1);
  cfg.params.present_penalty = xbrNum(p.present_penalty, cfg.params.present_penalty, 0, 2);
  cfg.params.mirostat_mode = xbrInt(p.mirostat_mode, cfg.params.mirostat_mode, 0, 2);
  cfg.params.mirostat_eta = xbrNum(p.mirostat_eta, cfg.params.mirostat_eta, 0, 1);
  cfg.params.mirostat_tau = xbrNum(p.mirostat_tau, cfg.params.mirostat_tau, 0, 10);
  cfg.params.state_uid = xbrInt(p.state_uid, cfg.params.state_uid, -1, 999999);
  cfg.extra_system = String(d.extra_system ?? "");
  return cfg;
}

/* ── 节点 widget 读写 ─────────────────────────────────────── */
function xbrWidget(node, name) { return (node?.widgets || []).find((w) => w?.name === name); }
function xbrWidgetVal(node, name) { return readWidgetValue(xbrWidget(node, name)); }
/** fire=true 时同步触发该 widget 原有回调（基础面板靠回调做步长/预设句框/尺寸联动） */
function xbrSetWidget(node, name, val, fire) {
  const w = xbrWidget(node, name);
  setWidgetValue(w, val);
  if (fire) { try { w?.callback?.(val); } catch (_) {} }
}
function xbrHint(text) { return el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", text); }
function xbrWidgetOptions(node, name) {
  const w = xbrWidget(node, name);
  const o = w?.options?.values ?? w?.options;
  return Array.isArray(o) ? o.slice() : [];
}
function xbrCurJson(node) {
  try {
    const raw = readWidgetValue(findWidget(node, "manager_settings"));
    const d = JSON.parse(raw || "{}");
    return (d && typeof d === "object") ? d : {};
  } catch (_) { return {}; }
}
function xbrSaveJson(node, patch) {
  const cur = xbrCurJson(node);
  Object.assign(cur, patch || {});
  persistSettings(node, cur);
  return cur;
}

/* ── 预设设定词（三视图 / 四视图 / 五视图 / 背景纯透明的设定文本）─────────────
 * · 用户改过的按「模式|语言」存进节点（基础面板的 preset_texts 存档）；
 * · 弹窗读「存档 → 默认」，提交时同步写 widget + 存档。 */
function xbrPresetStore(node) {
  try { return parsePresetTexts(xbrCurJson(node).preset_texts); } catch (_) { return {}; }
}
function xbrPresetTextFor(node, mode, lang) {
  const t = xbrPresetStore(node)[presetKeyOf(mode, lang)];
  return (t && String(t).trim()) ? t : (defaultPresetOf(mode, lang) || "");
}

/* ── 预设选项按「输出语言」过滤 ───────────────────────────────
 * 预设名的语言标签形如 "Z-Image Turbo [ZH]" / "Normal - 描述 [EN]"；
 * 输出语言选中文 → 增强预设 / 反推预设 只列 [ZH] 项，选英文 → 只列 [EN] 项。 */
function xbrLangTagOf(v) {
  const m = String(v == null ? "" : v).match(/[\[［](ZH|EN)[\]］]\s*$/i);
  return m ? m[1].toUpperCase() : "";
}
function xbrFilterByLang(opts, lang) {
  const want = xbrLangTagOf(lang);
  if (!want) return opts.slice();
  const hit = opts.filter((o) => xbrLangTagOf(o) === want);
  return hit.length ? hit : opts.slice();      // 全无语言标签（老预设）→ 全量兜底
}
/** 语言变了：优先换到「同名的另一语言项」，否则取该语言第一项 */
function xbrSnapPreset(opts, cur, lang) {
  const list = xbrFilterByLang(opts, lang);
  if (list.includes(cur)) return cur;
  const base = String(cur == null ? "" : cur).replace(/\s*[\[［](ZH|EN)[\]］]\s*$/i, "").trim();
  const same = list.find((o) => String(o).replace(/\s*[\[［](ZH|EN)[\]］]\s*$/i, "").trim() === base);
  return same || list[0] || cur;
}

/* ── 在线 API（存 ComfyUI user 目录，Key 不进工作流）──────── */
async function xbrApiGet() {
  const resp = await api.fetchApi(XBR_API_ENDPOINT);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
  return { settings: data.settings || {}, providers: data.providers || [] };
}
async function xbrApiPut(payload) {
  const resp = await api.fetchApi(XBR_API_ENDPOINT, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
  return data.settings || payload;
}
function xbrNormApi(raw) {
  const x = { ...XBR_API_DEFAULTS, ...(raw && typeof raw === "object" ? raw : {}) };
  x.provider = String(x.provider || "").trim() || XBR_DEFAULT_PROVIDER;
  x.model = String(x.model ?? "").trim() || XBR_API_DEFAULTS.model;
  x.base_url = String(x.base_url ?? "").trim() || XBR_API_DEFAULTS.base_url;
  x.api_key = String(x.api_key ?? "");
  x.temperature = xbrNum(x.temperature, XBR_API_DEFAULTS.temperature, 0, 2);
  x.max_tokens = xbrInt(x.max_tokens, XBR_API_DEFAULTS.max_tokens, 1, 262144);
  x.thinking = (x.thinking === "enabled") ? "enabled" : "disabled";
  return x;
}

/* ── 本地模型候选（取「📦 模型加载器」的 object_info，单一真相）── */
let xbrModelLists = null;
async function xbrLoadModelLists(force) {
  if (xbrModelLists && !force) return xbrModelLists;
  try {
    const resp = await api.fetchApi("/object_info/XB_llamaModelLoader");
    const data = await resp.json();
    const req = data?.XB_llamaModelLoader?.input?.required || {};
    xbrModelLists = {
      model: Array.isArray(req.model?.[0]) ? req.model[0] : [],
      mmproj: Array.isArray(req.mmproj?.[0]) ? req.mmproj[0] : ["None"],
      chat_handler: Array.isArray(req.chat_handler?.[0]) ? req.chat_handler[0] : ["None"],
    };
  } catch (_) {
    xbrModelLists = { model: [], mmproj: ["None"], chat_handler: ["None"] };
  }
  return xbrModelLists;
}

/* ── 控件：数字 / 密码 / 单选行 / 种子行 ─────────────────── */
function xbrNumberControl(value, opts, onChange) {
  const i = el("input", BOX_CSS + "min-width:0;");
  i.type = "number";
  i.value = value ?? 0;
  if (opts) {
    if (opts.min !== undefined) i.min = opts.min;
    if (opts.max !== undefined) i.max = opts.max;
    i.step = opts.step ?? 1;
  }
  i.addEventListener("change", () => {
    let v = parseFloat(i.value);
    if (!Number.isFinite(v)) v = opts?.min ?? 0;
    if (opts?.min !== undefined) v = Math.max(opts.min, v);
    if (opts?.max !== undefined) v = Math.min(opts.max, v);
    i.value = v;
    onChange(v);
  });
  return i;
}
function xbrPasswordControl(value, placeholder, onChange) {
  const i = el("input", BOX_CSS + "min-width:0;");
  i.type = "password";
  i.value = value ?? "";
  if (placeholder) i.placeholder = placeholder;
  i.autocomplete = "new-password";
  i.spellcheck = false;
  i.addEventListener("change", () => onChange(i.value.trim()));
  return i;
}
function xbrTextControl(value, placeholder, onChange) {
  const i = el("input", BOX_CSS + "min-width:0;");
  i.type = "text";
  i.value = value ?? "";
  if (placeholder) i.placeholder = placeholder;
  i.spellcheck = false;
  i.addEventListener("change", () => onChange(i.value.trim()));
  return i;
}
/** 导演台同款「种子 + 生成后控制（随机/固定/增加/减少）」一行 */
function xbrSeedRow(run, onChange) {
  const g = el("div", "display:flex;align-items:center;gap:10px;margin-bottom:10px;");
  g.append(el("label", "flex:0 0 160px;font-size:13px;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;", "种子"));
  const i = xbrNumberControl(run.seed, { min: 0, max: Number.MAX_SAFE_INTEGER, step: 1 }, (v) => { run.seed = Math.round(v); onChange?.(); });
  i.style.flex = "1 1 0";
  const ctrl = smallBtn("", "flex:1 1 0;min-width:0;background:#b45309;border:1px solid #d97706;color:#fff;text-align:center;", "生成后控制：点击在 随机 / 固定 / 增加 / 减少 间切换", null);
  const cur = () => (XBR_SEED_LABEL[run.seed_control] ? run.seed_control : "randomize");
  const render = () => {
    ctrl.textContent = "🔁 " + XBR_SEED_LABEL[cur()];
    ctrl.title = "生成后控制：随机 = 每次运行后自动换新种子；固定 = 锁定当前值；增加/减少 = 每次运行后 ±1。点击切换";
  };
  ctrl.addEventListener("click", () => {
    run.seed_control = XBR_SEED_MODES[(XBR_SEED_MODES.indexOf(cur()) + 1) % XBR_SEED_MODES.length];
    render();
    onChange?.();
  });
  render();
  g.append(i, ctrl);
  return g;
}

/* ── 弹窗外壳（与生图预设面板同风格；底部：自动保存 + 字号 + 界面缩放）── */
let xbrModal = null;
function xbrDialog({ label, title, subtitle, width = 820, autoSaveRef = null, onCommit = null, onImmediate = null, onChange = null, onClose = null }) {
  const overlay = el("div", "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:10300;display:flex;align-items:center;justify-content:center;overflow:auto;");
  const dialog = el("section", `background:#1c1c1e;border:1px solid #333;border-radius:8px;width:${width}px;max-width:94vw;` +
    "max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 40px rgba(0,0,0,.6);flex:0 0 auto;color:#ddd;font-size:13px;");
  dialog.dataset.xbrProModal = label;
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", label);

  const header = el("div", "padding:18px 20px;border-bottom:1px solid #444;");
  header.append(el("div", "font-size:17px;font-weight:700;color:#eee;", title));
  if (subtitle) header.append(el("div", "font-size:12px;color:#999;margin-top:5px;line-height:1.6;", subtitle));
  const body = el("div", "padding:16px 20px;overflow-y:auto;flex:1;min-height:200px;");
  const error = el("div", "color:#e55;font-size:12px;margin:0 20px;min-height:14px;");
  const footer = el("div", "padding:12px 20px;border-top:1px solid #444;display:flex;justify-content:flex-end;gap:10px;align-items:center;background:#18181a;border-bottom-left-radius:8px;border-bottom-right-radius:8px;");
  const left = el("div", "display:flex;align-items:center;gap:16px;margin-right:auto;flex-wrap:wrap;");

  let autoCb = null;
  if (autoSaveRef) {
    const autoRow = el("label", "display:flex;align-items:center;gap:6px;font-size:13px;color:#999;cursor:pointer;user-select:none;");
    autoCb = el("input", "width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;");
    autoCb.type = "checkbox";
    autoCb.checked = autoSaveRef.value !== false;
    autoCb.title = "开启后：弹窗内改动会自动保存（防抖）；关闭后需手动点「💾 保存」";
    autoCb.addEventListener("change", () => { autoSaveRef.value = autoCb.checked; try { onImmediate?.(); } catch (_) {} });
    autoRow.append(autoCb, el("span", "", "自动保存"));
    left.append(autoRow);
  }
  const zoomRow = buildZoomRow(dialog);
  zoomRow.title = "调整面板文本编辑字号（与本节点其它面板共享记忆）";
  const uiRow = buildUIRow(dialog);
  uiRow.title = "调整整个弹窗界面大小（不缩放网页/画布；Ctrl/⌘+滚轮 也可）";
  left.append(zoomRow, uiRow);

  const cancelBtn = el("button", "background:transparent;border:1px solid #555;color:#fff;border-radius:4px;padding:8px 20px;font-size:14px;cursor:pointer;font-family:inherit;", "取消");
  const saveBtn = onCommit ? el("button", "background:#2d5a88;color:#fff;border:none;border-radius:4px;padding:8px 20px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;", "💾 保存") : null;
  footer.append(left, cancelBtn);
  if (saveBtn) footer.append(saveBtn);
  dialog.append(header, body, error, footer);
  overlay.append(dialog);
  document.body.append(overlay);
  zoomApplyContainer(dialog);
  uiApply(dialog);
  bindWheelZoom(dialog);

  let timer = null;
  const close = () => {
    clearTimeout(timer);
    try { overlay.remove(); } catch (_) {}
    if (xbrModal && xbrModal.overlay === overlay) xbrModal = null;
    try { onClose?.(); } catch (_) {}
  };
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
  document.addEventListener("keydown", onKey, true);
  cancelBtn.addEventListener("click", close);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      if (saveBtn.disabled) return;
      saveBtn.disabled = true;
      saveBtn.textContent = "保存中…";
      error.textContent = "";
      try { await onCommit(); close(); }
      catch (e) { error.textContent = "保存失败：" + ((e && e.message) || e); saveBtn.disabled = false; saveBtn.textContent = "💾 保存"; }
    });
  }
  // 自动保存（导演台同款：改动后防抖提交）
  body.addEventListener("change", () => {
    try { onChange?.(); } catch (_) {}
    if (autoSaveRef && autoSaveRef.value === false) { try { onImmediate?.(); } catch (_) {} return; }
    clearTimeout(timer);
    timer = setTimeout(() => { try { onCommit?.(); } catch (_) {} }, 800);
  });
  const shell = { overlay, dialog, body, error, close };
  xbrModal = shell;
  return shell;
}

/* ── 弹窗内容：🤖 大语言模型配置 ─────────────────────────── */
function xbrRenderLlm(body, node, draft, ctx) {
  const s = draft.settings.llm;

  body.append(makeSectionTitle("输出语言（全节点唯一的语言设置）"));
  body.append(field("输出语言", selectControl(LANGS, draft.lang, (v) => {
    draft.lang = v;
    // 换语言 → 未在弹窗里改过设定词时，跟着取该语言的「存档 → 默认」
    if (!draft.presetTouched) draft.presetText = xbrPresetTextFor(node, draft.mode, v);
    // 语言决定预设可选范围：增强预设 / 反推预设 自动换到同语言的同名项（没有则取该语言第一项）
    draft.preset = xbrSnapPreset(xbrWidgetOptions(node, "preset"), draft.preset, v);
    draft.task_preset = xbrSnapPreset(xbrWidgetOptions(node, "task_preset"), draft.task_preset, v);
  })));
  body.append(xbrHint("本项是唯一的语言设置：① 词表 / 设定词 / 预设句按哪种语言加载　② 增强预设与反推预设只列该语言的选项　③ 最终输出的提示词语言。"));

  body.append(makeSectionTitle("提示词增强反推（总开关在节点表面的「启用 LLM 反推」）"));

  body.append(makeSectionTitle("LLM 后端"));
  body.append(field("LLM 后端", radioRow(XBR_BACKENDS, draft.backend, (v) => { draft.backend = v; ctx.rerender(); })));

  if (draft.backend !== "在线 API") {
    body.append(makeSectionTitle("本地 LLM 模型"));
    const lists = xbrModelLists || { model: [], mmproj: ["None"], chat_handler: ["None"] };
    const llm = s.model;
    const models = lists.model.length ? lists.model : (llm.model ? [llm.model] : []);
    if (!llm.model && models.length) llm.model = models[0];
    body.append(field("强制卸载", checkboxControl(s.run.force_offload, "LLM 用完即卸载，释放显存", (v) => { s.run.force_offload = v; })));
    if (models.length) body.append(field("模型", selectControl(models, llm.model, (v) => { llm.model = v; })));
    else body.append(field("模型", xbrTextControl(llm.model, "未找到本地 LLM 模型（.gguf 放到 models/LLM）", (v) => { llm.model = v; })));
    body.append(field("视觉模块 mmproj", selectControl(lists.mmproj.length ? lists.mmproj : ["None"], llm.mmproj, (v) => { llm.mmproj = v; })));
    body.append(field("Chat Handler", selectControl(lists.chat_handler.length ? lists.chat_handler : ["None"], llm.chat_handler, (v) => { llm.chat_handler = v; })));
    body.append(field("上下文长度 n_ctx", xbrNumberControl(llm.n_ctx, { min: 1024, max: 327680, step: 128 }, (v) => { llm.n_ctx = Math.round(v); })));
    body.append(field("显存上限 vram_limit (GB)", xbrNumberControl(llm.vram_limit, { min: -1, max: 1024, step: 1 }, (v) => { llm.vram_limit = Math.round(v); })));
    body.append(field("图像最小 tokens", xbrNumberControl(llm.image_min_tokens, { min: 0, max: 4096, step: 32 }, (v) => { llm.image_min_tokens = Math.round(v); })));
    body.append(field("图像最大 tokens", xbrNumberControl(llm.image_max_tokens, { min: 0, max: 4096, step: 32 }, (v) => { llm.image_max_tokens = Math.round(v); })));

    const p = s.params;
    body.append(field("max_tokens", xbrNumberControl(p.max_tokens, { min: 0, max: 262144, step: 1 }, (v) => { p.max_tokens = Math.round(v); })));
    body.append(field("top_k", xbrNumberControl(p.top_k, { min: 0, max: 1000, step: 1 }, (v) => { p.top_k = Math.round(v); })));
    body.append(field("top_p", xbrNumberControl(p.top_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.top_p = v; })));
    body.append(field("min_p", xbrNumberControl(p.min_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.min_p = v; })));
    body.append(field("typical_p", xbrNumberControl(p.typical_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.typical_p = v; })));
    body.append(field("temperature", xbrNumberControl(p.temperature, { min: 0, max: 2, step: 0.01 }, (v) => { p.temperature = v; })));
    body.append(field("repeat_penalty", xbrNumberControl(p.repeat_penalty, { min: 0, max: 10, step: 0.01 }, (v) => { p.repeat_penalty = v; })));
    body.append(field("frequency_penalty", xbrNumberControl(p.frequency_penalty, { min: 0, max: 1, step: 0.01 }, (v) => { p.frequency_penalty = v; })));
    body.append(field("present_penalty", xbrNumberControl(p.present_penalty, { min: 0, max: 2, step: 0.01 }, (v) => { p.present_penalty = v; })));
    body.append(field("mirostat_mode", xbrNumberControl(p.mirostat_mode, { min: 0, max: 2, step: 1 }, (v) => { p.mirostat_mode = Math.round(v); })));
    body.append(field("mirostat_eta", xbrNumberControl(p.mirostat_eta, { min: 0, max: 1, step: 0.01 }, (v) => { p.mirostat_eta = v; })));
    body.append(field("mirostat_tau", xbrNumberControl(p.mirostat_tau, { min: 0, max: 10, step: 0.01 }, (v) => { p.mirostat_tau = v; })));
  }

  if (draft.backend === "在线 API") {
    body.append(makeSectionTitle("在线 API"));
    const a = draft.api || (draft.api = { ...XBR_API_DEFAULTS });
    body.append(field("服务商", selectControl(ctx.providers, a.provider, (v) => { a.provider = v; })));
    body.append(field("模型", xbrTextControl(a.model, XBR_API_DEFAULTS.model, (v) => { a.model = v; })));
    body.append(field("API Key", xbrPasswordControl(a.api_key, "sk-… 保存在本地，不写入工作流", (v) => { a.api_key = v; })));
    body.append(field("Base URL", xbrTextControl(a.base_url, XBR_API_DEFAULTS.base_url, (v) => { a.base_url = v; })));
    body.append(field("temperature", xbrNumberControl(a.temperature, { min: 0, max: 2, step: 0.01 }, (v) => { a.temperature = v; })));
    body.append(field("max_tokens", xbrNumberControl(a.max_tokens, { min: 1, max: 262144, step: 1 }, (v) => { a.max_tokens = Math.round(v); })));
    body.append(field("thinking", selectControl(["disabled", "enabled"], a.thinking, (v) => { a.thinking = v; })));
    body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "默认：deepseek-v4-flash-vision-exp ｜ https://api.deepseek.com/v1（可改）。配置保存在本地 ComfyUI user 目录，不会写入工作流。"));
  }

  body.append(makeSectionTitle("随机种子"));
  body.append(xbrSeedRow(s.run, () => ctx.touch?.()));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "点「🔁」切换生成后控制：随机 = 运行后自动换新种子；固定 = 锁定；增加/减少 = 运行后 ±1（后端算完会回写）。"));

  body.append(makeSectionTitle("指令推理"));
  body.append(field("推理模式", selectControl(XBR_INFERENCE_MODES, s.run.inference_mode, (v) => { s.run.inference_mode = v; })));
  body.append(field("最大帧数", xbrNumberControl(s.run.max_frames, { min: 2, max: 1024, step: 1 }, (v) => { s.run.max_frames = Math.round(v); })));
  body.append(field("最大尺寸", xbrNumberControl(s.run.max_size, { min: 128, max: 16384, step: 64 }, (v) => { s.run.max_size = Math.round(v); })));
  body.append(field("保存对话状态", checkboxControl(s.run.save_states, "在内存中保留本次对话上下文，多轮连续反推", (v) => { s.run.save_states = v; })));
  body.append(field("状态 UID", xbrNumberControl(s.params.state_uid, { min: -1, max: 999999, step: 1 }, (v) => { s.params.state_uid = Math.round(v); })));
  body.append(field("🧠 过滤思考过程", checkboxControl(s.run.strip_thinking,
    "模型把「思考过程 / 推理段 / 工作流程」一起输出时，自动只保留最终提示词", (v) => { s.run.strip_thinking = v; })));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.65;margin:2px 0 8px;",
    "开启后＝① 系统提示词末尾追加「只输出最终提示词」硬规则　② 仍漏出思考时自动剔除思考标签、"
    + "Final Output / 最终输出 标记之前的推理段与代码围栏（拿不到内容则原文保留）。"));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "提示词正文在节点上的提示词框里编辑；「📝 提示词」端口接线后该框锁定。"));
}

/* ── 弹窗内容：✨ 提示词增强预设 ─────────────────────────── */
function xbrRenderPreset(body, node, draft, ctx) {
  const s = draft.settings.llm;

  body.append(makeSectionTitle("生图预设"));
  body.append(field("空latent类型", selectControl(LATENT_KINDS, draft.kind, (v) => { draft.kind = v; })));
  body.append(xbrHint("空latent类型：选你正在用的模型即可（形状 / 下采样 / 尺寸步长自动适配 8/16/32）。"));
  body.append(field("预设模式", selectControl(MODES, draft.mode, (v) => {
    draft.mode = v;
    // 换模式 → 立刻取该模式的设定词（用户改过的存档 → 默认），改过的不会被冲掉
    draft.presetTouched = false;
    draft.presetText = xbrPresetTextFor(node, v, draft.lang);
    ctx.rerender();     // 有/无设定词的模式之间切换 → 重画「设定词」区
  })));
  body.append(xbrHint("常规文生图 = 只输出正文；人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明 = 最终提示词最顶端自动加上该模式的设定词。"));

  // ── 设定词（预设模式对应的设定文本；只在弹窗里编辑，节点表面不显示）──
  const modeDef = defaultPresetOf(draft.mode, draft.lang);
  if (modeDef) {
    body.append(makeSectionTitle("设定词"));
    if (!String(draft.presetText || "").trim()) draft.presetText = modeDef;
    const taP = textareaControl(draft.presetText, (v) => { draft.presetText = v; draft.presetTouched = true; },
      "width:100%;box-sizing:border-box;min-height:180px;resize:vertical;");
    taP.placeholder = "该模式的设定词；改过的按「模式 + 语言」记进节点，换模式 / 换语言都不丢";
    taP.spellcheck = false;
    body.append(taP);
    const taRow = el("div", "display:flex;align-items:center;gap:10px;margin:6px 0 4px;");
    taRow.append(smallBtn("♻️ 恢复默认", "border:1px solid #555;background:#2a2a2a;color:#ccc;padding:4px 10px;",
      "把设定词恢复为该模式 × 该语言的默认文本",
      () => { draft.presetText = modeDef; draft.presetTouched = false; ctx.rerender(); }));
    taRow.append(el("span", "font-size:11px;color:#888;",
      String(draft.presetText || "") === modeDef ? "当前 = 默认" : "当前 = 自定义"));
    body.append(taRow);
    body.append(el("div", "font-size:11px;color:#888;line-height:1.75;margin:6px 0 8px;",
      "· 最终输出时，设定词会原封不动加在增强后提示词的最顶端；\n"
      + "· LLM 只增强正文，把设定词当作增强参考，不会改写它；\n"
      + "· 改过的设定词随节点保存，换模式 / 换语言都会取回你改过的那一版。"));
  } else {
    body.append(el("div", "font-size:11px;color:#888;line-height:1.75;margin:6px 0 8px;", "常规文生图 = 没有设定词，直接输出正文。"));
  }

  body.append(makeSectionTitle("增强预设（= 提示词设定 / system prompt）"));
  const presetOpts = xbrFilterByLang(xbrWidgetOptions(node, "preset"), draft.lang);
  if (presetOpts.length) body.append(field("增强预设", selectControl(presetOpts, draft.preset, (v) => { draft.preset = v; })));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;",
    `该预设内容即「🧩 提示词设定」输出的正文，同时作为 LLM 反推的系统提示词；只列与输出语言 ${draft.lang} 相符的预设。`));

  body.append(makeSectionTitle("反推预设"));
  const taskOpts = xbrFilterByLang(xbrWidgetOptions(node, "task_preset"), draft.lang);
  if (taskOpts.length) body.append(field("反推预设", selectControl(taskOpts, draft.task_preset, (v) => { draft.task_preset = v; })));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "带 * 的预设里 * 是必填占位符，由节点上的提示词框或外接「📝 提示词」填入。"));

  body.append(makeSectionTitle("追加设定（可留空）"));
  const ta = textareaControl(s.extra_system, (v) => { s.extra_system = v; },
    "width:100%;box-sizing:border-box;min-height:200px;resize:vertical;");
  ta.placeholder = "追加在增强预设之后的额外要求，例：只输出一行、不要解释过程…";
  ta.spellcheck = false;
  body.append(ta);
}

/* ── 弹窗内容：📖 使用说明 ───────────────────────────────── */
function xbrRenderHelp(body) {
  const lines = [
    "【本节点 = 生图提示词预设 + 提示词增强反推】",
    "",
    "【输入端口】",
    "  · 📝 提示词：外接提示词；接线后节点上的提示词框会锁定，二选一",
    "  · 🖼️ 图像：外接图像 / 视频帧",
    "  · 有图 + 有文字 = 看图改图：先识图，再把文字当修改指令执行，只输出修改后的最终画面提示词",
    "  · 只有图 = 看图写提示词；只有文字 = 文案增强",
    "",
    "【输出端口】",
    "  · 📝 提示词：最终提示词。未启用 LLM = 拼装好的提示词；启用 LLM = 设定词原封不动置顶 + LLM 增强后的正文",
    "  · 📊 空latent：第二位。按「空latent类型」生成，官方 latent_format 逐字段对齐",
    "  · 📋 提示词列表：按行拆分",
    "  · 🧩 提示词设定：本次的提示词设定，即增强预设 + 输出语言 + 追加设定",
    "",
    "【节点表面】",
    "  · 第 1 行按钮：🤖 LLM设置（唯一语言设置 / 后端 / 采样参数）｜ ✨ 增强预设（空latent类型 / 预设模式 / 增强预设 / 反推预设 / 追加设定）｜ 📖 使用说明",
    "  · 第 2 行按钮：8 个元素分类（点选项行加入/移除提示词，【添加详细描述】写补充说明）",
    "  · ✅ 启用 LLM 反推：关（默认）= 原「生图提示词预设」行为；开 = 图/文 → 提示词",
    "  · 设定词：预设模式（三视图 / 四视图 / 五视图 / 背景纯透明）的设定文本，在「✨ 增强预设」弹窗里编辑；"
    + "改过的随节点保存，换模式 / 换语言不丢；输出时原封不动加在增强结果的顶端，也作为 LLM 的增强参考",
    "  · 提示词框右上角「📋 复制」；下方「参数设定显示」实时显示当前配置",
    "",
    "【保存】",
    "  · 弹窗底部：☑ 自动保存（默认开）+ 字号 + 界面缩放；「取消」丢弃未保存改动",
    "  · 配置随工作流保存；在线 API 的 Key 存在 ComfyUI user 目录，不进工作流",
    "",
    "【语言 / 思考过程】",
    "  · 输出语言（🤖 LLM设置）是唯一语言设置：决定词表与设定词按哪种语言加载、增强预设与反推预设只列哪种语言的选项、最终提示词的语言",
    "  · 🧠 过滤思考过程（🤖 LLM设置 → 指令推理，默认开）：系统提示词末尾追加「只输出最终提示词」硬规则；模型仍漏出思考过程时，自动剔掉思考标签、Final Output / 最终输出 之前的推理段与代码围栏",
  ];
  body.append(el("div", "font-size:12px;color:#bbb;line-height:1.9;white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;", lines.join("\n")));
}

const XBR_PANEL_RENDER = { llm: xbrRenderLlm, preset: xbrRenderPreset, help: xbrRenderHelp };

async function xbrOpenModal(node, panelId) {
  if (xbrModal) { try { xbrModal.close(); } catch (_) {} }
  const meta = XBR_PANEL_BUTTONS.find((b) => b.id === panelId) || XBR_PANEL_BUTTONS[0];
  const cur = xbrCurJson(node);
  const autoSaveRef = { value: cur.auto_save !== false };
  const draft = {
    settings: { llm: xbrParseLlm(cur.llm) },
    backend: String(xbrWidgetVal(node, "backend") ?? XBR_BACKENDS[0].value),
    preset: String(xbrWidgetVal(node, "preset") ?? ""),
    task_preset: String(xbrWidgetVal(node, "task_preset") ?? ""),
    lang: xbrPick(String(xbrWidgetVal(node, "output_lang") ?? ""), LANGS, LANGS[0]),
    kind: xbrPick(String(xbrWidgetVal(node, "latent_kind") ?? ""), LATENT_KINDS, LATENT_KINDS[0]),
    mode: xbrPick(String(xbrWidgetVal(node, "preset_mode") ?? ""), MODES, MODES[0]),
    // 设定词（三视图/四视图/五视图/背景纯透明）：弹窗内草稿 + 「用户是否改过」标记
    presetText: String(xbrWidgetVal(node, "three_view_text") ?? ""),
    presetTouched: false,
  };
  // 预设选项与输出语言对齐（旧工作流可能存着异语言的预设名）
  draft.preset = xbrSnapPreset(xbrWidgetOptions(node, "preset"), draft.preset, draft.lang);
  draft.task_preset = xbrSnapPreset(xbrWidgetOptions(node, "task_preset"), draft.task_preset, draft.lang);

  let apiSaved = null, providers = [XBR_DEFAULT_PROVIDER];
  if (panelId === "llm") {
    try {
      const r = await xbrApiGet();
      apiSaved = xbrNormApi(r.settings);
      if (r.providers?.length) providers = r.providers;
    } catch (_) { apiSaved = xbrNormApi(node.__xbrProApiInfo); }
    node.__xbrProApiInfo = apiSaved;
    draft.api = { ...apiSaved };
  }

  const commit = async () => {
    if (panelId === "llm" && draft.api && apiSaved
      && JSON.stringify(xbrNormApi(draft.api)) !== JSON.stringify(apiSaved)) {
      try {
        apiSaved = xbrNormApi(await xbrApiPut(xbrNormApi(draft.api)));
        draft.api = { ...apiSaved };
        node.__xbrProApiInfo = apiSaved;
      } catch (e) { notify("API 配置保存失败：" + ((e && e.message) || e), "error"); }
    }
    xbrSetWidget(node, "output_lang", draft.lang, true);      // 唯一语言设置
    xbrSetWidget(node, "latent_kind", draft.kind, true);      // 触发基础面板的步长/上限联动
    xbrSetWidget(node, "preset_mode", draft.mode, true);      // 触发预设句框显隐
    // 设定词：写进节点 widget（原样）+ 按「模式|语言」存档 → 换模式 / 换语言都不丢
    try {
      if (defaultPresetOf(draft.mode, draft.lang)) {
        node.__ippSetPreset?.(draft.presetText);
        node.__ippWritePreset?.(draft.mode, draft.lang, draft.presetText);
      }
    } catch (_) {}
    xbrSetWidget(node, "backend", draft.backend, true);
    xbrSetWidget(node, "preset", draft.preset, true);
    xbrSetWidget(node, "task_preset", draft.task_preset, true);
    xbrSaveJson(node, { llm: draft.settings.llm, auto_save: autoSaveRef.value !== false });
    try { node.__xbrProRefreshInfo?.(); } catch (_) {}
  };
  const immediate = () => { xbrSaveJson(node, { auto_save: autoSaveRef.value !== false }); };

  const readonly = (panelId === "help");
  const body = xbrDialog({
    label: meta.title,
    title: meta.title,
    subtitle: meta.subtitle,
    autoSaveRef: readonly ? null : autoSaveRef,
    onCommit: readonly ? null : commit,
    onImmediate: readonly ? null : immediate,
    onChange: readonly ? null : () => { try { node.__xbrProRefreshInfo?.(); } catch (_) {} },
  }).body;

  const ctx = {
    providers,
    rerender: () => { body.replaceChildren(); renderInto(); },
    touch: () => {},
  };
  function renderInto() {
    try { XBR_PANEL_RENDER[panelId](body, node, draft, ctx); }
    catch (e) { body.append(el("div", "color:#e55;font-size:12px;", "面板渲染失败：" + ((e && e.message) || e))); }
  }
  renderInto();
  if (panelId === "llm" && xbrModelLists === null) xbrLoadModelLists().then(() => ctx.rerender());
}

/* ── 按钮区 / 提示词框标题行 / 参数设定显示 / 锁定 ─────────── */
function xbrBuildButtonRow(node) {
  const grid = el("div", "display:grid;grid-template-columns:repeat(3,1fr);grid-auto-rows:30px;gap:6px;flex:0 0 auto;");
  for (const b of XBR_PANEL_BUTTONS) {
    const btn = el("button", "width:100%;height:30px;box-sizing:border-box;display:flex;align-items:center;justify-content:center;border-radius:6px;border:2px solid #5b9bd5;background:#3a3a3a;color:#eee;font-size:13px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:inherit;", b.label);
    btn.title = `打开「${b.title}」弹窗`;
    btn.dataset.xbrProBtn = b.id;
    btn.addEventListener("mousedown", (e) => e.stopPropagation());
    btn.addEventListener("mouseenter", () => { btn.style.background = "#4a4a4a"; });
    btn.addEventListener("mouseleave", () => { btn.style.background = "#3a3a3a"; });
    btn.addEventListener("click", (e) => { e.stopPropagation(); xbrOpenModal(node, b.id); });
    grid.append(btn);
  }
  return grid;
}

/** 显示窗取值：去掉括号注释与语言标签（[ZH]/[EN]），只留干净的值 */
function xbrClean(v) {
  let s = String(v == null ? "" : v);
  s = s.replace(/\s*[\[［][^\]］]*[\]］]\s*$/g, "");      // 尾部 [ZH] / [EN] 之类的语言标签
  s = s.replace(/（[^）]*）|\([^)]*\)/g, "");                 // 中英文括号注释
  return s.trim();
}

/** 参数设定显示（只读摘要 7 行；按用户要求：不显示括号与注释） */
function xbrInfoLines(node, promptText) {
  const llm = xbrParseLlm(xbrCurJson(node).llm);
  const useLlm = !!xbrWidgetVal(node, "use_llm");
  const backend = String(xbrWidgetVal(node, "backend") ?? "");
  const pMode = String(xbrWidgetVal(node, "preset_mode") ?? "");
  const pDef = defaultPresetOf(pMode, String(xbrWidgetVal(node, "output_lang") ?? "")) || "";
  const pCur = String(xbrWidgetVal(node, "three_view_text") ?? "");
  const line1 = `📊 空latent：${xbrClean(xbrWidgetVal(node, "latent_kind"))} ｜ ${xbrWidgetVal(node, "width")}x${xbrWidgetVal(node, "height")} ｜ 数量 ${xbrWidgetVal(node, "batch_size")}`;
  const line2 = `🎨 预设模式：${xbrClean(pMode)}`
    + (pDef ? ` ｜ 设定词：${(pCur.trim() && pCur !== pDef) ? "✏️ 自定义" : "默认"}` : " ｜ 设定词：无");
  const line3 = `🌐 输出语言：${xbrClean(xbrWidgetVal(node, "output_lang"))}`;
  const line4 = useLlm
    ? (backend === "在线 API"
      ? `🤖 LLM 反推：已启用 ｜ 在线API ｜ ${xbrClean((node.__xbrProApiInfo?.model) || XBR_API_DEFAULTS.model)}`
      : `🤖 LLM 反推：已启用 ｜ 本地模型 ｜ ${xbrClean(llm.model.model) || "未选择模型"}`)
    : "🤖 LLM 反推：未启用";
  const line5 = `✨ 增强预设：${xbrClean(xbrWidgetVal(node, "preset")) || "-"} ｜ 🎯 反推预设：${xbrClean(xbrWidgetVal(node, "task_preset")) || "-"}`;
  const line6 = `⚙️ 温度 ${llm.params.temperature} · top_k ${llm.params.top_k} · top_p ${llm.params.top_p} · max_tokens ${llm.params.max_tokens} ｜ ${xbrClean(llm.run.inference_mode)} ｜ 种子 ${llm.run.seed}`;
  const line7 = `📝 提示词：${(promptText || "").length} 字`;
  return [line1, line2, line3, line4, line5, line6, line7].join("\n");
}

/** 提示词框标题行（左标签 + 右复制）+ 参数设定显示；并挂上端口锁定/执行回写/摘要刷新 */
function xbrBuildPromptHeader(node, promptBox) {
  const head = el("div", "display:flex;align-items:center;gap:8px;flex:0 0 auto;");
  const lab = el("div", "font-size:12px;color:#bbb;", "📝 节点提示词（与面板预览框双向同步）");
  const copy = smallBtn("📋 复制", "margin-left:auto;", "复制提示词框内容", () => { copyText(promptBox.value || ""); });
  head.append(lab, copy);

  const infoBox = el("div", "flex:0 0 auto;height:150px;overflow:auto;background:#1c1c1e;border:1px solid #333;border-radius:6px;padding:6px 9px;font-size:11px;line-height:1.65;color:#b9c6d2;white-space:pre-wrap;box-sizing:border-box;font-family:ui-monospace,Consolas,monospace;");
  infoBox.dataset.captureWheel = "true";
  infoBox.title = "当前配置摘要（只读）";

  const refresh = () => { try { infoBox.textContent = xbrInfoLines(node, promptBox.value); } catch (_) {} };
  node.__xbrProRefreshInfo = refresh;
  node.__ippRefreshInfo = refresh;   // 基础面板改了设定词存档也会来刷这条摘要

  // 「📝 提示词」端口接线 → 锁定提示词框（二选一）
  const updateLock = () => {
    try {
      const inp = (node.inputs || []).find((i) => i.name === "text");
      const linked = !!inp && inp.link != null;
      promptBox.readOnly = linked;
      promptBox.style.background = linked ? "#141416" : "#1d1d1d";
      promptBox.style.color = linked ? "#8a8a8a" : "#ccc";
      promptBox.title = linked ? "已由「📝 提示词」端口控制，断开连线后恢复编辑" : "";
      lab.textContent = linked ? "📝 提示词已锁定（由「📝 提示词」端口控制）" : "📝 节点提示词（与面板预览框双向同步）";
      lab.style.color = linked ? "#d9a441" : "#bbb";
    } catch (_) {}
  };
  const prevConn = node.onConnectionsChange;
  node.onConnectionsChange = function (...a) {
    const r = prevConn?.apply(this, a);
    setTimeout(updateLock, 0);
    return r;
  };
  updateLock();

  // 生成后控制：后端算好的「下一次种子」回写进 manager_settings.llm.run.seed
  const prevExecuted = node.onExecuted;
  node.onExecuted = function (msg) {
    const r = prevExecuted?.apply(this, arguments);
    try {
      const ns = msg?.seed?.[0];
      if (ns !== undefined && ns !== null && ns !== "") {
        const cur = xbrCurJson(node);
        const llm = xbrParseLlm(cur.llm);
        if (Number(ns) !== Number(llm.run.seed)) {
          llm.run.seed = Math.max(0, Math.round(Number(ns)) || 0);
          xbrSaveJson(node, { llm });
        }
      }
      refresh();
    } catch (_) {}
    return r;
  };

  // 表面参数变化 → 摘要刷新（只 setDirtyCanvas，不动用 setSize）
  for (const nm of ["latent_kind", "output_lang", "preset_mode", "use_llm", "backend", "preset", "task_preset", "width", "height", "batch_size", "aspect_ratio"]) {
    const w = xbrWidget(node, nm);
    if (!w || w.__xbrProHooked) continue;
    w.__xbrProHooked = true;
    const orig = w.callback;
    w.callback = function (...a) {
      const r = orig?.apply(this, a);
      setTimeout(refresh, 0);
      return r;
    };
  }
  promptBox.addEventListener("input", () => { setTimeout(refresh, 0); });

  xbrApiGet().then((r) => { node.__xbrProApiInfo = xbrNormApi(r.settings); refresh(); }).catch(() => { refresh(); });
  setTimeout(refresh, 0);
  return [head, infoBox];
}

app.registerExtension({
  name: "XB.ImagePromptPresetPro",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_TYPE) return;
    const orig = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = orig?.apply(this, arguments);
      try { setupNode(this); } catch (e) { console.error("[XB-生图提示词预设]", e); }
      return r;
    };
  },
  // 低频兜底：工作流加载 / 复制节点后，节点提示词框与配置重新对齐
  setup() {
    // 启动时做一次词表自检（子类归属 / 重复 / 孤儿），只在控制台报，不影响使用
    try {
      const probs = verifyWordTable();
      const nSubs = ALL_CATS.reduce((n, c) => n + (catOf(c).subs || []).length, 0);
      const nWords = ALL_CATS.reduce((n, c) => n + (catOf(c).subs || []).reduce((m, s) => m + (s.keys || []).length, 0), 0);
      if (probs.length) console.warn("[XB-生图提示词预设] 词表校验不通过：\n" + probs.join("\n"));
      else console.log(`[XB-生图提示词预设] 词表校验通过：${ALL_CATS.length} 大类 / ${nSubs} 子类 / ${nWords} 条`);
    } catch (_) {}
    setInterval(() => {
      try {
        const nodes = (app.graph && (app.graph._nodes || app.graph.nodes)) || [];
        for (const n of nodes) {
          if (n && n.type === NODE_TYPE && typeof n.__ippSyncPromptBox === "function") n.__ippSyncPromptBox();
        }
      } catch (_) {}
    }, 1500);
  },
});
