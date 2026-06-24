import torch
import gc
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