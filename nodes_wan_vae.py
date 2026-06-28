import torch
import comfy.model_management
import comfy.utils
import comfy.patcher_extension
import node_helpers
import comfy.clip_vision
import math
import numpy as np
import nodes

_SCALE_METHODS = ["lanczos", "bilinear", "bicubic", "nearest-exact", "area"]
_CROP_MODES = ["center", "disabled"]

def _upscale(img, w, h, method="lanczos", crop="center"):
    """Upscale helper for all nodes"""
    return comfy.utils.common_upscale(img.movedim(-1, 1), w, h, method, crop).movedim(1, -1)

def _encode_vae(vae, pixels, tile_size):
    if pixels.dim() == 3:
        pixels = pixels.unsqueeze(0)
    p = pixels[:, :, :, :3]

    # 🛡️ 显存连续性重组 (movedim/切片会产生非连续张量，MIOpen 无法处理)
    if not p.is_contiguous():
        p = p.contiguous()

    # 🛡️ VAE 精度对齐 (输入 float32 vs 权重 bfloat16 会 RuntimeError)
    if hasattr(vae, 'first_stage_model'):
        vae_dtype = getattr(vae.first_stage_model, 'dtype', None)
        if vae_dtype is None:
            try: vae_dtype = next(vae.first_stage_model.parameters()).dtype
            except: pass
        if vae_dtype is not None and p.dtype != vae_dtype:
            p = p.to(vae_dtype)

    if tile_size == 0 or tile_size is None:
        return vae.encode(p)
    else:
        # 🔧 overlap_t = tile_t//2: Wan 3D VAE 时间卷积需要充足上下文帧，
        #    overlap_t=4 (12.5%) 导致分块边界 latent 衰减 → 解码尾帧发灰
        return vae.encode_tiled(p, tile_x=tile_size, tile_y=tile_size, overlap=32, tile_t=32, overlap_t=16)

# ============================================================
# XB_WanImageToVideo — Wan 图生视频
# ============================================================
class XB_WanImageToVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 1}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 8192, "step": 1}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "start_image": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, clip_vision_output=None, start_image=None, scale_method="lanczos", crop_mode="center"):
        spacial_scale = vae.spacial_compression_encode()
        latent_channels = vae.latent_channels
        latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())

        if start_image is not None:
            start_image = _upscale(start_image[:length], width, height, scale_method, crop_mode)
            image = torch.ones((length, height, width, start_image.shape[-1]), device=start_image.device, dtype=start_image.dtype) * 0.5
            image[:start_image.shape[0]] = start_image

            concat_latent_image = _encode_vae(vae, image, vae_tile_size)

            mask = torch.ones((1, 1, latent.shape[2] * 4, concat_latent_image.shape[-2], concat_latent_image.shape[-1]), device=start_image.device, dtype=start_image.dtype)
            mask[:, :, :start_image.shape[0] + 3] = 0.0
            mask = mask.view(1, mask.shape[2] // 4, 4, mask.shape[3], mask.shape[4]).transpose(1, 2)

            positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent_image, "concat_mask": mask})
            negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent_image, "concat_mask": mask})

        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})

        return (positive, negative, {"samples": latent})


# ============================================================
# XB_WanFirstLastFrameToVideo — Wan 首尾帧转视频
# ============================================================
class XB_WanFirstLastFrameToVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 1}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 8192, "step": 1}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "clip_vision_start_image": ("CLIP_VISION_OUTPUT",),
                "clip_vision_end_image": ("CLIP_VISION_OUTPUT",),
                "start_image": ("IMAGE",),
                "end_image": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, clip_vision_start_image=None, clip_vision_end_image=None, start_image=None, end_image=None, scale_method="lanczos", crop_mode="center"):
        spacial_scale = vae.spacial_compression_encode()
        latent = torch.zeros([batch_size, vae.latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        
        if start_image is not None:
            start_image = _upscale(start_image[:length], width, height, scale_method, crop_mode)
        if end_image is not None:
            end_image = _upscale(end_image[-length:], width, height, scale_method, crop_mode)

        image = torch.ones((length, height, width, 3), device=latent.device) * 0.5
        mask = torch.ones((1, 1, latent.shape[2] * 4, latent.shape[-2], latent.shape[-1]), device=latent.device)

        if start_image is not None:
            image[:start_image.shape[0]] = start_image
            mask[:, :, :start_image.shape[0] + 3] = 0.0

        if end_image is not None:
            image[-end_image.shape[0]:] = end_image
            mask[:, :, -end_image.shape[0]:] = 0.0

        concat_latent_image = _encode_vae(vae, image, vae_tile_size)

        mask = mask.view(1, mask.shape[2] // 4, 4, mask.shape[3], mask.shape[4]).transpose(1, 2)
        positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent_image, "concat_mask": mask})
        negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent_image, "concat_mask": mask})

        clip_vision_output = None
        if clip_vision_start_image is not None:
            clip_vision_output = clip_vision_start_image

        if clip_vision_end_image is not None:
            if clip_vision_output is not None:
                states = torch.cat([clip_vision_output.penultimate_hidden_states, clip_vision_end_image.penultimate_hidden_states], dim=-2)
                clip_vision_output = comfy.clip_vision.Output()
                clip_vision_output.penultimate_hidden_states = states
            else:
                clip_vision_output = clip_vision_end_image

        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})

        return (positive, negative, {"samples": latent})


# ============================================================
# XB_WanFunControlToVideo — Wan FunControl 转视频
# ============================================================
class XB_WanFunControlToVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "start_image": ("IMAGE",),
                "control_video": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, start_image=None, clip_vision_output=None, control_video=None, scale_method="lanczos", crop_mode="center"):
        spacial_scale = vae.spacial_compression_encode()
        latent_channels = vae.latent_channels
        latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        concat_latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        concat_latent = comfy.latent_formats.Wan21().process_out(concat_latent)
        concat_latent = concat_latent.repeat(1, 2, 1, 1, 1)

        if start_image is not None:
            start_image = _upscale(start_image[:length], width, height, scale_method, crop_mode)
            concat_latent_image = _encode_vae(vae, start_image, vae_tile_size)
            concat_latent[:,latent_channels:,:concat_latent_image.shape[2]] = concat_latent_image[:,:,:concat_latent.shape[2]]

        if control_video is not None:
            control_video = _upscale(control_video[:length], width, height, scale_method, crop_mode)
            concat_latent_image = _encode_vae(vae, control_video, vae_tile_size)
            concat_latent[:,:latent_channels,:concat_latent_image.shape[2]] = concat_latent_image[:,:,:concat_latent.shape[2]]

        positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent})
        negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent})

        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})
            negative = node_helpers.conditioning_set_values(negative, {"clip_vision_output": clip_vision_output})

        out_latent = {}
        out_latent["samples"] = latent
        return (positive, negative, out_latent)


