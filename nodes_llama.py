"""
XB-ToolBox Llama 节点
====================
基于 ComfyUI-llama-cpp_vlm 适配，提供 LLM/VLM 本地推理支持。

节点列表：
- XB_llamaModelLoader     : Llama 模型加载器
- XB_llamaInstruct        : Llama 指令推理
- XB_llamaParameters      : Llama 推理参数
- XB_llamaUnloadModel     : Llama 卸载模型
- XB_llamaCleanStates     : Llama 清理状态
- XB_llamaParseJSON       : 解析 JSON
- XB_llamaJSON2BBox       : JSON 转 BBox
- XB_llamaBBox2SEGS       : BBox 转 SEGS
- XB_llamaBBox2Mask       : BBox 转 Mask
- XB_llamaBBoxes2BBox     : BBoxes 转 BBox
- XB_llamaUnpackCodeBlock : 解包代码块
- XB_llamaPromptEnhancer  : 提示词增强预设

A卡适配项 (相比原版):
- 自动检测 AMD/NVIDIA GPU 并调整显存计算
- ROCm / HIP 后端 n_gpu_layers 优化分配
- Vulkan 后端回退支持 (旧 AMD 卡)
- GPU 信息打印便于调试
"""

import os
import io
import gc
import json
import base64
import random
import torch

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter
from .support_llama.cqdm import cqdm
from .support_llama.gguf_layers import get_layer_count
from .support_llama.prompt_enhancer_preset import *

import folder_paths
import comfy.model_management as mm
import comfy.utils

from llama_cpp import Llama
from llama_cpp.llama_chat_format import (
    Llava15ChatHandler, Llava16ChatHandler, MoondreamChatHandler,
    NanoLlavaChatHandler, Llama3VisionAlphaChatHandler, MiniCPMv26ChatHandler
)

# =============================================================================
# A卡 / N卡 检测工具
# =============================================================================

def is_rocm() -> bool:
    """检测是否为 AMD ROCm 环境"""
    try:
        return torch.cuda.is_available() and hasattr(torch.version, "hip") and torch.version.hip is not None
    except Exception:
        return False


def is_nvidia() -> bool:
    """检测是否为 NVIDIA CUDA 环境"""
    try:
        return torch.cuda.is_available() and not is_rocm()
    except Exception:
        return False


def get_gpu_name() -> str:
    """获取 GPU 名称"""
    try:
        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return "Unknown"


def get_vram_gb() -> float:
    """获取 GPU 显存大小 (GB)"""
    try:
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def get_amd_arch() -> str:
    """获取 AMD GPU 架构代号"""
    if not is_rocm():
        return ""
    try:
        raw = torch.cuda.get_device_properties(0).gcnArchName
        return raw.split(":")[0] if raw else "unknown"
    except Exception:
        return "unknown"


# AMD 架构显存效率系数: 某些AMD架构的GGML offload效率与N卡不同
_AMD_VRAM_FACTOR = {
    "gfx1201": 1.55,  # RDNA4
    "gfx1200": 1.55,
    "gfx1151": 1.50,  # RDNA3.5
    "gfx1150": 1.50,
    "gfx1103": 1.50,  # RDNA3
    "gfx1102": 1.50,
    "gfx1101": 1.50,
    "gfx1100": 1.50,
    "gfx1037": 1.65,  # RDNA2
    "gfx1036": 1.65,
    "gfx1035": 1.65,
    "gfx1034": 1.65,
    "gfx1032": 1.65,
    "gfx1031": 1.65,
    "gfx1030": 1.65,
    "gfx1012": 1.70,  # RDNA1
    "gfx1011": 1.70,
    "gfx1010": 1.70,
    "gfx942":  1.40,  # CDNA3 (MI300X)
    "gfx90a":  1.40,  # CDNA2
    "gfx908":  1.45,  # CDNA
    "gfx906":  1.70,  # Vega
}


def get_vram_factor() -> float:
    """获取当前 GPU 的显存系数"""
    if is_nvidia():
        return 1.55
    if is_rocm():
        arch = get_amd_arch()
        for k, v in _AMD_VRAM_FACTOR.items():
            if arch.startswith(k):
                return v
        return 1.60  # AMD 默认
    return 1.55  # CPU / fallback


def print_gpu_info():
    """打印 GPU 信息用于调试"""
    gpu_type = "ROCm (AMD)" if is_rocm() else ("CUDA (NVIDIA)" if is_nvidia() else "CPU")
    gpu_name = get_gpu_name()
    vram = get_vram_gb()
    arch = get_amd_arch() if is_rocm() else ""
    factor = get_vram_factor()
    arch_str = f", arch={arch}" if arch else ""
    print(f"[XB-llama] GPU 检测: {gpu_type}, {gpu_name}, VRAM={vram:.1f}GB{arch_str}, factor={factor}")


# =============================================================================
# Chat Handler 导入 (兼容不同版本 llama-cpp-python)
# =============================================================================

try:
    from llama_cpp.llama_chat_format import MTMDChatHandler
    chat_handlers_extra = ["DeepSeek-OCR"]
    _MTMD = True
except Exception:
    _MTMD = False
    chat_handlers_extra = []

chat_handlers = ["None", "LLaVA-1.5", "LLaVA-1.6", "Moondream2", "nanoLLaVA", "llama3-Vision-Alpha", "MiniCPM-v2.6"]

try:
    from llama_cpp.llama_chat_format import Gemma3ChatHandler
    chat_handlers += ["Gemma3"]
except Exception:
    Gemma3ChatHandler = None

try:
    from llama_cpp.llama_chat_format import Gemma4ChatHandler
    chat_handlers += ["Gemma4"]
except Exception:
    Gemma4ChatHandler = None

try:
    from llama_cpp.llama_chat_format import Qwen25VLChatHandler
    chat_handlers += ["Qwen2.5-VL", "MinerU2.5-Pro"]
except Exception:
    Qwen25VLChatHandler = None

try:
    from llama_cpp.llama_chat_format import Qwen3VLChatHandler
    chat_handlers += ["Qwen3-VL", "Qwen3-VL-Thinking"]
except Exception:
    Qwen3VLChatHandler = None

try:
    from llama_cpp.llama_chat_format import Qwen35ChatHandler
    chat_handlers += ["Qwen3.5", "Qwen3.5-Thinking", "Qwen3.6", "Qwen3.6-Thinking"]
except Exception:
    Qwen35ChatHandler = None

try:
    from llama_cpp.llama_chat_format import (GLM46VChatHandler, LFM2VLChatHandler, GLM41VChatHandler)
    chat_handlers += ["GLM-4.6V", "GLM-4.6V-Thinking", "GLM-4.1V-Thinking", "LFM2-VL"]
