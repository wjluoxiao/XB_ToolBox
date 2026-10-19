"""
XB-BOX 加载视频
===============
套皮官方「Load Video」+「Get Video Components」二合一：
选择 / 上传视频 → 解码 → 输出 图像 / 音频 / 帧率 / 位深 / 色彩空间。

同时融合 XB-BOX 视频加载器的抽帧与缩放选项：
强制帧率 → 输出宽度 → 输出高度 → 帧数上限 → 跳过帧数 → 间隔取帧。

预览行为与「保存视频」一致：自动播放开关 + 鼠标悬停在画面上才出声
（由 js/xb_video_preview.js 控制），节点宽高可自由缩放。
"""

import os

import folder_paths
import torch
from comfy.utils import common_upscale
from comfy_api.latest import io, InputImpl
from comfy_extras.nodes_video import preview_input_video

DIMMAX = 8192
BIGMAX = (2**53) - 1


def _video_files():
    input_dir = folder_paths.get_input_directory()
    files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
    return sorted(folder_paths.filter_files_content_types(files, ["video"]))


def _resize(images, width, height):
    """0 表示按原始比例；两个都给则强制拉伸到指定尺寸。"""
    if images.shape[0] == 0 or not width and not height:
        return images
    src_h, src_w = int(images.shape[1]), int(images.shape[2])
    if not src_w or not src_h:
        return images
    if width and height:
        target_w, target_h = int(width), int(height)
    elif width:
        target_w, target_h = int(width), max(1, round(src_h * width / src_w))
    else:
        target_w, target_h = max(1, round(src_w * height / src_h)), int(height)
    if (target_w, target_h) == (src_w, src_h):
        return images
    return common_upscale(images.movedim(-1, 1), target_w, target_h, "lanczos", "center").movedim(1, -1)


def _trim_audio(audio, start_seconds, duration_seconds):
    """按跳过的帧把音轨对齐到输出图像的时间段。"""
    if not audio:
        return None
    waveform = audio.get("waveform")
    sample_rate = int(audio.get("sample_rate") or 0)
    if waveform is None or sample_rate <= 0:
        return audio
    total = int(waveform.shape[-1])
    start = max(0, min(total, int(round(start_seconds * sample_rate))))
    end = min(total, start + int(round(duration_seconds * sample_rate))) if duration_seconds > 0 else total
    if end <= start:
        end = min(total, start + 1) if total else total
    if start == 0 and end == total:
        return audio
    return {"waveform": waveform[..., start:end], "sample_rate": sample_rate}


