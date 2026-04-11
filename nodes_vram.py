import torch
import gc
import comfy.model_management as mm

# ======================================================================
# 🧹 显存清理大师 (数据过滤 & 战前清场)
# ======================================================================
class XTX_VRAM_Cleaner:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "latent_image": ("LATENT",),
                "核爆级清理": ("BOOLEAN", {"default": True}),
            }
        }
    
    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("model", "positive", "negative", "latent")
    FUNCTION = "clean_vram"
    CATEGORY = "小白工具箱/显存特攻"

    def clean_vram(self, model, positive, negative, latent_image, 核爆级清理):
        print("\n" + "🚀" * 15)
        print("🧹 [小白工具箱] 显存清理大师：正在执行战前清场...")
        mm.unload_all_models() # 强制卸载无用模型（如 CLIP）
        gc.collect()
        if 核爆级清理:
            mm.soft_empty_cache()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("💥 已执行核爆级清理，显存碎片已彻底蒸发！")
        print("✅ 战场打扫完毕，核心数据已就绪！")
        print("🚀" * 15 + "\n")
        return (model, positive, negative, latent_image)

# ======================================================================
# 🪞 生成数据预览 (升级版：支持正负双条件称重)
# ======================================================================
class XTX_Data_Radar:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "latent": ("LATENT",),
            },
            "optional": {
                "正面条件": ("CONDITIONING",),
                "负面条件": ("CONDITIONING",),
                "标注信息": ("STRING", {"default": "生成数据预览"}),
            }
        }
    
    RETURN_TYPES = ("LATENT", "CONDITIONING", "CONDITIONING", "STRING")
    RETURN_NAMES = ("latent", "positive", "negative", "显存雷达报告")
    FUNCTION = "scan_data"
    CATEGORY = "小白工具箱/数据预览"

    def scan_data(self, latent, 正面条件=None, 负面条件=None, 标注信息=""):
        report = []
        report.append(f"🔍 [{标注信息}] 数据照妖镜扫描 🔍")
        report.append("-" * 35)
        
        if "samples" in latent:
            samples = latent["samples"]
            size_mb = (samples.element_size() * samples.nelement()) / (1024 * 1024)
            report.append(f"📦 潜变量(Latent): {size_mb:.2f} MB")
            report.append(f"📐 形状: {list(samples.shape)}")
        
        def get_cond_weight(cond):
            total_size = 0
            if cond is not None:
                for c in cond:
                    if isinstance(c, list) and len(c) > 0:
                        tensor = c[0]
                        if isinstance(tensor, torch.Tensor):
                            total_size += tensor.element_size() * tensor.nelement()
            return total_size / (1024 * 1024)

        pos_w = get_cond_weight(正面条件)
        neg_w = get_cond_weight(负面条件)
        report.append(f"✅ 正面条件重量: {pos_w:.2f} MB")
        report.append(f"❌ 负面条件重量: {neg_w:.2f} MB")
        report.append("-" * 35)
        
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / (1024**3)
            reserved = torch.cuda.memory_reserved() / (1024**3)
            report.append(f"💻 实际显存占用: {allocated:.2f} GB")
            report.append(f"🔒 系统圈占总量: {reserved:.2f} GB")
            report.append(f"⚠️ 缓存碎片大小: {(reserved - allocated):.2f} GB")
        
        res_str = "\n".join(report)
        print("\n" + res_str + "\n")
        return (latent, 正面条件, 负面条件, res_str)