except Exception:
    GLM46VChatHandler = None
    LFM2VLChatHandler = None
    GLM41VChatHandler = None

try:
    from llama_cpp.llama_chat_format import LFM25VLChatHandler
    chat_handlers += ["LFM2.5-VL"]
except Exception:
    LFM25VLChatHandler = None

try:
    from llama_cpp.llama_chat_format import GraniteDoclingChatHandler
    chat_handlers += ["Granite-Docling"]
except Exception:
    GraniteDoclingChatHandler = None

try:
    from llama_cpp.llama_chat_format import MiniCPMv45ChatHandler
    chat_handlers += ["MiniCPM-v4.5", "MiniCPM-v4.5-Thinking"]
except Exception:
    MiniCPMv45ChatHandler = None

try:
    from llama_cpp.llama_chat_format import MiniCPMv46ChatHandler
    chat_handlers += ["MiniCPM-v4.6", "MiniCPM-v4.6-Thinking"]
except Exception:
    MiniCPMv46ChatHandler = None

try:
    from llama_cpp.llama_chat_format import PaddleOCRChatHandler
    chat_handlers += ["PaddleOCR-VL-1.5"]
except Exception:
    PaddleOCRChatHandler = None

try:
    from llama_cpp.llama_chat_format import Qwen3ASRChatHandler
    chat_handlers += ["Qwen3-ASR"]
except Exception:
    Qwen3ASRChatHandler = None

try:
    from llama_cpp.llama_chat_format import Step3VLChatHandler
    chat_handlers += ["Step3-VL"]
except Exception:
    Step3VLChatHandler = None

chat_handlers += chat_handlers_extra


# =============================================================================
# AnyType / 存储类
# =============================================================================

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False


class LLAMA_CPP_STORAGE:
    llm = None
    chat_handler = None
    current_config = None
    messages = {}
    sys_prompts = {}

    @classmethod
    def clean_state(cls, id=-1):
        if id == -1:
            cls.messages.clear()
            cls.sys_prompts.clear()
        else:
            cls.messages.pop(f"{id}", None)
            cls.sys_prompts.pop(f"{id}", None)

    @classmethod
    def clean(cls, all=False):
        try:
            cls.llm.close()
        except Exception:
            pass

        try:
            cls.chat_handler._exit_stack.close()
        except Exception:
            pass

        cls.llm = None
        cls.chat_handler = None
        cls.current_config = None
        if all:
            cls.clean_state()

        gc.collect()
        mm.soft_empty_cache()

    @classmethod
    def load_model(cls, config):
        def get_chat_handler(chat_handler):
            match chat_handler:
                case "Qwen3.5" | "Qwen3.5-Thinking" | "Qwen3.6" | "Qwen3.6-Thinking":
                    return Qwen35ChatHandler
                case "Qwen3-VL" | "Qwen3-VL-Thinking":
                    return Qwen3VLChatHandler
                case "Qwen3-ASR":
                    return Qwen3ASRChatHandler
                case "Qwen2.5-VL" | "MinerU2.5-Pro":
                    return Qwen25VLChatHandler
                case "LLaVA-1.5":
                    return Llava15ChatHandler
                case "LLaVA-1.6":
                    return Llava16ChatHandler
                case "Moondream2":
                    return MoondreamChatHandler
                case "nanoLLaVA":
                    return NanoLlavaChatHandler
                case "llama3-Vision-Alpha":
                    return Llama3VisionAlphaChatHandler
                case "MiniCPM-v2.6":
                    return MiniCPMv26ChatHandler
                case "MiniCPM-v4.5" | "MiniCPM-v4.5-Thinking":
                    return MiniCPMv45ChatHandler
                case "MiniCPM-v4.6" | "MiniCPM-v4.6-Thinking":
                    return MiniCPMv46ChatHandler
                case "Gemma3":
                    return Gemma3ChatHandler
                case "Gemma4":
                    return Gemma4ChatHandler
                case "GLM-4.6V" | "GLM-4.6V-Thinking":
                    return GLM46VChatHandler
                case "GLM-4.1V-Thinking":
                    return GLM41VChatHandler
                case "LFM2-VL":
                    return LFM2VLChatHandler
                case "LFM2.5-VL":
                    return LFM25VLChatHandler
                case "Granite-Docling":
                    return GraniteDoclingChatHandler
                case "DeepSeek-OCR":
                    return MTMDChatHandler
                case "PaddleOCR-VL-1.5":
                    return PaddleOCRChatHandler
                case "Step3-VL":
                    return Step3VLChatHandler
                case "None":
                    return None
                case _:
                    raise ValueError(f'未知模型类型: "{chat_handler}"')

        cls.clean(all=True)
        cls.current_config = config.copy()
        model = config["model"]
        mmproj = config["mmproj"]
        chat_handler = config["chat_handler"]
        n_ctx = config["n_ctx"]
        vram_limit = config["vram_limit"]
        image_max_tokens = config["image_max_tokens"]
        image_min_tokens = config["image_min_tokens"]
        n_gpu_layers = -1

        model_path = os.path.join(folder_paths.models_dir, 'LLM', model)
        handler = get_chat_handler(chat_handler)

        # A卡/N卡统一的显存感知层数计算
        vram_factor = get_vram_factor()
        if vram_limit != -1:
            gguf_layers = get_layer_count(model_path) or 32
            gguf_size = os.path.getsize(model_path) * vram_factor / (1024 ** 3)
            gguf_layer_size = gguf_size / gguf_layers

        if mmproj and mmproj != "None":
            mmproj_path = os.path.join(folder_paths.models_dir, 'LLM', mmproj)
            if chat_handler == "None":
                raise ValueError('"chat_handler" 不能为 None! (加载了 mmproj 视觉模块)')

            if vram_limit != -1:
                mmproj_size = os.path.getsize(mmproj_path) * vram_factor / (1024 ** 3)
                n_gpu_layers = max(1, int((vram_limit - mmproj_size) / gguf_layer_size))

            print(f"[XB-llama] 加载视觉模块: {mmproj}")

            think_mode = "Thinking" in chat_handler
            kwargs = {"clip_model_path": mmproj_path, "verbose": False}
            if chat_handler in ["Qwen3-VL", "Qwen3-VL-Thinking"]:
                kwargs["force_reasoning"] = think_mode
                kwargs["image_max_tokens"] = image_max_tokens
                kwargs["image_min_tokens"] = image_min_tokens
            elif chat_handler in ["MiniCPM-v4.5", "GLM-4.6V", "Qwen3.5"]:
                kwargs["enable_thinking"] = think_mode

            if _MTMD:
                kwargs["image_max_tokens"] = image_max_tokens
                kwargs["image_min_tokens"] = image_min_tokens

            try:
                cls.chat_handler = handler(**kwargs)
            except Exception as e:
                raise RuntimeError(
                    f"{e}\n请更新 llama-cpp-python 版本\n"
                    "N卡: https://github.com/JamePeng/llama-cpp-python/releases\n"
                    "A卡: 请使用 ROCm/HIP 编译的 llama-cpp-python"
                )

        else:
            if vram_limit != -1:
                n_gpu_layers = max(1, int(vram_limit / gguf_layer_size))
            if handler is not None:
                cls.chat_handler = handler(verbose=False)
            else:
                cls.chat_handler = None

        print(f"[XB-llama] 加载模型: {model}")
        print(f"[XB-llama] n_gpu_layers = {n_gpu_layers} (0=仅CPU, -1=全部GPU)")
        cls.llm = Llama(
            model_path,
            chat_handler=cls.chat_handler,
            n_gpu_layers=n_gpu_layers,
            n_ctx=n_ctx,
            verbose=False
        )


