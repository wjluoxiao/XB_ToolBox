"""
XB CosyVoice3 Zero-Shot Voice Cloning Node
Clone any voice from a reference audio sample
"""

import torch
import random
from typing import Tuple, Dict, Any, Optional
import sys
import os

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from ..utils.audio_utils import tensor_to_comfyui_audio, save_raw_audio_to_tempfile, cleanup_temp_file
except (ImportError, ValueError):
    from utils.audio_utils import tensor_to_comfyui_audio, save_raw_audio_to_tempfile, cleanup_temp_file

# ComfyUI progress bar
import comfy.utils

# Import language detection utility
import re
_chinese_char_pattern = re.compile(r'[\u4e00-\u9fff]+')

def contains_chinese(text):
    """Check if text contains Chinese characters"""
    return bool(_chinese_char_pattern.search(text))

# Whisper model cache for auto-transcription
_whisper_model = None

def _ensure_ffmpeg():
    """确保 ffmpeg 可用。返回 ffmpeg 绝对路径，供 Whisper 使用。"""
    import shutil, subprocess
    candidates = []
    # 1. 从 PATH 中找
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    # 2. imageio-ffmpeg 内置便携版
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(exe) and exe not in candidates:
            candidates.append(exe)
    except Exception:
        pass
    # 3. 验证并返回第一个可用的
    for exe in candidates:
        try:
            subprocess.run([exe, "-version"], capture_output=True, timeout=5, check=True)
            print(f"[XB CosyVoice3 ZeroShot] ffmpeg ready: {exe}")
            return exe
        except Exception:
            continue
    return None

# 全局缓存 ffmpeg 路径
_ffmpeg_path = None

def _get_ffmpeg():
    global _ffmpeg_path
    if _ffmpeg_path is None:
        _ffmpeg_path = _ensure_ffmpeg()
    return _ffmpeg_path

# Monkey-patch whisper 让它用我们的 ffmpeg
_original_transcribe = None

def _patch_whisper():
    """让 whisper 使用我们找到的 ffmpeg 绝对路径。"""
    global _original_transcribe
    ffmpeg = _get_ffmpeg()
    if not ffmpeg:
        return  # 没有 ffmpeg，走降级逻辑
    import whisper.audio
    import subprocess
    # 替换 whisper 的 subprocess 调用
    _original_popen = subprocess.Popen
    class _FfmpegPopen(subprocess.Popen):
        def __init__(self, args, **kwargs):
            if isinstance(args, list) and args[0] == "ffmpeg":
                args = [ffmpeg] + args[1:]
            elif isinstance(args, str) and args.startswith("ffmpeg"):
                args = ffmpeg + args[5:]
            super().__init__(args, **kwargs)
    subprocess.Popen = _FfmpegPopen
    print(f"[XB CosyVoice3 ZeroShot] Whisper patched to use: {ffmpeg}")

def get_whisper_model():
    """Get cached Whisper model for transcription"""
    global _whisper_model
    if _whisper_model is None:
        try:
            _patch_whisper()
            import whisper
            print("[XB CosyVoice3 ZeroShot] Loading Whisper model for auto-transcription...")
            _whisper_model = whisper.load_model("base")
            print("[XB CosyVoice3 ZeroShot] Whisper model loaded successfully")
        except Exception as e:
            print(f"[XB CosyVoice3 ZeroShot] Failed to load Whisper: {e}")
            return None
    return _whisper_model

def transcribe_audio(audio_path: str) -> str:
    """
    Auto-transcribe audio using Whisper when no reference text is provided.

    Args:
        audio_path: Path to the audio file to transcribe

    Returns:
        Transcribed text, or empty string if transcription fails
    """
    try:
        model = get_whisper_model()
        if model is None:
            return ""

        result = model.transcribe(audio_path, language=None)  # Auto-detect language
        transcript = result["text"].strip()
        detected_lang = result.get("language", "unknown")
        print(f"[XB CosyVoice3 ZeroShot] Whisper detected language: {detected_lang}")
        return transcript
    except Exception as e:
        print(f"[XB CosyVoice3 ZeroShot] Whisper transcription failed: {e}")
        return ""

