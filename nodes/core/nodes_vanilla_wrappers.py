"""
XB_ToolBox 原版优化节点 (Vanilla Wrappers) — v1.0
=================================================
一字不差地调用 ComfyUI 官方节点，仅在其执行前插入分级显存清理。
彻底放弃自定义底层算法，完全依赖官方维护的采样/解码逻辑。

设计原则:
  - 动态继承 INPUT_TYPES → 官方新增参数自动同步
  - **kwargs 透传 → 参数名/数量永不过时
  - 不做任何底层魔改 → 零维护成本
"""

import gc
import copy
import inspect
import comfy.model_management as mm
import comfy.samplers
import nodes

# 安全导入: comfy_extras 在未来版本可能被移除
try:
    from comfy_extras import nodes_custom_sampler as _ncs
except ImportError:
    _ncs = None


# ═══════════════════════════════════════════════════════════════
# 统一的清理调度器
# ═══════════════════════════════════════════════════════════════

_CLEANUP_OPTIONS = [
    "不做任何清理",
    "卸载显存模型",
    "卸载全量模型",
]


def _safe_call(target_func, **kwargs):
    """向下兼容透传: 仅传入目标函数实际支持的参数，自动丢弃旧版不识别的参数。

    典型场景: 新版 ComfyUI 的 VAEDecodeTiled.decode() 支持 temporal_size/temporal_overlap，
    但秋叶整合包等旧版只有 tile_size/overlap。此函数用 inspect 探测签名并过滤。
    Returns:
        (result, dropped_params) — result 是调用结果，dropped_params 是被丢弃的参数字典
    """
    sig = inspect.signature(target_func)
    valid = set(sig.parameters.keys())
    accepted = {}
    dropped = {}
    for k, v in kwargs.items():
        if k in valid:
            accepted[k] = v
        else:
            dropped[k] = v
    if dropped:
        print(f"[XB_Wrapper] 旧版 ComfyUI 不支持参数 {list(dropped.keys())}，已自动跳过")
    return target_func(**accepted), dropped


# ───────────────────────────────────────────────────────────────
# 执行器定位：ComfyUI 把 PromptExecutor 实例放在主循环的局部变量里，
# 外部拿不到，这里在上游 hook 住它的 __init__/reset 以取得引用。
# ───────────────────────────────────────────────────────────────

_XB_EXECUTOR = None


def _install_executor_hook():
    global _XB_EXECUTOR
    try:
        from execution import PromptExecutor
    except Exception:
        return False
    if getattr(PromptExecutor, "_xb_hooked", False):
        return True

    orig_init = PromptExecutor.__init__
    orig_reset = PromptExecutor.reset

    def _xb_init(self, *args, **kwargs):
        global _XB_EXECUTOR
        orig_init(self, *args, **kwargs)
        _XB_EXECUTOR = self

    def _xb_reset(self, *args, **kwargs):
        global _XB_EXECUTOR
        _XB_EXECUTOR = self
        return orig_reset(self, *args, **kwargs)

    PromptExecutor.__init__ = _xb_init
    PromptExecutor.reset = _xb_reset
    PromptExecutor._xb_hooked = True
    return True


def _get_executor():
    """取当前 PromptExecutor；取不到返回 None（清理降级为 L2 行为）。"""
    global _XB_EXECUTOR
    if _XB_EXECUTOR is not None:
        return _XB_EXECUTOR
    _install_executor_hook()
    if _XB_EXECUTOR is not None:
        return _XB_EXECUTOR
    try:
        import sys
        for frame in list(sys._current_frames().values()):
            while frame is not None:
                for value in frame.f_locals.values():
                    if type(value).__name__ == "PromptExecutor":
                        _XB_EXECUTOR = value
                        return value
                frame = frame.f_back
    except Exception:
        pass
    return None


def _is_model_patcher(obj) -> bool:
    try:
        from comfy.model_patcher import ModelPatcher
        return isinstance(obj, ModelPatcher)
    except Exception:
        return type(obj).__name__ == "ModelPatcher"