any_type = AnyType("*")

# 模型卸载钩子
if not hasattr(mm, "unload_all_models_backup"):
    mm.unload_all_models_backup = mm.unload_all_models

    def patched_unload_all_models(*args, **kwargs):
        LLAMA_CPP_STORAGE.clean(all=True)
        result = mm.unload_all_models_backup(*args, **kwargs)
        return result

    mm.unload_all_models = patched_unload_all_models
    print("[XB-llama] 模型卸载钩子已注册!")

# LLM 模型文件夹注册
llm_extensions = ['.ckpt', '.pt', '.bin', '.pth', '.safetensors', '.gguf']
folder_paths.folder_names_and_paths["LLM"] = ([os.path.join(folder_paths.models_dir, "LLM")], llm_extensions)

# 打印 GPU 信息
print_gpu_info()

# =============================================================================
# 预设提示词
# =============================================================================

preset_prompts = {
    # ── 空 ──
    "Empty - Nothing": "",

    # ── 描述 [EN] ──
    "Normal - Describe [EN]": "Describe this @.",
    "Prompt Style - Tags [EN]": "Your task is to generate a clean list of comma-separated tags for a text-to-@ AI, based *only* on the visual information in the @. Limit the output to a maximum of 50 unique tags. Strictly describe visual elements like subject, clothing, environment, colors, lighting, and composition. Do not include abstract concepts, interpretations, marketing terms, or technical jargon (e.g., no 'SEO', 'brand-aligned', 'viral potential'). The goal is a concise list of visual descriptors. Avoid repeating tags.",
    "Prompt Style - Simple [EN]": "Analyze the @ and generate a simple, single-sentence text-to-@ prompt. Describe the main subject and the setting concisely.",
    "Prompt Style - Detailed [EN]": "Generate a detailed, artistic text-to-@ prompt based on the @. Combine the subject, their actions, the environment, lighting, and overall mood into a single, cohesive paragraph of about 2-3 sentences. Focus on key visual details.",
    "Prompt Style - Extreme Detailed [EN]": "Generate an extremely detailed and descriptive text-to-@ prompt from the @. Create a rich paragraph that elaborates on the subject's appearance, textures of clothing, specific background elements, the quality and color of light, shadows, and the overall atmosphere. Aim for a highly descriptive and immersive prompt.",
    "Prompt Style - Cinematic [EN]": "Act as a master prompt engineer. Create a highly detailed and evocative prompt for an @ generation AI. Describe the subject, their pose, the environment, the lighting, the mood, and the artistic style (e.g., photorealistic, cinematic, painterly). Weave all elements into a single, natural language paragraph, focusing on visual impact.",
    "Creative - Detailed Analysis [EN]": "Describe this @ in detail, breaking down the subject, attire, accessories, background, and composition into separate sections.",
    "Creative - Summarize Video [EN]": "Summarize the key events and narrative points in this video.",
    "Creative - Short Story [EN]": "Write a short, imaginative story inspired by this @ or video.",
    "Creative - Refine & Expand Prompt [EN]": "Refine and enhance the following user prompt for creative text-to-@ generation. Keep the meaning and keywords, make it more expressive and visually rich. Output **only the improved prompt text itself**, without any reasoning steps, thinking process, or additional commentary.",
    "Vision - *Bounding Box [EN]": 'Locate every instance that belongs to the following categories: "#". Report bbox coordinates in {"bbox_2d": [x1, y1, x2, y2], "label": "string"} JSON format as a List.',

    # ── 描述 [ZH] ──
    "Normal - 描述 [ZH]": "请描述这张@。",
    "Prompt Style - 标签 [ZH]": "你的任务是基于@中的视觉信息，为文生@AI生成一个干净的逗号分隔标签列表，最多50个独特标签。严格描述视觉元素，如主体、服装、环境、颜色、光照和构图。不要包含抽象概念、解读、营销术语或技术术语。目标是生成简洁的视觉描述列表，避免重复标签。",
    "Prompt Style - 简洁 [ZH]": "分析这张@，生成一个简洁的单句文生@提示词，简明扼要地描述主体和场景。",
    "Prompt Style - 详细 [ZH]": "基于这张@，生成一个详细、富有艺术感的文生@提示词。将主体、动作、环境、光照和整体氛围融合为一段约2-3句的连贯描述，聚焦关键视觉细节。",
    "Prompt Style - 极度详细 [ZH]": "基于这张@，生成一个极度详细和描述性的文生@提示词。用丰富的段落详细描述主体的外观、服装质感、背景元素、光线质量和颜色、阴影以及整体氛围。力求生成高度描述性和沉浸感的提示词。",
    "Prompt Style - 电影级 [ZH]": "作为一名提示词工程大师，为文生@AI创建一个高度详细、富有感染力的提示词。描述主体、姿态、环境、光照、情绪和艺术风格（如写实摄影、电影级、油画风）。将所有元素编织成一段自然流畅的描述，聚焦视觉冲击力。",
    "Creative - 详细分析 [ZH]": "详细描述这张@，将主体、着装、配饰、背景和构图分解为独立的部分进行说明。",
    "Creative - 视频摘要 [ZH]": "总结这段视频中的关键事件和叙事要点。",
    "Creative - 短故事 [ZH]": "为这张@或视频写一个简短、富有想象力的故事。",
    "Creative - 润色扩充提示词 [ZH]": "优化并增强以下用户提示词，用于创意文生@生成。保留原意和关键词，使其更具表现力和视觉丰富度。**仅输出优化后的提示词文本**，不要包含任何推理步骤、思考过程或额外评论。",
    "Vision - BBox检测 [ZH]": '定位所有属于以下类别的实例："#"。以 {"bbox_2d": [x1, y1, x2, y2], "label": "string"} 的JSON列表格式报告边界框坐标。',
}
preset_tags = list(preset_prompts.keys())


