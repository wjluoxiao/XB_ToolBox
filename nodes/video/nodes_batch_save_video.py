"""
XB-BOX 视频批量保存
====================
参考官方「Create Video」/「Save Video」，但把「解码 → 组帧 → 编码 → 存盘 → 释放」
全部放进同一个节点内部的逐段循环：

· 上游是列表时（如「🎬 视频批量切片」的 N 段），普通节点会先把 N 段全部算完
  再往下传 —— 于是 N 段解码结果同时留在内存里，长视频必然 OOM；
· 本节点用 INPUT_IS_LIST 一次拿到整批，然后按段 解码 → 编码 → 写盘 → 释放，
  峰值内存只等于 **1 段** 的体积。

两种用法（自动判断，无需切换）：
1. 接 vae + samples(潜变量列表) [+ images 低清参考帧] → 内部逐段解码后存盘；
   解码器支持 lq_images 时（RelayVSR 的 Flash 解码器）自动带上低清参考帧与 detail，
   普通 VAE 则走标准解码 —— 所以本节点不绑定 RelayVSR，任何"每段解码后要落盘"的流程都能用；
2. 只接 images（图像列表 / 视频列表）→ 直接把每段编码存盘；
3. 可选「拼接为完整视频」：所有段跑完后把分段文件**无损拼接**（stream copy，不重新解码）
   成一个完整视频，内存占用几乎为 0。
"""

import copy
import gc
import inspect
import os
from fractions import Fraction

import comfy.model_management
import folder_paths
import torch
from comfy.cli_args import args
from comfy_api.latest import io, ui, InputImpl, Types
from comfy_extras.nodes_video import CreateVideo, SaveVideo

from ...libs.xb_paths import resolve_filename_prefix

DEFAULT_FPS = 24.0
MAX_SEGMENTS = 1000


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


# 官方 Save Video 的「格式」：格式 → 编解码器 → 编码模式 → CRF
_FORMAT_INPUT = copy.deepcopy(_SAVE_INPUTS["format"])
_localize_dynamic(_FORMAT_INPUT, {"codec": "编解码器", "encoding": "编码模式", "crf": "CRF"})


def _resolve_save_settings(fmt):
    """把 DynamicCombo 的 format 值拆成 (容器, 编解码器, CRF)。

    ⚠️ 本节点是 INPUT_IS_LIST，动态组合的值可能被多包一层 list（实测会出现
    `[['auto']]` / `[{'format': ['auto'], ...}]` 这类结构），这里统一逐层拆掉。
    """
    fmt = _unwrap_scalar(fmt, "auto")
    if isinstance(fmt, dict):
        format_name = _unwrap_scalar(fmt.get("format", "auto"), "auto")
        codec = fmt.get("codec") or {}
    elif isinstance(fmt, (list, tuple)):
        format_name = next((x for x in fmt if isinstance(x, str)), "auto")
        codec = {}
    else:
        format_name, codec = (fmt or "auto"), {}
    if not isinstance(format_name, str):
        format_name = "auto"
    if not isinstance(codec, dict):
        codec = {"codec": _unwrap_scalar(codec, "auto")}
    codec_name = _unwrap_scalar(codec.get("codec") or "auto", "auto")
    if not isinstance(codec_name, str):
        codec_name = "auto"
    if format_name == "auto":
        format_name = "webm" if codec_name == "av1" else "mp4"
    encoding = codec.get("encoding") or {}
    if not isinstance(encoding, dict):
        encoding = {}
    return format_name, codec_name, _unwrap_scalar(encoding.get("crf"), None)


def _as_list(value):
    """INPUT_IS_LIST 下每个输入都是 list；None 视为空列表。"""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _at(value, index, fallback=None):
    """按下标取值，超出范围时沿用最后一个（标量输入天然满足）。"""
    items = _as_list(value)
    if not items:
        return fallback
    return items[index] if index < len(items) else items[-1]


def _unwrap_scalar(value, fallback=None):
    """逐层拆掉只含 1 个元素的 list/tuple（INPUT_IS_LIST 下动态组合会被多包一层）。"""
    while isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    if isinstance(value, (list, tuple)):
        return fallback
    return fallback if value is None else value


def _pick_scalar(container, index, fallback=None):
    """先按下标取，再把可能多包的一层 list 拆掉。"""
    return _unwrap_scalar(_at(container, index), fallback)


def _unpack_source(value, fallback_fps):
    """把一段输入统一成 (帧张量 或 None, 音频 或 None, 帧率 或 None)。"""
    if value is None:
        return None, None, None
    if isinstance(value, torch.Tensor):
        return value, None, None
    if hasattr(value, "get_components"):
        components = value.get_components()
        rate = float(components.frame_rate or 0) or None
        return components.images, components.audio, rate
    return None, None, None


