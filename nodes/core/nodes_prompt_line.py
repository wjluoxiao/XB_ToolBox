"""
XB-BOX 提示词多行节点
=====================
复刻 ComfyUI-Easy-Use 的 promptLine（提示词行），完全独立实现，不依赖 easy-use。
把多行文本按行拆成列表输出，可设起始行 / 最大行数 / 去除空行，
下游接到任意列表消费节点即可逐行处理。
"""


class XB_PromptLine:
    """提示词多行 — 多行文本 → 逐行列表输出。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"default": "text", "multiline": True}),
                "start_index": ("INT", {"default": 0, "min": 0, "max": 9999, "step": 1,
                                        "tooltip": "从第几行开始取（0 = 第一行）"}),
                "max_rows": ("INT", {"default": 1000, "min": 1, "max": 9999, "step": 1,
                                     "tooltip": "最多输出多少行"}),
                "remove_empty_lines": ("BOOLEAN", {"default": True,
                                                  "tooltip": "先剔除空白行再按行切分"}),
            }
        }

    RETURN_TYPES = ("STRING", "*")
    RETURN_NAMES = ("字符串", "COMBO")
    OUTPUT_IS_LIST = (True, True)
    FUNCTION = "split_lines"
    CATEGORY = "XB_ToolBox/Text"
    DESCRIPTION = (
        "提示词多行（参考 Easy-Use 提示词行）：把多行文本按行切成列表输出，"
        "每行一项。可设起始行、最大行数，并可先剔除空行。\n"
        "「字符串」输出为 STRING 列表，「COMBO」输出为任意类型列表，"
        "用于把下拉选项逐项喂给需要 combo 值的节点。"
    )

    def split_lines(self, prompt, start_index, max_rows, remove_empty_lines=True):
        lines = (prompt or "").split("\n")

        if remove_empty_lines:
            lines = [line for line in lines if line.strip()]

        if not lines:
            return ([], [])

        start_index = max(0, min(start_index, len(lines) - 1))
        rows = lines[start_index:start_index + max_rows]
        return (rows, rows)
