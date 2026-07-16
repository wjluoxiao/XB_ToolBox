"""
XB CosyVoice3 Dialog TTS Node
Multi-speaker dialog synthesis with voice cloning
"""

import torch
import random
from typing import Tuple, Dict, Any, Optional, List
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

# Import Whisper transcription functions from zero_shot
try:
    from .zero_shot import transcribe_audio, is_cosyvoice3_model
except (ImportError, ValueError):
    from zero_shot import transcribe_audio, is_cosyvoice3_model

# ComfyUI progress bar
import comfy.utils


class XB_CosyVoice3_Dialog:
    """
    Multi-speaker dialog TTS using CosyVoice voice cloning.
    Accepts dialog text with speaker labels and generates audio using separate voice prompts.
    """

    RETURN_TYPES = ("AUDIO", "AUDIO", "AUDIO", "AUDIO", "AUDIO", "STRING")
    RETURN_NAMES = ("dialog_audio", "speaker_a_audio", "speaker_b_audio",
                    "speaker_c_audio", "speaker_d_audio", "message")
    FUNCTION = "generate_dialog"
    CATEGORY = "🔊XB CosyVoice3/Synthesis"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("COSYVOICE_MODEL", {
                    "description": "CosyVoice model from ModelLoader"
                }),
                "dialog_text": ("STRING", {
                    "default": "SPEAKER A: Hello, how are you?\nSPEAKER B: I'm doing great, thanks for asking!",
                    "multiline": True,
                    "description": "Dialog text with speaker labels (SPEAKER A:, SPEAKER B:, etc.)"
                }),
                "speaker_A_Audio": ("AUDIO", {
                    "description": "Voice reference for Speaker A (max 30 seconds)"
                }),
                "speaker_B_Audio": ("AUDIO", {
                    "description": "Voice reference for Speaker B (max 30 seconds)"
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
                "speaker_C_Audio": ("AUDIO", {
                    "description": "Voice reference for Speaker C (optional)"
                }),
                "speaker_D_Audio": ("AUDIO", {
                    "description": "Voice reference for Speaker D (optional)"
                }),
                "seed": ("INT", {
                    "default": 42,
                    "min": -1,
                    "max": 2147483647,
                    "description": "Random seed (-1 for random)"
                }),
            }
        }

    def _validate_audio_duration(self, audio: Dict[str, Any], speaker_name: str) -> float:
        """Validate audio duration and return it."""
        waveform = audio['waveform']
        sample_rate = audio['sample_rate']
        duration = waveform.shape[-1] / sample_rate

        if duration > 30:
            raise ValueError(
                f"Speaker {speaker_name} reference audio is too long ({duration:.1f} seconds). "
                f"CosyVoice only supports reference audio up to 30 seconds. "
                f"Please use the XB Audio Crop node to trim your audio. "
                f"Recommended: 3-10 seconds for best quality."
            )
        return duration

    def _prepare_speaker_data(
        self,
        speakers: Dict[str, Dict[str, Any]],
        is_v3: bool
    ) -> Tuple[Dict[str, str], Dict[str, str], List[str]]:
        """
        Prepare speaker temp files and transcripts.

        Returns:
            temp_files: Dict mapping speaker ID to temp file path
            transcripts: Dict mapping speaker ID to formatted transcript
            temp_file_list: List of temp file paths for cleanup
        """
        temp_files = {}
        transcripts = {}
        temp_file_list = []

        for speaker_id, audio in speakers.items():
            if audio is None:
                continue

            # Save audio to temp file
            temp_file = save_raw_audio_to_tempfile(audio)
            temp_files[speaker_id] = temp_file
            temp_file_list.append(temp_file)

            # Transcribe the reference audio
            print(f"[XB CosyVoice3 Dialog] Transcribing Speaker {speaker_id} reference audio...")
            transcript = transcribe_audio(temp_file)

            if transcript:
                if is_v3:
                    # CosyVoice3 format with system prompt
                    transcripts[speaker_id] = f"You are a helpful assistant.<|endofprompt|>{transcript}"
                else:
                    transcripts[speaker_id] = transcript
                print(f"[XB CosyVoice3 Dialog] Speaker {speaker_id} transcript: '{transcript[:50]}{'...' if len(transcript) > 50 else ''}'")
            else:
                # Empty transcript - will fall back to cross-lingual
                transcripts[speaker_id] = None
                print(f"[XB CosyVoice3 Dialog] Speaker {speaker_id}: No transcript (will use cross-lingual mode)")

        return temp_files, transcripts, temp_file_list

    def _parse_dialog_line(self, line: str) -> Tuple[Optional[str], str]:
        """
        Parse a dialog line to extract speaker and content.

        Returns:
            Tuple of (speaker_id, content) or (None, "") if invalid
        """
        line = line.strip()
        if not line:
            return None, ""

        # Check for speaker prefixes
        prefixes = {
            "SPEAKER A:": "A",
            "SPEAKER B:": "B",
            "SPEAKER C:": "C",
            "SPEAKER D:": "D",
        }

        for prefix, speaker_id in prefixes.items():
            if line.upper().startswith(prefix):
                content = line[len(prefix):].strip()
                return speaker_id, content

        return None, ""

    def generate_dialog(
        self,
        model: Dict[str, Any],
        dialog_text: str,
        speaker_A_Audio: Dict[str, Any],
        speaker_B_Audio: Dict[str, Any],
        speed: float = 1.0,
        speaker_C_Audio: Optional[Dict[str, Any]] = None,
        speaker_D_Audio: Optional[Dict[str, Any]] = None,
        seed: int = -1
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
        """
        Generate multi-speaker dialog audio.
        """
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 Dialog] Starting dialog generation...")
        print(f"[XB CosyVoice3 Dialog] Speed: {speed}x")
        print(f"{'='*60}\n")

        temp_file_list = []

        try:
            # Set seed if specified
            if seed >= 0:
                torch.manual_seed(seed)
                random.seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)

            # Get model instance and sample rate
            cosyvoice_model = model["model"]
            sample_rate = cosyvoice_model.sample_rate

            # Detect model version
            is_v3 = model.get("is_cosyvoice3", False) or is_cosyvoice3_model(model)

            # Validate audio durations
            print(f"[XB CosyVoice3 Dialog] Validating speaker audio durations...")
            self._validate_audio_duration(speaker_A_Audio, "A")
            self._validate_audio_duration(speaker_B_Audio, "B")
            if speaker_C_Audio is not None:
                self._validate_audio_duration(speaker_C_Audio, "C")
            if speaker_D_Audio is not None:
                self._validate_audio_duration(speaker_D_Audio, "D")

            # Prepare speaker data (temp files and transcripts)
            speakers = {
                "A": speaker_A_Audio,
                "B": speaker_B_Audio,
                "C": speaker_C_Audio,
                "D": speaker_D_Audio,
            }

            temp_files, transcripts, temp_file_list = self._prepare_speaker_data(speakers, is_v3)

            # Parse dialog lines
            lines = dialog_text.strip().splitlines()
            valid_lines = []
            for line in lines:
                speaker_id, content = self._parse_dialog_line(line)
                if speaker_id and content:
                    # Check if we have audio for this speaker
                    if speaker_id in temp_files:
                        valid_lines.append((speaker_id, content))
                    else:
                        print(f"[XB CosyVoice3 Dialog] Skipping line for Speaker {speaker_id}: no audio reference provided")

            if not valid_lines:
                print(f"[XB CosyVoice3 Dialog] No valid dialog lines found!")
                empty_audio = {"waveform": torch.zeros(1, 1, sample_rate), "sample_rate": sample_rate}
                return (empty_audio, empty_audio, empty_audio, empty_audio, empty_audio,
                        "No valid dialog lines found. Use format: SPEAKER A: text")

            # Initialize progress bar
            total_steps = len(valid_lines) + 2  # +2 for prep and finalize
            pbar = comfy.utils.ProgressBar(total_steps)
            pbar.update_absolute(1, total_steps)

            # Generate audio for each line
            speaker_waveforms = {"A": [], "B": [], "C": [], "D": []}
            combined_waveforms = []

            for i, (speaker_id, content) in enumerate(valid_lines):
                print(f"[XB CosyVoice3 Dialog] Generating line {i+1}/{len(valid_lines)}: Speaker {speaker_id}")

                temp_file = temp_files[speaker_id]
                transcript = transcripts.get(speaker_id)

                # Generate speech
                if transcript:
                    # Use zero-shot with transcript
                    output = cosyvoice_model.inference_zero_shot(
                        tts_text=content,
                        prompt_text=transcript,
                        prompt_wav=temp_file,
                        stream=False,
                        speed=speed
                    )
                else:
                    # Fall back to cross-lingual (no transcript)
                    if is_v3:
                        formatted_text = f"You are a helpful assistant.<|endofprompt|>{content}"
                    else:
                        formatted_text = content

                    output = cosyvoice_model.inference_cross_lingual(
                        tts_text=formatted_text,
                        prompt_wav=temp_file,
                        stream=False,
                        speed=speed
                    )

                # Collect output chunks
                all_speech = []
                for chunk in output:
                    all_speech.append(chunk['tts_speech'])

                if len(all_speech) > 1:
                    current_wav = torch.cat(all_speech, dim=-1)
                else:
                    current_wav = all_speech[0]

                # Ensure on CPU
                if current_wav.device != torch.device('cpu'):
                    current_wav = current_wav.cpu()

                # Add to combined dialog
                combined_waveforms.append(current_wav)

                # Add to correct speaker track, silence to others
                silence = torch.zeros_like(current_wav)
                for sid in speaker_waveforms.keys():
                    if sid == speaker_id:
                        speaker_waveforms[sid].append(current_wav)
                    else:
                        speaker_waveforms[sid].append(silence)

                pbar.update_absolute(i + 2, total_steps)

            # Concatenate all waveforms
            combined_waveform = torch.cat(combined_waveforms, dim=-1)

            speaker_tracks = {}
            for sid, waveforms in speaker_waveforms.items():
                if waveforms:
                    speaker_tracks[sid] = torch.cat(waveforms, dim=-1)
                else:
                    # Empty track for unused speakers
                    speaker_tracks[sid] = torch.zeros_like(combined_waveform)

            # Convert to ComfyUI audio format
            dialog_audio = tensor_to_comfyui_audio(combined_waveform, sample_rate)
            speaker_a_audio = tensor_to_comfyui_audio(speaker_tracks["A"], sample_rate)
            speaker_b_audio = tensor_to_comfyui_audio(speaker_tracks["B"], sample_rate)
            speaker_c_audio = tensor_to_comfyui_audio(speaker_tracks["C"], sample_rate)
            speaker_d_audio = tensor_to_comfyui_audio(speaker_tracks["D"], sample_rate)

            pbar.update_absolute(total_steps, total_steps)

            duration = combined_waveform.shape[-1] / sample_rate
            message = f"Dialog synthesized successfully! Duration: {duration:.2f}s, Lines: {len(valid_lines)}"

            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 Dialog] {message}")
            print(f"[XB CosyVoice3 Dialog] Sample rate: {sample_rate} Hz")
            print(f"{'='*60}\n")

            return (dialog_audio, speaker_a_audio, speaker_b_audio,
                    speaker_c_audio, speaker_d_audio, message)

        except Exception as e:
            error_msg = f"Error generating dialog: {str(e)}"
            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 Dialog] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")

            # Return empty audio on error
            empty_audio = {"waveform": torch.zeros(1, 1, 22050), "sample_rate": 22050}
            return (empty_audio, empty_audio, empty_audio, empty_audio, empty_audio, error_msg)

        finally:
            # Clean up temp files
            for temp_file in temp_file_list:
                cleanup_temp_file(temp_file)
