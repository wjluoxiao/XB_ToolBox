import os
import torch
import numpy as np
import gc
from PIL import Image, ImageOps
import nodes
import comfy.samplers
import comfy.model_management as mm
import folder_paths
try:
    import torchaudio
except ImportError:
    torchaudio = None
    print("⚠️ [XB-BOX] torchaudio 未安装！音频重采样功能将不可用。请运行: pip install torchaudio")
from .nodes_wan_vae import XB_WanFirstLastFrameToVideo, XB_WanImageToVideo, XB_WanInfiniteTalkToVideo_Single


# VRAM 保护阈值：累积视频超过总显存此比例时自动迁移至 CPU（兼容 6GB~48GB 全系列显卡）
_VRAM_VIDEO_SAFETY_RATIO = 0.30


def _get_vram_info():
    """获取当前 CUDA 设备显存信息 (total, free, used)"""
    if not torch.cuda.is_available():
        return 0, 0, 0
    d = torch.cuda.current_device()
    total = torch.cuda.get_device_properties(d).total_memory
    reserved = torch.cuda.memory_reserved(d)
    allocated = torch.cuda.memory_allocated(d)
    free = total - reserved
    return total, free, allocated


def _refresh_models(force=False):
    """VRAM 感知缓存刷新：仅在显存紧张时清理，避免频繁清空分配池导致碎片化"""
    if not force:
        _, free, _ = _get_vram_info()
        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(torch.cuda.current_device()).total_memory
            if free > total * 0.12:
                return
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
    elif torch.backends.mps.is_available():
        torch.mps.synchronize()
        torch.mps.empty_cache()
    gc.collect()


def _safe_video_accumulate(prev_video, new_segment, concat_dim, label="", concat_mode="自动"):
    """
    VRAM 感知视频累积拼接，兼容从 6GB 到 48GB 的所有配置。
    concat_mode: "自动"(默认) | "强制GPU" | "强制CPU"
    """
    if prev_video is None:
        return new_segment

    target_device = new_segment.device

    # 强制CPU
    if concat_mode == "强制CPU":
        new_segment = new_segment.cpu()
        if prev_video.device.type != 'cpu':
            prev_video = prev_video.cpu()
        result = torch.cat([prev_video, new_segment], dim=concat_dim)
        tag = f"[{label}] " if label else ""
        print(f"💾 [XB-BOX] {tag}强制CPU拼接")
        return result

    # 强制GPU
    if concat_mode == "强制GPU":
        if prev_video.device != target_device:
            prev_video = prev_video.to(target_device, non_blocking=True)
        result = torch.cat([prev_video, new_segment], dim=concat_dim)
        tag = f"[{label}] " if label else ""
        print(f"🚀 [XB-BOX] {tag}强制GPU拼接: {result.numel()*result.element_size()/1024**3:.2f}GB")
        return result

    # 自动模式
    combined_bytes = (prev_video.numel() + new_segment.numel()) * new_segment.element_size()
    if target_device.type == 'cuda':
        total_mem = torch.cuda.get_device_properties(target_device).total_memory
        ratio = combined_bytes / total_mem
    else:
        ratio = 0.0

    if prev_video.device.type == 'cpu' or ratio > _VRAM_VIDEO_SAFETY_RATIO:
        new_segment = new_segment.cpu()
        if prev_video.device.type != 'cpu':
            prev_video = prev_video.cpu()
        result = torch.cat([prev_video, new_segment], dim=concat_dim)
        tag = f"[{label}] " if label else ""
        print(f"💾 [XB-BOX] {tag}VRAM保护: 累积视频 {combined_bytes/1024**3:.2f}GB ({ratio*100:.0f}% 总显存) → 已在 CPU 完成无损拼接")
        return result

    if prev_video.device != target_device:
        prev_video = prev_video.to(target_device, non_blocking=True)
    return torch.cat([prev_video, new_segment], dim=concat_dim)


def _match_color_to_ref(target_img, ref_img):
    """色彩重映射引擎：用均值和标准差将 target 光影强制对齐到 ref。

    3D VAE 的边界帧因缺失未来帧 padding 会变暗——此函数用数学手段
    把变暗的尾帧拉回原始首帧的光影分布，斩断接力中的曝光衰减死循环。

    target_img: [1, H, W, 3] (变暗的尾帧)
    ref_img:    [1, H', W', 3] (总线里的全局参考首帧)
    """
    t = target_img.movedim(-1, 1)  # [1, 3, H, W]
    r = ref_img.movedim(-1, 1)     # [1, 3, H', W']

    t_mean = t.mean(dim=(2, 3), keepdim=True)
    t_std = t.std(dim=(2, 3), keepdim=True) + 1e-6
    r_mean = r.mean(dim=(2, 3), keepdim=True)
    r_std = r.std(dim=(2, 3), keepdim=True) + 1e-6

    matched = (t - t_mean) / t_std * r_std + r_mean
    return torch.clamp(matched, 0.0, 1.0).movedim(1, -1)


def _apply_progressive_color_correction(decoded_image, ref_image, is_4d):
    """全序列渐变色彩补偿：平方权重 + 50% 混合降敏，避免尾端色彩过度补偿伪影。

    用 start_image 做色彩锚点。平方权重 (x²) 比三次幂 (x³) 过渡更平缓，
    在 33 帧场景下后 15% 帧的修正强度从 73% 降至 60%。
    50% blending (原帧×0.5 + 匹配帧×0.5) 进一步抑制 color transfer 的内容差异伪影。
    """
    vid = decoded_image if is_4d else decoded_image[0]
    T = vid.shape[0]
    if T <= 1:
        return decoded_image

    raw_last = vid[-1:]  # [1, H, W, C]
    full_match = _match_color_to_ref(raw_last, ref_image)

    # 🌟 50% 混合降敏：一半原帧 + 一半色彩匹配，抑制内容差异导致的过度补偿
    blended_last = raw_last * 0.5 + full_match * 0.5

    drift_diff = blended_last - raw_last
    linear = torch.linspace(0.0, 1.0, T, device=vid.device, dtype=vid.dtype)
    weights = (linear ** 2).view(T, 1, 1, 1)  # 平方权重，更平缓

    corrected_vid = vid + drift_diff * weights
    corrected_vid = torch.clamp(corrected_vid, 0.0, 1.0)

    return corrected_vid if is_4d else corrected_vid.unsqueeze(0)


# ============================================================
# XB_Wan_ParamBus — Wan 视频参数总线
# ============================================================
class XB_Wan_ParamBus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_high": ("MODEL",),  
                "model_low": ("MODEL",),   
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "negative_prompt": ("STRING", {"multiline": True, "default": "vivid colors, overexposed, static, blurry details..."}),
                "width": ("INT", {"forceInput": True}),
                "height": ("INT", {"forceInput": True}),
                "length": ("INT", {"forceInput": True}),
                "fps": ("FLOAT", {"forceInput": True}),
                # --- VAE 时空分块与重叠参数 ---
                "vae_encode_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
                "vae_decode_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
                "spatial_overlap": ("INT", {"default": 32, "min": 0, "max": 3840, "step": 32}),
                "temporal_chunk_size": ("INT", {"default": 64, "min": 0, "max": 8192, "step": 4}),
                "temporal_overlap": ("INT", {"default": 8, "min": 0, "max": 8192, "step": 4}),
                "steps": ("INT", {"default": 4, "min": 1, "max": 100}),
                "high_noise_steps": ("INT", {"default": 2, "min": 1, "max": 50}), 
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "sampler_name": (comfy.samplers.KSAMPLER_NAMES, ),
                "scheduler": (comfy.samplers.SCHEDULER_NAMES, ),
                "seed": ("INT", {"default": 123456789}),
                "cut_first_frame": ("BOOLEAN", {"default": True, "label_on": "Yes (Relay Deduplication)", "label_off": "No (Keep First Frame)"}),
                "trim_head_frames": ("INT", {"default": 1, "min": 1, "max": 8192, "step": 1}),
            },
            "optional": {
                "clip_vision": ("CLIP_VISION",),
                "global_start_image": ("IMAGE",),
                "concat_mode": (["自动", "强制GPU", "强制CPU"], {"default": "自动", "tooltip": "视频累积拼接位置"}),
                "scale_method": (["lanczos", "bilinear", "bicubic", "nearest-exact", "area"], {"default": "lanczos"}),
                "crop_mode": (["center", "disabled"], {"default": "center"}),
            }
        }

    RETURN_TYPES = ("WAN_BUS",)  
    RETURN_NAMES = ("📦 WAN_BUS (Dynamic Bus)",)
    FUNCTION = "pack_bus"
    CATEGORY = "XB_ToolBox/Pipeline"

    def pack_bus(self, **kwargs):
        import comfy.utils
        cv = kwargs.get("clip_vision")
        ref = kwargs.get("global_start_image")  # 首尾帧/图生视频用 global_start_image 做视觉参考
        if cv is not None and ref is not None:
            w, h = kwargs["width"], kwargs["height"]
            method = kwargs.get("scale_method", "lanczos")
            crop = kwargs.get("crop_mode", "center")
            scaled = comfy.utils.common_upscale(ref.movedim(-1, 1), w, h, method, crop).movedim(1, -1)
            kwargs["clip_vision_output"], = nodes.CLIPVisionEncode().encode(cv, scaled, "center")
            print(f"👁️ [XB-BOX] CLIP视觉编码 ({ref.shape[1]}×{ref.shape[2]} → {w}×{h}, {method}/{crop})")
        else:
            kwargs["clip_vision_output"] = None
        return (kwargs,)


