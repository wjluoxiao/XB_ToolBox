import os
import subprocess
import re
import asyncio
import shutil

import server
import folder_paths

web = server.web

# 查找 ffmpeg
def _find_ffmpeg():
    path = shutil.which("ffmpeg")
    if path:
        return path
    # 尝试 imageio_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    return None

_ffmpeg_path = _find_ffmpeg()
if _ffmpeg_path:
    print(f"✅ [XB-BOX] ffmpeg: {_ffmpeg_path}")
else:
    print("⚠️ [XB-BOX] ffmpeg 未找到，视频预览转码不可用")

ENCODE_ARGS = ("utf-8", "backslashreplace")
PREVIEW_MAX = 960      # 预览转码的长边上限（只影响预览，不影响真实输出）


async def _stream_media(request, args, filename, content_type="video/webm"):
    """把 ffmpeg 的 stdout 直接流给浏览器，中途取消也能安全收尾。"""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    resp = web.StreamResponse()
    resp.content_type = content_type
    resp.headers["Content-Disposition"] = f'filename="{os.path.basename(filename)}"'
    resp.headers["Cache-Control"] = "no-store"
    try:
        await resp.prepare(request)
        while True:
            chunk = await proc.stdout.read(2**20)
            if not chunk:
                break
            await resp.write(chunk)
    except (ConnectionResetError, ConnectionError, BrokenPipeError):
        pass
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
    return resp


@server.PromptServer.instance.routes.get("/xb/videopreview")
async def xb_video_preview(request):
    """加载视频节点用的实时参数预览：按 跳过帧 / 间隔取帧 / 帧率 / 分辨率 / 帧数上限 重新转码。"""
    if _ffmpeg_path is None:
        return web.Response(status=501, text="ffmpeg not found")

    query = request.rel_url.query
    filename = query.get("filename", "")
    file_type = query.get("type", "input")
    if not filename:
        return web.Response(status=400)

    try:
        if file_type == "input":
            filepath = folder_paths.get_annotated_filepath(filename)
        else:
            filepath = folder_paths.get_annotated_filepath(filename, file_type)
        if not os.path.isfile(filepath):
            return web.Response(status=404)
    except Exception:
        return web.Response(status=404)

    def _num(name, default=0.0):
        try:
            return float(query.get(name, default) or default)
        except (TypeError, ValueError):
            return default

    # 源帧率/尺寸用 PyAV 读元数据，比跑一遍 ffmpeg 探测快得多
    base_fps = 0.0
    src_w = src_h = 0
    try:
        import av
        with av.open(filepath, mode="r") as container:
            stream = container.streams.video[0]
            rate = stream.average_rate or stream.guessed_rate
            base_fps = float(rate) if rate else 0.0
            src_w = int(stream.codec_context.width or 0)
            src_h = int(stream.codec_context.height or 0)
            if stream.metadata.get("rotate") in ("90", "-90", "270", "-270"):
                src_w, src_h = src_h, src_w
    except Exception:
        base_fps = 0.0
    if base_fps <= 0:
        base_fps = 30.0

    skip = max(0, int(_num("skip_first_frames")))
    nth = max(1, int(_num("select_every_nth", 1)))
    force_rate = _num("force_rate")
    cap = max(0, int(_num("frame_load_cap")))
    width = max(0, int(_num("custom_width")))
    height = max(0, int(_num("custom_height")))

    # 与后端 XB_LoadVideo 完全一致：跳过帧 → 强制帧率重采样 → 每隔 nth 帧取一帧
    # 输出帧率 = (强制帧率 or 源帧率) / nth
    target_rate = force_rate if force_rate > 0 else base_fps
    out_rate = target_rate / nth

    # 跳过帧数用「按帧号裁剪」而不是 -ss：-ss 停在帧边界时会丢/多留一帧，
    # 后端的 images[skip:] 是按帧号精确切的，这里必须一致
    start_frame = skip
    if "start_time" in query:
        try:
            start_frame = max(0, int(round(float(query["start_time"]) * base_fps)))
        except (TypeError, ValueError):
            start_frame = skip

    args = [_ffmpeg_path, "-v", "error", "-i", filepath]

    rate_filters = []
    if start_frame > 0:
        rate_filters.append(f"trim=start_frame={start_frame}")
        rate_filters.append("setpts=PTS-STARTPTS")
    if force_rate > 0 and abs(force_rate - base_fps) > 1e-6:
        rate_filters.append(f"fps={force_rate:.6f}")
    if nth > 1:
        rate_filters.append(f"select=not(mod(n\\,{nth}))")
    if force_rate > 0 or nth > 1:
        # 重新打时间戳：每帧间隔 1/out_rate，时长与后端输出一致
        rate_filters.append(f"setpts=N/({out_rate:.6f}*TB)")

    def _even(v):
        return max(2, int(v) - int(v) % 2)

    # 预览尺寸：用户填了宽高就按输出尺寸出；没填就按原尺寸，超过 PREVIEW_MAX 的长边等比压下来（只影响预览）
    crop_to_box = False
    if width and height:
        # 与节点实际输出一致：宽高都填 → 居中裁剪到目标比例，再缩放（不是拉伸）
        target_w, target_h = _even(width), _even(height)
        crop_to_box = True
    elif width and src_w and src_h:
        target_w, target_h = _even(width), _even(round(src_h * width / src_w))
    elif height and src_w and src_h:
        target_w, target_h = _even(round(src_w * height / src_h)), _even(height)
    elif width or height:
        target_w, target_h = _even(width) if width else 0, _even(height) if height else 0
    else:
        target_w, target_h = src_w, src_h
        if target_w and target_h and max(target_w, target_h) > PREVIEW_MAX:
            ratio = PREVIEW_MAX / max(target_w, target_h)
            target_w, target_h = _even(round(target_w * ratio)), _even(round(target_h * ratio))

    vfilters = list(rate_filters)
    if crop_to_box:
        vfilters.append(f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase")
        vfilters.append(f"crop={target_w}:{target_h}")
    elif target_w and target_h:
        vfilters.append(f"scale={target_w}:{target_h}")
    elif target_w:
        vfilters.append(f"scale={target_w}:-2")
    elif target_h:
        vfilters.append(f"scale=-2:{target_h}")
    else:
        # 源尺寸是奇数时 yuv420p 会编码失败，兜一层偶数对齐
        vfilters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    args += ["-vf", ",".join(vfilters)]

    if rate_filters:
        # 帧已由 select/setpts 决定，禁止 ffmpeg 再按原始帧率补帧/丢帧
        args += ["-fps_mode", "passthrough"]

    if cap > 0:
        args += ["-frames:v", str(cap)]

    # 用渐进式 H.264(fMP4)：比 VP9/WebM 兼容性更好，浏览器不用等整段转码完就能播
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "96k",
             "-movflags", "frag_keyframe+empty_moov+default_base_moof",
             "-f", "mp4", "-"]
    return await _stream_media(request, args, filename, content_type="video/mp4")


