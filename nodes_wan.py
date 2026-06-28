"""
XB-ToolBox Wan 视频节点 (ROCm 优化版)
=====================================
完全独立：XB_WanAnimateToVideo / CompileSettings / BlockSwap 零依赖。
ModelLoader / Sampler / VAELoader / Decode / TextEncode 需要 ComfyUI-WanVideoWrapper。
"""
import torch
import os
import sys
import gc
import importlib.util
import comfy.model_management as mm
import folder_paths

_SCALE_METHODS = ["lanczos", "bilinear", "bicubic", "nearest-exact", "area"]
_CROP_MODES = ["disabled", "center"]

# ROCm 全局补丁（纯 torch，零依赖）
if not hasattr(torch.backends.cuda, "matmul"):
    class _FM: allow_fp16_accumulation = False
    torch.backends.cuda.matmul = _FM()
elif not hasattr(torch.backends.cuda.matmul, "allow_fp16_accumulation"):
    torch.backends.cuda.matmul.allow_fp16_accumulation = False
if not hasattr(torch.cuda, "get_device_capability"):
    torch.cuda.get_device_capability = lambda d=None: (9, 0)
if not hasattr(torch.cuda, "reset_peak_memory_stats"):
    torch.cuda.reset_peak_memory_stats = lambda d=None: None

_PKG_NAME = "_xb_wanwrapper"
_wan_loaded = False


def _find_wan_root():
    for base in folder_paths.get_folder_paths("custom_nodes"):
        for n in os.listdir(base):
            if n.startswith("ComfyUI-WanVideoWrapper"):
                p = os.path.join(base, n)
                if os.path.exists(os.path.join(p, "__init__.py")):
                    return p
    raise RuntimeError(
        "ComfyUI-WanVideoWrapper 未安装。\n"
        "此节点依赖它作为模型架构库。\n"
        "XB_WanAnimateToVideo/XB_WanCompileSettings/XB_WanBlockSwap 不需要。"
    )


def _wan_setup():
    global _wan_loaded
    if _wan_loaded: return
    root = _find_wan_root()
    if _PKG_NAME not in sys.modules:
        s = importlib.util.spec_from_file_location(_PKG_NAME, os.path.join(root, "__init__.py"), submodule_search_locations=[root])
        m = importlib.util.module_from_spec(s)
        sys.modules[_PKG_NAME] = m
        s.loader.exec_module(m)
    _wan_loaded = True


def _wan_import(rel_path: str):
    _wan_setup()
    full = _PKG_NAME + "." + rel_path
    if full in sys.modules: return sys.modules[full]
    root = _find_wan_root()
    parts = rel_path.split(".")
    fp = os.path.join(root, *parts[:-1], parts[-1] + ".py")
    if not os.path.exists(fp):
        fp = os.path.join(root, *parts, "__init__.py")
    s = importlib.util.spec_from_file_location(full, fp)
    m = importlib.util.module_from_spec(s)
    sys.modules[full] = m
    s.loader.exec_module(m)
    return m


