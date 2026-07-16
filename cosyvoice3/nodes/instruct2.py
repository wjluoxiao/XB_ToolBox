"""
XB CosyVoice3 Instruct2 Node
Zero-shot voice cloning with instruct text to control speaking style and tone
"""

import torch
import random
from typing import Tuple, Dict, Any
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
            print(f"[XB CosyVoice3 Instruct2] ffmpeg ready: {exe}")
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
    print(f"[XB CosyVoice3 Instruct2] Whisper patched to use: {ffmpeg}")

def get_whisper_model():
    """Get cached Whisper model for transcription"""
    global _whisper_model
    if _whisper_model is None:
        try:
            _patch_whisper()
            import whisper
            print("[XB CosyVoice3 Instruct2] Loading Whisper model for auto-transcription...")
            _whisper_model = whisper.load_model("base")
            print("[XB CosyVoice3 Instruct2] Whisper model loaded successfully")
        except Exception as e:
            print(f"[XB CosyVoice3 Instruct2] Failed to load Whisper: {e}")
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
        print(f"[XB CosyVoice3 Instruct2] Whisper detected language: {detected_lang}")
        return transcript
    except Exception as e:
        print(f"[XB CosyVoice3 Instruct2] Whisper transcription failed: {e}")
        return ""

def is_cosyvoice3_model(model_info: Dict[str, Any]) -> bool:
    """Check if the loaded model is CosyVoice3"""
    version = model_info.get("model_version", "").lower()
    return "cosyvoice3" in version or "fun-cosyvoice3" in version


