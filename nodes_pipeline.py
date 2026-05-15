import os
import torch
import numpy as np
from PIL import Image, ImageOps
import nodes
import comfy.samplers  
import folder_paths  
from .nodes_wan_vae import XB_WanFirstLastFrameToVideo

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
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
                "steps": ("INT", {"default": 4, "min": 1, "max": 100}),
                "high_noise_steps": ("INT", {"default": 2, "min": 1, "max": 50}), 
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "sampler_name": (comfy.samplers.KSAMPLER_NAMES, ),
                "scheduler": (comfy.samplers.SCHEDULER_NAMES, ),
            }
        }

    RETURN_TYPES = ("WAN_BUS",)  
    RETURN_NAMES = ("📦 WAN_BUS (Dynamic Bus)",)
    FUNCTION = "pack_bus"
    CATEGORY = "XB_ToolBox/Pipeline"

    def pack_bus(self, **kwargs):
        return (kwargs,)

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
                "seed": ("INT", {"default": 123456789}),
                "cut_first_frame": ("BOOLEAN", {"default": True, "label_on": "Yes (Relay Deduplication)", "label_off": "No (Keep First Frame)"}),
                "end_image_file": (files, {"image_upload": True})
            },
            "optional": {
                "opt_end_image": ("IMAGE",),
                "prev_video": ("IMAGE",)
            }
        }

    RETURN_TYPES = ("WAN_BUS", "IMAGE", "IMAGE")
    RETURN_NAMES = ("📦 WAN_BUS (Pass to next)", "🖼️ Current End Image (Connect to next Start Image)", "🎞️ Accumulated Video Stream")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, wan_bus, start_image, positive_prompt, seed, cut_first_frame, end_image_file, opt_end_image=None, prev_video=None):
        print("\n🏃 [XB-BOX] Executing single-batch first/last frame generation task...")
        b = wan_bus

        if opt_end_image is not None:
            end_image = opt_end_image
            print(f"🖼️ [XB-BOX] Connection detected, prioritizing end frame from opt_end_image endpoint.")
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
            print(f"🖼️ [XB-BOX] Successfully loaded panel preview image: {end_image_file}")

        pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], positive_prompt)
        neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b["negative_prompt"])

        pos, neg, latent = XB_WanFirstLastFrameToVideo().process(
            positive=pos_cond, negative=neg_cond, vae=b["vae"], 
            clip_vision_start_image=None, clip_vision_end_image=None, 
            start_image=start_image, end_image=end_image, 
            width=b["width"], height=b["height"], length=b["length"], 
            batch_size=1, vae_tile_size=b["vae_tile_size"]
        )

        print(f"🔥 [XB-BOX] Starting high noise engine (0 -> {b['high_noise_steps']} steps)...")
        latent_high, = nodes.KSamplerAdvanced().sample(
            model=b["model_high"], add_noise="enable", noise_seed=seed,
            steps=b["steps"], cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent,
            start_at_step=0, end_at_step=b["high_noise_steps"], return_with_leftover_noise="enable" 
        )

        print(f"❄️ [XB-BOX] Switching to low noise engine ({b['high_noise_steps']} -> completion)...")
        latent_low, = nodes.KSamplerAdvanced().sample(
            model=b["model_low"], add_noise="disable", noise_seed=seed, 
            steps=b["steps"], cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent_high, 
            start_at_step=b["high_noise_steps"], end_at_step=10000, return_with_leftover_noise="disable"
        )

        decoded_image, = nodes.VAEDecodeTiled().decode(
            samples=latent_low, vae=b["vae"], tile_size=b["vae_tile_size"], 
            overlap=32, temporal_size=64, temporal_overlap=8
        )

        is_4d = len(decoded_image.shape) == 4

        if cut_first_frame:
            if is_4d:
                decoded_image = decoded_image[1:, :, :, :]
            else:
                decoded_image = decoded_image[:, 1:, :, :, :]
            print("✂️ [XB-BOX] Physical deduplication triggered: overlap first frame removed.")

        if is_4d:
            last_frame = decoded_image[-1:, :, :, :]
            out_length = decoded_image.shape[0]
        else:
            last_frame = decoded_image[:, -1:, :, :, :]
            out_length = decoded_image.shape[1]

        print(f"✅ [XB-BOX] Current batch complete! New segment length: {out_length} frames")
        
        if prev_video is not None:
            print("🧩 [XB-BOX] Previous video connection detected, executing snowball accumulation merge...")
            concat_dim = 0 if is_4d else 1
            final_video = torch.cat([prev_video, decoded_image], dim=concat_dim)
            print(f"🎉 [XB-BOX] Snowball accumulation complete! Current long video reached: {final_video.shape[concat_dim]} frames")
        else:
            final_video = decoded_image

        return (wan_bus, last_frame, final_video)

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
        videos = []
        for i in range(1, 11):
            vid = kwargs.get(f"video_{i}")
            if vid is not None:
                videos.append(vid)

        if not videos:
            raise ValueError("🚨 [XB-BOX] Merge failed: At least one video must be connected!")
            
        print(f"🧩 [XB-BOX] Executing seamless physical merge of {len(videos)} video segments...")
        
        concat_dim = 0 if len(videos[0].shape) == 4 else 1
        final_video = torch.cat(videos, dim=concat_dim) 
        
        total_frames = final_video.shape[concat_dim]
        print(f"🎉 [XB-BOX] Video merge successful! Total frames: {total_frames}")
        
        return (final_video,)

