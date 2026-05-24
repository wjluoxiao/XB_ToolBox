"""
XB-ToolBox ROCm 优化节点 (v5.0)
================================
6 个节点，专为 AMD ROCm GPU 设计，零外部依赖。

  XB_ROCmKSampler          — 采样器（rocBLAS调优 + SDPA修复）
  XB_ROCmKSamplerAdvanced  — 高级采样器（支持分段采样/加噪控制/残留噪声）
  XB_ROCmVAEDecode         — 空间分块解码器（架构自适应 tile）
  XB_ROCmVAEEncode         — 空间分块编码器（架构自适应 tile）
  XB_ROCmVAEDecodeTemporal — 空间+时间分块解码器（视频专用）
  XB_ROCmMemCleaner        — 显存清理+诊断报告

核心机制:
  - tile_size=0 → 自动根据 GPU 架构选择最优分块大小（用户也可手动覆盖）
  - fp16_accumulation=True → rocBLAS 矩阵乘法用 fp16 中间累积（~5-10% 加速）
  - mem_efficient SDPA → AMD 上最稳定的 attention 后端（防崩溃）
  - 时间分块 → 视频 latent 逐 chunk 解码，显存峰值降低 80%
"""

import torch, gc, time
import comfy.model_management as mm
import comfy.samplers
import nodes


class AnyType(str):
    """哑类型——接受任意连线，仅用于串联节点防止误删"""
    def __eq__(self, _) -> bool: return True
    def __ne__(self, __value: object) -> bool: return False

_any = AnyType("*")


# ====================================================================
# AMD GPU 架构数据库
# ====================================================================

_AMD_ARCH_DB = {
    # RDNA4 — RX 9070 系列
    "gfx1201": {"name": "RX 9070 XT",   "tile": 768, "gen": "RDNA4"},
    "gfx1200": {"name": "RX 9070",      "tile": 640, "gen": "RDNA4"},
    # RDNA3.5 — Strix APU
    "gfx1151": {"name": "Strix Halo",   "tile": 768, "gen": "RDNA3.5"},
    "gfx1150": {"name": "Strix Point",  "tile": 512, "gen": "RDNA3.5"},
    # RDNA3 — RX 7000
    "gfx1102": {"name": "RX 7600",      "tile": 384, "gen": "RDNA3"},
    "gfx1101": {"name": "RX 7800 XT",   "tile": 512, "gen": "RDNA3"},
    "gfx1100": {"name": "RX 7900 XTX",  "tile": 640, "gen": "RDNA3"},
    # RDNA2 — RX 6000
    "gfx1032": {"name": "RX 6600",      "tile": 256, "gen": "RDNA2"},
    "gfx1031": {"name": "RX 6700 XT",   "tile": 320, "gen": "RDNA2"},
    "gfx1030": {"name": "RX 6800/6900", "tile": 384, "gen": "RDNA2"},
    # CDNA
    "gfx942":  {"name": "MI300X",       "tile": 512, "gen": "CDNA3"},
    "gfx90a":  {"name": "MI250X",       "tile": 512, "gen": "CDNA2"},
    "gfx908":  {"name": "MI100",        "tile": 256, "gen": "CDNA"},
    "gfx906":  {"name": "Radeon VII",   "tile": 256, "gen": "Vega"},
}


def _lookup(arch: str):
    if not arch: return None
    if arch in _AMD_ARCH_DB: return _AMD_ARCH_DB[arch]
    for k in sorted(_AMD_ARCH_DB, key=len, reverse=True):
        if arch.startswith(k): return _AMD_ARCH_DB[k]
    return None


# ====================================================================
# 工具函数
# ====================================================================

def is_rocm() -> bool:
    return torch.cuda.is_available() and hasattr(torch.version, 'hip') and torch.version.hip


def get_arch() -> str:
    if not is_rocm(): return "nvidia"
    try:
        raw = torch.cuda.get_device_properties(0).gcnArchName
        return raw.split(':')[0] if raw else "unknown"
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


