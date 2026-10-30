"""XB-BOX - 🖼️ 生图提示词预设（图）—— 生图提示词预设 + 姿态参考图 + 穿搭参考图
=================================================================
完全**继承** nodes_image_prompt_preset.XB_ImagePromptPreset 的参数与拼词逻辑：
· 表面参数 / 8 大元素面板 / 预设文件 / 空 latent 规格 / 画幅联动，一行都不改；
· 只额外做两件事：
    ① 多两个内部字段 pose_ref / outfit_ref（前端隐藏，由「🎬 姿态参考图选择 /
       👚 穿搭参考图选择」按钮写入，值 = JSON {"path": 库内相对路径, "name": 展示名}，
       随工作流保存）；
    ② 多两个 IMAGE 输出「姿态图 / 穿搭图」，执行时从用户自行绑定的图库读图
       （带素材清单的整套图库或普通图片文件夹都支持，见 xb_gallery.py）。
"""

from . import xb_gallery
from .nodes_image_prompt_preset import XB_ImagePromptPreset

_REF_TOOLTIP = ("内部字段（节点表面不显示）：由「参考图选择」按钮写入的图库相对路径 JSON；"
                "随工作流保存，换机器 / 换图库后需重新选择。")


class XB_ImagePreset(XB_ImagePromptPreset):
    """生图预设：生图提示词预设的全部能力 + 姿态 / 穿搭参考图输出。"""

    @classmethod
    def INPUT_TYPES(cls):
        data = super().INPUT_TYPES()
        # 追加在 manager_settings 之后 → 不影响老工作流 widgets_values 的顺序
        data["required"]["pose_ref"] = ("STRING", {"default": "", "tooltip": _REF_TOOLTIP})
        data["required"]["outfit_ref"] = ("STRING", {"default": "", "tooltip": _REF_TOOLTIP})
        return data

    RETURN_TYPES = ("STRING", "LATENT", "IMAGE", "IMAGE")
    RETURN_NAMES = ("提示词", "空latent", "姿态图", "穿搭图")
    FUNCTION = "generate"
    CATEGORY = "XB_ToolBox/Image_Params"
    DESCRIPTION = ("生图预设：在「生图提示词预设」的全部能力（空latent类型 + 画幅比例/宽高/数量 + 8 大类元素面板拼词 + "
                   "预设文件）之上，新增「🎬 姿态参考图选择 / 👚 穿搭参考图选择」两个按钮：可绑定带素材清单的整套图库"
                   "（按体系/分类/视角/标签筛选，按姿势编号分组并带视角条）或任意普通图片文件夹（按文件名多宫格）。"
                   "参考图可单独勾选「禁用」：禁用后该输出不做任何输出（等同 mute），下游节点会被跳过。"
                   "输出：①提示词 ②空latent ③姿态图 ④穿搭图。")

    @classmethod
    def IS_CHANGED(cls, manager_settings="", pose_ref="", outfit_ref="", **kwargs):
        base = super().IS_CHANGED(manager_settings=manager_settings, **kwargs)
        return (f"{base}|{pose_ref}|{outfit_ref}"
                f"|{xb_gallery.fingerprint('pose', pose_ref)}"
                f"|{xb_gallery.fingerprint('costume', outfit_ref)}")

    def generate(self, output_lang, preset_mode, latent_kind, three_view_text, aspect_ratio,
                 width, height, batch_size, internal_prompt="", manager_settings="",
                 pose_ref="", outfit_ref=""):
        prompt, latent = super().generate(
            output_lang=output_lang, preset_mode=preset_mode, latent_kind=latent_kind,
            three_view_text=three_view_text, aspect_ratio=aspect_ratio, width=width,
            height=height, batch_size=batch_size, internal_prompt=internal_prompt,
            manager_settings=manager_settings)
        return (prompt, latent,
                xb_gallery.load_reference("pose", pose_ref),
                xb_gallery.load_reference("costume", outfit_ref))


NODE_CLASS_MAPPINGS = {"XB_ImagePreset": XB_ImagePreset}
NODE_DISPLAY_NAME_MAPPINGS = {"XB_ImagePreset": "XB-BOX - 🖼️ 生图提示词预设（图）"}
