"""
Audio Utilities for XB CosyVoice3
Handles audio format conversions and processing
"""

import torch
import torchaudio
import soundfile as sf
import tempfile
import os
from typing import Dict, Any, Tuple, Optional


def comfyui_audio_to_tensor(audio: Dict[str, Any]) -> Tuple[torch.Tensor, int]:
    """
    Convert ComfyUI AUDIO format to tensor and sample rate

    Args:
        audio: ComfyUI audio dict {"waveform": tensor, "sample_rate": int}

    Returns:
        Tuple of (waveform_tensor, sample_rate)
    """
    waveform = audio['waveform']
    sample_rate = audio['sample_rate']

    return waveform, sample_rate


def tensor_to_comfyui_audio(waveform: torch.Tensor, sample_rate: int) -> Dict[str, Any]:
    """
    Convert tensor to ComfyUI AUDIO format

    Args:
        waveform: Audio tensor
        sample_rate: Sample rate in Hz

    Returns:
        ComfyUI audio dict
    """
    # Ensure waveform is on CPU
    if waveform.device != torch.device('cpu'):
        waveform = waveform.cpu()

    # Ensure proper shape [batch, channels, samples]
    if waveform.ndim == 1:
        # Mono, no batch -> [1, 1, samples]
        waveform = waveform.unsqueeze(0).unsqueeze(0)
    elif waveform.ndim == 2:
        # Either [channels, samples] or [batch, samples]
        # Assume [channels, samples] and add batch dim
        waveform = waveform.unsqueeze(0)

    return {
        "waveform": waveform,
        "sample_rate": sample_rate
    }


def save_audio_to_tempfile(waveform: torch.Tensor, sample_rate: int, suffix: str = ".wav") -> str:
    """
    Save audio tensor to a temporary file

    Args:
        waveform: Audio tensor [channels, samples] or [batch, channels, samples]
        sample_rate: Sample rate in Hz
        suffix: File suffix

    Returns:
        Path to temporary file
    """
    # Ensure waveform is on CPU
    if waveform.device != torch.device('cpu'):
        waveform = waveform.cpu()

    # Remove batch dimension if present
    if waveform.ndim == 3:
        waveform = waveform.squeeze(0)

    # Create temp file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = temp_file.name
    temp_file.close()

    # Save audio using soundfile directly (avoids torchaudio's torchcodec requirement)
    # soundfile expects shape (samples, channels), so transpose from (channels, samples)
    audio_np = waveform.cpu().numpy()
    if audio_np.ndim == 2:
        audio_np = audio_np.T  # (channels, samples) -> (samples, channels)
    sf.write(temp_path, audio_np, sample_rate)

    return temp_path


