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
  XB_ROCmLTXVAEDecode          — LTX VAE 时空分块解码器（128ch/32x压缩专用）
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


def _sdp_context():
    """返回适合当前 GPU 架构的 sdp_kernel context manager。

    与 tune() 解耦：matmul 等设置保持全局，SDPA 路由通过 context manager
    在每次采样时精确控制，采样结束后自动归还算子调度权给 ComfyUI 主进程，
    杜绝全局 enable_flash_sdp 对老旧 ControlNet/AnimateDiff 节点的生态污染。
    """
    g = gpu_info()
    gen = g.get("gen", "")
    if gen in ("RDNA3", "RDNA3.5", "RDNA4", "CDNA2", "CDNA3"):
        return torch.backends.cuda.sdp_kernel(enable_flash=True, enable_math=False, enable_mem_efficient=True)
    else:
        return torch.backends.cuda.sdp_kernel(enable_flash=False, enable_math=True, enable_mem_efficient=True)


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


def _vae_tune_light():
    """VAE 专用轻量调优 — 仅设置 fp16 累积，不污染全局 matmul 精度。

    与 tune() 的区别：
      - 不调用 torch.set_float32_matmul_precision('high')  ← 这是关键！
        该调用会让 PyTorch 尝试 TF32 tensor core，AMD GPU 没有 TF32，
        回退到慢速路径，导致 VAE 内部所有卷积/矩阵乘变慢。
      - 仅设置 allow_fp16_accumulation，对 VAE 解码路径安全。
    """
    if not is_rocm():
        return
    if _has_comfy_arg("--cpu"):
        return
    g = gpu_info()
    # ── 仅做 fp16 累积，不碰 float32 matmul 精度 ──
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
    """解码前轻量清理 — 仅 empty_cache，绝不同步。

    设计原则：
      - 解码前只需要释放 PyTorch 缓存池中未使用的显存块，
        让 VAE 有足够空间分配 tile 缓冲区。
      - empty_cache() 是异步的，不阻塞 GPU 流水线。
      - 绝不调用 synchronize() —— 这是 3 分钟卡顿的元凶。
      - 绝不调用 gc.collect() —— Python GC 对 GPU 显存无帮助，
        反而可能触发 CUDA IPC 清理的隐式同步。
    """
    if level == "不做任何清理":
        return
    if not torch.cuda.is_available():
        return
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


def _is_video_latent(latent_dict: dict) -> bool:
    """检测是否为视频 latent（5D 张量，时间维度 > 1）"""
    samples = latent_dict.get("samples")
    if samples is None:
        return False
    return samples.ndim == 5 and samples.shape[2] > 1


def _make_ksampler_callback(steps: int, is_video: bool = False):
    """创建增强进度回调：ETA 预估 + 每步耗时 + 视频模式自动跳过预览。

    视频工作流中解码预览图开销极大（需跑 VAE），因此自动跳过。
    """
    pbar = comfy.utils.ProgressBar(steps)
    last_update = [time.time()]
    start_time = time.time()

    def callback(step, x0, x, total_steps):
        now = time.time()
        if now - last_update[0] < 0.5 and step < total_steps - 1:
            return

        preview_bytes = None
        if not is_video and step % 5 == 0:
            try:
                previewer = latent_preview.get_previewer(
                    mm.get_torch_device(),
                    latent_preview.TAESDLatentPreviewer().latent_format
                )
                if previewer:
                    preview_bytes = previewer.decode_latent_to_preview_image("JPEG", x0)
            except Exception:
                pass

        try:
            pbar.update_absolute(step + 1, total_steps, preview=preview_bytes)
        except Exception:
            pass

        last_update[0] = now
        elapsed = now - start_time
        if step > 0:
            avg_per_step = elapsed / (step + 1)
            eta = (total_steps - step - 1) * avg_per_step
            prefix = "🎬" if is_video else "🖼️"
            print(f"{prefix} Step {step+1}/{total_steps} | 已用 {elapsed:.1f}s | 剩余 ~{eta:.1f}s | 均速 {avg_per_step:.2f}s/步", flush=True)

    return callback


