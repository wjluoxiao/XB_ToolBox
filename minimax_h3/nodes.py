"""
MiniMax-H3 一键漫剧创作 — 节点定义
=====================================
总线信号链: ScriptWriter → PromptGenerator → 分镜处理中心
调度分支: 分镜处理中心 → SceneDispatcher / VideoAudioDispatcher

输出目录: {ComfyUI output}/jzl/{story_name}/{子目录}/
文件命名: {前缀}_{HHMMSS}.txt
"""

import os, re, json, torch
from datetime import datetime


class _FlexibleInputType(dict):
    def __init__(self, type_): self.type_ = type_
    def __getitem__(self, key): return (self.type_,)
    def __contains__(self, key): return True


def _get_output_dir(story_name="", subfolder=""):
    try:
        import folder_paths
        base = folder_paths.get_output_directory()
    except ImportError:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "output")
    safe_name = re.sub(r'[<>:"/\\|?*\s]', '_', (story_name or "untitled").strip())
    out_dir = os.path.join(base, "jzl", safe_name, subfolder)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _safe_path(output_dir, prefix, shot_num=None, ext="txt"):
    ts = datetime.now().strftime("%H%M%S")
    fn = f"{prefix}_{shot_num:03d}_{ts}.{ext}" if shot_num is not None else f"{prefix}_{ts}.{ext}"
    return os.path.join(output_dir, fn)


def _find_latest(output_dir, prefix, shot_num):
    """找到指定镜头的最新 TXT 文件"""
    if not os.path.isdir(output_dir): return None
    pattern = re.compile(rf"{re.escape(prefix)}_{shot_num:03d}_\d{{6}}\.txt")
    matches = sorted([f for f in os.listdir(output_dir) if pattern.match(f)], reverse=True)
    return os.path.join(output_dir, matches[0]) if matches else None


def _find_latest_version(base_dir):
    """找到最新版本文件夹(第NNN次分镜词), 返回路径和下一个编号"""
    if not os.path.isdir(base_dir): return base_dir, 1
    pat = re.compile(r'第(\d{3})次分镜词')
    versions = []
    for f in os.listdir(base_dir):
        m = pat.match(f)
        if m and os.path.isdir(os.path.join(base_dir, f)):
            versions.append((int(m.group(1)), f))
    if versions:
        versions.sort(reverse=True)
        return os.path.join(base_dir, versions[0][1]), versions[0][0] + 1
    return os.path.join(base_dir, "第001次分镜词"), 1



# ═══════════════════════════════════════════════════════════════
#  节点 1: 剧本编剧 (总线生产者)
# ═══════════════════════════════════════════════════════════════

