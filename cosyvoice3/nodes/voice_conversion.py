"""
XB CosyVoice3 Voice Conversion Node
Convert one voice to sound like another (voice-to-voice)
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
    from ..utils.audio_utils import tensor_to_comfyui_audio, prepare_audio_for_cosyvoice, cleanup_temp_file
except (ImportError, ValueError):
    from utils.audio_utils import tensor_to_comfyui_audio, prepare_audio_for_cosyvoice, cleanup_temp_file

# ComfyUI progress bar
import comfy.utils


class XB_CosyVoice3_VoiceConversion:
    """
    Voice conversion - convert source voice to target voice
    """

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "convert_voice"
    CATEGORY = "🔊XB CosyVoice3/Synthesis"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("COSYVOICE_MODEL", {
                    "description": "CosyVoice model from ModelLoader"
                }),
                "source_audio": ("AUDIO", {
                    "description": "Source audio to convert"
                }),
                "target_audio": ("AUDIO", {
                    "description": "Target voice reference"
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
            }
        }

    def convert_voice(
        self,
        model: Dict[str, Any],
        source_audio: Dict[str, Any],
        target_audio: Dict[str, Any],
        speed: float = 1.0,
        seed: int = -1
    ) -> Tuple[Dict[str, Any]]:
        """
        Convert source voice to target voice

        Args:
            model: CosyVoice model info dict
            source_audio: Source audio to convert
            target_audio: Target voice reference
            speed: Speech speed
            seed: Random seed

        Returns:
            Tuple containing audio dict
        """
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 VC] Converting voice...")
        print(f"[XB CosyVoice3 VC] Speed: {speed}x")
        print(f"{'='*60}\n")

        # Check audio durations BEFORE try block so errors propagate to ComfyUI
        source_waveform = source_audio['waveform']
        source_sample_rate = source_audio['sample_rate']
        source_duration = source_waveform.shape[-1] / source_sample_rate

        target_waveform = target_audio['waveform']
        target_sample_rate = target_audio['sample_rate']
        target_duration = target_waveform.shape[-1] / target_sample_rate

        if source_duration < 0.5:
            raise ValueError(f"源音频太短（{source_duration:.1f} 秒），请提供至少 0.5 秒的音频。")
        if source_duration > 30:
            raise ValueError(f"源音频太长（{source_duration:.1f} 秒），请裁剪到 30 秒以内。")

        if target_duration < 0.5:
            raise ValueError(f"目标参考音频太短（{target_duration:.1f} 秒），请提供至少 0.5 秒的音频。")
        if target_duration > 30:
            raise ValueError(f"目标参考音频太长（{target_duration:.1f} 秒），请裁剪到 30 秒以内。")

        source_temp = None
        target_temp = None

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

            # Initialize progress bar - 3 steps: prepare, inference, finalize
            pbar = comfy.utils.ProgressBar(3)

            # Step 1: Prepare audio
            pbar.update_absolute(0, 3)
            print(f"[XB CosyVoice3 VC] Model sample rate: {sample_rate} Hz")

            # Check if model supports voice conversion
            if not hasattr(cosyvoice_model, 'inference_vc'):
                raise RuntimeError("Model does not support voice conversion")

            # Prepare source and target audio - use model's sample rate
            print(f"[XB CosyVoice3 VC] Preparing source audio ({source_duration:.1f}s)...")
            _, _, source_temp = prepare_audio_for_cosyvoice(source_audio, target_sample_rate=sample_rate)

            print(f"[XB CosyVoice3 VC] Preparing target audio ({target_duration:.1f}s)...")
            _, _, target_temp = prepare_audio_for_cosyvoice(target_audio, target_sample_rate=sample_rate)

            pbar.update_absolute(1, 3)

            # Step 2: Perform voice conversion
            pbar.update_absolute(1, 3)
            print(f"[XB CosyVoice3 VC] Running voice conversion...")

            output = cosyvoice_model.inference_vc(
                source_wav=source_temp,
                prompt_wav=target_temp,
                stream=False,
                speed=speed
            )

            # Collect all output chunks
            all_speech = []
            chunk_count = 0
            for chunk in output:
                chunk_count += 1
                all_speech.append(chunk['tts_speech'])
                print(f"[XB CosyVoice3 VC] Processed chunk {chunk_count}")

            # Concatenate all chunks
            if len(all_speech) > 1:
                waveform = torch.cat(all_speech, dim=-1)
                print(f"[XB CosyVoice3 VC] Combined {len(all_speech)} chunks")
            else:
                waveform = all_speech[0]

            pbar.update_absolute(2, 3)

            # Ensure waveform is on CPU
            if waveform.device != torch.device('cpu'):
                waveform = waveform.cpu()

            # Step 3: Finalize
            pbar.update_absolute(2, 3)

            # Convert to ComfyUI AUDIO format
            audio = tensor_to_comfyui_audio(waveform, sample_rate)

            duration = waveform.shape[-1] / sample_rate

            pbar.update_absolute(3, 3)

            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 VC] Voice conversion successful!")
            print(f"[XB CosyVoice3 VC] Duration: {duration:.2f} seconds")
            print(f"[XB CosyVoice3 VC] Sample rate: {sample_rate} Hz")
            print(f"{'='*60}\n")

            return (audio,)

        except Exception as e:
            error_msg = f"语音转换失败: {str(e)}"
            print(f"[XB CosyVoice3 VC] [!] {error_msg}")
            empty_audio = {"waveform": torch.zeros(1, 1, 22050), "sample_rate": 22050}
            return (empty_audio,)

        finally:
            # Clean up temp files
            cleanup_temp_file(source_temp)
            cleanup_temp_file(target_temp)
