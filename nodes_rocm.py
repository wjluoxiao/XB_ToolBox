"""
XB-ToolBox ROCm 优化节点 (v5.0)
================================
8 个节点，专为 AMD ROCm GPU 设计，零外部依赖。

  XB_ROCmKSampler              — 采样器（rocBLAS调优 + SDPA修复）
  XB_ROCmKSamplerAdvanced      — 高级采样器（支持分段采样/加噪控制/残留噪声）
  XB_ROCmSamplerCustom         — 自定义采样器（模块化调度器/采样器/引导器）
  XB_ROCmSamplerCustomAdvanced — 自定义高级采样器（完全模块化 + 独立噪波注入）
  XB_ROCmVAEDecode             — 空间分块解码器（架构自适应 tile）
  XB_ROCmVAEEncode             — 空间分块编码器（架构自适应 tile）
  XB_ROCmVAEDecodeTemporal     — 空间+时间分块解码器（视频专用）
  XB_ROCmMemCleaner            — 显存清理+诊断报告

核心机制:
  - tile_size=0 → 自动根据 GPU 架构选择最优分块大小（用户也可手动覆盖）
  - fp16_accumulation=True → rocBLAS 矩阵乘法用 fp16 中间累积（~5-10% 加速）
  - mem_efficient SDPA → AMD 上最稳定的 attention 后端（防崩溃）
  - 时间分块 → 视频 latent 逐 chunk 解码，显存峰值降低 80%
"""

import torch, gc, os, sys, time
import comfy.model_management as mm
import comfy.samplers
import comfy.sample
import comfy.utils
import comfy.nested_tensor
import latent_preview
import nodes


class AnyType(str):
    """哑类型——接受任意连线，仅用于串联节点防止误删"""
    def __eq__(self, _) -> bool: return True
    def __ne__(self, __value: object) -> bool: return False

_any = AnyType("*")