# ============================================================
# XB_ROCmKSampler — ROCm 优化采样器
# ============================================================
class XB_ROCmKSampler:
    """
    ROCm 优化采样器 (v5.2) — rocBLAS fp16累积 + mem_efficient SDPA + 增强进度
    配合 XB_SageAttentionAccelerator 使用（先 SageAttn 注入，再接此采样器）。

    v5.2 增强：
      - 增强进度回调：ETA 预估 + 每步耗时
      - 视频 latent 自动跳过预览（节省 VAE 解码开销）
      - 采样后轻量清理，绝不同步等待
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
        # ── 轨道 A：非 AMD 环境 → 直接使用官方采样器 ──
        if not is_rocm():
            return nodes.KSampler().sample(model, seed, steps, cfg, sampler, scheduler,
                                            positive, negative, latent, denoise)

        # ── 轨道 B：AMD ROCm 环境 → 优化 + 熔断降级 ──
        try:
            tune()
            is_video = _is_video_latent(latent)
            callback = _make_ksampler_callback(steps, is_video)
            print(f"🚀 开始采样: {steps}步, CFG {cfg}, {sampler} ({scheduler})", flush=True)
            with _sdp_context():
                out, = nodes.KSampler().sample(
                    model, seed, steps, cfg, sampler, scheduler,
                    positive, negative, latent, denoise,
                    callback=callback, disable_pbar=False
                )
            print(f"✅ 采样完成", flush=True)
            # 采样后仅 empty_cache（异步），绝不同步
            if cleanup != "不做任何清理" and torch.cuda.is_available():
                torch.cuda.empty_cache()
            return (out,)
        except Exception as e:
            print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
            print(f"[XB_ToolBox 错误信息] {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return nodes.KSampler().sample(model, seed, steps, cfg, sampler, scheduler,
                                            positive, negative, latent, denoise)


# ============================================================
# XB_ROCmKSamplerAdvanced — ROCm 优化高级采样器
# ============================================================
class XB_ROCmKSamplerAdvanced:
    """
    ROCm 优化高级采样器 (v5.2) — 支持分段采样、加噪控制、残留噪声返回 + 增强进度
    配合 XB_SageAttentionAccelerator 使用（先 SageAttn 注入，再接此采样器）。

    v5.2 增强：
      - 增强进度回调：ETA 预估 + 每步耗时
      - 视频 latent 自动跳过预览
      - 采样后轻量清理，绝不同步等待
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
        # ── 轨道 A：非 AMD 环境 → 直接使用官方高级采样器 ──
        if not is_rocm():
            return nodes.KSamplerAdvanced().sample(
                model, add_noise, noise_seed, steps, cfg, sampler, scheduler,
                positive, negative, latent, start_at_step, end_at_step,
                return_with_leftover_noise, denoise=denoise)

        # ── 轨道 B：AMD ROCm 环境 → 优化 + 熔断降级 ──
        try:
            tune()
            is_video = _is_video_latent(latent)
            callback = _make_ksampler_callback(steps, is_video)
            print(f"🚀 开始高级采样: {steps}步 (区间 {start_at_step}-{end_at_step}), CFG {cfg}, {sampler} ({scheduler})", flush=True)
            with _sdp_context():
                out, = nodes.KSamplerAdvanced().sample(
                    model, add_noise, noise_seed, steps, cfg, sampler, scheduler,
                    positive, negative, latent, start_at_step, end_at_step,
                    return_with_leftover_noise, denoise=denoise,
                    callback=callback, disable_pbar=False
                )
            print(f"✅ 高级采样完成", flush=True)
            if cleanup != "不做任何清理" and torch.cuda.is_available():
                torch.cuda.empty_cache()
            return (out,)
        except Exception as e:
            print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
            print(f"[XB_ToolBox 错误信息] {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return nodes.KSamplerAdvanced().sample(
                model, add_noise, noise_seed, steps, cfg, sampler, scheduler,
                positive, negative, latent, start_at_step, end_at_step,
                return_with_leftover_noise, denoise=denoise)


