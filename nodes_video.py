import os
import itertools
import numpy as np
import torch
import cv2
import hashlib
import re
import time
import subprocess
import shutil as _shutil

import folder_paths
from comfy.utils import common_upscale, ProgressBar
import nodes

# ============================================================
# XB_ImageParamsMaster — 图像参数主控
# ============================================================
class XB_ImageParamsMaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"], {"default": "Free"}),
                "width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 1}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 1}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 1000, "step": 1}),
                "strength_float": ("FLOAT", {"default": 1.00, "min": 0.00, "max": 10.00, "step": 0.01}),
                "strength_int": ("INT", {"default": 1, "min": 0, "max": 1000, "step": 1}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "FLOAT", "INT", "INT")
    RETURN_NAMES = ("Image Width", "Image Height", "Batch Size", "Float Control", "Int Control", "Scale Size")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Image_Params"

    def process(self, aspect_ratio, width, height, batch_size, strength_float, strength_int):
        if "Free" in aspect_ratio:
            return (width, height, batch_size, float(strength_float), int(strength_int), max(width, height))

        # 解析宽高比约束，使用 round() 而非 // 避免累积误差
        ratio_map = {"1:1": 1.0, "16:9": 16/9, "9:16": 9/16, "4:3": 4/3, "3:4": 3/4, "21:9": 21/9}
        target_ratio = ratio_map.get(aspect_ratio, 1.0)
        step = 16

        if width >= height:
            safe_w = max(step, round(width / step) * step)
            safe_h = max(step, round((safe_w / target_ratio) / step) * step)
        else:
            safe_h = max(step, round(height / step) * step)
            safe_w = max(step, round((safe_h * target_ratio) / step) * step)

        return (safe_w, safe_h, batch_size, float(strength_float), int(strength_int), max(safe_w, safe_h))

# ============================================================
# XB_VideoParamsMaster — 视频参数主控
# ============================================================
class XB_VideoParamsMaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "16:9 (LTX)", "9:16 (LTX)", "4:3 (LTX)", "3:4 (LTX)"], {"default": "Free"}),
                "duration_display": ("STRING", {"default": "Video Duration: 0.00 s", "multiline": False}),
                "width": ("INT", {"default": 480, "min": 64, "max": 8192, "step": 1}),
                "height": ("INT", {"default": 832, "min": 64, "max": 8192, "step": 1}),
                "length": ("INT", {"default": 81, "min": 1, "max": 9999, "step": 1}),
                "fps": ("INT", {"default": 16, "min": 1, "max": 120, "step": 1}),
                "fps_float": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT", "FLOAT", "INT")
    RETURN_NAMES = ("Width", "Height", "Frames", "FPS", "FPS_Float", "Scale Size")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Image_Params"

    def process(self, aspect_ratio, duration_display, width, height, length, fps, fps_float):
        final_fps = int(round(fps))

        if "Free" in aspect_ratio:
            return (width, height, length, final_fps, float(final_fps), max(width, height))

        if "LTX" in aspect_ratio:
            # LTX 模式使用 step=32
            step = 32
            ratio_map = {"16:9 (LTX)": 16/9, "9:16 (LTX)": 9/16, "4:3 (LTX)": 4/3, "3:4 (LTX)": 3/4}
            target_ratio = ratio_map.get(aspect_ratio, 16/9)
            if width >= height:
                safe_w = max(step, round(width / step) * step)
                safe_h = max(step, round((safe_w / target_ratio) / step) * step)
            else:
                safe_h = max(step, round(height / step) * step)
                safe_w = max(step, round((safe_h * target_ratio) / step) * step)
        else:
            # 解析宽高比并强制约束，使用 round() 避免累积误差
            step = 16
            ratio_map = {"16:9": 16/9, "9:16": 9/16, "1:1": 1.0, "4:3": 4/3, "3:4": 3/4, "21:9": 21/9}
            target_ratio = ratio_map.get(aspect_ratio, 1.0)
            if width >= height:
                safe_w = max(step, round(width / step) * step)
                safe_h = max(step, round((safe_w / target_ratio) / step) * step)
            else:
                safe_h = max(step, round(height / step) * step)
                safe_w = max(step, round((safe_h * target_ratio) / step) * step)

        safe_len = max(1, round((length - 1) / 8) * 8 + 1)

        return (safe_w, safe_h, safe_len, final_fps, float(final_fps), max(safe_w, safe_h))

