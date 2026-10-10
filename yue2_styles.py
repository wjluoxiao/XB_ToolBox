"""YuE2 风格库与配方（官方 6 段式 style 的单一数据源）

官方 style 规范（yuE2 Prompt Guide）：
    Language + Genre + Vocal Character + Tempo + Instruments + Musical Characteristics
官方示例：
    "English, warm female vocal, contemporary pop, 96 BPM, piano,
     rounded electric bass, restrained drums, clear diction"
    "Upbeat indie pop with warm female vocals, bright electric guitars, punchy drums, ...
     Catchy and energetic, with an uplifting summer atmosphere, a memorable chorus,
     and polished modern production."

与 MiniMax Music3 的三段式 caption 不同，YuE2 的 style 是「扁平标签串 + 一句音乐特征」：
    - 不写段落结构（结构在歌词标签与 ABC 谱面里）
    - 不写实现指令（官方明确禁止把 "plan a melody with chords" 之类塞进 style）
    - 调式/调号/拍号由谱面负责，style 只做与谱面一致的描述

本文件同时被后端节点与前端 JS 读取（配方表是前端联动的唯一数据源）。
"""

# ═══════════════════════════════════════════════════════════════════════
#  维度词表（label -> English term）
# ═══════════════════════════════════════════════════════════════════════

# ①② 演唱语言（官方 Guide 的第一段，必填）
LANGUAGE_HINTS = {
    "中文 / Chinese": "Chinese",
    "英文 / English": "English",
    "日文 / Japanese": "Japanese",
    "粤语 / Cantonese": "Cantonese",
    "韩文 / Korean": "Korean",
    "中英混合 / Chinese-English": "Chinese and English",
    "西班牙文 / Spanish": "Spanish",
    "法文 / French": "French",
    "纯音乐 / Instrumental": "Instrumental",
}

# ③ 人声编制（YuE2 原生 Vocal 只有一条单声部旋律线：对唱/合唱只能靠文本弱控制）
VOCAL_HINTS = {
    "女声独唱 / Female Lead": "warm female vocal",
    "男声独唱 / Male Lead": "expressive male vocal",
    "童声独唱 / Child Lead": "bright child vocal",
    "中性嗓音 / Androgynous Lead": "soft androgynous vocal",
    "男女对唱 / Duet": "male and female duet vocals trading lines",
    "双女声对唱 / Female Duet": "two female vocalists trading lines",
    "合唱 / Choir": "mixed choir backing",
    "伴唱垫底 / Backing Vocals": "lead vocal with lush backing harmonies",
    "无主唱 / No Vocals": "no vocals",
}

TIMBRE_HINTS = {
    "跟随风格 / Follow Style": "",
    "清亮 / Clear Bright": "clear bright tone",
    "温暖 / Warm": "warm timbre",
    "气声 / Breathy": "breathy airy delivery",
    "沙哑 / Husky": "slightly husky tone",
    "厚重 / Deep Rich": "deep rich tone",
    "空灵 / Ethereal Airy": "ethereal floating tone",
    "颗粒感 / Raspy": "raspy textured tone",
    "柔滑 / Smooth": "smooth polished tone",
    "清冷 / Cool Metallic": "cool metallic tone",
}

TECHNIQUE_HINTS = {
    "跟随风格 / Follow Style": "",
    "流行通俗 / Pop Vocal": "natural pop phrasing",
    "咬字清晰 / Clear Diction": "clear diction",
    "慵懒后拍 / Behind-the-beat": "lazy behind-the-beat phrasing",
    "气声耳语 / Hushed Half-whispered": "hushed half-whispered delivery",
    "美声 / Bel Canto": "classical bel canto technique",
    "假声 / Falsetto": "airy falsetto",
    "说唱 / Rap Flow": "rhythmic rap flow",
    "民谣叙事 / Folk Storytelling": "plainspoken folk storytelling",
    "高亢爆发 / Belted High Notes": "powerful belted high notes",
    "戏曲腔 / Operatic Folk Ornament": "ornamented folk-opera delivery",
}

