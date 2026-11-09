"""
XB-PlaySound — 播放声音节点
============================
复刻自 ComfyUI-Custom-Scripts (pysssss) 的 PlaySound 节点，完全独立运行。

特点:
  - 零外部依赖（不引用本仓库其它模块，也不依赖 ComfyUI-Custom-Scripts）
  - 自带 notify.mp3 音频资源 (js/assets/notify.mp3)
  - 透传任意类型输入，仅作为"执行完成提示音"挂载点

用法:
  把本节点接在工作流末端（任意数据连入 any 端口），
  queue 执行到该节点时，浏览器会播放指定音效。

选项:
  mode = "always"          每次执行都播放
  mode = "on empty queue"  仅当队列全部跑完后播放（批量出图只响一次）
"""


# ══════════════════════════════════════════════════════════
#  通配类型（永远不相等，避免 ComfyUI 类型校验拦截）
# ══════════════════════════════════════════════════════════

class _AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False

    def __repr__(self) -> str:
        return "*"


ANY = _AnyType("*")


# ══════════════════════════════════════════════════════════
#  XB_PlaySound
# ══════════════════════════════════════════════════════════

class XB_PlaySound:
    """播放声音 — 工作流执行提示音。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "any": (ANY, {"tooltip": "任意类型输入，仅用于挂载到工作流执行链上（数据原样透传）"}),
                "mode": (["always", "on empty queue"], {
                    "default": "always",
                    "tooltip": "always: 每次执行都播放\non empty queue: 仅当整个队列跑完后播放一次（批量出图只响一次）",
                }),
                "volume": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.1,
                    "tooltip": "播放音量 (0.0 ~ 1.0)",
                }),
                "file": ("STRING", {
                    "default": "notify.mp3", "multiline": False,
                    "tooltip": "音频文件名（默认读取 js/assets/notify.mp3）\n"
                               "可填: notify.mp3 / 子目录/xx.wav / https://... 完整网址",
                }),
            }
        }

    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("any",)
    OUTPUT_IS_LIST = (True,)
    INPUT_IS_LIST = True
    OUTPUT_NODE = True
    FUNCTION = "nop"
    CATEGORY = "XB_ToolBox/Utils"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 永远视为已变更 → 每次都执行（提示音必须每次都响）
        return float("NaN")

    def nop(self, any, mode, volume, file):
        # 数据透传；前端 onExecuted 负责播放音频
        return {"ui": {"a": []}, "result": (any,)}


# ══════════════════════════════════════════════════════════
#  节点注册
# ══════════════════════════════════════════════════════════

NODE_CLASS_MAPPINGS = {
    "XB_PlaySound": XB_PlaySound,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_PlaySound": "XB-BOX - 🔊 播放声音",
}
