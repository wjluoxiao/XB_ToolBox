"""
XB-BOX 视频批量拼接
====================
配套「🎬 视频批量保存」使用：接收它输出的 **批量视频**（每段一个 VIDEO，指向已保存的文件），

· 「拼接保存」：把所有分段**无损拼接**成一个完整视频（stream copy，不重新解码/编码，几乎不占内存）；
· 「保留分段」：关掉则拼接成功后删除分段文件，只留完整视频；
· 节点面板会把每段 + 拼接后的完整视频一起预览。

注：这里只读文件句柄，不把画面读进内存，所以长视频也不会 OOM。
"""

import copy
import gc
import os

import comfy.model_management
import folder_paths
from comfy_api.latest import io, ui, InputImpl, Types

from .nodes_batch_save_video import (
    _FORMAT_INPUT as _SAVE_FORMAT_INPUT,
    _as_list,
    _pick_scalar,
    _resolve_save_settings,
    XB_BatchSaveVideo,
)

# 深拷贝一份，避免与保存节点共用同一个 input 对象
_FORMAT_INPUT = copy.deepcopy(_SAVE_FORMAT_INPUT)


def _video_path(video):
    """从 VIDEO 输入里拿到真实文件路径（VideoFromFile 才有；内存视频返回 None）。"""
    try:
        source = video.get_stream_source()
    except Exception:
        return None
    if isinstance(source, str) and os.path.isfile(source):
        return source
    return None


def _saved_result(path):
    """把 output 目录下的文件转成前端可预览的 SavedResult。"""
    try:
        out_dir = os.path.abspath(folder_paths.get_output_directory())
        abs_path = os.path.abspath(path)
        if os.path.commonpath([out_dir, abs_path]) != out_dir:
            return None
        rel = os.path.relpath(abs_path, out_dir)
        subfolder = os.path.dirname(rel).replace("\\", "/")
        return ui.SavedResult(os.path.basename(rel), subfolder, io.FolderType.output)
    except Exception:
        return None


class XB_BatchVideoMerge(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="XB_BatchVideoMerge",
            display_name="XB-BOX - 🎬 视频批量拼接",
            category="XB_ToolBox/Video",
            search_aliases=["batch video merge", "视频批量拼接", "拼接视频", "concat video"],
            description=(
                "接「🎬 视频批量保存」的「批量视频」输出：把所有分段无损拼接成一个完整视频"
                "（stream copy，不重新解码/编码），可选择性删除分段文件，并预览每段与合成结果。"
            ),
            is_output_node=True,
            is_input_list=True,
            inputs=[
                io.Video.Input(
                    "videos",
                    display_name="批量视频",
                    tooltip="分段视频列表（接「视频批量保存」的批量视频端口）。",
                ),
                io.Boolean.Input(
                    "merge",
                    default=True,
                    display_name="拼接保存",
                    tooltip="打开：把所有分段拼接成一个完整视频；关闭：只预览/透传，不生成新文件。",
                ),
                io.Boolean.Input(
                    "keep_segments",
                    default=True,
                    display_name="保留分段",
                    tooltip="拼接保存成功时：关掉则删除分段文件，只留完整视频。",
                ),
                io.String.Input(
                    "filename_prefix",
                    default="video/XB_Merged",
                    display_name="文件名前缀",
                    tooltip="完整视频保存到 output 目录下的路径前缀，序号自动递增。",
                ),
                _FORMAT_INPUT,
            ],
            outputs=[
                io.Video.Output(
                    display_name="完整视频",
                    tooltip="拼接后的完整视频；关闭「拼接保存」时输出第一段（透传），没有内容时为空。",
                ),
                io.String.Output(
                    display_name="已保存文件",
                    tooltip="完整视频的文件路径；没有拼接时为空字符串。",
                ),
            ],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
        )

    # ------------------------------------------------------------------
    @classmethod
    def execute(cls, videos=None, merge=True, keep_segments=True,
                filename_prefix="video/XB_Merged", format="auto"):
        video_list = _as_list(videos)
        if len(video_list) == 1 and isinstance(video_list[0], (list, tuple)):
            video_list = _as_list(video_list[0])       # 保险：万一被多包一层
        if not video_list:
            raise ValueError("视频批量拼接：没有收到任何视频")

        merge = bool(_pick_scalar(merge, 0, True))
        keep_segments = bool(_pick_scalar(keep_segments, 0, True))
        prefix = _pick_scalar(filename_prefix, 0, "video/XB_Merged") or "video/XB_Merged"
        format_name, _, _ = _resolve_save_settings(_pick_scalar(format, 0, "auto"))

        segment_paths = [p for p in (_video_path(v) for v in video_list) if p]

        # 预览：每段（能定位到 output 目录的才预览）
        previews = [r for r in (_saved_result(p) for p in segment_paths) if r is not None]

        merged_video = None
        merged_path = ""

        if merge and len(video_list) > 1:
            merged_path = cls._concat(video_list, prefix, format_name)
            if merged_path:
                merged_video = InputImpl.VideoFromFile(merged_path)
                result = _saved_result(merged_path)
                if result is not None:
                    previews.append(result)
                if not keep_segments:
                    cls._remove_segments(segment_paths, merged_path)
        elif merge:
            # 只有 1 段：直接透传，不重复生成文件
            merged_video = video_list[0]
            merged_path = segment_paths[0] if segment_paths else ""

        if merged_video is None and video_list:
            merged_video = video_list[0]

        print(f"[视频批量拼接] 收到 {len(video_list)} 段"
              + (f"，已拼接 → {merged_path}" if merged_path and len(video_list) > 1 else "（未拼接）"))
        return io.NodeOutput(merged_video, merged_path, ui=ui.PreviewVideo(previews))

    # ------------------------------------------------------------------
    @classmethod
    def _concat(cls, video_list, prefix, format_name):
        """无损拼接（stream copy），返回新文件绝对路径；失败返回空字符串。"""
        try:
            merged = InputImpl.VideoFromList(video_list, codec=Types.VideoCodec.AUTO)
            extension = Types.VideoContainer.get_extension(format_name)
            folder, base, counter, subfolder, _ = folder_paths.get_save_image_path(
                prefix, folder_paths.get_output_directory(), 0, 0
            )
            while True:
                file = f"{base}_merged_{counter:05}_.{extension}"
                target = os.path.join(folder, file)
                if not os.path.exists(target):
                    break
                counter += 1
            merged.save_to(
                target,
                format=Types.VideoContainer(format_name),
                codec=Types.VideoCodec.AUTO,
                metadata=XB_BatchSaveVideo._metadata(),
            )
            del merged
            gc.collect()
            comfy.model_management.soft_empty_cache()
            print(f"[视频批量拼接] {len(video_list)} 段 → {os.path.join(subfolder, file)}")
            return target
        except Exception as e:
            print(f"[视频批量拼接] 拼接失败（分段文件未受影响）：{e}")
            return ""

    # ------------------------------------------------------------------
    @classmethod
    def _remove_segments(cls, segment_paths, merged_path):
        merged_abs = os.path.abspath(merged_path)
        removed = 0
        for path in segment_paths:
            if os.path.abspath(path) == merged_abs:
                continue
            try:
                os.remove(path)
                removed += 1
            except OSError as e:
                print(f"[视频批量拼接] 删除分段失败 {path}: {e}")
        print(f"[视频批量拼接] 已删除 {removed} 个分段文件")