# ============================================================
# XB_WanVaceToVideo — Wan VACE 视频编辑
# ============================================================
class XB_WanVaceToVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1000.0, "step": 0.01}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "control_video": ("IMAGE",),
                "control_masks": ("MASK",),
                "reference_image": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT", "INT")
    RETURN_NAMES = ("positive", "negative", "latent", "trim_latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, strength, vae_tile_size,
                control_video=None, control_masks=None, reference_image=None,
                scale_method="lanczos", crop_mode="center"):
        latent_length = ((length - 1) // 4) + 1

        if control_video is not None:
            control_video = comfy.utils.common_upscale(control_video[:length].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
            if control_video.shape[0] < length:
                control_video = torch.nn.functional.pad(control_video, (0, 0, 0, 0, 0, 0, 0, length - control_video.shape[0]), value=0.5)
        else:
            control_video = torch.ones((length, height, width, 3)) * 0.5

        if reference_image is not None:
            reference_image = comfy.utils.common_upscale(reference_image[:1].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
            reference_image = _encode_vae(vae, reference_image[:, :, :, :3], vae_tile_size)
            reference_image = torch.cat([reference_image, comfy.latent_formats.Wan21().process_out(torch.zeros_like(reference_image))], dim=1)

        if control_masks is None:
            mask = torch.ones((length, height, width, 1))
        else:
            mask = control_masks
            if mask.ndim == 3:
                mask = mask.unsqueeze(1)
            mask = comfy.utils.common_upscale(mask[:length], width, height, "bilinear", "center").movedim(1, -1)
            if mask.shape[0] < length:
                mask = torch.nn.functional.pad(mask, (0, 0, 0, 0, 0, 0, 0, length - mask.shape[0]), value=1.0)

        control_video = control_video - 0.5
        inactive = (control_video * (1 - mask)) + 0.5
        reactive = (control_video * mask) + 0.5

        inactive = _encode_vae(vae, inactive[:, :, :, :3], vae_tile_size)
        reactive = _encode_vae(vae, reactive[:, :, :, :3], vae_tile_size)
        control_video_latent = torch.cat((inactive, reactive), dim=1)
        if reference_image is not None:
            control_video_latent = torch.cat((reference_image, control_video_latent), dim=2)

        vae_stride = 8
        height_mask = height // vae_stride
        width_mask = width // vae_stride
        mask = mask.view(length, height_mask, vae_stride, width_mask, vae_stride)
        mask = mask.permute(2, 4, 0, 1, 3)
        mask = mask.reshape(vae_stride * vae_stride, length, height_mask, width_mask)
        mask = torch.nn.functional.interpolate(mask.unsqueeze(0), size=(latent_length, height_mask, width_mask), mode='nearest-exact').squeeze(0)

        trim_latent = 0
        if reference_image is not None:
            mask_pad = torch.zeros_like(mask[:, :reference_image.shape[2], :, :])
            mask = torch.cat((mask_pad, mask), dim=1)
            latent_length += reference_image.shape[2]
            trim_latent = reference_image.shape[2]

        mask = mask.unsqueeze(0)

        positive = node_helpers.conditioning_set_values(positive, {"vace_frames": [control_video_latent], "vace_mask": [mask], "vace_strength": [strength]}, append=True)
        negative = node_helpers.conditioning_set_values(negative, {"vace_frames": [control_video_latent], "vace_mask": [mask], "vace_strength": [strength]}, append=True)

        latent = torch.zeros([batch_size, 16, latent_length, height // 8, width // 8], device=comfy.model_management.intermediate_device())
        out_latent = {}
        out_latent["samples"] = latent
        return (positive, negative, out_latent, trim_latent)


# ============================================================
# XB_Wan22FunControlToVideo — Wan 2.2 FunControl 转视频
# ============================================================
class XB_Wan22FunControlToVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "ref_image": ("IMAGE",),
                "start_image": ("IMAGE",),
                "control_video": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, ref_image=None, start_image=None, control_video=None, scale_method="lanczos", crop_mode="center"):
        spacial_scale = vae.spacial_compression_encode()
        latent_channels = vae.latent_channels
        latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        concat_latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        if latent_channels == 48:
            concat_latent = comfy.latent_formats.Wan22().process_out(concat_latent)
        else:
            concat_latent = comfy.latent_formats.Wan21().process_out(concat_latent)
        concat_latent = concat_latent.repeat(1, 2, 1, 1, 1)
        mask = torch.ones((1, 1, latent.shape[2] * 4, latent.shape[-2], latent.shape[-1]), device=latent.device)

        if start_image is not None:
            start_image = _upscale(start_image[:length], width, height, scale_method, crop_mode)
            concat_latent_image = _encode_vae(vae, start_image, vae_tile_size)
            concat_latent[:,latent_channels:,:concat_latent_image.shape[2]] = concat_latent_image[:,:,:concat_latent.shape[2]]
            mask[:, :, :start_image.shape[0] + 3] = 0.0

        ref_latent = None
        if ref_image is not None:
            ref_image = _upscale(ref_image[:1], width, height, scale_method, crop_mode)
            ref_latent = _encode_vae(vae, ref_image, vae_tile_size)

        if control_video is not None:
            control_video = _upscale(control_video[:length], width, height, scale_method, crop_mode)
            concat_latent_image = _encode_vae(vae, control_video, vae_tile_size)
            concat_latent[:,:latent_channels,:concat_latent_image.shape[2]] = concat_latent_image[:,:,:concat_latent.shape[2]]

        mask = mask.view(1, mask.shape[2] // 4, 4, mask.shape[3], mask.shape[4]).transpose(1, 2)
        positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent, "concat_mask": mask, "concat_mask_index": latent_channels})
        negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent, "concat_mask": mask, "concat_mask_index": latent_channels})

        if ref_latent is not None:
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": [ref_latent]}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": [ref_latent]}, append=True)

        out_latent = {}
        out_latent["samples"] = latent
        return (positive, negative, out_latent)


def linear_interpolation(features, input_fps, output_fps, output_len=None):
    features = features.transpose(1, 2)
    seq_len = features.shape[2] / float(input_fps)
    if output_len is None:
        output_len = int(seq_len * output_fps)
    output_features = torch.nn.functional.interpolate(features, size=output_len, align_corners=True, mode='linear')
    return output_features.transpose(1, 2)

def get_sample_indices(original_fps, total_frames, target_fps, num_sample, fixed_start=None):
    required_duration = num_sample / target_fps
    required_origin_frames = int(np.ceil(required_duration * original_fps))
    if required_duration > total_frames / original_fps:
        raise ValueError("required_duration must be less than video length")
    if fixed_start is not None and fixed_start >= 0:
        start_frame = fixed_start
    else:
        max_start = total_frames - required_origin_frames
        if max_start < 0:
            raise ValueError("video length is too short")
        start_frame = np.random.randint(0, max_start + 1)
    start_time = start_frame / original_fps
    end_time = start_time + required_duration
    time_points = np.linspace(start_time, end_time, num_sample, endpoint=False)
    frame_indices = np.round(np.array(time_points) * original_fps).astype(int)
    frame_indices = np.clip(frame_indices, 0, total_frames - 1)
    return frame_indices

