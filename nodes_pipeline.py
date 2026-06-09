import os
import torch
import numpy as np
import gc
from PIL import Image, ImageOps
import nodes
import comfy.samplers
import comfy.model_management
import folder_paths  
from .nodes_wan_vae import XB_WanFirstLastFrameToVideo, XB_WanImageToVideo, XB_WanInfiniteTalkToVideo_Single

# ==============================================================================
# 公共工具：模型状态刷新，防止接力过程中补丁/缓存累积导致质量下滑
# ==============================================================================
def _refresh_models():
    """清空 GPU 缓存但不卸载模型（BlockSwap 分块模型卸载后重新加载会崩溃）"""
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    gc.collect()

# ==============================================================================
# 1. 视频参数总线 (全面解耦 VAE 编码与解码的时空分块参数)
# ==============================================================================
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
                # ------------------------------
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
        ref = kwargs.get("start_image")  # 首尾帧/图生视频用 start_image 做视觉参考
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

# ==============================================================================
# 2. 🏃首尾帧接力点
# ==============================================================================
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

        # 🔄 向后兼容：旧工作流只有 vae_tile_size，新工作流分离了编解码参数
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
                raise ValueError("🚨 [XB-BOX] End frame missing! Connect image to opt_end_image or upload via panel!")
                
            image_path = folder_paths.get_annotated_filepath(end_image_file)
            if not os.path.exists(image_path):
                 raise ValueError(f"🚨 [XB-BOX] Image file not found: {image_path}")
            
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

        print(f"🔥 [XB-BOX] Samping Layer 1 (0 -> {b['high_noise_steps']} steps)...")
        latent_high, = nodes.KSamplerAdvanced().sample(
            model=b["model_high"], add_noise="enable", noise_seed=seed,
            steps=b["steps"], cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent,
            start_at_step=0, end_at_step=b["high_noise_steps"], return_with_leftover_noise="enable" 
        )

        print(f"❄️ [XB-BOX] Samping Layer 2 ({b['high_noise_steps']} -> completion)...")
        latent_low, = nodes.KSamplerAdvanced().sample(
            model=b["model_low"], add_noise="disable", noise_seed=seed, 
            steps=b["steps"], cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent_high, 
            start_at_step=b["high_noise_steps"], end_at_step=10000, return_with_leftover_noise="disable"
        )

        decoded_image, = nodes.VAEDecodeTiled().decode(
            samples=latent_low, 
            vae=b["vae"], 
            tile_size=decode_tile, 
            overlap=spat_overlap, 
            temporal_size=temp_chunk, 
            temporal_overlap=temp_overlap
        )

        is_4d = len(decoded_image.shape) == 4
        frame_dim = 0 if is_4d else 1
        total_frames = decoded_image.shape[frame_dim]

        # 🛡️ 安全钳：trim_head_frames 不能超过实际帧数，至少保留 1 帧
        if cut_first_frame and total_frames > 1:
            safe_trim = min(trim_head_frames, total_frames - 1)
            if safe_trim > 0:
                if is_4d:
                    decoded_image = decoded_image[safe_trim:, :, :, :]
                else:
                    decoded_image = decoded_image[:, safe_trim:, :, :, :]

        last_frame = decoded_image[-1:, :, :, :] if is_4d else decoded_image[:, -1:, :, :, :]
        concat_dim = 0 if is_4d else 1
        
        if prev_video is not None:
            final_video = torch.cat([prev_video, decoded_image], dim=concat_dim)
        else:
            final_video = decoded_image

        return (wan_bus, last_frame, final_video)

