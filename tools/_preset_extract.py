# === JLZ_MiniMaxPreset ===
class JLZ_MiniMaxPreset:
    """MiniMax H3 提示词预设 — T2VA/I2VA/FL2VA/L2VA + 动态参数注入"""

    _STYLES = [
        "不指定 / Unspecified",
        # 🎬 电影感
        "电影感 / Cinematic", "实拍 / Live-action",
        "复古胶片 / Vintage film", "黑白电影 / Black & White",
        "纪录片 / Documentary",
        # 📷 商业摄影
        "极简广告 / Minimalist commercial",
        "微距摄影 / Macro photography",
        "航拍 / Aerial drone",
        # 🎨 动画
        "二维动画 / 2D-animated", "三维CG / 3D CG",
        "日系二次元 / Anime", "美式漫画 / American Comic",
        "皮克斯3D / Pixar-style 3D", "定格动画 / Stop-motion",
        "手绘发光 / Hand-drawn glow", "像素艺术 / Pixel art",
        # 🚀 科幻前卫
        "赛博朋克 / Cyberpunk", "蒸汽朋克 / Steampunk",
        "故障艺术 / Glitch art",
        # 🧶 特殊材质
        "羊毛毡 / Wool felt", "折纸 / Origami",
        # 🖌️ 美术
        "水彩 / Watercolor", "粘土动画 / Claymation",
        "水墨 / Ink wash", "油画 / Oil painting",
        "纸艺拼贴 / Paper collage", "剪纸 / Paper cutout",
        "铅笔素描 / Pencil sketch", "浮世绘 / Ukiyo-e",
        # 🏮 中国风
        "敦煌壁画 / Dunhuang Murals",
        "青花瓷 / Blue-white Porcelain",
        "工笔画 / Gongbi Painting",
        "皮影戏 / Shadow Puppetry",
        "中国风插画 / Chinese Illustration",
        "年画 / New Year Painting",
        # 🧵 手工布艺
        "布艺 / Fabric Art",
        "蜡笔画 / Crayon drawing",
        "哥特萝莉 / Gothic Lolita",
    ]

    _STYLE_HINTS = {
        "电影感 / Cinematic": "cinematic lighting with shallow depth of field, film grain, and professional color grading",
        "实拍 / Live-action": "photorealistic live-action footage with natural lighting and authentic set design",
        "复古胶片 / Vintage film": "vintage film stock with warm color grading, subtle grain, and nostalgic atmosphere",
        "黑白电影 / Black & White": "high-contrast black-and-white cinematography with dramatic shadows",
        "纪录片 / Documentary": "observational documentary style with natural handheld camera work and candid framing",
        "极简广告 / Minimalist commercial": "clean minimalist product cinematography with smooth dolly moves, soft even lighting, and uncluttered compositions",
        "微距摄影 / Macro photography": "extreme close-up macro lens with razor-thin depth of field, revealing fine textures and details",
        "航拍 / Aerial drone": "sweeping aerial drone shots with wide vistas, slow majestic reveals, and expansive landscape views",
        "二维动画 / 2D-animated": "traditional 2D hand-drawn animation with expressive line art and fluid character motion",
        "三维CG / 3D CG": "high-quality 3D rendering with realistic materials, global illumination, and smooth animation",
        "日系二次元 / Anime": "Japanese anime cel-shading with vibrant saturated colors, clean linework, and expressive character designs",
        "美式漫画 / American Comic": "American comic book style with bold black ink outlines, halftone dot shading, and dynamic compositions",
        "皮克斯3D / Pixar-style 3D": "Pixar-quality 3D with smooth curved surfaces, rich vibrant colors, expressive character animation, and polished lighting",
        "定格动画 / Stop-motion": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a stop-motion animation. Characters are handcrafted puppets with visible material textures, moving with tactile frame-by-frame stutter. Environments are miniature physical sets with real fabrics, painted backdrops, and practical lighting. EVERYTHING is a physical model under a camera.",
        "手绘发光 / Hand-drawn glow": "GLOBAL MATERIAL OVERRIDE — the entire visual world is rough hand-drawn line art on dark paper. Characters and environments are sketched with glowing neon-colored outlines that flicker and pulse organically. Light trails follow movement like afterimages. The world itself is a living drawing, every line redrawn in real-time.",
        "像素艺术 / Pixel art": "GLOBAL MATERIAL OVERRIDE — the entire visual world is built from visible pixel blocks. Characters, environments, water, fire, smoke, sky — EVERYTHING is composed of crisp square pixels with a limited retro color palette. Motion is frame-by-frame at low FPS with deliberate pixel-level changes. Particles are individual pixel dots. The pixel grid IS the universe.",
        "赛博朋克 / Cyberpunk": "high-contrast neon-lit cyberpunk cityscape with rain-slicked streets, holographic displays, and chrome cybernetics",
        "蒸汽朋克 / Steampunk": "intricate brass machinery and Victorian-era steam technology with copper pipes, gears, and sepia tones",
        "故障艺术 / Glitch art": "digital glitch distortion with RGB color channel split, scan lines, data corruption artifacts, and VHS noise",
        "羊毛毡 / Wool felt": "GLOBAL MATERIAL OVERRIDE — the entire visual world is handcrafted from fuzzy wool felt. Characters have soft felt textile bodies with visible fiber textures and stitched seams. Wind ripples through felt grass, felt water flows with fiber movement, felt clouds drift across a felt sky. Environments are sewn felt dioramas. DO NOT place felt toys in a real scene — everything IS felt.",
        "折纸 / Origami": "GLOBAL MATERIAL OVERRIDE — the entire universe is constructed from folded paper. Characters are origami figures with sharp clean creases and geometric folded anatomy. Paper birds flap creased wings, paper water ripples in folded layers, paper fire crackles as curling sheets. The world itself is paper — all matter is folded, creased, and crisp.",
        "水彩 / Watercolor": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D watercolor painting on paper. Characters are NOT real people — their bodies are translucent color washes, their faces are soft pigment blooms on wet paper, their edges dissolve into the paper grain. Hair is bleeding pigment streaks, skin is the white of paper with tinted wash. Rain falls as pigment droplets, light diffuses through layered washes. NO realistic skin, NO 3D — only wet pigment on paper.",
        "粘土动画 / Claymation": "GLOBAL MATERIAL OVERRIDE — the entire visual world is hand-sculpted clay. Characters are NOT real people — their bodies are clay with rounded tactile surfaces, visible fingerprints, and tool marks. Hair is sculpted clay strands, skin is smooth plasticine, clothing is pressed clay sheets. Clay water splashes in sculpted droplets, clay smoke rolls in malleable puffs. NO real skin — only clay shaped by human hands.",
        "水墨 / Ink wash": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D ink wash painting on xuan rice paper. Characters are NOT real people — their bodies are fluid black brushstrokes, their faces are ink lines on paper, their clothing is graded ink washes. Hair flows as sweeping brushstrokes, skin tone is the white of the paper itself with ink shading. Water splashes as flying ink drops, wind leaves brushstroke trails, mist is spreading ink on wet paper. NO realistic skin, NO realistic fabric, NO 3D — only ink and paper.",
        "油画 / Oil painting": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D oil painting on canvas. Characters are NOT real people — their bodies are thick oil paint applied with palette knives, their faces are built from layered brushstrokes, their clothing is impasto pigment. Hair is swept paint, skin is blended oil color on canvas, eyes are precise brush dabs. Water ripples in heavy oil strokes, fire is palette-knife texture, clouds are smeared white paint. NO realistic skin, NO real fabric, NO 3D — only oil paint on canvas.",
        "纸艺拼贴 / Paper collage": "GLOBAL MATERIAL OVERRIDE — the entire visual world is layered torn paper. Characters are NOT real people — their bodies are cut from textured paper with torn edges, their faces are printed paper fragments, their clothing is different paper types (newsprint, craft, tissue). Paper birds flap torn-edge wings, paper water ripples in layered sheets. NO real skin — only paper.",
        "剪纸 / Paper cutout": "GLOBAL MATERIAL OVERRIDE — the entire visual world is Chinese paper cutout art. Characters are NOT real people — their bodies are intricate red paper silhouettes cut with symmetrical patterns, moving with articulated paper joints. Shadows cast dramatic shapes through the paper lattice. NO real skin — only cut paper.",
        "铅笔素描 / Pencil sketch": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D graphite pencil drawing on textured paper. Characters are NOT real people — their bodies are graphite lines, hatching, and cross-hatching on paper. Faces are sketched pencil marks, hair is sweeping graphite strokes, skin tone is the white of paper with varying pencil pressure. Motion is lines erasing and redrawing. Eraser marks leave ghost trails. NO real skin, NO 3D — only pencil on paper.",
        "浮世绘 / Ukiyo-e": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D Japanese ukiyo-e woodblock print. Characters are NOT real people — their bodies are flat color areas with bold black outlines printed on washi paper. Faces are printed woodblock features, hair is carved-line black ink, clothing is flat color blocks. NO real skin, NO 3D — only woodblock ink on paper.",
        "敦煌壁画 / Dunhuang Murals": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D animated Dunhuang cave mural on a fresco wall. Characters are NOT real people — their bodies are mineral pigment paintings (ochre, turquoise, lapis lazuli) with weathered fresco cracks. Flying deities trail faded pigment ribbons. NO real skin, NO 3D — only ancient mural pigment on plaster.",
        "青花瓷 / Blue-white Porcelain": "GLOBAL MATERIAL OVERRIDE — the entire universe is living 3D blue-and-white porcelain. Characters are NOT real people — their bodies are white-glazed porcelain with cobalt-blue hand-painted patterns flowing across their skin as features and clothing. Porcelain birds take flight with clicking ceramic wings, porcelain water flows as liquid glaze, porcelain trees bloom with cobalt flowers. NO real skin — only glazed ceramic.",
        "工笔画 / Gongbi Painting": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D gongbi painting on flat silk. Characters are NOT real people — their bodies are ultra-fine brush outlines filled with flat mineral color washes on silk. Every hair and petal is individually painted. Silk fibers visible beneath the pigment. NO real skin, NO 3D — only brush and silk.",
        "皮影戏 / Shadow Puppetry": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D shadow puppet theater on a translucent screen. Characters are NOT real people — their bodies are intricately carved leather silhouettes with articulated joints, illuminated by warm amber backlighting. NO real skin, NO 3D — only leather shadows on a screen.",
        "中国风插画 / Chinese Illustration": "modern Chinese illustration blending traditional ink aesthetics with contemporary digital art, featuring elegant flowing lines, poetic composition, and dreamlike color harmony",
        "年画 / New Year Painting": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D vibrant Chinese folk New Year woodblock print. Characters are NOT real people — their bodies are bold primary color blocks with thick black outlines on flat printed paper. Door gods step out of frames and walk, carp leap as printed patterns. NO real skin, NO 3D — only folk print on paper.",
        "布艺 / Fabric Art": "GLOBAL MATERIAL OVERRIDE — the entire visual world is constructed from sewn fabric and textiles. Characters are NOT real people — they are cloth dolls with stitched seams, button eyes, embroidered facial features, yarn hair, and patchwork clothing. Environments are quilted fabric landscapes: grass is green felt, water is flowing blue silk, clouds are tufted cotton, trees are embroidered tapestry. Every surface shows visible thread, stitching, and fabric grain. NO realistic skin, NO real materials — only fabric and thread.",
        "蜡笔画 / Crayon drawing": "GLOBAL MATERIAL OVERRIDE — the entire visual world is a 2D wax crayon drawing on textured paper. Characters are NOT real people — their bodies are waxy crayon strokes on paper with the paper grain visible through the wax. Bright colors have the distinctive grainy, slightly uneven crayon texture. Lines are thick and waxy with visible stroke direction. Paper texture shows through all color areas. NO 3D depth, NO CG, NO realistic skin — only crayon on paper.",
        "哥特萝莉 / Gothic Lolita": "Gothic Lolita fashion and atmosphere — NOT a material override but a costume and world style. Characters wear elaborate dark Victorian-inspired Lolita clothing: lace-trimmed black dresses, ruffled petticoats, corsets, platform boots, ornate headpieces with ribbons and roses. Architecture is moody Gothic with pointed arches, stained glass, wrought iron. Dramatic chiaroscuro lighting with deep shadows. Color palette: black, deep purple, burgundy, ivory, silver accents. Atmosphere is darkly romantic and theatrical.",
    }

    _MUSIC = [
        "禁止音乐 / No Music",
        "不指定 / Unspecified",
        # 🎹 器乐
        "钢琴 / Piano", "管弦乐 / Orchestral",
        "原声吉他 / Acoustic",
        # 🎛️ 电子
        "电子 / Electronic", "氛围 / Ambient",
        "合成器浪潮 / Synthwave", "芯片音乐 / Chiptune",
        "Lo-fi / Lo-fi",
        # 🎞️ 叙事
        "史诗 / Epic", "悬疑 / Suspense",
        "浪漫弦乐 / Romantic Strings",
        # 🥁 节奏
        "摇滚 / Rock", "爵士 / Jazz",
        "嘻哈 / Hip-Hop", "放克 / Funk",
        # ⛪ 人声
        "纯人声合唱 / Acapella Choir",
        # 🔇 极简
        "极简拟音 / Minimalist Foley",
        # 🏮 中国风
        "国风民乐 / Chinese Folk",
        "戏曲 / Chinese Opera",
        "古琴 / Guqin",
    ]

    _MUSIC_HINTS = {
        "禁止音乐 / No Music": "ABSOLUTELY NO background music of any kind. non_diegetic_music MUST be \"N/A\". Do not add any score, melody, or rhythm.",
        "钢琴 / Piano": "a solo piano piece at a slow to moderate tempo, with sparse delicate notes and natural reverb",
        "管弦乐 / Orchestral": "a majestic full orchestral arrangement with swelling strings and warm brass, maintaining a steady high-energy rhythm throughout",
        "原声吉他 / Acoustic": "an acoustic guitar piece with gentle fingerpicking patterns and warm natural wood resonance",
        "电子 / Electronic": "an electronic track with layered synthesizers, digital beats, and atmospheric pads",
        "氛围 / Ambient": "a minimal ambient soundscape with long sustained tones, subtle textures, and no distinct rhythm",
        "合成器浪潮 / Synthwave": "a pulsing Synthwave instrumental track with heavy analog bass, retro drum machines, neon-soaked pads, and a driving steady rhythm, no vocals, starting abruptly at full energy with zero intro",
        "芯片音乐 / Chiptune": "a retro 8-bit instrumental chiptune track with square-wave melodies, simple waveforms, and nostalgic video game sound",
        "Lo-fi / Lo-fi": "a lo-fi instrumental beat with vinyl crackle, mellow chords, soft drum loops, and a relaxed downtempo groove",
        "史诗 / Epic": "an epic cinematic instrumental score with powerful brass, thundering percussion, soaring choir, and dramatic steady intensity, starting abruptly at full energy without any intro or build-up",
        "悬疑 / Suspense": "a tense suspense instrumental score with low-frequency drones, sudden dissonant stabs, creeping tension, and unsettling silence",
        "浪漫弦乐 / Romantic Strings": "a romantic instrumental string arrangement with lush violins, gentle cello, harp glissandos, and a tender sustained atmosphere",
        "摇滚 / Rock": "an instrumental-only rock track with electric guitar riffs, driving drums, bass groove, and energetic dynamics, STRICTLY NO VOCALS, starting at full power with zero intro",
        "爵士 / Jazz": "an instrumental jazz piece with walking bass, brushed drums, improvisational piano or saxophone, smoky club atmosphere, no vocals",
        "嘻哈 / Hip-Hop": "an instrumental hip-hop beat with heavy 808 bass, crisp trap snares, hi-hat rolls, and a grooving rhythmic flow, STRICTLY NO VOCALS, dropping in at full energy with no intro",
        "放克 / Funk": "an instrumental funk groove with a bouncy slap bassline, tight rhythm guitar, brass stabs, and an infectious syncopated rhythm, no vocals, kicking in immediately at full groove",
        "纯人声合唱 / Acapella Choir": "a pure acapella choir with layered vocal harmonies and no instruments, evoking sacred, ethereal, or haunting atmosphere",
        "极简拟音 / Minimalist Foley": "minimalist foley and ambient silence — only crisp physical sound effects like subtle clicks, soft whooshes, and spatial emptiness, with no melodic music at all",
        "国风民乐 / Chinese Folk": "a traditional Chinese folk piece with guzheng, erhu, dizi bamboo flute, pipa, and flowing pentatonic melodies evoking ancient landscapes",
        "戏曲 / Chinese Opera": "a stylized Chinese opera piece with clanging gongs, wooden clappers, piercing erhu, and dramatic vocal delivery in traditional theatrical style",
        "古琴 / Guqin": "a solo guqin piece with deep resonant plucked silk strings, slow meditative pace, profound stillness, and subtle harmonic overtones",
    }

    _ASPECTS = [
        "16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "4:5", "5:4",
    ]

    _ASPECT_HINTS = {
        "16:9": "standard widescreen — use wide establishing shots, horizontal subject placement, cinematic scope",
        "9:16": "vertical portrait — center subjects vertically, stack elements top-to-bottom, leave breathing room above and below",
        "4:3": "classic Academy ratio — balanced framed composition, suited for dialogue and character-focused shots",
        "3:4": "tall portrait — vertical emphasis, subjects fill the frame from top to bottom, dramatic low/high angles",
        "1:1": "square format — symmetrical center-weighted composition, subjects centered in frame",
        "21:9": "ultrawide cinematic — emphasize sweeping horizontal space, panoramic landscapes, subjects placed off-center with vast negative space",
        "4:5": "portrait tall — slightly taller than 3:4, ideal for social media portrait, subjects framed with vertical breathing room",
        "5:4": "landscape tall — slightly taller than standard, balanced composition with modest horizontal emphasis",
    }

    _CUTS = [
        "不指定 / Unspecified",
        "不切镜 / Single Shot",
        "1 次切镜 / 1 Cut",
        "2 次切镜 / 2 Cuts",
        "3 次切镜 / 3 Cuts",
        "4 次切镜 / 4 Cuts",
        "5 次切镜 / 5 Cuts",
        "6 次切镜 / 6 Cuts",
        "7 次切镜 / 7 Cuts",
        "8 次切镜 / 8 Cuts",
        "9 次切镜 / 9 Cuts",
    ]

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "预设模式": ([
                    "纯文本生成音视频[英文]-T2VA [EN]", "纯文本生成音视频[中文]-T2VA [ZH]",
                    "首帧图生成音视频[英文]-I2VA [EN]", "首帧图生成音视频[中文]-I2VA [ZH]",
                    "首尾帧生成音视频[英文]-FL2VA [EN]", "首尾帧生成音视频[中文]-FL2VA [ZH]",
                    "尾帧图生成音视频[英文]-L2VA [EN]", "尾帧图生成音视频[中文]-L2VA [ZH]",
                ],),
                "视频时长": ("INT", {"default": 8, "min": 4, "max": 15, "step": 1,
                    "tooltip": "视频时长 (秒), MiniMax H3 支持 4–15 秒"}),
                "视觉风格": (s._STYLES, {"default": "不指定 / Unspecified"}),
                "音乐风格": (s._MUSIC, {"default": "禁止音乐 / No Music"}),
                "画面比例": (s._ASPECTS, {"default": "16:9"}),
                "切镜次数": (s._CUTS, {"default": "不指定 / Unspecified"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("system_prompt",)
    FUNCTION = "build"
    CATEGORY = "JLZ/MiniMax"

    def build(self, 预设模式, 视频时长, 视觉风格, 音乐风格, 画面比例, 切镜次数):
        preset = 预设模式
        duration = 视频时长
        style = 视觉风格
        music = 音乐风格
        aspect = 画面比例
        cuts = 切镜次数
        match preset:
            case "纯文本生成音视频[英文]-T2VA [EN]":   base = MINIMAX_T2VA_EN
            case "纯文本生成音视频[中文]-T2VA [ZH]":   base = MINIMAX_T2VA_ZH
            case "首帧图生成音视频[英文]-I2VA [EN]":   base = MINIMAX_I2VA_EN
            case "首帧图生成音视频[中文]-I2VA [ZH]":   base = MINIMAX_I2VA_ZH
            case "首尾帧生成音视频[英文]-FL2VA [EN]":   base = MINIMAX_FL2VA_EN
            case "首尾帧生成音视频[中文]-FL2VA [ZH]":   base = MINIMAX_FL2VA_ZH
            case "尾帧图生成音视频[英文]-L2VA [EN]":   base = MINIMAX_L2VA_EN
            case "尾帧图生成音视频[中文]-L2VA [ZH]":   base = MINIMAX_L2VA_ZH
            case _: raise ValueError(f'未知预设: "{preset}"')

        is_zh = "[ZH]" in preset
        params = []

        if is_zh:
            params.append("## 目标视频参数（必须严格遵守）")
            params.append(f"- 视频时长：正好 {duration} 秒（镜头切分和时间戳必须精确落在此范围内，最后一个镜头必须在第{duration}秒前结束）")
            if "不指定" not in style:
                en_name = style.split(" / ")[0]
                zh_name = style.split(" / ")[-1]
                hint = self._STYLE_HINTS.get(style, "")
                params.append(f"- 视觉风格：{zh_name} ({en_name}) — {hint}")
                params.append(f"  ⚠️ [Shot 1] 必须以 \"{en_name}\" 开头，然后立即用1-2句话详细描述{zh_name}在画面中的具体视觉呈现——材质、光影、色彩、动作特征。严禁只写风格名称就跳到下一句！必须写出该风格\"长什么样\"。")
                params.append(f"  正确示例: \"[Shot 1] 粘土动画，画面中的角色呈现手工泥塑的圆润质感，表面可见细微指痕和工具刮痕，动作带有定格动画特有的逐帧卡顿节奏...\"")
                params.append(f"  错误示例: \"[Shot 1] 粘土动画，中全景镜头...\"（只写了名称，没有视觉描述）")
            if "不指定" not in music:
                zh_name = music.split(" / ")[-1]
                hint = self._MUSIC_HINTS.get(music, "")
                params.append(f"- 背景音乐风格：{zh_name} — {hint}")
                if "禁止音乐" in music:
                    params.append(f"  ⚠️ 整个视频不得出现任何背景音乐。non_diegetic_music 必须严格输出 \"N/A\"。")
            if "不指定" not in cuts:
                if "不切镜" in cuts:
                    params.append(f"- 切镜：固定镜头，不切镜。整段视频只有 [Shot 1] 一个镜头。仅通过运镜（摇摄、俯仰、横移、变焦、跟拍、推拉）改变视角。严禁输出 [Shot N] 时间戳。")
                else:
                    n = int(cuts.split(" ")[0])
                    max_ok = max(1, duration // 2)
                    if n > max_ok:
                        params.append(f"- ⚠️ 切镜次数 {n} 对于 {duration} 秒视频过多（合理上限 {max_ok} 次）。请根据实际可用时长自行削减到合理范围，保证每个镜头至少 2 秒。")
                    params.append(f"- 切镜：正好 {n} 次（共 {n+1} 个镜头）。所有镜头必须在 {duration} 秒内完成。切镜时机遵循叙事节奏——紧张段落切快、抒情段落切慢，不可均分。每次切镜必须以 [Shot N] At MM:SS.mmm 开头，时间戳严格递增。")
            hint = self._ASPECT_HINTS.get(aspect, "")
            params.append(f"- 画面比例：{aspect} — {hint}")
            params.append(f"  所有镜头构图、主体位置、留白空间必须匹配 {aspect} 比例。")
        else:
            params.append("## Target Video Parameters (MUST follow exactly)")
            params.append(f"- Duration: exactly {duration} seconds (all shot timestamps MUST fall within this range; the final shot must end before the {duration}-second mark)")
            if "Unspecified" not in style:
                en_name = style.split(" / ")[0]
                hint = self._STYLE_HINTS.get(style, "")
                params.append(f"- Visual style: {en_name} — {hint}")
                params.append(f"  ⚠️ [Shot 1] MUST begin with \"{en_name}\" and immediately elaborate with 1-2 sentences of concrete visual description — textures, lighting, colors, motion characteristics that define this style. Do NOT just name the style and move on. Show what the style actually looks like.")
                params.append(f"  Correct: \"[Shot 1] Claymation, the characters have the rounded tactile quality of hand-sculpted clay with visible fingerprints and tool marks, their movements carrying the distinctive frame-by-frame stutter of stop-motion...\"")
                params.append(f"  Wrong: \"[Shot 1] Claymation, a medium-wide shot...\" (name only, no visual description)")
            if "Unspecified" not in music:
                en_name = music.split(" / ")[0]
                hint = self._MUSIC_HINTS.get(music, "")
                params.append(f"- Background music style: {en_name} — {hint}")
                if "No Music" in music:
                    params.append(f"  ⚠️ The video must have absolutely no background music. non_diegetic_music MUST be \"N/A\".")
            if "Unspecified" not in cuts:
                if "Single Shot" in cuts:
                    params.append(f"- Cuts: Single continuous shot — NO cuts. The entire video is only [Shot 1]. Use camera movement only (pan, tilt, truck, zoom, tracking, push/pull) to change viewpoint. Do NOT output any [Shot N] timestamps.")
                else:
                    n = int(cuts.split(" ")[0])
                    max_ok = max(1, duration // 2)
                    if n > max_ok:
                        params.append(f"- ⚠️ {n} cuts is excessive for a {duration}-second video (reasonable max: {max_ok}). Reduce to a feasible number, ensuring at least 2 seconds per shot.")
                    params.append(f"- Cuts: exactly {n} cut(s) (meaning {n+1} total shots). All shots must fit within {duration} seconds. Cut timing must follow narrative rhythm — faster cuts for tense/action moments, longer holds for calm/emotional moments. Do NOT space cuts evenly. Every cut MUST begin with [Shot N] At MM:SS.mmm with strictly increasing timestamps.")
            hint = self._ASPECT_HINTS.get(aspect, "")
            params.append(f"- Aspect ratio: {aspect} — {hint}")
            params.append(f"  All shot compositions, subject placement, and negative space must be framed for {aspect}.")
        params.append("")
        param_block = "\n".join(params)

        marker = "## "
        idx = base.find(marker)
        if idx > 0:
            result = base[:idx].rstrip() + "\n\n" + param_block + base[idx:]
        else:
            result = param_block + "\n" + base

        return (result,)


# === JLZ_MiniMaxRef2vaPreset ===
class JLZ_MiniMaxRef2vaPreset:
    """MiniMax H3 Ref2VA 全引用模式专用 — 多模态参考 + 风格策略"""

    _STYLES = [
        "保持统一风格 / Consistent Style",
        "多种风格混搭 / Mixed Styles",
        "多种风格转换 / Style Transformation",
    ]

    _STYLE_HINTS = {
        "保持统一风格 / Consistent Style": "STRICT STYLE CONSISTENCY — all characters, environments, and visual elements must share the exact same visual style derived from the reference images. Every frame must look like it belongs to a single unified visual universe. No character should look like they came from a different artwork.",
        "多种风格混搭 / Mixed Styles": "STYLE MIXING — different characters or elements may retain their distinct visual styles from their respective references. Examples: a live-action person interacting with a 2D-animated character; two pixel-art characters walking through a photorealistic background; a clay figure next to an origami figure. CRITICAL: each reference element must remain visually STABLE — a real person must stay real, an anime character must stay anime, clay must stay clay throughout the video. The challenge is making them coexist naturally in the same space.",
        "多种风格转换 / Style Transformation": "STYLE TRANSFORMATION — the ENTIRE frame undergoes a smooth, visible transition from one visual style to another over the course of the video. Examples: live-action gradually becomes 2D-animated; claymation transforms into origami; watercolor washes over a realistic scene. ALL shapes, proportions, and spatial relationships must be preserved during the transformation — only the rendering style changes. The transformation must be smooth and continuous, not an abrupt switch.",
    }

    _CUTS = JLZ_MiniMaxPreset._CUTS
    _MUSIC = JLZ_MiniMaxPreset._MUSIC
    _MUSIC_HINTS = JLZ_MiniMaxPreset._MUSIC_HINTS
    _ASPECTS = JLZ_MiniMaxPreset._ASPECTS
    _ASPECT_HINTS = JLZ_MiniMaxPreset._ASPECT_HINTS

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "预设模式": ([
                    "多参考生成音视频[英文]-Ref2VA [EN]",
                    "多参考生成音视频[中文]-Ref2VA [ZH]",
                ],),
                "参考图片介绍": ("STRING", {"default": "", "multiline": True,
                    "placeholder": "输入参考图片描述，例：图一男主角特写，图二女主角全身，图三背景街道..."}),
                "参考视频介绍": ("STRING", {"default": "", "multiline": True,
                    "placeholder": "输入参考视频描述，例：视频一运镜参考，视频二角色动作参考..."}),
                "参考音频介绍": ("STRING", {"default": "", "multiline": True,
                    "placeholder": "输入参考音频描述，例：音频一男主音色参考，音频二女主音色参考..."}),
                "视频时长": ("INT", {"default": 8, "min": 4, "max": 15, "step": 1,
                    "tooltip": "视频时长 (秒), MiniMax H3 支持 4–15 秒"}),
                "视觉风格": (s._STYLES, {"default": "保持统一风格 / Consistent Style"}),
                "音乐风格": (s._MUSIC, {"default": "禁止音乐 / No Music"}),
                "画面比例": (s._ASPECTS, {"default": "16:9"}),
                "切镜次数": (s._CUTS, {"default": "不指定 / Unspecified"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("system_prompt",)
    FUNCTION = "build"
    CATEGORY = "JLZ/MiniMax"

    def build(self, 预设模式, 参考图片介绍, 参考视频介绍, 参考音频介绍, 视频时长, 视觉风格, 音乐风格, 画面比例, 切镜次数):
        preset = 预设模式
        imgs = 参考图片介绍
        vids = 参考视频介绍
        auds = 参考音频介绍
        duration = 视频时长
        style = 视觉风格
        music = 音乐风格
        aspect = 画面比例
        cuts = 切镜次数

        match preset:
            case "多参考生成音视频[英文]-Ref2VA [EN]":   base = MINIMAX_REF2VA_EN
            case "多参考生成音视频[中文]-Ref2VA [ZH]":   base = MINIMAX_REF2VA_ZH
            case _: raise ValueError(f'未知预设: "{preset}"')

        is_zh = "[ZH]" in preset
        params = []

        # ── 参考素材注入 ──
        if is_zh:
            params.append("## 目标视频参数（必须严格遵守）")
            if imgs.strip():
                params.append(f"- 参考图片说明：{imgs.strip()}")
            if vids.strip():
                params.append(f"- 参考视频说明：{vids.strip()}")
            if auds.strip():
                params.append(f"- 参考音频说明：{auds.strip()}")
            params.append(f"- 视频时长：正好 {duration} 秒（镜头切分和时间戳必须精确落在此范围内，最后一个镜头必须在第{duration}秒前结束）")
            hint = self._STYLE_HINTS.get(style, "")
            params.append(f"- 视觉风格策略：{style.split('/')[-1].strip()} ({style.split('/')[0].strip()}) — {hint}")
            if "不指定" not in music:
                zh_name = music.split(" / ")[-1]
                hint_m = self._MUSIC_HINTS.get(music, "")
                params.append(f"- 背景音乐风格：{zh_name} — {hint_m}")
                if "禁止音乐" in music:
                    params.append(f"  ⚠️ 整个视频不得出现任何背景音乐。non_diegetic_music 必须严格输出 \"N/A\"。")
            if "不指定" not in cuts:
                if "不切镜" in cuts:
                    params.append(f"- 切镜：固定镜头，不切镜。整段视频只有 [Shot 1] 一个镜头。仅通过运镜改变视角。严禁输出 [Shot N] 时间戳。")
                else:
                    n = int(cuts.split(" ")[0])
                    max_ok = max(1, duration // 2)
                    if n > max_ok:
                        params.append(f"- ⚠️ 切镜次数 {n} 对于 {duration} 秒视频过多（合理上限 {max_ok} 次）。请自行削减。")
                    params.append(f"- 切镜：正好 {n} 次（共 {n+1} 个镜头）。切镜时机遵循叙事节奏，不可均分。每次切镜必须以 [Shot N] At MM:SS.mmm 开头。")
            hint_a = self._ASPECT_HINTS.get(aspect, "")
            params.append(f"- 画面比例：{aspect} — {hint_a}")
            params.append(f"  所有镜头构图、主体位置、留白空间必须匹配 {aspect} 比例。")
        else:
            params.append("## Target Video Parameters (MUST follow exactly)")
            if imgs.strip():
                params.append(f"- Reference image notes: {imgs.strip()}")
            if vids.strip():
                params.append(f"- Reference video notes: {vids.strip()}")
            if auds.strip():
                params.append(f"- Reference audio notes: {auds.strip()}")
            params.append(f"- Duration: exactly {duration} seconds (all shot timestamps MUST fit within this range; the final shot must end before the {duration}-second mark)")
            hint = self._STYLE_HINTS.get(style, "")
            params.append(f"- Visual style strategy: {style.split('/')[0].strip()} — {hint}")
            if "Unspecified" not in music:
                en_name = music.split(" / ")[0]
                hint_m = self._MUSIC_HINTS.get(music, "")
                params.append(f"- Background music style: {en_name} — {hint_m}")
                if "No Music" in music:
                    params.append(f"  ⚠️ The video must have absolutely no background music. non_diegetic_music MUST be \"N/A\".")
            if "Unspecified" not in cuts:
                if "Single Shot" in cuts:
                    params.append(f"- Cuts: Single continuous shot — NO cuts. Only [Shot 1]. Use camera movement only.")
                else:
                    n = int(cuts.split(" ")[0])
                    max_ok = max(1, duration // 2)
                    if n > max_ok:
                        params.append(f"- ⚠️ {n} cuts is excessive for a {duration}-second video (reasonable max: {max_ok}). Reduce.")
                    params.append(f"- Cuts: exactly {n} cut(s) (meaning {n+1} total shots). Cut timing follows narrative rhythm — do NOT space evenly. Every cut MUST begin with [Shot N] At MM:SS.mmm.")
            hint_a = self._ASPECT_HINTS.get(aspect, "")
            params.append(f"- Aspect ratio: {aspect} — {hint_a}")
            params.append(f"  All shot compositions must be framed for {aspect}.")
        params.append("")
        param_block = "\n".join(params)

        marker = "## "
        idx = base.find(marker)
        if idx > 0:
            result = base[:idx].rstrip() + "\n\n" + param_block + base[idx:]
        else:
            result = param_block + "\n" + base

        return (result,)