def _collect_model_patchers(outputs, found=None):
    """递归找出输出里携带的 ModelPatcher（MODEL / CLIP / VAE / CONTROL_NET 等）"""
    if found is None:
        found = []
    if outputs is None:
        return found
    if hasattr(outputs, "values") and not isinstance(outputs, (str, bytes)):
        try:
            outputs = list(outputs.values())
        except Exception:
            return found
    elif not isinstance(outputs, (list, tuple)):
        outputs = (outputs,)

    for item in outputs:
        if item is None:
            continue
        if isinstance(item, (list, tuple)) or hasattr(item, "values"):
            _collect_model_patchers(item, found)
            continue
        if _is_model_patcher(item):
            found.append(item)
            continue
        patcher = getattr(item, "patcher", None)
        if _is_model_patcher(patcher):
            found.append(patcher)
        get_models = getattr(item, "get_models", None)
        if callable(get_models):
            try:
                found.extend(m for m in get_models() if _is_model_patcher(m))
            except Exception:
                pass
    return found


def _purge_model_refs() -> str:
    """销毁模型对象的强引用，让 CPU 侧权重真正可被回收（而非只从显存搬到内存）。

    ComfyUI 里模型存活靠两处强引用：
      1. PromptExecutor.prompt_model_tracker.models（当前 prompt 期间钉住的动态模型）
      2. 执行缓存里的节点输出（MODEL/CLIP/VAE 对象）
    两处都断开后 ModelPatcher 才会被 GC，权重才会交还分配器；显存里也才会真正空出来。
    """
    executor = _get_executor()
    if executor is None:
        return "未找到执行器，跳过引用清理"

    pinned = 0
    tracker = getattr(executor, "prompt_model_tracker", None)
    if tracker is not None:
        try:
            pinned = len(getattr(tracker, "models", None) or {})
            tracker.end()
        except Exception:
            pinned = 0

    dropped = 0
    store = getattr(getattr(executor, "caches", None), "outputs", None)
    cache = getattr(store, "cache", None)
    if isinstance(cache, dict):
        for key, entry in list(cache.items()):
            entry_outputs = getattr(entry, "outputs", entry)
            if not _collect_model_patchers(entry_outputs):
                continue
            cache.pop(key, None)
            for attr in ("used_generation", "timestamps", "children"):
                book = getattr(store, attr, None)
                if isinstance(book, dict):
                    book.pop(key, None)
            dropped += 1

    return f"解除 {pinned} 个模型钉住、丢弃 {dropped} 个模型缓存条目"


def _execute_cleanup(level: str, label: str = ""):
    """在正式节点运行前释放显存，给本节点的计算腾位置。

    两档策略（旧值「单次缓存清理 / 双次缓存清理」一律按不清理处理）：
      L2【卸载显存模型】→ unload_all_models：模型权重从显存退到内存，显存立即空出
      L3【卸载全量模型】→ L2 + 断开模型强引用 + cleanup_models/gc：模型对象被销毁，
                          显存与内存两侧的占用都交还，下次需要时从磁盘重新加载
    """
    prefix = f"[XB_Wrapper{':'+label if label else ''}]"
    if level not in ("卸载显存模型", "卸载全量模型"):
        return

    print(f"{prefix} 🧹 执行 {level} ...", flush=True)

    mm.unload_all_models()
    if level == "卸载全量模型":
        detail = _purge_model_refs()
        mm.cleanup_models()
        mm.cleanup_models_gc()
        gc.collect()
        print(f"{prefix}    {detail}", flush=True)
    mm.soft_empty_cache()

    print(f"{prefix} ✅ 清理完成，显存环境纯净", flush=True)


# ───────────────────────────────────────────────────────────────
# 分块策略：整幅图装得进一块时直接走官方不分块解码
# 官方 decode_tiled_ 对 2D latent 会跑 3 遍分块解码再平均，
# 图幅比 tile_size 还小时这 3 遍完全是白跑（实测 1024² 慢 40%~60%）。
# ───────────────────────────────────────────────────────────────


