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
