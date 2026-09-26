"""
XB-llama - ✨ 提示词增强反推（一体化融合节点）
================================================
把原先需要 5 个节点串联的链路融合成 1 个节点：

    XB-llama - 📦 模型加载器    ┐
    XB-llama - ⚙️ 推理参数      ├─ 节点内配置（前端面板 → manager_settings JSON，不再需要连线）
    JZL - 🌐 LLM-API 设置      ┘   （API 字段直接内嵌在节点弹窗里；配置存 ComfyUI user 目录，Key 不明文进工作流）
    XB-llama - ✨ 提示词增强预设  ── 节点表面「增强预设」下拉（同时作为 system_prompt 输出）
    XB-llama - 💬 指令推理        ── 执行体（图/文 → 提示词 反推），直接复用其 process()

设计要点
--------
* **零逻辑复制**：真正干活仍走 `XB_llamaInstruct.process()`（本地 llama-cpp / 在线 API 双后端、
  one by one / images / video 三种推理模式、对话状态、打断响应全部继承），本节点只负责
  「收集配置 → 组装 system_prompt → 调 process → 输出」。
* **五个旧节点全部保留**：本节点只是融合，不影响任何既有工作流。
* 输入端口只保留「提示词」（text）与「图像」（images）；输出为「提示词全量 / 提示词列表 / 提示词设定」。

CATEGORY: XB-llama
"""

import json
import os
import random

import folder_paths
from aiohttp import web
from server import PromptServer

from .nodes_llama import (
    LLAMA_CPP_STORAGE,
    XB_llamaInstruct,
    XB_llamaPromptEnhancer,
    preset_tags,
)

# ═══════════════════════════════════════════════════════════════
#  API 设置持久化（存 ComfyUI user 目录，API Key 不明文进工作流）
# ═══════════════════════════════════════════════════════════════

API_PROVIDERS = [
    "OpenAI 兼容 (OpenAI/DeepSeek/Qwen/GLM/Kimi/Ollama/vLLM/LM Studio)",
    "Anthropic",
    "Google Gemini",
]

# 在线 API 默认预设（面板里可改）
_DEFAULT_API_MODEL = "deepseek-v4-flash-vision-exp"
_DEFAULT_API_BASE_URL = "https://api.deepseek.com/v1"


def _api_settings_file():
    try:
        base = folder_paths.get_user_directory()
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "xb_toolbox_llm_api.json")


def read_api_settings():
    """读取 API 设置（无配置返回空字典）"""
    try:
        with open(_api_settings_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_api_settings(data):
    """保存 API 设置到磁盘（成功返回规范化后的字典）"""
    try:
        os.makedirs(os.path.dirname(_api_settings_file()), exist_ok=True)
        with open(_api_settings_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception as e:
        print(f"[XB-llama] API 设置保存失败: {e}")
        return {}


def build_api_config():
    """按「指令推理」的 API 配置格式组装（parse_api_config 直接可识别）"""
    s = read_api_settings()
    return {
        "provider": s.get("provider") or API_PROVIDERS[0],
        "model": (s.get("model") or "").strip() or _DEFAULT_API_MODEL,
        "api_key": (s.get("api_key") or "").strip(),
        "base_url": (s.get("base_url") or "").strip() or _DEFAULT_API_BASE_URL,
        "temperature": _num(s.get("temperature"), 0.6, 0.0, 2.0),
        "max_tokens": int(_num(s.get("max_tokens"), 8192, 1, 262144)),
        "thinking": s.get("thinking"),
    }


@PromptServer.instance.routes.get("/xb_toolbox/llm_api_settings")
async def _xb_llm_api_settings_get(request):
    return web.json_response({
        "ok": True,
        "settings": read_api_settings(),
        "providers": API_PROVIDERS,
    })


@PromptServer.instance.routes.post("/xb_toolbox/llm_api_settings")
async def _xb_llm_api_settings_post(request):
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "请求不是合法 JSON"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "请求体必须是对象"}, status=400)
    settings = {
        "provider": str(payload.get("provider") or API_PROVIDERS[0]),
        "model": str(payload.get("model") or "").strip(),
        "api_key": str(payload.get("api_key") or "").strip(),
        "base_url": str(payload.get("base_url") or "").strip(),
        "temperature": _num(payload.get("temperature"), 0.6, 0.0, 2.0),
        "max_tokens": int(_num(payload.get("max_tokens"), 8192, 1, 262144)),
        "thinking": "enabled" if payload.get("thinking") == "enabled" else "disabled",
    }
    saved = write_api_settings(settings)
    if not saved:
        return web.json_response({"ok": False, "error": "写入失败（请检查 ComfyUI user 目录权限）"}, status=500)
    return web.json_response({"ok": True, "settings": saved})