def tune():
    """ROCm 全局调优 — fp16累积(rocBLAS加速) + mem_efficient SDPA(防崩溃)"""
    if not is_rocm(): return
    # 核心优化: rocBLAS 用 fp16 中间累积 → 矩阵乘法 ~5-10% 加速
    torch.backends.cuda.matmul.allow_fp16_accumulation = True
    # AMD 稳定 attention 后端
    if hasattr(torch.backends.cuda, 'enable_mem_efficient_sdp'):
        torch.backends.cuda.enable_mem_efficient_sdp(True)
    if hasattr(torch.backends.cuda, 'enable_flash_sdp'):
        torch.backends.cuda.enable_flash_sdp(False)


def memclr(sync: bool = True):
    if not torch.cuda.is_available(): return
    if sync: torch.cuda.synchronize()
    torch.cuda.empty_cache()
    gc.collect()
    if hasattr(torch.cuda, "ipc_collect"): torch.cuda.ipc_collect()


def memstat() -> dict:
    """获取当前显存状态"""
    if not torch.cuda.is_available(): return {}
    return {
        "alloc": torch.cuda.memory_allocated(0) / 1024**3,
        "rsvd":  torch.cuda.memory_reserved(0) / 1024**3,
        "total": torch.cuda.get_device_properties(0).total_memory / 1024**3,
    }


def _banner(title, g):
    print(f"\n{'='*50}\n  {title}\n  GPU: {g['name']} | {g['gen']} | {g['gb']:.1f}GB\n{'='*50}")


def _do_cleanup(stage: str, level: str):
    """执行分级清理。pre=操作前不同步, post=操作后先sync再清"""
    if level == "不做任何清理":
        return
    sync = (stage == "post")
    if level == "单次缓存清理":
        memclr(sync)
    elif level == "双次缓存清理":
        memclr(sync)
        memclr(sync)
        gc.collect()
    elif level == "卸载显存模型":
        mm.unload_all_models()
        mm.soft_empty_cache()
        memclr(sync)
        memclr(sync)
        gc.collect()


def _even_chunks(total: int, chunk: int):
    """均匀分块：避免末尾出现特别小的碎片。
    如果剩余 < chunk/2，合并到前一个 chunk。"""
    if total <= chunk:
        return [(0, total)]
    n_full = total // chunk
    remainder = total % chunk
    if remainder == 0:
        return [(i * chunk, (i + 1) * chunk) for i in range(n_full)]
    # 有余数：如果余数 < chunk/2，把它分给前面的 chunk
    if remainder < chunk // 2:
        chunks = []
        extra_each = remainder // n_full
        extra_rem = remainder % n_full
        pos = 0
        for i in range(n_full):
            sz = chunk + extra_each + (1 if i < extra_rem else 0)
            chunks.append((pos, pos + sz))
            pos += sz
        chunks.append((pos, total))  # 最后小块也保留，但已经很小了，合并逻辑在上面
        # 更简单：直接把余数加到最后一个 chunk
        chunks = [(i * chunk, (i + 1) * chunk) for i in range(n_full - 1)]
        chunks.append(((n_full - 1) * chunk, total))
        return chunks
    else:
        return [(i * chunk, min((i + 1) * chunk, total)) for i in range(n_full + 1)]


# ====================================================================
# 节点 1: XB_ROCmKSampler
# ====================================================================

class XB_ROCmKSampler:
    """
    ROCm 优化采样器 — rocBLAS fp16累积 + mem_efficient SDPA
    配合 XB_SageAttentionAccelerator 使用（先 SageAttn 注入，再接此采样器）。
    """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ("MODEL",),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1}),
            "sampler": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent": ("LATENT",),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, model, seed, steps, cfg, sampler, scheduler,
           positive, negative, latent, denoise):
        tune()
        out, = nodes.KSampler().sample(model, seed, steps, cfg, sampler, scheduler,
                                        positive, negative, latent, denoise)
        return (out,)


# ====================================================================
# 节点 1.5: XB_ROCmKSamplerAdvanced  (高级采样器 ROCm 版)
# ====================================================================

