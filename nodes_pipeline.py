import os
import torch
import numpy as np
from PIL import Image, ImageOps
import nodes
import comfy.samplers  
import folder_paths  
from .nodes_wan_vae import XB_WanFirstLastFrameToVideo

# ====================================================================
# 积木一：【📦 视频参数打包总线】
# ====================================================================
class XB_Wan_ParamBus:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_high": ("MODEL",),  
                "model_low": ("MODEL",),   
                "clip": ("CLIP",),
                "vae": ("VAE",),
                
                "negative_prompt": ("STRING", {"multiline": True, "default": "色调艳丽，过曝，静态，细节模糊不清..."}),
                
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
    RETURN_NAMES = ("📦 WAN_BUS (动态总线)",)
    FUNCTION = "pack_bus"
    CATEGORY = "小白工具箱/流水线架构"

    def pack_bus(self, **kwargs):
        return (kwargs,)


# ====================================================================
# 积木二：【🏃 首尾帧接力节点】 (🟢 回归 Required，重新召唤图片面板)
# ====================================================================
class XB_Wan_RelayNode:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))] if os.path.exists(input_dir) else []
        files = sorted(files)
        
        # 兜底：防止真没图的时候前端发神经
        if not files:
            files = ["[文件夹为空_请连线或上传]"]
            
        return {
            "required": {
                "wan_bus": ("WAN_BUS",),  
                "start_image": ("IMAGE",),
                
                "positive_prompt": ("STRING", {"multiline": True, "default": "描述这一段的具体动作..."}),
                "seed": ("INT", {"default": 123456789}),
                "cut_first_frame": ("BOOLEAN", {"default": True, "label_on": "是 (接力去重)", "label_off": "否 (保留首帧)"}),
                
                # 🟢 核心修复：必须放在 required 里，面板才会重新出现！
                "end_image_file": (files, {"image_upload": True})
            },
            "optional": {
                "opt_end_image": ("IMAGE",),
                "prev_video": ("IMAGE",)
            }
        }

    RETURN_TYPES = ("WAN_BUS", "IMAGE", "IMAGE")
    RETURN_NAMES = ("📦 WAN_BUS (传给下段)", "🖼️ 当前尾图 (接下段首图)", "🎞️ 累加视频流 (接下段或输出)")
    FUNCTION = "execute_relay"
    CATEGORY = "小白工具箱/流水线架构"

    def execute_relay(self, wan_bus, start_image, positive_prompt, seed, cut_first_frame, end_image_file, opt_end_image=None, prev_video=None):
        print("\n🏃 [XB-BOX] 正在执行单批次首尾帧生成任务...")
        b = wan_bus

        if opt_end_image is not None:
            end_image = opt_end_image
            print(f"🖼️ [XB-BOX] 检测到连线，正在优先使用 opt_end_image 端点传入的尾帧。")
        else:
            if end_image_file == "[文件夹为空_请连线或上传]":
                raise ValueError("🚨 [XB-BOX] 尾帧缺失！请使用左侧 opt_end_image 连入图片，或点击面板上传图片！")
                
            image_path = folder_paths.get_annotated_filepath(end_image_file)
            if not os.path.exists(image_path):
                 raise ValueError(f"🚨 [XB-BOX] 找不到图片文件: {image_path}")
            
            i = Image.open(image_path)
            i = ImageOps.exif_transpose(i)
            image_data = i.convert("RGB")
            image_data = np.array(image_data).astype(np.float32) / 255.0
            end_image = torch.from_numpy(image_data)[None,]
            print(f"🖼️ [XB-BOX] 已成功加载面板预览图: {end_image_file}")

        pos_cond, = nodes.CLIPTextEncode().encode(b["clip"], positive_prompt)
        neg_cond, = nodes.CLIPTextEncode().encode(b["clip"], b["negative_prompt"])

        pos, neg, latent = XB_WanFirstLastFrameToVideo().process(
            positive=pos_cond, negative=neg_cond, vae=b["vae"], 
            clip_vision_start_image=None, clip_vision_end_image=None, 
            start_image=start_image, end_image=end_image, 
            width=b["width"], height=b["height"], length=b["length"], 
            batch_size=1, vae_tile_size=b["vae_tile_size"]
        )

        print(f"🔥 [XB-BOX] 启动高噪引擎 (0 -> {b['high_noise_steps']} 步)...")
        latent_high, = nodes.KSamplerAdvanced().sample(
            model=b["model_high"], add_noise="enable", noise_seed=seed,
            steps=b["steps"], cfg=b["cfg"], sampler_name=b["sampler_name"], scheduler=b["scheduler"],
            positive=pos, negative=neg, latent_image=latent,
            start_at_step=0, end_at_step=b["high_noise_steps"], return_with_leftover_noise="enable" 
        )

        print(f"❄️ [XB-BOX] 切换低噪引擎 ({b['high_noise_steps']} -> 补齐满步)...")
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
            print("✂️ [XB-BOX] 已触发物理去重：切除重叠首帧。")

        if is_4d:
            last_frame = decoded_image[-1:, :, :, :]
            out_length = decoded_image.shape[0]
        else:
            last_frame = decoded_image[:, -1:, :, :, :]
            out_length = decoded_image.shape[1]

        print(f"✅ [XB-BOX] 当前批次完成！新生成片段长度: {out_length} 帧")
        
        if prev_video is not None:
            print("🧩 [XB-BOX] 检测到连入的上一段视频，正在执行雪球累加合并...")
            concat_dim = 0 if is_4d else 1
            final_video = torch.cat([prev_video, decoded_image], dim=concat_dim)
            print(f"🎉 [XB-BOX] 雪球累加完成！当前长视频已达: {final_video.shape[concat_dim]} 帧")
        else:
            final_video = decoded_image

        return (wan_bus, last_frame, final_video)