# =============================================================================
# 工具函数
# =============================================================================

def image2base64(image):
    img = Image.fromarray(image)
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG", quality=85)
    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return img_base64


def parse_json(json_str):
    json_output = json_str.strip().removeprefix("```json").removesuffix("```")
    try:
        parsed = json.loads(json_output)
    except Exception as e:
        raise ValueError(f"无法解析 JSON 数据!\n{e}")
    return parsed


def scale_image(image: torch.Tensor, max_size: int = 128):
    img_np = np.clip(255.0 * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8)
    img_pil = Image.fromarray(img_np)
    w, h = img_pil.size
    scale = min(max_size / max(w, h), 1.0)
    new_w, new_h = int(w * scale), int(h * scale)
    img_resized = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return np.array(img_resized)


def qwen3bbox(image, json_data):
    img = Image.fromarray(np.clip(255.0 * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))
    bboxes = []
    for item in json_data:
        x0, y0, x1, y1 = item["bbox_2d"]
        size = 1000
        x0 = x0 / size * img.width
        y0 = y0 / size * img.height
        x1 = x1 / size * img.width
        y1 = y1 / size * img.height
        bboxes.append((x0, y0, x1, y1))
    return bboxes


def draw_bbox(image, json_data, mode):
    label_colors = {}
    img = Image.fromarray(np.clip(255.0 * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)

    for item in json_data:
        try:
            label = item["label"]
        except Exception:
            try:
                label = item["text_content"]
            except Exception:
                label = "bbox"
        x0, y0, x1, y1 = item["bbox_2d"]
        if mode in ["Qwen3-VL", "Qwen2.5-VL"]:
            size = 1000
            x0 = x0 / size * img.width
            y0 = y0 / size * img.height
            x1 = x1 / size * img.width
            y1 = y1 / size * img.height
        bbox = (x0, y0, x1, y1)

        if label not in label_colors:
            label_colors[label] = tuple(random.randint(80, 180) for _ in range(3))
        color = label_colors[label]
        draw.rectangle(bbox, outline=color, width=4)
        text_y = max(0, y0 - 10)
        text_size = draw.textbbox((x0, text_y), label)
        draw.rectangle([text_size[0], text_size[1] - 2, text_size[2] + 4, text_size[3] + 2], fill=color)
        draw.text((x0 + 2, text_y), label, fill=(255, 255, 255))
    return torch.from_numpy(np.array(img).astype(np.float32) / 255.0).unsqueeze(0)


# =============================================================================
# 节点定义
# =============================================================================

class XB_llamaModelLoader:
    """Llama 模型加载器 - 支持 N卡/A卡"""

    @classmethod
    def INPUT_TYPES(s):
        all_llms = folder_paths.get_filename_list("LLM")
        model_list = [f for f in all_llms if "mmproj" not in f.lower()]
        mmproj_list = ["None"] + [f for f in all_llms if "mmproj" in f.lower()]

        return {"required": {
            "model": (model_list,),
            "mmproj": (mmproj_list, {"default": "None"}),
            "chat_handler": (chat_handlers, {"default": "None"}),
            "n_ctx": ("INT", {
                "default": 8192,
                "min": 1024, "max": 327680, "step": 128,
                "tooltip": "上下文长度上限"
            }),
            "vram_limit": ("INT", {
                "default": -1,
                "min": -1, "max": 1024, "step": 1,
                "tooltip": "显存使用上限(GB), -1=不限制\n参考值, 实际可能略超"
            }),
            "image_min_tokens": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 32}),
            "image_max_tokens": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 32}),
        }}

    RETURN_TYPES = ("LLAMACPPMODEL",)
    RETURN_NAMES = ("llama_model",)
    FUNCTION = "loadmodel"
    CATEGORY = "XB-llama"

    def loadmodel(self, model, mmproj, chat_handler, n_ctx, vram_limit, image_min_tokens, image_max_tokens):
        custom_config = {
            "model": model,
            "mmproj": mmproj,
            "chat_handler": chat_handler,
            "n_ctx": n_ctx,
            "vram_limit": vram_limit,
            "image_min_tokens": image_min_tokens,
            "image_max_tokens": image_max_tokens
        }
        if not LLAMA_CPP_STORAGE.llm or LLAMA_CPP_STORAGE.current_config != custom_config:
            print("[XB-llama] 开始加载模型...")
            LLAMA_CPP_STORAGE.load_model(custom_config)
        return (custom_config,)