# ============================================================
# XB_ROCmVAEDecode — ROCm VAE 解码器 (空间分块)
# ============================================================
class XB_ROCmVAEDecode:
    """
    ROCm VAE 解码器 — 架构自适应空间分块 (v5.2 修复版)
    tile=0 → 自动根据GPU架构选最优值 (RX9070XT→768, RX7900→640, ...)
    tile>0 → 使用手动指定的分块大小

    v5.2 修复：
      - 移除 tune() 全局 matmul 精度污染 → 改为 _vae_tune_light()
      - 解码后不再同步等待 → 消除 10-60s 白等
      - 解码前仅 empty_cache()，不 sync 不 gc → 保持流水线并发
      - 清理默认值改为 "不做任何清理" → 用户需要时手动选择
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
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, samples, vae, tile, overlap, cleanup):
        # ── 轨道 A：非 AMD 环境 (NVIDIA CUDA / CPU) → 直接使用官方 VAE 解码 ──
        if not is_rocm():
            return nodes.VAEDecode().decode(samples=samples, vae=vae)

        # ── 轨道 B：AMD ROCm 环境 → 优化 + 熔断降级 ──
        try:
            g = gpu_info(); _vae_tune_light()
            lat = samples["samples"]

            # 🛡️ 强制显存连续性校验 (嵌套张量跳过)
            if not lat.is_nested and not lat.is_contiguous():
                lat = lat.contiguous()

            if tile == 0: tile = g["tile"]

            spatial_comp = _get_spatial_compression(vae)
            tile_x = tile // spatial_comp
            tile_y = tile // spatial_comp

            if overlap == 0:
                overlap_xy = max(4, tile_x // 8)
            else:
                overlap_xy = overlap // spatial_comp

            # 🛡️ 数学护城河：stride = tile - overlap，必须 > 0，否则死循环
            overlap_xy = max(1, min(overlap_xy, tile_x - 1))

            if tile_x < overlap_xy * 4:
                overlap_xy = tile_x // 4

            lat_h, lat_w = lat.shape[-2], lat.shape[-1]
            use_fast = (tile_x >= lat_h and tile_y >= lat_w)

            # 🔧 v5.2: 解码前仅 empty_cache，绝不同步等待
            _predecode_cleanup(cleanup)
            try:
                if use_fast:
                    img = vae.decode(lat)
                else:
                    img = vae.decode_tiled(lat, tile_x=tile_x, tile_y=tile_y, overlap=overlap_xy)
            except AttributeError:
                print(f"  ⚠️ ROCm VAE Decode: tiled not available, fallback to standard")
                img = vae.decode(lat)
            # 🔧 v5.2: 解码后不做任何清理，让 Python 引用计数自然回收
            if isinstance(img, tuple):
                img = img[0]
            if img.dim() == 5:
                img = img.reshape(-1, img.shape[-3], img.shape[-2], img.shape[-1])
            return (img,)
        except Exception as e:
            print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
            print(f"[XB_ToolBox 错误信息] {e}")
            # 🔧 v5.2: 异常恢复也不 sync，直接清理缓存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return nodes.VAEDecode().decode(samples=samples, vae=vae)


# ============================================================
# XB_ROCmVAEEncode — ROCm VAE 编码器 (空间分块)
# ============================================================
class XB_ROCmVAEEncode:
    """
    ROCm VAE 编码器 — 架构自适应空间分块 (v5.2 修复版)
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
        # ── 轨道 A：非 AMD 环境 (NVIDIA CUDA / CPU) → 直接使用官方 VAE 编码 ──
        if not is_rocm():
            return nodes.VAEEncode().encode(pixels=pixels, vae=vae)

        # ── 轨道 B：AMD ROCm 环境 → 优化 + 熔断降级 ──
        try:
            g = gpu_info(); _vae_tune_light()

            # 🛡️ 强制显存连续性校验
            if not pixels.is_contiguous():
                pixels = pixels.contiguous()

            if tile == 0: tile = g["tile"]
            if overlap == 0: overlap = max(32, tile // 8)
            # 🛡️ 编码路径：overlap 必须 < tile，防止 stride ≤ 0 导致死循环
            overlap = max(1, min(overlap, tile - 1))

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

            # 🔧 v5.2: 编码前仅 empty_cache，绝不同步
            _predecode_cleanup(cleanup)
            try:
                lat = vae.encode_tiled(pixels, tile_x=tile, tile_y=tile, overlap=overlap,
                                       tile_t=t_tile, overlap_t=t_overlap)
            except TypeError:
                print(f"  ⚠️ ROCm VAE Encode: temporal kwargs unsupported, using spatial only.")
                lat = vae.encode_tiled(pixels, tile_x=tile, tile_y=tile, overlap=overlap)
            except AttributeError:
                print(f"  ⚠️ ROCm VAE Encode: tiled not available, fallback to standard")
                lat = vae.encode(pixels)
            # 🔧 v5.2: 编码后不做任何清理
            return ({"samples": lat},)
        except Exception as e:
            print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
            print(f"[XB_ToolBox 错误信息] {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return nodes.VAEEncode().encode(pixels=pixels, vae=vae)


# ============================================================
# XB_ROCmVAEDecodeTemporal — ROCm VAE 时空解码器
# ============================================================
class XB_ROCmVAEDecodeTemporal:
    """
    ROCm VAE 解码器 (空间+时间分块) — 视频模型专用 (v5.2 重写)
    适用于 Wan/LTX 等视频 VAE latent。
    所有参数=0 时全自动: 空间tile→架构自适应, 时间chunk→显存自适应

    v5.2 重写：
      - 手动时间轴切片 + 线性混合 (_temporal_tiled_decode)
      - 彻底废弃全局解码回退（大显存机器全局解码会触发慢速内存交换）
      - 移除 tune() 全局 matmul 精度影响 → _vae_tune_light()
      - 解码后不做任何同步清理
      - 重叠区域线性淡入淡出混合，消除分块接缝
      - 每个 chunk 解码后轻量 empty_cache，防止碎片累积
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
                               "tooltip": "时间分块(Latent帧) 0=根据显存自适应"}),
            "t_overlap": ("INT", {"default": 0, "min": 0, "max": 32, "step": 2,
                                  "tooltip": "时间重叠(Latent帧) 0=自动(t_tile/8)"}),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, samples, vae, tile, overlap, t_tile, t_overlap, cleanup):
        # ── 轨道 A：非 AMD 环境 (NVIDIA CUDA / CPU) → 直接使用官方时空解码 ──
        if not is_rocm():
            if t_tile <= 0:
                return nodes.VAEDecode().decode(samples=samples, vae=vae)
            return nodes.VAEDecodeTiled().decode(
                samples=samples, vae=vae,
                tile_size=tile if tile > 0 else 256,
                overlap=overlap if overlap > 0 else 32,
                temporal_size=t_tile, temporal_overlap=t_overlap)

        # ── 轨道 B：AMD ROCm 环境 → 手动时间轴切片 + 线性混合 ──
        try:
            g = gpu_info(); _vae_tune_light()
            lat = samples["samples"]

            # 🛡️ 强制显存连续性校验 (嵌套张量跳过)
            if not lat.is_nested and not lat.is_contiguous():
                lat = lat.contiguous()

            if lat.dim() == 5:
                B, C, F, H, W = lat.shape; is_vid = True
            elif lat.dim() == 4:
                B, C, H, W = lat.shape; F = 1; is_vid = False
            else:
                raise ValueError(f"unsupported latent dim: {lat.dim()}")

            # ── 空间分块参数 ──
            if tile == 0: tile = g["tile"]
            spatial_comp = _get_spatial_compression(vae)
            tile_x = tile // spatial_comp
            tile_y = tile // spatial_comp
            if overlap == 0: overlap = max(32, tile // 8)
            overlap_xy = overlap // spatial_comp
            overlap_xy = max(1, min(overlap_xy, tile_x - 1))

            # ── 时间压缩比 ──
            temporal_comp = None
            if hasattr(vae, 'temporal_compression_decode'):
                temporal_comp = vae.temporal_compression_decode()

            # 🔧 v5.2: 解码前仅 empty_cache，绝不同步
            _predecode_cleanup(cleanup)

            if is_vid and temporal_comp is not None and t_tile > 0 and t_tile < F:
                # ── 手动时间轴切片路径 (视频 + 时间压缩 + 需要分块) ──
                img = self._temporal_tiled_decode(
                    vae, lat, B, C, F, H, W,
                    tile_x, tile_y, overlap_xy,
                    t_tile, t_overlap, temporal_comp
                )
            elif is_vid:
                # ── 视频但不需要时间分块 → 空间分块解码 ──
                try:
                    img = vae.decode_tiled(lat, tile_x=tile_x, tile_y=tile_y, overlap=overlap_xy)
                except (AttributeError, TypeError):
                    # 回退：展平 5D→4D 做空间分块（绝不全局解码！）
                    print("  ⚠️ decode_tiled unavailable, flattening 5D→4D for spatial tiled decode")
                    lat_flat = lat.movedim(2, 1).reshape(-1, C, H, W)
                    img = vae.decode_tiled(lat_flat, tile_x=tile_x, tile_y=tile_y, overlap=overlap_xy)
            else:
                # ── 单帧图片 → 直接空间分块或全图解码 ──
                use_fast = (tile_x >= H and tile_y >= W)
                if use_fast:
                    img = vae.decode(lat)
                else:
                    try:
                        img = vae.decode_tiled(lat, tile_x=tile_x, tile_y=tile_y, overlap=overlap_xy)
                    except (AttributeError, TypeError):
                        img = vae.decode(lat)

            if isinstance(img, tuple):
                img = img[0]
            if img.dim() == 5:
                img = img.reshape(-1, img.shape[-3], img.shape[-2], img.shape[-1])

            # 🔧 v5.2: 解码后不做任何同步清理
            return (img,)

        except Exception as e:
            print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
            print(f"[XB_ToolBox 错误信息] {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if t_tile <= 0:
                return nodes.VAEDecode().decode(samples=samples, vae=vae)
            return nodes.VAEDecodeTiled().decode(
                samples=samples, vae=vae,
                tile_size=tile if tile > 0 else 256,
                overlap=overlap if overlap > 0 else 32,
                temporal_size=t_tile, temporal_overlap=t_overlap)

    # ═══════════════════════════════════════════════════════════════
    # 手动时间轴切片解码（核心加速引擎）
    # ═══════════════════════════════════════════════════════════════
    def _temporal_tiled_decode(self, vae, lat, B, C, F, H, W,
                                tile_x, tile_y, overlap_xy,
                                t_tile, t_overlap, temporal_comp):
        """手动时间轴切片 + 线性混合，避免全局解码导致的内存溢出。

        算法：
          1. 将 latent 按时间轴切成有重叠的 chunk
          2. 每个 chunk 用 vae.decode() 解码（内部自动做空间分块）
          3. 丢掉每个后续 chunk 的第 1 个输出帧（时间上下文不完整）
          4. 对重叠区域做线性淡入淡出混合
          5. 用 torch.cat 分配新内存拼接（避免张量原地切片写入问题）
        """
        device = lat.device
        dtype = lat.dtype

        # ── 确定 chunk 边界 (latent 帧坐标) ──
        if t_overlap == 0:
            t_overlap = max(2, t_tile // 8)
        t_overlap = max(1, min(t_overlap, t_tile // 2))

        chunks = []
        chunk_start = 0
        while chunk_start < F:
            if chunk_start == 0:
                chunk_end = min(chunk_start + t_tile, F)
            else:
                # 前移 overlap 帧作为上下文，+1 给因果卷积额外一帧
                overlap_start = max(1, chunk_start - t_overlap - 1)
                extra = chunk_start - overlap_start
                chunk_end = min(chunk_start + t_tile - extra, F)
            if chunk_end <= chunk_start:
                break
            chunks.append((chunk_start, chunk_end))
            chunk_start = chunk_end

        num_chunks = len(chunks)
        if num_chunks <= 1:
            # 不需要分块，直接解码
            result = vae.decode(lat)
            if isinstance(result, tuple):
                result = result[0]
            result = result.squeeze(0)  # [T_out, H, W, C]
            return result

        print(f"  🧩 Temporal tiling: {num_chunks} chunks, {F} latent frames → ~{F * temporal_comp} output frames")

        # ── 逐 chunk 解码 + 混合拼接 ──
        result = None
        first_chunk_done = False

        for chunk_idx, (c_start, c_end) in enumerate(chunks):
            # 允许 ComfyUI 中断
            mm.throw_exception_if_processing_interrupted()

            chunk_frames = c_end - c_start
            chunk_latent = lat[:, :, c_start:c_end, :, :]

            # 空间分块解码这个时间 chunk
            with torch.no_grad():
                if tile_x >= H and tile_y >= W:
                    decoded = vae.decode(chunk_latent)
                else:
                    try:
                        decoded = vae.decode_tiled(chunk_latent,
                                                   tile_x=tile_x, tile_y=tile_y,
                                                   overlap=overlap_xy)
                    except (AttributeError, TypeError):
                        decoded = vae.decode(chunk_latent)

            if isinstance(decoded, tuple):
                decoded = decoded[0]
            # vae.decode 返回 [B, T_out, H, W, C]，B=1
            decoded = decoded.squeeze(0)  # [T_out, H, W, C]

            if not first_chunk_done:
                result = decoded
                first_chunk_done = True
                out_T = decoded.shape[0]
                if chunk_idx < 3:
                    print(f"  Chunk 0: latent [{c_start}:{c_end}] ({chunk_frames}f) → {out_T} output frames")
            else:
                out_T = decoded.shape[0]

                # 丢掉第 1 个输出帧（时间上下文不完整，可能有人工痕迹）
                decoded = decoded[1:]  # [out_T-1, H, W, C]

                # 计算混合帧数
                blend_frames = min(t_overlap * temporal_comp, decoded.shape[0], result.shape[0])
                if blend_frames > 0:
                    prev_tail = result[-blend_frames:]
                    curr_head = decoded[:blend_frames]
                    # 线性权重：prev 1→0, curr 0→1
                    w = torch.linspace(0, 1, blend_frames, device=device, dtype=decoded.dtype)
                    w = w.view(-1, 1, 1, 1)
                    blended = prev_tail * (1.0 - w) + curr_head * w
                    # torch.cat 分配新内存拼接，避免张量原地切片写入问题
                    result = torch.cat(
                        [result[:-blend_frames], blended, decoded[blend_frames:]],
                        dim=0
                    )
                else:
                    result = torch.cat([result, decoded], dim=0)

                if chunk_idx < 3:
                    print(f"  Chunk {chunk_idx}: latent [{c_start}:{c_end}] ({chunk_frames}f) → "
                          f"{out_T} output, dropped 1, blended {blend_frames}")

            # 每个 chunk 后轻量清理，防止显存碎片累积（异步，不 sync）
            if torch.cuda.is_available() and chunk_idx % 2 == 0:
                torch.cuda.empty_cache()

        print(f"  ✅ Temporal tiling complete: {result.shape[0]} total output frames")
        return result


# ============================================================
# XB_ROCmLTXVAEDecode — ROCm LTX VAE 时空分块解码器
# ============================================================
class XB_ROCmLTXVAEDecode:
    """
    ROCm LTX VAE 时空分块解码器 (v5.2 全新) — 专为 LTX Video VAE 设计

    LTX VAE 特性:
      - 128 通道 latent，32× 空间压缩，8× 时间压缩
      - 使用 vae.downscale_index_formula 获取缩放因子
      - 空间分块：网格切分 + 权重累积 + 重叠羽化混合
      - 时间分块：逐 chunk 解码 + 线性时间混合

    v5.2 设计:
      - 空间分块采用预分配输出张量 + 权重累积归一化
      - 时间分块手动切片 + 线性混合
      - ROCm 优化：异步 empty_cache，绝不同步
      - 解码前轻量清理，解码后不做任何清理
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "samples": ("LATENT",),
                "vae": ("VAE",),
                "spatial_tiles": ("INT", {"default": 4, "min": 1, "max": 8,
                    "tooltip": "空间分块数(宽高相同)，1=不分块"}),
                "spatial_overlap": ("INT", {"default": 1, "min": 0, "max": 8,
                    "tooltip": "空间块重叠(latent像素)"}),
                "temporal_tile_length": ("INT", {"default": 16, "min": 0, "max": 256,
                    "tooltip": "时间分块长度(latent帧)，0=不分时间块"}),
                "temporal_overlap": ("INT", {"default": 1, "min": 0, "max": 8,
                    "tooltip": "时间块重叠(latent帧)"}),
                "last_frame_fix": ("BOOLEAN", {"default": False,
                    "tooltip": "重复最后一帧后解码再丢弃多余帧，修复尾部伪影"}),
                "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"],
                            {"default": "不做任何清理"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/ROCm"

    def go(self, samples, vae, spatial_tiles, spatial_overlap,
           temporal_tile_length, temporal_overlap, last_frame_fix, cleanup):
        # ── 轨道 A：非 AMD 环境 → 直接使用官方解码 ──
        if not is_rocm():
            return nodes.VAEDecode().decode(samples=samples, vae=vae)

        # ── 轨道 B：AMD ROCm 环境 → 手动时空分块 ──
        try:
            _vae_tune_light()
            lat = samples["samples"]

            # 🛡️ 强制显存连续性
            if not lat.is_nested and not lat.is_contiguous():
                lat = lat.contiguous()

            B, C, F, H, W = lat.shape
            time_scale, width_scale, height_scale = vae.downscale_index_formula
            out_frames = 1 + (F - 1) * time_scale
            out_H = H * height_scale
            out_W = W * width_scale

            # last_frame_fix：复制最后一帧到末尾以修复尾部伪影
            if last_frame_fix:
                lat = torch.cat([lat, lat[:, :, -1:, :, :]], dim=2)
                F = lat.shape[2]
                out_frames = 1 + (F - 1) * time_scale

            # 🔧 解码前仅 empty_cache，绝不同步
            _predecode_cleanup(cleanup)

            if temporal_tile_length > 0 and temporal_tile_length < F:
                # ── 时空分块路径 ──
                img = self._decode_spatiotemporal(
                    vae, lat, B, C, F, H, W, out_frames, out_H, out_W,
                    spatial_tiles, spatial_overlap,
                    temporal_tile_length, temporal_overlap,
                    time_scale, width_scale, height_scale
                )
            else:
                # ── 仅空间分块路径 ──
                img = self._decode_spatial(
                    vae, lat, B, out_frames, out_H, out_W,
                    spatial_tiles, spatial_overlap,
                    width_scale, height_scale
                )

            # 去掉 last_frame_fix 产生的多余帧
            if last_frame_fix:
                img = img[:-time_scale]

            # reshape 为 ComfyUI 标准格式 [B*F, H, W, C]
            img = img.view(-1, out_H, out_W, img.shape[-1])

            # 🔧 解码后不做任何同步清理
            return (img,)

        except Exception as e:
            print(f"\n[XB_ToolBox 警告] LTX VAE 优化节点异常，回退到官方解码器！")
            print(f"[XB_ToolBox 错误信息] {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return nodes.VAEDecode().decode(samples=samples, vae=vae)

    # ═══════════════════════════════════════════════════════════════
    # 仅空间分块 (LTX 原算法：网格切分 + 权重累积)
    # ═══════════════════════════════════════════════════════════════
    def _decode_spatial(self, vae, lat, B, out_frames, out_H, out_W,
                        spatial_tiles, spatial_overlap,
                        width_scale, height_scale):
        """空间分块解码：网格切分 + 权重累积归一化。

        每个空间 tile 独立调用 vae.decode() 解码完整时间序列，
        重叠区域使用线性羽化权重，累加后归一化消除接缝。
        """
        _, C, F, H, W = lat.shape

        # 预分配输出张量和权重张量
        output = torch.zeros(
            (B, out_frames, out_H, out_W, 3),
            device=lat.device, dtype=torch.float32
        )
        weights = torch.zeros(
            (B, out_frames, out_H, out_W, 1),
            device=lat.device, dtype=torch.float32
        )

        # 计算基础 tile 尺寸 (含重叠)
        base_tile_H = (H + (spatial_tiles - 1) * spatial_overlap) // spatial_tiles
        base_tile_W = (W + (spatial_tiles - 1) * spatial_overlap) // spatial_tiles

        for v in range(spatial_tiles):
            for h in range(spatial_tiles):
                # 计算 latent 空间中的 tile 边界
                h_start = h * (base_tile_W - spatial_overlap)
                v_start = v * (base_tile_H - spatial_overlap)
                h_end = min(h_start + base_tile_W, W) if h < spatial_tiles - 1 else W
                v_end = min(v_start + base_tile_H, H) if v < spatial_tiles - 1 else H

                # 提取 tile → 解码
                tile_lat = lat[:, :, :, v_start:v_end, h_start:h_end]
                with torch.no_grad():
                    decoded = vae.decode(tile_lat)

                # 计算输出空间中的 tile 边界
                out_h_start = v_start * height_scale
                out_h_end = v_end * height_scale
                out_w_start = h_start * width_scale
                out_w_end = h_end * width_scale

                # 构建羽化权重 (重叠区域线性渐变)
                tile_out_H = out_h_end - out_h_start
                tile_out_W = out_w_end - out_w_start
                tile_weights = torch.ones(
                    (B, out_frames, tile_out_H, tile_out_W, 1),
                    device=decoded.device, dtype=decoded.dtype
                )

                overlap_out_H = spatial_overlap * height_scale
                overlap_out_W = spatial_overlap * width_scale

                # 水平羽化
                if h > 0:
                    w_blend = torch.linspace(0, 1, overlap_out_W, device=decoded.device)
                    tile_weights[:, :, :, :overlap_out_W, :] *= w_blend.view(1, 1, 1, -1, 1)
                if h < spatial_tiles - 1:
                    w_blend = torch.linspace(1, 0, overlap_out_W, device=decoded.device)
                    tile_weights[:, :, :, -overlap_out_W:, :] *= w_blend.view(1, 1, 1, -1, 1)

                # 垂直羽化
                if v > 0:
                    h_blend = torch.linspace(0, 1, overlap_out_H, device=decoded.device)
                    tile_weights[:, :, :overlap_out_H, :, :] *= h_blend.view(1, 1, -1, 1, 1)
                if v < spatial_tiles - 1:
                    h_blend = torch.linspace(1, 0, overlap_out_H, device=decoded.device)
                    tile_weights[:, :, -overlap_out_H:, :, :] *= h_blend.view(1, 1, -1, 1, 1)

                # 加权累加到输出
                output[:, :, out_h_start:out_h_end, out_w_start:out_w_end, :] += (
                    decoded * tile_weights
                )
                weights[:, :, out_h_start:out_h_end, out_w_start:out_w_end, :] += tile_weights

        # 归一化
        output /= weights + 1e-8
        return output

    # ═══════════════════════════════════════════════════════════════
    # 时空分块：时间轴切片 + 空间分块 + 时间线性混合
    # ═══════════════════════════════════════════════════════════════
    def _decode_spatiotemporal(self, vae, lat, B, C, F, H, W,
                                out_frames, out_H, out_W,
                                spatial_tiles, spatial_overlap,
                                temporal_tile_length, temporal_overlap,
                                time_scale, width_scale, height_scale):
        """时空分块解码：先按时间轴切片，每个切片再做空间分块。

        时间混合：每个后续 chunk 丢弃第 1 个输出帧，重叠区域线性混合。
        """
        if temporal_tile_length < temporal_overlap + 1:
            temporal_overlap = max(0, temporal_tile_length - 2)

        # 预分配完整输出
        output = torch.empty(
            (B, out_frames, out_H, out_W, 3),
            device=lat.device, dtype=torch.float32
        )

        chunk_start = 0
        while chunk_start < F:
            # 计算时间 chunk 边界 (与 LTX compute_chunk_boundaries 一致)
            if chunk_start == 0:
                overlap_start = chunk_start
                chunk_end = min(chunk_start + temporal_tile_length, F)
            else:
                overlap_start = max(1, chunk_start - temporal_overlap - 1)
                extra = chunk_start - overlap_start
                chunk_end = min(chunk_start + temporal_tile_length - extra, F)

            chunk_latent_frames = chunk_end - overlap_start
            tile = lat[:, :, overlap_start:chunk_end]

            # 空间分块解码这个时间切片
            decoded = self._decode_spatial(
                vae, tile, B,
                1 + (chunk_latent_frames - 1) * time_scale,
                out_H, out_W,
                spatial_tiles, spatial_overlap,
                width_scale, height_scale
            )  # [B, chunk_out_frames, H, W, 3]

            if chunk_start == 0:
                # 第一个 chunk：直接放入输出
                output[:, :decoded.shape[1]] = decoded
            else:
                # 丢弃第 1 帧（时间上下文不完整）
                if decoded.shape[1] <= 1:
                    raise RuntimeError("Temporal tile has only 1 output frame after trim")
                decoded = decoded[:, 1:]

                # 计算输出中的时间位置
                out_t_start = 1 + overlap_start * time_scale
                out_t_end = out_t_start + decoded.shape[1]

                # 线性时间混合
                blend_frames = temporal_overlap * time_scale
                if blend_frames > 0:
                    frame_weights = torch.linspace(
                        0, 1, blend_frames + 2,
                        device=decoded.device, dtype=decoded.dtype
                    )[1:-1].view(1, -1, 1, 1, 1)

                    after_blend = out_t_start + blend_frames
                    # 旧帧渐隐 + 新帧渐显
                    output[:, out_t_start:after_blend] *= (1 - frame_weights)
                    output[:, out_t_start:after_blend] += frame_weights * decoded[:, :blend_frames]
                    # 非重叠部分直接替换
                    output[:, after_blend:out_t_end] = decoded[:, blend_frames:]
                else:
                    output[:, out_t_start:out_t_end] = decoded

            chunk_start = chunk_end

            # 每个时间 chunk 后轻量清理
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        return output


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
    ROCm 优化自定义采样器 (v5.2) — 配合调度器/采样器/引导器模块化使用 + 增强进度
    优化: rocBLAS fp16累积 + mem_efficient SDPA，在采样循环中生效

    v5.2 增强：
      - 视频 latent 自动跳过预览
      - 采样开始/完成日志
      - 采样后轻量清理，绝不同步等待
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
        # ── 轨道 A：非 AMD 环境 → 直接使用官方自定义采样器 ──
        if not is_rocm():
            return nodes.SamplerCustom().sample(model, add_noise, noise_seed, cfg, positive, negative,
                                                 sampler, sigmas, latent_image)

        # ── 轨道 B：AMD ROCm 环境 → 优化 + 熔断降级 ──
        try:
            tune()
            is_video = _is_video_latent(latent_image)
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
            # 视频模式：跳过预览，禁用进度条
            disable_pbar = is_video or not comfy.utils.PROGRESS_BAR_ENABLED

            print(f"🚀 开始自定义采样: {sigmas.shape[-1]-1}步, CFG {cfg}", flush=True)
            with _sdp_context():
                samples = comfy.sample.sample_custom(model, noise, cfg, sampler, sigmas, positive, negative, latent_image_data, noise_mask=noise_mask, callback=callback, disable_pbar=disable_pbar, seed=noise_seed)
            print(f"✅ 自定义采样完成", flush=True)

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
            if cleanup != "不做任何清理" and torch.cuda.is_available():
                torch.cuda.empty_cache()
            return (out, out_denoised)
        except Exception as e:
            print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
            print(f"[XB_ToolBox 错误信息] {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return nodes.SamplerCustom().sample(model, add_noise, noise_seed, cfg, positive, negative,
                                                 sampler, sigmas, latent_image)


# ============================================================
# XB_ROCmSamplerCustomAdvanced — ROCm 自定义高级采样器
# ============================================================
class XB_ROCmSamplerCustomAdvanced:
    """
    ROCm 优化自定义高级采样器 (v5.2) — 完全模块化：噪波/引导器/采样器/sigma 独立注入 + 增强进度
    优化: rocBLAS fp16累积 + mem_efficient SDPA，在采样循环中生效

    v5.2 增强：
      - 视频 latent 自动跳过预览
      - 采样开始/完成日志
      - 采样后轻量清理，绝不同步等待
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
        # ── 轨道 A：非 AMD 环境 → 直接使用官方自定义高级采样器 ──
        if not is_rocm():
            return nodes.SamplerCustomAdvanced().sample(noise, guider, sampler, sigmas, latent_image)

        # ── 轨道 B：AMD ROCm 环境 → 优化 + 熔断降级 ──
        try:
            tune()
            is_video = _is_video_latent(latent_image)
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
            disable_pbar = is_video or not comfy.utils.PROGRESS_BAR_ENABLED

            print(f"🚀 开始自定义高级采样: {sigmas.shape[-1]-1}步", flush=True)
            with _sdp_context():
                samples = guider.sample(noise.generate_noise(latent), latent_image_data, sampler, sigmas, denoise_mask=noise_mask, callback=callback, disable_pbar=disable_pbar, seed=noise.seed)
            samples = samples.to(comfy.model_management.intermediate_device())
            print(f"✅ 自定义高级采样完成", flush=True)

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
            if cleanup != "不做任何清理" and torch.cuda.is_available():
                torch.cuda.empty_cache()
            return (out, out_denoised)
        except Exception as e:
            print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
            print(f"[XB_ToolBox 错误信息] {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return nodes.SamplerCustomAdvanced().sample(noise, guider, sampler, sigmas, latent_image)


__all__ = ['XB_ROCmKSampler', 'XB_ROCmKSamplerAdvanced', 'XB_ROCmSamplerCustom',
           'XB_ROCmSamplerCustomAdvanced', 'XB_ROCmVAEDecode',
           'XB_ROCmVAEEncode', 'XB_ROCmVAEDecodeTemporal', 'XB_ROCmLTXVAEDecode',
           'XB_ROCmMemCleaner']