# ==============================================================================
# 3. 🏃‍♀️Wan无限长接力点
# ==============================================================================
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

        # 🔄 向后兼容：旧工作流只有 vae_tile_size，新工作流分离了编解码参数
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

        latent_high, = nodes.KSamplerAdvanced().sample(
            model=b["model_high"], add_noise="enable", noise_seed=seed,
            steps=b["steps"], cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent,
            start_at_step=0, end_at_step=b["high_noise_steps"], return_with_leftover_noise="enable" 
        )

        latent_low, = nodes.KSamplerAdvanced().sample(
            model=b["model_low"], add_noise="disable", noise_seed=seed, 
            steps=b["steps"], cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent_high, 
            start_at_step=b["high_noise_steps"], end_at_step=10000, return_with_leftover_noise="disable"
        )

        decoded_image, = nodes.VAEDecodeTiled().decode(
            samples=latent_low, 
            vae=b["vae"], 
            tile_size=decode_tile, 
            overlap=spat_overlap, 
            temporal_size=temp_chunk, 
            temporal_overlap=temp_overlap
        )

        is_4d = len(decoded_image.shape) == 4
        frame_dim = 0 if is_4d else 1
        total_frames = decoded_image.shape[frame_dim]

        # 🛡️ 安全钳：trim_head_frames 不能超过实际帧数，至少保留 1 帧
        if cut_first_frame and total_frames > 1:
            safe_trim = min(trim_head_frames, total_frames - 1)
            if safe_trim > 0:
                if is_4d:
                    decoded_image = decoded_image[safe_trim:, :, :, :]
                else:
                    decoded_image = decoded_image[:, safe_trim:, :, :, :]

        last_frame = decoded_image[-1:, :, :, :] if is_4d else decoded_image[:, -1:, :, :, :]
        concat_dim = 0 if is_4d else 1
        
        if prev_video is not None:
            final_video = torch.cat([prev_video, decoded_image], dim=concat_dim)
        else:
            final_video = decoded_image

        return (wan_bus, last_frame, final_video)

# ==============================================================================
# 4. 视频拼接与分镜切片 
# ==============================================================================
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
        return (torch.cat(videos, dim=concat_dim),)

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
            sliced_images.append(torch.zeros((1, placeholder_h, placeholder_w, 3), dtype=torch.float32))
        return tuple(sliced_images)

# ==============================================================================
# 6. 🎬 Wan Animate 动作迁移专用总线 (修正：单模型单轨架构)
# ==============================================================================
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

# ==============================================================================
# 7. 🏃‍♀️ Wan Animate 无限接力点 (完全复刻首尾帧接力点的 UI 交互模式)
# ==============================================================================
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

        # ====================================================================
        # 🛡️ 防呆 1：帧数智能对齐与越界跳过
        # ====================================================================
        source_video = b.get("pose_video") if b.get("pose_video") is not None else b.get("face_video")
        total_source_frames = float('inf')

        if source_video is not None:
            total_source_frames = source_video.shape[0] if len(source_video.shape) == 4 else source_video.shape[1]

        remaining_frames = max(0, total_source_frames - current_offset)

        if remaining_frames <= 0:
            print(f"\n⏭️ [XB-BOX] 动作视频已耗尽 (已跑到 {current_offset} 帧 / 总 {total_source_frames} 帧)。当前接力点直接跳过！")
            fallback_video = prev_video if prev_video is not None else torch.zeros((1, b.get("height", 832), b.get("width", 480), 3))
            return (b, fallback_video)

        actual_length = min(segment_length, remaining_frames)
        if actual_length < segment_length:
            print(f"\n⚠️ [XB-BOX] 帧数截断触发：节点请求 {segment_length} 帧，源动作视频仅剩 {actual_length} 帧。已自动对齐缩减！")
        else:
            print(f"\n🏃‍♀️ [XB-BOX] Executing Wan Animate Relay task... Target segment length: {actual_length}")

        # ====================================================================
        # 🎨 开关控制：ON=独立选图, OFF=继承总线全局图
        # ====================================================================
        # 判断是否使用独立参考图（兼容字符串/布尔/索引）
        is_local = (use_local_ref_image == "独立参考图" or 
                    use_local_ref_image is True or 
                    use_local_ref_image == 1)
        if is_local:
            if not ref_image_file or ref_image_file == "[Folder empty_Please connect or upload]":
                raise ValueError("🚨 [XB-BOX] 已开启独立参考图，但未选择图片文件！")
            image_path = folder_paths.get_annotated_filepath(ref_image_file)
            if not os.path.exists(image_path):
                raise ValueError(f"🚨 [XB-BOX] 图片文件未找到: {image_path}")
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
            local_clip_vision, = nodes.CLIPVisionEncode().encode(cv_model, clip_img, "center")
            local_clip_vision, = nodes.CLIPVisionEncode().encode(cv_model, clip_img, "center")
            clip_vision_output = local_clip_vision
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

        # 🛡️ 强制卸载扩散模型到 CPU：防止 ComfyUI 因显存充裕而全量加载模型，
        # 全量加载后 BlockSwap 回调无法正确分块 → comfy_kitchen 崩溃
        model_obj = b["model"]
        if hasattr(model_obj, "model") and hasattr(model_obj, "offload_device"):
            model_obj.model.to(model_obj.offload_device)
            comfy.model_management.soft_empty_cache()
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            gc.collect()

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

        # ====================================================================
        # 🚀 核弹升级：ROCm 专属时空解码 (cleanup 从总线继承)
        # ====================================================================
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

        if prev_video is not None:
            final_video = torch.cat([prev_video, decoded_image], dim=concat_dim)
        else:
            final_video = decoded_image

        actual_out = decoded_image.shape[concat_dim]
        b["current_offset"] = current_offset + actual_out
        print(f"✅ [XB-BOX] Animate Relay Complete. trim_lat={trim_latent_val} trim_px={trim_px} out={actual_out}f total={final_video.shape[concat_dim]}f")

        return (b, final_video)