def is_cosyvoice3_model(model_info: Dict[str, Any]) -> bool:
    """Check if the loaded model is CosyVoice3"""
    version = model_info.get("model_version", "").lower()
    return "cosyvoice3" in version or "fun-cosyvoice3" in version


class XB_CosyVoice3_ZeroShot:
    """
    Zero-shot voice cloning from reference audio
    """

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "clone_voice"
    CATEGORY = "🔊XB CosyVoice3/Synthesis"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("COSYVOICE_MODEL", {
                    "description": "CosyVoice model from ModelLoader"
                }),
                "text": ("STRING", {
                    "default": "Hello, this is my cloned voice speaking.",
                    "multiline": True,
                    "description": "Text to synthesize in cloned voice"
                }),
                "reference_audio": ("AUDIO", {
                    "description": "Reference voice to clone (max 30 seconds, recommended 3-10s)"
                }),
                "speed": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.5,
                    "max": 2.0,
                    "step": 0.05,
                    "description": "Speech speed multiplier"
                }),
            },
            "optional": {
                "seed": ("INT", {
                    "default": 42,
                    "min": -1,
                    "max": 2147483647,
                    "description": "Random seed (-1 for random)"
                }),
                "text_frontend": ("BOOLEAN", {
                    "default": True,
                    "description": "Enable text normalization. Disable for CMU phonemes or special tags like <slow>"
                }),
            }
        }

    def clone_voice(
        self,
        model: Dict[str, Any],
        text: str,
        reference_audio: Dict[str, Any],
        speed: float = 1.0,
        seed: int = -1,
        text_frontend: bool = True
    ) -> Tuple[Dict[str, Any]]:
        """
        Clone voice from reference audio

        Args:
            model: CosyVoice model info dict
            text: Text to synthesize
            reference_audio: Reference audio for voice cloning
            speed: Speech speed
            seed: Random seed

        Returns:
            Tuple containing audio dict
        """
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 ZeroShot] Cloning voice...")
        print(f"[XB CosyVoice3 ZeroShot] Text: {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"[XB CosyVoice3 ZeroShot] Speed: {speed}x")
        print(f"{'='*60}\n")

        # Check audio duration BEFORE try block so error propagates to ComfyUI
        ref_waveform = reference_audio['waveform']
        ref_sample_rate = reference_audio['sample_rate']
        ref_duration = ref_waveform.shape[-1] / ref_sample_rate

        if ref_duration > 30:
            error_msg = (
                f"Reference audio is too long ({ref_duration:.1f} seconds). "
                f"CosyVoice only supports reference audio up to 30 seconds for voice cloning. "
                f"Please use the XB Audio Crop node to trim your audio to 30 seconds or less. "
                f"Recommended: 3-10 seconds for best quality."
            )
            raise ValueError(error_msg)

        temp_file = None

        try:
            # Set seed if specified
            if seed >= 0:
                torch.manual_seed(seed)
                random.seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)

            # Get model instance
            cosyvoice_model = model["model"]
            sample_rate = cosyvoice_model.sample_rate  # Use actual model sample rate (24000 for v2/v3)

            # Prepare reference audio
            print(f"[XB CosyVoice3 ZeroShot] Preparing reference audio...")
            print(f"[XB CosyVoice3 ZeroShot] Model sample rate: {sample_rate} Hz")
            print(f"[XB CosyVoice3 ZeroShot] Reference audio duration: {ref_duration:.1f}s (max 30s)")

            # Save audio directly WITHOUT preprocessing - CosyVoice's load_wav() handles mono/resampling
            temp_file = save_raw_audio_to_tempfile(reference_audio)
            print(f"[XB CosyVoice3 ZeroShot] Saved reference audio to temp file")

            # Detect model version for proper formatting (use cached flag or detect from version string)
            is_v3 = model.get("is_cosyvoice3", False) or is_cosyvoice3_model(model)

            # Initialize progress bar - 4 steps: transcribe, prepare, inference, finalize
            pbar = comfy.utils.ProgressBar(4)

            # Step 1: Auto-transcribe using Whisper
            print(f"[XB CosyVoice3 ZeroShot] Auto-transcribing reference audio with Whisper...")
            pbar.update_absolute(0, 4)

            transcript = transcribe_audio(temp_file)
            use_cross_lingual_fallback = False

            if transcript:
                print(f"[XB CosyVoice3 ZeroShot] Transcribed: '{transcript[:100]}{'...' if len(transcript) > 100 else ''}'")
            else:
                print(f"[XB CosyVoice3 ZeroShot] WARNING: Transcription failed or empty audio.")
                print(f"[XB CosyVoice3 ZeroShot] Falling back to cross-lingual mode (voice cloning without transcript)...")
                use_cross_lingual_fallback = True

            pbar.update_absolute(1, 4)

            # Step 2: Format prompt text based on model version
            pbar.update_absolute(1, 4)

            if is_v3:
                # CosyVoice3 format: system_prompt<|endofprompt|>transcript
                if transcript and not use_cross_lingual_fallback:
                    formatted_prompt_text = f"You are a helpful assistant.<|endofprompt|>{transcript}"
                else:
                    formatted_prompt_text = None  # Signal to use cross-lingual
            else:
                # CosyVoice v1/v2 format: just the reference text, no system prompt
                formatted_prompt_text = transcript if transcript else None

            pbar.update_absolute(2, 4)

            # Step 3: Generate speech
            pbar.update_absolute(2, 4)

            if use_cross_lingual_fallback or formatted_prompt_text is None:
                # Use cross-lingual as fallback (extracts voice without needing transcript)
                print(f"[XB CosyVoice3 ZeroShot] Using cross-lingual mode (no transcript required)...")

                # For CosyVoice3 cross-lingual, add system prompt to tts_text
                if is_v3:
                    formatted_tts_text = f"You are a helpful assistant.<|endofprompt|>{text}"
                else:
                    formatted_tts_text = text

                output = cosyvoice_model.inference_cross_lingual(
                    tts_text=formatted_tts_text,
                    prompt_wav=temp_file,
                    stream=False,
                    speed=speed,
                    text_frontend=text_frontend
                )
            else:
                # Use standard zero-shot with transcript
                print(f"[XB CosyVoice3 ZeroShot] Running zero-shot inference...")

                output = cosyvoice_model.inference_zero_shot(
                    tts_text=text,
                    prompt_text=formatted_prompt_text,
                    prompt_wav=temp_file,
                    stream=False,
                    speed=speed,
                    text_frontend=text_frontend
                )

            # Collect all output chunks (for longer text that gets split)
            all_speech = []
            chunk_count = 0
            for chunk in output:
                chunk_count += 1
                all_speech.append(chunk['tts_speech'])
                print(f"[XB CosyVoice3 ZeroShot] Processed chunk {chunk_count}")

            # Concatenate all chunks
            if len(all_speech) > 1:
                waveform = torch.cat(all_speech, dim=-1)
                print(f"[XB CosyVoice3 ZeroShot] Combined {len(all_speech)} chunks")
            else:
                waveform = all_speech[0]

            pbar.update_absolute(3, 4)

            # Ensure waveform is on CPU
            if waveform.device != torch.device('cpu'):
                waveform = waveform.cpu()

            # Step 4: Finalize
            pbar.update_absolute(3, 4)

            # Convert to ComfyUI AUDIO format
            audio = tensor_to_comfyui_audio(waveform, sample_rate)

            duration = waveform.shape[-1] / sample_rate

            pbar.update_absolute(4, 4)

            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 ZeroShot] Voice cloned successfully!")
            print(f"[XB CosyVoice3 ZeroShot] Duration: {duration:.2f} seconds")
            print(f"[XB CosyVoice3 ZeroShot] Sample rate: {sample_rate} Hz")
            print(f"{'='*60}\n")

            return (audio,)

        except Exception as e:
            error_msg = f"Error cloning voice: {str(e)}"
            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 ZeroShot] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")

            # Return empty audio on error
            empty_audio = {
                "waveform": torch.zeros(1, 1, 22050),
                "sample_rate": 22050
            }
            return (empty_audio,)

        finally:
            # Clean up temp file
            cleanup_temp_file(temp_file)