class XB_CosyVoice3_Instruct2:
    """
    Instruct-based TTS with zero-shot voice cloning.
    Clone a reference voice and control speaking style/tone using instruct text.
    Uses CosyVoice3's inference_instruct2 to apply emotional and stylistic instructions.
    """

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "generate_with_instruct"
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
                "instruct_text": ("STRING", {
                    "default": "Speak in a warm and friendly tone.",
                    "multiline": True,
                    "description": "Instructions to control speaking style, emotion, and tone. "
                                   "Examples: 'Speak slowly and gently', "
                                   "'Use an excited and energetic tone', "
                                   "'Sound calm and professional'."
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

    def generate_with_instruct(
        self,
        model: Dict[str, Any],
        text: str,
        instruct_text: str,
        reference_audio: Dict[str, Any],
        speed: float = 1.0,
        seed: int = -1,
        text_frontend: bool = True
    ) -> Tuple[Dict[str, Any]]:
        """
        Generate speech with instruct-based style control and voice cloning.

        Args:
            model: CosyVoice model info dict
            text: Text to synthesize
            instruct_text: Instructions for speaking style and tone
            reference_audio: Reference audio for voice cloning
            speed: Speech speed
            seed: Random seed
            text_frontend: Enable text normalization

        Returns:
            Tuple containing audio dict
        """
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 Instruct2] Generating instructed speech...")
        print(f"[XB CosyVoice3 Instruct2] Text: {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"[XB CosyVoice3 Instruct2] Instruct: {instruct_text[:80]}{'...' if len(instruct_text) > 80 else ''}")
        print(f"[XB CosyVoice3 Instruct2] Speed: {speed}x")
        print(f"{'='*60}\n")

        # Validate inputs
        if not instruct_text or not instruct_text.strip():
            raise ValueError(
                "instruct_text cannot be empty. Please provide style instructions, "
                "e.g. 'Speak in a warm, friendly tone' or '用温柔的语气说话'."
            )

        # Check audio duration BEFORE try block so error propagates to ComfyUI
        ref_waveform = reference_audio['waveform']
        ref_sample_rate = reference_audio['sample_rate']
        ref_duration = ref_waveform.shape[-1] / ref_sample_rate

        if ref_duration > 30:
            error_msg = (
                f"Reference audio is too long ({ref_duration:.1f} seconds). "
                f"CosyVoice only supports reference audio up to 30 seconds. "
                f"Please use the XB Audio Crop node to trim to 30 seconds or less. "
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
            sample_rate = cosyvoice_model.sample_rate

            # Detect model version
            is_v3 = model.get("is_cosyvoice3", False) or is_cosyvoice3_model(model)

            print(f"[XB CosyVoice3 Instruct2] Model sample rate: {sample_rate} Hz")
            print(f"[XB CosyVoice3 Instruct2] Is CosyVoice3: {is_v3}")
            print(f"[XB CosyVoice3 Instruct2] Reference audio duration: {ref_duration:.1f}s")

            # Check that inference_instruct2 is available (CosyVoice2 / CosyVoice3 only)
            if not hasattr(cosyvoice_model, 'inference_instruct2'):
                raise RuntimeError(
                    "inference_instruct2 is not available on this model. "
                    "The Instruct node requires a CosyVoice2 or CosyVoice3 model. "
                    "Please load a compatible model in the Model Loader."
                )

            # Initialize progress bar: transcribe, prepare, inference, finalize
            pbar = comfy.utils.ProgressBar(4)

            # Step 1: Save reference audio to temp file
            print(f"[XB CosyVoice3 Instruct2] Saving reference audio...")
            pbar.update_absolute(0, 4)
            temp_file = save_raw_audio_to_tempfile(reference_audio)

            # Step 2: Build instruct text
            # For CosyVoice3, the instruct_text is passed directly; the model handles formatting.
            # We optionally prepend a system prompt consistent with the v3 format used in zero_shot.
            pbar.update_absolute(1, 4)

            # Format instruct_text based on model version.
            # CosyVoice3 requires:  "You are a helpful assistant.\n<instruct><|endofprompt|>"
            # CosyVoice2 requires:  "<instruct><|endofprompt|>"  (no system prompt prefix)
            # We handle all formatting automatically so users only need to type their instruction.
            SYSTEM_PROMPT = "You are a helpful assistant."
            ENDOFPROMPT = "<|endofprompt|>"
            raw_instruct = instruct_text.strip()
            # Strip any pre-existing wrapper that the user may have typed manually
            if raw_instruct.startswith(SYSTEM_PROMPT):
                raw_instruct = raw_instruct[len(SYSTEM_PROMPT):].lstrip("\n")
            if raw_instruct.endswith(ENDOFPROMPT):
                raw_instruct = raw_instruct[:-len(ENDOFPROMPT)].rstrip()
            if is_v3:
                # CosyVoice3: prepend system prompt and append <|endofprompt|>
                formatted_instruct = SYSTEM_PROMPT + "\n" + raw_instruct + ENDOFPROMPT
                print(f"[XB CosyVoice3 Instruct2] Using CosyVoice3 instruct mode")
                print(f"[XB CosyVoice3 Instruct2] Formatted instruct: {formatted_instruct[:100]}")
            else:
                # CosyVoice2: only append <|endofprompt|>, no system prompt
                formatted_instruct = f"{raw_instruct}{ENDOFPROMPT}"
                print(f"[XB CosyVoice3 Instruct2] Using CosyVoice2 instruct mode")
                print(f"[XB CosyVoice3 Instruct2] Formatted instruct: {formatted_instruct[:100]}")

            pbar.update_absolute(2, 4)

            # Step 3: Run inference_instruct2
            # inference_instruct2(tts_text, instruct_text, prompt_wav, zero_shot_spk_id, stream, speed, text_frontend)
            print(f"[XB CosyVoice3 Instruct2] Running instruct inference...")

            output = cosyvoice_model.inference_instruct2(
                tts_text=text,
                instruct_text=formatted_instruct,
                prompt_wav=temp_file,
                zero_shot_spk_id='',
                stream=False,
                speed=speed,
                text_frontend=text_frontend
            )

            # Collect all output chunks
            all_speech = []
            chunk_count = 0
            for chunk in output:
                chunk_count += 1
                all_speech.append(chunk['tts_speech'])
                print(f"[XB CosyVoice3 Instruct2] Processed chunk {chunk_count}")

            if not all_speech:
                raise RuntimeError("No audio was generated. Check model and inputs.")

            # Concatenate all chunks
            if len(all_speech) > 1:
                waveform = torch.cat(all_speech, dim=-1)
                print(f"[XB CosyVoice3 Instruct2] Combined {len(all_speech)} chunks")
            else:
                waveform = all_speech[0]

            pbar.update_absolute(3, 4)

            # Ensure waveform is on CPU
            if waveform.device != torch.device('cpu'):
                waveform = waveform.cpu()

            # Step 4: Convert to ComfyUI AUDIO format
            audio = tensor_to_comfyui_audio(waveform, sample_rate)
            duration = waveform.shape[-1] / sample_rate

            pbar.update_absolute(4, 4)

            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 Instruct2] Speech generated successfully!")
            print(f"[XB CosyVoice3 Instruct2] Duration: {duration:.2f} seconds")
            print(f"[XB CosyVoice3 Instruct2] Sample rate: {sample_rate} Hz")
            print(f"{'='*60}\n")

            return (audio,)

        except Exception as e:
            error_msg = f"Error generating instructed speech: {str(e)}"
            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 Instruct2] ERROR: {error_msg}")
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
