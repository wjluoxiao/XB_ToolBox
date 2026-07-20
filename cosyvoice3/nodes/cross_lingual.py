"""
XB CosyVoice3 Cross-Lingual Synthesis Node
Speak text in different language using reference voice
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


class XB_CosyVoice3_CrossLingual:
    """
    Cross-lingual voice synthesis - speak text in different language with same voice
    """

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "cross_lingual_synthesis"
    CATEGORY = "🔊XB CosyVoice3/Synthesis"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("COSYVOICE_MODEL", {
                    "description": "CosyVoice model from ModelLoader"
                }),
                "text": ("STRING", {
                    "default": "Hello, this is cross-lingual speech synthesis.",
                    "multiline": True,
                    "description": "Text to synthesize in target language"
                }),
                "reference_audio": ("AUDIO", {
                    "description": "Reference voice (can be in any language)"
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
                "target_language": (["auto", "zh", "en", "ja", "ko", "de", "es", "fr", "it", "ru"], {
                    "default": "auto",
                    "description": "Target language (auto-detect from text)"
                }),
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

    def cross_lingual_synthesis(
        self,
        model: Dict[str, Any],
        text: str,
        reference_audio: Dict[str, Any],
        speed: float = 1.0,
        target_language: str = "auto",
        seed: int = -1,
        text_frontend: bool = True
    ) -> Tuple[Dict[str, Any]]:
        """
        Generate cross-lingual speech

        Args:
            model: CosyVoice model info dict
            text: Text in target language
            reference_audio: Reference audio for voice
            speed: Speech speed
            target_language: Target language
            seed: Random seed

        Returns:
            Tuple containing audio dict
        """
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 CrossLingual] Generating cross-lingual speech...")
        print(f"[XB CosyVoice3 CrossLingual] Text: {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"[XB CosyVoice3 CrossLingual] Target language: {target_language}")
        print(f"[XB CosyVoice3 CrossLingual] Speed: {speed}x")
        print(f"{'='*60}\n")

        # Check audio duration BEFORE try block so error propagates to ComfyUI
        ref_waveform = reference_audio['waveform']
        ref_sample_rate = reference_audio['sample_rate']
        ref_duration = ref_waveform.shape[-1] / ref_sample_rate

        if ref_duration < 0.5:
            raise ValueError(f"参考音频太短（{ref_duration:.1f} 秒），请提供至少 0.5 秒的音频，建议 3~10 秒效果最佳。")
        if ref_duration > 30:
            raise ValueError(f"参考音频太长（{ref_duration:.1f} 秒），请裁剪到 30 秒以内，建议 3~10 秒。")

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

            # Initialize progress bar - 3 steps: prepare, inference, finalize
            pbar = comfy.utils.ProgressBar(3)

            # Step 1: Prepare reference audio
            pbar.update_absolute(0, 3)
            print(f"[XB CosyVoice3 CrossLingual] Preparing reference audio...")
            print(f"[XB CosyVoice3 CrossLingual] Model sample rate: {sample_rate} Hz")
            print(f"[XB CosyVoice3 CrossLingual] Reference audio duration: {ref_duration:.1f}s (max 30s)")
            # Save at original sample rate - CosyVoice's load_wav() handles resampling internally
            _, _, temp_file = prepare_audio_for_cosyvoice(reference_audio, target_sample_rate=ref_sample_rate)

            # Detect model version for proper formatting
            is_v3 = model.get("is_cosyvoice3", False)
            version_str = model.get("model_version", "").lower()
            if not is_v3:
                is_v3 = "cosyvoice3" in version_str or "fun-cosyvoice3" in version_str

            # Format text based on model version
            # CosyVoice3 cross-lingual requires system prompt in tts_text (per example.py:81-83)
            if is_v3:
                formatted_text = f"You are a helpful assistant.<|endofprompt|>{text}"
                print(f"[XB CosyVoice3 CrossLingual] Using CosyVoice3 format with system prompt")
            else:
                # CosyVoice v1 may need language tags for cross-lingual
                if target_language != "auto":
                    lang_tags = {
                        "en": "<|en|>", "zh": "<|zh|>", "ja": "<|jp|>",
                        "ko": "<|ko|>", "yue": "<|yue|>", "de": "<|de|>",
                        "es": "<|es|>", "fr": "<|fr|>", "it": "<|it|>", "ru": "<|ru|>"
                    }
                    lang_tag = lang_tags.get(target_language, "")
                    formatted_text = f"{lang_tag}{text}"
                    print(f"[XB CosyVoice3 CrossLingual] Using CosyVoice v1 format with language tag: {lang_tag}")
                else:
                    formatted_text = text
                    print(f"[XB CosyVoice3 CrossLingual] Using CosyVoice v1 format (auto language detection)")

            pbar.update_absolute(1, 3)

            # Step 2: Generate speech
            pbar.update_absolute(1, 3)
            print(f"[XB CosyVoice3 CrossLingual] Running cross-lingual inference...")

            output = cosyvoice_model.inference_cross_lingual(
                tts_text=formatted_text,
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
                print(f"[XB CosyVoice3 CrossLingual] Processed chunk {chunk_count}")

            # Concatenate all chunks
            if len(all_speech) > 1:
                waveform = torch.cat(all_speech, dim=-1)
                print(f"[XB CosyVoice3 CrossLingual] Combined {len(all_speech)} chunks")
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
            print(f"[XB CosyVoice3 CrossLingual] Cross-lingual speech generated successfully!")
            print(f"[XB CosyVoice3 CrossLingual] Duration: {duration:.2f} seconds")
            print(f"[XB CosyVoice3 CrossLingual] Sample rate: {sample_rate} Hz")
            print(f"{'='*60}\n")

            return (audio,)

        except Exception as e:
            error_msg = f"跨语言合成失败: {str(e)}"
            print(f"[XB CosyVoice3 CrossLingual] [!] {error_msg}")
            empty_audio = {"waveform": torch.zeros(1, 1, 22050), "sample_rate": 22050}
            return (empty_audio,)

        finally:
            # Clean up temp file
            cleanup_temp_file(temp_file)
