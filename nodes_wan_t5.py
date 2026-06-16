"""
XB-ToolBox Wan T5 文本编码器加载器
===================================
支持 FP8 scaled 模型 + ROCm 友好。需要 ComfyUI-WanVideoWrapper 作为模型架构库。
"""
import torch
import os
import sys
import importlib.util
import comfy.utils
import folder_paths

# ROCm 补丁
if not hasattr(torch.backends.cuda, "matmul"):
    class _FM: allow_fp16_accumulation = False
    torch.backends.cuda.matmul = _FM()
elif not hasattr(torch.backends.cuda.matmul, "allow_fp16_accumulation"):
    torch.backends.cuda.matmul.allow_fp16_accumulation = False
if not hasattr(torch.cuda, "get_device_capability"):
    torch.cuda.get_device_capability = lambda d=None: (9, 0)
if not hasattr(torch.cuda, "reset_peak_memory_stats"):
    torch.cuda.reset_peak_memory_stats = lambda d=None: None

_PKG_NAME = "_xb_wanwrapper"


def _find_wan_root():
    for base in folder_paths.get_folder_paths("custom_nodes"):
        for n in os.listdir(base):
            if n.startswith("ComfyUI-WanVideoWrapper"):
                p = os.path.join(base, n)
                if os.path.exists(os.path.join(p, "__init__.py")):
                    return p
    raise RuntimeError("ComfyUI-WanVideoWrapper 未安装。XB_WanT5Loader 依赖其 T5EncoderModel。")


def _wan_import(rel_path: str):
    root = _find_wan_root()
    if _PKG_NAME not in sys.modules:
        s = importlib.util.spec_from_file_location(_PKG_NAME, os.path.join(root, "__init__.py"), submodule_search_locations=[root])
        m = importlib.util.module_from_spec(s)
        sys.modules[_PKG_NAME] = m
        s.loader.exec_module(m)
    full = _PKG_NAME + "." + rel_path
    if full in sys.modules:
        return sys.modules[full]
    parts = rel_path.split(".")
    fp = os.path.join(root, *parts[:-1], parts[-1] + ".py")
    if not os.path.exists(fp):
        fp = os.path.join(root, *parts, "__init__.py")
    s = importlib.util.spec_from_file_location(full, fp)
    m = importlib.util.module_from_spec(s)
    sys.modules[full] = m
    s.loader.exec_module(m)
    return m


def _load_state_dict_safe(model_path: str) -> dict:
    sd = comfy.utils.load_torch_file(model_path, safe_load=True)
    has_scaled = "scaled_fp8" in sd
    if has_scaled: del sd["scaled_fp8"]
    scale_weights, keys_to_remove = {}, []
    for key in list(sd.keys()):
        if key.endswith("_scale"):
            base = key[:-6]
            if base in sd:
                scale_weights[base] = sd[key]
                keys_to_remove.append(key)
    if has_scaled:
        print("  [XB_WanT5] FP8 scaled detected, dequantizing...")
        for key, tensor in sd.items():
            if isinstance(tensor, torch.Tensor) and tensor.dtype in (torch.float8_e4m3fn, torch.float8_e5m2):
                sk = key + "_scale"
                sd[key] = tensor.float() * scale_weights[sk].float() if sk in scale_weights else tensor.float()
    else:
        for key, tensor in sd.items():
            if isinstance(tensor, torch.Tensor) and tensor.dtype in (torch.float8_e4m3fn, torch.float8_e5m2):
                sd[key] = tensor.float()
    for key in keys_to_remove: del sd[key]
    return sd


def _convert_t5_keys(sd: dict) -> dict:
    if "shared.weight" not in sd: return sd
    print("  [XB_WanT5] Converting T5 keys...")
    converted = {}
    for key, value in sd.items():
        nk = key
        if key.startswith("encoder.block."):
            parts = key.split(".")
            blk = parts[2]
            if "layer.0.SelfAttention" in key:
                if key.endswith(".k.weight"): nk = f"blocks.{blk}.attn.k.weight"
                elif key.endswith(".o.weight"): nk = f"blocks.{blk}.attn.o.weight"
                elif key.endswith(".q.weight"): nk = f"blocks.{blk}.attn.q.weight"
                elif key.endswith(".v.weight"): nk = f"blocks.{blk}.attn.v.weight"
                elif "relative_attention_bias" in key: nk = f"blocks.{blk}.pos_embedding.embedding.weight"
            elif "layer.0.layer_norm" in key: nk = f"blocks.{blk}.norm1.weight"
            elif "layer.1.layer_norm" in key: nk = f"blocks.{blk}.norm2.weight"
            elif "layer.1.DenseReluDense" in key:
                if "wi_0" in key: nk = f"blocks.{blk}.ffn.gate.0.weight"
                elif "wi_1" in key: nk = f"blocks.{blk}.ffn.fc1.weight"
                elif "wo" in key: nk = f"blocks.{blk}.ffn.fc2.weight"
        elif key == "shared.weight": nk = "token_embedding.weight"
        elif key == "encoder.final_layer_norm.weight": nk = "norm.weight"
        converted[nk] = value
    return converted


# ============================================================
# XB_WanT5Loader — Wan T5 文本编码器加载器
# ============================================================
class XB_WanT5Loader:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model_name": (folder_paths.get_filename_list("text_encoders"),),
                "precision": (["bf16", "fp16", "fp32"], {"default": "bf16"}),
            },
            "optional": {
                "load_device": (["main_device", "offload_device"], {"default": "offload_device"}),
                "quantization": (["disabled", "fp8_e4m3fn"], {"default": "disabled"}),
            },
        }
    RETURN_TYPES = ("WANTEXTENCODER",)
    RETURN_NAMES = ("t5_model",)
    FUNCTION = "load"
    CATEGORY = "XB_ToolBox/Wan"

    def load(self, model_name, precision, load_device="offload_device", quantization="disabled"):
        from comfy.model_management import get_torch_device
        device = get_torch_device()
        cpu_device = torch.device("cpu")
        text_encoder_device = device if load_device == "main_device" else cpu_device
        dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[precision]
        model_path = folder_paths.get_full_path_or_raise("text_encoders", model_name)
        sd = _load_state_dict_safe(model_path)
        if quantization == "disabled":
            for v in sd.values():
                if isinstance(v, torch.Tensor) and v.dtype == torch.float8_e4m3fn:
                    quantization = "fp8_e4m3fn"; break
        if "token_embedding.weight" not in sd and "shared.weight" not in sd:
            raise ValueError("Invalid T5 model, expected 'umt5-xxl' format")
        sd = _convert_t5_keys(sd)
        t5m = _wan_import("wanvideo.modules.t5")
        wan_root = _find_wan_root()
        tk_path = os.path.join(wan_root, "configs", "T5_tokenizer")
        T5_model = t5m.T5EncoderModel(text_len=512, dtype=dtype, device=text_encoder_device, state_dict=sd, tokenizer_path=tk_path, quantization=quantization)
        print(f"  [XB_WanT5] Loaded: {model_name} | {precision} | quant={quantization}")
        return ({"model": T5_model, "dtype": dtype, "name": model_name},)


__all__ = ["XB_WanT5Loader"]