# ==============================================================================
# 8. 🎵 InfiniteTalk 无限对口型总线（单人）—— 重写版
# ==============================================================================
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

# ==============================================================================
# 9. 🎵 InfiniteTalk 无限对口型接力点（单人）—— 重写版
# ==============================================================================
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

        # 🛡️ 总线模式：previous_frames 只含最后一段，补齐到累积帧数，
        # 让 _process_infinite_talk_audio 的 frame_offset 算出正确的全局 audio_start
        if bus_audio_mode and prev is not None:
            accumulated = b["_accumulated_frames"]
            target_len = accumulated + motion
            cd_pad = 0 if len(prev.shape) == 4 else 1
            if prev.shape[cd_pad] < target_len:
                pad_shape = list(prev.shape)
                pad_shape[cd_pad] = target_len - prev.shape[cd_pad]
                dummy = torch.zeros(pad_shape, device=prev.device, dtype=prev.dtype)
                prev = torch.cat([dummy, prev], dim=cd_pad)

        core = XB_WanInfiniteTalkToVideo_Single()

        # 🛡️ 保存模型原始状态，之后完整恢复，防止补丁累积导致质量下滑
        model_ref = b["model"]
        _saved_wrappers = dict(model_ref.wrappers) if hasattr(model_ref, "wrappers") else {}
        _saved_obj_patches = dict(model_ref.object_patches) if hasattr(model_ref, "object_patches") else {}
        _saved_trans_opts = dict(model_ref.model_options.get("transformer_options", {})) if hasattr(model_ref, "model_options") else {}

        model_out, pos, neg, latent, trim = core.process(
            model=model_ref, model_patch=b["model_patch"],
            positive=pos_cond, negative=neg_cond, vae=b["vae"],
            width=b["width"], height=b["height"], length=actual_length,
            audio_encoder_output_1=encoded_audio,
            motion_frame_count=motion, audio_scale=b["audio_scale"],
            vae_tile_size=b["vae_encode_tile_size"],
            clip_vision_output=b.get("clip_vision_output"),
            start_image=b.get("start_image"), previous_frames=prev,
            segment_audio=use_segment_audio,
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

        # --- 完整恢复模型原始状态（不只是删 key，防止残留引用累积） ---
        if hasattr(model_out, "wrappers"):
            model_out.wrappers.clear()
            model_out.wrappers.update(_saved_wrappers)
        if hasattr(model_out, "object_patches"):
            model_out.object_patches.clear()
            model_out.object_patches.update(_saved_obj_patches)
        if hasattr(model_out, "model_options"):
            model_out.model_options["transformer_options"] = _saved_trans_opts

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
        final_video = torch.cat([prev_video, cut], dim=cd) if prev_video is not None else cut

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

        if prev_audio is None:
            final_audio = cut_audio
        elif cut_audio is None:
            final_audio = prev_audio
        else:
            pa, ca = prev_audio, cut_audio
            if pa["sample_rate"] != ca["sample_rate"]:
                import torchaudio
                ca_wf = torchaudio.functional.resample(ca["waveform"], ca["sample_rate"], pa["sample_rate"])
                ca = {"waveform": ca_wf, "sample_rate": pa["sample_rate"]}
            final_audio = {"waveform": torch.cat([pa["waveform"], ca["waveform"]], dim=-1),
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