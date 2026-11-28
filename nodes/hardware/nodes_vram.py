import torch
import gc
import time
import comfy.model_management as mm

# ============================================================
# XTX_Data_Radar — 数据雷达扫描
# ============================================================
class XTX_Data_Radar:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "latent": ("LATENT",),
            },
            "optional": {
                "positive_cond": ("CONDITIONING",),
                "negative_cond": ("CONDITIONING",),
            }
        }
    
    RETURN_TYPES = ("MODEL", "LATENT")
    RETURN_NAMES = ("model", "latent")
    FUNCTION = "scan_data"
    CATEGORY = "XB_ToolBox/VRAM_Hacks"

    def scan_data(self, model, latent, positive_cond=None, negative_cond=None):
        print("\n" + "=" * 35)
        print(f"🪞 [XB-BOX] Data Generation Radar Scan 🔍")
        print("-" * 35)
        
        if "samples" in latent:
            samples = latent["samples"]
            size_mb = (samples.element_size() * samples.nelement()) / (1024 * 1024)
            print(f"📦 Latent: {size_mb:.2f} MB")
            print(f"📐 Shape: {list(samples.shape)}")
        
        def get_cond_weight(cond):
            total_size = 0
            if cond is not None:
                for c in cond:
                    if isinstance(c, list) and len(c) > 0:
                        # c[0]: 交叉注意力条件张量
                        tensor = c[0]
                        if isinstance(tensor, torch.Tensor):
                            total_size += tensor.element_size() * tensor.nelement()
                        # c[1]: 字典，含 pooled_output / ControlNet / GLIGEN 等重型特征
                        if len(c) > 1 and isinstance(c[1], dict):
                            for _k, _v in c[1].items():
                                if isinstance(_v, torch.Tensor):
                                    total_size += _v.element_size() * _v.nelement()
            return total_size / (1024 * 1024)

        pos_w = get_cond_weight(positive_cond)
        neg_w = get_cond_weight(negative_cond)
        print(f"✅ Positive Cond Weight: {pos_w:.2f} MB")
        print(f"❌ Negative Cond Weight: {neg_w:.2f} MB")
        print("-" * 35)
        
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / (1024**3)
            reserved = torch.cuda.memory_reserved() / (1024**3)
            print(f"🔥 GPU Current Allocated: {allocated:.2f} GB")
            print(f"🛡️ GPU Current Reserved:  {reserved:.2f} GB")
        print("=" * 35 + "\n")
        
        return (model, latent)


# ============================================================
# XB_VRAM_Cleanup — 显存/内存占用清理（任意输入 → 任意输出 直通）
# ============================================================
def _gb(n):
    return f"{n / (1024 ** 3):.2f}GB"


def _vram_stats():
    """返回 (可用显存字节, 显存总量字节, torch已分配, torch已预留)"""
    free = total = alloc = reserved = 0
    try:
        free = mm.get_free_memory()
    except Exception:
        pass
    try:
        if torch.cuda.is_available():
            free_dev, total = torch.cuda.mem_get_info()
            if not free:
                free = free_dev
            alloc = torch.cuda.memory_allocated()
            reserved = torch.cuda.memory_reserved()
    except Exception:
        pass
    return free, total, alloc, reserved


def _ram_used():
    try:
        import psutil
        return psutil.virtual_memory().used, psutil.virtual_memory().total
    except Exception:
        return 0, 0


def _loaded_model_names():
    try:
        return [type(m.model.model).__name__ for m in mm.current_loaded_models if m.model is not None]
    except Exception:
        return []


class XB_VRAM_Cleanup:
    """占用清理节点：清理后把输入原样传出，用于在流程中途/末尾释放内存与显存。

    两个开关：
      - clean_ram（内存清理）：gc.collect()，回收被引用环/中间变量占住的 CPU 内存。
      - clean_vram（显存清理）：卸载所有已加载模型 + soft_empty_cache()，
          真正腾出显存（soft_empty_cache 兼容 CUDA/XPU/NPU/MLU/MPS 并调用 ipc_collect）。
          代价是下一次推理需要重新加载模型。

    清理顺序为 卸载模型 → gc → 清空缓存：先让张量真正释放，再回收缓存块最有效。
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "clean_ram": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "内存清理：Python 垃圾回收，释放被中间变量/引用环占住的 CPU 内存",
                }),
                "clean_vram": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "显存清理：卸载所有已加载模型并清空显存缓存（回收最多，下次使用需重新加载模型）",
                }),
            },
            "optional": {
                "any_input": ("*", {
                    "tooltip": "任意输入，清理后原样从 any_output 输出（仅作触发/直通）",
                }),
            },
        }

    RETURN_TYPES = ("*", "INT", "INT")
    RETURN_NAMES = ("any_output", "free_before_mb", "free_after_mb")
    FUNCTION = "cleanup"
    CATEGORY = "XB_ToolBox/VRAM_Hacks"
    OUTPUT_NODE = True
    DESCRIPTION = ("清理内存/显存占用后把输入原样输出。可单独作为流程末尾的清理动作，"
                   "也可串在流程中间作为触发节点。")

    def cleanup(self, clean_ram=True, clean_vram=True, any_input=None, **kwargs):
        t0 = time.perf_counter()
        free_before, total, alloc_before, reserved_before = _vram_stats()
        ram_before, _ = _ram_used()
        models_before = _loaded_model_names()

        unloaded = 0
        if clean_vram and models_before:
            try:
                mm.unload_all_models()
                unloaded = len(models_before)
            except Exception as e:
                print(f"[XB 占用清理] ⚠️ 卸载模型失败: {e}")

        if clean_ram:
            gc.collect()
            print("[XB 占用清理] 内存清理完毕。")

        if clean_vram:
            try:
                mm.soft_empty_cache()
            except Exception as e:
                print(f"[XB 占用清理] ⚠️ 清空显存缓存失败: {e}")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            print("[XB 占用清理] 显存清理完毕。")

        free_after, _, alloc_after, reserved_after = _vram_stats()
        ram_after, _ = _ram_used()
        models_after = _loaded_model_names()

        freed_vram = max(0, free_after - free_before)
        freed_ram = max(0, ram_before - ram_after)

        lines = [f"🧹 占用清理（{time.perf_counter() - t0:.2f}s）"]
        if clean_ram:
            lines.append(f"内存：已用 {_gb(ram_before)} → {_gb(ram_after)}（释放 {_gb(freed_ram)}）")
        if clean_vram:
            lines.append(f"显存：空闲 {_gb(free_before)} → {_gb(free_after)}（释放 {_gb(freed_vram)}）")
            lines.append(f"    torch 已分配 {_gb(alloc_before)} → {_gb(alloc_after)}，"
                         f"预留 {_gb(reserved_before)} → {_gb(reserved_after)}")
            if unloaded:
                lines.append(f"已加载模型：{len(models_before)} → {len(models_after)}")
        report = "\n".join(lines)

        return {
            "ui": {"text": [report]},
            "result": (any_input, int(free_before / (1024 ** 2)), int(free_after / (1024 ** 2))),
        }