_AMD_ARCH_DB = {
    # ═══════════ RDNA4 — RX 9000 ═══════════
    "gfx1201": {"name": "RDNA4 (Navi 48 XT)",     "tile": 768, "gen": "RDNA4",   "fp16_ok": True,  "fp8_ok": True},
    "gfx1200": {"name": "RDNA4 (Navi 48)",        "tile": 640, "gen": "RDNA4",   "fp16_ok": True,  "fp8_ok": True},
    # ═══════════ RDNA3.5 — Strix APU ═══════════
    "gfx1151": {"name": "RDNA3.5 (Strix Halo)",   "tile": 768, "gen": "RDNA3.5", "fp16_ok": True},
    "gfx1150": {"name": "RDNA3.5 (Strix Point)",  "tile": 384, "gen": "RDNA3.5", "fp16_ok": True},
    # ═══════════ RDNA3 — RX 7000 + Phoenix ═══════════
    "gfx1103": {"name": "RDNA3 (Phoenix iGPU)",   "tile": 256, "gen": "RDNA3",   "fp16_ok": True},
    "gfx1102": {"name": "RDNA3 (Navi 33)",        "tile": 384, "gen": "RDNA3",   "fp16_ok": True},
    "gfx1101": {"name": "RDNA3 (Navi 32)",        "tile": 512, "gen": "RDNA3",   "fp16_ok": True},
    "gfx1100": {"name": "RDNA3 (Navi 31)",        "tile": 640, "gen": "RDNA3",   "fp16_ok": True},
    # ═══════════ RDNA2 — RX 6000 + 集显 ═══════════
    "gfx1037": {"name": "RDNA2 (Mendocino iGPU)",  "tile": 64,  "gen": "RDNA2",   "fp16_ok": False},
    "gfx1036": {"name": "RDNA2 (Raphael iGPU)",    "tile": 64,  "gen": "RDNA2",   "fp16_ok": False},
    "gfx1035": {"name": "RDNA2 (Rembrandt iGPU)",  "tile": 128, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1034": {"name": "RDNA2 (Navi 24)",         "tile": 128, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1032": {"name": "RDNA2 (Navi 23)",         "tile": 256, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1031": {"name": "RDNA2 (Navi 22)",         "tile": 320, "gen": "RDNA2",   "fp16_ok": False},
    "gfx1030": {"name": "RDNA2 (Navi 21)",         "tile": 384, "gen": "RDNA2",   "fp16_ok": False},
    # ═══════════ RDNA1 — RX 5000 ═══════════
    "gfx1012": {"name": "RDNA1 (Navi 14)",         "tile": 128, "gen": "RDNA1",   "fp16_ok": False},
    "gfx1011": {"name": "RDNA1 (Navi 12)",         "tile": 192, "gen": "RDNA1",   "fp16_ok": False},
    "gfx1010": {"name": "RDNA1 (Navi 10)",         "tile": 256, "gen": "RDNA1",   "fp16_ok": False},
    # ═══════════ CDNA — 数据中心 ═══════════
    "gfx942":  {"name": "CDNA3 (MI300X)",          "tile": 512, "gen": "CDNA3",   "fp16_ok": True,  "fp8_ok": True},
    "gfx90a":  {"name": "CDNA2 (MI250X)",          "tile": 512, "gen": "CDNA2",   "fp16_ok": True},
    "gfx908":  {"name": "CDNA (MI100)",            "tile": 256, "gen": "CDNA",    "fp16_ok": True},
    # ═══════════ Legacy — Vega ═══════════
    "gfx906":  {"name": "Vega (Radeon VII)",       "tile": 256, "gen": "Vega",    "fp16_ok": False},
}


def _lookup(arch: str):
    if not arch: return None
    if arch in _AMD_ARCH_DB: return _AMD_ARCH_DB[arch]
    for k in sorted(_AMD_ARCH_DB, key=len, reverse=True):
        if arch.startswith(k): return _AMD_ARCH_DB[k]
    return None


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


def _read_env_flag(name: str) -> bool | None:
    """读取用户环境变量: 1/true → True, 0/false → False, 未设置 → None.
    这是 XB_ToolBox 专属的补充开关，不是 ComfyUI 官方参数。"""
    v = os.environ.get(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):  return True
    if v in ("0", "false", "no", "off"): return False
    return None


def _has_comfy_arg(flag: str) -> bool:
    """检查 ComfyUI 启动命令行是否包含指定 flag (如 --force-fp32)."""
    return flag in sys.argv


def tune():
    """ROCm 全局调优 — 动态架构感知 + DiT 算力解放 (2026 v5.1).

    三级优先级: ComfyUI 启动参数 > XB_ 环境变量 > 架构自动判断.

    自动识别的 ComfyUI 官方参数 (v0.16 ~ v0.25 通用):
      --cpu              → 跳过 GPU 调优
      --force-fp32, --fp32-unet, --fp64-unet
                         → 禁用 fp16/bf16 加速
      --force-fp16, --fp16-unet
                         → 仅在 GPU 硬件支持时启用

    XB_ToolBox 补充环境变量（调试用）:
      XB_FP16_ACCUM=1/0  强制启用/禁用 rocBLAS fp16 累积
    """
    if not is_rocm(): return

    # ── CPU 模式直接退出 ──
    if _has_comfy_arg("--cpu"):
        return

    g = gpu_info()

    # ═══════════════════════════════════════════
    # 1. 全局矩阵乘法精度解放
    #    激活 AMD RDNA3+/CDNA 的 WMMA 矩阵核心，
    #    加速所有 Transformer/DiT 线性层 (Anima/LTX/Ideogram).
    #    老架构无 WMMA，PyTorch 自动退回避免报错.
    # ═══════════════════════════════════════════
    torch.set_float32_matmul_precision('high')

    # ═══════════════════════════════════════════
    # 2. FP16 / BF16 累积调度
    # ═══════════════════════════════════════════
    if _has_comfy_arg("--force-fp32") or _has_comfy_arg("--fp32-unet") or _has_comfy_arg("--fp64-unet"):
        can_fp16 = False
    elif _has_comfy_arg("--force-fp16") or _has_comfy_arg("--fp16-unet"):
        can_fp16 = g.get("fp16_ok", False)
    elif (user_fp16 := _read_env_flag("XB_FP16_ACCUM")) is not None:
        can_fp16 = user_fp16
    else:
        can_fp16 = g.get("fp16_ok", False)

    torch.backends.cuda.matmul.allow_fp16_accumulation = can_fp16

    # BF16 降精度规约: 2026 年 DiT 模型默认 BF16，启用后加速 ~15-25%
    if hasattr(torch.backends.cuda.matmul, 'allow_bf16_reduced_precision_reduction'):
        torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = can_fp16

    # ═══════════════════════════════════════════
    # 3. SDPA 架构动态路由 — DiT 长序列算力解放
    # ═══════════════════════════════════════════
    if hasattr(torch.backends.cuda, 'enable_mem_efficient_sdp'):
        torch.backends.cuda.enable_mem_efficient_sdp(True)  # 始终作为兜底

    if hasattr(torch.backends.cuda, 'enable_flash_sdp'):
        gen = g.get("gen", "")
        # RDNA3+ / CDNA2+: Flash Attention 2/3 通过 Triton/CK 完美支持
        # RDNA1/2 / Vega / CDNA1: Flash 触发 MIOpen 段错误，必须禁用
        if gen in ("RDNA3", "RDNA3.5", "RDNA4", "CDNA2", "CDNA3"):
            torch.backends.cuda.enable_flash_sdp(True)
        else:
            torch.backends.cuda.enable_flash_sdp(False)


def _vae_force_fp32() -> bool:
    """老架构 GPU 是否应强制 VAE 用 fp32.

    优先级: ComfyUI 启动参数 > XB_ 环境变量 > 架构自动判断.

    自动识别的 ComfyUI 官方参数 (v0.16 ~ v0.25 通用):
      --force-fp32, --fp32-vae
        → 强制 VAE 用 fp32
      --fp16-vae, --bf16-vae
        → 不强制 (用户明确要 fp16/bf16 VAE)
      --cpu-vae
        → 不强制 (VAE 在 CPU 上运行，无需 GPU 精度保护)

    XB_ToolBox 补充环境变量（调试用）:
      XB_FP16_VAE=1 / 0  强制 VAE fp16 / fp32
    """
    if not is_rocm(): return False

    # ── 优先级 1: ComfyUI 官方启动参数 ──
    if _has_comfy_arg("--cpu-vae"):
        return False  # VAE 在 CPU 上，不需要 GPU 精度保护
    if _has_comfy_arg("--force-fp32") or _has_comfy_arg("--fp32-vae"):
        return True
    if _has_comfy_arg("--fp16-vae") or _has_comfy_arg("--bf16-vae"):
        return False

    # ── 优先级 2: XB_ToolBox 环境变量 ──
    user_fp16 = _read_env_flag("XB_FP16_VAE")
    if user_fp16 is not None:
        return not user_fp16

    # ── 优先级 3: 架构自动判断 ──
    g = gpu_info()
    return not g.get("fp16_ok", False)


def _vae_enforce_precision(vae, tensor: torch.Tensor):
    """ROCm VAE 精度防线 (v5.1 物理扫荡版)

    ComfyUI 的 decode_tiled 内部会调用 load_model_gpu 重新加载原始权重，
    model.to() 的修改会被覆盖。因此必须：
    1. 先让 ComfyUI 把模型加载到 GPU
    2. 直接在 GPU 上篡改 param.data / buffer.data 物理张量

    返回: (安全转换后的 tensor, 模型原始名义 dtype 供 restore)
    """
    if not hasattr(vae, 'first_stage_model'):
        return tensor, None

    model = vae.first_stage_model
    try:
        nominal_dtype = model.dtype
    except AttributeError:
        try:
            nominal_dtype = next(model.parameters()).dtype
        except (StopIteration, AttributeError):
            nominal_dtype = torch.float32

    target_dtype = torch.float32 if _vae_force_fp32() else nominal_dtype
    safe_tensor = tensor.to(target_dtype)

    # 抢占: 让 ComfyUI 先把模型加载到 GPU
    if hasattr(vae, 'patcher'):
        mm.load_model_gpu(vae.patcher)

    # 物理扫荡: 直接在 GPU 上篡改底层张量数据，无视 ComfyUI 拦截
    for param in model.parameters():
        if param.dtype != target_dtype:
            param.data = param.data.to(target_dtype)
    for buf in model.buffers():
        if buf.dtype != target_dtype:
            buf.data = buf.data.to(target_dtype)

    return safe_tensor, nominal_dtype


def _vae_restore_dtype(vae, orig_dtype):
    """恢复 VAE 模型权重到原始精度。"""
    if orig_dtype is not None and hasattr(vae, 'first_stage_model'):
        try:
            vae.first_stage_model.to(orig_dtype)
        except Exception:
            pass


def _get_spatial_compression(vae) -> int:
    """获取 VAE 空间压缩比，兼容多种属性名和 ComfyUI 原生接口。
    优先级: spatial_compression_decode (正确拼写)
           > spacial_compression_decode (历史遗留错误拼写)
           > downscale_ratio (ComfyUI 原生属性)
           > 8 (默认兜底)"""
    for attr in ('spatial_compression_decode', 'spacial_compression_decode'):
        if hasattr(vae, attr):
            val = getattr(vae, attr)
            return val() if callable(val) else val
    if hasattr(vae, 'downscale_ratio'):
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
    """获取当前显存状态。

    ⚠️ Windows ROCm 限制: torch.cuda.memory_allocated() 只能读取 PyTorch 进程内
    分配的显存池，无法感知 AMD 驱动层的隐式分配 (如 MIOpen 算子编译缓存)。
    若推理突然变慢，请以任务管理器「专用 GPU 内存」读数为准。
    Linux 下此问题不存在。
    """
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
    """均匀分块：避免末尾出现特别小的碎片。
    余数 >= chunk/2 时单独成块，< chunk/2 时合并到最后一块。"""
    if total <= chunk:
        return [(0, total)]
    n_full = total // chunk
    remainder = total % chunk
    if remainder == 0:
        return [(i * chunk, (i + 1) * chunk) for i in range(n_full)]

    if remainder < chunk // 2:
        # 余数太小，合并到最后一块
        chunks = [(i * chunk, (i + 1) * chunk) for i in range(n_full - 1)]
        chunks.append(((n_full - 1) * chunk, total))
    else:
        # 余数够大，单独成块
        chunks = [(i * chunk, min((i + 1) * chunk, total)) for i in range(n_full + 1)]
    return chunks


class _Noise_EmptyNoise:
    """空噪波 — 不加噪"""
    def __init__(self):
        self.seed = 0

    def generate_noise(self, input_latent):
        latent_image = input_latent["samples"]
        if latent_image.is_nested:
            tensors = latent_image.unbind()
            zeros = [torch.zeros(t.shape, dtype=t.dtype, layout=t.layout, device="cpu") for t in tensors]
            return comfy.nested_tensor.NestedTensor(zeros)
        else:
            return torch.zeros(latent_image.shape, dtype=latent_image.dtype, layout=latent_image.layout, device="cpu")


class _Noise_RandomNoise:
    """随机噪波"""
    def __init__(self, seed):
        self.seed = seed

    def generate_noise(self, input_latent):
        latent_image = input_latent["samples"]
        batch_inds = input_latent.get("batch_index", None) if "batch_index" in input_latent else None
        return comfy.sample.prepare_noise(latent_image, self.seed, batch_inds)


# ============================================================
# XB_ROCmKSampler — ROCm 优化采样器
# ============================================================
class XB_ROCmKSampler:
    """
    ROCm 优化采样器 — rocBLAS fp16累积 + mem_efficient SDPA
    配合 XB_SageAttentionAccelerator 使用（先 SageAttn 注入，再接此采样器）。
    """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ("MODEL",),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "sampler": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent": ("LATENT",),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理"], {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, model, seed, steps, cfg, sampler, scheduler,
           positive, negative, latent, denoise, cleanup="不做任何清理"):
        tune()
        out, = nodes.KSampler().sample(model, seed, steps, cfg, sampler, scheduler,
                                        positive, negative, latent, denoise)
        _do_cleanup("post", cleanup)
        return (out,)


# ============================================================
# XB_ROCmKSamplerAdvanced — ROCm 优化高级采样器
# ============================================================
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
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "sampler": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent": ("LATENT",),
            "start_at_step": ("INT", {"default": 0, "min": 0, "max": 10000}),
            "end_at_step": ("INT", {"default": 10000, "min": 0, "max": 10000}),
            "return_with_leftover_noise": (["disable", "enable"], {}),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理"], {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, model, add_noise, noise_seed, steps, cfg, sampler, scheduler,
           positive, negative, latent, start_at_step, end_at_step, return_with_leftover_noise, denoise=1.0, cleanup="不做任何清理"):
        tune()
        out, = nodes.KSamplerAdvanced().sample(
            model, add_noise, noise_seed, steps, cfg, sampler, scheduler,
            positive, negative, latent, start_at_step, end_at_step,
            return_with_leftover_noise, denoise=denoise)
        _do_cleanup("post", cleanup)
        return (out,)