class XB_llamaInstruct:
    """Llama 指令推理节点"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "llama_model": ("LLAMACPPMODEL",),
                "preset_prompt": (preset_tags, {"default": preset_tags[1]}),
                "custom_prompt": ("STRING", {"default": "", "multiline": True, "placeholder": '用户提示词\n\n带 "*" 的预设提示中用作占位符 (如BBox检测中的目标名称)\n否则将覆盖预设提示词'}),
                "system_prompt": ("STRING", {"multiline": True, "default": ""}),
                "inference_mode": (["one by one", "images", "video"], {
                    "default": "one by one",
                    "tooltip": "one by one: 逐张读取\nimages: 一次性读取所有图片\nvideo: 将输入图像视为视频帧"
                }),
                "max_frames": ("INT", {
                    "default": 24, "min": 2, "max": 1024, "step": 1,
                    "tooltip": '从输入视频中均匀采样的帧数 (仅 "video" 模式)'
                }),
                "max_size": ("INT", {
                    "default": 256, "min": 128, "max": 16384, "step": 64,
                    "tooltip": '"images" 和 "video" 模式下输入图像的最大尺寸'
                }),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "step": 1}),
                "force_offload": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "推理后卸载模型以释放显存"
                }),
                "save_states": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "在内存中保留此对话的上下文"
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
            "optional": {
                "parameters": ("LLAMACPPARAMS",),
                "images": ("IMAGE",),
                "queue_handler": (any_type, {"tooltip": "用于控制 instruct 节点的执行顺序"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("output", "output_list", "state_uid")
    OUTPUT_IS_LIST = (False, True, False)
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def sanitize_messages(self, messages):
        clean_messages = messages.copy()
        for msg in clean_messages:
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        item["image_url"]["url"] = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAACXBIWXMAAAsTAAALEwEAmpwYAAAADElEQVQImWP4//8/AAX+Av5Y8msOAAAAAElFTkSuQmCC"
        return clean_messages

    @staticmethod
    def _timed_completion(llm, label, **kwargs):
        """包装 create_chat_completion, 计时并打印 T/s"""
        import time
        t0 = time.perf_counter()
        output = llm.create_chat_completion(**kwargs)
        t1 = time.perf_counter()
        elapsed = t1 - t0
        try:
            tokens = output.get("usage", {}).get("completion_tokens", 0)
        except Exception:
            tokens = 0
        tps = tokens / elapsed if elapsed > 0 else 0
        print(f"[XB-llama] {label} → {tokens} tokens / {elapsed:.2f}s = {tps:.1f} T/s")
        return output

    def process(self, llama_model, preset_prompt, custom_prompt, system_prompt, inference_mode, max_frames, max_size, seed, force_offload, save_states, unique_id, parameters=None, images=None, queue_handler=None):
        if not LLAMA_CPP_STORAGE.llm:
            LLAMA_CPP_STORAGE.load_model(llama_model)

        if parameters is None:
            parameters = {}

        if _MTMD:
            parameters.pop("present_penalty", None)

        _uid = parameters.get("state_uid", None)
        _parameters = parameters.copy()
        _parameters.pop("state_uid", None)
        uid = unique_id.rpartition('.')[-1] if _uid in (None, -1) else _uid

        last_sys_prompt = LLAMA_CPP_STORAGE.sys_prompts.get(f"{uid}", None)
        video_input = inference_mode == "video"
        system_prompts = "请将输入的图片序列当做视频而不是静态帧序列, " + system_prompt if video_input else system_prompt
        if last_sys_prompt != system_prompts:
            messages = []
            LLAMA_CPP_STORAGE.clean_state()
            LLAMA_CPP_STORAGE.sys_prompts[f"{uid}"] = system_prompts
            if system_prompts.strip():
                messages.append({"role": "system", "content": system_prompts})
        else:
            if save_states:
                try:
                    print(f"[XB-llama] 加载状态和历史 id={uid}...")
                    messages = LLAMA_CPP_STORAGE.messages.get(f"{uid}", [])
                except Exception:
                    messages = []
            else:
                messages = []

        out1 = ""
        out2 = []
        user_content = []
        if custom_prompt.strip() and "*" not in preset_prompt:
            user_content.append({"type": "text", "text": custom_prompt})
        else:
            p = preset_prompts[preset_prompt].replace("#", custom_prompt.strip()).replace("@", "video" if video_input else "image")
            user_content.append({"type": "text", "text": p})

        if images is not None:
            # 检查是否具备图像处理能力:
            # chat_handler=None → 纯文本模型, 绝对不支持图像
            # chat_handler 存在 → 检查是否有 "clip_model_path"(LLaVA系) 或其它图像能力标记
            _ch = LLAMA_CPP_STORAGE.chat_handler
            if _ch is None:
                raise ValueError(
                    "检测到图像输入, 但 chat_handler=None (纯文本模型)!\n"
                    "请选择支持视觉的 chat_handler, 例如 Qwen3-VL / Qwen3.5 / MiniCPM-v4.6 等"
                )
            # LLaVA系 handler 有 clip_model_path 属性, 检查是否为空
            if hasattr(_ch, "clip_model_path") and _ch.clip_model_path is None:
                raise ValueError(
                    "检测到图像输入, 但 mmproj 未正确加载!\n"
                    "请确认在模型加载器中选择了正确的 mmproj 文件"
                )
            # Qwen3.5 等新 handler 不暴露 clip_model_path, 直接放行
            # (如果模型实际不支持图像, llama-cpp-python 会自己报错)

            frames = images
            if video_input:
                indices = np.linspace(0, len(images) - 1, max_frames, dtype=int)
                frames = [images[i] for i in indices]

            if inference_mode == "one by one":
                tmp_list = []
                image_content = {"type": "image_url", "image_url": {"url": ""}}
                user_content.append(image_content)
                messages.append({"role": "user", "content": user_content})
                print(f"[XB-llama] 开始处理 {len(frames)} 张图像")

                import time
                _total_tokens = 0
                _t0 = time.perf_counter()
                for i, image in enumerate(cqdm(frames)):
                    if mm.processing_interrupted():
                        raise mm.InterruptProcessingException()
                    data = image2base64(np.clip(255.0 * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))
                    for item in user_content:
                        if item.get("type") == "image_url":
                            item["image_url"]["url"] = f"data:image/jpeg;base64,{data}"
                            break
                    output = LLAMA_CPP_STORAGE.llm.create_chat_completion(messages=messages, seed=seed, **_parameters)
                    text = output['choices'][0]['message']['content'].removeprefix(": ").lstrip()
                    out2.append(text)
                    if len(frames) > 1:
                        tmp_list.append(f"====== Image {i + 1} ======")
                    tmp_list.append(text)
                    try:
                        _total_tokens += output.get("usage", {}).get("completion_tokens", 0)
                    except Exception:
                        pass
                _elapsed = time.perf_counter() - _t0
                _tps = _total_tokens / _elapsed if _elapsed > 0 else 0
                print(f"[XB-llama] one by one 完成 → {_total_tokens} tokens / {_elapsed:.2f}s = {_tps:.1f} T/s")

                out1 = "\n\n".join(tmp_list)
            else:
                for image in frames:
                    if len(frames) > 1:
                        data = image2base64(scale_image(image, max_size))
                    else:
                        data = image2base64(np.clip(255.0 * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))
                    image_content = {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}
                    user_content.append(image_content)

                messages.append({"role": "user", "content": user_content})
                output = self._timed_completion(LLAMA_CPP_STORAGE.llm, f"{inference_mode} mode", messages=messages, seed=seed, **_parameters)
                out1 = output['choices'][0]['message']['content'].removeprefix(": ").lstrip()
                out2 = [out1]
        else:
            messages.append({"role": "user", "content": user_content})
            output = self._timed_completion(LLAMA_CPP_STORAGE.llm, "text-only", messages=messages, seed=seed, **_parameters)
            out1 = output['choices'][0]['message']['content'].removeprefix(": ").lstrip()
            out2 = [out1]

        if save_states:
            print(f"[XB-llama] 保存状态 id={uid}...")
            messages.append({"role": "assistant", "content": out1})
            clear_message = self.sanitize_messages(messages)
            LLAMA_CPP_STORAGE.messages[f"{uid}"] = clear_message
        else:
            if not LLAMA_CPP_STORAGE.messages.get(f"{uid}"):
                LLAMA_CPP_STORAGE.sys_prompts.pop(f"{uid}", None)

        if force_offload:
            LLAMA_CPP_STORAGE.clean()
        else:
            if LLAMA_CPP_STORAGE.current_config["chat_handler"] in ["Qwen3.5", "Qwen3.5-Thinking"]:
                LLAMA_CPP_STORAGE.llm.n_tokens = 0
                LLAMA_CPP_STORAGE.llm._ctx.memory_clear(True)
                if LLAMA_CPP_STORAGE.llm.is_hybrid and LLAMA_CPP_STORAGE.llm._hybrid_cache_mgr is not None:
                    LLAMA_CPP_STORAGE.llm._hybrid_cache_mgr.clear()

        del messages
        gc.collect()
        return (out1, out2, uid)


class XB_llamaParameters:
    """Llama 推理参数"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "max_tokens": ("INT", {"default": 1024, "min": 0, "max": 4096, "step": 1}),
                "top_k": ("INT", {"default": 30, "min": 0, "max": 1000, "step": 1}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01}),
                "min_p": ("FLOAT", {"default": 0.05, "min": 0.0, "max": 1.0, "step": 0.01}),
                "typical_p": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "temperature": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.01}),
                "repeat_penalty": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "frequency_penalty": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "present_penalty": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 2.0, "step": 0.01}),
                "mirostat_mode": ("INT", {"default": 0, "min": 0, "max": 2, "step": 1}),
                "mirostat_eta": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 1.0, "step": 0.01}),
                "mirostat_tau": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "state_uid": ("INT", {
                    "default": -1, "min": -1, "max": 999999, "step": 1,
                    "tooltip": "使用特定 ID 保存对话状态 (-1 = 使用节点 unique_id)"
                }),
            }
        }
    RETURN_TYPES = ("LLAMACPPARAMS",)
    RETURN_NAMES = ("parameters",)
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, **kwargs):
        return (kwargs,)


