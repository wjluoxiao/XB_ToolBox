"""
XB-BOX Canvas Label — 画布文字标签节点
======================================
纯展示型节点，用于在工作流画布上添加说明文字。
所有渲染逻辑由前端 JS (xb_label.js) 处理。
"""


# ============================================================
# XB_CanvasLabel — 画布文字标签
# ============================================================
class XB_CanvasLabel:
    """纯显示标签节点 - 在画布上展示自定义文字，兼容所有 ComfyUI 版本"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "XB_ToolBox/Display"

    def noop(self, **kwargs):
        return ()
