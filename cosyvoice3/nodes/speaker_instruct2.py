"""
XB CosyVoice3 Speaker Instruct2 Node
Combine speaker preset loading (like Speaker Clone) with instruct-based style
control (like Instruct2), using inference_instruct2 with zero_shot_spk_id.
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


def is_cosyvoice3_model(model_info: Dict[str, Any]) -> bool:
    """Check if the loaded model is CosyVoice3"""
    version = model_info.get("model_version", "").lower()
    return "cosyvoice3" in version or "fun-cosyvoice3" in version


class XB_CosyVoice3_SpeakerInstruct2:
    """
    Synthesize speech using a saved speaker preset for voice timbre,
    combined with instruct text for style/emotion control.
    Uses inference_instruct2 with zero_shot_spk_id — no live reference
    audio needed.
    """

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "speaker_instruct2"
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
                    "description": "Text to synthesize"
                }),
                "instruct_text": ("STRING", {
                    "default": "请非常开心地说这句话。",
                    "multiline": True,
                    "description": "Instructions to control speaking style, emotion, and tone. "
                                   "Examples: '请非常伤心地说这句话。', 'Please say this in a very soft voice.'"
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

    def speaker_instruct2(
        self,
        model: Dict[str, Any],
        text: str,
        instruct_text: str,
        speaker_preset: str,
        speed: float = 1.0,
        seed: int = -1,
        text_frontend: bool = True,
    ) -> Tuple[Dict[str, Any]]:

        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 SpeakerInstruct2] Synthesizing...")
        print(f"[XB CosyVoice3 SpeakerInstruct2] Preset  : {speaker_preset}")
        print(f"[XB CosyVoice3 SpeakerInstruct2] Text    : {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"[XB CosyVoice3 SpeakerInstruct2] Instruct: {instruct_text[:80]}{'...' if len(instruct_text) > 80 else ''}")
        print(f"[XB CosyVoice3 SpeakerInstruct2] Speed   : {speed}x")
        print(f"{'='*60}\n")

        # Validate inputs
        if speaker_preset == "[none]":
            raise ValueError(
                "No speaker presets found. "
                "Please use the XB CosyVoice3 Save Speaker node to create one first."
            )
        if not instruct_text or not instruct_text.strip():
            raise ValueError(
                "instruct_text cannot be empty. Please provide style instructions, "
                "e.g. '请非常开心地说这句话。' or 'Please say this in a very soft voice.'"
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

            # Check inference_instruct2 is available
            if not hasattr(cosyvoice_model, 'inference_instruct2'):
                raise RuntimeError(
                    "inference_instruct2 is not available on this model. "
                    "The Speaker Instruct2 node requires a CosyVoice2 or CosyVoice3 model."
                )

            pbar = comfy.utils.ProgressBar(3)

            # Step 1: Load speaker preset
            pbar.update_absolute(0, 3)
            speaker_dir = get_speaker_dir()
            pt_path = os.path.join(speaker_dir, f"{speaker_preset}.pt")

            if not os.path.isfile(pt_path):
                raise FileNotFoundError(
                    f"Speaker preset file not found: {pt_path}\n"
                    f"Please run XB CosyVoice3 Save Speaker to create it."
                )

            print(f"[XB CosyVoice3 SpeakerInstruct2] Loading preset from: {pt_path}")
            load_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            spk2info = torch.load(pt_path, map_location=load_device)
            spk_id = next(iter(spk2info))
            print(f"[XB CosyVoice3 SpeakerInstruct2] Speaker ID: '{spk_id}'")

            # Inject preset into model frontend
            cosyvoice_model.frontend.spk2info = spk2info
            print(f"[XB CosyVoice3 SpeakerInstruct2] Injected spk2info into model frontend")

            # Step 2: Format instruct_text based on model version
            # NOTE: Because we pass zero_shot_spk_id, frontend_zero_shot skips instruct_text
            # entirely and uses the .pt data as-is. We must manually extract the instruct_text
            # tokens and overwrite prompt_text / prompt_text_len in spk2info after injection.
            # CosyVoice3: "You are a helpful assistant.\n<instruct><|endofprompt|>"
            # CosyVoice2: "<instruct><|endofprompt|>"
            pbar.update_absolute(1, 3)

            SYSTEM_PROMPT = "You are a helpful assistant."
            ENDOFPROMPT = "<|endofprompt|>"
            raw_instruct = instruct_text.strip()
            # Strip any pre-existing wrapper the user may have typed manually
            if raw_instruct.startswith(SYSTEM_PROMPT):
                raw_instruct = raw_instruct[len(SYSTEM_PROMPT):].lstrip("\n")
            if raw_instruct.endswith(ENDOFPROMPT):
                raw_instruct = raw_instruct[:-len(ENDOFPROMPT)].rstrip()

            is_v3 = model.get("is_cosyvoice3", False) or is_cosyvoice3_model(model)
            if is_v3:
                formatted_instruct = SYSTEM_PROMPT + "\n" + raw_instruct + ENDOFPROMPT
                print(f"[XB CosyVoice3 SpeakerInstruct2] Using CosyVoice3 instruct mode")
            else:
                formatted_instruct = f"{raw_instruct}{ENDOFPROMPT}"
                print(f"[XB CosyVoice3 SpeakerInstruct2] Using CosyVoice2 instruct mode")
            print(f"[XB CosyVoice3 SpeakerInstruct2] Formatted instruct: {formatted_instruct[:100]}")

            # Overwrite prompt_text in spk2info with the formatted instruct tokens.
            # This is necessary because frontend_zero_shot ignores instruct_text when
            # zero_shot_spk_id is provided, using the .pt data directly instead.
            prompt_text_token, prompt_text_token_len = cosyvoice_model.frontend._extract_text_token(formatted_instruct)
            cosyvoice_model.frontend.spk2info[spk_id]['prompt_text'] = prompt_text_token
            cosyvoice_model.frontend.spk2info[spk_id]['prompt_text_len'] = prompt_text_token_len
            print(f"[XB CosyVoice3 SpeakerInstruct2] Overwrote prompt_text with formatted instruct tokens")

            # Step 3: Run inference_instruct2 with zero_shot_spk_id, no prompt_wav
            print(f"[XB CosyVoice3 SpeakerInstruct2] Running inference_instruct2...")
            output = cosyvoice_model.inference_instruct2(
                tts_text=text,
                instruct_text=formatted_instruct,
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
                print(f"[XB CosyVoice3 SpeakerInstruct2] Processed chunk {chunk_count}")

            if not all_speech:
                raise RuntimeError("No audio was generated. Check model and inputs.")

            if len(all_speech) > 1:
                waveform = torch.cat(all_speech, dim=-1)
                print(f"[XB CosyVoice3 SpeakerInstruct2] Combined {len(all_speech)} chunks")
            else:
                waveform = all_speech[0]

            pbar.update_absolute(2, 3)

            if waveform.device != torch.device("cpu"):
                waveform = waveform.cpu()

            audio = tensor_to_comfyui_audio(waveform, sample_rate)
            duration = waveform.shape[-1] / sample_rate

            pbar.update_absolute(3, 3)

            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 SpeakerInstruct2] Speech generated successfully!")
            print(f"[XB CosyVoice3 SpeakerInstruct2] Duration    : {duration:.2f} seconds")
            print(f"[XB CosyVoice3 SpeakerInstruct2] Sample rate : {sample_rate} Hz")
            print(f"{'='*60}\n")

            return (audio,)

        except Exception as e:
            error_msg = f"说话人指令合成失败: {str(e)}"
            print(f"[XB CosyVoice3 SpeakerInstruct2] [!] {error_msg}")
            empty_audio = {"waveform": torch.zeros(1, 1, 22050), "sample_rate": 22050}
            return (empty_audio,)
