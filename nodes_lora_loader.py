"""
XB-BOX 三连 LoRA 加载
=====================
两个节点，都是「三个官方 LoRA 加载节点串联」的套皮：

· XB_TripleLoraLoader            —— 串联三个官方 Load LoRA (Model and CLIP)：输入 model + clip，输出 MODEL + CLIP
· XB_TripleLoraLoaderModelOnly   —— 串联三个官方 Load LoRA（仅模型）：输入 model，输出 MODEL

每个槽位的 LoRA 下拉都多一个「关闭」选项：选中即跳过该槽位（不加载、不改变模型）。
前者每个槽位的强度同时作用于 MODEL 与 CLIP（strength_model = strength_clip）。
"""

import copy

import nodes


_OFF = "关闭"


class XB_TripleLoraLoader:
    """三连 LoRA — 三个官方 Load LoRA 串联，任一槽位可选「关闭」跳过。"""

    def __init__(self):
        # 官方实例只缓存「最后一次」加载的 LoRA，所以每个槽位各用一个实例
        self._loaders = [nodes.LoraLoader() for _ in range(3)]

    @classmethod
    def INPUT_TYPES(cls):
        base = copy.deepcopy(nodes.LoraLoader.INPUT_TYPES()["required"])
        loras = [_OFF] + [name for name in base["lora_name"][0] if name != _OFF]
        strength_def = copy.deepcopy(base["strength_model"])

        required = {
            "model": copy.deepcopy(base["model"]),
            "clip": copy.deepcopy(base["clip"]),
        }
        for i in (1, 2, 3):
            required[f"lora_{i:02d}"] = (loras, {
                "default": _OFF,
                "tooltip": f"LORA-{i:02d}：选择「关闭」= 跳过该槽位",
            })
            required[f"strength_{i:02d}"] = copy.deepcopy(strength_def)
        return {"required": required}

    RETURN_TYPES = ("MODEL", "CLIP")
    RETURN_NAMES = ("MODEL", "CLIP")
    FUNCTION = "load"
    CATEGORY = "XB_ToolBox/原版优化"
    DESCRIPTION = (
        "等效于串联三个官方 Load LoRA 节点。\n"
        "每个槽位（LORA-01 / LORA-02 / LORA-03）选择「关闭」时直接跳过，不加载也不改模型。\n"
        "强度同时作用于 MODEL 与 CLIP（官方节点的 strength_model = strength_clip）。"
    )

    def load(self, model, clip, lora_01=_OFF, strength_01=1.0,
             lora_02=_OFF, strength_02=1.0, lora_03=_OFF, strength_03=1.0):
        slots = (
            (lora_01, strength_01),
            (lora_02, strength_02),
            (lora_03, strength_03),
        )
        for idx, (name, strength) in enumerate(slots):
            if not name or name == _OFF:
                continue
            try:
                value = float(strength)
            except (TypeError, ValueError):
                value = 1.0
            model, clip = self._loaders[idx].load_lora(model, clip, name, value, value)
        return (model, clip)


class XB_TripleLoraLoaderModelOnly:
    """三连 LoRA（仅模型）— 三个官方 Load LoRA（仅模型）串联，任一槽位可选「关闭」跳过。"""

    def __init__(self):
        # 官方实例只缓存「最后一次」加载的 LoRA，所以每个槽位各用一个实例
        self._loaders = [nodes.LoraLoaderModelOnly() for _ in range(3)]

    @classmethod
    def INPUT_TYPES(cls):
        base = copy.deepcopy(nodes.LoraLoaderModelOnly.INPUT_TYPES()["required"])
        loras = [_OFF] + [name for name in base["lora_name"][0] if name != _OFF]
        strength_def = copy.deepcopy(base["strength_model"])

        required = {"model": copy.deepcopy(base["model"])}
        for i in (1, 2, 3):
            required[f"lora_{i:02d}"] = (loras, {
                "default": _OFF,
                "tooltip": f"LORA-{i:02d}：选择「关闭」= 跳过该槽位",
            })
            required[f"strength_{i:02d}"] = copy.deepcopy(strength_def)
        return {"required": required}

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("MODEL",)
    FUNCTION = "load"
    CATEGORY = "XB_ToolBox/原版优化"
    DESCRIPTION = (
        "等效于串联三个官方 Load LoRA（仅模型）节点。\n"
        "每个槽位（LORA-01 / LORA-02 / LORA-03）选择「关闭」时直接跳过，不加载也不改模型。"
    )

    def load(self, model, lora_01=_OFF, strength_01=1.0,
             lora_02=_OFF, strength_02=1.0, lora_03=_OFF, strength_03=1.0):
        slots = (
            (lora_01, strength_01),
            (lora_02, strength_02),
            (lora_03, strength_03),
        )
        for idx, (name, strength) in enumerate(slots):
            if not name or name == _OFF:
                continue
            try:
                value = float(strength)
            except (TypeError, ValueError):
                value = 1.0
            model = self._loaders[idx].load_lora_model_only(model, name, value)[0]
        return (model,)
