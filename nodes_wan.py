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
        "XB_WanAnimateToVideo/XB_WanCompileSettings 不需要。"
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
    "XB_WanCompileSettings", "XB_WanAnimateToVideo",
]
