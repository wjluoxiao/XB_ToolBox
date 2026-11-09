"""
XB-ToolBox 节点状态开关
======================
源自 ComfyUI-DaSiWa-Nodes 的 NodeStatusSwitch，经授权移植。

功能：通过 boolean 开关对目标节点执行"静音(mute)"或"绕过(bypass)"操作。
支持开关串联（enabled_out → enabled 输入），动态目标槽位自动扩展。
"""


class AnyType(str):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    def __hash__(self):
        return hash("*")


ANY = AnyType("*")


class XB_NodeStatusSwitch:
    """节点状态开关 — 通过 boolean 控制目标节点的 mute/bypass 状态。
    目标节点通过将任意输出连线到本节点的 target_XX 输入来绑定。
    支持多个开关串联：enabled_out 连接下游开关的 enabled 输入。"""

    DESCRIPTION = (
        "XB 节点状态开关：基于 boolean 状态对连接的目标节点执行静音或绕过操作，"
        "支持开关串联（enabled_out 可链接下游开关）。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "enabled": ("BOOLEAN", {"default": True,
                    "description": "主开关：激活/停用切换器"}),
                "trigger_on": (
                    ["true → active", "false → active"],
                    {"default": "true → active",
                     "description": "定义 boolean 为 True 还是 False 时处于激活状态"},
                ),
                "action": (["mute", "bypass"], {"default": "bypass",
                    "description": "选择 Mute（停止执行）或 Bypass（透传）目标节点"}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("BOOLEAN",)
    RETURN_NAMES = ("enabled_out",)
    FUNCTION = "execute"
    CATEGORY = "XB_ToolBox/Utils"
    OUTPUT_NODE = False

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def validate_inputs(self, *args, **kwargs):
        return True

    def execute(self, enabled, trigger_on, action, unique_id=None, **kwargs):
        return (bool(enabled),)