class XB_llamaCleanStates:
    """清理对话状态"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "any": (any_type,),
                "state_uid": ("INT", {
                    "default": -1, "min": -1, "max": 999999, "step": 1,
                    "tooltip": "清除特定 ID 的状态 (-1 = 清除全部)"
                }),
            },
        }

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("any",)
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, any, state_uid):
        print(f"[XB-llama] 清理状态 state_uid={state_uid}...")
        LLAMA_CPP_STORAGE.clean_state(state_uid)
        return (any,)


class XB_llamaUnloadModel:
    """卸载 Llama 模型"""

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"any": (any_type,)}}

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("any",)
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, any):
        print("[XB-llama] 卸载 Llama 模型...")
        LLAMA_CPP_STORAGE.clean()
        return (any,)


class XB_llamaJSON2BBox:
    """JSON 转 BBox"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "json": ("STRING", {"forceInput": True}),
                "mode": (["simple", "Qwen3-VL", "Qwen2.5-VL"], {"default": "simple"}),
                "label": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "仅选择特定标签的 BBox"
                }),
            },
            "optional": {
                "image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("BBOX", "IMAGE")
    RETURN_NAMES = ("bboxes", "image_list")
    OUTPUT_IS_LIST = (True, True)
    INPUT_IS_LIST = True
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, json, mode, label, image=None):
        mode = mode[0]
        label = label[0]

        flat_images_list = []
        original_structure = []

        if image is not None:
            for img_batch in image:
                if img_batch.ndim == 3:
                    flat_images_list.append(img_batch.unsqueeze(0))
                    original_structure.append(1)
                else:
                    count = img_batch.shape[0]
                    original_structure.append(count)
                    for n in range(count):
                        flat_images_list.append(img_batch[n:n + 1])

        total_images = len(flat_images_list)
        output_bboxes = []
        processed_flat_results = []

        for i, j in enumerate(json):
            bboxes = parse_json(j)

            if label != "":
                try:
                    bboxes = [item for item in bboxes if item["label"] == label]
                except Exception:
                    bboxes = [item for item in bboxes if item.get("text_content") == label]

            if total_images > 0:
                curr_idx = i if i < total_images else (total_images - 1)
                curr_img = flat_images_list[curr_idx]

                try:
                    res_img = draw_bbox(curr_img[0], bboxes, mode)
                    if res_img.ndim == 3:
                        res_img = res_img.unsqueeze(0)
                    elif res_img.ndim == 4 and res_img.shape[0] > 1:
                        res_img = res_img[0:1]
                    processed_flat_results.append(res_img)
                except Exception as e:
                    print(f"绘制 BBox 出错 image {curr_idx}: {e}")
                    processed_flat_results.append(curr_img)

            if mode in ["Qwen3-VL", "Qwen2.5-VL"]:
                if total_images == 0:
                    raise ValueError("Qwen 模式需要输入图像!")
                curr_idx = i if i < total_images else (total_images - 1)
                bbox = qwen3bbox(flat_images_list[curr_idx][0], bboxes)
            else:
                bbox = [tuple(item["bbox_2d"]) for item in bboxes]

            output_bboxes.append(bbox)

        restructured_images_list = []
        cursor = 0
        for count in original_structure:
            chunk = processed_flat_results[cursor: cursor + count]
            if chunk:
                restructured_images_list.append(torch.cat(chunk, dim=0))
            cursor += count

        return (output_bboxes, restructured_images_list)


class SEG:
    """SEG 数据类"""
    def __init__(self, cropped_image, cropped_mask, confidence, crop_region, bbox, label, control_net_wrapper=None):
        self.cropped_image = cropped_image
        self.cropped_mask = cropped_mask
        self.confidence = confidence
        self.crop_region = crop_region
        self.bbox = bbox
        self.label = label
        self.control_net_wrapper = control_net_wrapper


