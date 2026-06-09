"""
XB-ToolBox 音频切片节点
======================
完全独立的音频加载/切片节点，支持可视化波形截取。
使用 av (PyAV) 解码，兼容所有格式（同 VHS 用 ffmpeg 的效果）
"""

import os

import folder_paths
import torch
import av
from aiohttp import web


def _load_audio_file(filepath: str):
    """用 av 解码音频，返回 (waveform_2d, sample_rate)。加载失败返回 None"""
    try:
        with av.open(filepath) as af:
            if not af.streams.audio:
                return None
            stream = af.streams.audio[0]
            sr = stream.codec_context.sample_rate
            frames = []
            for frame in af.decode(streams=stream.index):
                buf = torch.from_numpy(frame.to_ndarray())
                if buf.dim() == 1:
                    buf = buf.unsqueeze(0)
                elif buf.shape[0] != stream.channels:
                    buf = buf.view(-1, stream.channels).t()
                frames.append(buf)
            if not frames:
                return None
            wav = torch.cat(frames, dim=1)
            # 统一转为 float32
            if not wav.dtype.is_floating_point:
                if wav.dtype == torch.int16:
                    wav = wav.float() / (2 ** 15)
                elif wav.dtype == torch.int32:
                    wav = wav.float() / (2 ** 31)
            return wav, sr
    except Exception:
        return None


def _make_audio(waveform, sample_rate):
    """确保输出 shape (1, channels, N)，与 VHS 完全一致"""
    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0).unsqueeze(0)  # (N)→(1,1,N)
    elif waveform.dim() == 2:
        waveform = waveform.unsqueeze(0)                # (C,N)→(1,C,N)
    return {"waveform": waveform, "sample_rate": sample_rate}


# ============================================================
# 波形数据 API
# ============================================================
async def handle_audio_waveform(request):
    """返回音频文件的波形峰值数据"""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"})

    filename = data.get("filename", "")
    num_peaks = data.get("num_peaks", 600)

    if not filename:
        return web.json_response({"error": "No filename provided"})

    input_dir = folder_paths.get_input_directory()
    audio_path = os.path.join(input_dir, filename)

    if not os.path.exists(audio_path):
        return web.json_response({"error": f"File not found: {filename}"})

    try:
        result = _load_audio_file(audio_path)
        if result is None:
            return web.json_response({"error": "Failed to decode audio"})
        waveform, sample_rate = result
        # 转单声道
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0)
        else:
            waveform = waveform[0]

        total_samples = waveform.shape[0]
        chunk_size = max(1, total_samples // num_peaks)
        peaks = []
        for i in range(0, total_samples, chunk_size):
            chunk = waveform[i:i + chunk_size]
            peaks.append([round(float(chunk.max().item()), 6), round(float(chunk.min().item()), 6)])

        return web.json_response({
            "duration": round(total_samples / sample_rate, 2),
            "sample_rate": sample_rate,
            "peaks": peaks[:num_peaks],
            "filename": filename
        })
    except Exception as e:
        return web.json_response({"error": str(e)})


# ============================================================
# 音频帧数工具：对齐 InfiniteTalk 的 4N+1 硬性要求
# ============================================================
def _snap_4n1(frames):
    """将帧数对齐到最近的 4N+1（1, 5, 9, 13, 17, 21, 25, 29, ...81, 85...）"""
    return max(1, ((frames + 2) // 4) * 4 + 1)

# ============================================================
# XB_AudioSlicer 节点
# ============================================================
class XB_AudioSlicer:
    """音频加载与切片节点 — 支持频谱可视化 + 拖拽分割线截取
    输出帧数（非秒数），可直接对接 InfiniteTalk 接力点的 segment_length。"""

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
                "audio": (audio_files,),
                "fps": ("FLOAT", {"default": 25.0, "min": 1.0, "max": 120.0, "step": 1.0}),
                "start_time": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 99999.00, "step": 0.01, "precision": 2, "round": 0.01}),
                "end_time":   ("FLOAT", {"default": 10.00, "min": 0.00, "max": 99999.00, "step": 0.01, "precision": 2, "round": 0.01}),
                "duration_display": ("STRING", {"default": "0 帧", "multiline": False}),
            }
        }

    RETURN_TYPES = ("AUDIO", "INT")
    RETURN_NAMES = ("audio", "frame_count")
    FUNCTION = "slice_audio"
    CATEGORY = "XB_ToolBox/Audio"

    @classmethod
    def VALIDATE_INPUTS(cls, audio, **kwargs):
        return True

    def slice_audio(self, audio, fps, start_time, end_time, duration_display):
        if audio == "none":
            return (_make_audio(torch.zeros((1, 1), dtype=torch.float32), 44100), 0)

        result = _load_audio_file(os.path.join(folder_paths.get_input_directory(), audio))
        if result is None:
            return (_make_audio(torch.zeros((1, 1), dtype=torch.float32), 44100), 0)

        waveform, sample_rate = result
        # 转单声道
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        total_duration = waveform.shape[1] / sample_rate
        frame_duration = 1.0 / fps

        # 钳制时间范围（最小 1 帧，防止零长度）
        start_time = max(0.0, min(start_time, total_duration))
        end_time = max(start_time + frame_duration, min(end_time, total_duration))

        # 切片
        start_sample = int(start_time * sample_rate)
        end_sample = int(end_time * sample_rate)

        if end_sample <= start_sample:
            end_sample = min(start_sample + int(frame_duration * 4 * sample_rate), waveform.shape[1])

        sliced = waveform[:, start_sample:end_sample]
        duration_sec = (end_sample - start_sample) / sample_rate
        raw_frames = int(round(duration_sec * fps))
        frame_count = _snap_4n1(raw_frames)
        if frame_count != raw_frames:
            print(f"🔧 [音频切片] 帧数 {raw_frames} → {frame_count} (对齐 4N+1)")
        return (_make_audio(sliced, sample_rate), frame_count)


