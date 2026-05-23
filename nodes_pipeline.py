import os
import torch
import numpy as np
from PIL import Image, ImageOps
import nodes
import comfy.samplers  
import folder_paths  
from .nodes_wan_vae import XB_WanFirstLastFrameToVideo, XB_WanImageToVideo

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
                "trim_head_frames": ("INT", {"default": 1, "min": 1, "max": 8192, "step": 1}), # 🚀 新增：精确去重帧数控制
            }
        }

    RETURN_TYPES = ("WAN_BUS",)  
    RETURN_NAMES = ("📦 WAN_BUS (Dynamic Bus)",)
    FUNCTION = "pack_bus"
    CATEGORY = "XB_ToolBox/Pipeline"

    def pack_bus(self, **kwargs):
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

        pos, neg, latent = XB_WanFirstLastFrameToVideo().process(
            positive=pos_cond, negative=neg_cond, vae=b["vae"], 
            clip_vision_start_image=None, clip_vision_end_image=None, 
            start_image=start_image, end_image=end_image, 
            width=b["width"], height=b["height"], length=b["length"], 
            batch_size=1, vae_tile_size=encode_tile
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

        pos, neg, latent = XB_WanImageToVideo().process(
            positive=pos_cond, negative=neg_cond, vae=b["vae"], 
            clip_vision_output=None, start_image=start_image, 
            width=b["width"], height=b["height"], length=b["length"], 
            batch_size=1, vae_tile_size=encode_tile
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