def _fits_one_tile(vae, samples, tile_size, temporal_size=None):
    """O(1) 形状判定：整幅 latent 能否装进单块。不做任何张量运算或显存同步。"""
    if vae is None or samples is None:
        return False
    latent = samples.get("samples") if isinstance(samples, dict) else samples
    if latent is None or getattr(latent, "is_nested", False):
        return False
    try:
        compression = vae.spacial_compression_decode()
        if isinstance(compression, (list, tuple)):
            compression = compression[-1]
        compression = int(compression)
    except Exception:
        return False
    if compression <= 0:
        return False
    tile_latent = int(tile_size) // compression
    if tile_latent <= 0:
        return False

    shape = tuple(latent.shape)
    if len(shape) == 4:
        return shape[-2] <= tile_latent and shape[-1] <= tile_latent
    if len(shape) == 5:
        if shape[-2] > tile_latent or shape[-1] > tile_latent:
            return False
        if temporal_size is None:
            return False
        try:
            temporal_compression = vae.temporal_compression_decode()
        except Exception:
            return False
        if temporal_compression is None:
            return True
        return shape[-3] <= max(2, int(temporal_size) // max(1, int(temporal_compression)))
    return False


def _decode_whole_if_single_tile(vae, samples, tile_size, temporal_size=None):
    """整幅能装进一块时静默返回官方不分块解码结果；否则返回 None（调用方继续走分块）"""
    if not _fits_one_tile(vae, samples, tile_size, temporal_size):
        return None
    return nodes.VAEDecode().decode(vae=vae, samples=samples)


def _encode_whole_if_single_tile(vae, pixels, tile_size):
    """整幅图能装进一块时静默返回官方不分块编码结果；否则返回 None（调用方继续走分块）

    官方 encode_tiled_ 对 2D 图像同样跑 3 遍分块再平均（tile、2x×½y、½x×2y），
    图幅不超过 tile_size 时这 3 遍结果都等价于整幅编码，纯属白跑。
    """
    if vae is None or pixels is None:
        return None
    shape = getattr(pixels, "shape", None)
    if shape is None or len(shape) != 4:
        return None
    tile = int(tile_size)
    if tile <= 0:
        return None
    if int(shape[1]) > tile or int(shape[2]) > tile:
        return None
    return nodes.VAEEncode().encode(vae=vae, pixels=pixels)


# ═══════════════════════════════════════════════════════════════
# 采样器 Wrapper 节点
# ═══════════════════════════════════════════════════════════════

class XB_KSampler:
    """原版 KSampler 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.KSampler.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.KSampler.RETURN_TYPES
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "采样器")
        return nodes.KSampler().sample(**kwargs)


class XB_KSamplerAdvanced:
    """原版 KSamplerAdvanced 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.KSamplerAdvanced.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.KSamplerAdvanced.RETURN_TYPES
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "高级采样器")
        return nodes.KSamplerAdvanced().sample(**kwargs)


class XB_SamplerCustom:
    """原版 SamplerCustom 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(_ncs.SamplerCustom.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = _ncs.SamplerCustom.RETURN_TYPES
    RETURN_NAMES = ("Latent", "降噪Latent")
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "自定义采样器")
        return _ncs.SamplerCustom.sample(**kwargs)


class XB_SamplerCustomAdvanced:
    """原版 SamplerCustomAdvanced 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(_ncs.SamplerCustomAdvanced.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = _ncs.SamplerCustomAdvanced.RETURN_TYPES
    RETURN_NAMES = ("Latent", "降噪Latent")
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "自定义高级采样器")
        return _ncs.SamplerCustomAdvanced.sample(**kwargs)


# ═══════════════════════════════════════════════════════════════
# VAE 解码器 Wrapper 节点
# ═══════════════════════════════════════════════════════════════

