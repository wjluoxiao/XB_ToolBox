"""
XB-ToolBox ROCm 辅助模块
========================
仅保留底层辅助函数 + 显存清理节点。
所有采样器和VAE解码/编码节点已迁移至 nodes_vanilla_wrappers.py（原版优化）。
"""

import torch, gc, os, sys, time
import comfy.model_management as mm
import nodes


class AnyType(str):
    """哑类型——接受任意连线，仅用于串联节点防止误删"""
    def __eq__(self, _) -> bool: return True
    def __ne__(self, __value: object) -> bool: return False

_any = AnyType("*")


_AMD_ARCH_DB = {
    "gfx1201": {"name": "RDNA4 (Navi 48 XT)",     "tile": 768, "gen": "RDNA4",   "fp16_ok": True,  "fp8_ok": True},
    "gfx1200": {"name": "RDNA4 (Navi 48)",        "tile": 640, "gen": "RDNA4",   "fp16_ok": True,  "fp8_ok": True},
    "gfx1151": {"name": "RDNA3.5 (Strix Halo)",   "tile": 768, "gen": "RDNA3.5", "fp16_ok": True},
    "gfx1150": {"name": "RDNA3.5 (Strix Point)",  "tile": 384, "gen": "RDNA3.5", "fp16_ok": True},
    "gfx1103": {"name": "RDNA3 (Phoenix iGPU)",   "tile": 256, "gen": "RDNA3",   "fp16_ok": True},
    "gfx1102": {"name": "RDNA3 (Navi 33)",        "tile": 384, "gen": "RDNA3",   "fp16_ok": True},
    "gfx1101": {"name": "RDNA3 (Navi 32)",        "tile": 512, "gen": "RDNA3",   "fp16_ok": True},
    "gfx1100": {"name": "RDNA3 (Navi 31)",        "tile": 640, "gen": "RDNA3",   "fp16_ok": True},
    "gfx1037": {"name": "RDNA2 (Mendocino iGPU)",  "tile": 64,  "gen": "RDNA2",   "fp16_ok": False},
    "gfx1036": {"name": "RDNA2 (Raphael iGPU)",    "tile": 64,  "gen": "RDNA2",   "fp16_ok": False},
    "gfx1035": {"name": "RDNA2 (Rembrandt iGPU)",  "tile": 128, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1034": {"name": "RDNA2 (Navi 24)",         "tile": 128, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1032": {"name": "RDNA2 (Navi 23)",         "tile": 256, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1031": {"name": "RDNA2 (Navi 22)",         "tile": 320, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1030": {"name": "RDNA2 (Navi 21)",         "tile": 384, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1012": {"name": "RDNA1 (Navi 14)",         "tile": 128, "gen": "RDNA1",   "fp16_ok": False},
    "gfx1011": {"name": "RDNA1 (Navi 12)",         "tile": 192, "gen": "RDNA1",   "fp16_ok": False},
    "gfx1010": {"name": "RDNA1 (Navi 10)",         "tile": 256, "gen": "RDNA1",   "fp16_ok": False},
    "gfx942":  {"name": "CDNA3 (MI300X)",          "tile": 512, "gen": "CDNA3",   "fp16_ok": True,  "fp8_ok": True},
    "gfx90a":  {"name": "CDNA2 (MI250X)",          "tile": 512, "gen": "CDNA2",   "fp16_ok": True},
    "gfx908":  {"name": "CDNA (MI100)",            "tile": 256, "gen": "CDNA",    "fp16_ok": True},
    "gfx906":  {"name": "Vega (Radeon VII)",       "tile": 256, "gen": "Vega",    "fp16_ok": False},
}


def _lookup(arch: str):
    if not arch: return None
    if arch in _AMD_ARCH_DB: return _AMD_ARCH_DB[arch]
    for k in sorted(_AMD_ARCH_DB, key=len, reverse=True):
        if arch.startswith(k): return _AMD_ARCH_DB[k]
    return None


def is_rocm() -> bool:
    return torch.cuda.is_available() and hasattr(torch.version, "hip") and torch.version.hip


def get_arch() -> str:
    if not is_rocm(): return "nvidia"
    try:
        raw = torch.cuda.get_device_properties(0).gcnArchName
        return raw.split(":")[0] if raw else "unknown"
    except: return "unknown"


def gpu_info() -> dict:
    arch = get_arch()
    d = {"arch": arch, "amd": is_rocm(), "name": "?", "gen": "?", "tile": 256, "gb": 0}
    if is_rocm():
        e = _lookup(arch)
        if e: d.update(e)
        try: d["gb"] = torch.cuda.get_device_properties(0).total_memory / 1024**3
        except: pass
    else:
        try:
            d["name"] = torch.cuda.get_device_name(0)
            d["gb"] = torch.cuda.get_device_properties(0).total_memory / 1024**3
        except: pass
    return d


def _read_env_flag(name: str) -> bool | None:
    v = os.environ.get(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):  return True
    if v in ("0", "false", "no", "off"): return False
    return None


def _has_comfy_arg(flag: str) -> bool:
    return flag in sys.argv


def tune():
    if not is_rocm(): return
    if _has_comfy_arg("--cpu"): return
    g = gpu_info()
    torch.set_float32_matmul_precision("high")
    if _has_comfy_arg("--force-fp32") or _has_comfy_arg("--fp32-unet") or _has_comfy_arg("--fp64-unet"):
        can_fp16 = False
    elif _has_comfy_arg("--force-fp16") or _has_comfy_arg("--fp16-unet"):
        can_fp16 = g.get("fp16_ok", False)
    elif (user_fp16 := _read_env_flag("XB_FP16_ACCUM")) is not None:
        can_fp16 = user_fp16
    else:
        can_fp16 = g.get("fp16_ok", False)
    torch.backends.cuda.matmul.allow_fp16_accumulation = can_fp16
    if hasattr(torch.backends.cuda.matmul, "allow_bf16_reduced_precision_reduction"):
        torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = can_fp16


def _sdp_context():
    g = gpu_info()
    gen = g.get("gen", "")
    if gen in ("RDNA3", "RDNA3.5", "RDNA4", "CDNA2", "CDNA3"):
        return torch.backends.cuda.sdp_kernel(enable_flash=True, enable_math=False, enable_mem_efficient=True)
    else:
        return torch.backends.cuda.sdp_kernel(enable_flash=False, enable_math=True, enable_mem_efficient=True)


def _vae_force_fp32() -> bool:
    if not is_rocm(): return False
    if _has_comfy_arg("--cpu-vae"): return False
    if _has_comfy_arg("--force-fp32") or _has_comfy_arg("--fp32-vae"): return True
    if _has_comfy_arg("--fp16-vae") or _has_comfy_arg("--bf16-vae"): return False
    user_fp16 = _read_env_flag("XB_FP16_VAE")
    if user_fp16 is not None: return not user_fp16
    g = gpu_info()
    return not g.get("fp16_ok", False)


def _is_ltx_vae(vae) -> bool:
    return hasattr(vae, "downscale_index_formula")


def _get_spatial_compression(vae) -> int:
    for attr in ("spatial_compression_decode", "spacial_compression_decode"):
        if hasattr(vae, attr):
            val = getattr(vae, attr)
            return val() if callable(val) else val
    if hasattr(vae, "downscale_index_formula"):
        val = vae.downscale_index_formula
        scales = val() if callable(val) else val
        if isinstance(scales, (tuple, list)) and len(scales) >= 2:
            return scales[1]
    if hasattr(vae, "downscale_ratio"):
        val = vae.downscale_ratio
        return val() if callable(val) else val
    return 8


def memclr(sync: bool = True):
    if not torch.cuda.is_available(): return
    if sync: torch.cuda.synchronize()
    torch.cuda.empty_cache()
    gc.collect()
    if hasattr(torch.cuda, "ipc_collect"): torch.cuda.ipc_collect()


def memstat() -> dict:
    if not torch.cuda.is_available(): return {}
    return {
        "alloc": torch.cuda.memory_allocated(0) / 1024**3,
        "rsvd":  torch.cuda.memory_reserved(0) / 1024**3,
        "total": torch.cuda.get_device_properties(0).total_memory / 1024**3,
    }


def _banner(title, g):
    print(f"\n{'='*50}\n  {title}\n  GPU: {g['name']} | {g['gen']} | {g['gb']:.1f}GB\n{'='*50}")


def _vae_tune_light():
    if not is_rocm(): return
    if _has_comfy_arg("--cpu"): return
    g = gpu_info()
    if _has_comfy_arg("--force-fp32") or _has_comfy_arg("--fp32-unet") or _has_comfy_arg("--fp64-unet"):
        can_fp16 = False
    elif _has_comfy_arg("--force-fp16") or _has_comfy_arg("--fp16-unet"):
        can_fp16 = g.get("fp16_ok", False)
    elif (user_fp16 := _read_env_flag("XB_FP16_ACCUM")) is not None:
        can_fp16 = user_fp16
    else:
        can_fp16 = g.get("fp16_ok", False)
    torch.backends.cuda.matmul.allow_fp16_accumulation = can_fp16


def _predecode_cleanup(level: str):
    if level == "不做任何清理": return
    if not torch.cuda.is_available(): return
    if level == "单次缓存清理":
        torch.cuda.empty_cache()
    elif level == "双次缓存清理":
        torch.cuda.empty_cache()
        mm.soft_empty_cache()
        torch.cuda.empty_cache()
    elif level == "卸载显存模型":
        mm.unload_all_models()
        mm.soft_empty_cache()
        torch.cuda.empty_cache()
        torch.cuda.empty_cache()


def _do_cleanup(stage: str, level: str):
    if level == "不做任何清理": return
    sync = (stage == "post")
    if level == "单次缓存清理":
        memclr(sync)
    elif level == "双次缓存清理":
        memclr(sync)
        mm.soft_empty_cache()
        memclr(sync)
        gc.collect()
    elif level == "卸载显存模型":
        mm.unload_all_models()
        mm.soft_empty_cache()
        memclr(sync)
        memclr(sync)
        gc.collect()


def _even_chunks(total: int, chunk: int):
    if total <= chunk: return [(0, total)]
    n_full = total // chunk
    remainder = total % chunk
    if remainder == 0:
        return [(i * chunk, (i + 1) * chunk) for i in range(n_full)]
    if remainder < chunk // 2:
        chunks = [(i * chunk, (i + 1) * chunk) for i in range(n_full - 1)]
        chunks.append(((n_full - 1) * chunk, total))
    else:
        chunks = [(i * chunk, min((i + 1) * chunk, total)) for i in range(n_full + 1)]
    return chunks


# ============================================================
# XB_ROCmMemCleaner - 显存清理
# ============================================================
class XB_ROCmMemCleaner:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "mode": (["单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "双次缓存清理"}),
            },
            "optional": {
                "anything": (_any, {}),
            },
        }
    RETURN_TYPES = (_any,)
    RETURN_NAMES = ("pass-through",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"
    OUTPUT_NODE = True

    def go(self, mode, anything=None):
        g = gpu_info(); tune()
        before = memstat()
        if mode == "卸载显存模型":
            mm.unload_all_models()
            mm.soft_empty_cache()
        memclr(sync=True)
        if mode in ("双次缓存清理", "卸载显存模型"):
            memclr(sync=True)
            gc.collect()
        after = memstat()
        freed_alloc = before["alloc"] - after["alloc"] if before and after else 0
        freed_rsvd  = before["rsvd"]  - after["rsvd"]  if before and after else 0
        print(f"\033[92m\U0001f9f9 {mode} | {g['name']} {g['gb']:.1f}GB | freed {freed_alloc:.2f}+{freed_rsvd:.2f}GB\033[0m")
        return (anything,)


__all__ = ["XB_ROCmMemCleaner"]
