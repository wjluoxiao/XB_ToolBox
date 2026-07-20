"""
Model Manager for XB CosyVoice3
Handles model downloading, caching, and loading
"""

import os
import torch
from typing import Optional, Dict, Any
from tqdm import tqdm

# Global model cache
_MODEL_CACHE = {}

# Model configurations
MODEL_CONFIGS = {
    "Fun-CosyVoice3-0.5B": {
        "modelscope_id": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
        "huggingface_id": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
        "recommended": True,
    },
    "CosyVoice2-0.5B": {
        "modelscope_id": "FunAudioLLM/CosyVoice2-0.5B",
        "huggingface_id": "FunAudioLLM/CosyVoice2-0.5B",
        "recommended": False,
    },
    "CosyVoice-300M": {
        "modelscope_id": "FunAudioLLM/CosyVoice-300M",
        "huggingface_id": "FunAudioLLM/CosyVoice-300M",
        "recommended": False,
    },
}


def get_models_directory() -> str:
    """Get the base models directory for CosyVoice models"""
    # Try to get ComfyUI models directory
    try:
        import folder_paths
        base_models_dir = folder_paths.models_dir
    except Exception as e:
        # Fallback to relative path
        print(f"[XB CosyVoice3] Could not import folder_paths: {e}")
        print(f"[XB CosyVoice3] Using fallback models directory")
        base_models_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "models"))

    cosyvoice_dir = os.path.join(base_models_dir, "cosyvoice")
    os.makedirs(cosyvoice_dir, exist_ok=True)

    print(f"[XB CosyVoice3] Models directory: {cosyvoice_dir}")
    return cosyvoice_dir


def download_model_modelscope(model_id: str, local_dir: str) -> str:
    """Download model from ModelScope"""
    print(f"\n{'='*60}")
    print(f"[XB CosyVoice3] Downloading from ModelScope: {model_id}")
    print(f"[XB CosyVoice3] Target directory: {local_dir}")
    print(f"{'='*60}\n")

    try:
        from modelscope import snapshot_download

        model_path = snapshot_download(
            model_id=model_id,
            cache_dir=local_dir,
            revision='master'
        )

        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3] Download complete!")
        print(f"[XB CosyVoice3] Model path: {model_path}")
        print(f"{'='*60}\n")

        return model_path

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3] ModelScope download failed: {str(e)}")
        print(f"{'='*60}\n")
        raise


def download_model_huggingface(model_id: str, local_dir: str) -> str:
    """Download model from HuggingFace"""
    print(f"\n{'='*60}")
    print(f"[XB CosyVoice3] Downloading from HuggingFace: {model_id}")
    print(f"[XB CosyVoice3] Target directory: {local_dir}")
    print(f"{'='*60}\n")

    try:
        from huggingface_hub import snapshot_download

        model_path = snapshot_download(
            repo_id=model_id,
            cache_dir=local_dir,
            revision='main'
        )

        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3] Download complete!")
        print(f"[XB CosyVoice3] Model path: {model_path}")
        print(f"{'='*60}\n")

        return model_path

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3] HuggingFace download failed: {str(e)}")
        print(f"{'='*60}\n")
        raise


def check_model_exists(model_dir: str) -> bool:
    """Check if model files exist in the directory"""
    if not os.path.exists(model_dir):
        return False

    # Check for any CosyVoice config file (v1, v2, or v3)
    config_files = ['cosyvoice.yaml', 'cosyvoice2.yaml', 'cosyvoice3.yaml']
    # Note: Some models use llm.rl.pt instead of llm.pt (e.g., Fun-CosyVoice3 on HuggingFace)
    llm_files = ['llm.pt', 'llm.rl.pt']
    flow_file = 'flow.pt'

    # Recursively search for files
    for root, dirs, files in os.walk(model_dir):
        has_config = any(f in files for f in config_files)
        has_llm = any(f in files for f in llm_files)
        has_flow = flow_file in files
        if has_config and has_llm and has_flow:
            return True

    return False


def get_model_path(
    model_version: str,
    download_source: str = "ModelScope",
    force_redownload: bool = False
) -> str:
    """
    Get the path to a CosyVoice model, downloading if necessary

    Args:
        model_version: Model version name (e.g., "Fun-CosyVoice3-0.5B")
        download_source: "ModelScope" or "HuggingFace"
        force_redownload: Force re-download even if model exists

    Returns:
        Path to the model directory
    """
    if model_version not in MODEL_CONFIGS:
        raise ValueError(f"Unknown model version: {model_version}. Available: {list(MODEL_CONFIGS.keys())}")

    config = MODEL_CONFIGS[model_version]
    models_dir = get_models_directory()
    model_dir = os.path.join(models_dir, model_version)

    # Check if model already exists
    if not force_redownload and check_model_exists(model_dir):
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3] Model already exists: {model_dir}")
        print(f"{'='*60}\n")
        return model_dir

    # Download model
    try:
        if download_source == "ModelScope":
            model_id = config["modelscope_id"]
            download_model_modelscope(model_id, model_dir)
        else:  # HuggingFace
            model_id = config["huggingface_id"]
            download_model_huggingface(model_id, model_dir)

        return model_dir

    except Exception as e:
        # Try alternate source if primary fails
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3] Primary download source failed, trying alternate...")
        print(f"{'='*60}\n")

        try:
            if download_source == "ModelScope":
                model_id = config["huggingface_id"]
                download_model_huggingface(model_id, model_dir)
            else:
                model_id = config["modelscope_id"]
                download_model_modelscope(model_id, model_dir)

            return model_dir

        except Exception as e2:
            raise RuntimeError(f"Failed to download model from both sources. Last error: {str(e2)}")