class XB_llamaBBox2SEGS:
    """BBox 转 SEGS"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "bboxes": ("BBOX",),
                "image": ("IMAGE",),
                "dilation": ("INT", {"default": 10, "min": 0, "max": 200, "step": 1}),
                "feather": ("INT", {"default": 0, "min": 0, "max": 100, "step": 1}),
            }
        }

    RETURN_TYPES = ("SEGS",)
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, bboxes, image, dilation, feather):
        _batch_size, height, width, _channels = image.shape
        mask_shape = (height, width)

        seg_list = []
        image_for_cropping = image[0]

        for bbox in bboxes:
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                print(f"警告: 跳过无效 bbox: {bbox}")
                continue

            x1, y1, x2, y2 = map(int, bbox)
            x1_exp = x1 - dilation
            y1_exp = y1 - dilation
            x2_exp = x2 + dilation
            y2_exp = y2 + dilation

            crop_region = [x1_exp, y1_exp, x2_exp, y2_exp]
            crop_w = x2_exp - x1_exp
            crop_h = y2_exp - y1_exp

            if crop_h <= 0 or crop_w <= 0:
                print(f"警告: 跳过无效扩展尺寸 bbox: {crop_region}")
                continue

            local_mask_np = np.zeros((crop_h, crop_w), dtype=np.float32)
            local_x1 = dilation
            local_y1 = dilation
            local_x2 = local_x1 + (x2 - x1)
            local_y2 = local_y1 + (y2 - y1)
            local_mask_np[local_y1:local_y2, local_x1:local_x2] = 1.0

            if feather > 0:
                local_mask_np = gaussian_filter(local_mask_np, sigma=feather)

            cropped_mask_np = local_mask_np
            cropped_img_padded = torch.zeros((crop_h, crop_w, 3), dtype=image.dtype, device=image.device)

            src_x_start = max(0, x1_exp)
            src_y_start = max(0, y1_exp)
            src_x_end = min(width, x2_exp)
            src_y_end = min(height, y2_exp)

            dst_x_start = src_x_start - x1_exp
            dst_y_start = src_y_start - y1_exp
            dst_x_end = src_x_end - x1_exp
            dst_y_end = src_y_end - y1_exp

            if src_x_end > src_x_start and src_y_end > src_y_start:
                source_crop = image_for_cropping[src_y_start:src_y_end, src_x_start:src_x_end, :]
                cropped_img_padded[dst_y_start:dst_y_end, dst_x_start:dst_x_end, :] = source_crop

            cropped_image_tensor = cropped_img_padded.permute(2, 0, 1).unsqueeze(0)

            seg = SEG(
                cropped_image=cropped_image_tensor,
                cropped_mask=cropped_mask_np,
                confidence=np.array([0.9], dtype=np.float32),
                crop_region=crop_region,
                bbox=np.array(bbox, dtype=np.float32),
                label="bbox"
            )
            seg_list.append(seg)

        segs = (mask_shape, seg_list)
        return (segs,)


class XB_llamaBBox2Mask:
    """BBox 转 Mask"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "bboxes": ("BBOX",),
                "image": ("IMAGE",),
                "dilation": ("INT", {"default": 10, "min": 0, "max": 200, "step": 1}),
                "feather": ("INT", {"default": 0, "min": 0, "max": 100, "step": 1}),
            }
        }

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, bboxes, image, dilation, feather):
        masks = []
        _batch_size, height, width, _channels = image.shape
        mask_shape = (height, width)
        combined_full_mask = torch.zeros(mask_shape, dtype=torch.float32, device=image.device)

        for bbox in bboxes:
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                print(f"警告: 跳过无效 bbox: {bbox}")
                continue

            x1, y1, x2, y2 = map(int, bbox)
            x1_exp = x1 - dilation
            y1_exp = y1 - dilation
            x2_exp = x2 + dilation
            y2_exp = y2 + dilation
            crop_w = x2_exp - x1_exp
            crop_h = y2_exp - y1_exp

            if crop_h <= 0 or crop_w <= 0:
                continue

            local_mask_np = np.zeros((crop_h, crop_w), dtype=np.float32)
            local_x1 = dilation
            local_y1 = dilation
            local_x2 = local_x1 + (x2 - x1)
            local_y2 = local_y1 + (y2 - y1)
            local_mask_np[local_y1:local_y2, local_x1:local_x2] = 1.0

            if feather > 0:
                local_mask_np = gaussian_filter(local_mask_np, sigma=feather)

            current_full_mask_np = np.zeros(mask_shape, dtype=np.float32)
            x1_c, y1_c = max(0, x1_exp), max(0, y1_exp)
            x2_c, y2_c = min(width, x2_exp), min(height, y2_exp)

            if x2_c > x1_c and y2_c > y1_c:
                current_full_mask_np[y1_c:y2_c, x1_c:x2_c] = 1.0

            if feather > 0:
                current_full_mask_np = gaussian_filter(current_full_mask_np, sigma=feather)

            current_full_mask_tensor = torch.from_numpy(current_full_mask_np).to(image.device)
            combined_full_mask = torch.maximum(combined_full_mask, current_full_mask_tensor)

        masks.append(combined_full_mask.unsqueeze(0))
        return (torch.cat(masks, dim=0),)


class XB_llamaBBoxes2BBox:
    """从 BBoxes 中提取单个 BBox"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "bboxes": ("BBOX",),
                "image_index": ("INT", {"default": 0, "min": 0, "max": 1000000, "step": 1}),
                "bbox_index": ("INT", {
                    "default": 0, "min": -998, "max": 999, "step": 1,
                    "tooltip": "图像中的 BBox 索引 (999 = 获取全部)"
                }),
            }
        }

    RETURN_TYPES = ("BBOX",)
    RETURN_NAMES = ("bbox",)
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, bboxes, image_index, bbox_index):
        if bbox_index != 999:
            return ([bboxes[image_index][bbox_index]],)
        return (bboxes[image_index],)


# from: https://github.com/crystian/ComfyUI-Crystools
class XB_llamaParseJSON:
    """解析 JSON 字符串"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "input": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "key": ("STRING",),
                "default": ("STRING",),
            },
        }

    RETURN_TYPES = (any_type, "STRING", "INT", "FLOAT", "BOOLEAN")
    RETURN_NAMES = ("any", "string", "int", "float", "boolean")
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, input, key=None, default=None):
        if isinstance(input, str):
            input = [input]

        result = {}
        for i, json_str in enumerate(input):
            val = ""
            if key is not None and key != "":
                val = get_nested_value(json_str.strip().removeprefix("```json").removesuffix("```"), key, default)
            else:
                raise ValueError("Key 不能为空!")

            result.setdefault("any", []).append(val)
            result.setdefault("string", []).append(str(val))
            result.setdefault("int", []).append(int(val) if isinstance(val, (int, float)) else val)
            result.setdefault("float", []).append(float(val) if isinstance(val, (int, float)) else val)
            result.setdefault("boolean", []).append(
                val.lower() == "true" if isinstance(val, str) else bool(val)
            )

        if len(result.get("any", [])) == 1:
            for k in result:
                result[k] = result[k][0]

        return (result.get("any", ""), result.get("string", ""), result.get("int", 0), result.get("float", 0.0), result.get("boolean", False))


def get_nested_value(data, dotted_key, default=None):
    keys = dotted_key.split('.')
    for key in keys:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return default
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return default
    return data