VOCAL_FX_HINTS = {
    "跟随风格 / Follow Style": "",
    "无处理 / Dry (No FX)": "dry upfront vocal",
    "暖混响 / Warm Reverb": "vocal drenched in warm reverb",
    "磁带延迟 / Tape Delay": "tape-delayed vocal echoes",
    "回声 / Echo": "slap-back echo on the voice",
    "自动修音 / Auto-Tune": "subtle Auto-Tune sheen on the voice",
    "双轨加厚 / Doubled Voice": "double-tracked thickening on the lead",
}

# ④ 速度（官方示例写法："96 BPM"；档位用于没有精确 BPM 时）
BPM_HINTS = {
    "不指定 / Unspecified": "",
    "慢 60-75 / Slow 60-75 BPM": "slow tempo around 68 BPM",
    "中慢 76-95 / Mid-Slow 76-95 BPM": "mid-slow tempo around 86 BPM",
    "中速 96-108 / Mid 96-108 BPM": "mid tempo around 100 BPM",
    "中快 109-125 / Mid-Fast 109-125 BPM": "mid-fast tempo around 116 BPM",
    "快 126-145 / Fast 126-145 BPM": "fast tempo around 132 BPM",
    "很快 146+ / Very Fast 146+ BPM": "driving tempo above 150 BPM",
}

MOOD_HINTS = {
    "不指定 / Unspecified": "",
    "温暖治愈 / Warm Healing": "warm and comforting",
    "浪漫甜蜜 / Romantic Sweet": "romantic and sweet",
    "忧郁感伤 / Melancholic": "melancholic and wistful",
    "燃爆热血 / Energetic Anthem": "soaring and anthemic",
    "神秘暗黑 / Dark Mysterious": "dark and mysterious",
    "明亮清爽 / Bright Fresh": "bright and refreshing",
    "复古怀旧 / Retro Nostalgic": "retro and nostalgic",
    "空灵冥想 / Ethereal Meditative": "weightless and meditative",
    "慵懒放松 / Laid-back Chill": "laid-back and unhurried",
    "宏大史诗 / Epic Cinematic": "vast and cinematic",
    "调皮俏皮 / Playful Quirky": "playful and quirky",
    "坚定励志 / Determined Uplifting": "determined and uplifting",
    "孤独深夜 / Late-night Lonely": "lonely late-night atmosphere",
    "节日欢庆 / Festive Celebration": "festive and celebratory",
    "梦幻漂移 / Dreamy Float": "dreamy and drifting",
    "紧张悬疑 / Tense Suspense": "tense and suspenseful",
}

INSTRUMENT_HINTS = {
    "钢琴 / Piano": "piano",
    "电钢琴 / Electric Piano": "electric piano",
    "管风琴 / Organ": "Hammond organ",
    "合成器 / Synthesizer": "warm analog synthesizers",
    "弦乐组 / Strings": "string section",
    "小提琴 / Violin": "violin",
    "大提琴 / Cello": "cello",
    "竖琴 / Harp": "harp",
    "原声吉他 / Acoustic Guitar": "acoustic guitar",
    "电吉他 / Electric Guitar": "electric guitar",
    "失真吉他 / Distorted Guitar": "distorted electric guitar",
    "贝斯 / Bass": "rounded electric bass",
    "低音提琴 / Upright Bass": "upright bass",
    "爵士鼓 / Drum Kit": "restrained drums",
    "打击乐 / Percussion": "hand percussion",
    "电子鼓机 / Drum Machine": "punchy drum machine",
    "808 低频 / 808 Bass": "deep 808 bass",
    "萨克斯 / Saxophone": "tenor saxophone",
    "小号 / Trumpet": "muted trumpet",
    "铜管组 / Brass Section": "brass section",
    "长笛 / Flute": "flute",
    "口琴 / Harmonica": "harmonica",
    "古筝 / Guzheng": "guzheng",
    "琵琶 / Pipa": "pipa",
    "二胡 / Erhu": "erhu",
    "笛子 / Dizi Flute": "Chinese bamboo flute",
    "中国鼓 / Chinese Drums": "Chinese festival drums",
    "战鼓 / War Drums": "thunderous war drums",
    "三味线 / Shamisen": "shamisen",
    "尺八 / Shakuhachi": "shakuhachi",
    "马林巴 / Marimba": "marimba",
    "钟琴 / Glockenspiel": "glockenspiel",
    "磁带噪底 / Tape Noise": "tape hiss and vinyl crackle",
    "自然氛围 / Nature Ambience": "birdsong and soft wind ambience",
}