# ====================================================================
# 积木三：【🧩 视频无缝拼接器】
# ====================================================================
class XB_Video_Merger:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {"required": {}, "optional": {}}
        for i in range(1, 11):
            inputs["optional"][f"video_{i}"] = ("IMAGE",)
        return inputs
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("🎞️ 完整长视频",)
    FUNCTION = "merge_videos"
    CATEGORY = "小白工具箱/流水线架构"

    def merge_videos(self, **kwargs):
        videos = []
        for i in range(1, 11):
            vid = kwargs.get(f"video_{i}")
            if vid is not None:
                videos.append(vid)

        if not videos:
            raise ValueError("🚨 [XB-BOX] 合并失败：至少需要连入一段视频！")
            
        print(f"🧩 [XB-BOX] 正在执行 {len(videos)} 段视频无缝物理合并...")
        
        concat_dim = 0 if len(videos[0].shape) == 4 else 1
        final_video = torch.cat(videos, dim=concat_dim) 
        
        total_frames = final_video.shape[concat_dim]
        print(f"🎉 [XB-BOX] 视频合并成功！长视频总帧数: {total_frames} 帧")
        
        return (final_video,)


# ====================================================================
# 积木四：【🧊 分镜阵列切割机】
# ====================================================================
class XB_StoryboardSlicer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": ([
                    "三宫格 (1行3列 · 横向)", 
                    "三宫格 (3行1列 · 竖向)", 
                    "四宫格 (2行2列)", 
                    "六宫格 (2行3列 · 横向)", 
                    "六宫格 (3行2列 · 竖向)", 
                    "九宫格 (3行3列)"
                ], {"default": "四宫格 (2行2列)"}),
                "crop_margin": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 0.45, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("图1", "图2", "图3", "图4", "图5", "图6", "图7", "图8", "图9")
    FUNCTION = "slice_image"
    CATEGORY = "小白工具箱/流水线架构"

    def slice_image(self, image, mode, crop_margin):
        print(f"\n✂️ [XB-BOX] 启动分镜切割机，当前模式: {mode} | 裁边比例: {crop_margin}")
        
        if "1行3列" in mode: rows, cols = 1, 3
        elif "3行1列" in mode: rows, cols = 3, 1
        elif "2行2列" in mode: rows, cols = 2, 2
        elif "2行3列" in mode: rows, cols = 2, 3
        elif "3行2列" in mode: rows, cols = 3, 2
        elif "3行3列" in mode: rows, cols = 3, 3
        else: rows, cols = 2, 2 

        batch_size, h, w, channels = image.shape
        
        slice_h = h // rows
        slice_w = w // cols
        
        crop_y = int(slice_h * crop_margin)
        crop_x = int(slice_w * crop_margin)

        print(f"📐 [XB-BOX] 原图: {w}x{h} -> 原始切片: {slice_w}x{slice_h} -> 环切后实际输出: {slice_w - crop_x*2}x{slice_h - crop_y*2}")

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

        print(f"✅ [XB-BOX] 分割完成: {rows * cols} 张有效画面 | 🛡️ 已生成 {empty_count} 个纯黑防爆占位符。")
        
        return tuple(sliced_images)