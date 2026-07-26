"""
XB-ToolBox 数字人参数调节节点
==============================
融合「视频参数大全」与「音频切片」节点，
为数字人推理提供一站式的参数管理与音频预处理。
"""

import os

import folder_paths
import torch

from .nodes_audio_slicer import _load_audio_file, _make_audio, _snap_4n1


# ============================================================
# XB_DigitalHumanParams_Single — 数字人参数调节（单人）
# ============================================================
class XB_DigitalHumanParams_Single:
    """融合「视频参数大全」的画幅/分辨率/帧率引擎与「音频切片V1」的音频截取。
    输出宽高、帧率、总帧数、切片音频，可直接对接单人数字人推理管线。"""

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        audio_files = ["none"]
        if os.path.exists(input_dir):
            for f in sorted(os.listdir(input_dir)):
                if f.lower().endswith(('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma', '.webm')):
                    audio_files.append(f)

        return {
            "required": {
                # ── 视频参数区（来自 XB_VideoParamsMaster）──
                "aspect_ratio": (["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "16:9 (LTX)", "9:16 (LTX)", "4:3 (LTX)", "3:4 (LTX)"], {"default": "Free"}),
                "width": ("INT", {"default": 480, "min": 64, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 832, "min": 64, "max": 8192, "step": 16}),
                "fps": ("INT", {"default": 25, "min": 1, "max": 120, "step": 1}),
                "fps_float": ("FLOAT", {"default": 25.0, "min": 1.0, "max": 120.0, "step": 0.01}),
                # ── 音频区（来自 XB_AudioSlicerV1）──
                "audio": (audio_files,),
                "start_time": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 99999.00, "step": 0.01}),
                "end_time":   ("FLOAT", {"default": 10.00, "min": 0.00, "max": 99999.00, "step": 0.01}),
                "duration_display": ("STRING", {"default": "0 帧", "multiline": False}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT", "FLOAT", "AUDIO")
    RETURN_NAMES = ("Width", "Height", "Total Frames", "FPS", "FPS_Float", "Audio")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/DigitalHuman"

    @classmethod
    def VALIDATE_INPUTS(cls, audio, **kwargs):
        return True

    def process(self, aspect_ratio, width, height, fps, fps_float,
                audio, start_time, end_time, duration_display):
        # ── 1. 视频参数处理（来自 XB_VideoParamsMaster）──
        final_fps = int(round(fps))

        if "Free" in aspect_ratio:
            safe_w, safe_h = width, height
        elif "LTX" in aspect_ratio:
            step = 32
            ratio_map = {"16:9 (LTX)": 16/9, "9:16 (LTX)": 9/16, "4:3 (LTX)": 4/3, "3:4 (LTX)": 3/4}
            target_ratio = ratio_map.get(aspect_ratio, 16/9)
            if width >= height:
                safe_w = max(step, round(width / step) * step)
                safe_h = max(step, round((safe_w / target_ratio) / step) * step)
            else:
                safe_h = max(step, round(height / step) * step)
                safe_w = max(step, round((safe_h * target_ratio) / step) * step)
        else:
            step = 16
            ratio_map = {"16:9": 16/9, "9:16": 9/16, "1:1": 1.0, "4:3": 4/3, "3:4": 3/4, "21:9": 21/9}
            target_ratio = ratio_map.get(aspect_ratio, 1.0)
            if width >= height:
                safe_w = max(step, round(width / step) * step)
                safe_h = max(step, round((safe_w / target_ratio) / step) * step)
            else:
                safe_h = max(step, round(height / step) * step)
                safe_w = max(step, round((safe_h * target_ratio) / step) * step)

        # ── 2. 音频切片处理（来自 XB_AudioSlicerV1）──
        if audio == "none":
            sliced_audio = _make_audio(torch.zeros((1, 1), dtype=torch.float32), 44100)
            total_frames = 0
        else:
            result = _load_audio_file(os.path.join(folder_paths.get_input_directory(), audio))
            if result is None:
                sliced_audio = _make_audio(torch.zeros((1, 1), dtype=torch.float32), 44100)
                total_frames = 0
            else:
                waveform, sample_rate = result
                if waveform.shape[0] > 1:
                    waveform = waveform.mean(dim=0, keepdim=True)

                total_duration = waveform.shape[1] / sample_rate
                frame_duration = 1.0 / final_fps

                st = max(0.0, min(start_time, total_duration))
                et = max(st + frame_duration, min(end_time, total_duration))

                start_sample = int(st * sample_rate)
                end_sample = int(et * sample_rate)

                if end_sample <= start_sample:
                    end_sample = min(start_sample + int(frame_duration * 4 * sample_rate), waveform.shape[1])

                sliced = waveform[:, start_sample:end_sample]
                duration_sec = (end_sample - start_sample) / sample_rate
                raw_frames = int(round(duration_sec * final_fps))
                total_frames = _snap_4n1(raw_frames)

                # 音频物理长度对齐 4N+1 帧数
                target_samples = int((total_frames / final_fps) * sample_rate)
                if sliced.shape[1] < target_samples:
                    pad = torch.zeros((sliced.shape[0], target_samples - sliced.shape[1]),
                                      dtype=sliced.dtype, device=sliced.device)
                    sliced = torch.cat([sliced, pad], dim=1)
                elif sliced.shape[1] > target_samples:
                    sliced = sliced[:, :target_samples]

                if total_frames != raw_frames:
                    print(f"🔧 [数字人参数(单人)] 帧数 {raw_frames} → {total_frames} (对齐 4N+1)")

                sliced_audio = _make_audio(sliced, sample_rate)

        return (safe_w, safe_h, total_frames, final_fps, float(final_fps), sliced_audio)


# ============================================================
# XB_DigitalHumanParams_Dual — 数字人参数调节（双人）
# ============================================================
class XB_DigitalHumanParams_Dual:
    """融合「视频参数大全」的画幅/分辨率/帧率引擎与「音频切片V3」的双轨混音。
    支持静音消音、接力/重叠合并，输出可直接对接双人数字人推理管线。"""

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        audio_files = ["none"]
        if os.path.exists(input_dir):
            for f in sorted(os.listdir(input_dir)):
                if f.lower().endswith(('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma', '.webm')):
                    audio_files.append(f)

        return {
            "required": {
                # ── 视频参数区（来自 XB_VideoParamsMaster）──
                "aspect_ratio": (["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "16:9 (LTX)", "9:16 (LTX)", "4:3 (LTX)", "3:4 (LTX)"], {"default": "Free"}),
                "width": ("INT", {"default": 480, "min": 64, "max": 8192, "step": 16}),
                "height": ("INT", {"default": 832, "min": 64, "max": 8192, "step": 16}),
                "fps": ("INT", {"default": 24, "min": 1, "max": 120, "step": 1}),
                "fps_float": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.01}),
                # ── 音频区（来自 XB_AudioSlicerV3）──
                "audio1": (audio_files,),
                "start1": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.01}),
                "end1": ("FLOAT", {"default": 10.0, "min": 0.0, "max": 3600.0, "step": 0.01}),
                "mute_count1": ("INT", {"default": 0, "min": 0, "max": 20, "step": 1}),
                "mutes1_data": ("STRING", {"default": ""}),
                "audio2": (audio_files,),
                "start2": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.01}),
                "end2": ("FLOAT", {"default": 10.0, "min": 0.0, "max": 3600.0, "step": 0.01}),
                "mute_count2": ("INT", {"default": 0, "min": 0, "max": 20, "step": 1}),
                "mutes2_data": ("STRING", {"default": ""}),
                "merge_mode": (["接力", "重叠"], {"default": "接力"}),
                "total_display": ("STRING", {"default": "0 / 0帧", "multiline": False}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT", "FLOAT", "AUDIO", "AUDIO", "AUDIO")
    RETURN_NAMES = ("Width", "Height", "Total Frames", "FPS", "FPS_Float", "Audio1", "Audio2", "Combined Audio")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/DigitalHuman"

    @classmethod
    def VALIDATE_INPUTS(cls, audio1, audio2, **kwargs):
        return True

    def _load(self, name):
        if name == "none":
            return None, 0
        result = _load_audio_file(os.path.join(folder_paths.get_input_directory(), name))
        if result is None:
            return None, 0
        wf, sr = result
        if wf.shape[0] > 1:
            wf = wf.mean(dim=0, keepdim=True)
        return {"waveform": wf, "sample_rate": sr}, wf.shape[1] / sr

    def _trim(self, audio, td, st, et, sr, fps):
        fd = 1.0 / fps
        st = max(0.0, min(st, td))
        et = max(st + fd, min(et, td))
        ss, es = int(st * sr), int(et * sr)
        if es <= ss:
            es = min(ss + int(fd * 4 * sr), audio.shape[1])
        dur = (es - ss) / sr
        raw = int(round(dur * fps))
        fc = _snap_4n1(raw)
        sliced = audio[:, ss:es]
        target = int((fc / fps) * sr)
        if sliced.shape[1] < target:
            pad = torch.zeros((sliced.shape[0], target - sliced.shape[1]),
                              dtype=sliced.dtype, device=sliced.device)
            sliced = torch.cat([sliced, pad], dim=1)
        elif sliced.shape[1] > target:
            sliced = sliced[:, :target]
        return sliced, fc

    def _apply_mutes(self, waveform, sample_rate, mute_data_str, start_offset):
        """静音消音：减去 start_offset，将绝对时间转换为切片内相对时间"""
        if not mute_data_str:
            return waveform
        wav = waveform.clone()
        for r in mute_data_str.split(';'):
            if not r.strip():
                continue
            try:
                s_str, e_str = r.split(',')
                rel_s = float(s_str) - start_offset
                rel_e = float(e_str) - start_offset
                s_idx = max(0, int(rel_s * sample_rate))
                e_idx = min(wav.shape[1], int(rel_e * sample_rate))
                if e_idx > s_idx:
                    wav[:, s_idx:e_idx] = 0.0
            except Exception:
                pass
        return wav

    def process(self, aspect_ratio, width, height, fps, fps_float,
                audio1, start1, end1, mute_count1, mutes1_data,
                audio2, start2, end2, mute_count2, mutes2_data,
                merge_mode, total_display):
        # ── 1. 视频参数处理（来自 XB_VideoParamsMaster）──
        final_fps = int(round(fps))

        if "Free" in aspect_ratio:
            safe_w, safe_h = width, height
        elif "LTX" in aspect_ratio:
            step = 32
            ratio_map = {"16:9 (LTX)": 16/9, "9:16 (LTX)": 9/16, "4:3 (LTX)": 4/3, "3:4 (LTX)": 3/4}
            target_ratio = ratio_map.get(aspect_ratio, 16/9)
            if width >= height:
                safe_w = max(step, round(width / step) * step)
                safe_h = max(step, round((safe_w / target_ratio) / step) * step)
            else:
                safe_h = max(step, round(height / step) * step)
                safe_w = max(step, round((safe_h * target_ratio) / step) * step)
        else:
            step = 16
            ratio_map = {"16:9": 16/9, "9:16": 9/16, "1:1": 1.0, "4:3": 4/3, "3:4": 3/4, "21:9": 21/9}
            target_ratio = ratio_map.get(aspect_ratio, 1.0)
            if width >= height:
                safe_w = max(step, round(width / step) * step)
                safe_h = max(step, round((safe_w / target_ratio) / step) * step)
            else:
                safe_h = max(step, round(height / step) * step)
                safe_w = max(step, round((safe_h * target_ratio) / step) * step)

        # ── 2. 双轨音频处理（来自 XB_AudioSlicerV3）──
        a1, d1f = self._load(audio1)
        a2, d2f = self._load(audio2)
        sr = 44100
        if a1:
            sr = a1["sample_rate"]
        elif a2:
            sr = a2["sample_rate"]

        t1 = torch.zeros((1, int(0.04 * sr)), dtype=torch.float32)
        f1 = 0
        t2 = torch.zeros((1, int(0.04 * sr)), dtype=torch.float32)
        f2 = 0

        if a1 and d1f > 0:
            t1, f1 = self._trim(a1["waveform"], d1f, start1, end1, a1["sample_rate"], final_fps)
            t1 = self._apply_mutes(t1, a1["sample_rate"], mutes1_data, start1)
        if a2 and d2f > 0:
            t2, f2 = self._trim(a2["waveform"], d2f, start2, end2, a2["sample_rate"], final_fps)
            t2 = self._apply_mutes(t2, a2["sample_rate"], mutes2_data, start2)

        # 采样率对齐
        import torchaudio
        if a2 and a2["sample_rate"] != sr:
            t2 = torchaudio.functional.resample(t2, a2["sample_rate"], sr)
        if a1 and a1["sample_rate"] != sr:
            t1 = torchaudio.functional.resample(t1, a1["sample_rate"], sr)

        # 核心混音引擎
        if merge_mode == "接力":
            combined = torch.cat([t1, t2], dim=1)
            total_frames = _snap_4n1(f1 + f2)
        else:  # 重叠混音模式
            len1, len2 = t1.shape[1], t2.shape[1]
            max_len = max(len1, len2)
            if len1 < max_len:
                t1 = torch.cat([t1, torch.zeros((t1.shape[0], max_len - len1),
                                                 dtype=t1.dtype, device=t1.device)], dim=1)
            if len2 < max_len:
                t2 = torch.cat([t2, torch.zeros((t2.shape[0], max_len - len2),
                                                 dtype=t2.dtype, device=t2.device)], dim=1)
            # 硬件级压限 (Hard Limiter)
            combined = torch.clamp(t1 + t2, min=-1.0, max=1.0)
            total_frames = _snap_4n1(max(f1, f2))

        # 最终长度保护
        target_samples = int((total_frames / final_fps) * sr)
        if combined.shape[1] < target_samples:
            combined = torch.cat([combined,
                                  torch.zeros((combined.shape[0], target_samples - combined.shape[1]),
                                              dtype=combined.dtype, device=combined.device)], dim=1)
        elif combined.shape[1] > target_samples:
            combined = combined[:, :target_samples]

        return (safe_w, safe_h, total_frames, final_fps, float(final_fps),
                _make_audio(t1, sr), _make_audio(t2, sr), _make_audio(combined, sr))