def get_audio_embed_bucket_fps(audio_embed, fps=16, batch_frames=81, m=0, video_rate=30):
    num_layers, audio_frame_num, audio_dim = audio_embed.shape
    return_all_layers = num_layers > 1
    scale = video_rate / fps
    min_batch_num = int(audio_frame_num / (batch_frames * scale)) + 1
    bucket_num = min_batch_num * batch_frames
    padd_audio_num = math.ceil(min_batch_num * batch_frames / fps * video_rate) - audio_frame_num
    batch_idx = get_sample_indices(video_rate, audio_frame_num + padd_audio_num, fps, bucket_num, fixed_start=0)
    batch_audio_eb = []
    audio_sample_stride = int(video_rate / fps)
    for bi in batch_idx:
        if bi < audio_frame_num:
            chosen_idx = list(range(bi - m * audio_sample_stride, bi + (m + 1) * audio_sample_stride, audio_sample_stride))
            chosen_idx = [0 if c < 0 else c for c in chosen_idx]
            chosen_idx = [audio_frame_num - 1 if c >= audio_frame_num else c for c in chosen_idx]
            if return_all_layers:
                frame_audio_embed = audio_embed[:, chosen_idx].flatten(start_dim=-2, end_dim=-1)
            else:
                frame_audio_embed = audio_embed[0][chosen_idx].flatten()
        else:
            frame_audio_embed = torch.zeros([audio_dim * (2 * m + 1)], device=audio_embed.device) if not return_all_layers else torch.zeros([num_layers, audio_dim * (2 * m + 1)], device=audio_embed.device)
        batch_audio_eb.append(frame_audio_embed)
    batch_audio_eb = torch.cat([c.unsqueeze(0) for c in batch_audio_eb], dim=0)
    return batch_audio_eb, min_batch_num

