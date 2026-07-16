"""
XB CosyVoice3 Audio Crop Node
Crop/trim audio to specific start and end times
"""

import torch
from typing import Tuple, Dict, Any


def parse_time_string(time_str: str) -> float:
    """
    Parse timer-style time string to seconds.

    Supported formats:
        - "MM:SS" (e.g., "0:05" = 5 seconds, "1:30" = 90 seconds)
        - "HH:MM:SS" (e.g., "0:01:30" = 90 seconds)

    Args:
        time_str: Time string in MM:SS or HH:MM:SS format

    Returns:
        Time in seconds as float

    Raises:
        ValueError: If format is invalid
    """
    time_str = time_str.strip()

    if not time_str:
        raise ValueError("Time string cannot be empty")

    parts = time_str.split(':')

    try:
        if len(parts) == 2:  # MM:SS
            minutes = int(parts[0])
            seconds = float(parts[1])
            if minutes < 0 or seconds < 0 or seconds >= 60:
                raise ValueError(f"Invalid time values in '{time_str}'")
            return minutes * 60 + seconds

        elif len(parts) == 3:  # HH:MM:SS
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            if hours < 0 or minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
                raise ValueError(f"Invalid time values in '{time_str}'")
            return hours * 3600 + minutes * 60 + seconds

        else:
            raise ValueError(f"Invalid time format: '{time_str}'. Use MM:SS (e.g., 0:05) or HH:MM:SS (e.g., 0:01:30)")

    except ValueError as e:
        if "Invalid time" in str(e):
            raise
        raise ValueError(f"Invalid time format: '{time_str}'. Use MM:SS (e.g., 0:05) or HH:MM:SS (e.g., 0:01:30)")


class XB_CosyVoice3_AudioCrop:
    """
    Crop (trim) audio to a specific start and end time.
    Useful for trimming reference audio to the recommended 3-10 second range.
    """

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "crop_audio"
    CATEGORY = "🔊XB CosyVoice3/Audio"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO", {
                    "description": "Input audio to crop"
                }),
                "start_time": ("STRING", {
                    "default": "0:00",
                    "description": "Start time (MM:SS or HH:MM:SS, e.g., 0:05 for 5 seconds)"
                }),
                "end_time": ("STRING", {
                    "default": "0:10",
                    "description": "End time (MM:SS or HH:MM:SS, e.g., 1:00 for 1 minute)"
                }),
            }
        }

    def crop_audio(
        self,
        audio: Dict[str, Any],
        start_time: str = "0:00",
        end_time: str = "0:10"
    ) -> Tuple[Dict[str, Any]]:
        """
        Crop audio to specific start and end times

        Args:
            audio: Input audio dict with 'waveform' and 'sample_rate'
            start_time: Start time in MM:SS or HH:MM:SS format
            end_time: End time in MM:SS or HH:MM:SS format

        Returns:
            Tuple containing cropped audio dict
        """
        # Parse time strings to seconds
        start_seconds = parse_time_string(start_time)
        end_seconds = parse_time_string(end_time)

        waveform = audio['waveform']
        sample_rate = audio['sample_rate']

        # Calculate frame indices
        start_frame = int(start_seconds * sample_rate)
        end_frame = int(end_seconds * sample_rate)

        # Get total frames
        total_frames = waveform.shape[-1]

        # Clamp to valid range
        start_frame = max(0, min(start_frame, total_frames - 1))
        end_frame = max(start_frame + 1, min(end_frame, total_frames))

        if start_frame >= end_frame:
            print(f"[XB CosyVoice3 AudioCrop] Warning: Invalid time range, returning original audio")
            return (audio,)

        # Crop waveform
        cropped_waveform = waveform[..., start_frame:end_frame]

        cropped_audio = {
            'waveform': cropped_waveform,
            'sample_rate': sample_rate
        }

        duration = (end_frame - start_frame) / sample_rate
        print(f"[XB CosyVoice3 AudioCrop] Cropped: {start_time} - {end_time} (duration: {duration:.2f}s)")

        return (cropped_audio,)