class XB_VAEDecode:
    """原版 VAEDecode 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEDecode.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEDecode.RETURN_TYPES
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE解码")
        return nodes.VAEDecode().decode(**kwargs)


class XB_VAEDecodeTiled:
    """原版 VAEDecodeTiled 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEDecodeTiled.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEDecodeTiled.RETURN_TYPES
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块解码")
        whole = _decode_whole_if_single_tile(kwargs.get("vae"), kwargs.get("samples"),
                                             kwargs.get("tile_size", 512), kwargs.get("temporal_size", 64))
        if whole is not None:
            return whole
        return nodes.VAEDecodeTiled().decode(**kwargs)


class XB_VAEDecodeTiledImage:
    """原版 VAEDecodeTiled 图片专用套皮 — 仅空间分块，无时间维度"""

    @classmethod
    def INPUT_TYPES(cls):
        # 从官方定义派生，官方新增参数能自动接住；时间参数裁掉，调用时用固定值
        inputs = copy.deepcopy(nodes.VAEDecodeTiled.INPUT_TYPES())
        required = inputs["required"]
        required.pop("temporal_size", None)
        required.pop("temporal_overlap", None)
        required["tile_size"] = ("INT", {"default": 512, "min": 256, "max": 4096, "step": 64,
                                         "tooltip": "空间分块大小(像素)"})
        required["overlap"] = ("INT", {"default": 64, "min": 0, "max": 256, "step": 16,
                                       "tooltip": "空间块重叠(像素)"})
        required["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块解码(图片)")
        whole = _decode_whole_if_single_tile(kwargs.get("vae"), kwargs.get("samples"),
                                             kwargs.get("tile_size", 512), 64)
        if whole is not None:
            return whole
        # 透传给官方 VAEDecodeTiled（向下兼容：旧版不支持时间参数时自动跳过）
        result, _ = _safe_call(nodes.VAEDecodeTiled().decode,
                               temporal_size=kwargs.get("temporal_size", 64),
                               temporal_overlap=kwargs.get("temporal_overlap", 8),
                               **kwargs)
        return result


class XB_VAEEncode:
    """原版 VAEEncode 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEEncode.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEEncode.RETURN_TYPES
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/原版优化"

    def encode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE编码")
        return nodes.VAEEncode().encode(**kwargs)


class XB_VAEEncodeTiled:
    """原版 VAEEncodeTiled 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEEncodeTiled.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEEncodeTiled.RETURN_TYPES
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/原版优化"

    def encode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块编码")
        return nodes.VAEEncodeTiled().encode(**kwargs)


