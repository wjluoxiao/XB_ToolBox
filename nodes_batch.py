import os
import torch
import numpy as np
import re
from PIL import Image, ImageOps
import folder_paths
import datetime  # 👇 新增：引入 Python 原生时间模块

class XB_BatchFolderLoader:
    """
    文件夹图片接力加载节点 (架构优化版)
    支持自动归档路径输出与友好数量提示
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "directory": ("STRING", {"default": ""}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 9999999, "step": 1, "tooltip": "利用 seed 机制内置的自动步进器"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING")
    RETURN_NAMES = ("IMAGE", "MASK", "FILE_NAME", "TOTAL_COUNT")
    FUNCTION = "load_images"
    CATEGORY = "小白工具箱/批量处理"

    def load_images(self, directory, seed):
        if not os.path.isdir(directory):
            raise FileNotFoundError(f"未找到文件夹: {directory}")

        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.jfif'}
        files = [f for f in os.listdir(directory) if os.path.splitext(f)[1].lower() in valid_extensions]
        
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]
        
        files.sort(key=natural_sort_key)
        
        if not files:
            raise Exception(f"文件夹内没有有效图片: {directory}")

        total_count = len(files)
        current_file_idx = seed % total_count
        file_path = os.path.join(directory, files[current_file_idx])
        
        # 1. 提取原始文件名（不含后缀）
        raw_name = os.path.splitext(files[current_file_idx])[0]
        
        # 2. 获取真实的系统当天日期 (格式：2026-04-15)
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 3. 注入纯净的路径前缀，彻底绕过 ComfyUI 的解析坑
        formatted_file_name = f"图片/批量处理/{today_str}/{raw_name}"

        # 4. 构造友好的数量提示字符串
        total_count_display = f"检测到图片总数为：{total_count}"

        img = Image.open(file_path)
        img = ImageOps.exif_transpose(img)
        image = img.convert("RGB")
        image = np.array(image).astype(np.float32) / 255.0
        image = torch.from_numpy(image)[None,]

        if 'A' in img.getbands():
            mask = np.array(img.getchannel('A')).astype(np.float32) / 255.0
            mask = 1. - torch.from_numpy(mask)
        else:
            mask = torch.zeros((64, 64), dtype=torch.float32)

        return (image, mask, formatted_file_name, total_count_display)