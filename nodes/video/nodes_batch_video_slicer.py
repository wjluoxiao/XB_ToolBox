"""
XB-BOX 视频批量切片
====================
参考官方「Trim Video」节点新写的批量版：

把一段长视频（或一批图像帧）按「起始时间 / 每段时长 / 段落数量」切成若干段，
以**列表**形式一次输出（批量视频）。下游节点会按列表逐段执行 —— 也就是
先切片、再批量处理，避免一次性把整段长视频丢给下游导致 OOM。

输入 / 输出都做了视频⇄图像的交叉兼容：
· 输入端口同时接受 VIDEO 与 IMAGE（图像输入时用「图像输入帧率」当帧率）；
· 输出端口是通配类型，每段既是一个 IMAGE 张量（B,H,W,C），
  又实现了 ComfyUI 的 VIDEO 接口（get_components / save_to / as_trimmed …），
  所以既能接图像节点，也能接视频节点，帧数 / 帧率 / 分辨率全部正确。
"""

from fractions import Fraction

import torch
from comfy_api.latest import io, InputImpl, Types

DEFAULT_FPS = 24.0


# ============================================================
# XB_VideoSliceSegment — 既是 IMAGE 张量，又是 VIDEO 的切片段
# ============================================================
class XB_VideoSliceSegment(torch.Tensor):
    """一段视频切片：当作 IMAGE 用时是 (帧数, 高, 宽, 通道) 张量；当作 VIDEO 用时走 VideoInput 接口。"""

    _frame_rate = Fraction(int(DEFAULT_FPS))
    _audio = None
    _video = None

    # ── 构造 ────────────────────────────────────────────────
    @staticmethod
    def wrap(images: torch.Tensor, frame_rate: Fraction, audio=None) -> "XB_VideoSliceSegment":
        plain = images.as_subclass(torch.Tensor) if isinstance(images, torch.Tensor) else images
        obj = torch.Tensor._make_subclass(XB_VideoSliceSegment, plain, False)
        obj._frame_rate = frame_rate
        obj._audio = audio
        obj._video = InputImpl.VideoFromComponents(
            Types.VideoComponents(images=plain, frame_rate=frame_rate, audio=audio)
        )
        return obj

    def _video_obj(self) -> InputImpl.VideoFromComponents:
        video = getattr(self, "_video", None)
        if video is None:
            video = InputImpl.VideoFromComponents(
                Types.VideoComponents(
                    images=self.as_subclass(torch.Tensor),
                    frame_rate=getattr(self, "_frame_rate", Fraction(int(DEFAULT_FPS))),
                    audio=getattr(self, "_audio", None),
                )
            )
            try:
                self._video = video
            except Exception:
                pass
        return video

    # ── VIDEO 接口（与官方 VideoInput 保持一致） ─────────────
    def get_components(self):
        return self._video_obj().get_components()

    def save_to(self, path, **kwargs):
        return self._video_obj().save_to(path, **kwargs)

    def as_trimmed(self, start_time=None, duration=None, strict_duration=False):
        return self._video_obj().as_trimmed(start_time, duration, strict_duration=strict_duration)

    def as_cropped(self, x=0, y=0, width=0, height=0):
        return self._video_obj().as_cropped(x, y, width, height)

    def get_stream_source(self):
        return self._video_obj().get_stream_source()

    def get_active_trim_window(self):
        return self._video_obj().get_active_trim_window()

    def get_dimensions(self):
        return int(self.shape[2]), int(self.shape[1])

    def get_frame_rate(self):
        return self._video_obj().get_frame_rate()

    def get_frame_count(self):
        return int(self.shape[0])

    def get_duration(self):
        rate = float(self.get_frame_rate())
        return float(self.shape[0] / rate) if rate > 0 else 0.0

    def get_bit_depth(self):
        return self._video_obj().get_bit_depth()

    def get_color_space(self):
        return self._video_obj().get_color_space()

    def get_chroma_subsampling(self):
        return self._video_obj().get_chroma_subsampling()