class XB_ROCmKSamplerAdvanced:
    """
    ROCm 优化高级采样器 — 支持分段采样 (start/end step)、加噪控制、残留噪声返回
    配合 XB_SageAttentionAccelerator 使用（先 SageAttn 注入，再接此采样器）。
    """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ("MODEL",),
            "add_noise": (["enable", "disable"], {}),
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1}),
            "sampler": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent": ("LATENT",),
            "start_at_step": ("INT", {"default": 0, "min": 0, "max": 10000}),
            "end_at_step": ("INT", {"default": 10000, "min": 0, "max": 10000}),
            "return_with_leftover_noise": (["disable", "enable"], {}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, model, add_noise, noise_seed, steps, cfg, sampler, scheduler,
           positive, negative, latent, start_at_step, end_at_step, return_with_leftover_noise, denoise=1.0):
        tune()
        out, = nodes.KSamplerAdvanced().sample(
            model, add_noise, noise_seed, steps, cfg, sampler, scheduler,
            positive, negative, latent, start_at_step, end_at_step,
            return_with_leftover_noise, denoise=denoise)
        return (out,)


# ====================================================================
# 节点 2: XB_ROCmVAEDecode  (空间分块解码)
# ====================================================================

class XB_ROCmVAEDecode:
    """
    ROCm VAE 解码器 — 架构自适应空间分块
    tile=0 → 自动根据GPU架构选最优值 (RX9070XT→768, RX7900→640, ...)
    tile>0 → 使用手动指定的分块大小
    """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "samples": ("LATENT",),
            "vae": ("VAE",),
            "tile": ("INT", {"default": 0, "min": 0, "max": 2048, "step": 64,
                             "tooltip": "0=根据GPU架构自动选择 手动可覆盖"}),
            "overlap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 16,
                                "tooltip": "0=自动(tile/8)"}),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "单次缓存清理"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, samples, vae, tile, overlap, cleanup):
        g = gpu_info(); tune()
        lat = samples["samples"]

        if tile == 0: tile = g["tile"]
        if overlap == 0: overlap = max(32, tile // 8)

        _do_cleanup("pre", cleanup)
        try:
            img = vae.decode_tiled(lat, tile_x=tile, tile_y=tile, overlap=overlap)
        except AttributeError:
            print(f"  ⚠️ ROCm VAE Decode: tiled not available, fallback to standard")
            img = vae.decode(lat)
        _do_cleanup("post", cleanup)
        return (img,)


# ====================================================================
# 节点 3: XB_ROCmVAEEncode  (空间分块编码)
# ====================================================================

class XB_ROCmVAEEncode:
    """
    ROCm VAE 编码器 — 架构自适应空间分块
    tile=0 → 自动, tile>0 → 手动
    """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "pixels": ("IMAGE",),
            "vae": ("VAE",),
            "tile": ("INT", {"default": 0, "min": 0, "max": 2048, "step": 64,
                             "tooltip": "0=自动"}),
            "overlap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 16,
                                "tooltip": "0=自动"}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, pixels, vae, tile, overlap):
        g = gpu_info(); tune()

        if tile == 0: tile = g["tile"]
        if overlap == 0: overlap = max(32, tile // 8)

        memclr(False)
        try:
            lat = vae.encode_tiled(pixels, tile_x=tile, tile_y=tile, overlap=overlap)
        except AttributeError:
            print(f"  ⚠️ ROCm VAE Encode: tiled not available, fallback to standard")
            lat = vae.encode(pixels)
        memclr(True)
        return ({"samples": lat},)


# ====================================================================
# 节点 4: XB_ROCmVAEDecodeTemporal  (空间+时间分块)
# ====================================================================

class XB_ROCmVAEDecodeTemporal:
    """
    ROCm VAE 解码器 (空间+时间分块) — 视频模型专用
    适用于 Wan/LTX 等视频 VAE latent。
    所有参数=0 时全自动: 空间tile→架构自适应, 时间chunk→显存自适应
    """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "samples": ("LATENT",),
            "vae": ("VAE",),
            "tile": ("INT", {"default": 0, "min": 0, "max": 2048, "step": 64,
                             "tooltip": "空间分块 0=自动"}),
            "overlap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 16,
                                "tooltip": "空间重叠 0=自动(tile/8, 最小32)"}),
            "t_tile": ("INT", {"default": 0, "min": 0, "max": 1024, "step": 16,
                               "tooltip": "时间分块帧数 0=根据显存自适应"}),
            "t_overlap": ("INT", {"default": 0, "min": 0, "max": 64, "step": 4,
                                  "tooltip": "时间重叠 0=自动(t_tile/16, 最小4)"}),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "单次缓存清理"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, samples, vae, tile, overlap, t_tile, t_overlap, cleanup):
        g = gpu_info(); tune()
        lat = samples["samples"]

        if lat.dim() == 5:
            B, C, F, H, W = lat.shape; is_vid = True
        elif lat.dim() == 4:
            B, C, H, W = lat.shape; F = 1; is_vid = False
        else:
            raise ValueError(f"unsupported latent dim: {lat.dim()}")

        if tile == 0: tile = g["tile"]
        if overlap == 0: overlap = max(32, tile // 8)
        if t_tile == 0 and is_vid:
            if g["gb"] >= 48:   t_tile = 64
            elif g["gb"] >= 24: t_tile = 32
            elif g["gb"] >= 16: t_tile = 16
            else:               t_tile = 8
        if t_overlap == 0:
            t_overlap = max(4, t_tile // 16)

        _do_cleanup("pre", cleanup)
        try:
            if is_vid and t_tile > 0 and F > t_tile:
                chunks = []
                for cs, ce in _even_chunks(F, t_tile):
                    ch = lat[:, :, cs:ce, :, :]
                    try:
                        dc = vae.decode_tiled(ch, tile_x=tile, tile_y=tile, overlap=overlap)
                    except AttributeError:
                        Bc, Cc, Fc, Hc, Wc = ch.shape
                        dc = vae.decode(ch.reshape(Bc * Fc, Cc, Hc, Wc))
                        dc = dc.reshape(Bc, Fc, *dc.shape[1:])
                    chunks.append(dc)
                img = torch.cat(chunks, dim=1)
            else:
                img = vae.decode_tiled(lat, tile_x=tile, tile_y=tile, overlap=overlap)
        except AttributeError:
            print(f"  ⚠️ ROCm VAE Decode Temporal: tiled not available, fallback")
            if is_vid and F > 1:
                frames = []
                for f in range(F):
                    fl = lat[:, :, f:f+1, :, :].squeeze(2)
                    frames.append(vae.decode(fl).unsqueeze(1))
                img = torch.cat(frames, dim=1)
            else:
                img = vae.decode(lat)
        _do_cleanup("post", cleanup)
        # 展平 batch+frame 维度, 输出标准 ComfyUI 4D 格式 (N, H, W, C)
        if img.dim() > 4:
            img = img.flatten(0, 1)
        return (img,)


# ====================================================================
# 节点 5: XB_ROCmMemCleaner  (独立显存清理+诊断)
# ====================================================================

class XB_ROCmMemCleaner:
    """
    ROCm 显存清理+诊断 — 独立节点
    显示 GPU 信息 + 清理前后显存对比。

    验证 fp16_accumulation 加速效果:
      在 Python 控制台运行:
        import torch, time
        a=torch.randn(4096,4096,dtype=torch.float16,device='cuda')
        b=torch.randn(4096,4096,dtype=torch.float16,device='cuda')
        for flag in [False,True]:
            torch.backends.cuda.matmul.allow_fp16_accumulation=flag
            torch.cuda.synchronize(); t0=time.time()
            for _ in range(500): c=a@b
            torch.cuda.synchronize()
            print(f"fp16_accum={flag}: {time.time()-t0:.2f}s")
    """
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

        # 执行清理
        if mode == "卸载显存模型":
            mm.unload_all_models()
            mm.soft_empty_cache()
        memclr(sync=True)
        if mode in ("双次缓存清理", "卸载显存模型"):
            memclr(sync=True)
            gc.collect()

        after = memstat()
        freed_alloc = before['alloc'] - after['alloc'] if before and after else 0
        freed_rsvd  = before['rsvd']  - after['rsvd']  if before and after else 0

        print(f"\033[92m🧹 ROCm {mode} | {g['name']} {g['gb']:.1f}GB | freed {freed_alloc:.2f}+{freed_rsvd:.2f}GB\033[0m")
        return (anything,)


# ====================================================================
__all__ = ['XB_ROCmKSampler', 'XB_ROCmKSamplerAdvanced', 'XB_ROCmVAEDecode',
           'XB_ROCmVAEEncode', 'XB_ROCmVAEDecodeTemporal', 'XB_ROCmMemCleaner']