# ============================================================
# XB_WanCompileSettings — Wan 编译设置
# ============================================================
class XB_WanCompileSettings:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "backend": (["inductor"], {"default": "inductor"}),
            "fullgraph": ("BOOLEAN", {"default": False}),
            "mode": (["default", "reduce-overhead", "max-autotune"], {"default": "default"}),
            "dynamic": ("BOOLEAN", {"default": False}),
            "dynamo_cache_size_limit": ("INT", {"default": 64, "min": 0, "max": 1024}),
            "compile_transformer_blocks_only": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = ("WANCOMPILEARGS",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/Wan"
    def go(self, **kw):
        kw.setdefault("force_parameter_static_shapes", False)
        kw.setdefault("allow_unmerged_lora_compile", False)
        return (kw,)


# ============================================================
# XB_WanModelLoader — Wan 模型加载器
# ============================================================
class XB_WanModelLoader:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": (folder_paths.get_filename_list("diffusion_models"),),
                "base_precision": (["bf16", "fp16", "fp32"], {"default": "bf16"}),
                "quantization": (["disabled", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"], {"default": "disabled"}),
                "load_device": (["main_device", "offload_device"], {"default": "main_device"}),
                "attention_mode": (["sdpa", "sageattn"], {"default": "sdpa"}),
                "rms_norm_function": (["default", "pytorch"], {"default": "default"}),
            },
            "optional": {
                "block_swap_args": ("BLOCKSWAPARGS",),
                "compile_args": ("WANCOMPILEARGS",),
                "lora": ("WANVIDLORA",),
            },
        }
    RETURN_TYPES = ("WANVIDEOMODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/Wan"

    def go(self, model, base_precision, quantization, load_device, attention_mode,
           rms_norm_function, block_swap_args=None, compile_args=None, lora=None):
        if attention_mode is not None and "flash" in str(attention_mode):
            attention_mode = "sdpa"
        if base_precision == "fp16_fast":
            base_precision = "bf16"
        if compile_args is not None and hasattr(torch.version, 'hip') and torch.version.hip:
            compile_args = None
        kw = {"model": model, "base_precision": base_precision, "quantization": quantization,
              "load_device": load_device, "attention_mode": attention_mode, "rms_norm_function": rms_norm_function}
        if block_swap_args is not None: kw["block_swap_args"] = block_swap_args
        if compile_args is not None: kw["compile_args"] = compile_args
        if lora is not None: kw["lora"] = lora
        return _wan_import("nodes_model_loading").WanVideoModelLoader().loadmodel(**kw)


# ============================================================
# XB_WanBlockSwap — Wan 分块交换
# ============================================================
class XB_WanBlockSwap:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "blocks_to_swap": ("INT", {"default": 0, "min": 0, "max": 48}),
            "offload_img_emb": ("BOOLEAN", {"default": False}),
            "offload_txt_emb": ("BOOLEAN", {"default": False}),
            "use_non_blocking": ("BOOLEAN", {"default": True}),
            "prefetch_blocks": ("INT", {"default": 0, "min": 0, "max": 40}),
            "vace_blocks_to_swap": ("INT", {"default": 0, "min": 0, "max": 15}),
        }}
    RETURN_TYPES = ("BLOCKSWAPARGS",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/Wan"
    def go(self, **kw): return (kw,)


# ============================================================
# XB_WanSampler — Wan 采样器
# ============================================================
class XB_WanSampler:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("WANVIDEOMODEL",),
                "image_embeds": ("WANVIDIMAGE_EMBEDS",),
                "steps": ("INT", {"default": 20, "min": 1, "max": 1000}),
                "cfg": ("FLOAT", {"default": 6.0, "min": 0.0, "max": 30.0, "step": 0.5}),
                "shift": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.5}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
                "force_offload": ("BOOLEAN", {"default": True}),
                "scheduler": (["unipc", "dpmpp_2m", "dpmpp_sde", "euler", "heun"], {"default": "unipc"}),
                "riflex_freq_index": ("INT", {"default": 0, "min": 0, "max": 1000}),
                "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理"], {"default": "单次缓存清理"}),
            },
            "optional": {
                "text_embeds": ("WANVIDEOTEXTEMBEDS",),
                "samples": ("LATENT",),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "batched_cfg": ("BOOLEAN", {"default": False}),
            },
        }
    RETURN_TYPES = ("LATENT", "LATENT")
    RETURN_NAMES = ("samples", "denoised_samples")
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/Wan"

    def go(self, model, image_embeds, steps, cfg, shift, seed, force_offload, scheduler,
           riflex_freq_index, cleanup="单次缓存清理", text_embeds=None,
           samples=None, denoise=1.0, batched_cfg=False, **extra):
        # 🔧 SDPA 路由已从全局污染改为 context manager（见 nodes_rocm.py _sdp_context），
        #    此采样器调用 WanVideoSampler（自有 Attention 实现），不依赖 PyTorch SDPA 全局设置
        kw = {"model": model, "image_embeds": image_embeds, "shift": shift,
              "steps": steps, "cfg": cfg, "seed": seed, "force_offload": force_offload,
              "scheduler": scheduler, "riflex_freq_index": riflex_freq_index}
        if text_embeds is not None: kw["text_embeds"] = text_embeds
        if samples is not None: kw["samples"] = samples
        if denoise < 1.0: kw["denoise_strength"] = denoise
        if batched_cfg: kw["batched_cfg"] = batched_cfg
        kw.update(extra)

        is_amd = torch.cuda.is_available() and hasattr(torch.version, 'hip') and torch.version.hip

        try:
            r = _wan_import("nodes_sampler").WanVideoSampler().process(**kw)
        except Exception as e:
            if is_amd:
                print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
                print(f"[XB_ToolBox 错误信息] {e}")
                torch.cuda.synchronize()
                mm.soft_empty_cache()
                torch.cuda.empty_cache()
                gc.collect()
                # 清理后重试一次（A卡环境可能因显存碎片导致首次失败）
                r = _wan_import("nodes_sampler").WanVideoSampler().process(**kw)
            else:
                raise

        if cleanup == "单次缓存清理":
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        elif cleanup == "双次缓存清理":
            torch.cuda.synchronize()
            mm.soft_empty_cache()
            torch.cuda.empty_cache()
            gc.collect()
        return r


