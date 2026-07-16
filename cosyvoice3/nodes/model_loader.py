"""
XB CosyVoice3 Model Loader Node
Downloads and loads CosyVoice models with automatic weight management
"""

import torch
from typing import Tuple, Dict, Any
import sys
import os

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from ..utils.model_manager import get_cached_model, MODEL_CONFIGS
except (ImportError, ValueError):
    from utils.model_manager import get_cached_model, MODEL_CONFIGS


class XB_CosyVoice3_ModelLoader:
    """
    Load CosyVoice models with automatic downloading and caching
    """

    RETURN_TYPES = ("COSYVOICE_MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "load_model"
    CATEGORY = "🔊XB CosyVoice3/Loaders"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_version": (list(MODEL_CONFIGS.keys()), {
                    "default": "Fun-CosyVoice3-0.5B",
                    "description": "CosyVoice model version to load"
                }),
                "download_source": (["HuggingFace", "ModelScope"], {
                    "default": "HuggingFace",
                    "description": "Source to download model from"
                }),
                "device": (["auto", "cuda", "cpu", "mps"], {
                    "default": "auto",
                    "description": "Device to load model on"
                }),
            },
            "optional": {
                "force_redownload": ("BOOLEAN", {
                    "default": False,
                    "description": "Force re-download even if model exists"
                }),
                "force_reload": ("BOOLEAN", {
                    "default": False,
                    "description": "Force reload model even if cached"
                }),
            }
        }

    def load_model(
        self,
        model_version: str,
        download_source: str = "ModelScope",
        device: str = "auto",
        force_redownload: bool = False,
        force_reload: bool = False
    ) -> Tuple[Dict[str, Any]]:
        """
        Load a CosyVoice model

        Args:
            model_version: Model version to load
            download_source: Download source (ModelScope or HuggingFace)
            device: Target device
            force_redownload: Force re-download
            force_reload: Force reload

        Returns:
            Tuple containing model info dict
        """
        print(f"\n{'='*60}")
        print(f"[XB CosyVoice3 ModelLoader] Loading model...")
        print(f"[XB CosyVoice3 ModelLoader] Version: {model_version}")
        print(f"[XB CosyVoice3 ModelLoader] Source: {download_source}")
        print(f"[XB CosyVoice3 ModelLoader] Device: {device}")
        print(f"{'='*60}\n")

        try:
            # Determine device
            if device == "auto":
                import comfy.model_management
                target_device = comfy.model_management.get_torch_device()
            else:
                target_device = torch.device(device)

            # Get cached model
            model_info = get_cached_model(
                model_version=model_version,
                download_source=download_source,
                device=target_device,
                force_redownload=force_redownload,
                force_reload=force_reload
            )

            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 ModelLoader] Model loaded successfully!")
            print(f"[XB CosyVoice3 ModelLoader] Model: {model_info['model_name']}")
            print(f"[XB CosyVoice3 ModelLoader] Device: {model_info['device']}")
            print(f"[XB CosyVoice3 ModelLoader] Path: {model_info['model_path']}")
            print(f"{'='*60}\n")

            return (model_info,)

        except Exception as e:
            error_msg = f"Error loading model: {str(e)}"
            print(f"\n{'='*60}")
            print(f"[XB CosyVoice3 ModelLoader] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")
            raise RuntimeError(error_msg)
