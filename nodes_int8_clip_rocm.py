"""
XB-ToolBox INT8 CLIP ROCm 节点
==============================
基于 ComfyUI-INT8-Fast-ROCM 适配，提供 INT8 文本编码器加载和保存。

节点列表：
- XB_CLIPLoaderINT8ROCm        : INT8 单文本编码器加载器
- XB_DualCLIPLoaderINT8ROCm    : INT8 双文本编码器加载器
- XB_INT8CLIPSaveROCm          : INT8 CLIP 模型保存
"""

import torch
import logging
import json
import os

import folder_paths
import comfy.sd
import comfy.utils
import comfy.model_management
import comfy.model_patcher
import nodes
from comfy.cli_args import args

from .nodes_int8_rocm import (
    Int8TensorwiseOps,
    INT8ModelPatcher,
    CONVROT_GROUP_SIZE,
)

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

_TE_FOLDER_KEYS = ("text_encoders", "clip")

_DTYPE_MAP = {
    "fp16": torch.float16,
    "bf16": torch.bfloat16,
    "fp32": torch.float32,
}


def _te_filename_list():
    files = []
    for key in _TE_FOLDER_KEYS:
        try:
            files += folder_paths.get_filename_list(key)
        except Exception:
            pass
    return sorted(set(files))


def _te_full_path(name):
    for key in _TE_FOLDER_KEYS:
        try:
            p = folder_paths.get_full_path(key, name)
            if p is not None:
                return p
        except Exception:
            pass
    return folder_paths.get_full_path("text_encoders", name)


def _prime_int8_ops(weight_dtype, on_the_fly_quantization, enable_convrot, excluded_names):
    Int8TensorwiseOps.excluded_names = list(excluded_names or [])
    Int8TensorwiseOps.dynamic_quantize = bool(on_the_fly_quantization)
    Int8TensorwiseOps.enable_convrot = bool(enable_convrot)
    Int8TensorwiseOps.use_triton = True
    Int8TensorwiseOps._is_prequantized = False
    Int8TensorwiseOps.compute_dtype = _DTYPE_MAP.get(str(weight_dtype), None)
    if hasattr(Int8TensorwiseOps, "_logged_otf"):
        delattr(Int8TensorwiseOps, "_logged_otf")


def _load_int8_clip(clip_paths, clip_type, weight_dtype, on_the_fly_quantization,
                    enable_convrot, excluded_names):
    _prime_int8_ops(weight_dtype, on_the_fly_quantization, enable_convrot, excluded_names)

    state_dicts = []
    for p in clip_paths:
        sd = comfy.utils.load_torch_file(p, safe_load=True)
        if "scaled_fp8" in sd:
            raise NotImplementedError(
                "This text encoder is scaled-FP8. INT8 custom ops can't be mixed "
                "with scaled-FP8 in the same encoder; use the stock CLIP loader "
                f"for this file:\n{p}"
            )
        state_dicts.append(sd)

    clip = comfy.sd.load_text_encoder_state_dicts(
        clip_type=clip_type,
        state_dicts=state_dicts,
        model_options={
            "custom_operations": Int8TensorwiseOps,
            "initial_device": comfy.model_management.text_encoder_offload_device(),
        },
        embedding_directory=folder_paths.get_folder_paths("embeddings"),
    )

    clip.patcher = INT8ModelPatcher.clone(clip.patcher)
    return clip


def _clip_type_from_str(type_str):
    return getattr(comfy.sd.CLIPType, str(type_str).upper(), comfy.sd.CLIPType.STABLE_DIFFUSION)


_TE_DEFAULT_EXCLUSIONS = [
    "shared", "embed_tokens", "token_embedding",
    "relative_attention_bias",
    "final_layer_norm", "encoder.final_layer_norm",
    "logit_scale", "text_projection",
]


# ---------------------------------------------------------------------------
# CLIPLoaderINT8ROCm 节点
# ---------------------------------------------------------------------------