def xb_wan_sound_to_video(positive, negative, vae, width, height, length, batch_size, vae_tile_size, frame_offset=0, ref_image=None, audio_encoder_output=None, control_video=None, ref_motion=None, ref_motion_latent=None, scale_method="lanczos", crop_mode="center"):
    latent_t = ((length - 1) // 4) + 1
    if audio_encoder_output is not None:
        feat = torch.cat(audio_encoder_output["encoded_audio_all_layers"])
        video_rate = 30
        fps = 16
        feat = linear_interpolation(feat, input_fps=50, output_fps=video_rate)
        batch_frames = latent_t * 4
        audio_embed_bucket, num_repeat = get_audio_embed_bucket_fps(feat, fps=fps, batch_frames=batch_frames, m=0, video_rate=video_rate)
        audio_embed_bucket = audio_embed_bucket.unsqueeze(0)
        if len(audio_embed_bucket.shape) == 3:
            audio_embed_bucket = audio_embed_bucket.permute(0, 2, 1)
        elif len(audio_embed_bucket.shape) == 4:
            audio_embed_bucket = audio_embed_bucket.permute(0, 2, 3, 1)

        audio_embed_bucket = audio_embed_bucket[:, :, :, frame_offset:frame_offset + batch_frames]
        if audio_embed_bucket.shape[3] > 0:
            positive = node_helpers.conditioning_set_values(positive, {"audio_embed": audio_embed_bucket})
            negative = node_helpers.conditioning_set_values(negative, {"audio_embed": audio_embed_bucket * 0.0})
            frame_offset += batch_frames

    if ref_image is not None:
        ref_image = comfy.utils.common_upscale(ref_image[:1].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
        ref_latent = _encode_vae(vae, ref_image, vae_tile_size)
        positive = node_helpers.conditioning_set_values(positive, {"reference_latents": [ref_latent]}, append=True)
        negative = node_helpers.conditioning_set_values(negative, {"reference_latents": [ref_latent]}, append=True)

    if ref_motion is not None:
        if ref_motion.shape[0] > 73:
            ref_motion = ref_motion[-73:]
        ref_motion = comfy.utils.common_upscale(ref_motion.movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
        if ref_motion.shape[0] < 73:
            r = torch.ones([73, height, width, 3]) * 0.5
            r[-ref_motion.shape[0]:] = ref_motion
            ref_motion = r
        ref_motion_latent = _encode_vae(vae, ref_motion, vae_tile_size)

    if ref_motion is not None:
        ref_motion_latent = ref_motion_latent[:, :, -19:]
        positive = node_helpers.conditioning_set_values(positive, {"reference_motion": ref_motion_latent})
        negative = node_helpers.conditioning_set_values(negative, {"reference_motion": ref_motion_latent})

    latent = torch.zeros([batch_size, 16, latent_t, height // 8, width // 8], device=comfy.model_management.intermediate_device())

    control_video_out = comfy.latent_formats.Wan21().process_out(torch.zeros_like(latent))
    if control_video is not None:
        control_video = comfy.utils.common_upscale(control_video[:length].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
        control_video = _encode_vae(vae, control_video, vae_tile_size)
        control_video_out[:, :, :control_video.shape[2]] = control_video

    positive = node_helpers.conditioning_set_values(positive, {"control_video": control_video_out})
    negative = node_helpers.conditioning_set_values(negative, {"control_video": control_video_out})

    out_latent = {}
    out_latent["samples"] = latent
    return positive, negative, out_latent, frame_offset

# ============================================================
# XB_WanSoundImageToVideo — Wan 音频+图像转视频
# ============================================================
class XB_WanSoundImageToVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 77, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "audio_encoder_output": ("AUDIO_ENCODER_OUTPUT",),
                "ref_image": ("IMAGE",),
                "control_video": ("IMAGE",),
                "ref_motion": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, ref_image=None, audio_encoder_output=None, control_video=None, ref_motion=None, scale_method="lanczos", crop_mode="center"):
        positive, negative, out_latent, frame_offset = xb_wan_sound_to_video(
            positive, negative, vae, width, height, length, batch_size, vae_tile_size, 
            ref_image=ref_image, audio_encoder_output=audio_encoder_output,
            control_video=control_video, ref_motion=ref_motion,
            scale_method=scale_method, crop_mode=crop_mode)
        return (positive, negative, out_latent)


from comfy.ldm.wan.model_multitalk import InfiniteTalkOuterSampleWrapper, MultiTalkCrossAttnPatch, project_audio_features

def _linear_interp(features, input_fps, output_fps, output_len=None):
    features = features.transpose(1, 2)
    seq_len = features.shape[2] / float(input_fps)
    if output_len is None:
        output_len = int(seq_len * output_fps)
    output_features = torch.nn.functional.interpolate(features, size=output_len, align_corners=True, mode='linear')
    return output_features.transpose(1, 2)

def _process_infinite_talk_audio(model, model_patch, positive, negative, vae, width, height, length,
                                  audio_encoder_output_1, motion_frame_count, audio_scale, vae_tile_size,
                                  clip_vision_output=None, start_image=None,
                                  audio_encoder_output_2=None, previous_frames=None,
                                  mask_1=None, mask_2=None, segment_audio=False,
                                  global_frame_offset=None,
                                  scale_method="lanczos", crop_mode="center"):
    """共用音频处理 + 模型补丁核心逻辑（单人/双人复用）"""

    # 🌟 零拷贝克隆：所有补丁打在 clone 上，OOM/取消中断时原模型不受污染
    model = model.clone()

    if previous_frames is not None and previous_frames.shape[0] < motion_frame_count:
        raise ValueError("Not enough previous frames provided.")

    if audio_encoder_output_2 is not None:
        if mask_1 is None or mask_2 is None:
            raise ValueError("Masks must be provided if two audio encoder outputs are used.")

    ref_masks = None
    if mask_1 is not None and mask_2 is not None:
        if audio_encoder_output_2 is None:
            raise ValueError("Second audio encoder output must be provided if two masks are used.")
        ref_masks = torch.cat([mask_1, mask_2])

    latent = torch.zeros([1, 16, ((length - 1) // 4) + 1, height // 8, width // 8],
                        device=comfy.model_management.intermediate_device())

    concat_latent_image = None
    if start_image is not None:
        start_image = comfy.utils.common_upscale(start_image[:length].movedim(-1, 1), width, height, scale_method, crop_mode).movedim(1, -1)
        image = torch.ones((length, height, width, start_image.shape[-1]), device=start_image.device, dtype=start_image.dtype) * 0.5
        image[:start_image.shape[0]] = start_image

        concat_latent_image = _encode_vae(vae, image, vae_tile_size)
        concat_mask = torch.ones((1, 1, latent.shape[2] * 4, concat_latent_image.shape[-2], concat_latent_image.shape[-1]),
                                 device=start_image.device, dtype=start_image.dtype)
        concat_mask[:, :, :start_image.shape[0] + 3] = 0.0
        concat_mask = concat_mask.view(1, concat_mask.shape[2] // 4, 4, concat_mask.shape[3], concat_mask.shape[4]).transpose(1, 2)

        positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent_image, "concat_mask": concat_mask})
        negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent_image, "concat_mask": concat_mask})

    if clip_vision_output is not None:
        positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})
        negative = node_helpers.conditioning_set_values(negative, {"clip_vision_output": clip_vision_output})

    # === 音频处理管线 ===
    encoded_audio_list = []
    seq_lengths = []
    for audio_encoder_output in [audio_encoder_output_1, audio_encoder_output_2]:
        if audio_encoder_output is None:
            continue
        all_layers = audio_encoder_output["encoded_audio_all_layers"]
        encoded_audio = torch.stack(all_layers, dim=0).squeeze(1)[1:]
        encoded_audio = _linear_interp(encoded_audio, input_fps=50, output_fps=25).movedim(0, 1)
        encoded_audio_list.append(encoded_audio)
        seq_lengths.append(encoded_audio.shape[0])

    multi_audio_type = "add"
    if len(encoded_audio_list) > 1:
        if multi_audio_type == "para":
            max_len = max(seq_lengths)
            padded = []
            for emb in encoded_audio_list:
                if emb.shape[0] < max_len:
                    pad = torch.zeros(max_len - emb.shape[0], *emb.shape[1:], dtype=emb.dtype)
                    emb = torch.cat([emb, pad], dim=0)
                padded.append(emb)
            encoded_audio_list = padded
        elif multi_audio_type == "add":
            total_len = sum(seq_lengths)
            full_list = []
            offset = 0
            for emb, seq_len in zip(encoded_audio_list, seq_lengths):
                full = torch.zeros(total_len, *emb.shape[1:], dtype=emb.dtype)
                full[offset:offset + seq_len] = emb
                full_list.append(full)
                offset += seq_len
            encoded_audio_list = full_list

    token_ref_target_masks = None
    if ref_masks is not None:
        token_ref_target_masks = torch.nn.functional.interpolate(
            ref_masks.unsqueeze(0), size=(latent.shape[-2] // 2, latent.shape[-1] // 2), mode='nearest')[0]
        token_ref_target_masks = (token_ref_target_masks > 0).view(token_ref_target_masks.shape[0], -1)

    if previous_frames is not None:
        motion_frames = comfy.utils.common_upscale(previous_frames[-motion_frame_count:].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
        # 🔧 优先使用显式传入的全局偏移量，彻底废弃通过 shape 反推
        if global_frame_offset is not None:
            frame_offset = global_frame_offset
        else:
            frame_offset = previous_frames.shape[0] - motion_frame_count
        if segment_audio:
            audio_start = 0  # [fixed]
        else:
            audio_start = frame_offset
        audio_end = audio_start + length
        motion_frames_latent = _encode_vae(vae, motion_frames[:, :, :, :3], vae_tile_size)
        trim_image = motion_frame_count
    else:
        audio_start = trim_image = 0
        audio_end = length
        motion_frames_latent = concat_latent_image[:, :, :1] if concat_latent_image is not None else torch.zeros((1, 16, 1, height // 8, width // 8), device=latent.device)

    audio_embed = project_audio_features(model_patch.model.audio_proj, encoded_audio_list, audio_start, audio_end).to(model.model_dtype())


    for key in ("infinite_talk_outer_sample",):
        if hasattr(model, "wrappers") and key in model.wrappers:
            del model.wrappers[key]
    for key in ("attn2_patch",):
        if hasattr(model, "object_patches") and key in model.object_patches:
            del model.object_patches[key]
    top = model.model_options.setdefault("transformer_options", {})
    top.pop("audio_embeds", None)

    top["audio_embeds"] = audio_embed

    model.add_wrapper_with_key(
        comfy.patcher_extension.WrappersMP.OUTER_SAMPLE,
        "infinite_talk_outer_sample",
        InfiniteTalkOuterSampleWrapper(motion_frames_latent, model_patch, is_extend=previous_frames is not None))
    model.set_model_patch(MultiTalkCrossAttnPatch(model_patch, audio_scale), "attn2_patch")

    out_latent = {"samples": latent}
    return model, positive, negative, out_latent, trim_image


# ============================================================
# XB_WanInfiniteTalkToVideo_Single — Wan 单人语音转视频
# ============================================================
class XB_WanInfiniteTalkToVideo_Single:
    """单人语音转视频分块 -- 对应 WanInfiniteTalkToVideo (single_speaker) + VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "model_patch": ("MODEL_PATCH",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "audio_encoder_output_1": ("AUDIO_ENCODER_OUTPUT",),
                "motion_frame_count": ("INT", {"default": 9, "min": 1, "max": 33, "step": 1}),
                "audio_scale": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
                "vae_tile_size": ("INT", {"default": 256, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "start_image": ("IMAGE",),
                "previous_frames": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING", "LATENT", "INT")
    RETURN_NAMES = ("model", "positive", "negative", "latent", "trim_image")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, model, model_patch, positive, negative, vae, width, height, length,
                audio_encoder_output_1, motion_frame_count, audio_scale, vae_tile_size,
                clip_vision_output=None, start_image=None, previous_frames=None, segment_audio=False,
                global_frame_offset=None,
                scale_method="lanczos", crop_mode="center"):
        return _process_infinite_talk_audio(
            model, model_patch, positive, negative, vae, width, height, length,
            audio_encoder_output_1, motion_frame_count, audio_scale, vae_tile_size,
            clip_vision_output=clip_vision_output, start_image=start_image,
            previous_frames=previous_frames, segment_audio=segment_audio,
            global_frame_offset=global_frame_offset)


# ============================================================
# XB_WanInfiniteTalkToVideo_Dual — Wan 双人语音转视频
# ============================================================
class XB_WanInfiniteTalkToVideo_Dual:
    """双人语音转视频分块 --对应 WanInfiniteTalkToVideo (two_speakers) + VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "model_patch": ("MODEL_PATCH",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "audio_encoder_output_1": ("AUDIO_ENCODER_OUTPUT",),
                "audio_encoder_output_2": ("AUDIO_ENCODER_OUTPUT",),
                "mask_1": ("MASK",),
                "mask_2": ("MASK",),
                "motion_frame_count": ("INT", {"default": 9, "min": 1, "max": 33, "step": 1}),
                "audio_scale": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
                "vae_tile_size": ("INT", {"default": 256, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "start_image": ("IMAGE",),
                "previous_frames": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING", "LATENT", "INT")
    RETURN_NAMES = ("model", "positive", "negative", "latent", "trim_image")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, model, model_patch, positive, negative, vae, width, height, length,
                audio_encoder_output_1, audio_encoder_output_2, mask_1, mask_2,
                motion_frame_count, audio_scale, vae_tile_size,
                clip_vision_output=None, start_image=None, previous_frames=None,
                global_frame_offset=None,
                scale_method="lanczos", crop_mode="center"):
        return _process_infinite_talk_audio(
            model, model_patch, positive, negative, vae, width, height, length,
            audio_encoder_output_1, motion_frame_count, audio_scale, vae_tile_size,
            clip_vision_output=clip_vision_output, start_image=start_image,
            audio_encoder_output_2=audio_encoder_output_2,
            previous_frames=previous_frames,
            mask_1=mask_1, mask_2=mask_2,
            global_frame_offset=global_frame_offset,
            scale_method=scale_method, crop_mode=crop_mode)

# ==============================================================================
# 保留旧的 XB_WanInfiniteTalkToVideo 兼容别名（单人/双人 mode 选择器）
# ==============================================================================
# ============================================================
# XB_WanInfiniteTalkToVideo — Wan 语音转视频分块
# ============================================================
class XB_WanInfiniteTalkToVideo:
    """兼容旧工作流 --通过 mode 切换单人/双人"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "model_patch": ("MODEL_PATCH",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "mode": (["single_speaker", "two_speakers"], {"default": "single_speaker"}),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "audio_encoder_output_1": ("AUDIO_ENCODER_OUTPUT",),
                "motion_frame_count": ("INT", {"default": 9, "min": 1, "max": 33, "step": 1}),
                "audio_scale": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
                "vae_tile_size": ("INT", {"default": 256, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "audio_encoder_output_2": ("AUDIO_ENCODER_OUTPUT",),
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "start_image": ("IMAGE",),
                "previous_frames": ("IMAGE",),
                "mask_1": ("MASK",),
                "mask_2": ("MASK",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING", "LATENT", "INT")
    RETURN_NAMES = ("model", "positive", "negative", "latent", "trim_image")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, model, model_patch, positive, negative, vae, mode, width, height, length,
                audio_encoder_output_1, motion_frame_count, audio_scale, vae_tile_size,
                clip_vision_output=None, start_image=None,
                audio_encoder_output_2=None, previous_frames=None,
                mask_1=None, mask_2=None,
                global_frame_offset=None,
                scale_method="lanczos", crop_mode="center"):
        return _process_infinite_talk_audio(
            model, model_patch, positive, negative, vae, width, height, length,
            audio_encoder_output_1, motion_frame_count, audio_scale, vae_tile_size,
            clip_vision_output=clip_vision_output, start_image=start_image,
            audio_encoder_output_2=audio_encoder_output_2,
            previous_frames=previous_frames,
            mask_1=mask_1, mask_2=mask_2,
            global_frame_offset=global_frame_offset,
            scale_method=scale_method, crop_mode=crop_mode)

# ==============================================================================

# ==============================================================================

# ==============================================================================
    """Wan FunInpaint to Video with VAE tiling"""
# ==============================================================================
# ============================================================
# XB_WanFunInpaintToVideo — Wan FunInpaint 转视频
# ============================================================
class XB_WanFunInpaintToVideo:
    """Wan FunInpaint to Video with VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "start_image": ("IMAGE",),
                "end_image": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size,
                start_image=None, end_image=None, clip_vision_output=None,
                scale_method="lanczos", crop_mode="center"):
        flfv = XB_WanFirstLastFrameToVideo()
        return flfv.process(positive, negative, vae, width, height, length, batch_size, vae_tile_size,
                           start_image=start_image, end_image=end_image,
                           clip_vision_start_image=clip_vision_output,
                           scale_method=scale_method, crop_mode=crop_mode)

# ==============================================================================
    """Wan Camera Control to Video with VAE tiling"""
# ==============================================================================
# ============================================================
# XB_WanCameraImageToVideo — Wan 相机运镜图生视频
# ============================================================
class XB_WanCameraImageToVideo:
    """Wan Camera Control to Video with VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "start_image": ("IMAGE",),
                "camera_conditions": ("WAN_CAMERA_EMBEDDING",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size,
                start_image=None, clip_vision_output=None, camera_conditions=None,
                scale_method="lanczos", crop_mode="center"):
        latent = torch.zeros([batch_size, 16, ((length - 1) // 4) + 1, height // 8, width // 8], device=comfy.model_management.intermediate_device())
        concat_latent = torch.zeros([batch_size, 16, ((length - 1) // 4) + 1, height // 8, width // 8], device=comfy.model_management.intermediate_device())
        concat_latent = comfy.latent_formats.Wan21().process_out(concat_latent)

        if start_image is not None:
            start_image = _upscale(start_image[:length], width, height, scale_method, crop_mode)
            concat_latent_image = _encode_vae(vae, start_image[:, :, :, :3], vae_tile_size)
            concat_latent[:,:,:concat_latent_image.shape[2]] = concat_latent_image[:,:,:concat_latent.shape[2]]
            mask = torch.ones((1, 1, latent.shape[2] * 4, latent.shape[-2], latent.shape[-1]), device=latent.device)
            mask[:, :, :start_image.shape[0] + 3] = 0.0
            mask = mask.view(1, mask.shape[2] // 4, 4, mask.shape[3], mask.shape[4]).transpose(1, 2)
            positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent, "concat_mask": mask})
            negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent, "concat_mask": mask})

        if camera_conditions is not None:
            positive = node_helpers.conditioning_set_values(positive, {'camera_conditions': camera_conditions})
            negative = node_helpers.conditioning_set_values(negative, {'camera_conditions': camera_conditions})

        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})
            negative = node_helpers.conditioning_set_values(negative, {"clip_vision_output": clip_vision_output})

        out_latent = {"samples": latent}
        return (positive, negative, out_latent)

# ==============================================================================
    """Wan Phantom Subject to Video with VAE tiling"""
# ==============================================================================
# ============================================================
# XB_WanPhantomSubjectToVideo — Wan Phantom 主体转视频
# ============================================================
class XB_WanPhantomSubjectToVideo:
    """Wan Phantom Subject to Video with VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "images": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative_text", "negative_img_text", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size,
                images=None, scale_method="lanczos", crop_mode="center"):
        latent = torch.zeros([batch_size, 16, ((length - 1) // 4) + 1, height // 8, width // 8], device=comfy.model_management.intermediate_device())
        cond2 = negative
        if images is not None:
            images = _upscale(images[:length], width, height, scale_method, crop_mode)
            latent_images = []
            for i in images:
                latent_images += [_encode_vae(vae, i.unsqueeze(0)[:, :, :, :3], vae_tile_size)]
            concat_latent_image = torch.cat(latent_images, dim=2)
            positive = node_helpers.conditioning_set_values(positive, {"time_dim_concat": concat_latent_image})
            cond2 = node_helpers.conditioning_set_values(negative, {"time_dim_concat": concat_latent_image})
            negative = node_helpers.conditioning_set_values(negative, {"time_dim_concat": comfy.latent_formats.Wan21().process_out(torch.zeros_like(concat_latent_image))})

        out_latent = {"samples": latent}
        return (positive, cond2, negative, out_latent)

# ==============================================================================
    """Wan HuMo to Video with VAE tiling"""
# ==============================================================================
def _get_audio_emb_window(audio_emb, frame_num, frame0_idx, audio_shift=2):
    zero_audio_embed = torch.zeros((audio_emb.shape[1], audio_emb.shape[2]), dtype=audio_emb.dtype, device=audio_emb.device)
    zero_audio_embed_3 = torch.zeros((3, audio_emb.shape[1], audio_emb.shape[2]), dtype=audio_emb.dtype, device=audio_emb.device)
    iter_ = 1 + (frame_num - 1) // 4
    audio_emb_wind = []
    for lt_i in range(iter_):
        if lt_i == 0:
            st = frame0_idx + lt_i - 2
            ed = frame0_idx + lt_i + 3
            wind_feat = torch.stack([audio_emb[i] if (0 <= i < audio_emb.shape[0]) else zero_audio_embed for i in range(st, ed)], dim=0)
            wind_feat = torch.cat((zero_audio_embed_3, wind_feat), dim=0)
        else:
            st = frame0_idx + 1 + 4 * (lt_i - 1) - audio_shift
            ed = frame0_idx + 1 + 4 * lt_i + audio_shift
            wind_feat = torch.stack([audio_emb[i] if (0 <= i < audio_emb.shape[0]) else zero_audio_embed for i in range(st, ed)], dim=0)
        audio_emb_wind.append(wind_feat)
    audio_emb_wind = torch.stack(audio_emb_wind, dim=0)
    return audio_emb_wind, ed - audio_shift

# ============================================================
# XB_WanHuMoImageToVideo — Wan HuMo 图生视频
# ============================================================
class XB_WanHuMoImageToVideo:
    """Wan HuMo to Video with VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 832, "min": 16, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 480, "min": 16, "max": 8192, "step": 16}),
                "length": ("INT", {"default": 97, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "audio_encoder_output": ("AUDIO_ENCODER_OUTPUT",),
                "ref_image": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size,
                ref_image=None, audio_encoder_output=None, scale_method="lanczos", crop_mode="center"):
        latent_t = ((length - 1) // 4) + 1
        latent = torch.zeros([batch_size, 16, latent_t, height // 8, width // 8], device=comfy.model_management.intermediate_device())

        if ref_image is not None:
            ref_image = _upscale(ref_image[:1], width, height, scale_method, crop_mode)
            ref_latent = _encode_vae(vae, ref_image[:, :, :, :3], vae_tile_size)
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": [ref_latent]}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": [torch.zeros_like(ref_latent)]}, append=True)
        else:
            zero_latent = torch.zeros([batch_size, 16, 1, height // 8, width // 8], device=comfy.model_management.intermediate_device())
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": [zero_latent]}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": [zero_latent]}, append=True)

        if audio_encoder_output is not None:
            audio_emb = torch.stack(audio_encoder_output["encoded_audio_all_layers"], dim=2)
            audio_len = audio_encoder_output["audio_samples"] // 640
            audio_emb = audio_emb[:, :audio_len * 2]
            feat0 = linear_interpolation(audio_emb[:, :, 0: 8].mean(dim=2), 50, 25)
            feat1 = linear_interpolation(audio_emb[:, :, 8: 16].mean(dim=2), 50, 25)
            feat2 = linear_interpolation(audio_emb[:, :, 16: 24].mean(dim=2), 50, 25)
            feat3 = linear_interpolation(audio_emb[:, :, 24: 32].mean(dim=2), 50, 25)
            feat4 = linear_interpolation(audio_emb[:, :, 32], 50, 25)
            audio_emb = torch.stack([feat0, feat1, feat2, feat3, feat4], dim=2)[0]
            audio_emb, _ = _get_audio_emb_window(audio_emb, length, frame0_idx=0)
            audio_emb = audio_emb.unsqueeze(0)
            audio_emb_neg = torch.zeros_like(audio_emb)
            positive = node_helpers.conditioning_set_values(positive, {"audio_embed": audio_emb})
            negative = node_helpers.conditioning_set_values(negative, {"audio_embed": audio_emb_neg})
        else:
            zero_audio = torch.zeros([batch_size, latent_t + 1, 8, 5, 1280], device=comfy.model_management.intermediate_device())
            positive = node_helpers.conditioning_set_values(positive, {"audio_embed": zero_audio})
            negative = node_helpers.conditioning_set_values(negative, {"audio_embed": zero_audio})

        out_latent = {"samples": latent}
        return (positive, negative, out_latent)

# ==============================================================================
# 7.5.5 🎬 Wan22 ImageToVideo Latent 分块
# ==============================================================================
# ============================================================
# XB_Wan22ImageToVideoLatent — Wan 2.2 图生视频 Latent
# ============================================================
class XB_Wan22ImageToVideoLatent:
    """Wan 2.2 Image to Video Latent with VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vae": ("VAE",),
                "width": ("INT", {"default": 1280, "min": 16, "max": 8192, "step": 32}),
                "height": ("INT", {"default": 704, "min": 32, "max": 8192, "step": 32}),
                "length": ("INT", {"default": 49, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "start_image": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, vae, width, height, length, batch_size, vae_tile_size,
                start_image=None, scale_method="lanczos", crop_mode="center"):
        latent = torch.zeros([1, 48, ((length - 1) // 4) + 1, height // 16, width // 16], device=comfy.model_management.intermediate_device())
        mask = torch.ones([latent.shape[0], 1, ((length - 1) // 4) + 1, latent.shape[-2], latent.shape[-1]], device=comfy.model_management.intermediate_device())

        if start_image is not None:
            start_image = _upscale(start_image[:length], width, height, scale_method, crop_mode)
            latent_temp = _encode_vae(vae, start_image, vae_tile_size)
            latent[:, :, :latent_temp.shape[-3]] = latent_temp
            mask[:, :, :latent_temp.shape[-3]] *= 0.0

        out_latent = {}
        latent_format = comfy.latent_formats.Wan22()
        latent = latent_format.process_out(latent) * mask + latent * (1.0 - mask)
        out_latent["samples"] = latent.repeat((batch_size,) + (1,) * (latent.ndim - 1))
        out_latent["noise_mask"] = mask.repeat((batch_size,) + (1,) * (mask.ndim - 1))
        return (out_latent,)

# ==============================================================================
# 7.5.6 🎬 Wan SoundImage Extend 分块
# ==============================================================================
# ============================================================
# XB_WanSoundImageToVideoExtend — Wan 音频+图像扩展视频
# ============================================================
class XB_WanSoundImageToVideoExtend:
    """Wan Sound Extend to Video with VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "length": ("INT", {"default": 77, "min": 1, "max": 8192, "step": 4}),
                "video_latent": ("LATENT",),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "audio_encoder_output": ("AUDIO_ENCODER_OUTPUT",),
                "ref_image": ("IMAGE",),
                "control_video": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, length, video_latent, vae_tile_size,
                ref_image=None, audio_encoder_output=None, control_video=None,
                scale_method="lanczos", crop_mode="center"):
        video_latent_data = video_latent["samples"]
        width = video_latent_data.shape[-1] * 8
        height = video_latent_data.shape[-2] * 8
        batch_size = video_latent_data.shape[0]
        frame_offset = video_latent_data.shape[-3] * 4
        positive, negative, out_latent, frame_offset = xb_wan_sound_to_video(
            positive, negative, vae, width, height, length, batch_size, vae_tile_size,
            frame_offset=frame_offset, ref_image=ref_image,
            audio_encoder_output=audio_encoder_output,
            control_video=control_video, ref_motion=None, ref_motion_latent=video_latent_data,
            scale_method=scale_method, crop_mode=crop_mode)
        return (positive, negative, out_latent)

# ==============================================================================
    """Wan SCAIL Pose to Video with VAE tiling"""
# ==============================================================================
# ============================================================
# XB_WanSCAILToVideo — Wan SCAIL 转视频
# ============================================================
class XB_WanSCAILToVideo:
    """Wan SCAIL Pose to Video with VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 512, "min": 16, "max": 8192, "step": 32}),
                "height": ("INT", {"default": 896, "min": 32, "max": 8192, "step": 32}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "pose_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "pose_start": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "pose_end": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "reference_image": ("IMAGE",),
                "pose_video": ("IMAGE",),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, pose_strength, pose_start, pose_end, vae_tile_size,
                reference_image=None, clip_vision_output=None, pose_video=None,
                scale_method="lanczos", crop_mode="center"):
        latent = torch.zeros([batch_size, 16, ((length - 1) // 4) + 1, height // 8, width // 8], device=comfy.model_management.intermediate_device())

        if reference_image is not None:
            reference_image = _upscale(reference_image[:1], width, height, scale_method, crop_mode)
            ref_latent = _encode_vae(vae, reference_image[:, :, :, :3], vae_tile_size)
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": [ref_latent]}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": [torch.zeros_like(ref_latent)]}, append=True)

        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})
            negative = node_helpers.conditioning_set_values(negative, {"clip_vision_output": clip_vision_output})

        if pose_video is not None:
            pose_video = _upscale(pose_video[:length], width // 2, height // 2, "area", "center")
            pose_video_latent = _encode_vae(vae, pose_video[:, :, :, :3], vae_tile_size) * pose_strength
            positive = node_helpers.conditioning_set_values_with_timestep_range(positive, {"pose_video_latent": pose_video_latent}, pose_start, pose_end)
            negative = node_helpers.conditioning_set_values_with_timestep_range(negative, {"pose_video_latent": pose_video_latent}, pose_start, pose_end)

        out_latent = {"samples": latent}
        return (positive, negative, out_latent)

# ==============================================================================
# 7.5.7 Pro 🎬 Wan SCAIL (pose) 转视频分块 — 高配版
# ==============================================================================
# SCAIL-2 mask helper — colored RGB mask → 28-channel binary latent
# ==============================================================================
def _scail_extract_mask_to_28ch(rgb_video):
    """Colored RGB mask (T, H, W, 3) in [0,1] -> SCAIL-2 28-channel binary latent
    (1, T_lat, 28, H_lat, W_lat). 7 per-color binary channels (white/r/g/b/y/m/c)
    threshold-extracted at 225/255, 8x spatial downsample, 4-frame temporal stacking."""
    T, H, W, _ = rgb_video.shape
    _ON_THRESH = 225.0 / 255.0
    mask = rgb_video.movedim(-1, 1).float()
    R = (mask[:, 0:1] > _ON_THRESH).float()
    G = (mask[:, 1:2] > _ON_THRESH).float()
    B = (mask[:, 2:3] > _ON_THRESH).float()
    nR, nG, nB = 1 - R, 1 - G, 1 - B
    binary_7ch = torch.cat([
        R * G * B,    # white
        R * nG * nB,  # red
        nR * G * nB,  # green
        nR * nG * B,  # blue
        R * G * nB,   # yellow
        R * nG * B,   # magenta
        nR * G * B,   # cyan
    ], dim=1)
    H_lat, W_lat = H, W
    for _ in range(3):
        H_lat = (H_lat + 1) // 2
        W_lat = (W_lat + 1) // 2
    binary_7ch = torch.nn.functional.interpolate(binary_7ch, size=(H_lat, W_lat), mode='area')
    T_latent = (T - 1) // 4 + 1
    padded = torch.cat([binary_7ch[:1].repeat(4, 1, 1, 1), binary_7ch[1:]], dim=0)
    out = padded.view(T_latent, 28, H_lat, W_lat)
    return out.unsqueeze(0)

# ==============================================================================
# 7.5.7 Pro 🎬 Wan SCAIL-2 (pose) 转视频分块 — 完整版
# ==============================================================================
# ============================================================
# XB_WanSCAILToVideoPro — Wan SCAIL Pro 转视频
# ============================================================
class XB_WanSCAILToVideoPro:
    """Wan SCAIL-2 Pose to Video Pro — exact port from ComfyUI core nodes_scail.py with VAE tiling"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "width": ("INT", {"default": 512, "min": 16, "max": 8192, "step": 32}),
                "height": ("INT", {"default": 896, "min": 32, "max": 8192, "step": 32}),
                "length": ("INT", {"default": 81, "min": 1, "max": 8192, "step": 4}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                "pose_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "pose_start": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "pose_end": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "replacement_mode": ("BOOLEAN", {"default": False}),
                "video_frame_offset": ("INT", {"default": 0, "min": 0, "max": 8192, "step": 1}),
                "previous_frame_count": ("INT", {"default": 5, "min": 1, "max": 8192, "step": 4}),
                "vae_tile_size": ("INT", {"default": 64, "min": 64, "max": 3840, "step": 32}),
            },
            "optional": {
                "pose_video": ("IMAGE",),
                "pose_video_mask": ("IMAGE",),
                "reference_image": ("IMAGE",),
                "reference_image_mask": ("IMAGE",),
                "clip_vision_output": ("CLIP_VISION_OUTPUT",),
                "previous_frames": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT", "INT")
    RETURN_NAMES = ("positive", "negative", "latent", "video_frame_offset")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, pose_strength, pose_start, pose_end,
                replacement_mode, video_frame_offset, previous_frame_count, vae_tile_size,
                pose_video=None, pose_video_mask=None, reference_image=None,
                reference_image_mask=None, clip_vision_output=None, previous_frames=None):
        latent = torch.zeros([batch_size, 16, ((length - 1) // 4) + 1, height // 8, width // 8], device=comfy.model_management.intermediate_device())
        noise_mask = None

        # ref_mask_flag: False=Animation Mode, True=Replacement Mode
        ref_mask_flag = not replacement_mode
        positive = node_helpers.conditioning_set_values(positive, {"ref_mask_flag": ref_mask_flag})
        negative = node_helpers.conditioning_set_values(negative, {"ref_mask_flag": ref_mask_flag})

        # --- previous_frames ---
        prev_trimmed = None
        if previous_frames is not None and previous_frames.shape[0] > 0:
            prev_trimmed = previous_frames[-previous_frame_count:]
            video_frame_offset -= prev_trimmed.shape[0]
            video_frame_offset = max(0, video_frame_offset)

        # --- reference_image + mask ---
        if reference_image is not None:
            reference_image = comfy.utils.common_upscale(reference_image[:1].movedim(-1, 1), width, height, "bicubic", "center").movedim(1, -1)
            # Replacement Mode: composite ref on black bg using reference_image_mask as alpha matte
            if replacement_mode and reference_image_mask is not None:
                rm = comfy.utils.common_upscale(reference_image_mask[:1].movedim(-1, 1), width, height, "nearest-exact", "center").movedim(1, -1)
                is_char = (rm[..., :3].max(dim=-1, keepdim=True).values > 0.1).to(reference_image.dtype)
                reference_image = reference_image * is_char
            ref_latent = _encode_vae(vae, reference_image[:, :, :, :3], vae_tile_size)
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": [ref_latent]}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": [ref_latent]}, append=True)

        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})
            negative = node_helpers.conditioning_set_values(negative, {"clip_vision_output": clip_vision_output})

        # --- pose_video (with offset truncation) ---
        if pose_video is not None:
            if pose_video.shape[0] <= video_frame_offset:
                pose_video = None
            else:
                pose_video = pose_video[video_frame_offset:]
        if pose_video_mask is not None:
            if pose_video_mask.shape[0] <= video_frame_offset:
                pose_video_mask = None
            else:
                pose_video_mask = pose_video_mask[video_frame_offset:]

        # Truncate pose+mask jointly to the shorter of the two, capped at length
        ts = [v.shape[0] for v in (pose_video, pose_video_mask) if v is not None]
        if ts:
            T_kept = ((min(min(ts), length) - 1) // 4) * 4 + 1
            if pose_video is not None:
                pose_video = pose_video[:T_kept]
            if pose_video_mask is not None:
                pose_video_mask = pose_video_mask[:T_kept]

        if pose_video is not None:
            pose_video = comfy.utils.common_upscale(pose_video[:length].movedim(-1, 1), width // 2, height // 2, "area", "center").movedim(1, -1)
            pose_video_latent = _encode_vae(vae, pose_video[:, :, :, :3], vae_tile_size) * pose_strength
            positive = node_helpers.conditioning_set_values_with_timestep_range(positive, {"pose_video_latent": pose_video_latent}, pose_start, pose_end)
            negative = node_helpers.conditioning_set_values_with_timestep_range(negative, {"pose_video_latent": pose_video_latent}, pose_start, pose_end)

        if pose_video_mask is not None:
            mask_video_hw = comfy.utils.common_upscale(pose_video_mask[:length].movedim(-1, 1), width // 2, height // 2, "area", "center").movedim(1, -1)
            driving_mask_28ch = _scail_extract_mask_to_28ch(mask_video_hw)
            positive = node_helpers.conditioning_set_values(positive, {"driving_mask_28ch": driving_mask_28ch})
            negative = node_helpers.conditioning_set_values(negative, {"driving_mask_28ch": driving_mask_28ch})

        if reference_image_mask is not None and replacement_mode:
            ref_mask_hw = comfy.utils.common_upscale(reference_image_mask[:1].movedim(-1, 1), width, height, "bicubic", "center").movedim(1, -1)
            ref_mask_1f = _scail_extract_mask_to_28ch(ref_mask_hw)
            zeros = torch.zeros((1, latent.shape[2], 28, ref_mask_1f.shape[-2], ref_mask_1f.shape[-1]), device=ref_mask_1f.device, dtype=ref_mask_1f.dtype)
            ref_mask_28ch = torch.cat([ref_mask_1f, zeros], dim=1)
            positive = node_helpers.conditioning_set_values(positive, {"ref_mask_28ch": ref_mask_28ch})
            negative = node_helpers.conditioning_set_values(negative, {"ref_mask_28ch": ref_mask_28ch})

        if prev_trimmed is not None:
            pf = comfy.utils.common_upscale(prev_trimmed.movedim(-1, 1), width, height, "bicubic", "center").movedim(1, -1)
            prev_latent = _encode_vae(vae, pf[:, :, :, :3], vae_tile_size)
            prev_latent_frames = min(prev_latent.shape[2], latent.shape[2])
            latent[:, :, :prev_latent_frames] = prev_latent[:, :, :prev_latent_frames].to(latent.dtype)
            noise_mask = torch.ones((1, 1, latent.shape[2], latent.shape[-2], latent.shape[-1]), device=latent.device, dtype=latent.dtype)
            noise_mask[:, :, :prev_latent_frames] = 0.0

        out_latent = {"samples": latent}
        if noise_mask is not None:
            out_latent["noise_mask"] = noise_mask
        return (positive, negative, out_latent, video_frame_offset + length)

# ==============================================================================
# 8. 🧊 Wan VAE 时空分块解码（独立节点）
# ==============================================================================
# 8. 🧊 Wan VAE 时空分块解码（独立节点）
# ==============================================================================
# ============================================================
# XB_WanVAEDecodeTiled — Wan VAE 分块解码
# ============================================================
class XB_WanVAEDecodeTiled:
    """Wan 视频 VAE 分块解码——空间+时间分块，降低显存峰值"""
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "vae": ("VAE",),
                "tile_size": ("INT", {"default": 256, "min": 64, "max": 2048, "step": 64, "tooltip": "空间分块大小"}),
                "spatial_overlap": ("INT", {"default": 32, "min": 0, "max": 512, "step": 32, "tooltip": "空间块重叠像素"}),
                "temporal_chunk": ("INT", {"default": 64, "min": 0, "max": 1024, "step": 4, "tooltip": "时间分块帧数(0=不分块)"}),
                "temporal_overlap": ("INT", {"default": 8, "min": 0, "max": 256, "step": 4, "tooltip": "时间块重叠帧数"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/Wan"

    def decode(self, samples, vae, tile_size, spatial_overlap, temporal_chunk, temporal_overlap):
        # ── 轨道 A：非 AMD 环境 (NVIDIA CUDA / CPU) → 直接使用官方解码器 ──
        if not (torch.cuda.is_available() and hasattr(torch.version, 'hip') and torch.version.hip):
            if temporal_chunk <= 0:
                return nodes.VAEDecode().decode(samples=samples, vae=vae)
            return nodes.VAEDecodeTiled().decode(
                samples=samples, vae=vae,
                tile_size=tile_size, overlap=spatial_overlap,
                temporal_size=temporal_chunk, temporal_overlap=temporal_overlap)

        # ── 轨道 B：AMD ROCm 环境 → 优化 + 熔断降级 ──
        try:
            # 🛡️ 显存连续性强制对齐 (专治 MIOpen HIP error: invalid argument)
            lat = samples["samples"] if isinstance(samples, dict) else samples
            is_nested_tensor = hasattr(lat, 'is_nested') and lat.is_nested
            if not is_nested_tensor and not lat.is_contiguous():
                if isinstance(samples, dict):
                    samples["samples"] = lat.contiguous()
                else:
                    samples = lat.contiguous()

            if temporal_chunk <= 0:
                return nodes.VAEDecode().decode(samples=samples, vae=vae)
            return nodes.VAEDecodeTiled().decode(
                samples=samples, vae=vae,
                tile_size=tile_size, overlap=spatial_overlap,
                temporal_size=temporal_chunk, temporal_overlap=temporal_overlap)
        except Exception as e:
            print(f"\n[XB_ToolBox 警告] 优化版节点异常，自动切换到官方原版节点！")
            print(f"[XB_ToolBox 错误信息] {e}")
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            if temporal_chunk <= 0:
                return nodes.VAEDecode().decode(samples=samples, vae=vae)
            return nodes.VAEDecodeTiled().decode(
                samples=samples, vae=vae,
                tile_size=tile_size, overlap=spatial_overlap,
                temporal_size=temporal_chunk, temporal_overlap=temporal_overlap)
