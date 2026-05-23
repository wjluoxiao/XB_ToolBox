import torch
import comfy.model_management
import comfy.utils
import node_helpers
import comfy.clip_vision
import math
import numpy as np

def _encode_vae(vae, pixels, tile_size):
    # 确保输入至少4维 (B, H, W, C)，防止3D输入直接索引崩溃
    if pixels.dim() == 3:
        pixels = pixels.unsqueeze(0)
    if tile_size == 0 or tile_size is None:
        return vae.encode(pixels[:, :, :, :3])
    else:
        return vae.encode_tiled(pixels[:, :, :, :3], tile_x=tile_size, tile_y=tile_size, overlap=32, tile_t=256, overlap_t=8)

# ==============================================================================
# 1. 基础单图转视频分块
# ==============================================================================
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
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, clip_vision_output=None, start_image=None):
        spacial_scale = vae.spacial_compression_encode()
        latent_channels = vae.latent_channels
        latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())

        if start_image is not None:
            start_image = comfy.utils.common_upscale(start_image[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
            image = torch.ones((length, height, width, start_image.shape[-1]), device=start_image.device, dtype=start_image.dtype) * 0.5
            image[:start_image.shape[0]] = start_image

            concat_latent_image = _encode_vae(vae, image, vae_tile_size)

            mask = torch.ones((1, 1, latent.shape[2], concat_latent_image.shape[-2], concat_latent_image.shape[-1]), device=start_image.device, dtype=start_image.dtype)
            mask[:, :, :((start_image.shape[0] - 1) // 4) + 1] = 0.0

            positive = node_helpers.conditioning_set_values(positive, {"concat_latent_image": concat_latent_image, "concat_mask": mask})
            negative = node_helpers.conditioning_set_values(negative, {"concat_latent_image": concat_latent_image, "concat_mask": mask})

        if clip_vision_output is not None:
            positive = node_helpers.conditioning_set_values(positive, {"clip_vision_output": clip_vision_output})

        return (positive, negative, {"samples": latent})

# ==============================================================================
# 2. 首尾帧转视频分块
# ==============================================================================
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
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, clip_vision_start_image=None, clip_vision_end_image=None, start_image=None, end_image=None):
        spacial_scale = vae.spacial_compression_encode()
        latent = torch.zeros([batch_size, vae.latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        
        if start_image is not None:
            start_image = comfy.utils.common_upscale(start_image[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
        if end_image is not None:
            end_image = comfy.utils.common_upscale(end_image[-length:].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)

        image = torch.ones((length, height, width, 3)) * 0.5
        mask = torch.ones((1, 1, latent.shape[2] * 4, latent.shape[-2], latent.shape[-1]))

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

# ==============================================================================
# 3. 万能控制视频分块 (Wan 2.1)
# ==============================================================================
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
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, start_image=None, clip_vision_output=None, control_video=None):
        spacial_scale = vae.spacial_compression_encode()
        latent_channels = vae.latent_channels
        latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        concat_latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        concat_latent = comfy.latent_formats.Wan21().process_out(concat_latent)
        concat_latent = concat_latent.repeat(1, 2, 1, 1, 1)

        if start_image is not None:
            start_image = comfy.utils.common_upscale(start_image[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
            concat_latent_image = _encode_vae(vae, start_image, vae_tile_size)
            concat_latent[:,latent_channels:,:concat_latent_image.shape[2]] = concat_latent_image[:,:,:concat_latent.shape[2]]

        if control_video is not None:
            control_video = comfy.utils.common_upscale(control_video[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
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

# ==============================================================================
# 4. 万能控制视频分块 (Wan 2.2)
# ==============================================================================
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
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, ref_image=None, start_image=None, control_video=None):
        spacial_scale = vae.spacial_compression_encode()
        latent_channels = vae.latent_channels
        latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        concat_latent = torch.zeros([batch_size, latent_channels, ((length - 1) // 4) + 1, height // spacial_scale, width // spacial_scale], device=comfy.model_management.intermediate_device())
        if latent_channels == 48:
            concat_latent = comfy.latent_formats.Wan22().process_out(concat_latent)
        else:
            concat_latent = comfy.latent_formats.Wan21().process_out(concat_latent)
        concat_latent = concat_latent.repeat(1, 2, 1, 1, 1)
        mask = torch.ones((1, 1, latent.shape[2] * 4, latent.shape[-2], latent.shape[-1]))

        if start_image is not None:
            start_image = comfy.utils.common_upscale(start_image[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
            concat_latent_image = _encode_vae(vae, start_image, vae_tile_size)
            concat_latent[:,latent_channels:,:concat_latent_image.shape[2]] = concat_latent_image[:,:,:concat_latent.shape[2]]
            mask[:, :, :start_image.shape[0] + 3] = 0.0

        ref_latent = None
        if ref_image is not None:
            ref_image = comfy.utils.common_upscale(ref_image[:1].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
            ref_latent = _encode_vae(vae, ref_image, vae_tile_size)

        if control_video is not None:
            control_video = comfy.utils.common_upscale(control_video[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
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


# ==============================================================================
# 5. 音频图像转视频分块 (WanSound) - 附带辅助函数
# ==============================================================================
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

def xb_wan_sound_to_video(positive, negative, vae, width, height, length, batch_size, vae_tile_size, frame_offset=0, ref_image=None, audio_encoder_output=None, control_video=None, ref_motion=None):
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
        ref_image = comfy.utils.common_upscale(ref_image[:1].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
        ref_latent = _encode_vae(vae, ref_image, vae_tile_size)
        positive = node_helpers.conditioning_set_values(positive, {"reference_latents": [ref_latent]}, append=True)
        negative = node_helpers.conditioning_set_values(negative, {"reference_latents": [ref_latent]}, append=True)

    if ref_motion is not None:
        if ref_motion.shape[0] > 73:
            ref_motion = ref_motion[-73:]
        ref_motion = comfy.utils.common_upscale(ref_motion.movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
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
        control_video = comfy.utils.common_upscale(control_video[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
        control_video = _encode_vae(vae, control_video, vae_tile_size)
        control_video_out[:, :, :control_video.shape[2]] = control_video

    positive = node_helpers.conditioning_set_values(positive, {"control_video": control_video_out})
    negative = node_helpers.conditioning_set_values(negative, {"control_video": control_video_out})

    out_latent = {}
    out_latent["samples"] = latent
    return positive, negative, out_latent, frame_offset

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
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, positive, negative, vae, width, height, length, batch_size, vae_tile_size, ref_image=None, audio_encoder_output=None, control_video=None, ref_motion=None):
        positive, negative, out_latent, frame_offset = xb_wan_sound_to_video(
            positive, negative, vae, width, height, length, batch_size, vae_tile_size, 
            ref_image=ref_image, audio_encoder_output=audio_encoder_output,
            control_video=control_video, ref_motion=ref_motion)
        return (positive, negative, out_latent)