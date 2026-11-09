"""
XB-BOX 字符串合并节点
====================
基于 ComfyUI-KJNodes 的 JoinStringMulti 节点进行重构，
增加「每段换行」选项。
"""


# ============================================================
# XB_StringMerge — 字符串合并（多重）
# ============================================================
class XB_StringMerge:
    """合并多个输入字符串为单个字符串，支持自定义分隔符和每段换行"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "inputcount": ("INT", {"default": 2, "min": 2, "max": 1000, "step": 1}),
                "string_1": ("STRING", {"default": "", "forceInput": True}),
                "delimiter": ("STRING", {"default": " ", "multiline": False}),
                "return_list": ("BOOLEAN", {"default": False}),
                "newline_per_segment": ("BOOLEAN", {"default": False, "tooltip": "每段换行：打开后，每段输入字符串将换行排列"}),
            },
            "optional": {
                "string_2": ("STRING", {"default": "", "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("string",)
    OUTPUT_IS_LIST = (True,)  # return_list=True 时返回 Python list，须告知 ComfyUI 引擎
    FUNCTION = "combine"
    CATEGORY = "XB_ToolBox/Text"
    DESCRIPTION = (
        "合并多个字符串输入。\n"
        "可以设置输入数量，点击「Update inputs」来增加更多插槽。\n"
        "分隔符：指定连接字符串的分隔符。\n"
        "输出为列表：开启后返回字符串列表而非合并后的单一字符串。\n"
        "每段换行：开启后忽略分隔符，每段字符串用换行符连接。"
    )

    def combine(self, inputcount, delimiter, return_list, newline_per_segment, **kwargs):
        string = kwargs.get("string_1", "")
        strings = [string]  # Initialize a list with the first string

        # 如果开启了每段换行，使用换行符作为实际分隔符
        actual_delimiter = "\n" if newline_per_segment else delimiter

        for c in range(1, inputcount):
            new_string = kwargs.get(f"string_{c + 1}", "")
            if not new_string:
                continue
            if return_list:
                strings.append(new_string)  # Add new string to the list
            else:
                string = string + actual_delimiter + new_string

        if return_list:
            return (strings,)  # Return the list of strings
        else:
            return (string,)  # Return the combined string