class XB_llamaUnpackCodeBlock:
    """解包代码块"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "input": ("STRING", {"forceInput": True}),
            },
            "optional": {
                "label": ("STRING",),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output",)
    FUNCTION = "process"
    CATEGORY = "XB-llama"

    def process(self, input, label=None):
        if isinstance(input, str):
            input = [input]

        output = []
        label_str = label if label else ""
        for value in input:
            output.append(value.strip().removeprefix(f"```{label_str}").removesuffix("```"))
        if len(output) == 1:
            return (output[0],)
        return (output,)


class XB_llamaPromptEnhancer:
    """提示词增强预设"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "preset": ([
                    "Qwen-Image [EN]", "Qwen-Image [ZH]",
                    "Qwen-Image 2512 [EN]", "Qwen-Image 2512 [ZH]",
                    "Qwen-Image-Edit [EN]", "Qwen-Image-Edit [ZH]",
                    "Qwen-Image-Edit 2509 [EN]", "Qwen-Image-Edit 2509 [ZH]",
                    "Qwen-Image-Edit 2511 [EN]", "Qwen-Image-Edit 2511 [ZH]",
                    "Krea2 T2I [EN]", "Krea2 T2I [ZH]",
                    "Boogu T2I [EN]", "Boogu T2I [ZH]",
                    "Z-Image Turbo [ZH]", "Z-Image Turbo [EN]",
                    "Flux.2 T2I [EN]", "Flux.2 T2I [ZH]",
                    "Flux.2 I2I [EN]", "Flux.2 I2I [ZH]",
                    "Wan T2V [EN]", "Wan T2V [ZH]",
                    "Wan I2V [EN]", "Wan I2V [ZH]",
                    "Wan I2V Full-Auto [EN]", "Wan I2V Full-Auto [ZH]",
                    "Wan FLF2V [EN]", "Wan FLF2V [ZH]",
                    "LTX2.3 T2V [EN]", "LTX2.3 T2V [ZH]",
                ],),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("system_prompt",)
    FUNCTION = "main"
    CATEGORY = "XB-llama"

    def main(self, preset):
        match preset:
            case "Qwen-Image [EN]":
                return (QWEN_IMAGE_EN,)
            case "Qwen-Image [ZH]":
                return (QWEN_IMAGE_ZH,)
            case "Qwen-Image 2512 [EN]":
                return (QWEN_IMAGE_2512_EN,)
            case "Qwen-Image 2512 [ZH]":
                return (QWEN_IMAGE_2512_ZH,)
            case "Qwen-Image-Edit [EN]":
                return (QWEN_IMAGE_EDIT,)
            case "Qwen-Image-Edit [ZH]":
                return (QWEN_IMAGE_EDIT_ZH,)
            case "Qwen-Image-Edit 2509 [EN]":
                return (QWEN_IMAGE_EDIT_2509,)
            case "Qwen-Image-Edit 2509 [ZH]":
                return (QWEN_IMAGE_EDIT_2509_ZH,)
            case "Qwen-Image-Edit 2511 [EN]":
                return (QWEN_IMAGE_EDIT_2511,)
            case "Qwen-Image-Edit 2511 [ZH]":
                return (QWEN_IMAGE_EDIT_2511_ZH,)
            case "Z-Image Turbo [ZH]":
                return (ZIMAGE_TURBO,)
            case "Z-Image Turbo [EN]":
                return (ZIMAGE_TURBO_EN,)
            case "Flux.2 T2I [EN]":
                return (FLUX2_T2I,)
            case "Flux.2 T2I [ZH]":
                return (FLUX2_T2I_ZH,)
            case "Flux.2 I2I [EN]":
                return (FLUX2_I2I,)
            case "Flux.2 I2I [ZH]":
                return (FLUX2_I2I_ZH,)
            case "Wan T2V [EN]":
                return (WAN_T2V_EN,)
            case "Wan T2V [ZH]":
                return (WAN_T2V_ZH,)
            case "Wan I2V [EN]":
                return (WAN_I2V_EN,)
            case "Wan I2V [ZH]":
                return (WAN_I2V_ZH,)
            case "Wan I2V Full-Auto [EN]":
                return (WAN_I2V_EMPTY_EN,)
            case "Wan I2V Full-Auto [ZH]":
                return (WAN_I2V_EMPTY_ZH,)
            case "Wan FLF2V [EN]":
                return (WAN_FLF2V_EN,)
            case "Wan FLF2V [ZH]":
                return (WAN_FLF2V_ZH,)
            case "Krea2 T2I [EN]":
                return (KREA2_T2I_EN,)
            case "Krea2 T2I [ZH]":
                return (KREA2_T2I_ZH,)
            case "Boogu T2I [EN]":
                return (BOOGU_T2I_EN,)
            case "Boogu T2I [ZH]":
                return (BOOGU_T2I_ZH,)
            case "LTX2.3 T2V [EN]":
                return (LTX2_3_T2V_EN,)
            case "LTX2.3 T2V [ZH]":
                return (LTX2_3_T2V_ZH,)
            case _:
                raise ValueError(f'未知预设: "{preset}"')


# =============================================================================
# 节点注册
# =============================================================================

NODE_CLASS_MAPPINGS = {
    "XB_llamaModelLoader": XB_llamaModelLoader,
    "XB_llamaInstruct": XB_llamaInstruct,
    "XB_llamaParameters": XB_llamaParameters,
    "XB_llamaUnloadModel": XB_llamaUnloadModel,
    "XB_llamaCleanStates": XB_llamaCleanStates,
    "XB_llamaParseJSON": XB_llamaParseJSON,
    "XB_llamaJSON2BBox": XB_llamaJSON2BBox,
    "XB_llamaBBox2SEGS": XB_llamaBBox2SEGS,
    "XB_llamaBBox2Mask": XB_llamaBBox2Mask,
    "XB_llamaBBoxes2BBox": XB_llamaBBoxes2BBox,
    "XB_llamaUnpackCodeBlock": XB_llamaUnpackCodeBlock,
    "XB_llamaPromptEnhancer": XB_llamaPromptEnhancer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_llamaModelLoader": "XB-llama - 📦 模型加载器",
    "XB_llamaInstruct": "XB-llama - 💬 指令推理",
    "XB_llamaParameters": "XB-llama - ⚙️ 推理参数",
    "XB_llamaUnloadModel": "XB-llama - 🗑️ 卸载模型",
    "XB_llamaCleanStates": "XB-llama - 🧹 清理状态",
    "XB_llamaParseJSON": "XB-llama - 📋 解析JSON",
    "XB_llamaJSON2BBox": "XB-llama - 🎯 JSON转BBox",
    "XB_llamaBBox2SEGS": "XB-llama - ✂️ BBox转SEGS",
    "XB_llamaBBox2Mask": "XB-llama - 🎭 BBox转Mask",
    "XB_llamaBBoxes2BBox": "XB-llama - 🔍 BBoxes取BBox",
    "XB_llamaUnpackCodeBlock": "XB-llama - 📝 解包代码块",
    "XB_llamaPromptEnhancer": "XB-llama - ✨ 提示词增强预设",
}