@server.PromptServer.instance.routes.get("/xb/viewvideo")
async def xb_view_video(request):
    """视频预览转码端点。根据 force_size 参数实时转码视频到目标分辨率。"""
    if _ffmpeg_path is None:
        return web.Response(status=500, text="ffmpeg not found")

    query = request.rel_url.query
    filename = query.get("filename", "")
    file_type = query.get("type", "input")

    if not filename:
        return web.Response(status=400)

    # 解析文件路径
    try:
        if file_type == "input":
            filepath = folder_paths.get_annotated_filepath(filename)
        else:
            filepath = folder_paths.get_annotated_filepath(filename, file_type)
        if not os.path.exists(filepath) and not os.path.isfile(filepath):
            return web.Response(status=404)
    except Exception:
        return web.Response(status=404)

    # 构建 ffmpeg 参数
    in_args = ["-i", filepath]

    # 获取视频信息
    try:
        proc = await asyncio.create_subprocess_exec(
            _ffmpeg_path, *in_args, "-t", "0", "-f", "null", "-",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        _, stderr = await proc.communicate()
        stderr_str = stderr.decode(*ENCODE_ARGS)
    except Exception:
        return web.Response(status=500)

    # 帧率
    base_fps = 30
    match = re.search(r": Video: (\w+) .+, (\d+(?:\.\d+)?) fps", stderr_str)
    if match:
        base_fps = float(match.group(2))

    vfilters = []
    target_rate = float(query.get("force_rate", 0)) or base_fps
    modified_rate = target_rate / (float(query.get("select_every_nth", 1)) or 1)

    # start_time
    start_time = 0
    if "start_time" in query:
        start_time = float(query["start_time"])
    elif float(query.get("skip_first_frames", 0)) > 0:
        start_time = float(query.get("skip_first_frames")) / target_rate

    pre_seek, post_seek = [], []
    if start_time > 0:
        if start_time > 4:
            post_seek = ["-ss", "4"]
            pre_seek = ["-ss", str(start_time - 4)]
        else:
            post_seek = ["-ss", str(start_time)]
            pre_seek = []

    args = [_ffmpeg_path, "-v", "error"] + pre_seek + in_args + post_seek

    if target_rate != 0:
        args += ["-r", str(modified_rate)]

    # force_size: WxH 格式
    force_size = query.get("force_size", "")
    if force_size and force_size != "Disabled":
        size = force_size.split("x")
        if "?" not in size[0] and "?" not in size[1]:
            try:
                ar = float(size[0]) / float(size[1])
                vfilters.append(f"crop=if(gt({ar}\\,a)\\,iw\\,ih*{ar}):if(gt({ar}\\,a)\\,iw/{ar}\\,ih)")
            except (ValueError, ZeroDivisionError):
                pass
        size[0] = "-2" if size[0] == "?" else f"'min({size[0]},iw)'"
        size[1] = "-2" if size[1] == "?" else f"'min({size[1]},ih)'"
        vfilters.append(f"scale={':'.join(size)}")

    if vfilters:
        args += ["-vf", ",".join(vfilters)]

    frame_cap = float(query.get("frame_load_cap", 0))
    if frame_cap > 0:
        args += ["-frames:v", str(int(frame_cap))]

    args += ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
             "-f", "webm", "-"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        try:
            resp = web.StreamResponse()
            resp.content_type = "video/webm"
            resp.headers["Content-Disposition"] = f'filename="{os.path.basename(filename)}"'
            await resp.prepare(request)
            while True:
                chunk = await proc.stdout.read(2**20)
                if not chunk:
                    break
                await resp.write(chunk)
        except (ConnectionResetError, ConnectionError):
            pass
        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
    except BrokenPipeError:
        pass
    return resp
