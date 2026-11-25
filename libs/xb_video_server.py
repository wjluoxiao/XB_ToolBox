import os
import subprocess
import re
import asyncio
import hashlib
import shutil

import server
import folder_paths

web = server.web

_PREVIEW_LOCKS = {}    # 同一个「文件+参数」并发请求只跑一次转码

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
MIN_DIM = 16           # 宽高低于它就当「没填」（拦截小数/脏值被当成分辨率）
PREVIEW_CACHE_KEEP = 60    # 预览缓存最多保留多少个文件

# 浏览器原生就能播的编码：这些情况下「参数全默认」时可以直接给原片，
# 既不用转码（秒开），又带完整时长、可拖动。
WEB_CODECS = {"h264", "vp8", "vp9", "av1"}
WEB_PIX_FMTS = {"yuv420p", "yuvj420p"}
WEB_EXTS = {".mp4", ".m4v", ".webm", ".mov"}


def _preview_cache_dir():
    d = os.path.join(folder_paths.get_temp_directory(), "xb_preview")
    os.makedirs(d, exist_ok=True)
    return d


def _prune_preview_cache(keep=PREVIEW_CACHE_KEEP):
    try:
        d = _preview_cache_dir()
        files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".mp4")]
        if len(files) <= keep:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for p in files[: len(files) - keep]:
            try:
                os.remove(p)
            except OSError:
                pass
    except Exception:
        pass


async def _transcode_to_file(args, target):
    """跑 ffmpeg 写到一个 .part 文件，成功后再改名。

    中途失败 / 被取消都不会留下半截缓存（半截文件会让播放器报错）。
    """
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + ".part.mp4"
    proc = await asyncio.create_subprocess_exec(
        *args, part, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    try:
        _, stderr = await proc.communicate()
    except asyncio.CancelledError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    if proc.returncode != 0 or not os.path.isfile(part) or os.path.getsize(part) == 0:
        err = (stderr or b"").decode(*ENCODE_ARGS).strip()
        print(f"[XB-BOX] 预览转码失败（{os.path.basename(target)}）：{err[:600] or 'ffmpeg 无输出'}")
        try:
            os.remove(part)
        except OSError:
            pass
        return False
    os.replace(part, target)
    return True


def _file_response(path, filename, content_type="video/mp4"):
    """完整文件响应：带 Content-Length 与 Range 支持 → 播放器一开始就知道总时长、可拖动。"""
    headers = {
        "Content-Disposition": f'filename="{os.path.basename(filename)}"',
        "Cache-Control": "no-store",
    }
    try:
        return web.FileResponse(path, headers=headers)
    except Exception:
        return web.Response(status=500, text="read failed")


def _probe_video(filepath):
    """用 PyAV 读元数据（比跑一遍 ffmpeg 探测快得多）。"""
    info = {"fps": 0.0, "w": 0, "h": 0, "codec": "", "pix_fmt": "", "duration": 0.0}
    try:
        import av
        with av.open(filepath, mode="r") as container:
            stream = container.streams.video[0]
            rate = stream.average_rate or stream.guessed_rate
            info["fps"] = float(rate) if rate else 0.0
            info["w"] = int(stream.codec_context.width or 0)
            info["h"] = int(stream.codec_context.height or 0)
            info["codec"] = (stream.codec_context.name or "").lower()
            info["pix_fmt"] = (stream.codec_context.pix_fmt or "").lower()
            if stream.metadata.get("rotate") in ("90", "-90", "270", "-270"):
                info["w"], info["h"] = info["h"], info["w"]
            try:
                info["duration"] = float(container.duration or 0) / 1_000_000.0
            except Exception:
                info["duration"] = 0.0
    except Exception:
        pass
    if info["fps"] <= 0:
        info["fps"] = 30.0
    return info


def _build_preview_args(filepath, opts):
    """拼 ffmpeg 参数（与后端 XB_LoadVideo 的取帧规则完全一致）。"""
    base_fps = opts["base_fps"]
    force_rate = opts["force_rate"]
    nth = opts["nth"]
    start_frame = opts["start_frame"]
    cap = opts["cap"]
    target_w, target_h = opts["target_w"], opts["target_h"]
    crop_to_box = opts["crop_to_box"]
    out_rate = (force_rate if force_rate > 0 else base_fps) / nth

    args = [_ffmpeg_path, "-v", "error", "-y", "-i", filepath]

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

    # +faststart：把 moov（含总时长）放到文件头，播放器一打开就知道完整时长、可任意拖动
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "96k",
             "-movflags", "+faststart",
             "-f", "mp4"]
    return args