class XB_StoryboardSlicer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": ([
                    "3-Grid (1x3 Horizontal)", 
                    "3-Grid (3x1 Vertical)", 
                    "4-Grid (2x2)", 
                    "6-Grid (2x3 Horizontal)", 
                    "6-Grid (3x2 Vertical)", 
                    "9-Grid (3x3)"
                ], {"default": "4-Grid (2x2)"}),
                "crop_margin": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 0.45, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("Img1", "Img2", "Img3", "Img4", "Img5", "Img6", "Img7", "Img8", "Img9")
    FUNCTION = "slice_image"
    CATEGORY = "XB_ToolBox/Pipeline"

    def slice_image(self, image, mode, crop_margin):
        print(f"\n✂️ [XB-BOX] Starting storyboard slicer, mode: {mode} | crop margin: {crop_margin}")
        
        if "1x3" in mode: rows, cols = 1, 3
        elif "3x1" in mode: rows, cols = 3, 1
        elif "2x2" in mode: rows, cols = 2, 2
        elif "2x3" in mode: rows, cols = 2, 3
        elif "3x2" in mode: rows, cols = 3, 2
        elif "3x3" in mode: rows, cols = 3, 3
        else: rows, cols = 2, 2 

        batch_size, h, w, channels = image.shape
        
        slice_h = h // rows
        slice_w = w // cols
        
        crop_y = int(slice_h * crop_margin)
        crop_x = int(slice_w * crop_margin)

        print(f"📐 [XB-BOX] Original: {w}x{h} -> Raw slice: {slice_w}x{slice_h} -> Final output after crop: {slice_w - crop_x*2}x{slice_h - crop_y*2}")

        sliced_images = []
        
        for r in range(rows):
            for c in range(cols):
                start_y = r * slice_h + crop_y
                end_y = (r + 1) * slice_h - crop_y
                start_x = c * slice_w + crop_x
                end_x = (c + 1) * slice_w - crop_x
                
                if start_y >= end_y: end_y = start_y + 1
                if start_x >= end_x: end_x = start_x + 1

                slice_tensor = image[:, start_y:end_y, start_x:end_x, :]
                sliced_images.append(slice_tensor)

        black_placeholder = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
        
        empty_count = 0
        while len(sliced_images) < 9:
            sliced_images.append(black_placeholder)
            empty_count += 1

        print(f"✅ [XB-BOX] Slicing complete: {rows * cols} valid images | 🛡️ Generated {empty_count} black placeholder(s).")
        
        return tuple(sliced_images)