# ============================================================
# XB_WanTextEncode — Wan 文本编码
# ============================================================
class XB_WanTextEncode:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "t5_model": ("WANTEXTENCODER",),
            "positive_prompt": ("STRING", {"multiline": True, "default": ""}),
            "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
            "use_disk_cache": ("BOOLEAN", {"default": True}),
            "device": (["gpu", "cpu"], {"default": "gpu"}),
        }}
    RETURN_TYPES = ("WANVIDEOTEXTEMBEDS",)
    RETURN_NAMES = ("text_embeds",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/Wan"
    def go(self, t5_model, positive_prompt, negative_prompt, use_disk_cache, device):
        return _wan_import("nodes").WanVideoTextEncode().process(
            positive_prompt=positive_prompt, negative_prompt=negative_prompt,
            t5=t5_model, use_disk_cache=use_disk_cache, device=device)


# ============================================================
# XB_WanVAELoader — Wan VAE 加载器
# ============================================================
class XB_WanVAELoader:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model_name": (folder_paths.get_filename_list("vae"),),
            "precision": (["bf16", "fp16", "fp32"], {"default": "bf16"}),
        }, "optional": {
            "compile_args": ("WANCOMPILEARGS",),
            "use_cpu_cache": ("BOOLEAN", {"default": False}),
        }}
    RETURN_TYPES = ("WANVAE",)
    RETURN_NAMES = ("vae",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/Wan"
    def go(self, model_name, precision, compile_args=None, use_cpu_cache=False):
        import comfy.utils as cu
        dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[precision]
        sd = cu.load_torch_file(folder_paths.get_full_path_or_raise("vae", model_name), safe_load=True)
        if not any(k.startswith("model.") for k in sd):
            sd = {f"model.{k}": v for k, v in sd.items()}
        dim = sd["model.decoder.conv1.bias"].shape[0]
        pruning_rate = 0.75 if dim == 96 else 0.0
        mod = _wan_import("wanvideo.wan_video_vae")
        cls = mod.WanVideoVAE38 if sd["model.conv2.weight"].shape[0] == 48 else mod.WanVideoVAE
        vae = cls(dtype=dtype, pruning_rate=pruning_rate, cpu_cache=use_cpu_cache)
        vae.load_state_dict(sd)
        del sd
        vae.eval()
        vae.to(dtype=dtype)
        print(f"  [XB_WanVAELoader] {model_name} | {precision} | pruning={pruning_rate}")
        return (vae,)


# ============================================================
# XB_WanDecode — Wan VAE 解码
# ============================================================
class XB_WanDecode:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "vae": ("WANVAE",), "samples": ("LATENT",),
            "enable_vae_tiling": ("BOOLEAN", {"default": True}),
            "tile_x": ("INT", {"default": 256, "min": 64, "max": 1024, "step": 64}),
            "tile_y": ("INT", {"default": 256, "min": 64, "max": 1024, "step": 64}),
            "tile_stride_x": ("INT", {"default": 192, "min": 32, "max": 1024, "step": 32}),
            "tile_stride_y": ("INT", {"default": 192, "min": 32, "max": 1024, "step": 32}),
            "cleanup": (["不做任何清理", "单次缓存清理", "双次缓存清理", "卸载显存模型"], {"default": "单次缓存清理"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/Wan"
    def go(self, vae, samples, enable_vae_tiling, tile_x, tile_y,
           tile_stride_x, tile_stride_y, cleanup="单次缓存清理"):
        is_amd = torch.cuda.is_available() and hasattr(torch.version, 'hip') and torch.version.hip

        try:
            r = _wan_import("nodes").WanVideoDecode().decode(
                vae=vae, samples=samples, enable_vae_tiling=enable_vae_tiling,
                tile_x=tile_x, tile_y=tile_y, tile_stride_x=tile_stride_x, tile_stride_y=tile_stride_y)
        except Exception as e:
            if is_amd:
                print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
                print(f"[XB_ToolBox 错误信息] {e}")
                torch.cuda.synchronize()
                mm.soft_empty_cache()
                torch.cuda.empty_cache()
                gc.collect()
                # 清理后重试一次
                r = _wan_import("nodes").WanVideoDecode().decode(
                    vae=vae, samples=samples, enable_vae_tiling=enable_vae_tiling,
                    tile_x=tile_x, tile_y=tile_y, tile_stride_x=tile_stride_x, tile_stride_y=tile_stride_y)
            else:
                raise

        if cleanup == "单次缓存清理":
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        elif cleanup == "双次缓存清理":
            torch.cuda.synchronize()
            mm.soft_empty_cache()
            torch.cuda.empty_cache()
            gc.collect()
        elif cleanup == "卸载显存模型":
            mm.unload_all_models()
            mm.soft_empty_cache()
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            gc.collect()
        return r


# ============================================================
# XB_WanAnimateToVideo — Wan 动画转视频
# ============================================================
class XB_WanAnimateToVideo:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "positive": ("CONDITIONING",), "negative": ("CONDITIONING",), "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 16384, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 16384, "step": 16}),
                "length": ("INT", {"default": 77, "min": 1, "max": 16384, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "continue_motion_max_frames": ("INT", {"default": 5, "min": 1, "max": 16384, "step": 4}),
                "video_frame_offset": ("INT", {"default": 0, "min": 0, "max": 16384, "step": 1}),
                "vae_tile_size": ("INT", {"default": 256, "min": 0, "max": 2048, "step": 64}),
            },
            "optional": {
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "reference_image": ("IMAGE",), "face_video": ("IMAGE",),
                "pose_video": ("IMAGE",), "background_video": ("IMAGE",),
                "character_mask": ("MASK",), "continue_motion": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            },
        }
    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT", "INT", "INT", "INT")
    RETURN_NAMES = ("positive", "negative", "latent", "trim_latent", "trim_image", "video_frame_offset")
    FUNCTION = "go"
    CATEGORY = "XB_ToolBox/Wan"

    def go(self, positive, negative, vae, width, height, length, batch_size,
           continue_motion_max_frames, video_frame_offset, vae_tile_size=256,
           reference_image=None, clip_vision_output=None, face_video=None,
           pose_video=None, continue_motion=None, background_video=None, character_mask=None,
           scale_method="lanczos", crop_mode="center"):
        import comfy.utils
        import node_helpers
        def _enc(pixels):
            if pixels.dim() == 3: pixels = pixels.unsqueeze(0)
            p = pixels[:, :, :, :3]

            # 🛡️ 显存连续性重组
            if not p.is_contiguous(): p = p.contiguous()
            # 🛡️ VAE 精度对齐
            if hasattr(vae, 'first_stage_model'):
                vae_dtype = getattr(vae.first_stage_model, 'dtype', None)
                if vae_dtype is None:
                    try: vae_dtype = next(vae.first_stage_model.parameters()).dtype
                    except: pass
                if vae_dtype is not None and p.dtype != vae_dtype:
                    p = p.to(vae_dtype)

            if vae_tile_size and vae_tile_size > 0:
                try: return vae.encode_tiled(p, tile_x=vae_tile_size, tile_y=vae_tile_size, overlap=32, tile_t=32, overlap_t=4)
                except (AttributeError, TypeError): pass
            return vae.encode(p)
        trim_latent, ref_motion_latent_length = 0, 0
        latent_length = ((length - 1) // 4) + 1
        if reference_image is None: reference_image = torch.zeros((1, height, width, 3))
        image = comfy.utils.common_upscale(reference_image[:length].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
        concat_latent_image = _enc(image)
        mask = torch.zeros((1, 4, concat_latent_image.shape[-3], concat_latent_image.shape[-2], concat_latent_image.shape[-1]), device=concat_latent_image.device, dtype=concat_latent_image.dtype)
        trim_latent += concat_latent_image.shape[2]
        if continue_motion is None:
            image = torch.ones((length, height, width, 3)) * 0.5
        else:
            continue_motion = continue_motion[-continue_motion_max_frames:]
            video_frame_offset = max(0, video_frame_offset - continue_motion.shape[0])
            continue_motion = comfy.utils.common_upscale(continue_motion[-length:].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
            image = torch.ones((length, height, width, continue_motion.shape[-1]), device=continue_motion.device, dtype=continue_motion.dtype) * 0.5
            image[:continue_motion.shape[0]] = continue_motion
            ref_motion_latent_length += ((continue_motion.shape[0] - 1) // 4) + 1
        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})
            negative = node_helpers.conditioning_set_values(negative, {"clip_vision_output": clip_vision_output})
        if pose_video is not None:
            if pose_video.shape[0] <= video_frame_offset: pose_video = None
            else: pose_video = pose_video[video_frame_offset:]
        if pose_video is not None:
            pose_video = comfy.utils.common_upscale(pose_video[:length].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
            if pose_video.shape[0] < length: pose_video = torch.cat((pose_video,) + (pose_video[-1:],) * (length - pose_video.shape[0]), dim=0)
            pvl = _enc(pose_video)
            positive = node_helpers.conditioning_set_values(positive, {"pose_video_latent": pvl})
            negative = node_helpers.conditioning_set_values(negative, {"pose_video_latent": pvl})
        if face_video is not None:
            if face_video.shape[0] <= video_frame_offset: face_video = None
            else: face_video = face_video[video_frame_offset:]
        if face_video is not None:
            fv = comfy.utils.common_upscale(face_video[:length].movedim(-1, 1), 512, 512, "area", "center") * 2.0 - 1.0
            fv = fv.movedim(0, 1).unsqueeze(0)
            positive = node_helpers.conditioning_set_values(positive, {"face_video_pixels": fv})
            negative = node_helpers.conditioning_set_values(negative, {"face_video_pixels": fv * 0.0 - 1.0})
        ref_images_num = max(0, ref_motion_latent_length * 4 - 3)
        if background_video is not None and background_video.shape[0] > video_frame_offset:
            bg = comfy.utils.common_upscale(background_video[video_frame_offset:][:length].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
            if bg.shape[0] > ref_images_num: image[ref_images_num:bg.shape[0]] = bg[ref_images_num:]
        mask_ref = torch.ones((1, 1, latent_length * 4, concat_latent_image.shape[-2], concat_latent_image.shape[-1]), device=mask.device, dtype=mask.dtype)
        if continue_motion is not None: mask_ref[:, :, :ref_motion_latent_length * 4] = 0.0
        if character_mask is not None:
            if character_mask.shape[0] > video_frame_offset or character_mask.shape[0] == 1:
                cm = character_mask.repeat((length,) + (1,) * (character_mask.ndim - 1)) if character_mask.shape[0] == 1 else character_mask[video_frame_offset:]
                # cm: [T, H, W] (3D) → 保持4D传入 common_upscale
                if cm.ndim == 3:
                    cm = cm.unsqueeze(1)  # [T, 1, H, W]
                cm = comfy.utils.common_upscale(cm[:length], concat_latent_image.shape[-1], concat_latent_image.shape[-2], "nearest-exact", "center")
                # cm: [length, 1, H_lat, W_lat] → 转为 [1, 1, length, H_lat, W_lat]
                cm = cm.permute(1, 0, 2, 3).unsqueeze(0)
                if cm.shape[2] > ref_images_num: mask_ref[:, :, ref_images_num:cm.shape[2]] = cm[:, :, ref_images_num:]
        concat_latent_image = torch.cat((concat_latent_image, _enc(image)), dim=2)
        mask_ref = mask_ref.view(1, mask_ref.shape[2] // 4, 4, mask_ref.shape[3], mask_ref.shape[4]).transpose(1, 2)
        mask = torch.cat((mask, mask_ref), dim=2)
        positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent_image, "concat_mask": mask})
        negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent_image, "concat_mask": mask})
        latent = torch.zeros([batch_size, 16, latent_length + trim_latent, height // 8, width // 8], device=comfy.model_management.intermediate_device())
        return (positive, negative, {"samples": latent}, trim_latent, max(0, ref_motion_latent_length * 4 - 3), video_frame_offset + length)


__all__ = [
    "XB_WanCompileSettings", "XB_WanModelLoader", "XB_WanBlockSwap",
    "XB_WanSampler", "XB_WanTextEncode", "XB_WanVAELoader", "XB_WanDecode",
    "XB_WanAnimateToVideo",
]
