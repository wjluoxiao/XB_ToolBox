"""
XB-BOX 保存视频
===============
套皮官方「Create Video」+「Save Video」二合一：
图片（+可选音频）→ 组帧 → 编码 → 保存到 output 目录，同时输出 VIDEO。

设置项顺序与需求一致：文件名前缀 → 帧率 → 位深 → 色彩空间 → 格式 → 编解码器。
其中「格式 / 编解码器」直接复用官方 Save Video 的输入定义（DynamicCombo），
因此编解码器下的「编码模式（auto / re-encode）+ CRF」等选项全部保留。
"""

import copy
import os
from fractions import Fraction

import folder_paths
from comfy.cli_args import args
from comfy_api.latest import io, ui, InputImpl, Types
from comfy_extras.nodes_video import CreateVideo, SaveVideo


def _input_map(schema):
    return {getattr(inp, "id", None): inp for inp in schema.inputs}


_CREATE_INPUTS = _input_map(CreateVideo.define_schema())
_SAVE_INPUTS = _input_map(SaveVideo.define_schema())


def _localize_dynamic(inp, names):
    """递归给 DynamicCombo 里的嵌套输入补中文显示名（官方只给了英文 id）。"""
    name = names.get(getattr(inp, "id", None))
    if name:
        inp.display_name = name
    for option in getattr(inp, "options", []) or []:
        for child in getattr(option, "inputs", []) or []:
            _localize_dynamic(child, names)


# 官方 Save Video 的「格式」是动态组合（格式 → 编解码器 → 编码模式 → CRF）。
# 深拷贝一份再汉化，避免改动官方节点本身的界面。
_FORMAT_INPUT = copy.deepcopy(_SAVE_INPUTS["format"])
_localize_dynamic(_FORMAT_INPUT, {"codec": "编解码器", "encoding": "编码模式", "crf": "CRF"})


def _resolve_save_settings(fmt):
    """把 DynamicCombo 的 format 值拆成 (容器, 编解码器, CRF)。"""
    if isinstance(fmt, dict):
        format_name = fmt.get("format", "auto")
        codec = fmt.get("codec") or {}
    else:
        format_name, codec = (fmt or "auto"), {}
    if not isinstance(codec, dict):
        codec = {"codec": str(codec)}
    codec_name = codec.get("codec") or "auto"
    if format_name == "auto":
        format_name = "webm" if codec_name == "av1" else "mp4"
    encoding = codec.get("encoding") or {}
    return format_name, codec_name, encoding.get("crf")


class XB_SaveVideo(io.ComfyNode):
    """保存视频 — 官方 Create Video + Save Video 的组合套皮。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="XB_SaveVideo",
            search_aliases=["save video", "保存视频", "导出视频", "create video"],
            display_name="XB-BOX - 🎬 保存视频",
            category="XB_ToolBox/Video",
            description=(
                "官方 Create Video + Save Video 二合一：图片（+可选音频）→ 组帧 → 编码 → 保存到 output 目录，"
                "同时输出 VIDEO。设置项顺序：文件名前缀 → 帧率 → 位深 → 色彩空间 → 格式 → 编解码器 → 自动播放"
                "（编解码器沿用官方动态选项，含编码模式 / CRF；自动播放控制预览是否自动开始，"
                "鼠标悬停在画面上才播放声音）。"
            ),
            inputs=[
                _CREATE_INPUTS["images"],
                _SAVE_INPUTS["filename_prefix"],
                _CREATE_INPUTS["fps"],
                io.Combo.Input(
                    "bit_depth",
                    options=["auto", 8, 10],
                    default="auto",
                    tooltip="Auto uses 8-bit for sRGB and 10-bit for HDR. Explicit 8-bit and 10-bit choices are independent of colorspace.",
                ),
                io.Combo.Input(
                    "color_space",
                    options=["sRGB", "HDR", "HDR PQ"],
                    default="sRGB",
                    tooltip="Colorspace of the input images. HDR selects BT.2020/HLG and HDR PQ selects BT.2020/PQ.",
                ),
                _FORMAT_INPUT,
                io.Boolean.Input(
                    "autoplay",
                    default=True,
                    label_on="开",
                    label_off="关",
                    tooltip="开：视频生成后自动播放（默认静音，鼠标悬停在画面上才出声）；"
                            "关：需要手动点击播放。",
                ),
                _CREATE_INPUTS["audio"],
            ],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
            is_output_node=True,
            outputs=[io.Video.Output(display_name="video")],
        )

    @classmethod
    def execute(cls, images, filename_prefix="video/ComfyUI", fps=30.0,
                bit_depth="auto", color_space="sRGB", format="auto", autoplay=True, audio=None):
        # autoplay 只给前端播放器用（js/xb_save_video.js），后端无需处理
        # 与官方 Create Video 一致：auto → sRGB 用 8bit、HDR / HDR PQ 用 10bit
        if bit_depth == "auto":
            bit_depth = 10 if color_space in ("HDR", "HDR PQ") else 8

        video = InputImpl.VideoFromComponents(
            Types.VideoComponents(images=images, audio=audio, frame_rate=Fraction(fps)),
            bit_depth=bit_depth,
            color_space=color_space,
        )

        format_name, codec_name, crf = _resolve_save_settings(format)

        # 与官方 Save Video 一致：写进输出文件元数据
        saved_metadata = None
        if not args.disable_metadata:
            hidden = getattr(cls, "hidden", None)
            prompt = getattr(hidden, "prompt", None) if hidden else None
            extra_pnginfo = getattr(hidden, "extra_pnginfo", None) if hidden else None
            metadata = {}
            if extra_pnginfo is not None:
                metadata.update(extra_pnginfo)
            if prompt is not None:
                metadata["prompt"] = prompt
            if metadata:
                saved_metadata = metadata

        width, height = video.get_dimensions()
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix,
            folder_paths.get_output_directory(),
            width,
            height,
        )
        file = f"{filename}_{counter:05}_.{Types.VideoContainer.get_extension(format_name)}"
        video.save_to(
            os.path.join(full_output_folder, file),
            format=Types.VideoContainer(format_name),
            codec=Types.VideoCodec(codec_name),
            metadata=saved_metadata,
            crf=crf,
        )

        return io.NodeOutput(video, ui=ui.PreviewVideo([ui.SavedResult(file, subfolder, io.FolderType.output)]))