DENSITY_HINTS = {
    "跟随风格 / Follow Style": "",
    "极简留白 / Minimal": "sparse arrangement with plenty of space",
    "标准 / Standard": "",
    "饱满丰富 / Full": "full, layered arrangement",
    "密集推进 / Dense Driving": "dense driving arrangement",
}

TEXTURE_HINTS = {
    "跟随风格 / Follow Style": "",
    "干净数字 / Clean Digital": "clean modern production",
    "温暖模拟 / Warm Analog": "warm analog production",
    "磁带质感 / Tape Lo-fi": "dusty tape-lo-fi texture",
    "黑胶质感 / Vinyl Warmth": "vinyl crackle and low-passed warmth",
    "现场空间 / Live Room": "natural live-room ambience",
    "宽广开阔 / Wide Spacious": "wide stereo field and long reverb tails",
    "贴身亲密 / Intimate Close": "close-miked, intimate production",
}

# ═══════════════════════════════════════════════════════════════════════
#  风格库（曲风条目自带默认乐器/质感/特征句，供「跟随风格」回填）
#    terms        官方 Genre 段
#    primary      默认主奏乐器
#    secondary    默认辅助乐器
#    texture      默认制作质感
#    character    默认音乐特征句（官方第二句）
# ═══════════════════════════════════════════════════════════════════════