# ============================================================
# XB_AudioSlicerV1 — 可视化音频切片节点（波形频谱 + 拖拽分割线）
# ============================================================
class XB_AudioSlicerV1:
    """音频切片节点 V1 — 可视化波形窗口 + 拖拽分割线截取
    输出帧数（非秒数），可直接对接 InfiniteTalk 接力点的 segment_length。"""

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
                "audio": (audio_files,),
                "fps": ("FLOAT", {"default": 25.0, "min": 1.0, "max": 120.0, "step": 1.0}),
                "start_time": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 99999.00, "step": 0.01}),
                "end_time":   ("FLOAT", {"default": 10.00, "min": 0.00, "max": 99999.00, "step": 0.01}),
                "duration_display": ("STRING", {"default": "0 帧", "multiline": False}),
            }
        }

    RETURN_TYPES = ("AUDIO", "INT")
    RETURN_NAMES = ("audio", "frame_count")
    FUNCTION = "slice_audio"
    CATEGORY = "XB_ToolBox/Audio"

    @classmethod
    def VALIDATE_INPUTS(cls, audio, **kwargs):
        return True

    def slice_audio(self, audio, fps, start_time, end_time, duration_display):
        if audio == "none":
            return (_make_audio(torch.zeros((1, 1), dtype=torch.float32), 44100), 0)

        result = _load_audio_file(os.path.join(folder_paths.get_input_directory(), audio))
        if result is None:
            return (_make_audio(torch.zeros((1, 1), dtype=torch.float32), 44100), 0)

        waveform, sample_rate = result
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        total_duration = waveform.shape[1] / sample_rate
        frame_duration = 1.0 / fps
        start_time = max(0.0, min(start_time, total_duration))
        end_time = max(start_time + frame_duration, min(end_time, total_duration))

        start_sample = int(start_time * sample_rate)
        end_sample = int(end_time * sample_rate)
        if end_sample <= start_sample:
            end_sample = min(start_sample + int(frame_duration * 4 * sample_rate), waveform.shape[1])

        sliced = waveform[:, start_sample:end_sample]
        duration_sec = (end_sample - start_sample) / sample_rate
        raw_frames = int(round(duration_sec * fps))
        frame_count = _snap_4n1(raw_frames)
        if frame_count != raw_frames:
            print(f"🔧 [音频切片V1] 帧数 {raw_frames} → {frame_count} (对齐 4N+1)")
        return (_make_audio(sliced, sample_rate), frame_count)