# ═══════════════════════════════════════════════════════════════
#  配置解析（None / 缺失 / 非法一律安全回落）
# ═══════════════════════════════════════════════════════════════

DEFAULT_SETTINGS = {
    # 本地模型（原「📦 模型加载器」）
    "model": {
        "model": "", "mmproj": "None", "chat_handler": "None",
        "n_ctx": 8192, "vram_limit": -1,
        "image_min_tokens": 0, "image_max_tokens": 0,
    },
    # 运行方式（原「💬 指令推理」的输入侧）
    "run": {
        "inference_mode": "one by one", "max_frames": 24, "max_size": 256,
        "seed": 0, "seed_control": "randomize", "force_offload": False, "save_states": False,
    },
    # 推理参数（原「⚙️ 推理参数」）
    "params": {
        "max_tokens": 6144, "top_k": 40, "top_p": 0.9, "min_p": 0.05,
        "typical_p": 1.0, "temperature": 0.6, "repeat_penalty": 1.12,
        "frequency_penalty": 0.0, "present_penalty": 0.0,
        "mirostat_mode": 0, "mirostat_eta": 0.1, "mirostat_tau": 5.0,
        "state_uid": -1,
    },
    # 面板里手写的「追加设定」（原「追加系统提示词」）
    "extra_system": "",
    # 输出语言（导演台同款「输出语言」；会拼进系统提示词，不影响预设原文）
    "output_lang": "中文 [ZH]",
}

_INFERENCE_MODES = ["one by one", "images", "video"]
# 生成后控制（control_after_generate，与 ComfyUI / 短剧导演台一致）
_SEED_MODES = ["randomize", "fixed", "increment", "decrement"]
_SEED_MAX = 0xFFFFFFFFFFFFFFFF
_OUTPUT_LANGS = ["中文 [ZH]", "英文 [EN]"]
_LANG_HINT = {
    "中文 [ZH]": "【输出语言】请始终使用中文输出。",
    "英文 [EN]": "【Output language】Always respond in English.",
}


def _num(value, default, lo=None, hi=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def _int(value, default, lo=None, hi=None):
    return int(_num(value, default, lo, hi))


def _bool(value, default=False):
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "开启")
    return bool(value)


def _pick(value, allowed, default):
    return value if value in allowed else default


def parse_settings(raw):
    """把 manager_settings（JSON 字符串 / 字典 / None）解析成完整配置"""
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

    out = {
        "model": dict(DEFAULT_SETTINGS["model"]),
        "run": dict(DEFAULT_SETTINGS["run"]),
        "params": dict(DEFAULT_SETTINGS["params"]),
        "extra_system": "",
        "output_lang": DEFAULT_SETTINGS["output_lang"],
    }

    m = data.get("model") if isinstance(data.get("model"), dict) else {}
    md = out["model"]
    md["model"] = str(m.get("model") or "")
    md["mmproj"] = str(m.get("mmproj") or "None")
    md["chat_handler"] = str(m.get("chat_handler") or "None")
    md["n_ctx"] = _int(m.get("n_ctx"), md["n_ctx"], 1024, 327680)
    md["vram_limit"] = _int(m.get("vram_limit"), md["vram_limit"], -1, 1024)
    md["image_min_tokens"] = _int(m.get("image_min_tokens"), md["image_min_tokens"], 0, 4096)
    md["image_max_tokens"] = _int(m.get("image_max_tokens"), md["image_max_tokens"], 0, 4096)

    r = data.get("run") if isinstance(data.get("run"), dict) else {}
    rd = out["run"]
    rd["inference_mode"] = _pick(r.get("inference_mode"), _INFERENCE_MODES, rd["inference_mode"])
    rd["max_frames"] = _int(r.get("max_frames"), rd["max_frames"], 2, 1024)
    rd["max_size"] = _int(r.get("max_size"), rd["max_size"], 128, 16384)
    rd["seed"] = _int(r.get("seed"), rd["seed"], 0, 0xFFFFFFFFFFFFFFFF)
    rd["seed_control"] = _pick(r.get("seed_control"), _SEED_MODES, rd["seed_control"])
    rd["force_offload"] = _bool(r.get("force_offload"), rd["force_offload"])
    rd["save_states"] = _bool(r.get("save_states"), rd["save_states"])

    p = data.get("params") if isinstance(data.get("params"), dict) else {}
    pd = out["params"]
    pd["max_tokens"] = _int(p.get("max_tokens"), pd["max_tokens"], 0, 262144)
    pd["top_k"] = _int(p.get("top_k"), pd["top_k"], 0, 1000)
    pd["top_p"] = _num(p.get("top_p"), pd["top_p"], 0.0, 1.0)
    pd["min_p"] = _num(p.get("min_p"), pd["min_p"], 0.0, 1.0)
    pd["typical_p"] = _num(p.get("typical_p"), pd["typical_p"], 0.0, 1.0)
    pd["temperature"] = _num(p.get("temperature"), pd["temperature"], 0.0, 2.0)
    pd["repeat_penalty"] = _num(p.get("repeat_penalty"), pd["repeat_penalty"], 0.0, 10.0)
    pd["frequency_penalty"] = _num(p.get("frequency_penalty"), pd["frequency_penalty"], 0.0, 1.0)
    pd["present_penalty"] = _num(p.get("present_penalty"), pd["present_penalty"], 0.0, 2.0)
    pd["mirostat_mode"] = _int(p.get("mirostat_mode"), pd["mirostat_mode"], 0, 2)
    pd["mirostat_eta"] = _num(p.get("mirostat_eta"), pd["mirostat_eta"], 0.0, 1.0)
    pd["mirostat_tau"] = _num(p.get("mirostat_tau"), pd["mirostat_tau"], 0.0, 10.0)
    pd["state_uid"] = _int(p.get("state_uid"), pd["state_uid"], -1, 999999)

    out["extra_system"] = str(data.get("extra_system") or "")
    out["output_lang"] = _pick(data.get("output_lang"), _OUTPUT_LANGS, out["output_lang"])
    return out