def load_cosyvoice_model(
    model_path: str,
    device: Optional[torch.device] = None
) -> Any:
    """
    Load a CosyVoice model from disk

    Args:
        model_path: Path to model directory
        device: Target device (will auto-detect if None)

    Returns:
        Loaded CosyVoice model instance
    """
    print(f"\n{'='*60}")
    print(f"[XB CosyVoice3] Loading CosyVoice model from: {model_path}")
    print(f"{'='*60}\n")

    try:
        # Import from vendored cosyvoice package (bundled with this node pack)
        # 使用相对导入确保加载本地的 cosyvoice 副本，避免与旧版冲突
        from ..cosyvoice.cli.cosyvoice import CosyVoice, CosyVoice2, CosyVoice3, AutoModel

        # Determine device
        if device is None:
            import comfy.model_management
            device = comfy.model_management.get_torch_device()

        print(f"[XB CosyVoice3] Target device: {device}")

        # Search for model directory containing cosyvoice.yaml or cosyvoice3.yaml
        # Also handles HuggingFace cache structure with snapshots/ subdirectory
        model_dir = None
        config_names = ['cosyvoice.yaml', 'cosyvoice3.yaml', 'cosyvoice2.yaml']
        for root, dirs, files in os.walk(model_path):
            for config_name in config_names:
                if config_name in files:
                    model_dir = root
                    print(f"[XB CosyVoice3] Found config: {os.path.join(root, config_name)}")
                    break
            if model_dir:
                break

        if model_dir is None:
            raise FileNotFoundError(f"Could not find cosyvoice.yaml/cosyvoice3.yaml in {model_path}")

        # Use AutoModel to automatically detect and load the correct model type
        print(f"[XB CosyVoice3] Using AutoModel to load from: {model_dir}")
        model = AutoModel(model_dir=model_dir, load_trt=False, fp16=False)

        # Note: CosyVoice handles device placement internally, no need to call .to()

        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3] Model loaded successfully!")
        print(f"{'='*60}\n")

        return model

    except Exception as e:
        print(f"[XB CosyVoice3] [!] 模型加载失败: {str(e)}")
        raise


def get_cached_model(
    model_version: str,
    download_source: str = "ModelScope",
    device: Optional[torch.device] = None,
    force_redownload: bool = False,
    force_reload: bool = False
) -> Dict[str, Any]:
    """
    Get a CosyVoice model, using cache if available

    Args:
        model_version: Model version name
        download_source: Download source
        device: Target device
        force_redownload: Force re-download
        force_reload: Force reload even if cached

    Returns:
        Dictionary containing model and metadata
    """
    cache_key = f"{model_version}_{device}"

    # Check cache
    if not force_reload and cache_key in _MODEL_CACHE:
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3] Using cached model: {model_version}")
        print(f"{'='*60}\n")
        return _MODEL_CACHE[cache_key]

    # Get model path (download if needed)
    model_path = get_model_path(model_version, download_source, force_redownload)

    # Load model
    model = load_cosyvoice_model(model_path, device)

    # Detect model version for nodes to use
    version_lower = model_version.lower()
    is_cosyvoice3 = "cosyvoice3" in version_lower or "fun-cosyvoice3" in version_lower
    is_cosyvoice2 = "cosyvoice2" in version_lower and not is_cosyvoice3

    # Create model info dict
    model_info = {
        "model": model,
        "model_name": model_version,
        "model_version": model_version,
        "model_path": model_path,
        "device": device,
        "sample_rate": model.sample_rate,  # Use actual model sample rate (24000 for v2/v3, 22050 for v1)
        "is_cosyvoice3": is_cosyvoice3,
        "is_cosyvoice2": is_cosyvoice2,
    }

    print(f"[XB CosyVoice3] Model sample rate: {model.sample_rate} Hz")
    print(f"[XB CosyVoice3] Model type: {'CosyVoice3' if is_cosyvoice3 else 'CosyVoice2' if is_cosyvoice2 else 'CosyVoice v1'}")

    # Cache model
    _MODEL_CACHE[cache_key] = model_info

    return model_info


def clear_model_cache():
    """Clear the model cache"""
    global _MODEL_CACHE
    _MODEL_CACHE.clear()
    print(f"\n{'='*60}")
    print(f"[XB CosyVoice3] Model cache cleared")
    print(f"{'='*60}\n")