# ============================================================
# XB_AudioSlicerV2 — 双人音频切片
# ============================================================
class XB_AudioSlicerV2:
    """双人音频切片 — 音频1 + 间隔(帧) + 音频2，独立可视化
    输出帧数（非秒数），可直接对接 InfiniteTalk 接力点的 segment_length。"""

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
                "audio1": (audio_files,),
                "fps": ("FLOAT", {"default": 25.0, "min": 1.0, "max": 120.0, "step": 1.0}),
                "start1": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 99999.00, "step": 0.01}),
                "end1": ("FLOAT", {"default": 10.00, "min": 0.00, "max": 99999.00, "step": 0.01}),
                "audio2": (audio_files,),
                "start2": ("FLOAT", {"default": 0.00, "min": 0.00, "max": 99999.00, "step": 0.01}),
                "end2": ("FLOAT", {"default": 10.00, "min": 0.00, "max": 99999.00, "step": 0.01}),
                "gap_frames": ("INT", {"default": 25, "min": 0, "max": 99999, "step": 1}),
                "total_display": ("STRING", {"default": "0 帧", "multiline": False}),
            }
        }

    RETURN_TYPES = ("AUDIO", "INT", "AUDIO", "INT", "AUDIO", "INT")
    RETURN_NAMES = ("combined_audio", "total_frames", "audio1", "frames1", "audio2", "frames2")
    FUNCTION = "slice_dual"
    CATEGORY = "XB_ToolBox/Audio"

    @classmethod
    def VALIDATE_INPUTS(cls, audio1, audio2, **kwargs):
        return True

    def _load(self, name):
        if name == "none": return None, 0
        result = _load_audio_file(os.path.join(folder_paths.get_input_directory(), name))
        if result is None: return None, 0
        wf, sr = result
        if wf.shape[0] > 1: wf = wf.mean(dim=0, keepdim=True)
        return {"waveform": wf, "sample_rate": sr}, wf.shape[1] / sr

    def _trim(self, audio, td, st, et, sr, fps):
        fd = 1.0 / fps
        st = max(0.0, min(st, td)); et = max(st + fd, min(et, td))
        ss, es = int(st * sr), int(et * sr)
        if es <= ss: es = min(ss + int(fd * 4 * sr), audio.shape[1])
        dur = (es - ss) / sr
        raw = int(round(dur * fps))
        return audio[:, ss:es], _snap_4n1(raw)

    def slice_dual(self, audio1, fps, start1, end1, audio2, start2, end2, gap_frames, total_display):
        a1, d1f = self._load(audio1); a2, d2f = self._load(audio2)
        sr = 44100
        if a1: sr = a1["sample_rate"]
        elif a2: sr = a2["sample_rate"]

        # 各自用原生采样率裁剪
        t1 = torch.zeros((1, int(0.04 * sr)), dtype=torch.float32); f1 = 0
        t2 = torch.zeros((1, int(0.04 * sr)), dtype=torch.float32); f2 = 0
        if a1 and d1f > 0: t1, f1 = self._trim(a1["waveform"], d1f, start1, end1, a1["sample_rate"], fps)
        if a2 and d2f > 0: t2, f2 = self._trim(a2["waveform"], d2f, start2, end2, a2["sample_rate"], fps)

        # 统一采样率
        import torchaudio
        if a2 and a2["sample_rate"] != sr:
            t2 = torchaudio.functional.resample(t2, a2["sample_rate"], sr)
        if a1 and a1["sample_rate"] != sr:
            t1 = torchaudio.functional.resample(t1, a1["sample_rate"], sr)

        gap_s = int(max(0, gap_frames) / fps * sr)
        gap_wf = torch.zeros((1, gap_s), dtype=torch.float32)
        combined = torch.cat([t1, gap_wf, t2], dim=1)
        total_f = _snap_4n1(f1 + max(0, gap_frames) + f2)
        if total_f != f1 + max(0, gap_frames) + f2:
            print(f"🔧 [音频切片V2] 合并帧数 {f1 + max(0, gap_frames) + f2} → {total_f} (对齐 4N+1)")
        return (_make_audio(combined, sr), total_f,
                _make_audio(t1, sr), f1, _make_audio(t2, sr), f2)