# ============================================================
# 工具函数
# ============================================================
def _slice_audio(audio, start_seconds: float, duration_seconds: float):
    """按时间切音频，让每段的音轨跟画面同段对齐。"""
    if not audio:
        return None
    waveform = audio.get("waveform")
    sample_rate = int(audio.get("sample_rate") or 0)
    if waveform is None or sample_rate <= 0:
        return audio
    total = int(waveform.shape[-1])
    start = max(0, min(total, int(round(start_seconds * sample_rate))))
    end = min(total, start + int(round(duration_seconds * sample_rate)))
    if end <= start:
        end = min(total, start + 1)
    return {"waveform": waveform[..., start:end], "sample_rate": sample_rate}


def _unpack(value, fallback_fps: float):
    """把输入的 VIDEO 或 IMAGE 统一成 (帧张量, 帧率, 音频)。"""
    if isinstance(value, torch.Tensor):
        return value.as_subclass(torch.Tensor), float(fallback_fps), None
    if hasattr(value, "get_components"):
        components = value.get_components()
        rate = float(components.frame_rate or 0) or float(fallback_fps)
        return components.images, rate, components.audio
    raise TypeError(f"不支持的输入类型：{type(value).__name__}（需要 VIDEO 或 IMAGE）")


def _probe_length(value, fallback_fps: float):
    """只读元数据拿 (帧率, 总帧数)，不解码画面。拿不到就返回 (0.0, 0)。"""
    if not hasattr(value, "get_frame_rate") or not hasattr(value, "get_frame_count"):
        return 0.0, 0
    try:
        rate = float(value.get_frame_rate() or 0)
        frames = int(value.get_frame_count() or 0)
    except Exception:
        return 0.0, 0
    if rate <= 0 or frames <= 0:
        return 0.0, 0
    return rate, frames


def _decode_range(value, start_seconds: float, duration_seconds: float):
    """只解码 [start, start+duration) 这一段，返回 (帧张量, 音频, 帧率)；失败返回 None。"""
    try:
        trimmed = value.as_trimmed(start_seconds, duration_seconds)
    except Exception as e:
        print(f"[视频批量切片] 按段裁剪失败，回退整段解码：{e}")
        return None
    if trimmed is None:
        return None
    try:
        components = trimmed.get_components()
    except Exception as e:
        print(f"[视频批量切片] 该段解码失败，已跳过：{e}")
        return None
    if components.images is None or components.images.shape[0] == 0:
        return None
    return components.images, components.audio, float(components.frame_rate or 0)