def _accepts_lq_images(vae):
    """解码器是否支持 lq_images（RelayVSR 的 Flash 解码器支持，普通 VAE 不支持）。

    普通 VAE 的 decode 只有 **kwargs，把 lq_images 传下去会炸，所以按签名显式判断。
    """
    try:
        decode = getattr(getattr(vae, "first_stage_model", None), "decode", None)
        if decode is None:
            return False
        return "lq_images" in inspect.signature(decode).parameters
    except Exception:
        return False


class XB_BatchSaveVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="XB_BatchSaveVideo",
            display_name="XB-BOX - 🎬 视频批量保存",
            category="XB_ToolBox/Video",
            search_aliases=["batch save video", "视频批量保存", "分段保存", "save video list"],
            description=(
                "参考官方 Create Video / Save Video 的批量版：逐段 解码 → 组帧 → 编码 → 写盘 → 释放，"
                "峰值内存只占 1 段，专治长视频批量放大时的 OOM。"
                "接 vae + 潜变量列表时内部逐段解码（RelayVSR 解码器会自动带上低清参考帧与 detail，"
                "普通 VAE 走标准解码）；只接图像/视频列表时直接编码存盘。"
                "「批量视频」端口输出每段的 VIDEO（指向已保存的文件，不占内存），拼接请接「🎬 视频批量拼接」。"
            ),
            is_output_node=True,
            is_input_list=True,
            inputs=[
                io.Latent.Input(
                    "samples",
                    optional=True,
                    display_name="潜变量",
                    tooltip="潜变量列表（如采样器的输出）。接上 vae 后由本节点逐段解码，避免整批解码堆积内存。",
                ),
                io.Vae.Input(
                    "vae",
                    optional=True,
                    display_name="VAE",
                    tooltip="解码用的 VAE；接 VSR 解码器时会传入低清参考帧与 detail，复刻官方 VSRDecode。",
                ),
                io.Image.Input(
                    "images",
                    optional=True,
                    display_name="图像",
                    tooltip="图像/视频列表。接 vae+samples 时作为低清参考帧；没接 vae 时作为要保存的成品帧。",
                ),
                io.Audio.Input(
                    "audio",
                    optional=True,
                    display_name="音频",
                    tooltip="音频列表，按段与画面合并；长度不足时沿用最后一段。",
                ),
                io.Float.Input(
                    "fps",
                    default=DEFAULT_FPS,
                    min=1.0,
                    max=240.0,
                    step=1.0,
                    display_name="帧率",
                    tooltip="可直接连「加载视频 / 获取视频组件」的帧率列表；标量时全部段落通用。",
                ),
                io.String.Input(
                    "filename_prefix",
                    default="video/XB_Batch",
                    display_name="文件名前缀",
                    tooltip="保存到 output 目录下的路径前缀，序号自动递增。",
                ),
                io.Float.Input(
                    "detail",
                    default=1.0,
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    display_name="细节强度",
                    tooltip="仅 VSR 解码时生效：保留多少解码器补充的细节，1 = 全部。",
                ),
                io.Combo.Input(
                    "bit_depth",
                    options=["auto", 8, 10],
                    default="auto",
                    display_name="位深",
                    tooltip="auto：sRGB 用 8bit，HDR 用 10bit。",
                ),
                io.Combo.Input(
                    "color_space",
                    options=["sRGB", "HDR", "HDR PQ"],
                    default="sRGB",
                    display_name="色彩空间",
                ),
                io.Combo.Input(
                    "chroma_subsampling",
                    options=["auto", "444", "422", "420", "none"],
                    default="auto",
                    display_name="色度子采样",
                    tooltip="444 保留完整色彩分辨率，422 横向减半，420 双向减半；auto 用编码器默认，"
                            "none 表示不指定。不支持的选项会自动退到最接近的模式。",
                ),
                _FORMAT_INPUT,
            ],
            outputs=[
                io.String.Output(
                    display_name="已保存文件",
                    is_output_list=True,
                    tooltip="每个段落保存出来的视频路径（列表），只传字符串，不额外占内存。",
                ),
                io.Video.Output(
                    display_name="批量视频",
                    is_output_list=True,
                    tooltip="每段一个 VIDEO（指向已保存的文件，不占内存），可直接接下游视频节点；"
                            "需要拼接成完整视频请用「🎬 视频批量拼接」节点。",
                ),
            ],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
        )

    # ------------------------------------------------------------------
    @classmethod
    def execute(cls, samples=None, vae=None, images=None, audio=None,
                fps=DEFAULT_FPS, filename_prefix="video/XB_Batch", detail=1.0,
                bit_depth="auto", color_space="sRGB", chroma_subsampling="auto", format="auto"):
        sample_list = _as_list(samples)
        image_list = _as_list(images)
        audio_list = _as_list(audio)
        vae_obj = _pick_scalar(vae, 0)
        prefix = _pick_scalar(filename_prefix, 0, "video/XB_Batch") or "video/XB_Batch"
        bit_depth = _pick_scalar(bit_depth, 0, "auto")
        color_space = _pick_scalar(color_space, 0, "sRGB")
        chroma = _pick_scalar(chroma_subsampling, 0, "auto")
        fmt = _at(format, 0, "auto")

        total = max(len(sample_list), len(image_list))
        if total == 0:
            raise ValueError("视频批量保存：没有收到任何图像 / 潜变量（上游列表为空）")
        if total > MAX_SEGMENTS:
            raise ValueError(f"视频批量保存：段落数 {total} 超过上限 {MAX_SEGMENTS}")

        if bit_depth == "auto":
            bit_depth = 10 if color_space in ("HDR", "HDR PQ") else 8
        format_name, codec_name, crf = _resolve_save_settings(fmt)
        prefix = resolve_filename_prefix(prefix)
        extension = Types.VideoContainer.get_extension(format_name)
        chroma = chroma if chroma in ("444", "422", "420") else None
        lq_supported = _accepts_lq_images(vae_obj)

        saved_metadata = cls._metadata()

        results = []
        saved_paths = []
        batch_videos = []
        for i in range(total):
            latent = sample_list[i] if i < len(sample_list) else None
            source = image_list[i] if i < len(image_list) else None
            rate = _pick_scalar(fps, i, DEFAULT_FPS) or DEFAULT_FPS
            sound = _at(audio, i)

            frames, src_audio, src_rate = _unpack_source(source, rate)
            if src_audio is not None:
                sound = src_audio
            if src_rate:
                rate = src_rate
            reference = frames

            if vae_obj is not None and isinstance(latent, dict) and "samples" in latent:
                # 只有 RelayVSR 的 Flash 解码器支持 lq_images；普通 VAE 传下去会报错，按签名判断
                if reference is not None and lq_supported:
                    options = {"lq_images": reference, "detail": _pick_scalar(detail, i, 1.0)}
                else:
                    options = {}
                decoded = vae_obj.decode(latent["samples"], vae_options=options)
                frames = decoded.reshape(-1, *decoded.shape[-3:])
                del decoded
            elif frames is None:
                print(f"[视频批量保存] 第 {i + 1}/{total} 段缺少图像或潜变量，已跳过")
                continue

            video = InputImpl.VideoFromComponents(
                Types.VideoComponents(images=frames, audio=sound, frame_rate=Fraction(rate)),
                bit_depth=bit_depth,
                color_space=color_space,
                chroma_subsampling=chroma,
            )
            width, height = video.get_dimensions()
            folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
                prefix, folder_paths.get_output_directory(), width, height
            )
            file = f"{filename}_{counter:05}_.{extension}"
            abs_path = os.path.join(folder, file)
            video.save_to(
                abs_path,
                format=Types.VideoContainer(format_name),
                codec=Types.VideoCodec(codec_name),
                metadata=saved_metadata,
                crf=crf,
            )
            results.append(ui.SavedResult(file, subfolder, io.FolderType.output))
            saved_paths.append(os.path.join(subfolder, file) if subfolder else file)
            # ????????????????????????????
            batch_videos.append(InputImpl.VideoFromFile(abs_path))
            print(f"[视频批量保存] 第 {i + 1}/{total} 段 → {os.path.join(subfolder, file)} "
                  f"({int(frames.shape[0])} 帧 @ {float(rate):.3f}fps, {width}x{height})")

            # 关键：每段处理完立刻释放，峰值只保留当前这一段
            del video, frames, reference
            gc.collect()
            comfy.model_management.soft_empty_cache()

        if not results:
            raise ValueError("视频批量保存：没有任何有效的段落被保存")

        print(f"[??????] ?????? {len(saved_paths)} ???")
        return io.NodeOutput(saved_paths, batch_videos, ui=ui.PreviewVideo(results))

    # ------------------------------------------------------------------
    @classmethod
    def _metadata(cls):
        if args.disable_metadata:
            return None
        hidden = getattr(cls, "hidden", None)
        if hidden is None:
            return None
        metadata = {}
        extra_pnginfo = getattr(hidden, "extra_pnginfo", None)
        prompt = getattr(hidden, "prompt", None)
        if extra_pnginfo is not None:
            metadata.update(extra_pnginfo)
        if prompt is not None:
            metadata["prompt"] = prompt
        return metadata or None
