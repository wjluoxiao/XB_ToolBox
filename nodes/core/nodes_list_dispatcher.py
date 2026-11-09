"""
XB-ToolBox 列表分发节点
========================
上游 STRING 列表输入（接线端口），按行拆分后分发到 N 个输出端口。
通过"更新输出"按钮动态管理输出数量（最多99个）。
"""


class XB_ListDispatcher:
    """列表分发 — 列表输入 → 拆行 → 动态输出。"""

    MAX_OUTPUTS = 99
    INPUT_IS_LIST = True  # 复刻 Show Text 🐍：统一以列表接收上游数据

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "列表输入": ("STRING", {"forceInput": True}),
                "输出数量": ("INT", {"default": 3, "min": 1, "max": cls.MAX_OUTPUTS, "step": 1}),
            },
        }

    RETURN_TYPES = ("STRING",) * MAX_OUTPUTS
    RETURN_NAMES = tuple(f"文本{i+1}" for i in range(MAX_OUTPUTS))
    FUNCTION = "dispatch"
    CATEGORY = "XB_ToolBox/Utils"

    def dispatch(self, 列表输入, 输出数量):
        # INPUT_IS_LIST=True 时所有参数都是列表，取第一个整形值
        count = int(输出数量[0]) if isinstance(输出数量, list) else int(输出数量)

        # 列表输入必定是 list：拼合 → 标准化切分
        text = "\n".join([str(item) for item in 列表输入])
        text = text.replace("\\n", "\n").replace("\\r", "\n")
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        results = []
        ui_displays = []

        for i in range(self.MAX_OUTPUTS):
            if i < count:
                val = lines[i] if i < len(lines) else ""
            else:
                val = ""
            results.append(val)
            if i < count:
                ui_displays.append(val)

        return {"ui": {"displays": ui_displays}, "result": tuple(results)}