# ============================================================
# XB_BatchVideoSlice — 视频批量切片
# ============================================================
class XB_BatchVideoSlice(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="XB_BatchVideoSlice",
            display_name="XB-BOX - 🎬 视频批量切片",
            category="XB_ToolBox/Video",
            search_aliases=["split video", "视频切片", "批量切片", "trim video", "视频分段"],
            description=(
                "参考官方 Trim Video 的批量版：把长视频（或图像帧）按起始时间、每段时长、段落数量切片，"
                "以列表形式逐段输出给下游批量处理，避免一次性处理整段导致 OOM。"
                "输入同时支持 VIDEO / IMAGE，输出每段既是 IMAGE 也是 VIDEO，可交叉连接图像与视频节点。"
            ),
            inputs=[
                io.MultiType.Input(
                    "video",
                    [io.Video, io.Image],
                    display_name="视频",
                    tooltip="支持视频（VIDEO）或图像帧序列（IMAGE）；接视频时自动读取原帧率与音轨。",
                ),
                io.Float.Input(
                    "start_time",
                    default=0.0,
                    min=0.0,
                    max=1e5,
                    step=0.001,
                    display_name="起始时间",
                    tooltip="从第几秒开始切（0 = 从头）。",
                ),
                io.Float.Input(
                    "duration",
                    default=3.0,
                    min=0.1,
                    max=1e5,
                    step=0.001,
                    display_name="每段时长",
                    tooltip="每一段持续几秒，按帧率换算成帧数。",
                ),
                io.Int.Input(
                    "count",
                    default=4,
                    min=1,
                    max=1000,
                    step=1,
                    display_name="段落数量",
                    tooltip="总共切出多少段；接近片尾时不足的段会自动截断（不会报错）。",
                ),
                io.Float.Input(
                    "fps",
                    default=DEFAULT_FPS,
                    min=1.0,
                    max=240.0,
                    step=1.0,
                    display_name="图像输入帧率",
                    optional=True,
                    advanced=True,
                    tooltip="仅当输入是 IMAGE 时用作帧率；输入是 VIDEO 时忽略，自动用视频原帧率。",
                ),
            ],
            outputs=[
                io.AnyType.Output(
                    "批量视频",
                    is_output_list=True,
                    tooltip="每段一个输出（列表），既可接图像节点也可接视频节点。",
                ),
                io.Image.Output(
                    "图像列表",
                    is_output_list=True,
                    tooltip="每段的图像帧（列表，与「批量视频」同一份数据，不额外占内存）；"
                            "接图像节点时可省掉「获取视频组件」的二次解码。",
                ),
                io.Audio.Output(
                    "音频列表",
                    is_output_list=True,
                    tooltip="每段对应的音轨（列表）；源文件没有音轨时为空。",
                ),
                io.Float.Output(
                    "帧率列表",
                    is_output_list=True,
                    tooltip="每段的帧率（列表），可直接接需要帧率的节点。",
                ),
            ],
        )

    @classmethod
    def execute(cls, video, start_time=0.0, duration=3.0, count=4, fps=DEFAULT_FPS):
        rate, total_frames = _probe_length(video, fps or DEFAULT_FPS)
        frame_rate = Fraction(rate).limit_denominator(1000000) if rate > 0 else Fraction(int(DEFAULT_FPS))
        seg_frames = max(1, int(round(float(duration) * rate))) if rate > 0 else int(DEFAULT_FPS)
        start_frame = max(0, min(total_frames, int(round(float(start_time) * rate)))) if rate > 0 else 0

        segments, images_out, audio_out, fps_out = [], [], [], []

        if total_frames > 0 and hasattr(video, "as_trimmed"):
            # ── 按段流式解码：只解当前这一段，不再把整段视频读进内存 ──
            for i in range(int(count)):
                begin = start_frame + i * seg_frames
                if begin >= total_frames:
                    break
                end = min(begin + seg_frames, total_frames)
                comp = _decode_range(video, begin / rate, (end - begin) / rate)
                if comp is None:
                    continue
                frames, sound, seg_rate = comp
                seg_frame_rate = Fraction(seg_rate).limit_denominator(1000000) if seg_rate else frame_rate
                segments.append(XB_VideoSliceSegment.wrap(frames, seg_frame_rate, sound))
                images_out.append(frames)
                audio_out.append(sound)
                fps_out.append(float(seg_frame_rate))
            mode = "流式解码"
        else:
            # ── 兜底（图像输入 / 拿不到时长元数据）：整段读入后按帧切 ──
            images, rate, audio = _unpack(video, fps or DEFAULT_FPS)
            if images is None or images.shape[0] == 0:
                return io.NodeOutput([], [], [], [])
            if rate <= 0:
                rate = DEFAULT_FPS
            frame_rate = Fraction(rate).limit_denominator(1000000)
            total_frames = int(images.shape[0])
            seg_frames = max(1, int(round(float(duration) * rate)))
            start_frame = max(0, min(total_frames, int(round(float(start_time) * rate))))
            for i in range(int(count)):
                begin = start_frame + i * seg_frames
                if begin >= total_frames:
                    break
                end = min(begin + seg_frames, total_frames)
                chunk = images[begin:end]
                sound = _slice_audio(audio, begin / rate, (end - begin) / rate)
                segments.append(XB_VideoSliceSegment.wrap(chunk, frame_rate, sound))
                images_out.append(chunk)
                audio_out.append(sound)
                fps_out.append(float(frame_rate))
            mode = "整段切片"

        print(
            f"[视频批量切片] {mode}：共 {total_frames} 帧 @ {float(frame_rate):.3f}fps → "
            f"起始 {start_frame} 帧，每段 {seg_frames} 帧，输出 {len(segments)} 段"
        )
        return io.NodeOutput(segments, images_out, audio_out, fps_out)
