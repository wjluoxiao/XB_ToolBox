"""XB-BOX - 🖼️ 文生图提示词预设 —— 纯提示词版（不带空 latent）。

与「🖼️ 文生图提示词预设 Pro」（nodes_image_prompt_preset.py）同源：
输出语言 / 预设句 / 8 大类元素面板 / 预设文件 / 拼词规则一行不改，
只把 latent 相关的东西全部去掉：

· 没有 latent类型 / 画幅比例 / 宽度 / 高度 / 生成数量；
· 只有一个输出端口「提示词」。

（想同时拿空 latent，请用「🖼️ 文生图提示词预设 Pro」。）
"""

from .nodes_image_prompt_preset import (
    LANG_ZH,
    MODE_TEXT2IMG,
    OUTPUT_LANGS,
    PRESET_MODES,
    XB_ImagePromptPreset,
    _norm_combo,
    build_prompt,
)

# 从父类里摘掉这几个「关于 latent」的输入（顺序保持父类剩余部分不变）
LATENT_FIELDS = ("latent_kind", "aspect_ratio", "width", "height", "batch_size")


class XB_Text2ImagePromptPreset(XB_ImagePromptPreset):
    """文生图提示词预设：只有提示词输出（无 latent 相关参数与端口）。"""

    @classmethod
    def INPUT_TYPES(cls):
        data = super().INPUT_TYPES()
        for key in LATENT_FIELDS:
            data["required"].pop(key, None)
        return data

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("提示词",)
    FUNCTION = "generate"
    CATEGORY = "XB_ToolBox/Image_Params"
    DESCRIPTION = ("文生图提示词预设（纯提示词版）：输出语言 + 8 大类元素面板（风格/视角/主体/姿态/穿搭/道具/光影/背景）"
                   "＋ 预设句 / 预设文件拼装，只输出「提示词」。"
                   "不含 latent类型 / 画幅比例 / 宽高 / 数量，也不输出空 latent（需要空 latent 用「文生图提示词预设 Pro」）。")

    @classmethod
    def VALIDATE_INPUTS(cls, output_lang=None, preset_mode=None):
        """放行下拉参数的历史值 / 错位值（与父类同理，避免老工作流被队列校验丢弃）。"""
        return True

    @classmethod
    def IS_CHANGED(cls, manager_settings="", **kwargs):
        keys = ("output_lang", "preset_mode", "three_view_text", "internal_prompt")
        sig = {k: kwargs.get(k) for k in keys}
        return f"{manager_settings}|{sig}"

    def generate(self, output_lang, preset_mode, three_view_text,
                 internal_prompt="", manager_settings=""):
        output_lang = _norm_combo(output_lang, OUTPUT_LANGS, LANG_ZH)
        preset_mode = _norm_combo(preset_mode, PRESET_MODES, MODE_TEXT2IMG)

        prompt = build_prompt(output_lang, preset_mode, three_view_text, internal_prompt)

        print(f"[XB-文生图提示词预设] 模式 {preset_mode}丨语言 {output_lang}丨提示词 {len(prompt)} 字")
        if prompt:
            print(f"[XB-文生图提示词预设] 提示词：{prompt[:200]}{'…' if len(prompt) > 200 else ''}")

        return (prompt,)


NODE_CLASS_MAPPINGS = {"XB_Text2ImagePromptPreset": XB_Text2ImagePromptPreset}
NODE_DISPLAY_NAME_MAPPINGS = {"XB_Text2ImagePromptPreset": "XB-BOX - 🖼️ 文生图提示词预设"}
