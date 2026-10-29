import os
import torch
import numpy as np
import re
from PIL import Image, ImageOps
import folder_paths
import datetime 

from .nodes_batch_images import batch_images

VALID_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.jfif'}


def _natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]


def _list_image_files(directory):
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"Directory not found: {directory}")
    files = [f for f in os.listdir(directory) if os.path.splitext(f)[1].lower() in VALID_EXTENSIONS]
    files.sort(key=_natural_sort_key)
    return files


def _load_image_tensor(file_path):
    """读取单张图片 → (1, H, W, C) float32 张量。"""
    img = Image.open(file_path)
    img = ImageOps.exif_transpose(img)
    image = img.convert("RGB")
    image = np.array(image).astype(np.float32) / 255.0
    return torch.from_numpy(image)[None,]


# ============================================================
# XB_BatchFolderLoader — 图片序列加载（单张步进）
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


# ============================================================
# XB_BatchFolderBatchLoader — 图片批量加载（一次读取多张）
# ============================================================
class XB_BatchFolderBatchLoader:
    """选择文件夹后一次性批量加载多张图片，合并成一个图像批次传给下游（等价于批量图像节点接多张图）。"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "directory": ("STRING", {"default": ""}),
                "count": ("INT", {"default": 4, "min": 1, "max": 500, "step": 1,
                                  "tooltip": "本次批量加载的图片数量"}),
                "skip": ("INT", {"default": 0, "min": 0, "max": 999999, "step": 1,
                                 "tooltip": "跳过前 N 张，便于多次分批处理"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("IMAGES",)
    FUNCTION = "load_batch"
    CATEGORY = "XB_ToolBox/Batch_Process"

    def load_batch(self, directory, count, skip):
        files = _list_image_files(directory)
        if not files:
            raise Exception(f"No valid images found in directory: {directory}")

        selected = files[skip:skip + count]
        if not selected:
            raise Exception(
                f"No images left: skipped {skip} of {len(files)} images in {directory}"
            )

        images = [_load_image_tensor(os.path.join(directory, f)) for f in selected]
        return (batch_images(images),)