GENRES = {
    "华语流行 / Mandopop": {
        "terms": "contemporary Mandopop ballad",
        "primary": "钢琴 / Piano", "secondary": "弦乐组 / Strings",
        "texture": "干净数字 / Clean Digital",
        "character": "Lyrical, memorable melody with an emotional chorus that opens up on the second half.",
    },
    "华语抒情摇滚 / Mandopop Rock Ballad": {
        "terms": "Mandarin rock ballad",
        "primary": "失真吉他 / Distorted Guitar", "secondary": "弦乐组 / Strings",
        "texture": "温暖模拟 / Warm Analog",
        "character": "Restrained verses building into a soaring, cathartic chorus.",
    },
    "粤语流行 / Cantopop": {
        "terms": "Cantopop",
        "primary": "电钢琴 / Electric Piano", "secondary": "电吉他 / Electric Guitar",
        "texture": "干净数字 / Clean Digital",
        "character": "Nostalgic city-pop sheen with a singable hook and tight vocal phrasing.",
    },
    "城市流行 / City Pop": {
        "terms": "city pop",
        "primary": "电钢琴 / Electric Piano", "secondary": "贝斯 / Bass",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Sleek 1980s city-night groove with glossy chords and a buoyant chorus.",
    },
    "英文流行 / English Pop": {
        "terms": "contemporary pop",
        "primary": "钢琴 / Piano", "secondary": "电子鼓机 / Drum Machine",
        "texture": "干净数字 / Clean Digital",
        "character": "Catchy and energetic with a memorable chorus and polished modern production.",
    },
    "民谣 / Folk": {
        "terms": "acoustic folk",
        "primary": "原声吉他 / Acoustic Guitar", "secondary": "口琴 / Harmonica",
        "texture": "现场空间 / Live Room",
        "character": "Plainspoken storytelling over fingerpicked guitar, intimate and unhurried.",
    },
    "国风民乐 / Chinese Folk New Age": {
        "terms": "folk new age with guzheng and erhu",
        "primary": "古筝 / Guzheng", "secondary": "二胡 / Erhu",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Modal pentatonic melody with modern orchestration and an expansive climax.",
    },
    "中国戏曲风 / Chinese Opera Fusion": {
        "terms": "Chinese opera fusion pop",
        "primary": "琵琶 / Pipa", "secondary": "中国鼓 / Chinese Drums",
        "texture": "现场空间 / Live Room",
        "character": "Operatic ornaments riding a modern pop groove, dramatic and theatrical.",
    },
    "爵士 / Jazz": {
        "terms": "intimate jazz",
        "primary": "钢琴 / Piano", "secondary": "萨克斯 / Saxophone",
        "texture": "温暖模拟 / Warm Analog",
        "character": "Relaxed swing with conversational phrasing and extended harmony.",
    },
    "摇摆大乐队 / Swing Big Band": {
        "terms": "swing big band",
        "primary": "小号 / Trumpet", "secondary": "爵士鼓 / Drum Kit",
        "texture": "温暖模拟 / Warm Analog",
        "character": "Brassy call-and-response riffs driving a joyful dance-floor swing.",
    },
    "波萨诺瓦 / Bossa Nova": {
        "terms": "bossa nova",
        "primary": "原声吉他 / Acoustic Guitar", "secondary": "低音提琴 / Upright Bass",
        "texture": "贴身亲密 / Intimate Close",
        "character": "Gentle syncopated sway, breezy and effortlessly elegant.",
    },
    "灵魂乐 / Soul": {
        "terms": "classic soul",
        "primary": "管风琴 / Organ", "secondary": "弦乐组 / Strings",
        "texture": "温暖模拟 / Warm Analog",
        "character": "Slow-burning emotional build with gospel-tinged runs and a full-throated chorus.",
    },
    "节奏布鲁斯 / R&B": {
        "terms": "contemporary R&B",
        "primary": "电钢琴 / Electric Piano", "secondary": "808 低频 / 808 Bass",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Smooth late-night groove with airy harmonies and silky runs.",
    },
    "放克 / Funk": {
        "terms": "funk",
        "primary": "电吉他 / Electric Guitar", "secondary": "贝斯 / Bass",
        "texture": "温暖模拟 / Warm Analog",
        "character": "Tight syncopated groove with rhythmic call-and-response vocal hooks.",
    },
    "摇滚 / Rock": {
        "terms": "guitar rock",
        "primary": "失真吉他 / Distorted Guitar", "secondary": "爵士鼓 / Drum Kit",
        "texture": "温暖模拟 / Warm Analog",
        "character": "Driving riffs and a shout-along chorus with raw live energy.",
    },
    "朋克 / Punk": {
        "terms": "pop punk",
        "primary": "失真吉他 / Distorted Guitar", "secondary": "电子鼓机 / Drum Machine",
        "texture": "干净数字 / Clean Digital",
        "character": "Fast, blunt and hooky, with gang-shouted backing on the chorus.",
    },
    "金属 / Metal": {
        "terms": "melodic metal",
        "primary": "失真吉他 / Distorted Guitar", "secondary": "爵士鼓 / Drum Kit",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Heavy palm-muted riffs under a clear melodic vocal line.",
    },
    "电子舞曲 / EDM": {
        "terms": "melodic EDM",
        "primary": "合成器 / Synthesizer", "secondary": "电子鼓机 / Drum Machine",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Build-and-drop structure with a bright topline hook and festival-sized chorus.",
    },
    "合成器浪潮 / Synthwave": {
        "terms": "synthwave",
        "primary": "合成器 / Synthesizer", "secondary": "电子鼓机 / Drum Machine",
        "texture": "磁带质感 / Tape Lo-fi",
        "character": "Neon-lit retro-futurist drive with gated reverb drums and shimmering arpeggios.",
    },
    "低保真嘻哈 / Lo-fi Hip-Hop": {
        "terms": "lo-fi hip-hop",
        "primary": "电钢琴 / Electric Piano", "secondary": "低音提琴 / Upright Bass",
        "texture": "黑胶质感 / Vinyl Warmth",
        "character": "Dusty, unhurried and hazy, with soft drums and warm Rhodes chords.",
    },
    "嘻哈说唱 / Hip-Hop": {
        "terms": "hip-hop",
        "primary": "808 低频 / 808 Bass", "secondary": "合成器 / Synthesizer",
        "texture": "干净数字 / Clean Digital",
        "character": "Sparse dark loop under a confident, rhythmic vocal delivery.",
    },
    "国风嘻哈 / Guofeng Trap": {
        "terms": "Chinese folk trap",
        "primary": "古筝 / Guzheng", "secondary": "808 低频 / 808 Bass",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Pentatonic plucks over rolling 808s, ancient-meets-modern tension.",
    },
    "日系动漫 / Anime J-Pop": {
        "terms": "anime J-pop",
        "primary": "电吉他 / Electric Guitar", "secondary": "合成器 / Synthesizer",
        "texture": "干净数字 / Clean Digital",
        "character": "Fast, bright and dramatic, with a key-change lift into the final chorus.",
    },
    "室内乐 / Chamber": {
        "terms": "chamber pop",
        "primary": "弦乐组 / Strings", "secondary": "竖琴 / Harp",
        "texture": "现场空间 / Live Room",
        "character": "Delicate counterpoint and close harmony, restrained and detailed.",
    },
    "影视管弦 / Cinematic Orchestral": {
        "terms": "cinematic orchestral",
        "primary": "弦乐组 / Strings", "secondary": "中国鼓 / Chinese Drums",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Long crescendo from fragile intimacy to a full-ensemble climax.",
    },
    "治愈器乐 / Healing Instrumental": {
        "terms": "gentle instrumental new age",
        "primary": "钢琴 / Piano", "secondary": "大提琴 / Cello",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Slow, spacious and unhurried, with motifs that breathe and resolve softly.",
    },
    "儿童童谣 / Children's Song": {
        "terms": "children's sing-along",
        "primary": "钟琴 / Glockenspiel", "secondary": "原声吉他 / Acoustic Guitar",
        "texture": "干净数字 / Clean Digital",
        "character": "Simple repeated hook in a narrow range, warm and easy to sing along.",
    },
    "节日欢庆 / Festive Celebration": {
        "terms": "festive celebration song",
        "primary": "中国鼓 / Chinese Drums", "secondary": "弦乐组 / Strings",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Bright, percussive and jubilant, with shouted hooks and a big finish.",
    },
    # ── 背景音乐（视频配乐向，建议配合「纯音乐」使用）──
    "热血战斗 / Battle Action": {
        "terms": "epic battle action score",
        "primary": "铜管组 / Brass Section", "secondary": "战鼓 / War Drums",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "Thunderous war drums drive a rising brass motif toward a victorious climax.",
    },
    "安静田园 / Peaceful Pastoral": {
        "terms": "peaceful pastoral folk",
        "primary": "原声吉他 / Acoustic Guitar", "secondary": "自然氛围 / Nature Ambience",
        "texture": "现场空间 / Live Room",
        "character": "Gentle acoustic picking over birdsong and soft wind, unhurried and sunlit.",
    },
    "悬疑紧张 / Suspense Tension": {
        "terms": "suspense tension underscore",
        "primary": "合成器 / Synthesizer", "secondary": "大提琴 / Cello",
        "texture": "宽广开阔 / Wide Spacious",
        "character": "A ticking pulse and low sustained strings tighten gradually, ending unresolved.",
    },
    "悲伤回忆 / Tragic Memory": {
        "terms": "melancholic memory cue",
        "primary": "钢琴 / Piano", "secondary": "大提琴 / Cello",
        "texture": "贴身亲密 / Intimate Close",
        "character": "Sparse piano over a warm cello line, slow and reflective, with long pauses.",
    },
}


