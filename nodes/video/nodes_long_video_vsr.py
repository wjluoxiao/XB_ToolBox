"""
XB-BOX 长视频逐段放大保存（RelayVSR）
=====================================
真正"切一节、跑一节、存一节、丢一节"的单节点流水线 —— 内存占用**与视频总长无关**。

为什么需要它：
ComfyUI 的列表执行是「每个节点先把 N 项全部算完再交给下游」，所以只要中间有一个节点
吃「图像列表」，N 段的帧就会同时留在内存里（切片 + 获取视频组件 + 条件节点会各留一份）。
把整条链路塞进一个节点内部的 for 循环后，任何时刻内存里只有 **当前这一段**：

    for i in range(count):
        解码第 i 段（只解这一段）
        RelayVSRConditioning → KSampler → VSRDecode
        编码落盘 → del + gc + soft_empty_cache()
        i += 1

内部直接调用官方实现（comfy_extras.nodes_wan 的 RelayVSRConditioning / VSRDecode、
nodes.KSampler），行为与「视频批量切片 → 获取视频组件 → 条件 → 采样 → VSR解码 → 保存」完全一致。
"""

import gc
import os
from fractions import Fraction

import comfy.model_management
import comfy.samplers
import comfy.utils
import folder_paths
import nodes as comfy_nodes
from comfy_api.latest import io, InputImpl, Types

from ...libs.xb_paths import resolve_filename_prefix
from .nodes_batch_save_video import (
    _FORMAT_INPUT,
    _pick_scalar,
    _resolve_save_settings,
    XB_BatchSaveVideo,
)
from .nodes_batch_video_slicer import _decode_range, _probe_length, _unpack

DEFAULT_FPS = 24.0
MAX_SEGMENTS = 1000
WEIGHT_DTYPES = ["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"]


def _list_or_empty(folder_key):
    try:
        names = list(folder_paths.get_filename_list(folder_key))
    except Exception:
        names = []
    return names or [""]


