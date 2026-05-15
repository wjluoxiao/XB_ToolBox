import torch
import gc
import comfy.model_management as mm

class XTX_VRAM_Cleaner:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "latent_image": ("LATENT",),
                "Nuclear_Cleanup": ("BOOLEAN", {"default": True}),
            }
        }
    
    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("model", "positive", "negative", "latent")
    FUNCTION = "clean_vram"
    CATEGORY = "XB_ToolBox/VRAM_Hacks"

    def clean_vram(self, model, positive, negative, latent_image, Nuclear_Cleanup):
        print("\n" + "🚀" * 15)
        print("🧹 [XB-BOX] VRAM Cleaner: Executing pre-generation sweep...")
        mm.unload_all_models() 
        gc.collect()
        if Nuclear_Cleanup:
            mm.soft_empty_cache()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                if hasattr(torch.cuda, "ipc_collect"):
                    torch.cuda.ipc_collect()
            print("☢️ [XB-BOX] Nuclear VRAM Cleanup completed.")
        print("🚀" * 15 + "\n")
        return (model, positive, negative, latent_image)

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
                        tensor = c[0]
                        if isinstance(tensor, torch.Tensor):
                            total_size += tensor.element_size() * tensor.nelement()
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