def genre_options() -> list:
    """风格下拉列表：按 GENRES 定义顺序。"""
    return list(GENRES.keys())


# ═══════════════════════════════════════════════════════════════════════
#  ✨ 一键配方（切换即回填全部维度，仍可手动微调）
#  键必须与节点 INPUT_TYPES 的维度名完全一致；「跟随风格」项由节点按风格库回填。
# ═══════════════════════════════════════════════════════════════════════

FOLLOW = "跟随风格 / Follow Style"
CUSTOM = "自定义 / Custom"

RECIPES = {
    CUSTOM: {},
    "🎤 华语流行金曲 / Mandopop Ballad": {
        "演唱语言": "中文 / Chinese",
        "音乐风格": "华语流行 / Mandopop",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "女声独唱 / Female Lead",
        "人声音色": "温暖 / Warm",
        "人声唱法": "流行通俗 / Pop Vocal",
        "人声效果": "暖混响 / Warm Reverb",
        "速度": "中慢 76-95 / Mid-Slow 76-95 BPM",
        "BPM数值": 84,
        "情绪氛围": "忧郁感伤 / Melancholic",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "标准 / Standard",
        "制作质感": FOLLOW,
        "音乐特征": "",
    },
    "🌃 城市流行 / City Pop Night": {
        "演唱语言": "日文 / Japanese",
        "音乐风格": "城市流行 / City Pop",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "女声独唱 / Female Lead",
        "人声音色": "清亮 / Clear Bright",
        "人声唱法": "流行通俗 / Pop Vocal",
        "人声效果": "无处理 / Dry (No FX)",
        "速度": "中速 96-108 / Mid 96-108 BPM",
        "BPM数值": 104,
        "情绪氛围": "复古怀旧 / Retro Nostalgic",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "饱满丰富 / Full",
        "制作质感": FOLLOW,
        "音乐特征": "",
    },
    "🇬🇧 英文流行 / English Pop": {
        "演唱语言": "英文 / English",
        "音乐风格": "英文流行 / English Pop",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "女声独唱 / Female Lead",
        "人声音色": "清亮 / Clear Bright",
        "人声唱法": "咬字清晰 / Clear Diction",
        "人声效果": "跟随风格 / Follow Style",
        "速度": "中快 109-125 / Mid-Fast 109-125 BPM",
        "BPM数值": 118,
        "情绪氛围": "明亮清爽 / Bright Fresh",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "饱满丰富 / Full",
        "制作质感": FOLLOW,
        "音乐特征": "Catchy and energetic, with a memorable chorus and a hook that lands on the first listen.",
    },
    "🐉 国风民乐 / Chinese Folk New Age": {
        "演唱语言": "中文 / Chinese",
        "音乐风格": "国风民乐 / Chinese Folk New Age",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "女声独唱 / Female Lead",
        "人声音色": "空灵 / Ethereal Airy",
        "人声唱法": "戏曲腔 / Operatic Folk Ornament",
        "人声效果": "暖混响 / Warm Reverb",
        "速度": "中速 96-108 / Mid 96-108 BPM",
        "BPM数值": 92,
        "情绪氛围": "宏大史诗 / Epic Cinematic",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "饱满丰富 / Full",
        "制作质感": "宽广开阔 / Wide Spacious",
        "音乐特征": "Pentatonic melody rising from a quiet guzheng figure to a full orchestral climax.",
    },
    "🎬 影视抒情 / Cinematic Ballad": {
        "演唱语言": "中文 / Chinese",
        "音乐风格": "影视管弦 / Cinematic Orchestral",
        "风格融合": "华语流行 / Mandopop",
        "人声编制": "女声独唱 / Female Lead",
        "人声音色": "空灵 / Ethereal Airy",
        "人声唱法": "高亢爆发 / Belted High Notes",
        "人声效果": "暖混响 / Warm Reverb",
        "速度": "慢 60-75 / Slow 60-75 BPM",
        "BPM数值": 68,
        "情绪氛围": "宏大史诗 / Epic Cinematic",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "饱满丰富 / Full",
        "制作质感": "宽广开阔 / Wide Spacious",
        "音乐特征": "Long crescendo from fragile intimacy to a full-ensemble climax.",
    },
    "🎷 摇摆爵士 / Swing Big Band": {
        "演唱语言": "英文 / English",
        "音乐风格": "摇摆大乐队 / Swing Big Band",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "男声独唱 / Male Lead",
        "人声音色": "柔滑 / Smooth",
        "人声唱法": "流行通俗 / Pop Vocal",
        "人声效果": "无处理 / Dry (No FX)",
        "速度": "快 126-145 / Fast 126-145 BPM",
        "BPM数值": 138,
        "情绪氛围": "节日欢庆 / Festive Celebration",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "饱满丰富 / Full",
        "制作质感": "现场空间 / Live Room",
        "音乐特征": "",
    },
    "🙏 灵魂福音 / Gospel Soul": {
        "演唱语言": "英文 / English",
        "音乐风格": "灵魂乐 / Soul",
        "风格融合": "节奏布鲁斯 / R&B",
        "人声编制": "女声独唱 / Female Lead",
        "人声音色": "厚重 / Deep Rich",
        "人声唱法": "高亢爆发 / Belted High Notes",
        "人声效果": "暖混响 / Warm Reverb",
        "速度": "慢 60-75 / Slow 60-75 BPM",
        "BPM数值": 72,
        "情绪氛围": "坚定励志 / Determined Uplifting",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "饱满丰富 / Full",
        "制作质感": "温暖模拟 / Warm Analog",
        "音乐特征": "Slow-burning build with gospel runs and a full-throated final chorus.",
    },
    "⚡ 摇滚力量 / Rock Power Ballad": {
        "演唱语言": "中文 / Chinese",
        "音乐风格": "华语抒情摇滚 / Mandopop Rock Ballad",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "男声独唱 / Male Lead",
        "人声音色": "颗粒感 / Raspy",
        "人声唱法": "高亢爆发 / Belted High Notes",
        "人声效果": "暖混响 / Warm Reverb",
        "速度": "中速 96-108 / Mid 96-108 BPM",
        "BPM数值": 96,
        "情绪氛围": "燃爆热血 / Energetic Anthem",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "饱满丰富 / Full",
        "制作质感": "温暖模拟 / Warm Analog",
        "音乐特征": "",
    },
    "🌙 深夜低保真 / Late-night Lo-fi": {
        "演唱语言": "英文 / English",
        "音乐风格": "低保真嘻哈 / Lo-fi Hip-Hop",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "中性嗓音 / Androgynous Lead",
        "人声音色": "气声 / Breathy",
        "人声唱法": "慵懒后拍 / Behind-the-beat",
        "人声效果": "磁带延迟 / Tape Delay",
        "速度": "中慢 76-95 / Mid-Slow 76-95 BPM",
        "BPM数值": 82,
        "情绪氛围": "孤独深夜 / Late-night Lonely",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "极简留白 / Minimal",
        "制作质感": FOLLOW,
        "音乐特征": "",
    },
    "🎹 治愈器乐 / Healing Instrumental": {
        "演唱语言": "纯音乐 / Instrumental",
        "音乐风格": "治愈器乐 / Healing Instrumental",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "无主唱 / No Vocals",
        "人声音色": FOLLOW,
        "人声唱法": FOLLOW,
        "人声效果": FOLLOW,
        "速度": "慢 60-75 / Slow 60-75 BPM",
        "BPM数值": 66,
        "情绪氛围": "空灵冥想 / Ethereal Meditative",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "极简留白 / Minimal",
        "制作质感": "宽广开阔 / Wide Spacious",
        "音乐特征": "Calm, spacious piano lines over sustained strings, resolving softly.",
    },
    "🐲 国风嘻哈 / Guofeng Trap": {
        "演唱语言": "中文 / Chinese",
        "音乐风格": "国风嘻哈 / Guofeng Trap",
        "风格融合": "嘻哈说唱 / Hip-Hop",
        "人声编制": "男声独唱 / Male Lead",
        "人声音色": "清冷 / Cool Metallic",
        "人声唱法": "说唱 / Rap Flow",
        "人声效果": "自动修音 / Auto-Tune",
        "速度": "中速 96-108 / Mid 96-108 BPM",
        "BPM数值": 100,
        "情绪氛围": "神秘暗黑 / Dark Mysterious",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "密集推进 / Dense Driving",
        "制作质感": "宽广开阔 / Wide Spacious",
        "音乐特征": "",
    },
    "👫 男女对唱情歌 / Duet Love Ballad": {
        "演唱语言": "中文 / Chinese",
        "音乐风格": "华语流行 / Mandopop",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "男女对唱 / Duet",
        "人声音色": "温暖 / Warm",
        "人声唱法": "流行通俗 / Pop Vocal",
        "人声效果": "暖混响 / Warm Reverb",
        "速度": "慢 60-75 / Slow 60-75 BPM",
        "BPM数值": 70,
        "情绪氛围": "浪漫甜蜜 / Romantic Sweet",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "标准 / Standard",
        "制作质感": "干净数字 / Clean Digital",
        "音乐特征": "Two voices trade lines in the verses and converge in harmony on the chorus.",
    },
    # ── 背景音乐配方（一键纯音乐，直接可当视频配乐）──
    "🗡️ 热血战斗 / Battle Action": {
        "演唱语言": "纯音乐 / Instrumental",
        "音乐风格": "热血战斗 / Battle Action",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "无主唱 / No Vocals",
        "人声音色": FOLLOW,
        "人声唱法": FOLLOW,
        "人声效果": FOLLOW,
        "速度": "快 126-145 / Fast 126-145 BPM",
        "BPM数值": 132,
        "情绪氛围": "燃爆热血 / Energetic Anthem",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "饱满丰富 / Full",
        "制作质感": "宽广开阔 / Wide Spacious",
        "音乐特征": "",
    },
    "🌾 安静田园 / Peaceful Pastoral": {
        "演唱语言": "纯音乐 / Instrumental",
        "音乐风格": "安静田园 / Peaceful Pastoral",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "无主唱 / No Vocals",
        "人声音色": FOLLOW,
        "人声唱法": FOLLOW,
        "人声效果": FOLLOW,
        "速度": "慢 60-75 / Slow 60-75 BPM",
        "BPM数值": 68,
        "情绪氛围": "温暖治愈 / Warm Healing",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "极简留白 / Minimal",
        "制作质感": "现场空间 / Live Room",
        "音乐特征": "",
    },
    "🕵️ 悬疑紧张 / Suspense Tension": {
        "演唱语言": "纯音乐 / Instrumental",
        "音乐风格": "悬疑紧张 / Suspense Tension",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "无主唱 / No Vocals",
        "人声音色": FOLLOW,
        "人声唱法": FOLLOW,
        "人声效果": FOLLOW,
        "速度": "中慢 76-95 / Mid-Slow 76-95 BPM",
        "BPM数值": 88,
        "情绪氛围": "紧张悬疑 / Tense Suspense",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "极简留白 / Minimal",
        "制作质感": "宽广开阔 / Wide Spacious",
        "音乐特征": "",
    },
    "💧 悲伤回忆 / Tragic Memory": {
        "演唱语言": "纯音乐 / Instrumental",
        "音乐风格": "悲伤回忆 / Tragic Memory",
        "风格融合": "不指定 / Unspecified",
        "人声编制": "无主唱 / No Vocals",
        "人声音色": FOLLOW,
        "人声唱法": FOLLOW,
        "人声效果": FOLLOW,
        "速度": "慢 60-75 / Slow 60-75 BPM",
        "BPM数值": 64,
        "情绪氛围": "忧郁感伤 / Melancholic",
        "主奏乐器": FOLLOW, "辅助乐器": FOLLOW,
        "编曲密度": "标准 / Standard",
        "制作质感": "贴身亲密 / Intimate Close",
        "音乐特征": "",
    },
}
