import os
import torch
import numpy as np
import re
from PIL import Image, ImageOps
import folder_paths
import datetime 

# ============================================================
# XB_BatchFolderLoader — 批量文件夹加载器
# ============================================================
class XB_BatchFolderLoader:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "directory": ("STRING", {"default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 9999999, "step": 1, "tooltip": "Built-in auto-stepper using the seed mechanism"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING")
    RETURN_NAMES = ("IMAGE", "MASK", "FILE_NAME", "TOTAL_COUNT")
    FUNCTION = "load_images"
    CATEGORY = "XB_ToolBox/Batch_Process"

    def load_images(self, directory, seed):
        if not os.path.isdir(directory):
            raise FileNotFoundError(f"Directory not found: {directory}")

        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.jfif'}
        files = [f for f in os.listdir(directory) if os.path.splitext(f)[1].lower() in valid_extensions]
        
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]
        
        files.sort(key=natural_sort_key)
        
        if not files:
            raise Exception(f"No valid images found in directory: {directory}")

        total_count = len(files)
        current_file_idx = seed % total_count
        file_path = os.path.join(directory, files[current_file_idx])
        
        raw_name = os.path.splitext(files[current_file_idx])[0]
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        formatted_file_name = f"Images/Batch/{today_str}/{raw_name}"
        total_count_display = f"Total images detected: {total_count}"

        img = Image.open(file_path)
        img = ImageOps.exif_transpose(img)
        image = img.convert("RGB")
        image = np.array(image).astype(np.float32) / 255.0
        image = torch.from_numpy(image)[None,]

        if 'A' in img.getbands():
            mask = np.array(img.getchannel('A')).astype(np.float32) / 255.0
            mask = 1. - torch.from_numpy(mask)
            mask = mask.unsqueeze(0)  # (H, W) → (1, H, W)
        else:
            mask = torch.zeros((1, image.shape[1], image.shape[2]), dtype=torch.float32)

        return (image, mask, formatted_file_name, total_count_display)