# ============================================================
# XB_Wan_RelayNode — Wan 首尾帧接力点
# ============================================================
class XB_Wan_RelayNode:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))] if os.path.exists(input_dir) else []
        files = sorted(files)
        
        if not files:
            files = ["[Folder empty_Please connect or upload]"]
            
        return {
            "required": {
                "wan_bus": ("WAN_BUS",),  
                "start_image": ("IMAGE",),
                "positive_prompt": ("STRING", {"multiline": True, "default": "Describe the specific action for this segment..."}),
                "end_image_file": (files, {"image_upload": True})
            },
            "optional": {
                "prev_video": ("IMAGE",),
                "opt_end_image": ("IMAGE",)
            }
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True 

    RETURN_TYPES = ("WAN_BUS", "IMAGE", "IMAGE")
    RETURN_NAMES = ("📦 WAN_BUS (Pass to next)", "🖼️ Current End Image (Connect to next Start Image)", "🎞️ Accumulated Video Stream")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_bus, start_image, positive_prompt, end_image_file, opt_end_image=None, prev_video=None):
        print("\n🏃 [XB-BOX] Executing First/Last frame constraint relay task...")
        b = wan_bus
        seed = b["seed"]
        cut_first_frame = b.get("cut_first_frame", True)
        trim_head_frames = b.get("trim_head_frames", 1)

        encode_tile = b.get("vae_encode_tile_size", b.get("vae_tile_size", 64))
        decode_tile = b.get("vae_decode_tile_size", b.get("vae_tile_size", 64))
        spat_overlap = b.get("spatial_overlap", 32)
        temp_chunk = b.get("temporal_chunk_size", 64)
        temp_overlap = b.get("temporal_overlap", 8)

        if opt_end_image is not None:
            end_image = opt_end_image
            print(f"🖼️ [XB-BOX] Endpoint connection detected, prioritizing opt_end_image payload.")
        else:
            if end_image_file == "[Folder empty_Please connect or upload]":
                print("⏭️  [XB-BOX] No end frame specified for this segment, skipping relay iteration.")
                return (wan_bus, start_image, prev_video)
                
            image_path = folder_paths.get_annotated_filepath(end_image_file)
            if not os.path.exists(image_path):
                print(f"⏭️  [XB-BOX] End frame file not found: {os.path.basename(image_path)}, skipping relay iteration.")
                return (wan_bus, start_image, prev_video)
            
            i = Image.open(image_path)
            i = ImageOps.exif_transpose(i)
            image_data = i.convert("RGB")
            image_data = np.array(image_data).astype(np.float32) / 255.0
            end_image = torch.from_numpy(image_data)[None,]

        pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], positive_prompt)
        neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b["negative_prompt"])

        cv_output = b.get("clip_vision_output")
        pos, neg, latent = XB_WanFirstLastFrameToVideo().process(
            positive=pos_cond, negative=neg_cond, vae=b["vae"], 
            clip_vision_start_image=cv_output, clip_vision_end_image=None, 
            start_image=start_image, end_image=end_image, 
            width=b["width"], height=b["height"], length=b["length"], 
            batch_size=1, vae_tile_size=encode_tile,
            scale_method=b.get("scale_method", "lanczos"),
            crop_mode=b.get("crop_mode", "center"),
        )

        # 🛡️ 护城河：步数边界校验，防止 ODE 时间步崩塌
        total_steps = b["steps"]
        high_steps = b["high_noise_steps"]
        if high_steps >= total_steps:
            high_steps = total_steps - 1
            print(f"⚠️ [XB-BOX] 拦截到致命参数：强制修正 high_noise_steps 为 {high_steps}")

        print(f"🔥 [XB-BOX] Samping Layer 1 (0 -> {high_steps} steps)...")
        latent_high, = nodes.KSamplerAdvanced().sample(
            model=b["model_high"], add_noise="enable", noise_seed=seed,
            steps=total_steps, cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent,
            start_at_step=0, end_at_step=high_steps, return_with_leftover_noise="enable" 
        )

        print(f"❄️ [XB-BOX] Samping Layer 2 ({high_steps} -> {total_steps})...")
        latent_low, = nodes.KSamplerAdvanced().sample(
            model=b["model_low"], add_noise="disable", noise_seed=seed, 
            steps=total_steps, cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent_high, 
            start_at_step=high_steps, end_at_step=total_steps, return_with_leftover_noise="disable"
        )

        decoded_image, = nodes.VAEDecode().decode(
            samples=latent_low, 
            vae=b["vae"], 
        )

        is_4d = len(decoded_image.shape) == 4
        frame_dim = 0 if is_4d else 1
        total_frames = decoded_image.shape[frame_dim]

        if cut_first_frame and total_frames > 1:
            safe_trim = min(trim_head_frames, total_frames - 1)
            if safe_trim > 0:
                if is_4d:
                    decoded_image = decoded_image[safe_trim:, :, :, :]
                else:
                    decoded_image = decoded_image[:, safe_trim:, :, :, :]

        last_frame = decoded_image[-1:, :, :, :] if is_4d else decoded_image[:, -1:, :, :, :]

        # 👑 全序列渐变补偿：start_image 做锚点（接力中=上一段修正尾帧，同色彩空间）
        decoded_image = _apply_progressive_color_correction(decoded_image, start_image, is_4d)
        last_frame = decoded_image[-1:, :, :, :] if is_4d else decoded_image[:, -1:, :, :, :]
        print("✨ [XB-BOX] 触发抗衰减机制：已应用全序列 3D VAE 曝光漂移渐变补偿！")

        concat_dim = 0 if is_4d else 1
        
        final_video = _safe_video_accumulate(prev_video, decoded_image, concat_dim, label="Relay")

        _refresh_models()
        return (wan_bus, last_frame, final_video)


# ============================================================
# XB_Wan_InfiniteRelayNode — Wan 无限长接力点
# ============================================================
class XB_Wan_InfiniteRelayNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wan_bus": ("WAN_BUS",),  
                "start_image": ("IMAGE",),
                "positive_prompt": ("STRING", {"multiline": True, "default": "Describe the specific action for this segment..."}),
            },
            "optional": {
                "prev_video": ("IMAGE",)
            }
        }
        
    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True 

    RETURN_TYPES = ("WAN_BUS", "IMAGE", "IMAGE")
    RETURN_NAMES = ("📦 WAN_BUS (Pass to next)", "🖼️ Current End Image (Connect to next Start Image)", "🎞️ Accumulated Video Stream")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_bus, start_image, positive_prompt, prev_video=None):
        print("\n🏃‍♀️ [XB-BOX] Executing Image-to-Video Infinite pipeline generation task...")
        b = wan_bus
        seed = b["seed"]
        cut_first_frame = b.get("cut_first_frame", True)
        trim_head_frames = b.get("trim_head_frames", 1)

        encode_tile = b.get("vae_encode_tile_size", b.get("vae_tile_size", 64))
        decode_tile = b.get("vae_decode_tile_size", b.get("vae_tile_size", 64))
        spat_overlap = b.get("spatial_overlap", 32)
        temp_chunk = b.get("temporal_chunk_size", 64)
        temp_overlap = b.get("temporal_overlap", 8)

        pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], positive_prompt)
        neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b["negative_prompt"])

        cv_output = b.get("clip_vision_output")
        pos, neg, latent = XB_WanImageToVideo().process(
            positive=pos_cond, negative=neg_cond, vae=b["vae"], 
            clip_vision_output=cv_output, start_image=start_image, 
            width=b["width"], height=b["height"], length=b["length"], 
            batch_size=1, vae_tile_size=encode_tile,
            scale_method=b.get("scale_method", "lanczos"),
            crop_mode=b.get("crop_mode", "center"),
        )

        # 🛡️ 护城河：步数边界校验，防止 ODE 时间步崩塌
        total_steps = b["steps"]
        high_steps = b["high_noise_steps"]
        if high_steps >= total_steps:
            high_steps = total_steps - 1
            print(f"⚠️ [XB-BOX] 拦截到致命参数：强制修正 high_noise_steps 为 {high_steps}")

        print(f"🔥 [XB-BOX] Samping Layer 1 (0 -> {high_steps} steps)...")
        latent_high, = nodes.KSamplerAdvanced().sample(
            model=b["model_high"], add_noise="enable", noise_seed=seed,
            steps=total_steps, cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent,
            start_at_step=0, end_at_step=high_steps, return_with_leftover_noise="enable" 
        )

        print(f"❄️ [XB-BOX] Samping Layer 2 ({high_steps} -> {total_steps})...")
        latent_low, = nodes.KSamplerAdvanced().sample(
            model=b["model_low"], add_noise="disable", noise_seed=seed, 
            steps=total_steps, cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent_high, 
            start_at_step=high_steps, end_at_step=total_steps, return_with_leftover_noise="disable"
        )

        decoded_image, = nodes.VAEDecode().decode(
            samples=latent_low, 
            vae=b["vae"], 
        )

        is_4d = len(decoded_image.shape) == 4
        frame_dim = 0 if is_4d else 1
        total_frames = decoded_image.shape[frame_dim]

        if cut_first_frame and total_frames > 1:
            safe_trim = min(trim_head_frames, total_frames - 1)
            if safe_trim > 0:
                if is_4d:
                    decoded_image = decoded_image[safe_trim:, :, :, :]
                else:
                    decoded_image = decoded_image[:, safe_trim:, :, :, :]

        last_frame = decoded_image[-1:, :, :, :] if is_4d else decoded_image[:, -1:, :, :, :]

        # 👑 全序列渐变补偿：start_image 做锚点（接力中=上一段修正尾帧，同色彩空间）
        decoded_image = _apply_progressive_color_correction(decoded_image, start_image, is_4d)
        last_frame = decoded_image[-1:, :, :, :] if is_4d else decoded_image[:, -1:, :, :, :]
        print("✨ [XB-BOX] 触发抗衰减机制：已应用全序列 3D VAE 曝光漂移渐变补偿！")

        concat_dim = 0 if is_4d else 1
        
        final_video = _safe_video_accumulate(prev_video, decoded_image, concat_dim, label="InfiniteRelay")

        _refresh_models()
        return (wan_bus, last_frame, final_video)


# ============================================================
# XB_Video_Merger — 视频拼接器
# ============================================================
class XB_Video_Merger:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {"required": {}, "optional": {}}
        for i in range(1, 11):
            inputs["optional"][f"video_{i}"] = ("IMAGE",)
        return inputs
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("🎞️ Full Long Video",)
    FUNCTION = "merge_videos"
    CATEGORY = "XB_ToolBox/Pipeline"

    def merge_videos(self, **kwargs):
        videos = [kwargs.get(f"video_{i}") for i in range(1, 11) if kwargs.get(f"video_{i}") is not None]
        if not videos: 
            raise ValueError("🚨 [XB-BOX] Merge failed: At least one video must be connected!")
        
        concat_dim = 0 if len(videos[0].shape) == 4 else 1
        ref_shape = list(videos[0].shape)
        for i, vid in enumerate(videos):
            for d in range(len(ref_shape)):
                if d != concat_dim and vid.shape[d] != ref_shape[d]:
                    raise ValueError(
                        f"🚨 [XB-BOX] Merge failed: Video segment {i+1} shape {list(vid.shape)} "
                        f"does not match first segment shape {ref_shape} on dimension {d} "
                        f"(expected {ref_shape[d]}, got {vid.shape[d]})"
                    )
        # 将全部视频段卸载到 CPU 再拼接，防止多段同时驻留 VRAM 导致 OOM
        videos_cpu = [v.cpu() for v in videos]
        merged = torch.cat(videos_cpu, dim=concat_dim)
        print(f"💾 [XB-BOX] Merger: {len(videos)} 段视频已在 CPU 完成拼接 (shape={list(merged.shape)})")
        return (merged,)

# ============================================================
# XB_StoryboardSlicer — 分镜切片器
# ============================================================
class XB_StoryboardSlicer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": (["3-Grid (1x3 Horizontal)", "3-Grid (3x1 Vertical)", "4-Grid (2x2)", "6-Grid (2x3 Horizontal)", "6-Grid (3x2 Vertical)", "9-Grid (3x3)"], {"default": "4-Grid (2x2)"}),
                "crop_margin": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 0.45, "step": 0.01}),
            }
        }
    RETURN_TYPES = ("IMAGE",) * 9
    RETURN_NAMES = ("Img1", "Img2", "Img3", "Img4", "Img5", "Img6", "Img7", "Img8", "Img9")
    FUNCTION = "slice_image"
    CATEGORY = "XB_ToolBox/Pipeline"

    def slice_image(self, image, mode, crop_margin):
        if "1x3" in mode: rows, cols = 1, 3
        elif "3x1" in mode: rows, cols = 3, 1
        elif "2x2" in mode: rows, cols = 2, 2
        elif "2x3" in mode: rows, cols = 2, 3
        elif "3x2" in mode: rows, cols = 3, 2
        elif "3x3" in mode: rows, cols = 3, 3
        else: rows, cols = 2, 2 

        batch_size, h, w, channels = image.shape
        slice_h, slice_w = h // rows, w // cols
        crop_y, crop_x = int(slice_h * crop_margin), int(slice_w * crop_margin)

        sliced_images = []
        for r in range(rows):
            for c in range(cols):
                sy, ey = r * slice_h + crop_y, (r + 1) * slice_h - crop_y
                sx, ex = c * slice_w + crop_x, (c + 1) * slice_w - crop_x
                if sy >= ey: ey = sy + 1
                if sx >= ex: ex = sx + 1
                sliced_images.append(image[:, sy:ey, sx:ex, :])

        placeholder_h = max(1, slice_h - crop_y * 2)
        placeholder_w = max(1, slice_w - crop_x * 2)
        while len(sliced_images) < 9:
            sliced_images.append(torch.zeros((1, placeholder_h, placeholder_w, 3), dtype=torch.float32, device=image.device))
        return tuple(sliced_images)