@server.PromptServer.instance.routes.get("/xb/videopreview")
async def xb_video_preview(request):
    """加载视频节点用的参数预览：按 跳过帧 / 间隔取帧 / 帧率 / 分辨率 / 帧数上限 转码。

    这里返回的是**完整文件**（而不是边转边播的流）：流式 fMP4 的 moov 时长是 0，
    浏览器不知道总长，进度条就会随着分片一截一截地长（长视频表现为「8 秒 8 秒地涨」）。
    完整文件带真实时长，和官方 Load Video 看不出来区别，而且能拖动。
    """
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

    info = _probe_video(filepath)
    base_fps = info["fps"]
    src_w, src_h = info["w"], info["h"]

    skip = max(0, int(_num("skip_first_frames")))
    nth = max(1, int(_num("select_every_nth", 1)))
    force_rate = _num("force_rate")
    cap = max(0, int(_num("frame_load_cap")))
    width = max(0, int(_num("custom_width")))
    height = max(0, int(_num("custom_height")))
    # 小于 MIN_DIM 的宽高一律当「没填」：上游若是把小数（如 megapixels 0.9）误连进来，
    # 会在下面的 _even() 里变成 2px，预览就成了拉伸的畸形长条
    if width < MIN_DIM:
        width = 0
    if height < MIN_DIM:
        height = 0

    # 跳过帧数用「按帧号裁剪」而不是 -ss：-ss 停在帧边界时会丢/多留一帧，
    # 后端的 images[skip:] 是按帧号精确切的，这里必须一致
    start_frame = skip
    if "start_time" in query:
        try:
            start_frame = max(0, int(round(float(query["start_time"]) * base_fps)))
        except (TypeError, ValueError):
            start_frame = skip

    # ── 参数全默认 + 浏览器原生能播 → 直接给原片 ─────────────────────
    # 这就是官方「Load Video」节点的做法：预览直接用 /view 播原片，
    # 因此时长一开始就是完整的、进度条可以随便拖。这里原样照搬。
    neutral = (start_frame == 0 and nth == 1 and force_rate <= 0
               and cap == 0 and width == 0 and height == 0)
    ext = os.path.splitext(filepath)[1].lower()
    web_playable = (
        info["codec"] in WEB_CODECS
        and info["pix_fmt"] in WEB_PIX_FMTS
        and ext in WEB_EXTS
    )
    if neutral and web_playable:
        return _file_response(filepath, filename)

    # ── 否则转码成完整文件并缓存 ──────────────────────────────────────
    def _even(v):
        return max(2, int(v) - int(v) % 2)

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

    args = _build_preview_args(filepath, {
        "base_fps": base_fps, "force_rate": force_rate, "nth": nth,
        "start_frame": start_frame, "cap": cap,
        "target_w": target_w, "target_h": target_h, "crop_to_box": crop_to_box,
    })

    try:
        st = os.stat(filepath)
        key = hashlib.sha1("|".join(map(str, (
            os.path.abspath(filepath), st.st_mtime_ns, st.st_size,
            start_frame, nth, force_rate, cap, width, height,
        ))).encode("utf-8")).hexdigest()
    except OSError:
        return web.Response(status=404)

    target = os.path.join(_preview_cache_dir(), key + ".mp4")
    if not os.path.isfile(target):
        lock = _PREVIEW_LOCKS.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                if not os.path.isfile(target):
                    ok = await _transcode_to_file(args, target)
                    if not ok:
                        return web.Response(status=500, text="transcode failed")
                    _prune_preview_cache()
        finally:
            _PREVIEW_LOCKS.pop(key, None)
    return _file_response(target, filename)


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
    # 小于 MIN_DIM 的宽高一律当「没填」：上游若是把小数（如 megapixels 0.9）误连进来，
    # 会在下面的 _even() 里变成 2px，预览就成了拉伸的畸形长条
    if width < MIN_DIM:
        width = 0
    if height < MIN_DIM:
        height = 0

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
