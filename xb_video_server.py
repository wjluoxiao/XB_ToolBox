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
            await proc.wait()
        except (ConnectionResetError, ConnectionError):
            proc.kill()
    except BrokenPipeError:
        pass
    return resp
