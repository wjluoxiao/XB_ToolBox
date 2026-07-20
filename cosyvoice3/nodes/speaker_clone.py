"""
XB CosyVoice3 Speaker Clone Node
Synthesize speech using a saved speaker preset (.pt) file
"""

import torch
import random
import os
import sys
from typing import Tuple, Dict, Any, List

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from ..utils.audio_utils import tensor_to_comfyui_audio
except (ImportError, ValueError):
    from utils.audio_utils import tensor_to_comfyui_audio

import comfy.utils
import folder_paths


def get_speaker_dir() -> str:
    """Return <ComfyUI models dir>/cosyvoice/speaker/"""
    return os.path.join(folder_paths.models_dir, "cosyvoice", "speaker")


def list_speaker_presets() -> List[str]:
    """
    Scan the speaker directory and return a list of speaker preset names
    (filenames without the .pt extension).
    Returns ['[none]'] if the directory is empty or does not exist.
    """
    speaker_dir = get_speaker_dir()
    if not os.path.isdir(speaker_dir):
        return ["[none]"]
    names = [
        os.path.splitext(f)[0]
        for f in sorted(os.listdir(speaker_dir))
        if f.endswith(".pt")
    ]
    return names if names else ["[none]"]






class XB_CosyVoice3_SpeakerClone:
    """
    Synthesize speech from a saved speaker preset.
    Loads a .pt file created by XB CosyVoice3 Save Speaker and calls
    inference_zero_shot via zero_shot_spk_id for high-quality voice cloning
    without needing the original reference audio.
    """

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "sft_clone"
    CATEGORY = "🔊XB CosyVoice3/Synthesis"

    @classmethod
    def INPUT_TYPES(cls):
        presets = list_speaker_presets()
        return {
            "required": {
                "model": ("COSYVOICE_MODEL", {
                    "description": "CosyVoice model from Model Loader"
                }),
                "text": ("STRING", {
                    "default": "Hello, this is my cloned voice speaking.",
                    "multiline": True,
                    "description": "Text to synthesize using the selected speaker preset"
                }),
                "speaker_preset": (presets, {
                    "description": "Speaker preset saved by XB CosyVoice3 Save Speaker"
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
                    "description": "Enable text normalization. Disable for CMU phonemes or special tags"
                }),
            }
        }

    def sft_clone(
        self,
        model: Dict[str, Any],
        text: str,
        speaker_preset: str,
        speed: float = 1.0,
        seed: int = -1,
        text_frontend: bool = True,
    ) -> Tuple[Dict[str, Any]]:
        """
        Load a speaker preset and synthesize speech via inference_zero_shot.

        Args:
            model:           CosyVoice model info dict from Model Loader
            text:            Text to synthesize
            speaker_preset:  Name of the preset (no .pt extension)
            speed:           Speech speed multiplier
            seed:            Random seed (-1 for random)
            text_frontend:   Enable text normalization

        Returns:
            Tuple containing ComfyUI AUDIO dict
        """
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 SpeakerClone] Synthesizing with speaker preset...")
        print(f"[XB CosyVoice3 SpeakerClone] Preset : {speaker_preset}")
        print(f"[XB CosyVoice3 SpeakerClone] Text   : {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"[XB CosyVoice3 SpeakerClone] Speed  : {speed}x")
        print(f"{'='*60}\n")

        # Guard against the placeholder shown when no presets exist
        if speaker_preset == "[none]":
            raise ValueError(
                "No speaker presets found. "
                "Please use the XB CosyVoice3 Save Speaker node to create one first."
            )

        try:
            # Set random seed
            if seed >= 0:
                torch.manual_seed(seed)
                random.seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)

            cosyvoice_model = model["model"]
            sample_rate = cosyvoice_model.sample_rate

            pbar = comfy.utils.ProgressBar(3)

            # Step 1: Load the .pt preset file
            pbar.update_absolute(0, 3)
            speaker_dir = get_speaker_dir()
            pt_path = os.path.join(speaker_dir, f"{speaker_preset}.pt")

            if not os.path.isfile(pt_path):
                raise FileNotFoundError(
                    f"Speaker preset file not found: {pt_path}\n"
                    f"Please run XB CosyVoice3 Save Speaker to create it."
                )

            print(f"[XB CosyVoice3 SpeakerClone] Loading preset from: {pt_path}")
            load_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            spk2info = torch.load(pt_path, map_location=load_device)
            print(f"[XB CosyVoice3 SpeakerClone] Preset loaded to device: {load_device}")

            # The first key in the dict is the spk_id
            spk_id = next(iter(spk2info))
            print(f"[XB CosyVoice3 SpeakerClone] Speaker ID: '{spk_id}'")

            # Step 2: Inject the preset into the model's frontend and run inference
            pbar.update_absolute(1, 3)

            # Override the model's spk2info so frontend_sft can look up our embedding
            cosyvoice_model.frontend.spk2info = spk2info
            print(f"[XB CosyVoice3 SpeakerClone] Injected spk2info into model frontend")

            print(f"[XB CosyVoice3 SpeakerClone] Running inference_zero_shot...")
            output = cosyvoice_model.inference_zero_shot(
                tts_text=text,
                prompt_text="",
                prompt_wav=None,
                zero_shot_spk_id=spk_id,
                stream=False,
                speed=speed,
                text_frontend=text_frontend,
            )

            # Collect all output chunks
            all_speech = []
            chunk_count = 0
            for chunk in output:
                chunk_count += 1
                all_speech.append(chunk["tts_speech"])
                print(f"[XB CosyVoice3 SpeakerClone] Processed chunk {chunk_count}")

            if not all_speech:
                raise RuntimeError("No audio was generated. Check model and preset.")

            # Concatenate chunks if more than one
            if len(all_speech) > 1:
                waveform = torch.cat(all_speech, dim=-1)
                print(f"[XB CosyVoice3 SpeakerClone] Combined {len(all_speech)} chunks")
            else:
                waveform = all_speech[0]

            pbar.update_absolute(2, 3)

            # Move to CPU
            if waveform.device != torch.device("cpu"):
                waveform = waveform.cpu()

            # Step 3: Convert to ComfyUI AUDIO format
            audio = tensor_to_comfyui_audio(waveform, sample_rate)
            duration = waveform.shape[-1] / sample_rate

            pbar.update_absolute(3, 3)

            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 SpeakerClone] Speech generated successfully!")
            print(f"[XB CosyVoice3 SpeakerClone] Duration    : {duration:.2f} seconds")
            print(f"[XB CosyVoice3 SpeakerClone] Sample rate : {sample_rate} Hz")
            print(f"{'='*60}\n")

            return (audio,)

        except Exception as e:
            error_msg = f"说话人克隆失败: {str(e)}"
            print(f"[XB CosyVoice3 SpeakerClone] [!] {error_msg}")
            empty_audio = {"waveform": torch.zeros(1, 1, 22050), "sample_rate": 22050}
            return (empty_audio,)