# ============================================================
# XB_MasterParameter — 万能参数控制器
# ============================================================
class XB_MasterParameter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["Free Mode", "Model Mode", "Encode Mode", "Decode Mode", "Ratio Mode", "Other Mode"], {"default": "Free Mode"}),
                "value": ("FLOAT", {"default": 1024.0, "min": 0.0, "max": 9999.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("INT", "FLOAT")
    RETURN_NAMES = ("Integer (INT)", "Float (FLOAT)")
    FUNCTION = "get_value"
    CATEGORY = "XB_ToolBox/Params_Control"

    def get_value(self, mode, value):
        if mode == "Free Mode":
            val = max(0.0, min(9999.0, value))
        elif mode == "Model Mode":
            val = max(0.0, min(50.0, value))
        elif mode in ["Encode Mode", "Decode Mode"]:
            val = max(64.0, min(3840.0, value))
            val = round(val / 32) * 32
        elif mode == "Ratio Mode":
            val = max(0.0, min(1.0, value))
        elif mode == "Other Mode":
            val = max(0.0, min(9999.0, value))
        else:
            val = value

        return (int(round(val)), float(val))


# ============================================================
# 以下代码一字不差搬运自 VHS load_video_nodes.py 和 utils.py
# ============================================================

DIMMAX = 8192
BIGMAX = (2**53-1)

video_extensions = ['webm', 'mp4', 'mkv', 'gif', 'mov']

VHSLoadFormats = {
    'None': {},
    'AnimateDiff': {'target_rate': 8, 'dim': (8,0,512,512)},
    'Mochi': {'target_rate': 24, 'dim': (16,0,848,480), 'frames':(6,1)},
    'LTXV': {'target_rate': 24, 'dim': (32,0,768,512), 'frames':(8,1)},
    'Hunyuan': {'target_rate': 24, 'dim': (16,0,848,480), 'frames':(4,1)},
    'Cosmos': {'target_rate': 24, 'dim': (16,0,1280,704), 'frames':(8,1)},
    'Wan': {'target_rate': 16, 'dim': (8,0,832,480), 'frames':(4,1)},
}

if not hasattr(nodes, 'VHSLoadFormats'):
    nodes.VHSLoadFormats = {}

def get_load_formats():
    formats = {}
    formats.update(nodes.VHSLoadFormats)
    formats.update(VHSLoadFormats)
    return (list(formats.keys()),
            {'default': 'AnimateDiff', 'formats': formats})

def get_format(format):
    if format in VHSLoadFormats:
        return VHSLoadFormats[format]
    return nodes.VHSLoadFormats.get(format, {})

def strip_path(path):
    path = path.strip()
    if path.startswith("\""):
        path = path[1:]
    if path.endswith("\""):
        path = path[:-1]
    return path

def calculate_file_hash(filename: str, hash_every_n: int = 1):
    h = hashlib.sha256()
    h.update(filename.encode())
    h.update(str(os.path.getmtime(filename)).encode())
    return h.hexdigest()

def target_size(width, height, custom_width, custom_height, downscale_ratio=8) -> tuple[int, int]:
    if downscale_ratio is None:
        downscale_ratio = 8
    if custom_width == 0 and custom_height ==  0:
        pass
    elif custom_height == 0:
        height *= custom_width/width
        width = custom_width
    elif custom_width == 0:
        width *= custom_height/height
        height = custom_height
    else:
        width = custom_width
        height = custom_height
    width = int(width/downscale_ratio + 0.5) * downscale_ratio
    height = int(height/downscale_ratio + 0.5) * downscale_ratio
    return (width, height)

def cv_frame_generator(video, force_rate, frame_load_cap, skip_first_frames,
                       select_every_nth, meta_batch=None, unique_id=None):
    video_cap = cv2.VideoCapture(video)
    if not video_cap.isOpened() or not video_cap.grab():
        raise ValueError(f"{video} could not be loaded with cv.")

    # extract video metadata
    fps = video_cap.get(cv2.CAP_PROP_FPS)
    width = int(video_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    width = 0

    if width <=0 or height <=0:
        _, frame = video_cap.retrieve()
        height, width, _ = frame.shape

    # set video_cap to look at start_index frame
    total_frame_count = 0
    total_frames_evaluated = -1
    frames_added = 0
    base_frame_time = 1 / fps
    prev_frame = None

    if force_rate == 0:
        target_frame_time = base_frame_time
    else:
        target_frame_time = 1/force_rate

    if total_frames > 0:
        if force_rate != 0:
            yieldable_frames = int(total_frames / fps * force_rate)
        else:
            yieldable_frames = total_frames
        if select_every_nth:
            yieldable_frames //= select_every_nth
        if frame_load_cap != 0:
            yieldable_frames =  min(frame_load_cap, yieldable_frames)
    else:
        yieldable_frames = 0
    yield (width, height, fps, duration, total_frames, target_frame_time, yieldable_frames)
    pbar = ProgressBar(yieldable_frames)
    time_offset=target_frame_time
    while video_cap.isOpened():
        if time_offset < target_frame_time:
            is_returned = video_cap.grab()
            # if didn't return frame, video has ended
            if not is_returned:
                break
            time_offset += base_frame_time
        if time_offset < target_frame_time:
            continue
        time_offset -= target_frame_time
        # if not at start_index, skip doing anything with frame
        total_frame_count += 1
        if total_frame_count <= skip_first_frames:
            continue
        else:
            total_frames_evaluated += 1

        # if should not be selected, skip doing anything with frame
        if total_frames_evaluated%select_every_nth != 0:
            continue

        # opencv loads images in BGR format (yuck), so need to convert to RGB for ComfyUI use
        # follow up: can videos ever have an alpha channel?
        # To my testing: No. opencv has no support for alpha
        unused, frame = video_cap.retrieve()
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # convert frame to comfyui's expected format
        # TODO: frame contains no exif information. Check if opencv2 has already applied
        frame = np.array(frame, dtype=np.float32)
        torch.from_numpy(frame).div_(255)
        if prev_frame is not None:
            inp  = yield prev_frame
            if inp is not None:
                #ensure the finally block is called
                return
        prev_frame = frame
        frames_added += 1
        if pbar is not None:
            pbar.update_absolute(frames_added, yieldable_frames)
        # if cap exists and we've reached it, stop processing frames
        if frame_load_cap > 0 and frames_added >= frame_load_cap:
            break
    if meta_batch is not None:
        meta_batch.inputs.pop(unique_id)
        meta_batch.has_closed_inputs = True
    if prev_frame is not None:
        yield prev_frame

#Python 3.12 adds an itertools.batched, but it's easily replicated for legacy support
def batched(it, n):
    while batch := tuple(itertools.islice(it, n)):
        yield batch

def batched_vae_encode(images, vae, frames_per_batch):
    for batch in batched(images, frames_per_batch):
        image_batch = torch.from_numpy(np.array(batch))
        yield from vae.encode(image_batch).numpy()

def resized_cv_frame_gen(custom_width, custom_height, downscale_ratio, **kwargs):
    gen = cv_frame_generator(**kwargs)
    info =  next(gen)
    width, height = info[0], info[1]
    frames_per_batch = (1920 * 1080 * 16) // (width * height) or 1
    if kwargs.get('meta_batch', None) is not None:
        frames_per_batch = min(frames_per_batch, kwargs['meta_batch'].frames_per_batch)
    if custom_width != 0 or custom_height != 0 or downscale_ratio is not None:
        new_size = target_size(width, height, custom_width, custom_height, downscale_ratio)
        yield (*info, new_size[0], new_size[1], False)
        if new_size[0] != width or new_size[1] != height:
            def rescale(frame):
                s = torch.from_numpy(np.fromiter(frame, np.dtype((np.float32, (height, width, 3)))))
                s = s.movedim(-1,1)
                s = common_upscale(s, new_size[0], new_size[1], "lanczos", "center")
                return s.movedim(1,-1).numpy()
            yield from itertools.chain.from_iterable(map(rescale, batched(gen, frames_per_batch)))
            return
    else:
        yield (*info, info[0], info[1], False)
    yield from gen

def _lazy_get_audio(file, start_time=0, duration=0):
    """替代 VHS 的 lazy_get_audio，使用 PyAV"""
    try:
        import av
    except ImportError:
        class _Dummy:
            def __getitem__(s,k): return torch.zeros((1,1))
            def __iter__(s): return iter({})
            def __len__(s): return 2
        return _Dummy()
    class _LazyAudioMap:
        def __init__(s, file, st, dur):
            s._d = None; s.file = file; s.st = st; s.dur = dur
        def _load(s):
            if s._d is not None: return
            try:
                c = av.open(s.file)
                a = next((x for x in c.streams if x.type == 'audio'), None)
                if not a: c.close(); s._d = {'waveform': torch.zeros((1,1)), 'sample_rate': 44100}; return
                sr = a.codec_context.sample_rate or 44100
                frames = []
                sp = int(s.st*sr) if s.st>0 else 0
                ep = int((s.st+s.dur)*sr) if s.dur>0 else None
                for f in c.decode(a):
                    if f.pts is not None:
                        if sp>0 and f.pts<sp: continue
                        if ep is not None and f.pts>=ep: break
                    frames.append(f.to_ndarray())
                c.close()
                if not frames: s._d = {'waveform': torch.zeros((1,1)), 'sample_rate': sr}; return
                wav = np.concatenate(frames, axis=-1)
                if wav.ndim==1: wav=wav[np.newaxis,:]
                elif wav.shape[0]>1: wav=wav.mean(axis=0, keepdims=True)
                wf = torch.from_numpy(wav.astype(np.float32))
                if wf.dim()==2: wf=wf.unsqueeze(0)
                s._d = {'waveform': wf, 'sample_rate': sr}
            except: s._d = {'waveform': torch.zeros((1,1)), 'sample_rate': 44100}
        def __getitem__(s,k): s._load(); return s._d[k]
        def __iter__(s): s._load(); return iter(s._d)
        def __len__(s): s._load(); return len(s._d)
    return _LazyAudioMap(file, start_time, duration)

def load_video(meta_batch=None, unique_id=None, memory_limit_mb=None, vae=None,
               generator=resized_cv_frame_gen, format='None',  **kwargs):
    if 'force_size' in kwargs:
        kwargs.pop('force_size')
    format = get_format(format)
    kwargs['video'] = strip_path(kwargs['video'])
    if vae is not None:
        downscale_ratio = getattr(vae, "downscale_ratio", 8)
    else:
        downscale_ratio = format.get('dim', (1,))[0]
    if meta_batch is None or unique_id not in meta_batch.inputs:
        gen = generator(meta_batch=meta_batch, unique_id=unique_id, downscale_ratio=downscale_ratio, **kwargs)
        (width, height, fps, duration, total_frames, target_frame_time, yieldable_frames, new_width, new_height, alpha) = next(gen)

        if meta_batch is not None:
            meta_batch.inputs[unique_id] = (gen, width, height, fps, duration, total_frames, target_frame_time, yieldable_frames, new_width, new_height, alpha)
            if yieldable_frames:
                meta_batch.total_frames = min(meta_batch.total_frames, yieldable_frames)
    else:
        (gen, width, height, fps, duration, total_frames, target_frame_time, yieldable_frames, new_width, new_height, alpha) = meta_batch.inputs[unique_id]

    memory_limit = None
    if memory_limit_mb is not None:
        memory_limit *= 2 ** 20
    else:
        try:
            import psutil
            memory_limit = (psutil.virtual_memory().available + psutil.swap_memory().free) - 2 ** 27
        except:
            memory_limit = BIGMAX
    if vae is not None:
        max_loadable_frames = int(memory_limit//(width*height*3*(4+4+1/10)))
    else:
        max_loadable_frames = int(memory_limit//(width*height*3*(.1)))
    if meta_batch is not None:
        if 'frames' in format:
            if meta_batch.frames_per_batch % format['frames'][0] != format['frames'][1]:
                error = (meta_batch.frames_per_batch - format['frames'][1]) % format['frames'][0]
                suggested = meta_batch.frames_per_batch - error
                if error > format['frames'][0] / 2:
                    suggested += format['frames'][0]
                raise RuntimeError(f"The chosen frames per batch is incompatible with the selected format. Try {suggested}")
        if meta_batch.frames_per_batch > max_loadable_frames:
            raise RuntimeError(f"Meta Batch set to {meta_batch.frames_per_batch} frames but only {max_loadable_frames} can fit in memory")
        gen = itertools.islice(gen, meta_batch.frames_per_batch)
    else:
        original_gen = gen
        gen = itertools.islice(gen, max_loadable_frames)
    frames_per_batch = (1920 * 1080 * 16) // (width * height) or 1
    if vae is not None:
        gen = batched_vae_encode(gen, vae, frames_per_batch)
        vw,vh = new_width//downscale_ratio, new_height//downscale_ratio
        channels = getattr(vae, 'latent_channels', 4)
        images = torch.from_numpy(np.fromiter(gen, np.dtype((np.float32, (channels,vh,vw)))))
    else:
        #Some minor wizardry to eliminate a copy and reduce max memory by a factor of ~2
        images = torch.from_numpy(np.fromiter(gen, np.dtype((np.float32, (new_height, new_width, 4 if alpha else 3)))))
    if meta_batch is None and memory_limit is not None:
        try:
            next(original_gen)
            raise RuntimeError(f"Memory limit hit after loading {len(images)} frames. Stopping execution.")
        except StopIteration:
            pass
    if len(images) == 0:
        raise RuntimeError("No frames generated")
    if 'frames' in format and len(images) % format['frames'][0] != format['frames'][1]:
        err_msg = f"The number of frames loaded {len(images)}, does not match the requirements of the currently selected format."
        if len(format['frames']) > 2 and format['frames'][2]:
            raise RuntimeError(err_msg)
        div, mod = format['frames'][:2]
        frames = (len(images) - mod) // div * div + mod
        images = images[:frames]
    if 'start_time' in kwargs:
        start_time = kwargs['start_time']
    else:
        start_time = kwargs['skip_first_frames'] * target_frame_time
    target_frame_time *= kwargs.get('select_every_nth', 1)
    #Setup lambda for lazy audio capture
    audio = _lazy_get_audio(kwargs['video'], start_time, kwargs['frame_load_cap']*target_frame_time)
    #Adjust target_frame_time for select_every_nth
    video_info = {
        "source_fps": fps,
        "source_frame_count": total_frames,
        "source_duration": duration,
        "source_width": width,
        "source_height": height,
        "loaded_fps": 1/target_frame_time,
        "loaded_frame_count": len(images),
        "loaded_duration": len(images) * target_frame_time,
        "loaded_width": new_width,
        "loaded_height": new_height,
    }
    if vae is None:
        return (images, len(images), audio, video_info)
    else:
        return ({"samples": images}, len(images), audio, video_info)


# ============================================================
# XB_VideoLoader
# ============================================================

class XB_VideoLoader:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = []
        for f in os.listdir(input_dir):
            if os.path.isfile(os.path.join(input_dir, f)):
                file_parts = f.split('.')
                if len(file_parts) > 1 and (file_parts[-1].lower() in video_extensions):
                    files.append(f)
        return {"required": {
                    "video": (sorted(files),),
                    "custom_width": ("INT", {"default": 0, "min": 0, "max": DIMMAX}),
                    "custom_height": ("INT", {"default": 0, "min": 0, "max": DIMMAX}),
                    "frame_load_cap": ("INT", {"default": 0, "min": 0, "max": BIGMAX, "step": 1}),
                    "force_rate": ("FLOAT", {"default": 0, "min": 0, "max": 60, "step": 1}),
                    "skip_first_frames": ("INT", {"default": 0, "min": 0, "max": BIGMAX, "step": 1}),
                    "select_every_nth": ("INT", {"default": 1, "min": 1, "max": BIGMAX, "step": 1}),
                    },
                "optional": {
                    "format": get_load_formats(),
                },
                "hidden": {
                    "unique_id": "UNIQUE_ID"
                },
                }

    RETURN_TYPES = ("IMAGE", "INT", "AUDIO", "VHS_VIDEOINFO")
    RETURN_NAMES = ("IMAGE", "frame_count", "audio", "video_info")
    FUNCTION = "load_video"
    CATEGORY = "XB_ToolBox/Video"

    def load_video(self, **kwargs):
        kwargs['video'] = folder_paths.get_annotated_filepath(strip_path(kwargs['video']))
        return load_video(**kwargs)

    @classmethod
    def IS_CHANGED(s, video, **kwargs):
        image_path = folder_paths.get_annotated_filepath(video)
        return calculate_file_hash(image_path)

    @classmethod
    def VALIDATE_INPUTS(s, video):
        if not folder_paths.exists_annotated_filepath(video):
            return "Invalid video file: {}".format(video)
        return True


# ============================================================
# 以下代码搬运自 VHS utils.py 和 nodes.py
# ============================================================

# ffmpeg_path
if "VHS_FORCE_FFMPEG_PATH" in os.environ:
    _ffmpeg = os.environ.get("VHS_FORCE_FFMPEG_PATH")
else:
    _ffmpeg_paths = []
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        _ffmpeg_paths.append(get_ffmpeg_exe())
    except:
        pass
    system_ffmpeg = _shutil.which("ffmpeg")
    if system_ffmpeg:
        _ffmpeg_paths.append(system_ffmpeg)
    if os.path.isfile("ffmpeg"): _ffmpeg_paths.append(os.path.abspath("ffmpeg"))
    if os.path.isfile("ffmpeg.exe"): _ffmpeg_paths.append(os.path.abspath("ffmpeg.exe"))
    _ffmpeg = _ffmpeg_paths[0] if _ffmpeg_paths else None

import json as _json
import datetime as _dt
import sys as _sys
import functools as _functools
from PIL import Image as _PILImage, ExifTags as _ExifTags
from PIL.PngImagePlugin import PngInfo as _PngInfo
from string import Template as _Template

# gifski_path
_gifski_path = os.environ.get("VHS_GIFSKI", None)
if _gifski_path is None:
    _gifski_path = os.environ.get("JOV_GIFSKI", None)
    if _gifski_path is None:
        _gifski_path = _shutil.which("gifski")

def _merge_filter_args(args, ftype="-vf"):
    try:
        start_index = args.index(ftype)+1
        index = start_index
        while True:
            index = args.index(ftype, index)
            args[start_index] += ',' + args[index+1]
            args.pop(index)
            args.pop(index)
    except ValueError:
        pass

def _cached(duration):
    def dec(f):
        cached_ret = None
        cache_time = 0
        def cached_func():
            nonlocal cache_time, cached_ret
            if time.time() > cache_time + duration or cached_ret is None:
                cache_time = time.time()
                cached_ret = f()
            return cached_ret
        return cached_func
    return dec

class _MultiInput(str):
    def __new__(cls, string, allowed_types="*"):
        res = super().__new__(cls, string)
        res.allowed_types=allowed_types
        return res
    def __ne__(self, other):
        if self.allowed_types == "*" or other == "*":
            return False
        return other not in self.allowed_types

_imageOrLatent = _MultiInput("IMAGE", ["IMAGE", "LATENT"])
_floatOrInt = _MultiInput("FLOAT", ["FLOAT", "INT"])

class _ContainsAll(dict):
    def __contains__(self, other):
        return True
    def __getitem__(self, key):
        return super().get(key, (None, {}))

def _flatten_list(l):
    ret = []
    for e in l:
        if isinstance(e, list):
            ret.extend(e)
        else:
            ret.append(e)
    return ret

def _iterate_format(video_format, for_widgets=True):
    def indirector(cont, index):
        if isinstance(cont[index], list) and (not for_widgets
          or len(cont[index])> 1 and not isinstance(cont[index][1], dict)):
            inp = yield cont[index]
            if inp is not None:
                cont[index] = inp
                yield
    for k in video_format:
        if k == "extra_widgets":
            if for_widgets:
                yield from video_format["extra_widgets"]
        elif k.endswith("_pass"):
            for i in range(len(video_format[k])):
                yield from indirector(video_format[k], i)
            if not for_widgets:
                video_format[k] = _flatten_list(video_format[k])
        else:
            yield from indirector(video_format, k)

if 'VHS_video_formats' not in folder_paths.folder_names_and_paths:
    folder_paths.folder_names_and_paths["VHS_video_formats"] = ((),{".json"})
if len(folder_paths.folder_names_and_paths['VHS_video_formats'][1]) == 0:
    folder_paths.folder_names_and_paths["VHS_video_formats"][1].add(".json")

_base_formats_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video_formats")

@_cached(5)
def _get_video_formats():
    format_files = {}
    for format_name in folder_paths.get_filename_list("VHS_video_formats"):
        format_files[format_name] = folder_paths.get_full_path("VHS_video_formats", format_name)
    os.makedirs(_base_formats_dir, exist_ok=True)
    for item in os.scandir(_base_formats_dir):
        if not item.is_file() or not item.name.endswith('.json'):
            continue
        format_files[item.name[:-5]] = item.path
    formats = []
    format_widgets = {}
    for format_name, path in format_files.items():
        with open(path, 'r') as stream:
            video_format = _json.load(stream)
        if "gifski_pass" in video_format and _gifski_path is None:
            continue
        widgets = list(_iterate_format(video_format))
        formats.append("video/" + format_name)
        if (len(widgets) > 0):
            format_widgets["video/"+ format_name] = widgets
    return formats, format_widgets

def _apply_format_widgets(format_name, kwargs):
    if os.path.exists(os.path.join(_base_formats_dir, format_name + ".json")):
        video_format_path = os.path.join(_base_formats_dir, format_name + ".json")
    else:
        video_format_path = folder_paths.get_full_path("VHS_video_formats", format_name)
    with open(video_format_path, 'r') as stream:
        video_format = _json.load(stream)
    for w in _iterate_format(video_format):
        if w[0] not in kwargs:
            if len(w) > 2 and 'default' in w[2]:
                default = w[2]['default']
            else:
                if type(w[1]) is list:
                    default = w[1][0]
                else:
                    default = {"BOOLEAN": False, "INT": 0, "FLOAT": 0, "STRING": ""}[w[1]]
            kwargs[w[0]] = default
    wit = _iterate_format(video_format, False)
    for w in wit:
        while isinstance(w, list):
            if len(w) == 1:
                w = [_Template(x).substitute(**kwargs) for x in w[0]]
                break
            elif isinstance(w[1], dict):
                w = w[1][str(kwargs[w[0]])]
            elif len(w) > 3:
                w = _Template(w[3]).substitute(val=kwargs[w[0]])
            else:
                w = str(kwargs[w[0]])
        wit.send(w)
    return video_format

def _tensor_to_int(tensor, bits):
    tensor = tensor.cpu().numpy() * (2**bits-1) + 0.5
    return np.clip(tensor, 0, (2**bits-1))
def _tensor_to_shorts(tensor):
    return _tensor_to_int(tensor, 16).astype(np.uint16)
def _tensor_to_bytes(tensor):
    return _tensor_to_int(tensor, 8).astype(np.uint8)

def _ffmpeg_process(args, video_format, video_metadata, file_path, env):
    res = None
    frame_data = yield
    total_frames_output = 0
    if video_format.get('save_metadata', 'False') != 'False':
        os.makedirs(folder_paths.get_temp_directory(), exist_ok=True)
        metadata_path = os.path.join(folder_paths.get_temp_directory(), "metadata.txt")
        def escape_ffmpeg_metadata(key, value):
            value = str(value)
            value = value.replace("\\","\\\\")
            value = value.replace(";","\\;")
            value = value.replace("#","\\#")
            value = value.replace("=","\\=")
            value = value.replace("\n","\\\n")
            return f"{key}={value}"
        with open(metadata_path, "w") as f:
            f.write(";FFMETADATA1\n")
            if "prompt" in video_metadata:
                f.write(escape_ffmpeg_metadata("prompt", _json.dumps(video_metadata["prompt"])) + "\n")
            if "workflow" in video_metadata:
                f.write(escape_ffmpeg_metadata("workflow", _json.dumps(video_metadata["workflow"])) + "\n")
            for k, v in video_metadata.items():
                if k not in ["prompt", "workflow"]:
                    f.write(escape_ffmpeg_metadata(k, _json.dumps(v)) + "\n")
        m_args = args[:1] + ["-i", metadata_path] + args[1:] + ["-metadata", "creation_time=now", "-movflags", "use_metadata_tags"]
        with subprocess.Popen(m_args + [file_path], stderr=subprocess.PIPE,
                              stdin=subprocess.PIPE, env=env) as proc:
            try:
                while frame_data is not None:
                    proc.stdin.write(frame_data)
                    frame_data = yield
                    total_frames_output+=1
                proc.stdin.flush()
                proc.stdin.close()
                res = proc.stderr.read()
            except BrokenPipeError as e:
                err = proc.stderr.read()
                if os.path.exists(file_path):
                    raise Exception("An error occurred in the ffmpeg subprocess:\n" + err.decode(*ENCODE_ARGS))
                print(err.decode(*ENCODE_ARGS), end="", file=_sys.stderr)
    if res != b'':
        with subprocess.Popen(args + [file_path], stderr=subprocess.PIPE,
                              stdin=subprocess.PIPE, env=env) as proc:
            try:
                while frame_data is not None:
                    proc.stdin.write(frame_data)
                    frame_data = yield
                    total_frames_output+=1
                proc.stdin.flush()
                proc.stdin.close()
                res = proc.stderr.read()
            except BrokenPipeError as e:
                res = proc.stderr.read()
                raise Exception("An error occurred in the ffmpeg subprocess:\n" + res.decode(*ENCODE_ARGS))
    yield total_frames_output
    if len(res) > 0:
        print(res.decode(*ENCODE_ARGS), end="", file=_sys.stderr)

def _gifski_process(args, dimensions, frame_rate, video_format, file_path, env):
    frame_data = yield
    with subprocess.Popen(args + video_format['main_pass'] + ['-f', 'yuv4mpegpipe', '-'],
                          stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, env=env) as procff:
        with subprocess.Popen([_gifski_path] + video_format['gifski_pass']
                              + ['-W', f'{dimensions[0]}', '-H', f'{dimensions[1]}']
                              + ['-r', f'{frame_rate}']
                              + ['-q', '-o', file_path, '-'], stderr=subprocess.PIPE,
                              stdin=procff.stdout, stdout=subprocess.PIPE,
                              env=env) as procgs:
            try:
                while frame_data is not None:
                    procff.stdin.write(frame_data)
                    frame_data = yield
                procff.stdin.flush()
                procff.stdin.close()
                resff = procff.stderr.read()
                resgs = procgs.stderr.read()
                outgs = procgs.stdout.read()
            except BrokenPipeError as e:
                procff.stdin.close()
                resff = procff.stderr.read()
                resgs = procgs.stderr.read()
                raise Exception("An error occurred while creating gifski output\n"
                        + "Make sure you are using gifski --version >=1.32.0\nffmpeg: "
                        + resff.decode(*ENCODE_ARGS) + '\ngifski: ' + resgs.decode(*ENCODE_ARGS))
    if len(resff) > 0:
        print(resff.decode(*ENCODE_ARGS), end="", file=_sys.stderr)
    if len(resgs) > 0:
        print(resgs.decode(*ENCODE_ARGS), end="", file=_sys.stderr)
    if len(outgs) > 0:
        print(outgs.decode(*ENCODE_ARGS))

def _to_pingpong(inp):
    if not hasattr(inp, "__getitem__"):
        inp = list(inp)
    yield from inp
    for i in range(len(inp)-2,0,-1):
        yield inp[i]


# ============================================================
# XB_VideoCombine — 完整搬运 VHS VideoCombine，完全独立
# ============================================================

class XB_VideoCombine:
    @classmethod
    def INPUT_TYPES(cls):
        ffmpeg_formats, format_widgets = _get_video_formats()
        format_widgets["image/webp"] = [['lossless', "BOOLEAN", {'default': True}]]
        return {
            "required": {
                "images": (_imageOrLatent,),
                "frame_rate": (_floatOrInt, {"default": 8, "min": 1, "step": 1}),
                "loop_count": ("INT", {"default": 0, "min": 0, "max": 100, "step": 1}),
                "filename_prefix": ("STRING", {"default": "视频"}),
                "format": (["image/gif", "image/webp"] + ffmpeg_formats, {'formats': format_widgets}),
                "pingpong": ("BOOLEAN", {"default": False}),
                "save_output": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "audio": ("AUDIO",),
            },
            "hidden": _ContainsAll({
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID"
            }),
        }

    RETURN_TYPES = ("VHS_FILENAMES",)
    RETURN_NAMES = ("Filenames",)
    OUTPUT_NODE = True
    FUNCTION = "combine_video"
    CATEGORY = "XB_ToolBox/Video"

    def combine_video(self, frame_rate, loop_count, images=None, latents=None,
                      filename_prefix="视频", format="image/gif", pingpong=False,
                      save_output=True, prompt=None, extra_pnginfo=None,
                      audio=None, unique_id=None, manual_format_widgets=None, **kwargs):
        if latents is not None:
            images = latents
        if images is None:
            return ((save_output, []),)
        if isinstance(images, torch.Tensor) and images.size(0) == 0:
            return ((save_output, []),)
        num_frames = len(images)
        pbar = ProgressBar(num_frames)
        first_image = images[0]
        while len(first_image.shape) > 3:
            first_image = first_image[0]
        images = iter(images)

        output_dir = folder_paths.get_output_directory() if save_output else folder_paths.get_temp_directory()
        full_output_folder, filename, _, subfolder, _ = folder_paths.get_save_image_path(filename_prefix, output_dir)
        output_files = []

        metadata = _PngInfo()
        video_metadata = {}
        if prompt is not None:
            metadata.add_text("prompt", _json.dumps(prompt))
            video_metadata["prompt"] = prompt
        if extra_pnginfo is not None:
            for x in extra_pnginfo:
                metadata.add_text(x, _json.dumps(extra_pnginfo[x]))
                video_metadata[x] = extra_pnginfo[x]
            extra_options = extra_pnginfo.get('workflow', {}).get('extra', {})
        else:
            extra_options = {}
        metadata.add_text("CreationTime", _dt.datetime.now().isoformat(" ")[:19])

        max_counter = 0
        matcher = re.compile(f"{re.escape(filename)}_(\\d+)\\D*\\..+", re.IGNORECASE)
        for existing_file in os.listdir(full_output_folder):
            match = matcher.fullmatch(existing_file)
            if match:
                max_counter = max(max_counter, int(match.group(1)))
        counter = max_counter + 1

        first_image_file = f"{filename}_{counter:05}.png"
        file_path = os.path.join(full_output_folder, first_image_file)
        if extra_options.get('VHS_MetadataImage', True) != False:
            _PILImage.fromarray(_tensor_to_bytes(first_image)).save(file_path, pnginfo=metadata, compress_level=4)
        output_files.append(file_path)

        format_type, format_ext = format.split("/")
        if format_type == "image":
            image_kwargs = {}
            if format_ext == "gif":
                image_kwargs['disposal'] = 2
            if format_ext == "webp":
                exif = _PILImage.Exif()
                exif[_ExifTags.IFD.Exif] = {36867: _dt.datetime.now().isoformat(" ")[:19]}
                image_kwargs['exif'] = exif
                image_kwargs['lossless'] = kwargs.get("lossless", True)
            file = f"{filename}_{counter:05}.{format_ext}"
            file_path = os.path.join(full_output_folder, file)
            if pingpong:
                images = _to_pingpong(images)
            def frames_gen(images):
                for i in images:
                    pbar.update(1)
                    yield _PILImage.fromarray(_tensor_to_bytes(i))
            frames = frames_gen(images)
            next(frames).save(file_path, format=format_ext.upper(), save_all=True,
                              append_images=frames, duration=round(1000/frame_rate),
                              loop=loop_count, compress_level=4, **image_kwargs)
            output_files.append(file_path)
        else:
            if _ffmpeg is None:
                raise RuntimeError("ffmpeg 未找到")

            if manual_format_widgets is not None:
                kwargs.update(manual_format_widgets)

            has_alpha = first_image.shape[-1] == 4
            kwargs["has_alpha"] = has_alpha
            video_format = _apply_format_widgets(format_ext, kwargs)
            dim_alignment = video_format.get("dim_alignment", 2)
            if (first_image.shape[1] % dim_alignment) or (first_image.shape[0] % dim_alignment):
                to_pad = (-first_image.shape[1] % dim_alignment, -first_image.shape[0] % dim_alignment)
                padding = (to_pad[0]//2, to_pad[0] - to_pad[0]//2, to_pad[1]//2, to_pad[1] - to_pad[1]//2)
                padfunc = torch.nn.ReplicationPad2d(padding)
                def pad(image):
                    image = image.permute((2,0,1))
                    padded = padfunc(image.to(dtype=torch.float32))
                    return padded.permute((1,2,0))
                images = map(pad, images)
                dimensions = (-first_image.shape[1] % dim_alignment + first_image.shape[1],
                              -first_image.shape[0] % dim_alignment + first_image.shape[0])
            else:
                dimensions = (first_image.shape[1], first_image.shape[0])
            if pingpong:
                images = _to_pingpong(images)
                if num_frames > 2:
                    num_frames += num_frames -2
                    pbar.total = num_frames
            if loop_count > 0:
                loop_args = ["-vf", "loop=loop=" + str(loop_count)+":size=" + str(num_frames)]
            else:
                loop_args = []
            if video_format.get('input_color_depth', '8bit') == '16bit':
                images = map(_tensor_to_shorts, images)
                i_pix_fmt = 'rgba64' if has_alpha else 'rgb48'
            else:
                images = map(_tensor_to_bytes, images)
                i_pix_fmt = 'rgba' if has_alpha else 'rgb24'
            file = f"{filename}_{counter:05}.{video_format['extension']}"
            file_path = os.path.join(full_output_folder, file)
            bitrate_arg = []
            bitrate = video_format.get('bitrate')
            if bitrate is not None:
                bitrate_arg = ["-b:v", str(bitrate) + "M" if video_format.get('megabit') == 'True' else str(bitrate) + "K"]
            args = [_ffmpeg, "-v", "error", "-f", "rawvideo", "-pix_fmt", i_pix_fmt,
                    "-color_range", "pc", "-colorspace", "rgb", "-color_primaries", "bt709",
                    "-color_trc", video_format.get("fake_trc", "iec61966-2-1"),
                    "-s", f"{dimensions[0]}x{dimensions[1]}", "-r", str(frame_rate), "-i", "-"] + loop_args

            images = map(lambda x: x.tobytes(), images)
            env = os.environ.copy()
            if "environment" in video_format:
                env.update(video_format["environment"])

            if "pre_pass" in video_format:
                images = [b''.join(images)]
                os.makedirs(folder_paths.get_temp_directory(), exist_ok=True)
                in_args_len = args.index("-i") + 2
                pre_pass_args = args[:in_args_len] + video_format['pre_pass']
                _merge_filter_args(pre_pass_args)
                try:
                    subprocess.run(pre_pass_args, input=images[0], env=env, capture_output=True, check=True)
                except subprocess.CalledProcessError as e:
                    raise Exception("An error occurred in the ffmpeg prepass:\n" + e.stderr.decode(*ENCODE_ARGS))
            if "inputs_main_pass" in video_format:
                in_args_len = args.index("-i") + 2
                args = args[:in_args_len] + video_format['inputs_main_pass'] + args[in_args_len:]

            if 'gifski_pass' in video_format:
                format = 'image/gif'
                output_process = _gifski_process(args, dimensions, frame_rate, video_format, file_path, env)
                audio = None
            else:
                args += video_format['main_pass'] + bitrate_arg
                _merge_filter_args(args)
                output_process = _ffmpeg_process(args, video_format, video_metadata, file_path, env)
            output_process.send(None)

            for image in images:
                pbar.update(1)
                output_process.send(image)
            try:
                total_frames_output = output_process.send(None)
                output_process.send(None)
            except StopIteration:
                pass
            output_files.append(file_path)

            a_waveform = None
            if audio is not None:
                try:
                    a_waveform = audio['waveform']
                except:
                    pass
            if a_waveform is not None:
                output_file_with_audio = f"{filename}_{counter:05}-audio.{video_format['extension']}"
                output_file_with_audio_path = os.path.join(full_output_folder, output_file_with_audio)
                if "audio_pass" not in video_format:
                    video_format["audio_pass"] = ["-c:a", "libopus"]
                channels = audio['waveform'].size(1)
                min_audio_dur = total_frames_output / frame_rate + 1
                if video_format.get('trim_to_audio', 'False') != 'False':
                    apad = []
                else:
                    apad = ["-af", "apad=whole_dur="+str(min_audio_dur)]
                mux_args = [_ffmpeg, "-v", "error", "-n", "-i", file_path,
                            "-ar", str(audio['sample_rate']), "-ac", str(channels),
                            "-f", "f32le", "-i", "-", "-c:v", "copy"] \
                            + video_format["audio_pass"] + apad + ["-shortest", output_file_with_audio_path]
                audio_data = audio['waveform'].squeeze(0).transpose(0,1).numpy().tobytes()
                _merge_filter_args(mux_args, '-af')
                try:
                    res = subprocess.run(mux_args, input=audio_data, env=env, capture_output=True, check=True)
                except subprocess.CalledProcessError as e:
                    raise Exception("An error occured in the ffmpeg subprocess:\n" + e.stderr.decode(*ENCODE_ARGS))
                output_files.append(output_file_with_audio_path)
                file = output_file_with_audio
        if extra_options.get('VHS_KeepIntermediate', True) == False:
            for intermediate in output_files[1:-1]:
                if os.path.exists(intermediate):
                    os.remove(intermediate)
        preview = {
            "filename": file,
            "subfolder": subfolder,
            "type": "output" if save_output else "temp",
            "format": format,
            "frame_rate": frame_rate,
            "workflow": first_image_file,
            "fullpath": output_files[-1],
        }
        if num_frames == 1 and 'png' in format and '%03d' in file:
            preview['format'] = 'image/png'
            preview['filename'] = file.replace('%03d', '001')
        return {"ui": {"gifs": [preview]}, "result": ((save_output, output_files),)}