# ============================================================
# XB_ROCmVAEDecode — ROCm VAE 解码器 (空间分块)
# ============================================================
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
            "tile": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64,
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

        # 嵌套张量不做 unbind：官方 decode_tiled 内部原生处理 NestedTensor
        # （官方 VAEDecodeTiled 也不做 unbind，直接透传）

        # 🛡️ 强制显存连续性校验 (嵌套张量跳过，由其内部各子张量自行处理)
        if not lat.is_nested and not lat.is_contiguous():
            lat = lat.contiguous()

        # 🛡️ ROCm VAE 精度防线: 抹平混合精度 (ComfyUI 可能 fp16权重+fp32Bias → MIOpen崩溃)
        lat, _orig_dtype = _vae_enforce_precision(vae, lat)

        if tile == 0: tile = g["tile"]

        spatial_comp = _get_spatial_compression(vae)
        tile_x = tile // spatial_comp
        tile_y = tile // spatial_comp

        if overlap == 0:
            overlap_xy = max(4, tile_x // 8)
        else:
            overlap_xy = overlap // spatial_comp

        # 官方防线：防止重叠区超过分块（潜空间校验，对齐 VAEDecodeTiled）
        if tile_x < overlap_xy * 4:
            overlap_xy = tile_x // 4

        # ⚡ 快速路径：图像完全在一个分块内 → 跳过 tiled 开销
        lat_h, lat_w = lat.shape[-2], lat.shape[-1]
        use_fast = (tile_x >= lat_h and tile_y >= lat_w)

        _do_cleanup("pre", cleanup)
        try:
            if use_fast:
                img = vae.decode(lat)
            else:
                img = vae.decode_tiled(lat, tile_x=tile_x, tile_y=tile_y, overlap=overlap_xy)
        except AttributeError:
            print(f"  ⚠️ ROCm VAE Decode: tiled not available, fallback to standard")
            img = vae.decode(lat)
        finally:
            _vae_restore_dtype(vae, _orig_dtype)
            _do_cleanup("post", cleanup)
        if img.dim() == 5:
            img = img.reshape(-1, img.shape[-3], img.shape[-2], img.shape[-1])
        return (img,)


# ============================================================
# XB_ROCmVAEEncode — ROCm VAE 编码器 (空间分块)
# ============================================================
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
            "tile": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64,
                             "tooltip": "0=自动"}),
            "overlap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 16,
                                "tooltip": "0=自动"}),
            "temporal_size": ("INT", {"default": 0, "min": 0, "max": 1024, "step": 16,
                                      "tooltip": "视频VAE时间分块帧数 0=根据显存自适应"}),
            "temporal_overlap": ("INT", {"default": 0, "min": 0, "max": 64, "step": 4,
                                         "tooltip": "时间重叠 0=自动"}),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, pixels, vae, tile, overlap, temporal_size, temporal_overlap, cleanup="不做任何清理"):
        g = gpu_info(); tune()

        # 🛡️ 强制显存连续性校验
        if not pixels.is_contiguous():
            pixels = pixels.contiguous()

        # 🛡️ ROCm VAE 精度防线: 抹平混合精度
        pixels, _orig_dtype = _vae_enforce_precision(vae, pixels)

        if tile == 0: tile = g["tile"]
        if overlap == 0: overlap = max(32, tile // 8)

        # 时间分块: 对齐官方 VAEEncodeTiled
        temporal_comp = vae.temporal_compression_encode() if hasattr(vae, 'temporal_compression_encode') else None
        if temporal_comp is not None:
            if temporal_size == 0:
                if g["gb"] >= 48:   temporal_size = 64
                elif g["gb"] >= 24: temporal_size = 32
                elif g["gb"] >= 16: temporal_size = 16
                else:               temporal_size = 8
            t_tile = max(2, temporal_size // temporal_comp)
            if temporal_overlap == 0:
                temporal_overlap = max(4, temporal_size // 16)
            t_overlap = max(1, min(t_tile // 2, temporal_overlap // temporal_comp))
        else:
            t_tile = None
            t_overlap = None

        _do_cleanup("pre", cleanup)
        try:
            lat = vae.encode_tiled(pixels, tile_x=tile, tile_y=tile, overlap=overlap,
                                   tile_t=t_tile, overlap_t=t_overlap)
        except TypeError:
            print(f"  ⚠️ ROCm VAE Encode: temporal kwargs unsupported, using spatial only.")
            lat = vae.encode_tiled(pixels, tile_x=tile, tile_y=tile, overlap=overlap)
        except AttributeError:
            print(f"  ⚠️ ROCm VAE Encode: tiled not available, fallback to standard")
            lat = vae.encode(pixels)
        finally:
            _vae_restore_dtype(vae, _orig_dtype)
            _do_cleanup("post", cleanup)
        return ({"samples": lat},)


# ============================================================
# XB_ROCmVAEDecodeTemporal — ROCm VAE 时空解码器
# ============================================================
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
            "tile": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64,
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

        # 嵌套张量不做 unbind：官方 decode_tiled 内部原生处理 NestedTensor

        # 🛡️ 强制显存连续性校验 (嵌套张量跳过)
        if not lat.is_nested and not lat.is_contiguous():
            lat = lat.contiguous()

        # 🛡️ ROCm VAE 精度防线: 抹平混合精度
        lat, _orig_dtype = _vae_enforce_precision(vae, lat)

        if lat.dim() == 5:
            B, C, F, H, W = lat.shape; is_vid = True
        elif lat.dim() == 4:
            B, C, H, W = lat.shape; F = 1; is_vid = False
        else:
            raise ValueError(f"unsupported latent dim: {lat.dim()}")

        if tile == 0: tile = g["tile"]
        spatial_comp = _get_spatial_compression(vae)
        tile_x = tile // spatial_comp
        tile_y = tile // spatial_comp
        if overlap == 0: overlap = max(32, tile // 8)
        overlap_xy = overlap // spatial_comp

        temporal_comp = vae.temporal_compression_decode() if hasattr(vae, 'temporal_compression_decode') else None
        if temporal_comp is not None and is_vid:
            if t_tile == 0:
                if g["gb"] >= 48:   t_tile = 64
                elif g["gb"] >= 24: t_tile = 32
                elif g["gb"] >= 16: t_tile = 16
                else:               t_tile = 8
            t_tile_vae = max(2, t_tile // temporal_comp)
            if t_overlap == 0:
                t_overlap = max(4, t_tile // 16)
            t_overlap_vae = max(1, min(t_tile_vae // 2, t_overlap // temporal_comp))
        else:
            t_tile_vae = None
            t_overlap_vae = None

        _do_cleanup("pre", cleanup)
        try:
            img = vae.decode_tiled(lat, tile_x=tile_x, tile_y=tile_y,
                                   overlap=overlap_xy,
                                   tile_t=t_tile_vae, overlap_t=t_overlap_vae)
        except TypeError:
            # decode_tiled 不支持 tile_t/overlap_t
            print(f"  ⚠️ ROCm VAE Temporal: temporal kwargs unsupported.")
            if is_vid and not hasattr(vae, 'temporal_compression_decode'):
                # 2D VAE 处理视频 → movedim 置换 F/C 再展平，防止帧间通道串扰
                print("  ⚠️ flattening 5D to 4D for spatial tiled decode...")
                lat_flat = lat.movedim(2, 1).reshape(-1, C, H, W)
                img = vae.decode_tiled(lat_flat, tile_x=tile_x, tile_y=tile_y, overlap=overlap_xy)
            else:
                # 真 3D VAE 但 decode_tiled 不认 5D，不能硬塞，退回全局解码
                print("  ⚠️ 3D VAE lacks native tiling, falling back to global decode (watch VRAM!)")
                img = vae.decode(lat)
        except AttributeError:
            # 连 decode_tiled 都没有 → 最终 fallback
            print(f"  ⚠️ ROCm VAE Temporal: decode_tiled not available, fallback to standard")
            img = vae.decode(lat)
        finally:
            _vae_restore_dtype(vae, _orig_dtype)
            _do_cleanup("post", cleanup)
        if img.dim() == 5:
            img = img.reshape(-1, img.shape[-3], img.shape[-2], img.shape[-1])
        return (img,)


# ============================================================
# XB_ROCmMemCleaner — ROCm 显存清理与诊断
# ============================================================
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


# ============================================================
# XB_ROCmSamplerCustom — ROCm 自定义采样器
# ============================================================
class XB_ROCmSamplerCustom:
    """
    ROCm 优化自定义采样器 — 配合调度器/采样器/引导器模块化使用
    优化: rocBLAS fp16累积 + mem_efficient SDPA，在采样循环中生效
    """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ("MODEL",),
            "add_noise": ("BOOLEAN", {"default": True}),
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "sampler": ("SAMPLER",),
            "sigmas": ("SIGMAS",),
            "latent_image": ("LATENT",),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理"], {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT", "LATENT")
    RETURN_NAMES = ("output", "denoised_output")
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, model, add_noise, noise_seed, cfg, positive, negative, sampler, sigmas, latent_image, cleanup="不做任何清理"):
        tune()
        latent = latent_image
        latent_image_data = latent["samples"]
        latent = latent.copy()
        latent_image_data = comfy.sample.fix_empty_latent_channels(model, latent_image_data, latent.get("downscale_ratio_spacial", None))
        latent["samples"] = latent_image_data

        if not add_noise:
            noise = _Noise_EmptyNoise().generate_noise(latent)
        else:
            noise = _Noise_RandomNoise(noise_seed).generate_noise(latent)

        noise_mask = None
        if "noise_mask" in latent:
            noise_mask = latent["noise_mask"]

        x0_output = {}
        callback = latent_preview.prepare_callback(model, sigmas.shape[-1] - 1, x0_output)

        disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
        samples = comfy.sample.sample_custom(model, noise, cfg, sampler, sigmas, positive, negative, latent_image_data, noise_mask=noise_mask, callback=callback, disable_pbar=disable_pbar, seed=noise_seed)

        out = latent.copy()
        out.pop("downscale_ratio_spacial", None)
        out["samples"] = samples
        if "x0" in x0_output:
            x0_out = model.model.process_latent_out(x0_output["x0"].cpu())
            if samples.is_nested:
                latent_shapes = [x.shape for x in samples.unbind()]
                x0_out = comfy.nested_tensor.NestedTensor(comfy.utils.unpack_latents(x0_out, latent_shapes))
            out_denoised = latent.copy()
            out_denoised["samples"] = x0_out
        else:
            out_denoised = out
        _do_cleanup("post", cleanup)
        return (out, out_denoised)


# ============================================================
# XB_ROCmSamplerCustomAdvanced — ROCm 自定义高级采样器
# ============================================================
class XB_ROCmSamplerCustomAdvanced:
    """
    ROCm 优化自定义高级采样器 — 完全模块化：噪波/引导器/采样器/sigma 独立注入
    优化: rocBLAS fp16累积 + mem_efficient SDPA，在采样循环中生效
    """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "noise": ("NOISE",),
            "guider": ("GUIDER",),
            "sampler": ("SAMPLER",),
            "sigmas": ("SIGMAS",),
            "latent_image": ("LATENT",),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理"], {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT", "LATENT")
    RETURN_NAMES = ("output", "denoised_output")
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, noise, guider, sampler, sigmas, latent_image, cleanup="不做任何清理"):
        tune()
        latent = latent_image
        latent_image_data = latent["samples"]
        latent = latent.copy()
        latent_image_data = comfy.sample.fix_empty_latent_channels(guider.model_patcher, latent_image_data, latent.get("downscale_ratio_spacial", None))
        latent["samples"] = latent_image_data

        noise_mask = None
        if "noise_mask" in latent:
            noise_mask = latent["noise_mask"]

        x0_output = {}
        callback = latent_preview.prepare_callback(guider.model_patcher, sigmas.shape[-1] - 1, x0_output)

        disable_pbar = not comfy.utils.PROGRESS_BAR_ENABLED
        samples = guider.sample(noise.generate_noise(latent), latent_image_data, sampler, sigmas, denoise_mask=noise_mask, callback=callback, disable_pbar=disable_pbar, seed=noise.seed)
        samples = samples.to(comfy.model_management.intermediate_device())

        out = latent.copy()
        out.pop("downscale_ratio_spacial", None)
        out["samples"] = samples
        if "x0" in x0_output:
            x0_out = guider.model_patcher.model.process_latent_out(x0_output["x0"].cpu())
            if samples.is_nested:
                latent_shapes = [x.shape for x in samples.unbind()]
                x0_out = comfy.nested_tensor.NestedTensor(comfy.utils.unpack_latents(x0_out, latent_shapes))
            out_denoised = latent.copy()
            out_denoised["samples"] = x0_out
        else:
            out_denoised = out
        _do_cleanup("post", cleanup)
        return (out, out_denoised)


__all__ = ['XB_ROCmKSampler', 'XB_ROCmKSamplerAdvanced', 'XB_ROCmSamplerCustom',
           'XB_ROCmSamplerCustomAdvanced', 'XB_ROCmVAEDecode',
           'XB_ROCmVAEEncode', 'XB_ROCmVAEDecodeTemporal', 'XB_ROCmMemCleaner']
