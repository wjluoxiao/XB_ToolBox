"""
XB-BOX 快速开关（参考 rgthree-comfy 的 Fast Muter / Fast Groups Muter / Any Switch）
=================================================================================
三个节点：

① XB_DisableGroups —— 禁用分组
   · **不接线**：在节点面板/右键菜单里勾选要控制的分组（可以随时增删）；
   · 点一行 = 把该分组里的所有节点一次性「静音 / 恢复」；
   · 与 rgthree「禁用框」一致：状态直接读写画布上节点自己的 mode（随工作流保存）。

② XB_DisableNodes —— 禁用节点
   · **不接线**：右击勾选要控制的节点（支持按分组整组加入）；
   · 点一行 = 把该节点「静音 / 绕过 / 恢复」；
   · 与 rgthree「禁用节点」一致，但不占用输入端口、不需要拖线绑定。

③ XB_AnySwitch —— 切换任意
   · 动态任意类型输入（默认 any_01 / any_02，连满自动追加）；
   · 与 rgthree「任意切换」完全一致：没有选择控件，永远输出第一个非空输入。

⚠️ 前两个节点**只在前端工作**（控制别的节点的 mode），Python 端不参与执行：
   它们没有任何输入输出，ComfyUI 不会把它们放进执行队列。
"""


class AnyType(str):
    """一个永远“等于”任何类型的占位类型（credit: pythongosssss / rgthree）"""

    def __ne__(self, other):
        return False

    def __eq__(self, other):
        return True

    def __hash__(self):
        return hash("*")


class FlexibleOptionalInputType(dict):
    """让 optional 输入可以无限扩展（任何名字都视为存在，类型由构造时指定）。"""

    def __init__(self, type_, data=None):
        self.type_ = type_
        self.data = data
        if self.data is not None:
            for k, v in self.data.items():
                self[k] = v

    def __getitem__(self, key):
        if self.data is not None and key in self.data:
            return self.data[key]
        return (self.type_,)

    def __contains__(self, key):
        return True


any_type = AnyType("*")


class XB_DisableGroups:
    """禁用分组：不接线，勾选分组后一键静音 / 恢复整组节点。"""

    DESCRIPTION = (
        "禁用分组（参考 rgthree 禁用框）：不接线，在面板或右键菜单里勾选要控制的分组；"
        "点一行即可把该分组内所有节点静音 / 绕过 / 恢复。状态直接写在画布的节点上，随工作流保存。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "XB_ToolBox/Utils"
    OUTPUT_NODE = False

    def noop(self):
        """纯前端控制节点，执行时什么都不做。"""
        return {}


class XB_DisableNodes:
    """禁用节点：不接线，勾选节点（可按分组整组加入）后一键静音 / 绕过 / 恢复。"""

    DESCRIPTION = (
        "禁用节点（参考 rgthree 禁用节点）：不接线，在面板或右键菜单里勾选要控制的节点（支持按分组整组加入）；"
        "点一行即可静音 / 绕过 / 恢复该节点。状态直接写在画布的节点上，随工作流保存。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "XB_ToolBox/Utils"
    OUTPUT_NODE = False

    def noop(self):
        return {}


class XB_AnySwitch:
    """切换任意：动态任意类型输入，直接输出第一个非空输入（无选择控件）。"""

    DESCRIPTION = (
        "切换任意（参考 rgthree 任意切换）：把不同来源接到任意类型的输入端口，端口会随连线自动增加；"
        "节点没有选择控件，永远输出从上往下第一个非空的输入。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": FlexibleOptionalInputType(any_type),
        }

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("*",)
    FUNCTION = "switch"
    CATEGORY = "XB_ToolBox/Utils"
    OUTPUT_NODE = False

    @staticmethod
    def _items(kwargs):
        items = [(k, v) for k, v in kwargs.items() if isinstance(k, str) and k.startswith("any_")]
        items.sort(key=lambda kv: kv[0])
        return items

    @staticmethod
    def _is_empty(value):
        if value is None:
            return True
        # 上下文为空时的兜底（与 rgthree 一致）
        if isinstance(value, dict) and "model" in value and "clip" in value:
            return all(v is None for v in value.values())
        return False

    def switch(self, **kwargs):
        """取第一个非空输入（与 rgthree Any Switch 同行为）。"""
        for _k, value in self._items(kwargs):
            if not self._is_empty(value):
                return (value,)
        return (None,)


NODE_CLASS_MAPPINGS = {
    "XB_DisableGroups": XB_DisableGroups,
    "XB_DisableNodes": XB_DisableNodes,
    "XB_AnySwitch": XB_AnySwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_DisableGroups": "XB-BOX - 🚫 禁用分组",
    "XB_DisableNodes": "XB-BOX - 🚫 禁用节点",
    "XB_AnySwitch": "XB-BOX - 🔀 切换任意",
}
