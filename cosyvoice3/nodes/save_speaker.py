"""
XB CosyVoice3 Save Speaker Node
Extract zero-shot speaker features from reference audio and save as a
CosyVoice-compatible spk2info .pt file for reuse without re-uploading audio.
"""

import torch
import os
import sys
from typing import Tuple, Dict, Any

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from ..utils.audio_utils import save_raw_audio_to_tempfile, cleanup_temp_file
except (ImportError, ValueError):
    from utils.audio_utils import save_raw_audio_to_tempfile, cleanup_temp_file

import comfy.utils
import folder_paths


def get_speaker_save_dir() -> str:
    """
    Return the path: <ComfyUI models dir>/cosyvoice/speaker/
    Creates the directory (and parents) if it does not exist.
    """
    speaker_dir = os.path.join(folder_paths.models_dir, "cosyvoice", "speaker")
    os.makedirs(speaker_dir, exist_ok=True)
    return speaker_dir


# Whisper model cache for auto-transcription
_whisper_model = None

def _ensure_ffmpeg():
    """确保 ffmpeg 可用。返回 ffmpeg 绝对路径。"""
    import shutil, subprocess
    candidates = []
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(exe) and exe not in candidates:
            candidates.append(exe)
    except Exception:
        pass
    for exe in candidates:
        try:
            subprocess.run([exe, "-version"], capture_output=True, timeout=5, check=True)
            print(f"[XB CosyVoice3 SaveSpeaker] ffmpeg ready: {exe}")
            return exe
        except Exception:
            continue
    return None

_ffmpeg_path = None

def _get_ffmpeg():
    global _ffmpeg_path
    if _ffmpeg_path is None:
        _ffmpeg_path = _ensure_ffmpeg()
    return _ffmpeg_path

def _patch_whisper():
    ffmpeg = _get_ffmpeg()
    if not ffmpeg:
        return
    import subprocess
    _original_popen = subprocess.Popen
    class _FfmpegPopen(subprocess.Popen):
        def __init__(self, args, **kwargs):
            if isinstance(args, list) and args[0] == "ffmpeg":
                args = [ffmpeg] + args[1:]
            elif isinstance(args, str) and args.startswith("ffmpeg"):
                args = ffmpeg + args[5:]
            super().__init__(args, **kwargs)
    subprocess.Popen = _FfmpegPopen
    print(f"[XB CosyVoice3 SaveSpeaker] Whisper patched to use: {ffmpeg}")

def get_whisper_model():
    """Get cached Whisper model for transcription"""
    global _whisper_model
    if _whisper_model is None:
        try:
            _patch_whisper()
            import whisper
            print("[XB CosyVoice3 SaveSpeaker] Loading Whisper model for auto-transcription...")
            _whisper_model = whisper.load_model("base")
            print("[XB CosyVoice3 SaveSpeaker] Whisper model loaded successfully")
        except Exception as e:
            print(f"[XB CosyVoice3 SaveSpeaker] Failed to load Whisper: {e}")
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
        print(f"[XB CosyVoice3 SaveSpeaker] Whisper detected language: {detected_lang}")
        return transcript
    except Exception as e:
        print(f"[XB CosyVoice3 SaveSpeaker] Whisper transcription failed: {e}")
        return ""


