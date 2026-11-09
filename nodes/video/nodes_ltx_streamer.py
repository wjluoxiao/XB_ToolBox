"""
XB-ToolBox LTX-2.3 IS2V Infinite Relay Node
=============================================
单次采样 (8步) + 302工作流 AddGuide 拼接
"""

import os, gc, math
import torch, nodes, comfy.utils, folder_paths, comfy.model_management as mm
from .nodes_pipeline import _safe_video_accumulate, _apply_progressive_color_correction, _refresh_models, _match_color_to_ref


class XB_LTX23_InfiniteStreamer:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "video_vae": ("VAE",),
                "audio_vae": ("VAE",),
                "clip": ("CLIP",),
                "start_image": ("IMAGE",),
                "width": ("INT", {"forceInput": True, "tooltip": "宽度"}),
                "height": ("INT", {"forceInput": True, "tooltip": "高度"}),
                "total_frames": ("INT", {"forceInput": True, "tooltip": "总帧数"}),
                "fps": ("INT", {"forceInput": True, "tooltip": "帧率"}),
                "audio": ("AUDIO",),
                "segment_frames": ("INT", {"default": 97, "min": 5, "max": 4096, "step": 4, "tooltip": "每段生成帧数"}),
                "overlap_frames": ("INT", {"default": 8, "min": 1, "max": 33, "step": 1, "tooltip": "接力重叠帧数（建议8的倍数）"}),
                "positive_prompt": ("STRING", {"multiline": True, "default": ""}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "sampler_gen": (["euler","euler_ancestral","heun","dpm_2","dpm_2_ancestral","lms","dpmpp_2m","dpmpp_2m_sde","dpmpp_3m_sde","ddim","uni_pc"], {"default":"euler","tooltip":"采样器（8步）"}),
                "gen_sigmas": ("STRING", {"default":"1.0,0.99375,0.9875,0.98125,0.975,0.909375,0.725,0.421875,0.0","tooltip":"Sigmas（8步）"}),
                "img_compression": ("INT", {"default":18,"min":0,"max":100,"step":1}),
                "img2video_strength": ("FLOAT", {"default":0.7,"min":0.0,"max":1.0,"step":0.05}),
            },
            "optional": {
                "prev_video": ("IMAGE",),
                "vae_tile_size": ("INT", {"default":320,"min":64,"max":4096,"step":64}),
                "vae_overlap": ("INT", {"default":64,"min":0,"max":512,"step":16}),
                "vae_temporal_size": ("INT", {"default":80,"min":1,"max":4096,"step":1}),
                "vae_temporal_overlap": ("INT", {"default":16,"min":0,"max":256,"step":1}),
            }
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "FLOAT", "STRING")
    RETURN_NAMES = ("accumulated_video", "original_audio", "output_fps", "output_filepath")
    FUNCTION = "execute_relay"
    CATEGORY = "XB_ToolBox/Pipeline"

    def execute_relay(self, model, video_vae, audio_vae, clip,
                      start_image, width, height, total_frames, fps, audio,
                      segment_frames, overlap_frames,
                      positive_prompt, negative_prompt,
                      seed, sampler_gen, gen_sigmas,
                      img_compression, img2video_strength,
                      prev_video=None,
                      vae_tile_size=320, vae_overlap=64,
                      vae_temporal_size=80, vae_temporal_overlap=16):

        overlap = overlap_frames
        audio_sr, audio_wf = audio["sample_rate"], audio["waveform"]
        relay_count = math.ceil(total_frames / segment_frames)

        print(f"\n{'='*60}\n[XB-BOX] LTX-2.3 (003单次采样) | {total_frames}f | seg {segment_frames}f | x{relay_count}\n{'='*60}")

        accumulated_video = prev_video
        current_image = start_image.clone()

        gen_sigmas_list = [float(x.strip()) for x in gen_sigmas.split(",") if x.strip()]
        total_written = 0

        NCM = nodes.NODE_CLASS_MAPPINGS
        Preproc   = NCM.get("LTXVPreprocess")
        EmptyLat  = NCM["EmptyLTXVLatentVideo"]
        Img2Vid   = NCM.get("LTXVImgToVideoInplace")
        AudioEnc  = NCM["LTXVAudioVAEEncode"]
        NoiseMask = NCM.get("SetLatentNoiseMask")
        LtxCond   = NCM.get("LTXVConditioning")
        ConcatAV  = NCM["LTXVConcatAVLatent"]
        SeparateAV= NCM["LTXVSeparateAVLatent"]
        CropGuides= NCM.get("LTXVCropGuides")
        Decoder   = NCM["VAEDecodeTiled"]
        CFGG, RandN, KSampler, SSA = NCM["CFGGuider"], NCM["RandomNoise"], NCM["KSamplerSelect"], NCM["SamplerCustomAdvanced"]

        output_path = os.path.join(folder_paths.get_output_directory(), "LTX23_Infinite_Output.mp4")

        try:
            for r in range(relay_count):
                remaining = total_frames - total_written
                if remaining <= 0:
                    break
                eff_seg = min(segment_frames, remaining)
                actual_frames = ((eff_seg + 2)//4)*4 + 1
                print(f"\n[relay {r+1}/{relay_count}] written={total_written} remaining={remaining} gen={actual_frames}")

                seg_start_s = total_written * audio_sr // fps
                audio_s_per = actual_frames * audio_sr // fps
                seg_end_s = min(seg_start_s + audio_s_per, audio_wf.shape[-1])
                if seg_start_s >= audio_wf.shape[-1]:
                    print("[XB-BOX] Audio exhausted"); break
                seg_wf = audio_wf[..., seg_start_s:seg_end_s]
                if seg_wf.shape[-1] < audio_s_per:
                    ps = seg_wf.shape[:-1] + (audio_s_per - seg_wf.shape[-1],)
                    seg_wf = torch.cat([seg_wf, torch.zeros(ps, dtype=seg_wf.dtype, device=seg_wf.device)], dim=-1)
                chunk_audio = {"waveform": seg_wf, "sample_rate": audio_sr}

                # Stage 1: 首段缩放到目标尺寸，后续段 VAE 原生分辨率不缩放（003 模式）
                if r == 0:
                    current_image = comfy.utils.common_upscale(current_image.movedim(-1,1), width, height, "lanczos","center").movedim(1,-1)
                if Preproc is not None:
                    prep_out, = getattr(Preproc(), Preproc.FUNCTION)(image=current_image, img_compression=img_compression)
                else:
                    prep_out = current_image
                lr_w, lr_h = prep_out.shape[2], prep_out.shape[1]
                el = EmptyLat()
                lr_lat, = getattr(el, el.FUNCTION)(width=lr_w, height=lr_h, length=actual_frames, batch_size=1)
                if Img2Vid is not None:
                    lr_lat, = getattr(Img2Vid(), Img2Vid.FUNCTION)(vae=video_vae, image=prep_out, latent=lr_lat, strength=img2video_strength, bypass=False)

                # Stage 2: Audio + Conditioning
                aud_lat, = getattr(AudioEnc(), AudioEnc.FUNCTION)(audio=chunk_audio, audio_vae=audio_vae)
                if NoiseMask is not None:
                    aud_lat, = getattr(NoiseMask(), NoiseMask.FUNCTION)(samples=aud_lat, mask=torch.zeros((1,1,1024,1024), dtype=torch.float32))
                pos_cond, = nodes.CLIPTextEncode().encode(clip, positive_prompt)
                neg_cond, = nodes.CLIPTextEncode().encode(clip, negative_prompt)
                if LtxCond is not None:
                    pos_cond, neg_cond = getattr(LtxCond(), LtxCond.FUNCTION)(positive=pos_cond, negative=neg_cond, frame_rate=float(fps))

                # Stage 3: Sampling + CropGuides（003 模式）
                av_low, = getattr(ConcatAV(), ConcatAV.FUNCTION)(video_latent=lr_lat, audio_latent=aud_lat)
                g1, = getattr(CFGG(), CFGG.FUNCTION)(model=model, positive=pos_cond, negative=neg_cond, cfg=1.0)
                base_seed = seed + r * 10000
                n1, = getattr(RandN(), RandN.FUNCTION)(noise_seed=base_seed)
                s1, = getattr(KSampler(), KSampler.FUNCTION)(sampler_name=sampler_gen)
                st1 = torch.tensor(gen_sigmas_list, dtype=torch.float32)
                sampled, _ = getattr(SSA(), SSA.FUNCTION)(noise=n1, guider=g1, sampler=s1, sigmas=st1, latent_image=av_low)
                seg_latent, _ = getattr(SeparateAV(), SeparateAV.FUNCTION)(av_latent=sampled)

                if CropGuides is not None:
                    _, _, seg_latent = getattr(CropGuides(), CropGuides.FUNCTION)(positive=pos_cond, negative=neg_cond, latent=seg_latent)

                # Stage 4: VAE decode + 像素累积（零重叠，纯顺序拼接）
                decoded, = getattr(Decoder(), Decoder.FUNCTION)(
                    samples=seg_latent, vae=video_vae,
                    tile_size=vae_tile_size, overlap=vae_overlap,
                    temporal_size=vae_temporal_size, temporal_overlap=vae_temporal_overlap)
                is_4d = len(decoded.shape) == 4

                current_image = decoded[-1:].clone() if is_4d else decoded[:, -1:].clone()

                cd = 0 if is_4d else 1
                accumulated_video = _safe_video_accumulate(accumulated_video, decoded, cd, label=f"LTX-{r+1}", concat_mode="自动")
                total_written += decoded.shape[cd]
                print(f"   accum: +{decoded.shape[cd]}f -> total {total_written}f/{total_frames}f")

                if total_written > total_frames:
                    excess = total_written - total_frames
                    if is_4d:
                        accumulated_video = accumulated_video[:-excess]
                    else:
                        accumulated_video = accumulated_video[:, :-excess]
                    total_written = total_frames
                    print(f"[XB-BOX] ⚠️ 裁剪多余帧: {excess}f")

                gc.collect()
                mm.soft_empty_cache()

            # 全视频统一色彩校正，消除段间边界差异
            if accumulated_video is not None:
                is_4d = len(accumulated_video.shape) == 4
                accumulated_video = _apply_progressive_color_correction(accumulated_video, start_image, is_4d)
            print(f"\n[DONE] {total_written}f ({total_written/fps:.1f}s)")

        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback; traceback.print_exc()

        _refresh_models(force=True)
        return (accumulated_video, audio, float(fps), output_path)