# ═══════════════════════════════════════════════════════════════
#  节点
# ═══════════════════════════════════════════════════════════════

class XB_llamaPromptReverse:
    """提示词增强反推 — 模型加载器 + 推理参数 + LLM-API 设置 + 提示词增强预设 + 指令推理 五合一"""

    _PRESETS = XB_llamaPromptEnhancer.INPUT_TYPES()["required"]["preset"][0]
    _DEFAULT_PRESET = "Z-Image Turbo [ZH]" if "Z-Image Turbo [ZH]" in _PRESETS else _PRESETS[0]
    _DEFAULT_TASK = "Normal - 描述 [ZH]" if "Normal - 描述 [ZH]" in preset_tags else preset_tags[0]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "backend": (["本地模型", "在线 API"], {
                    "default": "本地模型",
                    "tooltip": "本地模型 = 用下面的模型/mmproj 跑 llama-cpp-python\n"
                               "在线 API = 用「⚙️ 打开 API 设置…」里配置的服务（存本地，不进工作流）",
                }),
                "preset": (cls._PRESETS, {
                    "default": cls._DEFAULT_PRESET,
                    "tooltip": "提示词增强预设（原「✨ 提示词增强预设」）\n"
                               "其内容作为 system_prompt 使用，并原样从 system_prompt 端口输出",
                }),
                "task_preset": (preset_tags, {
                    "default": cls._DEFAULT_TASK,
                    "tooltip": "反推任务预设（原「💬 指令推理」的预设提示词）\n"
                               "带 * 的预设里，* 表示必填占位符；带 # 的预设会把「文本」填入该位置",
                }),
                "open_api_settings": ("BOOLEAN", {
                    "default": False,
                    "label_on": "⚙️ 打开 API 设置…", "label_off": "⚙️ 打开 API 设置…",
                    "tooltip": "点击后弹出 API 设置窗口（provider / 模型名 / API Key / 地址 / 温度 / Token）\n"
                               "配置保存在 ComfyUI user 目录，不会写入工作流",
                }),
                "custom_prompt": ("STRING", {
                    "default": "", "multiline": True,
                    "placeholder": "节点内手写提示词 / 或带 * 预设的占位符内容（如 BBox 检测的目标名称）\n"
                                   "外接「文本」端口有值时以端口值为准",
                }),
                "manager_settings": ("STRING", {"default": "{}", "multiline": False}),
            },
            "optional": {
                "text": ("STRING", {
                    "forceInput": True,
                    "tooltip": "外接提示词（优先于节点上的手写提示词编辑框）\n接上线后节点上的编辑框会锁定不可编辑",
                }),
                "images": ("IMAGE", {
                    "tooltip": "外接图像 / 视频帧（VLM 反推：图 → 提示词）",
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("提示词全量", "提示词列表", "提示词设定")
    OUTPUT_IS_LIST = (False, True, False)
    FUNCTION = "execute"
    CATEGORY = "XB-llama"

    @classmethod
    def IS_CHANGED(cls, manager_settings="", backend="", **kwargs):
        # API 设置 / 配置改动 → 节点重跑
        return json.dumps(
            [manager_settings, backend, read_api_settings()],
            ensure_ascii=False, sort_keys=True,
        )

    # ── 内部：提示词设定（system prompt）= 增强预设 + 输出语言 + 追加设定 ──
    def _build_system_prompt(self, preset, extra, output_lang):
        parts = [XB_llamaPromptEnhancer().main(preset)[0] or ""]
        parts.append(_LANG_HINT.get(output_lang, _LANG_HINT[_OUTPUT_LANGS[0]]))
        extra = (extra or "").strip()
        if extra:
            parts.append(extra)
        return "\n\n".join([p for p in parts if p])

    # ── 内部：本地模型配置 ──
    @staticmethod
    def _local_model_config(cfg):
        md = cfg["model"]
        if not md["model"]:
            raise ValueError(
                "[XB-llama] 未选择本地模型\n"
                "请点节点上的「🤖 大语言模型配置」→ 选好「模型」后保存（或在「LLM 后端」里切到在线API）"
            )
        return {
            "model": md["model"],
            "mmproj": md["mmproj"],
            "chat_handler": md["chat_handler"],
            "n_ctx": md["n_ctx"],
            "vram_limit": md["vram_limit"],
            "image_min_tokens": md["image_min_tokens"],
            "image_max_tokens": md["image_max_tokens"],
        }

    def execute(self, backend, preset, task_preset, open_api_settings, custom_prompt,
                manager_settings, text="", images=None, unique_id=None):
        cfg = parse_settings(manager_settings)

        # ① 提示词设定：增强预设 + 输出语言 + 追加设定
        full_system = self._build_system_prompt(preset, cfg["extra_system"], cfg["output_lang"])

        # ② 用户提示词：外接「提示词」端口优先于节点上的手写框
        user_text = (text or "").strip() or (custom_prompt or "").strip()

        # ③ 后端选择
        if backend == "在线 API":
            api_cfg = build_api_config()
            if not api_cfg["model"]:
                raise ValueError(
                    "[XB-llama] 在线 API 未填写模型名\n"
                    "请点节点上的「🤖 大语言模型配置」→ LLM 后端选「在线API [api]」→ 在「模型」里填写"
                )
            print(f"[XB-llama] 提示词增强反推 → 在线 API: {api_cfg['provider']} / {api_cfg['model']}")
            model_or_api = json.dumps(api_cfg, ensure_ascii=False)
        else:
            local_cfg = self._local_model_config(cfg)
            if not LLAMA_CPP_STORAGE.llm or LLAMA_CPP_STORAGE.current_config != local_cfg:
                print("[XB-llama] 提示词增强反推 → 加载本地模型...")
                LLAMA_CPP_STORAGE.load_model(local_cfg)
            else:
                print(f"[XB-llama] 提示词增强反推 → 本地模型: {local_cfg['model']}")
            model_or_api = local_cfg

        # ④ 参数（原「⚙️ 推理参数」）+ 生成后控制（本次用当前种子，回写下一次）
        parameters = dict(cfg["params"])
        run = cfg["run"]
        seed = int(run["seed"])
        next_seed = None
        if run["seed_control"] == "randomize":
            next_seed = random.randint(0, _SEED_MAX)
        elif run["seed_control"] == "increment":
            next_seed = (seed + 1) & _SEED_MAX
        elif run["seed_control"] == "decrement":
            next_seed = (seed - 1) & _SEED_MAX
        # fixed 模式：不回写（保持锁定）

        # ⑤ 执行（复用「💬 指令推理」的全部推理逻辑）
        out1, out2, _uid = XB_llamaInstruct().process(
            llama_model=model_or_api,
            preset_prompt=task_preset,
            custom_prompt=user_text,
            system_prompt=full_system,
            inference_mode=run["inference_mode"],
            max_frames=run["max_frames"],
            max_size=run["max_size"],
            seed=seed,
            force_offload=run["force_offload"],
            save_states=run["save_states"],
            unique_id=str(unique_id or "0"),
            parameters=parameters,
            images=images,
            queue_handler=None,
        )

        ui = {
            "text": [out1 or ""],
            "backend": [backend],
            "system_prompt": [full_system or ""],
        }
        if next_seed is not None:
            ui["seed"] = [next_seed]   # 前端回写到 manager_settings.run.seed
        return {"ui": ui, "result": (out1 or "", out2 or [], full_system or "")}


NODE_CLASS_MAPPINGS = {
    "XB_llamaPromptReverse": XB_llamaPromptReverse,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_llamaPromptReverse": "XB-llama - ✨ 提示词增强反推",
}