# ============================================================
# XB_WanAnimate_ParamBus — Wan Animate 动作迁移参数总线
# ============================================================
class XB_WanAnimate_ParamBus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "negative_prompt": ("STRING", {"multiline": True, "default": "vivid colors, overexposed, static, blurry details..."}),
                "width": ("INT", {"default": 480, "min": 260, "step": 16}),
                "height": ("INT", {"default": 832, "step": 16}),
                "total_frames": ("INT", {"default": 0, "min": 0, "max": 999999, "tooltip": "0=自动从源视频取长度；>0=强制截断到此帧数"}),
                "fps": ("FLOAT", {"default": 16.0}),
                # --- VAE 时空分块与重叠参数 ---
                "vae_encode_tile_size": ("INT", {"default": 320, "step": 32}),
                "vae_decode_tile_size": ("INT", {"default": 320, "step": 32}),
                "spatial_overlap": ("INT", {"default": 32, "step": 32}),
                "temporal_chunk_size": ("INT", {"default": 64, "step": 4}),
                "temporal_overlap": ("INT", {"default": 8, "step": 4}),
                # --- 采样与控制 ---
                "steps": ("INT", {"default": 20, "min": 1, "max": 100}),
                "cfg": ("FLOAT", {"default": 5.0, "step": 0.1}),
                "sampler_name": (comfy.samplers.KSAMPLER_NAMES, ),
                "scheduler": (comfy.samplers.SCHEDULER_NAMES, ),
                "seed": ("INT", {"default": 123456789}),
                "continue_motion_max_frames": ("INT", {"default": 5, "min": 0, "max": 16}),
                # --- 显存清理 ---
                "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "双次缓存清理"}),
                # --- CLIP视觉 ---
                "clip_vision": ("CLIP_VISION",),
            },
            "optional": {
                "global_ref_image": ("IMAGE",),
                "pose_video": ("IMAGE",),
                "face_video": ("IMAGE",),
                "background_video": ("IMAGE",),
                "character_mask": ("MASK",),
                "concat_mode": (["自动", "强制GPU", "强制CPU"], {"default": "自动", "tooltip": "视频累积拼接位置"}),
                "scale_method": (["lanczos", "bilinear", "bicubic", "nearest-exact", "area"], {"default": "lanczos"}),
                "crop_mode": (["center", "disabled"], {"default": "center"}),
            }
        }

    RETURN_TYPES = ("WAN_ANIMATE_BUS",)
    RETURN_NAMES = ("📦 WAN_ANIMATE_BUS",)
    FUNCTION = "pack_bus"
    CATEGORY = "XB_ToolBox/Pipeline"

    def pack_bus(self, **kwargs):
        kwargs["current_offset"] = 0
        cv = kwargs.get("clip_vision")
        ref = kwargs.get("global_ref_image")
        if cv is not None and ref is not None:
            w, h = kwargs.get("width", 480), kwargs.get("height", 832)
            m = kwargs.get("scale_method", "lanczos")
            c = kwargs.get("crop_mode", "center")
            scaled = comfy.utils.common_upscale(ref.movedim(-1, 1), w, h, m, c).movedim(1, -1)
            kwargs["clip_vision_output"], = nodes.CLIPVisionEncode().encode(cv, scaled, "center")
            print(f"👁️ [XB-BOX] Animate CLIP视觉编码 ({ref.shape[1]}×{ref.shape[2]} → {w}×{h}, {m}/{c})")
        return (kwargs,)


# ============================================================
# XB_WanAnimate_RelayNode — Wan Animate 无限接力点
# ============================================================
class XB_WanAnimate_RelayNode:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))] if os.path.exists(input_dir) else []
        files = sorted(files)

        if not files:
            files = ["[Folder empty_Please connect or upload]"]

        return {
            "required": {
                "wan_animate_bus": ("WAN_ANIMATE_BUS",),
                "segment_length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 1}),
                "positive_prompt": ("STRING", {"multiline": True, "default": "Describe the scene..."}),
                "use_local_ref_image": (["继承总线全局图", "独立参考图"], {"default": "继承总线全局图"}),
                "ref_image_file": (files, {"image_upload": True}),
            },
            "optional": {
                "prev_video": ("IMAGE",),
            }
        }
        
    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True 

    RETURN_TYPES = ("WAN_ANIMATE_BUS", "IMAGE")
    RETURN_NAMES = ("📦 WAN_ANIMATE_BUS (传给下段)", "🎞️ 累加视频流")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_animate_bus, segment_length, positive_prompt, use_local_ref_image, ref_image_file, prev_video=None, opt_ref_image=None):
        b = wan_animate_bus.copy()
        current_offset = b.get("current_offset", 0)
        seed = b.get("seed", 123456789)

        source_video = b.get("pose_video") if b.get("pose_video") is not None else b.get("face_video")
        total_source_frames = float('inf')

        # 优先使用总线 total_frames，其次用源视频长度
        bus_total = b.get("total_frames", 0)
        if bus_total > 0:
            total_source_frames = bus_total
        elif source_video is not None:
            total_source_frames = source_video.shape[0] if len(source_video.shape) == 4 else source_video.shape[1]

        remaining_frames = max(0, total_source_frames - current_offset)
        cont_max = b.get("continue_motion_max_frames", 5)

        if remaining_frames <= 0:
            print(f"\n⏭️ [XB-BOX] 动作视频已耗尽 (已跑到 {current_offset} 帧 / 总 {total_source_frames} 帧)。当前接力点直接跳过！")
            fallback_video = prev_video if prev_video is not None else torch.zeros((1, b.get("height", 832), b.get("width", 480), 3))
            return (b, fallback_video)

        if remaining_frames < segment_length:
            # 最后一段：trim 会吃掉 continue_motion 帧，需补回；再对齐 4N+1
            if current_offset == 0:
                need_raw = remaining_frames  # 第一段无 trim
            else:
                need_raw = remaining_frames + cont_max
            actual_length = ((need_raw + 2) // 4) * 4 + 1
            if actual_length < 1:
                print(f"⏭️ [XB-BOX] 剩余 {remaining_frames} 帧不足以生成最小段，跳过")
                fallback_video = prev_video if prev_video is not None else torch.zeros((1, b.get("height", 832), b.get("width", 480), 3))
                return (b, fallback_video)
            print(f"\n⚠️ [XB-BOX] 最后一段: 剩余 {remaining_frames} → need_raw={need_raw} → {actual_length} 帧 (4N+1)")
        else:
            actual_length = segment_length
            print(f"\n🏃‍♀️ [XB-BOX] Executing Wan Animate Relay task... Target segment length: {actual_length}")

        is_local = (use_local_ref_image == "独立参考图" or 
                    use_local_ref_image is True or 
                    use_local_ref_image == 1)
        if is_local:
            if not ref_image_file or ref_image_file == "[Folder empty_Please connect or upload]":
                print("⏭️  [XB-BOX] 已开启独立参考图但未选择图片文件，跳过当前 Animate 接力点。")
                return (b, prev_video if prev_video is not None else torch.zeros((1, b.get("height", 832), b.get("width", 480), 3)))
            image_path = folder_paths.get_annotated_filepath(ref_image_file)
            if not os.path.exists(image_path):
                print(f"⏭️  [XB-BOX] 独立参考图文件未找到: {os.path.basename(image_path)}，跳过当前 Animate 接力点。")
                return (b, prev_video if prev_video is not None else torch.zeros((1, b.get("height", 832), b.get("width", 480), 3)))
            i = Image.open(image_path)
            i = ImageOps.exif_transpose(i)
            image_data = i.convert("RGB")
            image_data = np.array(image_data).astype(np.float32) / 255.0
            ref_image = torch.from_numpy(image_data)[None,]
            cv_model = b.get("clip_vision")
            if cv_model is None:
                raise ValueError("🚨 [XB-BOX] 使用独立参考图需要总线连接 clip_vision 模型！")
            # CLIP 编码用总线缩放参数，不做预缩放（XB_WanAnimateToVideo 内部自己处理 VAE 编码）
            w, h = b.get("width", 480), b.get("height", 832)
            sm = b.get("scale_method", "lanczos")
            cm = b.get("crop_mode", "center")
            clip_img = comfy.utils.common_upscale(ref_image.movedim(-1, 1), w, h, sm, cm).movedim(1, -1)
            clip_vision_output, = nodes.CLIPVisionEncode().encode(cv_model, clip_img, "center")
            print("🖼️ [XB-BOX] 使用独立参考图（含独立CLIP视觉编码）。")
        else:
            ref_image = b.get("global_ref_image")
            if ref_image is None:
                raise ValueError("🚨 [XB-BOX] 缺少参考图！请开启独立参考图选择图片，或在总线上连接 global_ref_image。")
            clip_vision_output = b.get("clip_vision_output")
            print("🌐 [XB-BOX] 使用总线全局参考图。")

        prompt_text = positive_prompt.strip() if positive_prompt.strip() else b.get("positive_prompt", "")
        pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], prompt_text)
        neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b.get("negative_prompt", ""))

        continue_motion = None
        cont_max_frames = b.get("continue_motion_max_frames", 5)
        if is_local:
            cont_max_frames = 0  # 独立参考图时关闭衔接帧，避免CLIP视觉特征冲突
        if prev_video is not None and cont_max_frames > 0:
            is_4d = len(prev_video.shape) == 4
            if is_4d:
                continue_motion = prev_video[-cont_max_frames:, :, :, :]
            else:
                continue_motion = prev_video[:, -cont_max_frames:, :, :, :]

        try:
            from .nodes_wan import XB_WanAnimateToVideo
        except ImportError:
            raise ImportError("🚨 [XB-BOX] 找不到 XB_WanAnimateToVideo 底座节点，请检查 nodes_wan.py 文件目录！")

        animate_core = XB_WanAnimateToVideo()
        func_name = getattr(XB_WanAnimateToVideo, "FUNCTION", "process")
        func = getattr(animate_core, func_name)

        kwargs = {
            "positive": pos_cond,
            "negative": neg_cond,
            "vae": b["vae"],
            "clip_vision_output": clip_vision_output,
            "reference_image": ref_image,
            "face_video": b.get("face_video"),
            "pose_video": b.get("pose_video"),
            "background_video": b.get("background_video"),
            "character_mask": b.get("character_mask"),
            "continue_motion": continue_motion,
            "width": b["width"],
            "height": b["height"],
            "length": actual_length,
            "batch_size": 1,
            "continue_motion_max_frames": cont_max_frames,
            "video_frame_offset": current_offset, 
            "vae_tile_size": b.get("vae_encode_tile_size", 320)
        }

        pos, neg, latent, trim_latent, trim_image, new_offset = func(**kwargs)

        print(f"🔥 [XB-BOX] Animate Single-Pass Sampling ({b['steps']} steps)...")
        latent_sampled, = nodes.KSampler().sample(
            model=b["model"], 
            seed=seed,
            steps=b["steps"], 
            cfg=b["cfg"], 
            sampler_name=b["sampler_name"], 
            scheduler=b["scheduler"],
            positive=pos, 
            negative=neg, 
            latent_image=latent,
            denoise=1.0  
        )

        trim_latent_val = trim_latent if trim_latent is not None else 0
        if trim_latent_val > 0:
            latent_sampled["samples"] = latent_sampled["samples"][:, :, trim_latent_val:, :, :]

        try:
            from .nodes_rocm import XB_ROCmVAEDecodeTemporal
        except ImportError:
            raise ImportError("🚨 [XB-BOX] 找不到 XB_ROCmVAEDecodeTemporal，请确保 nodes_rocm.py 未被删除！")

        cleanup_mode = b.get("cleanup", "双次缓存清理")
        decoder = XB_ROCmVAEDecodeTemporal()
        decoded_image, = decoder.go(
            samples=latent_sampled,
            vae=b["vae"],
            tile=b.get("vae_decode_tile_size", 320),
            overlap=b.get("spatial_overlap", 32),
            t_tile=b.get("temporal_chunk_size", 64),
            t_overlap=b.get("temporal_overlap", 8),
            cleanup=cleanup_mode
        )

        is_4d = len(decoded_image.shape) == 4
        concat_dim = 0 if is_4d else 1

        # 像素层裁切重叠过渡帧（trim_image 对应 continue_motion_max_frames）
        trim_px = int(trim_image) if trim_image else 0
        if trim_px > 0 and trim_px < decoded_image.shape[concat_dim]:
            if is_4d:
                decoded_image = decoded_image[trim_px:, :, :, :]
            else:
                decoded_image = decoded_image[:, trim_px:, :, :, :]
            print(f"✂️ [XB-BOX] 像素裁切重叠: {trim_px} 帧")

        final_video = _safe_video_accumulate(prev_video, decoded_image, concat_dim, label="AnimateRelay")

        actual_out = decoded_image.shape[concat_dim]
        b["current_offset"] = current_offset + actual_out
        print(f"✅ [XB-BOX] Animate Relay Complete. trim_lat={trim_latent_val} trim_px={trim_px} out={actual_out}f total={final_video.shape[concat_dim]}f")

        return (b, final_video)