class CLIPLoaderINT8ROCm:
    @classmethod
    def INPUT_TYPES(s):
        base = nodes.CLIPLoader.INPUT_TYPES()
        return {
            "required": {
                "clip_name": (_te_filename_list(),),
                "type": base["required"]["type"],
                "weight_dtype": (["default", "fp16", "bf16", "fp32"],),
                "on_the_fly_quantization": ("BOOLEAN", {"default": False}),
                "enable_convrot": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("CLIP",)
    FUNCTION = "load_clip"
    CATEGORY = "loaders"
    TITLE = "Load CLIP INT8 ROCm (W8A8)"
    DESCRIPTION = "XB INT8 ROCm: 加载INT8文本编码器"

    def load_clip(self, clip_name, type="wan", weight_dtype="default",
                  on_the_fly_quantization=False, enable_convrot=True):
        clip_path = _te_full_path(clip_name)
        clip_type = _clip_type_from_str(type)
        excl = _TE_DEFAULT_EXCLUSIONS if on_the_fly_quantization else []
        clip = _load_int8_clip(
            [clip_path], clip_type, weight_dtype, on_the_fly_quantization,
            enable_convrot, excl,
        )
        return (clip,)


# ---------------------------------------------------------------------------
# DualCLIPLoaderINT8ROCm 节点
# ---------------------------------------------------------------------------

class DualCLIPLoaderINT8ROCm(CLIPLoaderINT8ROCm):
    @classmethod
    def INPUT_TYPES(s):
        base = nodes.CLIPLoader.INPUT_TYPES()
        names = _te_filename_list()
        return {
            "required": {
                "clip_name1": (names,),
                "clip_name2": (names,),
                "type": base["required"]["type"],
                "weight_dtype": (["default", "fp16", "bf16", "fp32"],),
                "on_the_fly_quantization": ("BOOLEAN", {"default": False}),
                "enable_convrot": ("BOOLEAN", {"default": True}),
            },
        }

    TITLE = "Load Dual CLIP INT8 ROCm (W8A8)"
    DESCRIPTION = "XB INT8 ROCm: 加载双INT8文本编码器"

    def load_clip(self, clip_name1, clip_name2, type="flux", weight_dtype="default",
                  on_the_fly_quantization=False, enable_convrot=True):
        paths = [_te_full_path(clip_name1), _te_full_path(clip_name2)]
        clip_type = _clip_type_from_str(type)
        excl = _TE_DEFAULT_EXCLUSIONS if on_the_fly_quantization else []
        clip = _load_int8_clip(
            paths, clip_type, weight_dtype, on_the_fly_quantization,
            enable_convrot, excl,
        )
        return (clip,)


# ---------------------------------------------------------------------------
# INT8CLIPSaveROCm 节点
# ---------------------------------------------------------------------------

def _is_dynamic_lora_enabled():
    return bool(getattr(Int8TensorwiseOps, "dynamic_lora", False))


class INT8CLIPSaveROCm:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "clip": ("CLIP",),
            "filename_prefix": ("STRING", {"default": "int8_clip/INT8_CLIP"}),
        }, "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "loaders"
    DESCRIPTION = "XB INT8 ROCm: 保存INT8 CLIP模型"

    def save(self, clip, filename_prefix, prompt=None, extra_pnginfo=None):
        prompt_info = ""
        if prompt is not None:
            prompt_info = json.dumps(prompt)

        metadata = {}
        if not args.disable_metadata:
            metadata["format"] = "pt"
            metadata["prompt"] = prompt_info
            if extra_pnginfo is not None:
                for x in extra_pnginfo:
                    metadata[x] = json.dumps(extra_pnginfo[x])

        model_patcher = clip.patcher

        extra_keys = {}
        patched_modules = []
        patched_module_ids = set()

        def mark_module_for_direct_save(module):
            module_id = id(module)
            if module_id in patched_module_ids:
                return
            had_flag = hasattr(module, "comfy_patched_weights")
            old_flag = getattr(module, "comfy_patched_weights", False)
            patched_modules.append((module, had_flag, old_flag))
            patched_module_ids.add(module_id)
            module.comfy_patched_weights = True

        def module_has_int8_param(module):
            for attr in ("weight", "bias"):
                tensor = getattr(module, attr, None)
                if isinstance(tensor, torch.Tensor) and tensor.dtype == torch.int8:
                    return True
            return False

        def iter_model_modules(patcher):
            if hasattr(patcher, "model") and hasattr(patcher.model, "named_modules"):
                yield from patcher.model.named_modules()

        def materialize_int8_lora_patches(patcher):
            if _is_dynamic_lora_enabled() or not hasattr(patcher, "patch_weight_to_device"):
                return
            patches = getattr(patcher, "patches", None)
            if not patches:
                return
            load_device = getattr(patcher, "load_device", None)
            materialized = 0
            for name, module in iter_model_modules(patcher):
                if not getattr(module, "_is_quantized", False):
                    continue
                weight_key = name + ".weight" if name else "weight"
                if weight_key not in patches:
                    continue
                try:
                    patcher.patch_weight_to_device(weight_key, device_to=load_device)
                    if hasattr(module, "weight_lowvram_function"):
                        module.weight_lowvram_function = None
                    materialized += 1
                except Exception as e:
                    logging.warning(f"XB INT8 CLIP ROCm: failed to materialize LoRA for {weight_key}: {e}")
            if materialized > 0:
                logging.info(f"XB INT8 CLIP ROCm: materialized {materialized} INT8 LoRA patched weights.")

        finalize_fn = getattr(model_patcher, "finalize_pending_int8", None)
        if finalize_fn is not None:
            finalize_fn()

        try:
            comfy.model_management.load_models_gpu([model_patcher], force_full_load=True)
        except Exception as e:
            logging.warning(f"XB INT8 CLIP ROCm: full-load pre-pass failed ({e}), falling back.")
            try:
                comfy.model_management.load_models_gpu([model_patcher])
            except Exception as e2:
                logging.warning(f"XB INT8 CLIP ROCm: load_models_gpu fallback also failed ({e2}).")

        if finalize_fn is not None:
            finalize_fn()

        materialize_int8_lora_patches(model_patcher)

        for name, module in iter_model_modules(model_patcher):
            if module_has_int8_param(module):
                mark_module_for_direct_save(module)

            if getattr(module, "_is_quantized", False):
                use_convrot = bool(getattr(module, "_use_convrot", False))
                quant_conf = {"format": "int8_tensorwise", "convrot": use_convrot}
                if use_convrot:
                    quant_conf["convrot_groupsize"] = int(
                        getattr(module, "_convrot_groupsize", CONVROT_GROUP_SIZE))
                quant_conf["per_row"] = bool(getattr(module, "_is_per_row", False))

                prefix = name + "." if name else ""
                extra_keys[prefix + "comfy_quant"] = torch.tensor(
                    list(json.dumps(quant_conf).encode('utf-8')), dtype=torch.uint8)

                if getattr(module, "_weight_scale_scalar", None) is not None:
                    extra_keys[prefix + "weight_scale"] = torch.tensor(module._weight_scale_scalar)

                mark_module_for_direct_save(module)

        original_lazy_new = comfy.model_patcher.LazyCastingParam.__new__
        original_lazy_piece_new = comfy.model_patcher.LazyCastingParamPiece.__new__

        def lazy_casting_param_new(cls, model, key, tensor):
            requires_grad = tensor.is_floating_point() or tensor.is_complex()
            return torch.nn.Parameter.__new__(cls, tensor, requires_grad=requires_grad)

        def lazy_casting_param_piece_new(cls, caster, state_dict_key, tensor):
            requires_grad = tensor.is_floating_point() or tensor.is_complex()
            return torch.nn.Parameter.__new__(cls, tensor, requires_grad=requires_grad)

        try:
            comfy.model_patcher.LazyCastingParam.__new__ = staticmethod(lazy_casting_param_new)
            comfy.model_patcher.LazyCastingParamPiece.__new__ = staticmethod(lazy_casting_param_piece_new)
            clip.load_model()
            clip_sd = clip.state_dict_for_saving()
            for k in extra_keys:
                clip_sd[k] = extra_keys[k]
        finally:
            comfy.model_patcher.LazyCastingParam.__new__ = original_lazy_new
            comfy.model_patcher.LazyCastingParamPiece.__new__ = original_lazy_piece_new
            for module, had_flag, old_flag in patched_modules:
                if had_flag:
                    module.comfy_patched_weights = old_flag
                else:
                    try:
                        delattr(module, "comfy_patched_weights")
                    except AttributeError:
                        pass

        # 动态获取子模块前缀
        try:
            child_prefixes = [f"{n}." for n, _ in clip.cond_stage_model.named_children()]
        except Exception:
            child_prefixes = []
        legacy_prefixes = ["clip_l.", "clip_g.", "clip_h.", "t5xxl.", "pile_t5xl.", "mt5xl.",
                           "umt5xxl.", "t5base.", "gemma2_2b.", "llama.", "hydit_clip."]
        seen_prefixes = set()
        ordered_prefixes = []
        for p in child_prefixes + legacy_prefixes + [""]:
            if p not in seen_prefixes:
                seen_prefixes.add(p)
                ordered_prefixes.append(p)

        for prefix in ordered_prefixes:
            k = list(filter(lambda a: a.startswith(prefix), clip_sd.keys()))
            current_clip_sd = {}
            for x in k:
                current_clip_sd[x] = clip_sd.pop(x)
            if len(current_clip_sd) == 0:
                continue

            p = prefix[:-1]
            replace_prefix = {}
            filename_prefix_ = filename_prefix
            if len(p) > 0:
                filename_prefix_ = "{}_{}".format(filename_prefix_, p)
                replace_prefix[prefix] = ""
            replace_prefix["transformer."] = ""

            full_output_folder, filename, counter, subfolder, filename_prefix_ = \
                folder_paths.get_save_image_path(filename_prefix_, self.output_dir)

            output_checkpoint = f"{filename}_{counter:05}_.safetensors"
            output_checkpoint = os.path.join(full_output_folder, output_checkpoint)

            current_clip_sd = comfy.utils.state_dict_prefix_replace(current_clip_sd, replace_prefix)

            # 反转 Qwen3-VL 的加载时重映射
            has_bare_visual = any(kk.startswith("visual.") for kk in current_clip_sd)
            if has_bare_visual:
                reverse_remap = {}
                if any(kk.startswith("model.lm_head.") for kk in current_clip_sd):
                    reverse_remap["model.lm_head."] = "lm_head."
                reverse_remap["model."] = "model.language_model."
                reverse_remap["visual."] = "model.visual."
                current_clip_sd = comfy.utils.state_dict_prefix_replace(current_clip_sd, reverse_remap)

            for kk in current_clip_sd:
                t = current_clip_sd[kk]
                if isinstance(t, torch.Tensor) and not t.is_contiguous():
                    current_clip_sd[kk] = t.contiguous()

            comfy.utils.save_torch_file(current_clip_sd, output_checkpoint, metadata=metadata)

        return {}
