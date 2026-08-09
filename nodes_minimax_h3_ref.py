"""
XB-ToolBox MiniMax H3 参考编码（独立版）
=========================================
完全独立复刻，不依赖官方内部代码。
参考图 ref_img_0~8、视频/音频均为固定端口。
"""

import math
import torch
import torchaudio
import nodes
import comfy.model_management
import comfy.nested_tensor
import comfy.utils
import node_helpers

CANVAS_MULTIPLE = 32
BASE_SHORT_EDGE = 768
MAX_PIXELS = 768 * 1344
FPS = 24
AUDIO_LATENT_FPS = 40


def _align_frame_count(n):
    while n % 17 != 5: n += 1
    return n

def _video_latent_t(fc):
    return 2 if fc <= 5 else ((fc - 5) // 17) * 5 + 2

def _temporal_shape(length):
    fc = _align_frame_count(max(5, length))
    return fc, _video_latent_t(fc), round((fc / FPS) * AUDIO_LATENT_FPS)

def _adapt_canvas(width, height):
    ratio = width / height
    nom_w = BASE_SHORT_EDGE * ratio if ratio >= 1.0 else BASE_SHORT_EDGE
    nom_h = BASE_SHORT_EDGE if ratio >= 1.0 else BASE_SHORT_EDGE / ratio
    if nom_w * nom_h > MAX_PIXELS:
        s = math.sqrt(MAX_PIXELS / (nom_w * nom_h))
        nom_w, nom_h = nom_w * s, nom_h * s
    return (max(CANVAS_MULTIPLE, round(nom_w / CANVAS_MULTIPLE) * CANVAS_MULTIPLE),
            max(CANVAS_MULTIPLE, round(nom_h / CANVAS_MULTIPLE) * CANVAS_MULTIPLE))

def _resize(image, width, height, crop):
    samples = image[..., :3].movedim(-1, 1)
    samples = comfy.utils.common_upscale(samples, width, height, "lanczos", crop)
    return samples.movedim(1, -1)

def _empty_av_latent(width, height, length, batch_size=1):
    fc, latent_t, audio_t = _temporal_shape(length)
    video = torch.zeros([batch_size, 24, latent_t, height // 16, width // 16],
                        device=comfy.model_management.intermediate_device())
    audio = torch.zeros([batch_size, 32, 2, audio_t],
                        device=comfy.model_management.intermediate_device())
    return {"samples": comfy.nested_tensor.NestedTensor((video, audio))}, fc

def _encode_ref_audio(audio_vae, audio):
    waveform = audio["waveform"]
    sr = audio["sample_rate"]
    vae_sr = getattr(audio_vae, "audio_sample_rate", 32000)
    if sr != vae_sr:
        waveform = torchaudio.functional.resample(waveform, sr, vae_sr)
    z = audio_vae.encode(waveform[:1].movedim(1, -1))
    return z, z.shape[-1]


class XB_MiniMaxH3RefEncoder:
    """MiniMax H3 参考编码 — 所有端口固定，批量编码可调。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "audio_vae": ("VAE",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True}),
                "width": ("INT", {"default": 1344, "min": 32, "max": nodes.MAX_RESOLUTION, "step": 32}),
                "height": ("INT", {"default": 768, "min": 32, "max": nodes.MAX_RESOLUTION, "step": 32}),
                "length": ("INT", {"default": 124, "min": 5, "max": 3600, "step": 17}),
                "ref_image_size": (["match", "720", "1024", "2048"], {"default": "match"}),
                "batch_encode": ("INT", {"default": 1, "min": 1, "max": 9, "step": 1}),
            },
            "optional": {
                "ref_img_0": ("IMAGE",),
                "ref_img_1": ("IMAGE",),
                "ref_img_2": ("IMAGE",),
                "ref_img_3": ("IMAGE",),
                "ref_img_4": ("IMAGE",),
                "ref_img_5": ("IMAGE",),
                "ref_img_6": ("IMAGE",),
                "ref_img_7": ("IMAGE",),
                "ref_img_8": ("IMAGE",),
                "ref_vid_0": ("IMAGE",),
                "ref_vid_1": ("IMAGE",),
                "ref_vid_2": ("IMAGE",),
                "ref_vid_aud_0": ("AUDIO",),
                "ref_vid_aud_1": ("AUDIO",),
                "ref_vid_aud_2": ("AUDIO",),
                "ref_aud_0": ("AUDIO",),
                "ref_aud_1": ("AUDIO",),
                "ref_aud_2": ("AUDIO",),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "LATENT")
    RETURN_NAMES = ("条件", "潜变量")
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/MiniMax"

    def encode(self, clip, vae, audio_vae, prompt, width, height, length,
               ref_image_size="match", batch_encode=1,
               ref_img_0=None, ref_img_1=None, ref_img_2=None,
               ref_img_3=None, ref_img_4=None, ref_img_5=None,
               ref_img_6=None, ref_img_7=None, ref_img_8=None,
               ref_vid_0=None, ref_vid_1=None, ref_vid_2=None,
               ref_vid_aud_0=None, ref_vid_aud_1=None, ref_vid_aud_2=None,
               ref_aud_0=None, ref_aud_1=None, ref_aud_2=None,
               **kwargs):
        latent, frame_count = _empty_av_latent(width, height, length)

        # 收集参考图
        ref_images = {}
        for i, img in enumerate([ref_img_0, ref_img_1, ref_img_2, ref_img_3,
                                  ref_img_4, ref_img_5, ref_img_6, ref_img_7, ref_img_8]):
            if img is not None:
                ref_images[f"ref_img_{i}"] = img

        # 收集参考视频
        ref_videos = {}
        for i, v in enumerate([ref_vid_0, ref_vid_1, ref_vid_2]):
            if v is not None:
                ref_videos[f"ref_vid_{i}"] = v

        ref_video_audios = {}
        for i, a in enumerate([ref_vid_aud_0, ref_vid_aud_1, ref_vid_aud_2]):
            if a is not None:
                ref_video_audios[f"ref_vid_aud_{i}"] = a

        ref_audios = {}
        for i, a in enumerate([ref_aud_0, ref_aud_1, ref_aud_2]):
            if a is not None:
                ref_audios[f"ref_aud_{i}"] = a

        ref_items = []
        ref_blocks = []

        # ── 参考图：按尺寸分组批量编码 ──
        if ref_images:
            resize_groups = {}
            resize_order = []
            for name, img in ref_images.items():
                h, w = img.shape[1], img.shape[2]
                if ref_image_size == "match":
                    scale = min(1.0, math.sqrt((width * height) / (w * h)))
                else:
                    target_short = int(ref_image_size)
                    scale = min(1.0, target_short / min(w, h))
                tw = max(CANVAS_MULTIPLE, round(w * scale / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
                th = max(CANVAS_MULTIPLE, round(h * scale / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
                resized = _resize(img[:1], tw, th, "disabled")
                key = (tw, th)
                if key not in resize_groups:
                    resize_groups[key] = []
                resize_groups[key].append(resized)
                resize_order.append((key, len(resize_groups[key]) - 1))

            encoded = {}
            for key, batch_list in resize_groups.items():
                batch = torch.cat(batch_list, dim=0)
                for b_start in range(0, len(batch), batch_encode):
                    chunk = batch[b_start:b_start + batch_encode]
                    z_batch = vae.encode(chunk)
                    for local_i in range(len(chunk)):
                        encoded[(key, b_start + local_i)] = z_batch[local_i:local_i + 1]

            for key, local_i in resize_order:
                z = encoded[(key, local_i)]
                tw, th = key
                ref_items.append({"type": "image", "data": resize_groups[key][local_i]})
                ref_blocks.append({"kind": "image", "latent_h": th // 16, "latent_w": tw // 16, "latent": z})

        # ── 参考视频 ──
        for name, video_frames in ref_videos.items():
            vh, vw = video_frames.shape[1], video_frames.shape[2]
            cw, ch = _adapt_canvas(vw, vh)
            if vw * vh < cw * ch:
                cw = max(CANVAS_MULTIPLE, round(vw / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
                ch = max(CANVAS_MULTIPLE, round(vh / CANVAS_MULTIPLE) * CANVAS_MULTIPLE)
            frames = _resize(video_frames, cw, ch, "disabled")
            if frames.shape[0] > frame_count:
                frames = frames[:frame_count]
            n = frames.shape[0]
            if n < 5:
                raise ValueError("MiniMax H3 reference videos need at least 5 frames")
            while n % 17 != 5:
                n -= 1
            frames = frames[:n]
            z = vae.encode(frames)

            suffix = name.rsplit("_", 1)[-1]
            soundtrack = ref_video_audios.get(f"ref_vid_aud_{suffix}")
            audio_latent, ref_audio_t = (None, 0)
            if soundtrack is not None:
                audio_latent, ref_audio_t = _encode_ref_audio(audio_vae, soundtrack)
                ref_items.append({"type": "audio"})

            sample_idx = list(range(0, frames.shape[0], FPS // 2))
            qwen_frames = frames[sample_idx]
            ref_items.append({"type": "video", "data": qwen_frames,
                              "timestamps": [i / 2.0 for i in range(len(sample_idx))]})
            ref_blocks.append({"kind": "video_audio" if ref_audio_t else "video",
                               "latent_t": z.shape[2], "latent_h": ch // 16, "latent_w": cw // 16,
                               "ref_audio_t": ref_audio_t, "latent": z, "audio_latent": audio_latent})

        # ── 独立音频 ──
        for audio in ref_audios.values():
            audio_latent, ref_audio_t = _encode_ref_audio(audio_vae, audio)
            ref_items.append({"type": "audio"})
            ref_blocks.append({"kind": "audio", "ref_audio_t": ref_audio_t, "audio_latent": audio_latent})

        tokens = clip.tokenize(prompt, minimax_ref_items=ref_items)
        cond = clip.encode_from_tokens_scheduled(tokens)
        if ref_blocks:
            cond = node_helpers.conditioning_set_values(cond, {"minimax_refs": ref_blocks})

        return (cond, latent)