class XB_CosyVoice3_SaveSpeaker:
    """
    Extract zero-shot speaker features from a reference audio clip and save
    them as a CosyVoice spk2info-compatible .pt file.

    Uses the official frontend_zero_shot method (same as add_zero_shot_spk)
    to build the feature dict, then saves it for later reuse by
    XB CosyVoice3 Speaker Clone.
    """

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_path",)
    FUNCTION = "save_speaker"
    CATEGORY = "🔊XB CosyVoice3/Utilities"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("COSYVOICE_MODEL", {
                    "description": "CosyVoice model from Model Loader"
                }),
                "reference_audio": ("AUDIO", {
                    "description": "Reference audio to extract speaker features from "
                                   "(max 30 seconds, recommended 3-10s)"
                }),
                "reference_text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "description": "Transcript of the reference audio."
                }),
                "speaker_name": ("STRING", {
                    "default": "my_speaker",
                    "multiline": False,
                    "description": "Name for this speaker preset (no file extension). "
                                   "Used as the key inside the .pt file and as the filename."
                }),
            }
        }

    def save_speaker(
        self,
        model: Dict[str, Any],
        reference_audio: Dict[str, Any],
        reference_text: str,
        speaker_name: str,
    ) -> Tuple[str]:
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 SaveSpeaker] Extracting speaker features...")
        print(f"[XB CosyVoice3 SaveSpeaker] Speaker name  : {speaker_name}")
        print(f"[XB CosyVoice3 SaveSpeaker] Reference text: {reference_text[:60]}{'...' if len(reference_text) > 60 else ''}")
        print(f"{'='*60}\n")

        speaker_name = speaker_name.strip()
        if not speaker_name:
            raise ValueError("speaker_name cannot be empty.")

        temp_file = None

        try:
            pbar = comfy.utils.ProgressBar(3)

            # Step 1: Save reference audio to temp wav file
            print(f"[XB CosyVoice3 SaveSpeaker] Saving reference audio to temp file...")
            pbar.update_absolute(0, 3)
            temp_file = save_raw_audio_to_tempfile(reference_audio)

            # Step 2: Use official frontend_zero_shot to extract all features at once
            # This mirrors the official add_zero_shot_spk method in cosyvoice.py
            print(f"[XB CosyVoice3 SaveSpeaker] Extracting features via frontend_zero_shot...")
            pbar.update_absolute(1, 3)

            cosyvoice_model = model["model"]

            # Auto-transcribe reference audio if reference_text is not provided
            if not reference_text.strip():
                print(f"[XB CosyVoice3 SaveSpeaker] No reference_text provided, auto-transcribing with Whisper...")
                reference_text = transcribe_audio(temp_file)
                if reference_text:
                    print(f"[XB CosyVoice3 SaveSpeaker] Transcribed: '{reference_text[:80]}{'...' if len(reference_text) > 80 else ''}'")
                else:
                    print(f"[XB CosyVoice3 SaveSpeaker] WARNING: Transcription failed, using empty reference_text")

            # CosyVoice3 requires prompt_text to be prefixed with the system prompt,
            # matching the official example: 'You are a helpful assistant.<|endofprompt|><reference_text>'
            version = model.get("model_version", "").lower()
            is_v3 = "cosyvoice3" in version or "fun-cosyvoice3" in version
            if is_v3:
                prompt_text = f"You are a helpful assistant.<|endofprompt|>{reference_text}"
                print(f"[XB CosyVoice3 SaveSpeaker] CosyVoice3 detected: prepended system prompt to prompt_text")
            else:
                prompt_text = reference_text
                print(f"[XB CosyVoice3 SaveSpeaker] CosyVoice2/1 detected: using reference_text as-is")

            model_input = cosyvoice_model.frontend.frontend_zero_shot(
                '', prompt_text, temp_file, cosyvoice_model.sample_rate, ''
            )
            # Remove tts_text fields — they belong to synthesis time, not the speaker preset
            del model_input['text']
            del model_input['text_len']

            # Move all tensors to CPU for portability
            spk2info = {speaker_name: model_input}

            # Step 3: Save to disk
            pbar.update_absolute(2, 3)
            save_dir = get_speaker_save_dir()
            save_path = os.path.join(save_dir, f"{speaker_name}.pt")
            torch.save(spk2info, save_path)

            pbar.update_absolute(3, 3)

            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 SaveSpeaker] Saved successfully!")
            print(f"[XB CosyVoice3 SaveSpeaker] Path        : {save_path}")
            print(f"[XB CosyVoice3 SaveSpeaker] Speaker key : '{speaker_name}'")
            print(f"[XB CosyVoice3 SaveSpeaker] Keys saved  : {list(spk2info[speaker_name].keys())}")
            print(f"{'='*60}\n")

            return (save_path,)

        except Exception as e:
            error_msg = f"保存说话人失败: {str(e)}"
            print(f"[XB CosyVoice3 SaveSpeaker] [!] {error_msg}")
            raise RuntimeError(error_msg)

        finally:
            cleanup_temp_file(temp_file)