class XB_MiniMax_ScriptWriter:
    @classmethod
    def INPUT_TYPES(cls):
        from .presets.script import STORY_STYLES, SHOT_COUNT_OPTIONS
        try:
            from .sheding.story_styles import STORY_STYLES as _ss
        except ImportError:
            _ss = STORY_STYLES
        return {
            "required": {
                "llm_backend": (["local", "api"], {"default": "local"}),
                "mode": (["拆解模式 (Decompose)", "生成模式 (Generate)"], {"default": "拆解模式 (Decompose)"}),
                "story_style": (list(_ss.keys()), {"default": list(_ss.keys())[0] if _ss else "热血战斗"}),
                "story_name": ("STRING", {"default": "", "placeholder": "故事名称"}),
                "story_input": ("STRING", {"multiline": True, "default": ""}),
                "shot_preference": (["跟随剧本", "着重文戏", "着重武戏"], {"default": "跟随剧本"}),
                "shot_length": (list(SHOT_COUNT_OPTIONS.keys()), {"default": list(SHOT_COUNT_OPTIONS.keys())[0] if SHOT_COUNT_OPTIONS else "短篇 (4镜)"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "step": 1}),
                "force_offload": ("BOOLEAN", {"default": False}),
                "save_states": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "llama_model": ("LLAMACPPMODEL",),
                "parameters": ("LLAMACPPARAMS",),
                "api_response": ("*", {"force_input": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("参数总线", "剧本输出")
    FUNCTION = "execute"
    CATEGORY = "XB-llama/MiniMax"

    def execute(self, mode, story_name, story_input, story_style, shot_length,
                seed, force_offload, save_states,
                llm_backend="local", shot_preference="跟随剧本", llama_model=None, parameters=None, api_response=None):
        from .presets.script import build_script_prompt, SHOT_COUNT_OPTIONS
        from ..nodes_llama import LLAMA_CPP_STORAGE

        bus = json.dumps({"story_name": story_name, "api_response": api_response, "has_llama": llama_model is not None}, ensure_ascii=False)
        if not story_input or not story_input.strip():
            return (bus, "[错误] 请输入故事内容")

        system_prompt = build_script_prompt(user_story=story_input.strip(), mode=mode, story_style=story_style, shot_count_label=shot_length)
        shot_count = SHOT_COUNT_OPTIONS.get(shot_length, 4)
        user_msg = f"请生成 {shot_count} 个分镜。输出 [SHOT_START]...[SHOT_END] 格式的分镜块。"

        if llm_backend == "api" and api_response:
            result = api_response
        elif llm_backend == "local" and llama_model is not None:
            if not LLAMA_CPP_STORAGE.llm: LLAMA_CPP_STORAGE.load_model(llama_model)
            try:
                _params = parameters.copy() if parameters else {}
                _params.pop("present_penalty", None); _params.pop("state_uid", None)
                output = LLAMA_CPP_STORAGE.llm.create_chat_completion(
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}],
                    seed=seed, **_params)
                result = output["choices"][0]["message"]["content"]
            except Exception as e:
                return (bus, f"[LLM 错误] {e}")
            finally:
                if force_offload: LLAMA_CPP_STORAGE.clean()
                elif not save_states: LLAMA_CPP_STORAGE.clean_state()
        else:
            return (bus, "[错误] 请连接 llama_model 或 api_response")

        prefix = "生成故事拆解" if "生成" in mode else "原始故事拆解"
        with open(_safe_path(_get_output_dir(story_name, "故事拆解"), prefix), "w", encoding="utf-8") as f:
            f.write(result)
        return (bus, result)


# ═══════════════════════════════════════════════════════════════
#  节点 2: 提示词生成器 (批量)
# ═══════════════════════════════════════════════════════════════

class XB_MiniMax_PromptGenerator:
    """批量生成全部镜头的 H3 提示词 → 保存 TXT"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "bus": ("*", {"force_input": True}),
                "shot_text": ("*", {"force_input": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "step": 1}),
                "force_offload": ("BOOLEAN", {"default": False}),
                "save_states": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("参数总线", "剧本输入")
    FUNCTION = "execute"
    CATEGORY = "XB-llama/MiniMax"

    def execute(self, bus, shot_text, seed, force_offload, save_states):
        from .presets.prompt import build_prompt_system
        from ..nodes_llama import LLAMA_CPP_STORAGE

        try:
            bus_data = json.loads(bus) if isinstance(bus, str) else (bus or {})
        except Exception:
            bus_data = {}
        story_name = bus_data.get("story_name", "")
        api_response = bus_data.get("api_response")

        shots = re.findall(r'\[SHOT_START\](.*?)\[SHOT_END\]', shot_text or "", re.DOTALL)
        shots = [s.strip() for s in shots]
        if not shots: return (bus, shot_text)

        # ── 批量生成, 数据存入总线(消除磁盘耦合) ──
        h3_list, scene_list, va_list = [], [], []
        base_dir = _get_output_dir(story_name, "H3提示词")
        _, next_ver = _find_latest_version(base_dir)
        ver_dir = os.path.join(base_dir, f"第{next_ver:03d}次分镜词")
        os.makedirs(ver_dir, exist_ok=True)
        for i, shot in enumerate(shots):
            shot_num = i + 1
            prompt = build_prompt_system("参考图/视频/音频将在生成时由调度器自动匹配", shot)
            user_msg = f"为第 {shot_num} 镜生成 Minimax-H3 的视频提示词。直接输出提示词文本。"

            if api_response:
                h3_text = api_response
            elif bus_data.get("has_llama") and LLAMA_CPP_STORAGE.llm:
                try:
                    output = LLAMA_CPP_STORAGE.llm.create_chat_completion(
                        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user_msg}], seed=seed)
                    h3_text = output["choices"][0]["message"]["content"]
                except Exception as e:
                    h3_text = f"[LLM 错误] 第{shot_num}镜: {e}"
            else:
                h3_text = f"[跳过] 第{shot_num}镜: 无LLM"

            chars = "无"; scene = ""; props = "无"; camera = "固定"; action = ""
            for key, pat in [("characters", r'\*\*角色\*\*[：:]\s*(.+?)(?:\n|$)'),
                             ("scene", r'\*\*场景\*\*[：:]\s*(.+?)(?:\n|$)'),
                             ("props", r'\*\*道具\*\*[：:]\s*(.+?)(?:\n|$)'),
                             ("camera", r'\*\*运镜\*\*[：:]\s*(.+?)(?:\n|$)'),
                             ("action", r'\*\*动作描述\*\*[：:]\s*(.+?)(?:\n|$)')]:
                m = re.search(pat, shot)
                if m: locals()[key] = m.group(1).strip()

            scene_info = json.dumps({"shot": shot_num, "characters": chars, "scene": scene, "props": props}, ensure_ascii=False)
            va_info = json.dumps({"shot": shot_num, "camera": camera, "action": action}, ensure_ascii=False)

            h3_list.append(h3_text)
            scene_list.append(scene_info)
            va_list.append(va_info)

            # 持久化保存（副作用，非主数据通道）
            ts = datetime.now().strftime("%H%M%S")
            txt_path = os.path.join(ver_dir, f"{shot_num:03d}镜头_{ts}.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"===H3_PROMPT===\n{h3_text}\n")
                f.write(f"===SCENE_INSTRUCTION===\n{scene_info}\n")
                f.write(f"===VIDEO_AUDIO_INSTRUCTION===\n{va_info}\n")

        # 总线注入结构化数据
        bus_data["h3_prompts"] = h3_list
        bus_data["scene_infos"] = scene_list
        bus_data["va_infos"] = va_list
        new_bus = json.dumps(bus_data, ensure_ascii=False)

        if force_offload: LLAMA_CPP_STORAGE.clean()
        elif not save_states: LLAMA_CPP_STORAGE.clean_state()
        return (new_bus, shot_text)


# ═══════════════════════════════════════════════════════════════
#  节点 3: 分镜处理中心
# ═══════════════════════════════════════════════════════════════

class XB_MiniMax_ShotFormatter:
    """本地文件为主数据通道, 重拍模式直接读选中文件"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reshoot_mode": ("BOOLEAN", {"default": False, "label_on": "重拍", "label_off": "正常"}),
            },
            "optional": {
                "bus": ("*", {"force_input": True}),
                "shot_text": ("*", {"force_input": True}),
                "_reshoot_path": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("H3提示词", "场景调度指令", "视频调度", "音频调度")
    OUTPUT_IS_LIST = (True, True, True, True)
    FUNCTION = "execute"
    CATEGORY = "XB-llama/MiniMax"

    @staticmethod
    def _parse_shots(text):
        return [{"raw": b.strip()} for b in re.findall(r'\[SHOT_START\](.*?)\[SHOT_END\]', text or "", re.DOTALL)]

    def execute(self, reshoot_mode, bus=None, shot_text=None, _reshoot_path=None):
        # ── 重拍: 只读选中的本地文件 ──
        if reshoot_mode and _reshoot_path and os.path.isfile(_reshoot_path):
            content = open(_reshoot_path, "r", encoding="utf-8").read()
            h, s, v = _parse_three_in_one(content)
            h3_list = [h or "[未找到H3提示词]"]
            scene_list = [s or "{}"]
            va_list = [v or "{}"]
            return {"ui": {"text": h3_list}, "result": (h3_list, scene_list, va_list, va_list)}

        # ── 正常模式: 优先从总线读取(无磁盘IO), 回退到磁盘 ──
        try:
            bus_data = json.loads(bus) if isinstance(bus, str) else (bus or {})
        except Exception:
            bus_data = {}

        h3_list = bus_data.get("h3_prompts", [])
        scene_list = bus_data.get("scene_infos", [])
        va_list = bus_data.get("va_infos", [])

        if not h3_list:
            # 磁盘回退
            story_name = bus_data.get("story_name", "")
            shots = self._parse_shots(shot_text)
            if not shots: return ([""], ["{}"], ["{}"], ["{}"])
            shot_count = len(shots)
            h3_list, scene_list, va_list = [], [], []

            base_dir = _get_output_dir(story_name, "H3提示词")
            latest_dir, _ = _find_latest_version(base_dir)
            pattern = re.compile(r'(\d{3})镜头_.*\.txt')
            shot_files = {}
            if os.path.isdir(latest_dir):
                for f in sorted(os.listdir(latest_dir)):
                    m = pattern.match(f)
                    if m:
                        shot_files[int(m.group(1))] = os.path.join(latest_dir, f)

            for i in range(1, shot_count + 1):
                h3, scene, va = "[未找到H3提示词]", "{}", "{}"
                if i in shot_files:
                    content = open(shot_files[i], "r", encoding="utf-8").read()
                    h, s, v = _parse_three_in_one(content)
                    if h: h3 = h
                    if s: scene = s
                    if v: va = v
                if scene == "{}" and i <= len(shots):
                    block = shots[i-1]["raw"]
                    chars, bg, props, cam, act = "无", "", "无", "固定", ""
                    for pat_key, pat in [("chars", r'\*\*角色\*\*[：:]\s*(.+?)(?:\n|$)'),
                                          ("bg", r'\*\*场景\*\*[：:]\s*(.+?)(?:\n|$)'),
                                          ("props", r'\*\*道具\*\*[：:]\s*(.+?)(?:\n|$)'),
                                          ("cam", r'\*\*运镜\*\*[：:]\s*(.+?)(?:\n|$)'),
                                          ("act", r'\*\*动作描述\*\*[：:]\s*(.+?)(?:\n|$)')]:
                        m = re.search(pat, block)
                        if m: locals()[pat_key] = m.group(1).strip()
                    scene = json.dumps({"shot": i, "characters": chars or "无", "scene": bg, "props": props or "无"}, ensure_ascii=False)
                    va = json.dumps({"shot": i, "camera": cam or "固定", "action": act}, ensure_ascii=False)
                h3_list.append(h3)
                scene_list.append(scene)
                va_list.append(va)

        # 对齐长度
        while len(scene_list) < len(h3_list): scene_list.append("{}")
        while len(va_list) < len(h3_list): va_list.append("{}")

        return {"ui": {"text": h3_list}, "result": (h3_list, scene_list, va_list, va_list)}


def _parse_three_in_one(content):
    """解析三合一格式, 返回 (h3_prompt, scene_info, va_info)"""
    h3, scene, va = "", "{}", "{}"
    for section in re.split(r'\n(?====)', content):
        section = section.strip()
        if section.startswith("===H3_PROMPT==="):
            h3 = section[len("===H3_PROMPT===\n"):].strip()
        elif section.startswith("===SCENE_INSTRUCTION==="):
            scene = section[len("===SCENE_INSTRUCTION===\n"):].strip()
        elif section.startswith("===VIDEO_AUDIO_INSTRUCTION==="):
            va = section[len("===VIDEO_AUDIO_INSTRUCTION===\n"):].strip()
    return h3, scene, va


# ═══════════════════════════════════════════════════════════════
#  节点 4: 场景元素调度
# ═══════════════════════════════════════════════════════════════

class XB_MiniMax_SceneDispatcher:
    _KW_CHARACTER = ["角色", "人物", "主角", "反派", "配角"]
    _KW_BACKGROUND = ["背景", "场景", "环境", "bg"]
    _KW_PROP = ["道具", "物品", "武器", "prop"]

    @staticmethod
    def _classify(name):
        try:
            from .sheding.dispatcher_rules import KW_CHARACTER, KW_BACKGROUND, KW_PROP
        except ImportError:
            KW_CHARACTER = XB_MiniMax_SceneDispatcher._KW_CHARACTER
            KW_BACKGROUND = XB_MiniMax_SceneDispatcher._KW_BACKGROUND
            KW_PROP = XB_MiniMax_SceneDispatcher._KW_PROP
        n = name.lower()
        for kw in KW_CHARACTER:
            if kw.lower() in n: return "character"
        for kw in KW_BACKGROUND:
            if kw.lower() in n: return "background"
        for kw in KW_PROP:
            if kw.lower() in n: return "prop"
        return "character"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene_instruction": ("*", {"force_input": True})}, "optional": _FlexibleInputType("IMAGE")}

    RETURN_TYPES = ("IMAGE","IMAGE","IMAGE","IMAGE","IMAGE","IMAGE","IMAGE","IMAGE","IMAGE")
    RETURN_NAMES = ("ref_image_0","ref_image_1","ref_image_2","ref_image_3","ref_image_4","ref_image_5","ref_image_6","ref_image_7","ref_image_8")
    FUNCTION = "execute"
    CATEGORY = "XB-llama/MiniMax"

    def execute(self, scene_instruction, **kwargs):
        needed_chars, needed_bg, needed_props = [], "", []
        try:
            si = json.loads(scene_instruction) if isinstance(scene_instruction, str) else scene_instruction
            if isinstance(si, list) and si:
                s = si[0]
                needed_chars = [c.strip() for c in s.get("characters","无").replace("、",",").split(",") if c.strip() and c.strip()!="无"]
                needed_bg = s.get("scene","").strip()
                needed_props = [p.strip() for p in s.get("props","无").replace("、",",").split(",") if p.strip() and p.strip()!="无"]
        except Exception: pass

        char_images, bg_images, prop_images = {}, {}, {}
        seen = {}
        for name, tensor in kwargs.items():
            if tensor is None or not isinstance(tensor, torch.Tensor): continue
            seen[name] = seen.get(name, -1) + 1
            uname = f"{name}_{seen[name]}" if seen[name] else name
            cat = self._classify(name)
            if cat == "character": char_images[uname] = tensor
            elif cat == "background": bg_images[uname] = tensor
            else: prop_images[uname] = tensor

        empty_img = torch.zeros((1,64,64,3), dtype=torch.float32, device="cpu")
        for t in kwargs.values():
            if isinstance(t, torch.Tensor): empty_img = torch.zeros_like(t); break

        slots = [empty_img] * 9
        si = 0
        # 背景
        for name in bg_images:
            if si >= 9: break
            if not needed_bg or needed_bg in name or name in needed_bg:
                slots[si] = bg_images[name]; si += 1; break
        # 角色
        for cn in needed_chars:
            if si >= 9: break
            for name in char_images:
                if cn in name or name in cn:
                    slots[si] = char_images[name]; si += 1; break
        # 道具
        for pn in needed_props:
            if si >= 9: break
            for name in prop_images:
                if pn in name or name in pn:
                    slots[si] = prop_images[name]; si += 1; break
        return tuple(slots)


# ═══════════════════════════════════════════════════════════════
#  节点 5: 视频调度 (固定9组)
# ═══════════════════════════════════════════════════════════════

class XB_MiniMax_VideoDispatcher:
    """固定9组视频+配对音频, 无需JS动态管理"""

    @classmethod
    def INPUT_TYPES(cls):
        opt = {}
        for c in "ABCDEFGHI":
            opt[f"视频{c}"] = ("IMAGE",)
            opt[f"视频{c}（音频）"] = ("*",)
        return {"required": {"va_instruction": ("*", {"force_input": True})}, "optional": opt}

    RETURN_TYPES = ("IMAGE","*","IMAGE","*","IMAGE","*")
    RETURN_NAMES = ("ref_video_0","ref_video_audio_0","ref_video_1","ref_video_audio_1","ref_video_2","ref_video_audio_2")
    FUNCTION = "execute"
    CATEGORY = "XB-llama/MiniMax"

    def execute(self, va_instruction, **kwargs):
        needed_action = ""
        try:
            vi = json.loads(va_instruction) if isinstance(va_instruction, str) else va_instruction
            if isinstance(vi, list) and vi: needed_action = vi[0].get("action", "").strip()
        except Exception: pass

        videos, video_audios = {}, {}
        seen = {}
        for name, value in kwargs.items():
            if value is None: continue
            seen[name] = seen.get(name, -1) + 1
            uname = f"{name}_{seen[name]}" if seen[name] else name
            if "（音频）" in name:
                video_audios[uname] = value
            elif isinstance(value, torch.Tensor):
                videos[uname] = value

        empty_img = torch.zeros((1,64,64,3), dtype=torch.float32, device="cpu")
        for t in videos.values():
            if isinstance(t, torch.Tensor): empty_img = torch.zeros_like(t); break

        vid_slots = [empty_img]*3; va_slots = [None]*3
        vi = 0
        for name in videos:
            if vi >= 3: break
            if not needed_action or any(kw in name for kw in needed_action.split() if kw):
                vid_slots[vi] = videos[name]; vi += 1
        vai = 0
        for name in video_audios:
            if vai >= 3: break
            va_slots[vai] = video_audios[name]; vai += 1
        # 交叉输出: ref_video_0, ref_video_audio_0, ref_video_1, ...
        return (vid_slots[0], va_slots[0], vid_slots[1], va_slots[1], vid_slots[2], va_slots[2])


# ═══════════════════════════════════════════════════════════════
#  节点 6: 音频调度 (动态)
# ═══════════════════════════════════════════════════════════════

class XB_MiniMax_AudioDispatcher:
    """动态音频接入, 仅接受AUDIO类型"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"va_instruction": ("*", {"force_input": True})}, "optional": _FlexibleInputType("AUDIO")}

    RETURN_TYPES = ("*","*","*")
    RETURN_NAMES = ("ref_audio_0","ref_audio_1","ref_audio_2")
    FUNCTION = "execute"
    CATEGORY = "XB-llama/MiniMax"

    def execute(self, va_instruction, **kwargs):
        audios = {}
        seen = {}
        for name, value in kwargs.items():
            if value is None: continue
            seen[name] = seen.get(name, -1) + 1
            audios[f"{name}_{seen[name]}" if seen[name] else name] = value

        slots = [None]*3
        ai = 0
        for name in audios:
            if ai >= 3: break
            slots[ai] = audios[name]; ai += 1
        return tuple(slots)