# ============================================================
# XB_WanInfiniteTalk_ParamBus — InfiniteTalk 无限对口型参数总线
# ============================================================
class XB_WanInfiniteTalk_ParamBus:
    """
    集中管理所有共享参数。内置音频编码器 + CLIP 视觉编码。
    接力点只需传正面提示词 + 分段帧数 + 音频，其余全从总线走。
    """
    _SCALE_METHODS = ["bilinear", "bicubic", "lanczos", "nearest-exact", "area"]
    _CROP_MODES = ["center", "disabled"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # --- 模型 ---
                "model": ("MODEL",),
                "model_patch": ("MODEL_PATCH",),
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "audio_encoder": ("AUDIO_ENCODER",),
                # --- CLIP视觉 ---
                "clip_vision": ("CLIP_VISION",),
                # --- 基础参数 ---
                "negative_prompt": ("STRING", {"multiline": True, "default": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"}),
                "width": ("INT", {"default": 832, "min": 260, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "total_frames": ("INT", {"default": 0, "min": 0, "max": 999999, "tooltip": "总线音频模式：音频切片节点输出的总帧数，耗尽后自动停止接力。0=独立音频模式"}),
                "fps": ("FLOAT", {"default": 25.0, "min": 1.0, "max": 120.0, "step": 1.0}),
                # --- VAE 分块 ---
                "vae_encode_tile_size": ("INT", {"default": 256, "min": 0, "max": 3840, "step": 32}),
                "vae_decode_tile_size": ("INT", {"default": 192, "min": 0, "max": 3840, "step": 32}),
                "spatial_overlap": ("INT", {"default": 32, "min": 0, "max": 3840, "step": 32}),
                "temporal_chunk_size": ("INT", {"default": 96, "min": 0, "max": 8192, "step": 4}),
                "temporal_overlap": ("INT", {"default": 4, "min": 0, "max": 8192, "step": 4}),
                # --- 采样 ---
                "steps": ("INT", {"default": 4, "min": 1, "max": 100}),
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "sampler_name": (comfy.samplers.KSAMPLER_NAMES,),
                "scheduler": (comfy.samplers.SCHEDULER_NAMES,),
                "seed": ("INT", {"default": 123456789}),
                # --- InfiniteTalk ---
                "motion_frame_count": ("INT", {"default": 9, "min": 1, "max": 33, "step": 1}),
                "audio_scale": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
                # --- 缩放 ---
                "scale_method": (cls._SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (cls._CROP_MODES, {"default": "center"}),
                # --- 清理 ---
                "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "双次缓存清理"}),
            },
            "optional": {
                "start_image": ("IMAGE",),
                "audio": ("AUDIO", {"tooltip": "总线音频模式：接入长音频，总线一次性编码，接力点自动分段"}),
                "concat_mode": (["自动", "强制GPU", "强制CPU"], {"default": "自动", "tooltip": "视频累积拼接位置"}),
            },
        }

    RETURN_TYPES = ("WAN_INFINITETALK_BUS",)
    RETURN_NAMES = ("📦 WAN_INFINITETALK_BUS",)
    FUNCTION = "pack_bus"
    CATEGORY = "XB_ToolBox/Pipeline"

    def pack_bus(self, **kwargs):
        # CLIP 视觉编码：先缩放到视频尺寸，再按 crop 模式处理
        cv = kwargs.get("clip_vision")
        ref = kwargs.get("start_image")
        if cv is not None and ref is not None:
            w, h = kwargs["width"], kwargs["height"]
            method = kwargs.get("scale_method", "lanczos")
            crop = kwargs.get("crop_mode", "center")
            scaled = comfy.utils.common_upscale(ref.movedim(-1, 1), w, h, method, crop).movedim(1, -1)
            kwargs["clip_vision_output"], = nodes.CLIPVisionEncode().encode(cv, scaled, "center")
            print(f"👁️ [XB-BOX] CLIP视觉编码: {ref.shape[1]}×{ref.shape[2]} → {w}×{h} ({method}/{crop})")
        else:
            kwargs["clip_vision_output"] = None

        # --- 总线音频模式：接入长音频 + 总帧数则一次性编码 ---
        audio_input = kwargs.get("audio")
        total_frames = kwargs.get("total_frames", 0)
        if audio_input is not None and total_frames > 0:
            ae_cls = nodes.NODE_CLASS_MAPPINGS.get("AudioEncoderEncode")
            if ae_cls is None:
                raise ImportError("AudioEncoderEncode not found")
            ae = ae_cls()
            kwargs["_encoded_audio"], = getattr(ae, ae.FUNCTION)(kwargs["audio_encoder"], audio_input)
            kwargs["_raw_audio"] = audio_input  # 保留原始波形用于输出拼接
            kwargs["_total_frames"] = total_frames
            kwargs["_accumulated_frames"] = 0
            kwargs["_bus_audio_mode"] = True
            print(f"🔊 [XB-BOX] 总线音频模式：已编码长音频，总目标 {total_frames} 帧 ({total_frames/kwargs['fps']:.1f}s)")
        else:
            kwargs["_bus_audio_mode"] = False

        kwargs["_previous_frames"] = None
        kwargs["_global_frame_offset"] = 0
        return (kwargs,)


# ============================================================
# XB_WanInfiniteTalk_RelayNode — InfiniteTalk 无限对口型接力点
# ============================================================
class XB_WanInfiniteTalk_RelayNode:
    """
    每个接力点完成：CLIPTextEncode → WanInfiniteTalkToVideo_Single → KSampler → VAEDecode → trim → 累加。
    音频独立输入 + 自动裁剪重叠 + 累加输出，与视频帧对齐。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wan_infinitetalk_bus": ("WAN_INFINITETALK_BUS",),
                "positive_prompt": ("STRING", {"multiline": True, "default": ""}),
                "segment_length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
            },
            "optional": {
                "prev_video": ("IMAGE",),
                "prev_audio": ("AUDIO",),
                "audio": ("AUDIO",),
            }
        }

    RETURN_TYPES = ("WAN_INFINITETALK_BUS", "IMAGE", "AUDIO")
    RETURN_NAMES = ("📦 WAN_INFINITETALK_BUS (传给下段)", "🎞️ 累加视频流", "🔊 累加音频流")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_infinitetalk_bus, positive_prompt, segment_length,
                      prev_video=None, prev_audio=None, audio=None):
        b = wan_infinitetalk_bus.copy()
        motion = b.get("motion_frame_count", 9)
        fps = b.get("fps", 25.0)
        bus_audio_mode = b.get("_bus_audio_mode", False)

        # ================================================================
        # 🛡️ 模式判断 & 帧数计算
        # ================================================================
        if bus_audio_mode:
            # --- 模式1：总线音频模式 ---
            total_frames = b["_total_frames"]
            accumulated = b["_accumulated_frames"]
            remaining = total_frames - accumulated

            if remaining <= 0:
                print(f"\n⏭️ [XB-BOX] 总线帧数已耗尽 ({accumulated}/{total_frames})，跳过接力点")
                fb_video = prev_video if prev_video is not None else torch.zeros((1, b["height"], b["width"], 3))
                fb_audio = prev_audio if prev_audio is not None else {"waveform": torch.zeros((1, 1)), "sample_rate": 44100}
                return (b, fb_video, fb_audio)

            if remaining < segment_length:
                # 最后一段：trim 会吃掉 motion 帧，需补回；再对齐 4N+1
                if accumulated == 0:
                    need_raw = remaining  # 第一段无 trim
                else:
                    need_raw = remaining + motion
                actual_length = ((need_raw + 2) // 4) * 4 + 1
                if actual_length < 1:
                    print(f"⏭️ [XB-BOX] 剩余 {remaining} 帧不足以生成最小段，跳过")
                    fb_video = prev_video if prev_video is not None else torch.zeros((1, b["height"], b["width"], 3))
                    fb_audio = prev_audio if prev_audio is not None else {"waveform": torch.zeros((1, 1)), "sample_rate": 44100}
                    return (b, fb_video, fb_audio)
                print(f"\n⚠️ [XB-BOX] 最后一段: 剩余 {remaining} → need_raw={need_raw} → {actual_length} 帧 (4N+1)")
            else:
                actual_length = segment_length

            encoded_audio = b["_encoded_audio"]
            raw_audio = b.get("_raw_audio")
            use_segment_audio = False  # 用 offset 方式裁剪长音频
            print(f"\n🔊 [XB-BOX] 总线音频接力: 偏移 {accumulated} 帧, 生成长度 {actual_length} 帧 ({accumulated}/{total_frames})")
        else:
            # --- 模式2：独立音频模式 ---
            if audio is None:
                print("\n⏭️ [XB-BOX] 无音频输入，跳过接力点")
                fb_video = prev_video if prev_video is not None else torch.zeros((1, b["height"], b["width"], 3))
                fb_audio = prev_audio if prev_audio is not None else {"waveform": torch.zeros((1, 1)), "sample_rate": 44100}
                return (b, fb_video, fb_audio)

            actual_length = segment_length
            encoded_audio = None  # 下面编码
            raw_audio = audio
            use_segment_audio = True  # 每段独立音频从头开始
            print(f"\n🎵 [XB-BOX] 独立音频接力: 生成长度 {actual_length} 帧")

        # --- 🛡️ 帧数对齐：Wan 模型要求 length = 4n+1 ---
        raw_length = actual_length
        aligned_length = ((actual_length + 2) // 4) * 4 + 1
        if aligned_length != raw_length:
            print(f"⚠️ [XB-BOX] 帧数对齐: {raw_length} → {aligned_length} (4n+1)")
            # 总线模式下不补音频（已编码），独立模式下补静音
            if not bus_audio_mode and audio is not None:
                pad_frames = aligned_length - raw_length
                pad_sec = pad_frames / fps
                sr = audio["sample_rate"]
                pad_samples = int(pad_sec * sr)
                pad_wf = torch.zeros((audio["waveform"].shape[0], pad_samples), dtype=audio["waveform"].dtype, device=audio["waveform"].device)
                raw_audio = {"waveform": torch.cat([audio["waveform"], pad_wf], dim=-1), "sample_rate": sr}
        actual_length = aligned_length

        # --- 音频编码（独立模式） ---
        if not bus_audio_mode:
            ae_cls = nodes.NODE_CLASS_MAPPINGS.get("AudioEncoderEncode")
            if ae_cls is None:
                raise ImportError("AudioEncoderEncode not found")
            ae = ae_cls()
            encoded_audio, = getattr(ae, ae.FUNCTION)(b["audio_encoder"], raw_audio)

        # --- 提示词 ---
        pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], positive_prompt)
        neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b["negative_prompt"])

        # --- InfiniteTalk 底座 ---
        prev = b.get("_previous_frames")

        # 🛡️ 总线模式：直接传递全局帧偏移量给底层，彻底废弃巨型 dummy tensor
        #     _process_infinite_talk_audio 现在接收 global_frame_offset 参数，
        #     不再依赖 previous_frames.shape[0] 来反推音频偏移
        global_frame_offset = None
        if bus_audio_mode:
            global_frame_offset = b["_accumulated_frames"]

        core = XB_WanInfiniteTalkToVideo_Single()

        # � _process_infinite_talk_audio 内部已通过 model.clone() 保护原模型，
        #    无需手动 save/restore——异常中断时 clone 自动被 GC 回收
        model_out, pos, neg, latent, trim = core.process(
            model=b["model"], model_patch=b["model_patch"],
            positive=pos_cond, negative=neg_cond, vae=b["vae"],
            width=b["width"], height=b["height"], length=actual_length,
            audio_encoder_output_1=encoded_audio,
            motion_frame_count=motion, audio_scale=b["audio_scale"],
            vae_tile_size=b["vae_encode_tile_size"],
            clip_vision_output=b.get("clip_vision_output"),
            start_image=b.get("start_image"), previous_frames=prev,
            segment_audio=use_segment_audio,
            global_frame_offset=global_frame_offset,
            scale_method=b.get("scale_method", "lanczos"),
            crop_mode=b.get("crop_mode", "center"),
        )

        # --- 采样 ---
        latent_out, = nodes.KSampler().sample(
            model=model_out, seed=b["seed"],
            steps=b["steps"], cfg=b["cfg"],
            sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent, denoise=1.0,
        )

        # --- 解码 ---
        decoded, = nodes.VAEDecode().decode(samples=latent_out, vae=b["vae"])

        # --- 视频裁剪累加 ---
        is4d = len(decoded.shape) == 4
        cd = 0 if is4d else 1
        total = decoded.shape[cd]
        b["_previous_frames"] = decoded

        trim_val = int(trim) if trim else 0
        trim_val = min(trim_val, total - 1) if trim_val < total else 0
        cut = decoded[trim_val:] if is4d else decoded[:, trim_val:]
        final_video = _safe_video_accumulate(prev_video, cut, cd, label="TalkRelay")

        # --- 音频裁剪累加 ---
        ats = trim_val / fps if trim_val else 0.0
        if bus_audio_mode:
            # 总线模式：从原始长音频中裁出当前段
            raw_wf = raw_audio["waveform"] if raw_audio else torch.zeros((1, 1))
            raw_sr = raw_audio["sample_rate"] if raw_audio else 44100
            seg_start_sample = int(b["_accumulated_frames"] / fps * raw_sr)
            seg_end_sample = int((b["_accumulated_frames"] + cut.shape[cd]) / fps * raw_sr)
            seg_end_sample = min(seg_end_sample, raw_wf.shape[-1])
            cut_audio = {"waveform": raw_wf[..., seg_start_sample:seg_end_sample], "sample_rate": raw_sr} if seg_end_sample > seg_start_sample else None
        else:
            cut_audio = raw_audio
            if ats > 0 and raw_audio:
                wf = raw_audio["waveform"]
                sr = raw_audio["sample_rate"]
                n = int(ats * sr)
                if n < wf.shape[-1]:
                    cut_audio = {"waveform": wf[..., n:], "sample_rate": sr}
                else:
                    cut_audio = None  # 裁切长度超出自身，彻底丢弃防止音画不同步

        if prev_audio is None:
            final_audio = cut_audio
        elif cut_audio is None:
            final_audio = prev_audio
        else:
            pa, ca = prev_audio, cut_audio
            if pa["sample_rate"] != ca["sample_rate"]:
                if torchaudio is None:
                    raise ImportError("🚨 [XB-BOX] 音频采样率不一致需要 torchaudio 重采样，但 torchaudio 未安装！请运行: pip install torchaudio")
                ca_wf = torchaudio.functional.resample(ca["waveform"], ca["sample_rate"], pa["sample_rate"])
                ca = {"waveform": ca_wf, "sample_rate": pa["sample_rate"]}

            # 🛡️ 设备对齐 + 声道对齐: 防止 torch.cat 因设备/声道不一致崩溃
            pa_wf = pa["waveform"]
            ca_wf = ca["waveform"].to(pa_wf.device)
            if pa_wf.dim() >= 2 and ca_wf.dim() >= 2 and pa_wf.shape[:-1] != ca_wf.shape[:-1]:
                # 🔧 严格针对 Channel 维度 (shape[-2]) 对齐 [B, C, T] 格式
                if pa_wf.shape[-2] == 1 and ca_wf.shape[-2] > 1:
                    rpt = [1] * pa_wf.dim()
                    rpt[-2] = ca_wf.shape[-2]
                    pa_wf = pa_wf.repeat(*rpt)
                elif ca_wf.shape[-2] == 1 and pa_wf.shape[-2] > 1:
                    rpt = [1] * ca_wf.dim()
                    rpt[-2] = pa_wf.shape[-2]
                    ca_wf = ca_wf.repeat(*rpt)

            final_audio = {"waveform": torch.cat([pa_wf, ca_wf], dim=-1),
                           "sample_rate": pa["sample_rate"]}

        b["_global_frame_offset"] = b.get("_global_frame_offset", 0) + cut.shape[cd]
        if bus_audio_mode:
            b["_accumulated_frames"] += cut.shape[cd]
            remaining_after = b["_total_frames"] - b["_accumulated_frames"]
            print(f"🎵 [XB-BOX] Relay done: {total}→{cut.shape[cd]}f (trim {trim_val}), "
                  f"acc={final_video.shape[cd]}f, 总线进度 {b['_accumulated_frames']}/{b['_total_frames']} (剩余 {remaining_after})")
        else:
            print(f"🎵 [XB-BOX] Relay done: {total}→{cut.shape[cd]}f (trim {trim_val}), "
                  f"acc={final_video.shape[cd]}f, video_dur={final_video.shape[cd]/fps:.1f}s")

        _refresh_models()
        return (b, final_video, final_audio)

# ============================================================
# NEW 无限接力节点（带重叠帧数/拼接模式等新功能）
# ============================================================

class XB_Wan_InfiniteRelayNode_New:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wan_bus": ("WAN_BUS",),  
                "start_image": ("IMAGE",),
                "positive_prompt": ("STRING", {"multiline": True, "default": "Describe the specific action for this segment..."}),
                "trim_head_frames": ("INT", {"default": 1, "min": 1, "max": 8192, "step": 1, "tooltip": "接力重叠帧数（去重）"}),
                "relay_count": ("INT", {"default": 1, "min": 1, "max": 999, "step": 1, "tooltip": "接力数量设定：本节点自动循环 N 次 = 串联 N 个接力点"}),
                "total_frames_display": ("STRING", {"default": "", "multiline": False, "tooltip": "总计生成帧数（自动计算）"}),
            },
            "optional": {
                "prev_video": ("IMAGE",)
            }
        }
        
    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True 

    RETURN_TYPES = ("WAN_BUS", "IMAGE", "IMAGE")
    RETURN_NAMES = ("📦 WAN_BUS (Pass to next)", "🖼️ Current End Image (Connect to next Start Image)", "🎞️ Accumulated Video Stream")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_bus, start_image, positive_prompt, trim_head_frames=1, relay_count=1, total_frames_display="", prev_video=None):
        print(f"\n🏃‍♀️ [XB-BOX] Executing Image-to-Video Infinite pipeline × {relay_count} relay(s)...")
        b = wan_bus
        segment_len = b["length"]
        cut_first_frame = b.get("cut_first_frame", True)
        # 估算总计帧数
        est_per_segment = segment_len - (trim_head_frames if cut_first_frame and segment_len > 1 else 0)
        est_total = est_per_segment * relay_count
        print(f"📊 [XB-BOX] 每段约 {est_per_segment} 帧 (原始 {segment_len}), 总计约 {est_total} 帧")

        current_image = start_image
        accumulated_video = prev_video

        for r in range(relay_count):
            seed = b["seed"]
            print(f"\n🔄 [XB-BOX] 接力 {r+1}/{relay_count}...")

            encode_tile = b.get("vae_encode_tile_size", b.get("vae_tile_size", 64))
            decode_tile = b.get("vae_decode_tile_size", b.get("vae_tile_size", 64))

            pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], positive_prompt)
            neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b["negative_prompt"])

            cv_output = b.get("clip_vision_output")
            pos, neg, latent = XB_WanImageToVideo().process(
                positive=pos_cond, negative=neg_cond, vae=b["vae"], 
                clip_vision_output=cv_output, start_image=current_image, 
                width=b["width"], height=b["height"], length=segment_len, 
                batch_size=1, vae_tile_size=encode_tile,
                scale_method=b.get("scale_method", "lanczos"),
                crop_mode=b.get("crop_mode", "center"),
            )

            total_steps = b["steps"]
            high_steps = b["high_noise_steps"]
            if high_steps >= total_steps:
                high_steps = total_steps - 1

            latent_high, = nodes.KSamplerAdvanced().sample(
                model=b["model_high"], add_noise="enable", noise_seed=seed,
                steps=total_steps, cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
                positive=pos, negative=neg, latent_image=latent,
                start_at_step=0, end_at_step=high_steps, return_with_leftover_noise="enable" 
            )

            latent_low, = nodes.KSamplerAdvanced().sample(
                model=b["model_low"], add_noise="disable", noise_seed=seed, 
                steps=total_steps, cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
                positive=pos, negative=neg, latent_image=latent_high, 
                start_at_step=high_steps, end_at_step=total_steps, return_with_leftover_noise="disable"
            )

            decoded_image, = nodes.VAEDecode().decode(samples=latent_low, vae=b["vae"])

            is_4d = len(decoded_image.shape) == 4
            frame_dim = 0 if is_4d else 1
            total_frames = decoded_image.shape[frame_dim]

            if cut_first_frame and total_frames > 1:
                safe_trim = min(trim_head_frames, total_frames - 1)
                if safe_trim > 0:
                    if is_4d:
                        decoded_image = decoded_image[safe_trim:, :, :, :]
                    else:
                        decoded_image = decoded_image[:, safe_trim:, :, :, :]

            last_frame = decoded_image[-1:, :, :, :] if is_4d else decoded_image[:, -1:, :, :, :]

            decoded_image = _apply_progressive_color_correction(decoded_image, current_image, is_4d)
            last_frame = decoded_image[-1:, :, :, :] if is_4d else decoded_image[:, -1:, :, :, :]

            concat_dim = 0 if is_4d else 1
            accumulated_video = _safe_video_accumulate(accumulated_video, decoded_image, concat_dim, label=f"InfiniteRelay-{r+1}", concat_mode=b.get("concat_mode", "自动"))
            current_image = last_frame

        _refresh_models()
        print(f"✅ [XB-BOX] 接力完成: {relay_count} 段, 总计 {accumulated_video.shape[concat_dim]} 帧")
        return (wan_bus, current_image, accumulated_video)


# ============================================================
# XB_Video_Merger — 视频拼接器
# ============================================================
class XB_Video_Merger:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {"required": {}, "optional": {}}
        for i in range(1, 11):
            inputs["optional"][f"video_{i}"] = ("IMAGE",)
        return inputs
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("🎞️ Full Long Video",)
    FUNCTION = "merge_videos"
    CATEGORY = "XB_ToolBox/Pipeline"

    def merge_videos(self, **kwargs):
        videos = [kwargs.get(f"video_{i}") for i in range(1, 11) if kwargs.get(f"video_{i}") is not None]
        if not videos: 
            raise ValueError("🚨 [XB-BOX] Merge failed: At least one video must be connected!")
        
        concat_dim = 0 if len(videos[0].shape) == 4 else 1
        ref_shape = list(videos[0].shape)
        for i, vid in enumerate(videos):
            for d in range(len(ref_shape)):
                if d != concat_dim and vid.shape[d] != ref_shape[d]:
                    raise ValueError(
                        f"🚨 [XB-BOX] Merge failed: Video segment {i+1} shape {list(vid.shape)} "
                        f"does not match first segment shape {ref_shape} on dimension {d} "
                        f"(expected {ref_shape[d]}, got {vid.shape[d]})"
                    )
        # 将全部视频段卸载到 CPU 再拼接，防止多段同时驻留 VRAM 导致 OOM
        videos_cpu = [v.cpu() for v in videos]
        merged = torch.cat(videos_cpu, dim=concat_dim)
        print(f"💾 [XB-BOX] Merger: {len(videos)} 段视频已在 CPU 完成拼接 (shape={list(merged.shape)})")
        return (merged,)

# ============================================================
# XB_StoryboardSlicer — 分镜切片器
# ============================================================
class XB_StoryboardSlicer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": (["3-Grid (1x3 Horizontal)", "3-Grid (3x1 Vertical)", "4-Grid (2x2)", "6-Grid (2x3 Horizontal)", "6-Grid (3x2 Vertical)", "9-Grid (3x3)"], {"default": "4-Grid (2x2)"}),
                "crop_margin": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 0.45, "step": 0.01}),
            }
        }
    RETURN_TYPES = ("IMAGE",) * 9
    RETURN_NAMES = ("Img1", "Img2", "Img3", "Img4", "Img5", "Img6", "Img7", "Img8", "Img9")
    FUNCTION = "slice_image"
    CATEGORY = "XB_ToolBox/Pipeline"

    def slice_image(self, image, mode, crop_margin):
        if "1x3" in mode: rows, cols = 1, 3
        elif "3x1" in mode: rows, cols = 3, 1
        elif "2x2" in mode: rows, cols = 2, 2
        elif "2x3" in mode: rows, cols = 2, 3
        elif "3x2" in mode: rows, cols = 3, 2
        elif "3x3" in mode: rows, cols = 3, 3
        else: rows, cols = 2, 2 

        batch_size, h, w, channels = image.shape
        slice_h, slice_w = h // rows, w // cols
        crop_y, crop_x = int(slice_h * crop_margin), int(slice_w * crop_margin)

        sliced_images = []
        for r in range(rows):
            for c in range(cols):
                sy, ey = r * slice_h + crop_y, (r + 1) * slice_h - crop_y
                sx, ex = c * slice_w + crop_x, (c + 1) * slice_w - crop_x
                if sy >= ey: ey = sy + 1
                if sx >= ex: ex = sx + 1
                sliced_images.append(image[:, sy:ey, sx:ex, :])

        placeholder_h = max(1, slice_h - crop_y * 2)
        placeholder_w = max(1, slice_w - crop_x * 2)
        while len(sliced_images) < 9:
            sliced_images.append(torch.zeros((1, placeholder_h, placeholder_w, 3), dtype=torch.float32, device=image.device))
        return tuple(sliced_images)


# ============================================================
# XB_WanAnimate_ParamBus — Wan Animate 动作迁移参数总线
# ============================================================
class XB_WanAnimate_RelayNode_New:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))] if os.path.exists(input_dir) else []
        files = sorted(files)

        if not files:
            files = ["[Folder empty_Please connect or upload]"]

        return {
            "required": {
                "wan_animate_bus": ("WAN_ANIMATE_BUS",),
                "segment_length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 1}),
                "positive_prompt": ("STRING", {"multiline": True, "default": "Describe the scene..."}),
                "use_local_ref_image": (["继承总线全局图", "独立参考图"], {"default": "继承总线全局图"}),
                "ref_image_file": (files, {"image_upload": True}),
                "continue_motion_max_frames": ("INT", {"default": 5, "min": 0, "max": 16, "tooltip": "接力重叠帧数（衔接过渡）"}),
                "relay_count": ("INT", {"default": 1, "min": 1, "max": 999, "step": 1, "tooltip": "接力数量设定"}),
                "total_frames_display": ("STRING", {"default": "", "multiline": False, "tooltip": "总计生成帧数（自动计算）"}),
            },
            "optional": {
                "prev_video": ("IMAGE",),
            }
        }
        
    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True 

    RETURN_TYPES = ("WAN_ANIMATE_BUS", "IMAGE")
    RETURN_NAMES = ("📦 WAN_ANIMATE_BUS (传给下段)", "🎞️ 累加视频流")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_animate_bus, segment_length, positive_prompt="", use_local_ref_image="继承总线全局图", ref_image_file="", continue_motion_max_frames=5, relay_count=1, total_frames_display="", prev_video=None, opt_ref_image=None):
        b = wan_animate_bus.copy()
        print(f"\n🏃‍♀️ [XB-BOX] Executing Wan Animate Relay × {relay_count} relay(s)... 每段 {segment_length} 帧, 总计约 {segment_length * relay_count} 帧")
        accumulated_video = prev_video

        completed = 0
        for r in range(relay_count):
            current_offset = b.get("current_offset", 0)
            seed = b.get("seed", 123456789)
            print(f"\n🔄 [XB-BOX] Animate 接力 {r+1}/{relay_count} (offset={current_offset})...")

            source_video = b.get("pose_video") if b.get("pose_video") is not None else b.get("face_video")
            total_source_frames = float('inf')
            bus_total = b.get("total_frames", 0)
            if bus_total > 0:
                total_source_frames = bus_total
            elif source_video is not None:
                total_source_frames = source_video.shape[0] if len(source_video.shape) == 4 else source_video.shape[1]

            remaining_frames = max(0, total_source_frames - current_offset)

            if remaining_frames <= 0:
                break

            if remaining_frames < segment_length:
                if current_offset == 0:
                    need_raw = remaining_frames
                else:
                    need_raw = remaining_frames + continue_motion_max_frames
                actual_length = ((need_raw + 2) // 4) * 4 + 1
                if actual_length < 1:
                    break
                print(f"⚠️ [XB-BOX] 最后一段: 剩余 {remaining_frames} → {actual_length} 帧 (4N+1)")
            else:
                actual_length = segment_length

            is_local = (use_local_ref_image in ("独立参考图", True, 1))
            if is_local:
                if not ref_image_file or ref_image_file == "[Folder empty_Please connect or upload]":
                    print("⏭️ [XB-BOX] 独立参考图未选择，跳过")
                    break
                image_path = folder_paths.get_annotated_filepath(ref_image_file)
                if not os.path.exists(image_path):
                    print(f"⏭️ [XB-BOX] 参考图文件未找到，跳过")
                    break
                i = Image.open(image_path)
                i = ImageOps.exif_transpose(i)
                image_data = i.convert("RGB")
                image_data = np.array(image_data).astype(np.float32) / 255.0
                ref_image = torch.from_numpy(image_data)[None,]
                cv_model = b.get("clip_vision")
                if cv_model is None:
                    raise ValueError("🚨 独立参考图需要 clip_vision 模型！")
                w, h = b.get("width", 480), b.get("height", 832)
                sm = b.get("scale_method", "lanczos")
                cm = b.get("crop_mode", "center")
                clip_img = comfy.utils.common_upscale(ref_image.movedim(-1, 1), w, h, sm, cm).movedim(1, -1)
                clip_vision_output, = nodes.CLIPVisionEncode().encode(cv_model, clip_img, "center")
            else:
                ref_image = b.get("global_ref_image")
                if ref_image is None:
                    raise ValueError("🚨 缺少参考图！")
                clip_vision_output = b.get("clip_vision_output")

            prompt_text = positive_prompt.strip() if positive_prompt.strip() else b.get("positive_prompt", "")
            pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], prompt_text)
            neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b.get("negative_prompt", ""))

            continue_motion = None
            cont_max_frames = continue_motion_max_frames
            if is_local:
                cont_max_frames = 0
            if accumulated_video is not None and cont_max_frames > 0:
                is_4d_v = len(accumulated_video.shape) == 4
                if is_4d_v:
                    continue_motion = accumulated_video[-cont_max_frames:, :, :, :]
                else:
                    continue_motion = accumulated_video[:, -cont_max_frames:, :, :, :]

            try:
                from .nodes_wan import XB_WanAnimateToVideo
            except ImportError:
                raise ImportError("🚨 找不到 XB_WanAnimateToVideo")

            animate_core = XB_WanAnimateToVideo()
            func_name = getattr(XB_WanAnimateToVideo, "FUNCTION", "process")
            func = getattr(animate_core, func_name)
            kwargs = {
                "positive": pos_cond, "negative": neg_cond, "vae": b["vae"],
                "clip_vision_output": clip_vision_output, "reference_image": ref_image,
                "face_video": b.get("face_video"), "pose_video": b.get("pose_video"),
                "background_video": b.get("background_video"), "character_mask": b.get("character_mask"),
                "continue_motion": continue_motion,
                "width": b["width"], "height": b["height"], "length": actual_length, "batch_size": 1,
                "continue_motion_max_frames": cont_max_frames,
                "video_frame_offset": current_offset, 
                "vae_tile_size": b.get("vae_encode_tile_size", 320)
            }
            pos, neg, latent, trim_latent, trim_image, new_offset = func(**kwargs)

            latent_sampled, = nodes.KSampler().sample(
                model=b["model"], seed=seed, steps=b["steps"], cfg=b["cfg"],
                sampler_name=b["sampler_name"], scheduler=b["scheduler"],
                positive=pos, negative=neg, latent_image=latent, denoise=1.0
            )
            trim_latent_val = trim_latent if trim_latent is not None else 0
            if trim_latent_val > 0:
                latent_sampled["samples"] = latent_sampled["samples"][:, :, trim_latent_val:, :, :]

            try:
                from .nodes_rocm import XB_ROCmVAEDecodeTemporal
            except ImportError:
                raise ImportError("🚨 找不到 XB_ROCmVAEDecodeTemporal")
            cleanup_mode = b.get("cleanup", "双次缓存清理")
            decoder = XB_ROCmVAEDecodeTemporal()
            decoded_image, = decoder.go(
                samples=latent_sampled, vae=b["vae"],
                tile=b.get("vae_decode_tile_size", 320), overlap=b.get("spatial_overlap", 32),
                t_tile=b.get("temporal_chunk_size", 64), t_overlap=b.get("temporal_overlap", 8),
                cleanup=cleanup_mode
            )

            is_4d = len(decoded_image.shape) == 4
            concat_dim = 0 if is_4d else 1
            trim_px = int(trim_image) if trim_image else 0
            if trim_px > 0 and trim_px < decoded_image.shape[concat_dim]:
                if is_4d:
                    decoded_image = decoded_image[trim_px:, :, :, :]
                else:
                    decoded_image = decoded_image[:, trim_px:, :, :, :]

            accumulated_video = _safe_video_accumulate(accumulated_video, decoded_image, concat_dim, label=f"AnimateRelay-{r+1}", concat_mode=b.get("concat_mode", "自动"))
            actual_out = decoded_image.shape[concat_dim]
            b["current_offset"] = current_offset + actual_out
            print(f"✅ [XB-BOX] 接力 {r+1}/{relay_count} 完成. out={actual_out}f total={accumulated_video.shape[concat_dim]}f")
            completed = r + 1

        if completed < relay_count:
            print(f"✅ [XB-BOX] 生成任务由 {completed} 个接力点已经完成，跳过剩余接力点！")
        else:
            print(f"🎉 [XB-BOX] Animate 接力全部完成: {relay_count} 段, 总计 {accumulated_video.shape[0 if len(accumulated_video.shape)==4 else 1]} 帧")
        overlap = continue_motion_max_frames
        total = max(0, segment_length * relay_count - overlap * (relay_count - 1))
        return (b, accumulated_video)


# ============================================================
# XB_WanInfiniteTalk_ParamBus — InfiniteTalk 无限对口型参数总线
# ============================================================
class XB_WanInfiniteTalk_RelayNode_New:
    """
    每个接力点完成：CLIPTextEncode → WanInfiniteTalkToVideo_Single → KSampler → VAEDecode → trim → 累加。
    音频独立输入 + 自动裁剪重叠 + 累加输出，与视频帧对齐。
    relay_count > 1 时本节点内部自动循环 N 次。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wan_infinitetalk_bus": ("WAN_INFINITETALK_BUS",),
                "positive_prompt": ("STRING", {"multiline": True, "default": ""}),
                "segment_length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "motion_frame_count": ("INT", {"default": 9, "min": 1, "max": 33, "step": 1, "tooltip": "接力重叠帧数（运动过渡）"}),
                "relay_count": ("INT", {"default": 1, "min": 1, "max": 999, "step": 1, "tooltip": "接力数量设定"}),
                "total_frames_display": ("STRING", {"default": "", "multiline": False, "tooltip": "总计生成帧数（自动计算）"}),
            },
            "optional": {
                "prev_video": ("IMAGE",),
                "prev_audio": ("AUDIO",),
                "audio": ("AUDIO",),
            }
        }

    RETURN_TYPES = ("WAN_INFINITETALK_BUS", "IMAGE", "AUDIO")
    RETURN_NAMES = ("📦 WAN_INFINITETALK_BUS (传给下段)", "🎞️ 累加视频流", "🔊 累加音频流")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_infinitetalk_bus, positive_prompt, segment_length, motion_frame_count=9, relay_count=1, total_frames_display="",
                      prev_video=None, prev_audio=None, audio=None):
        b = wan_infinitetalk_bus.copy()
        fps = b.get("fps", 25.0)
        bus_audio_mode = b.get("_bus_audio_mode", False)
        print(f"\n🏃‍♀️ [XB-BOX] Executing InfiniteTalk Relay × {relay_count} relay(s)... 每段 {segment_length} 帧, 总计约 {segment_length * relay_count} 帧")

        accumulated_video = prev_video
        accumulated_audio = prev_audio

        completed = 0
        for r in range(relay_count):
            print(f"\n🔄 [XB-BOX] InfiniteTalk 接力 {r+1}/{relay_count}...")

            # ================================================================
            # 🛡️ 模式判断 & 帧数计算
            # ================================================================
            if bus_audio_mode:
                # --- 模式1：总线音频模式 ---
                total_frames = b["_total_frames"]
                accumulated = b["_accumulated_frames"]
                remaining = total_frames - accumulated

                if remaining <= 0:
                    break

                if remaining < segment_length:
                    if accumulated == 0:
                        need_raw = remaining  # 第一段无 trim
                    else:
                        need_raw = remaining + motion_frame_count
                    actual_length = ((need_raw + 2) // 4) * 4 + 1
                    if actual_length < 1:
                        break
                    print(f"\n⚠️ [XB-BOX] 最后一段: 剩余 {remaining} → need_raw={need_raw} → {actual_length} 帧 (4N+1)")
                else:
                    actual_length = segment_length

                encoded_audio = b["_encoded_audio"]
                raw_audio = b.get("_raw_audio")
                use_segment_audio = False
                print(f"\n🔊 [XB-BOX] 总线音频接力: 偏移 {accumulated} 帧 @ {fps:.0f}fps, 生成长度 {actual_length} 帧 ({accumulated}/{total_frames})")
            else:
                # --- 模式2：独立音频模式 ---
                if audio is None:
                    print(f"⏭️ [XB-BOX] 无音频输入，跳过接力 {r+1}")
                    break

                actual_length = segment_length
                encoded_audio = None
                raw_audio = audio
                use_segment_audio = True
                print(f"\n🎵 [XB-BOX] 独立音频接力: 生成长度 {actual_length} 帧")

            # --- 🛡️ 帧数对齐：Wan 模型要求 length = 4n+1 ---
            raw_length = actual_length
            aligned_length = ((actual_length + 2) // 4) * 4 + 1
            if aligned_length != raw_length:
                print(f"⚠️ [XB-BOX] 帧数对齐: {raw_length} → {aligned_length} (4n+1)")
                if not bus_audio_mode and audio is not None:
                    pad_frames = aligned_length - raw_length
                    pad_sec = pad_frames / fps
                    sr = audio["sample_rate"]
                    pad_samples = int(pad_sec * sr)
                    pad_wf = torch.zeros((audio["waveform"].shape[0], pad_samples), dtype=audio["waveform"].dtype, device=audio["waveform"].device)
                    raw_audio = {"waveform": torch.cat([audio["waveform"], pad_wf], dim=-1), "sample_rate": sr}
            actual_length = aligned_length

            # --- 音频编码（独立模式） ---
            if not bus_audio_mode:
                ae_cls = nodes.NODE_CLASS_MAPPINGS.get("AudioEncoderEncode")
                if ae_cls is None:
                    raise ImportError("AudioEncoderEncode not found")
                ae = ae_cls()
                encoded_audio, = getattr(ae, ae.FUNCTION)(b["audio_encoder"], raw_audio)

            # --- 提示词 ---
            pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], positive_prompt)
            neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b["negative_prompt"])

            # --- InfiniteTalk 底座 ---
            prev = b.get("_previous_frames")
            global_frame_offset = None
            if bus_audio_mode:
                global_frame_offset = b["_accumulated_frames"]

            core = XB_WanInfiniteTalkToVideo_Single()
            model_out, pos, neg, latent, trim = core.process(
                model=b["model"], model_patch=b["model_patch"],
                positive=pos_cond, negative=neg_cond, vae=b["vae"],
                width=b["width"], height=b["height"], length=actual_length,
                audio_encoder_output_1=encoded_audio,
                motion_frame_count=motion_frame_count, audio_scale=b["audio_scale"],
                vae_tile_size=b["vae_encode_tile_size"],
                clip_vision_output=b.get("clip_vision_output"),
                start_image=b.get("start_image"), previous_frames=prev,
                segment_audio=use_segment_audio,
                global_frame_offset=global_frame_offset,
                scale_method=b.get("scale_method", "lanczos"),
                crop_mode=b.get("crop_mode", "center"),
            )

            # --- 采样 ---
            latent_out, = nodes.KSampler().sample(
                model=model_out, seed=b["seed"],
                steps=b["steps"], cfg=b["cfg"],
                sampler_name=b["sampler_name"], scheduler=b["scheduler"],
                positive=pos, negative=neg, latent_image=latent, denoise=1.0,
            )

            # --- 解码 ---
            decoded, = nodes.VAEDecode().decode(samples=latent_out, vae=b["vae"])

            # --- 视频裁剪累加 ---
            is4d = len(decoded.shape) == 4
            cd = 0 if is4d else 1
            total = decoded.shape[cd]
            b["_previous_frames"] = decoded

            trim_val = int(trim) if trim else 0
            trim_val = min(trim_val, total - 1) if trim_val < total else 0
            cut = decoded[trim_val:] if is4d else decoded[:, trim_val:]
            final_video = _safe_video_accumulate(accumulated_video, cut, cd, label=f"TalkRelay-{r+1}", concat_mode=b.get("concat_mode", "自动"))

            # --- 音频裁剪累加 ---
            ats = trim_val / fps if trim_val else 0.0
            if bus_audio_mode:
                raw_wf = raw_audio["waveform"] if raw_audio else torch.zeros((1, 1))
                raw_sr = raw_audio["sample_rate"] if raw_audio else 44100
                seg_start_sample = int(b["_accumulated_frames"] / fps * raw_sr)
                seg_end_sample = int((b["_accumulated_frames"] + cut.shape[cd]) / fps * raw_sr)
                seg_end_sample = min(seg_end_sample, raw_wf.shape[-1])
                cut_audio = {"waveform": raw_wf[..., seg_start_sample:seg_end_sample], "sample_rate": raw_sr} if seg_end_sample > seg_start_sample else None
            else:
                cut_audio = raw_audio
                if ats > 0 and raw_audio:
                    wf = raw_audio["waveform"]
                    sr = raw_audio["sample_rate"]
                    n = int(ats * sr)
                    if n < wf.shape[-1]:
                        cut_audio = {"waveform": wf[..., n:], "sample_rate": sr}
                    else:
                        cut_audio = None

            if accumulated_audio is None:
                final_audio = cut_audio
            elif cut_audio is None:
                final_audio = accumulated_audio
            else:
                pa, ca = accumulated_audio, cut_audio
                if pa["sample_rate"] != ca["sample_rate"]:
                    if torchaudio is None:
                        raise ImportError("🚨 [XB-BOX] 音频采样率不一致需要 torchaudio 重采样，但 torchaudio 未安装！请运行: pip install torchaudio")
                    ca_wf = torchaudio.functional.resample(ca["waveform"], ca["sample_rate"], pa["sample_rate"])
                    ca = {"waveform": ca_wf, "sample_rate": pa["sample_rate"]}
                pa_wf = pa["waveform"]
                ca_wf = ca["waveform"].to(pa_wf.device)
                if pa_wf.dim() >= 2 and ca_wf.dim() >= 2 and pa_wf.shape[:-1] != ca_wf.shape[:-1]:
                    if pa_wf.shape[-2] == 1 and ca_wf.shape[-2] > 1:
                        rpt = [1] * pa_wf.dim()
                        rpt[-2] = ca_wf.shape[-2]
                        pa_wf = pa_wf.repeat(*rpt)
                    elif ca_wf.shape[-2] == 1 and pa_wf.shape[-2] > 1:
                        rpt = [1] * ca_wf.dim()
                        rpt[-2] = pa_wf.shape[-2]
                        ca_wf = ca_wf.repeat(*rpt)
                final_audio = {"waveform": torch.cat([pa_wf, ca_wf], dim=-1), "sample_rate": pa["sample_rate"]}

            b["_global_frame_offset"] = b.get("_global_frame_offset", 0) + cut.shape[cd]
            if bus_audio_mode:
                b["_accumulated_frames"] += cut.shape[cd]
            accumulated_video = final_video
            accumulated_audio = final_audio
            print(f"✅ [XB-BOX] 接力 {r+1}/{relay_count} 完成. out={cut.shape[cd]}f total={final_video.shape[cd]}f")
            completed = r + 1

        if completed < relay_count:
            print(f"✅ [XB-BOX] 生成任务由 {completed} 个接力点已经完成，跳过剩余接力点！")
        else:
            print(f"🎉 [XB-BOX] InfiniteTalk 接力全部完成: {relay_count} 段, 总计 {accumulated_video.shape[0 if len(accumulated_video.shape)==4 else 1]} 帧")
        _refresh_models()
        overlap = motion_frame_count
        total = max(0, segment_length * relay_count - overlap * (relay_count - 1))
        return (b, accumulated_video, accumulated_audio)