class XB_VAEEncodeTiledImage:
    """原版 VAEEncodeTiled 图片专用套皮 — 仅空间分块，无时间维度"""

    @classmethod
    def INPUT_TYPES(cls):
        # 从官方定义派生，官方新增参数能自动接住；时间参数裁掉，调用时用固定值
        inputs = copy.deepcopy(nodes.VAEEncodeTiled.INPUT_TYPES())
        required = inputs["required"]
        required.pop("temporal_size", None)
        required.pop("temporal_overlap", None)
        required["tile_size"] = ("INT", {"default": 512, "min": 256, "max": 4096, "step": 64,
                                         "tooltip": "空间分块大小(像素)"})
        required["overlap"] = ("INT", {"default": 64, "min": 0, "max": 256, "step": 16,
                                       "tooltip": "空间块重叠(像素)"})
        required["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/原版优化"

    def encode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块编码(图片)")
        whole = _encode_whole_if_single_tile(kwargs.get("vae"), kwargs.get("pixels"),
                                             kwargs.get("tile_size", 512))
        if whole is not None:
            return whole
        # 透传给官方 VAEEncodeTiled（向下兼容：旧版不支持时间参数时自动跳过）
        result, _ = _safe_call(nodes.VAEEncodeTiled().encode,
                               temporal_size=64, temporal_overlap=8, **kwargs)
        return result


class XB_VAEEncodeForInpaint:
    """原版 VAEEncodeForInpaint 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEEncodeForInpaint.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEEncodeForInpaint.RETURN_TYPES
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/原版优化"

    def encode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE修补编码")
        return nodes.VAEEncodeForInpaint().encode(**kwargs)


# ═══════════════════════════════════════════════════════════════
# 别名类 — 匹配旧 ROCm 节点参数名，保证旧工作流连线兼容
#         （采样器别名已废弃：旧节点在载入时自动升级为新节点）
# ═══════════════════════════════════════════════════════════════


class _AliasVAEDecodeTemporal:
    """别名: XB_ROCmVAEDecodeTemporal — tile→tile_size, t_tile→temporal_size, t_overlap→temporal_overlap"""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "samples": ("LATENT",),
            "vae": ("VAE",),
            "tile": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64}),
            "overlap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 16}),
            "t_tile": ("INT", {"default": 0, "min": 0, "max": 1024, "step": 16}),
            "t_overlap": ("INT", {"default": 0, "min": 0, "max": 128, "step": 8}),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块解码")
        if "tile" in kwargs:
            kwargs["tile_size"] = kwargs.pop("tile") if kwargs["tile"] > 0 else 512
        if "t_tile" in kwargs:
            kwargs["temporal_size"] = kwargs.pop("t_tile") if kwargs["t_tile"] > 0 else 64
        if "t_overlap" in kwargs:
            kwargs["temporal_overlap"] = kwargs.pop("t_overlap") if kwargs["t_overlap"] > 0 else 8
        # 向下兼容: 旧版 ComfyUI 不支持时间参数时自动跳过
        result, _ = _safe_call(nodes.VAEDecodeTiled().decode, **kwargs)
        return result


# ═══════════════════════════════════════════════════════════════
# 节点注册
# ═══════════════════════════════════════════════════════════════

NODE_CLASS_MAPPINGS = {
    "XB_KSampler": XB_KSampler,
    "XB_KSamplerAdvanced": XB_KSamplerAdvanced,
    "XB_VAEDecode": XB_VAEDecode,
    "XB_VAEDecodeTiled": XB_VAEDecodeTiled,
    "XB_VAEDecodeTiledImage": XB_VAEDecodeTiledImage,
    "XB_VAEEncode": XB_VAEEncode,
    "XB_VAEEncodeTiled": XB_VAEEncodeTiled,
    "XB_VAEEncodeTiledImage": XB_VAEEncodeTiledImage,
    "XB_VAEEncodeForInpaint": XB_VAEEncodeForInpaint,
}

# 仅在 comfy_extras 可用时注册自定义采样器
if _ncs is not None:
    NODE_CLASS_MAPPINGS["XB_SamplerCustom"] = XB_SamplerCustom
    NODE_CLASS_MAPPINGS["XB_SamplerCustomAdvanced"] = XB_SamplerCustomAdvanced

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_KSampler": "XB-采样器（原版优化）",
    "XB_KSamplerAdvanced": "XB-高级采样器（原版优化）",
    "XB_VAEDecode": "XB-VAE解码（原版优化）",
    "XB_VAEDecodeTiled": "XB-VAE分块解码（原版优化）",
    "XB_VAEDecodeTiledImage": "XB-VAE解码（原版优化）",
    "XB_VAEEncode": "XB-VAE编码（原版优化）",
    "XB_VAEEncodeTiled": "XB-VAE分块编码（原版优化）",
    "XB_VAEEncodeTiledImage": "XB-VAE分块编码·图片（原版优化）",
    "XB_VAEEncodeForInpaint": "XB-VAE修补编码（原版优化）",
}
if _ncs is not None:
    NODE_DISPLAY_NAME_MAPPINGS["XB_SamplerCustom"] = "XB-自定义采样器（原版优化）"
    NODE_DISPLAY_NAME_MAPPINGS["XB_SamplerCustomAdvanced"] = "XB-自定义高级采样器（原版优化）"

# 尽早 hook 住 PromptExecutor，供「卸载全量模型」断开模型强引用使用
_install_executor_hook()