def load_audio_from_path(audio_path: str, target_sample_rate: Optional[int] = None) -> Dict[str, Any]:
    """
    Load audio file from path into ComfyUI AUDIO format

    Args:
        audio_path: Path to audio file
        target_sample_rate: Target sample rate (None to keep original)

    Returns:
        ComfyUI audio dict
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Load audio
    waveform, sample_rate = torchaudio.load(audio_path)

    # Resample if needed
    if target_sample_rate is not None and target_sample_rate != sample_rate:
        resampler = torchaudio.transforms.Resample(sample_rate, target_sample_rate)
        waveform = resampler(waveform)
        sample_rate = target_sample_rate

    # Convert to ComfyUI format
    return tensor_to_comfyui_audio(waveform, sample_rate)


def resample_audio(waveform: torch.Tensor, orig_sample_rate: int, target_sample_rate: int) -> torch.Tensor:
    """
    Resample audio tensor to target sample rate

    Args:
        waveform: Audio tensor
        orig_sample_rate: Original sample rate
        target_sample_rate: Target sample rate

    Returns:
        Resampled audio tensor
    """
    if orig_sample_rate == target_sample_rate:
        return waveform

    resampler = torchaudio.transforms.Resample(orig_sample_rate, target_sample_rate)
    return resampler(waveform)


def ensure_mono(waveform: torch.Tensor) -> torch.Tensor:
    """
    Convert audio to mono by averaging channels

    Args:
        waveform: Audio tensor [..., channels, samples]

    Returns:
        Mono audio tensor [..., 1, samples]
    """
    if waveform.shape[-2] == 1:
        return waveform

    # Average across channels
    return waveform.mean(dim=-2, keepdim=True)


def ensure_stereo(waveform: torch.Tensor) -> torch.Tensor:
    """
    Convert audio to stereo

    Args:
        waveform: Audio tensor [..., channels, samples]

    Returns:
        Stereo audio tensor [..., 2, samples]
    """
    if waveform.shape[-2] == 2:
        return waveform

    if waveform.shape[-2] == 1:
        # Duplicate mono to stereo
        return waveform.repeat(*([1] * (waveform.ndim - 2)), 2, 1)

    # Multiple channels - take first two
    return waveform[..., :2, :]


def normalize_audio(waveform: torch.Tensor, target_peak: float = 0.95) -> torch.Tensor:
    """
    Normalize audio to target peak amplitude

    Args:
        waveform: Audio tensor
        target_peak: Target peak amplitude (0.0 - 1.0)

    Returns:
        Normalized audio tensor
    """
    current_peak = waveform.abs().max()

    if current_peak > 0:
        waveform = waveform * (target_peak / current_peak)

    return waveform


def prepare_audio_for_cosyvoice(
    audio: Dict[str, Any],
    target_sample_rate: int = 16000,
    mono: bool = True
) -> Tuple[torch.Tensor, int, Optional[str]]:
    """
    Prepare ComfyUI audio for CosyVoice inference

    Args:
        audio: ComfyUI audio dict
        target_sample_rate: Target sample rate for CosyVoice
        mono: Convert to mono

    Returns:
        Tuple of (waveform, sample_rate, temp_file_path)
    """
    waveform, sample_rate = comfyui_audio_to_tensor(audio)

    # Remove batch dimension if present
    if waveform.ndim == 3:
        waveform = waveform.squeeze(0)

    # Convert to mono if needed
    if mono and waveform.shape[0] > 1:
        waveform = ensure_mono(waveform)

    # Resample if needed
    if sample_rate != target_sample_rate:
        waveform = resample_audio(waveform, sample_rate, target_sample_rate)
        sample_rate = target_sample_rate

    # Save to temp file (CosyVoice may expect file paths)
    temp_path = save_audio_to_tempfile(waveform, sample_rate)

    return waveform, sample_rate, temp_path


def save_raw_audio_to_tempfile(audio: Dict[str, Any]) -> str:
    """
    Save ComfyUI audio to temp file WITHOUT any processing.

    CosyVoice's load_wav() handles mono conversion and resampling internally,
    so we should NOT preprocess the audio.

    Args:
        audio: ComfyUI audio dict {"waveform": tensor, "sample_rate": int}

    Returns:
        Path to temporary file
    """
    waveform = audio['waveform']
    sample_rate = audio['sample_rate']

    # Remove batch dim if present
    if waveform.ndim == 3:
        waveform = waveform.squeeze(0)

    # Ensure CPU
    if waveform.device != torch.device('cpu'):
        waveform = waveform.cpu()

    # Save directly without any processing
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_path = temp_file.name
    temp_file.close()

    # soundfile expects (samples, channels) format
    audio_np = waveform.numpy()
    if audio_np.ndim == 2:
        audio_np = audio_np.T  # (channels, samples) -> (samples, channels)
    sf.write(temp_path, audio_np, sample_rate)

    return temp_path


def cleanup_temp_file(temp_path: Optional[str]):
    """
    Clean up temporary audio file

    Args:
        temp_path: Path to temporary file
    """
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except:
            pass