class XB_LongVideoVSRUpscale(io.ComfyNode):
    """长视频逐段放大保存（RelayVSR）— 单节点内循环，内存只占 1 段。"""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="XB_LongVideoVSRUpscale",
            display_name="XB-BOX - 🎬 长视频逐段放大保存（RelayVSR）",
            category="XB_ToolBox/Video",
            search_aliases=["long video vsr", "长视频放大", "逐段放大", "relayvsr batch", "long video upscale"],
            description=(
                "把「切片 → 条件 → 采样 → VSR 解码 → 保存」整条链塞进一个节点内部的逐段循环："
                "解码一段、放大一段、存一段、释放一段，任何时刻内存里只有当前这一段，"
                "所以不管视频多长、段数多少，内存占用基本恒定。"
                "内部直接调用官方 RelayVSRConditioning / KSampler / VSRDecode，效果与原流程一致。"
            ),
            is_output_node=True,
            inputs=[
                io.MultiType.Input(
                    "video",
                    [io.Video, io.Image],
                    display_name="视频",
                    tooltip="源视频（按时间段流式解码，不整片读入）；也接受图像帧序列。",
                ),
                io.Combo.Input(
                    "unet_name",
                    options=_list_or_empty("diffusion_models"),
                    default=next(iter(_list_or_empty("diffusion_models"))),
                    display_name="主模型",
                    tooltip="RelayVSR 放大模型（diffusion_models 目录），节点内部自动加载。",
                ),
                io.Combo.Input(
                    "unet_weight_dtype",
                    options=WEIGHT_DTYPES,
                    default="default",
                    display_name="模型精度",
                    advanced=True,
                    tooltip="一般保持 default；fp8 模型可按需选择。",
                ),
                io.Combo.Input(
                    "vae_name",
                    options=_list_or_empty("vae"),
                    default=next(iter(_list_or_empty("vae"))),
                    display_name="VAE",
                    tooltip="RelayVSR 解码用的 VAE（vae 目录），节点内部自动加载。",
                ),
                io.Float.Input(
                    "start_time", default=0.0, min=0.0, max=1e5, step=0.001,
                    display_name="起始时间", tooltip="从第几秒开始处理（0 = 从头）。",
                ),
                io.Float.Input(
                    "duration", default=5.0, min=0.1, max=1e5, step=0.001,
                    display_name="每段时长",
                    tooltip="每段几秒。段越短内存峰值越低（HQ 帧数与段长成正比）。",
                ),
                io.Int.Input(
                    "count", default=4, min=1, max=MAX_SEGMENTS, step=1,
                    display_name="段落数量", tooltip="处理多少段；到片尾自动停止。",
                ),
                io.Int.Input(
                    "steps", default=1, min=1, max=10000, step=1,
                    display_name="步数", tooltip="RelayVSR 用 1 步即可（cfg 1）。",
                ),
                io.Float.Input(
                    "cfg", default=1.0, min=0.0, max=100.0, step=0.1,
                    display_name="CFG", tooltip="RelayVSR 用 1.0。",
                ),
                io.Combo.Input(
                    "sampler_name",
                    options=list(comfy.samplers.KSampler.SAMPLERS),
                    default="euler",
                    display_name="采样器",
                ),
                io.Combo.Input(
                    "scheduler",
                    options=list(comfy.samplers.KSampler.SCHEDULERS),
                    default="simple",
                    display_name="调度器",
                ),
                io.Int.Input(
                    "seed", default=0, min=0, max=0xFFFFFFFFFFFFFFFF, step=1,
                    display_name="种子",
                ),
                io.Boolean.Input(
                    "seed_increment", default=True,
                    display_name="每段递增种子", tooltip="开：每段 seed+1，避免各段完全复制同样噪声。",
                ),
                io.Float.Input(
                    "detail", default=1.0, min=0.0, max=1.0, step=0.01,
                    display_name="细节强度", tooltip="VSR 解码保留多少模型补充的细节，1 = 全部。",
                ),
                io.String.Input(
                    "filename_prefix", default="video/XB_VSR",
                    display_name="文件名前缀", tooltip="保存到 output 目录下的路径前缀，序号自动递增。",
                ),
                io.Combo.Input(
                    "bit_depth", options=["auto", 8, 10], default="auto", display_name="位深",
                    tooltip="auto：sRGB 用 8bit，HDR 用 10bit。",
                ),
                io.Combo.Input(
                    "color_space", options=["sRGB", "HDR", "HDR PQ"], default="sRGB", display_name="色彩空间",
                ),
                io.Combo.Input(
                    "chroma_subsampling", options=["auto", "444", "422", "420", "none"], default="auto",
                    display_name="色度子采样",
                    tooltip="444 保留完整色彩分辨率，422 横向减半，420 双向减半；auto 用编码器默认。",
                ),
                _FORMAT_INPUT,
            ],
            outputs=[
                io.Video.Output(
                    display_name="批量视频", is_output_list=True,
                    tooltip="每段一个 VIDEO（指向已保存文件，不占内存），可接「🎬 视频批量拼接」。",
                ),
                io.String.Output(
                    display_name="已保存文件", is_output_list=True,
                    tooltip="每段保存出来的视频路径（列表）。",
                ),
            ],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
        )

    # ------------------------------------------------------------------
    @classmethod
    def execute(cls, video, unet_name="", unet_weight_dtype="default", vae_name="",
                start_time=0.0, duration=5.0, count=4,
                steps=1, cfg=1.0, sampler_name="euler", scheduler="simple",
                seed=0, seed_increment=True, detail=1.0, filename_prefix="video/XB_VSR",
                bit_depth="auto", color_space="sRGB", chroma_subsampling="auto", format="auto"):
        from comfy_extras.nodes_wan import RelayVSRConditioning, VSRDecode

        unet_name = _pick_scalar(unet_name, 0, "") or ""
        unet_weight_dtype = _pick_scalar(unet_weight_dtype, 0, "default") or "default"
        vae_name = _pick_scalar(vae_name, 0, "") or ""

        # 主模型 / VAE 由节点内部按下拉框加载
        if not unet_name:
            raise ValueError("长视频逐段放大保存：请在「主模型」下拉框选择模型")
        model = comfy_nodes.UNETLoader().load_unet(unet_name, unet_weight_dtype)[0]
        if not vae_name:
            raise ValueError("长视频逐段放大保存：请在「VAE」下拉框选择 VAE")
        vae = comfy_nodes.VAELoader().load_vae(vae_name)[0]

        bit_depth = _pick_scalar(bit_depth, 0, "auto")
        color_space = _pick_scalar(color_space, 0, "sRGB")
        chroma = _pick_scalar(chroma_subsampling, 0, "auto")
        prefix = _pick_scalar(filename_prefix, 0, "video/XB_VSR") or "video/XB_VSR"
        if bit_depth == "auto":
            bit_depth = 10 if color_space in ("HDR", "HDR PQ") else 8
        chroma = chroma if chroma in ("444", "422", "420") else None
        format_name, codec_name, crf = _resolve_save_settings(_pick_scalar(format, 0, "auto"))
        extension = Types.VideoContainer.get_extension(format_name)

        from ...libs.xb_paths import resolve_filename_prefix  # noqa: F811 (保持局部引用避免循环导入)
        prefix = resolve_filename_prefix(prefix)
        metadata = XB_BatchSaveVideo._metadata()

        rate, total_frames = _probe_length(video, DEFAULT_FPS)
        if total_frames <= 0:
            # 图像输入 / 拿不到元数据：退回整段读入（这种输入本来就是内存里已有的数据）
            images, rate, audio = _unpack(video, DEFAULT_FPS)
            if images is None or images.shape[0] == 0:
                raise ValueError("长视频逐段放大保存：输入里没有可用的帧")
            rate = float(rate or DEFAULT_FPS)
            total_frames = int(images.shape[0])
            whole = (images, audio)
        else:
            whole = None

        seg_frames = max(1, int(round(float(duration) * rate)))
        start_frame = max(0, min(total_frames, int(round(float(start_time) * rate))))
        if start_frame >= total_frames:
            raise ValueError(
                f"长视频逐段放大保存：起始时间 {start_time}s 超出视频长度 {total_frames / rate:.2f}s"
            )

        progress = comfy.utils.ProgressBar(int(count))
        saved_paths, batch_videos = [], []
        ksampler = comfy_nodes.KSampler()
        render = dict(
            steps=int(steps), cfg=float(cfg), sampler_name=sampler_name, scheduler=scheduler,
            detail=float(detail), bit_depth=bit_depth, color_space=color_space, chroma=chroma,
            format_name=format_name, codec_name=codec_name, crf=crf, extension=extension,
            prefix=prefix, metadata=metadata,
        )

        for i in range(int(count)):
            begin = start_frame + i * seg_frames
            if begin >= total_frames:
                break
            end = min(begin + seg_frames, total_frames)

            if whole is not None:
                frames = whole[0][begin:end]
                sound, seg_rate = None, rate
            else:
                decoded_range = _decode_range(video, begin / rate, (end - begin) / rate)
                if decoded_range is None:
                    print(f"[长视频放大] 第 {i + 1} 段解码失败，已跳过")
                    progress.update(1)
                    continue
                frames, sound, seg_rate = decoded_range
                seg_rate = float(seg_rate or rate)

            seg_seed = int(seed) + (i if seed_increment else 0)
            try:
                # 单独的函数作用域：返回时这一段的所有中间张量（LQ/HQ/latent/conditioning）自动释放
                rel_path, abs_path = cls._render_segment(
                    model, vae, ksampler, RelayVSRConditioning, VSRDecode,
                    frames, sound, seg_rate, seg_seed, **render,
                )
            finally:
                frames = None
                sound = None
                gc.collect()
                comfy.model_management.soft_empty_cache()
                progress.update(1)

            if not rel_path:
                continue
            saved_paths.append(rel_path)
            batch_videos.append(InputImpl.VideoFromFile(abs_path))
            print(f"[长视频放大] 第 {i + 1}/{int(count)} 段（帧 {begin}-{end}）→ {rel_path}")

        if not saved_paths:
            raise ValueError("长视频逐段放大保存：没有任何一段被成功处理")

        print(f"[长视频放大] 完成，共 {len(saved_paths)} 段")
        # 不返回 ui.PreviewVideo：这个节点不做视频预览（看结果请接「视频批量拼接」或直接打开 output 目录）
        return io.NodeOutput(batch_videos, saved_paths)

    # ------------------------------------------------------------------
    @classmethod
    def _render_segment(cls, model, vae, ksampler, RelayVSRConditioning, VSRDecode,
                        frames, sound, seg_rate, seg_seed, steps, cfg, sampler_name, scheduler,
                        detail, bit_depth, color_space, chroma, format_name, codec_name, crf,
                        extension, prefix, metadata):
        """处理单独一段：条件 → 采样 → VSR 解码 → 编码落盘。返回 (相对路径, 绝对路径)。"""
        frame_rate = Fraction(float(seg_rate)).limit_denominator(1000000)
        positive, latent = RelayVSRConditioning.execute(model, frames).result
        sampled = ksampler.sample(
            model, seg_seed, steps, cfg, sampler_name, scheduler,
            positive, positive, latent, 1.0,
        )[0]
        upscaled = VSRDecode.execute(vae, sampled, frames, detail).result[0]

        out_video = InputImpl.VideoFromComponents(
            Types.VideoComponents(images=upscaled, audio=sound, frame_rate=frame_rate),
            bit_depth=bit_depth,
            color_space=color_space,
            chroma_subsampling=chroma,
        )
        width, height = out_video.get_dimensions()
        folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            prefix, folder_paths.get_output_directory(), width, height
        )
        file = f"{filename}_{counter:05}_.{extension}"
        abs_path = os.path.join(folder, file)
        out_video.save_to(
            abs_path,
            format=Types.VideoContainer(format_name),
            codec=Types.VideoCodec(codec_name),
            metadata=metadata,
            crf=crf,
        )
        rel_path = os.path.join(subfolder, file) if subfolder else file
        print(f"[长视频放大]   本段输出 {width}x{height} {int(upscaled.shape[0])} 帧 @ {float(frame_rate):.3f}fps")
        # 函数返回后 positive/latent/sampled/upscaled/out_video 全部出作用域，可被回收
        return rel_path, abs_path
