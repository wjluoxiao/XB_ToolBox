"""
XB-ToolBox 引用任意节点
========================
融合 rgthree Fast Muter + Any Switch 的功能。
JS 端管理动态槽位和单选开关，Python 端直通选中的数据。

参照 rgthree-comfy 的 FlexibleOptionalInputType 模式处理动态输入。
"""


class AnyType(str):
    """Credit to pythongosssss / rgthree. Always equals any other type."""
    def __ne__(self, other):
        return False


class FlexibleOptionalInputType(dict):
    """Credit to rgthree-comfy.
    Enables dynamic/flexible input types. __contains__ always returns True,
    and unknown keys return the given type via __getitem__.
    """

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


class XB_ReferenceAny:
    """引用任意 — 动态输入槽，下拉菜单选择活跃的上游节点。
    - 下拉菜单"选择"：手动选择
    - "选择"端口可通过 defaultInput 接受上游 STRING 来控制选择"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "选择": ("STRING", {"default": "全部关闭", "defaultInput": True}),
            },
            "optional": FlexibleOptionalInputType(any_type),
        }

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("输出",)
    FUNCTION = "execute"
    CATEGORY = "XB_ToolBox/Utils"
    OUTPUT_NODE = False

    def execute(self, 选择="", **kwargs):
        # JS 端通过 mode 控制上游节点静音/激活
        # 激活的节点数据会到达 kwargs，静音的不会
        active_input = None
        active_value = None
        for key, value in kwargs.items():
            if value is not None:
                active_input = key
                active_value = value
                break

        if 选择 and 选择 != "全部关闭":
            val_type = type(active_value).__name__ if active_value is not None else "?"
            print(f"[引用任意] 选中 [{选择}] → 上游 [{active_input}] ({val_type}) → 输出")
        elif active_value is not None:
            print(f"[引用任意] 直通 → 上游 [{active_input}] → 输出")

        if active_value is not None:
            return (active_value,)
        return (None,)