class XB_LoadVideo(io.ComfyNode):
    """加载视频 — 官方 Load Video + Get Video Components 的组合套皮。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="XB_LoadVideo",
            search_aliases=["load video", "加载视频", "读取视频", "get video components", "视频抽帧"],
            display_name="XB-BOX - 🎬 加载视频",
            category="XB_ToolBox/Video",
            has_intermediate_output=True,
            description=(
                "官方 Load Video + Get Video Components 二合一：选择 / 上传视频后解码，"
                "输出 图像 / 音频 / 帧率 / 位深 / 色彩空间。"
                "选项顺序：视频文件 → 强制帧率 → 输出宽度 → 输出高度 → 帧数上限 → 跳过帧数 → 间隔取帧 → 自动播放"
                "（自动播放控制预览是否自动开始，鼠标悬停在画面上才播放声音）。"
            ),
            inputs=[
                io.Combo.Input(
                    "file",
                    options=_video_files(),
                    display_name="视频文件",
                    upload=io.UploadType.video,
                    tooltip="input 目录下的视频文件；用输入框右侧的按钮可以直接上传视频。",
                ),
                io.Float.Input(
                    "force_rate",
                    default=0.0,
                    min=0.0,
                    max=60.0,
                    step=1.0,
                    display_name="强制帧率",
                    tooltip="0 = 保持原帧率；大于 0 时按该帧率重采样（丢帧或重复帧）。",
                ),
                io.Int.Input(
                    "custom_width",
                    default=0,
                    min=0,
                    max=DIMMAX,
                    display_name="输出宽度",
                    tooltip="0 = 保持原始宽度；只填一边时按原始比例缩放。",
                ),
                io.Int.Input(
                    "custom_height",
                    default=0,
                    min=0,
                    max=DIMMAX,
                    display_name="输出高度",
                    tooltip="0 = 保持原始高度；只填一边时按原始比例缩放。",
                ),
                io.Int.Input(
                    "frame_load_cap",
                    default=0,
                    min=0,
                    max=BIGMAX,
                    step=1,
                    display_name="帧数上限",
                    tooltip="0 = 不限制，读取全部帧。",
                ),
                io.Int.Input(
                    "skip_first_frames",
                    default=0,
                    min=0,
                    max=BIGMAX,
                    step=1,
                    display_name="跳过帧数",
                    tooltip="从第几帧开始读取（音轨会同步对齐）。",
                ),
                io.Int.Input(
                    "select_every_nth",
                    default=1,
                    min=1,
                    max=BIGMAX,
                    step=1,
                    display_name="间隔取帧",
                    tooltip="每隔 N 帧取一帧，1 = 逐帧读取。",
                ),
                io.Boolean.Input(
                    "autoplay",
                    default=True,
                    label_on="开",
                    label_off="关",
                    display_name="自动播放",
                    tooltip="开：加载后自动播放（默认静音，鼠标悬停在画面上才出声）；关：需要手动点击播放。",
                ),
            ],
            outputs=[
                io.Image.Output(display_name="图像"),
                io.Audio.Output(display_name="音频"),
                io.Float.Output(display_name="帧率"),
                io.Combo.Output(display_name="位深"),
                io.Combo.Output(display_name="色彩空间"),
            ],
        )

    @classmethod
    def execute(cls, file, force_rate=0.0, custom_width=0, custom_height=0,
                frame_load_cap=0, skip_first_frames=0, select_every_nth=1, autoplay=True):
        # autoplay 只给前端播放器用（js/xb_video_preview.js），后端无需处理
        video_path = folder_paths.get_annotated_filepath(file)
        source = InputImpl.VideoFromFile(video_path)
        components = source.get_components()

        images = components.images
        audio = components.audio
        source_rate = float(components.frame_rate) or 1.0

        # 与 XB 视频加载器一致的顺序：跳过帧 → 间隔取帧 → 帧数上限 → 强制帧率
        skip = max(0, int(skip_first_frames or 0))
        nth = max(1, int(select_every_nth or 1))
        cap = max(0, int(frame_load_cap or 0))

        if skip:
            images = images[skip:]
        if nth > 1:
            images = images[::nth]
        if cap and images.shape[0] > cap:
            images = images[:cap]

        out_rate = source_rate / nth
        rate = float(force_rate or 0.0)
        if rate > 0 and images.shape[0] > 1 and abs(rate - out_rate) > 1e-6:
            count = max(1, int(round(images.shape[0] * rate / out_rate)))
            idx = torch.clamp(
                (torch.arange(count, dtype=torch.float64) * out_rate / rate).round().long(),
                0, images.shape[0] - 1,
            )
            images = images[idx]
            out_rate = rate

        images = _resize(images, int(custom_width or 0), int(custom_height or 0))
        duration = images.shape[0] / out_rate if out_rate > 0 else 0.0
        audio = _trim_audio(audio, skip / source_rate, duration)

        return io.NodeOutput(
            images,
            audio,
            float(out_rate),
            str(source.get_bit_depth()),
            source.get_color_space(),
            ui=preview_input_video(file, source),
        )

    @classmethod
    def validate_inputs(cls, file):
        if not folder_paths.exists_annotated_filepath(file):
            return "Invalid video file: {}".format(file)
        return True

    @classmethod
    def fingerprint_inputs(cls, file, **kwargs):
        # 用修改时间代替内容哈希，避免大文件反复哈希
        return os.path.getmtime(folder_paths.get_annotated_filepath(file))