# ============================================================
# XB_WanSCAIL_ParamBus — SCAIL 无限时长参数总线
# ============================================================
class XB_WanSCAIL_ParamBus_New:
    """SCAIL 无限接力参数总线。
    集中管理模型、姿态视频、参考图等所有共享参数，
    接力点只需传正面提示词 + 单次生成帧数，其余全从总线走。
    """
    _SCALE_METHODS = ["bilinear", "bicubic", "lanczos", "nearest-exact", "area"]
    _CROP_MODES = ["center", "disabled"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # --- 模型 ---
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "clip_vision": ("CLIP_VISION",),
                # --- 基础参数 ---
                "negative_prompt": ("STRING", {"multiline": True, "default": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"}),
                "width": ("INT", {"default": 512, "min": 16, "max": 8192, "step": 32}),
                "height": ("INT", {"default": 896, "min": 32, "max": 8192, "step": 32}),
                "total_frames": ("INT", {"default": 0, "min": 0, "max": 999999, "tooltip": "0=自动从姿态视频取长度；>0=强制截断到此帧数"}),
                "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 1.0}),
                # --- SCAIL 控制 ---
                "pose_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "pose_start": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "pose_end": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "replacement_mode": ("BOOLEAN", {"default": False, "label_on": "替换模式", "label_off": "动画模式"}),
                "concat_mode": (["自动", "强制GPU", "强制CPU"], {"default": "自动", "tooltip": "视频累积拼接位置: 自动=显存>30%切CPU | 强制GPU=始终GPU | 强制CPU=始终CPU"}),
                # --- VAE 分块 ---
                "vae_encode_tile_size": ("INT", {"default": 256, "min": 64, "max": 3840, "step": 32}),
                "vae_decode_tile_size": ("INT", {"default": 192, "min": 64, "max": 3840, "step": 32}),
                "spatial_overlap": ("INT", {"default": 32, "min": 0, "max": 3840, "step": 32}),
                "temporal_chunk_size": ("INT", {"default": 64, "min": 0, "max": 8192, "step": 4}),
                "temporal_overlap": ("INT", {"default": 8, "min": 0, "max": 8192, "step": 4}),
                # --- 采样 ---
                "steps": ("INT", {"default": 20, "min": 1, "max": 100}),
                "cfg": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "sampler_name": (comfy.samplers.KSAMPLER_NAMES,),
                "scheduler": (comfy.samplers.SCHEDULER_NAMES,),
                "seed": ("INT", {"default": 123456789}),
                # --- 清理 ---
                "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "双次缓存清理"}),
            },
            "optional": {
                "global_ref_image": ("IMAGE",),
                "reference_image_mask": ("IMAGE", {"tooltip": "参考图遮罩 (替换模式: 隔离角色区域)"}),
                "pose_video": ("IMAGE", {"tooltip": "姿态/驱动视频"}),
                "pose_video_mask": ("IMAGE", {"tooltip": "SCAIL-2 彩色遮罩视频"}),
                "scale_method": (cls._SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (cls._CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("WAN_SCAIL_BUS",)
    RETURN_NAMES = ("📦 WAN_SCAIL_BUS",)
    FUNCTION = "pack_bus"
    CATEGORY = "XB_ToolBox/Pipeline"

    def pack_bus(self, **kwargs):
        # CLIP 视觉编码：参考图缩放到视频尺寸后编码
        cv = kwargs.get("clip_vision")
        ref = kwargs.get("global_ref_image")
        if cv is not None and ref is not None:
            w, h = kwargs["width"], kwargs["height"]
            method = kwargs.get("scale_method", "lanczos")
            crop = kwargs.get("crop_mode", "center")
            scaled = comfy.utils.common_upscale(ref.movedim(-1, 1), w, h, method, crop).movedim(1, -1)
            kwargs["clip_vision_output"], = nodes.CLIPVisionEncode().encode(cv, scaled, "center")
            print(f"👁️ [XB-BOX] SCAIL CLIP视觉编码 ({ref.shape[1]}×{ref.shape[2]} → {w}×{h}, {method}/{crop})")
        else:
            kwargs["clip_vision_output"] = None

        kwargs["current_offset"] = 0
        return (kwargs,)


# ============================================================
# XB_WanSCAIL_RelayNode — SCAIL 无限接力点
# ============================================================
class XB_WanSCAIL_RelayNode_New:
    """SCAIL 无限接力节点。
    每个接力点完成：CLIPTextEncode → SCAIL Process → KSampler → VAEDecode → trim → 累加。
    自动管理姿态视频偏移 + 前段尾帧衔接。
    relay_count > 1 时本节点内部自动循环 N 次。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wan_scail_bus": ("WAN_SCAIL_BUS",),
                "segment_length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "positive_prompt": ("STRING", {"multiline": True, "default": "Describe the scene..."}),
                "previous_frame_count": ("INT", {"default": 5, "min": 1, "max": 8192, "step": 4, "tooltip": "接力重叠帧数（尾帧衔接）"}),
                "relay_count": ("INT", {"default": 1, "min": 1, "max": 999, "step": 1, "tooltip": "接力数量设定"}),
                "total_frames_display": ("STRING", {"default": "", "multiline": False, "tooltip": "总计生成帧数（自动计算）"}),
            },
            "optional": {
                "prev_video": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("WAN_SCAIL_BUS", "IMAGE")
    RETURN_NAMES = ("📦 WAN_SCAIL_BUS (传给下段)", "🎞️ 累加视频流")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_scail_bus, segment_length, positive_prompt="", previous_frame_count=5, relay_count=1, total_frames_display="", prev_video=None):
        b = wan_scail_bus.copy()
        print(f"\n🏃‍♀️ [XB-BOX] Executing SCAIL Relay × {relay_count} relay(s)... 每段 {segment_length} 帧, 总计约 {segment_length * relay_count} 帧")
        accumulated_video = prev_video

        completed = 0
        for r in range(relay_count):
            current_offset = b.get("current_offset", 0)
            seed = b.get("seed", 123456789)
            print(f"\n🔄 [XB-BOX] SCAIL 接力 {r+1}/{relay_count} (offset={current_offset})...")

            pose_video = b.get("pose_video")
            total_source_frames = float('inf')
            bus_total = b.get("total_frames", 0)
            if bus_total > 0:
                total_source_frames = bus_total
            elif pose_video is not None:
                total_source_frames = pose_video.shape[0] if len(pose_video.shape) == 4 else pose_video.shape[1]

            remaining_frames = max(0, total_source_frames - current_offset)

            if remaining_frames <= 0:
                break

            if remaining_frames < segment_length:
                if current_offset == 0:
                    need_raw = remaining_frames
                else:
                    need_raw = remaining_frames + previous_frame_count
                actual_length = ((need_raw + 2) // 4) * 4 + 1
                if actual_length < 1:
                    break
                print(f"⚠️ [XB-BOX] SCAIL 最后一段: 剩余 {remaining_frames} → {actual_length} 帧 (4N+1)")
            else:
                actual_length = segment_length

            # --- 参考图：始终从总线继承（已含遮罩处理） ---
            ref_image = b.get("global_ref_image")
            clip_vision_output = b.get("clip_vision_output")

            # --- 提示词 ---
            prompt_text = positive_prompt.strip() if positive_prompt.strip() else b.get("positive_prompt", "")
            pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], prompt_text)
            neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b.get("negative_prompt", ""))

            # --- 准备 previous_frames ---
            previous_frames = None
            if accumulated_video is not None and current_offset > 0:
                is_4d = len(accumulated_video.shape) == 4
                if is_4d:
                    previous_frames = accumulated_video[-previous_frame_count:]
                else:
                    previous_frames = accumulated_video[:, -previous_frame_count:]

            # --- SCAIL Pro 底座 ---
            try:
                from .nodes_wan_vae import XB_WanSCAILToVideoPro
            except ImportError:
                raise ImportError("🚨 找不到 XB_WanSCAILToVideoPro")
            scail_core = XB_WanSCAILToVideoPro()
            pos, neg, latent, new_offset = scail_core.process(
                positive=pos_cond, negative=neg_cond, vae=b["vae"],
                width=b["width"], height=b["height"], length=actual_length, batch_size=1,
                pose_strength=b.get("pose_strength", 1.0),
                pose_start=b.get("pose_start", 0.0), pose_end=b.get("pose_end", 1.0),
                replacement_mode=b.get("replacement_mode", False),
                video_frame_offset=current_offset, previous_frame_count=previous_frame_count,
                vae_tile_size=b.get("vae_encode_tile_size", 256),
                pose_video=pose_video, pose_video_mask=b.get("pose_video_mask"),
                reference_image=ref_image, reference_image_mask=b.get("reference_image_mask"),
                clip_vision_output=clip_vision_output, previous_frames=previous_frames,
            )

            # --- 采样 ---
            latent_sampled, = nodes.KSampler().sample(
                model=b["model"], seed=seed, steps=b["steps"], cfg=b["cfg"],
                sampler_name=b["sampler_name"], scheduler=b["scheduler"],
                positive=pos, negative=neg, latent_image=latent, denoise=1.0,
            )

            # --- 解码 ---
            try:
                from .nodes_rocm import XB_ROCmVAEDecodeTemporal
            except ImportError:
                raise ImportError("🚨 找不到 XB_ROCmVAEDecodeTemporal")
            cleanup_mode = b.get("cleanup", "双次缓存清理")
            decoder = XB_ROCmVAEDecodeTemporal()
            decoded_image, = decoder.go(
                samples=latent_sampled, vae=b["vae"],
                tile=b.get("vae_decode_tile_size", 192), overlap=b.get("spatial_overlap", 32),
                t_tile=b.get("temporal_chunk_size", 64), t_overlap=b.get("temporal_overlap", 8),
                cleanup=cleanup_mode,
            )

            # --- 裁剪重叠帧 & 累加 ---
            is_4d = len(decoded_image.shape) == 4
            concat_dim = 0 if is_4d else 1
            total_out = decoded_image.shape[concat_dim]
            trim_px = previous_frame_count if (accumulated_video is not None and current_offset > 0) else 0
            trim_px = min(trim_px, total_out - 1) if trim_px < total_out else 0
            if trim_px > 0:
                if is_4d:
                    decoded_image = decoded_image[trim_px:, :, :, :]
                else:
                    decoded_image = decoded_image[:, trim_px:, :, :, :]

            accumulated_video = _safe_video_accumulate(accumulated_video, decoded_image, concat_dim, label=f"SCAIL-{r+1}", concat_mode=b.get("concat_mode", "自动"))
            actual_out = decoded_image.shape[concat_dim]
            b["current_offset"] = new_offset
            print(f"✅ [XB-BOX] SCAIL 接力 {r+1}/{relay_count} 完成. out={actual_out}f total={accumulated_video.shape[concat_dim]}f")
            completed = r + 1

        if completed < relay_count:
            print(f"✅ [XB-BOX] 生成任务由 {completed} 个接力点已经完成，跳过剩余接力点！")
        else:
            print(f"🎉 [XB-BOX] SCAIL 接力全部完成: {relay_count} 段, 总计 {accumulated_video.shape[0 if len(accumulated_video.shape)==4 else 1]} 帧")
        _refresh_models()
        overlap = previous_frame_count
        total = max(0, segment_length * relay_count - overlap * (relay_count - 1))
        return (b, accumulated_video)