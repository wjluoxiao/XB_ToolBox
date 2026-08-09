"""
MiniMax-H3 一键漫剧创作 — 独立节点包
=====================================
总线信号链: ScriptWriter → ShotFormatter → SceneDispatcher → PromptGenerator
"""

import os as _os
WEB_DIRECTORY = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "js")

from .nodes import (
    XB_MiniMax_ScriptWriter,
    XB_MiniMax_ShotFormatter,
    XB_MiniMax_SceneDispatcher,
    XB_MiniMax_VideoDispatcher,
    XB_MiniMax_AudioDispatcher,
    XB_MiniMax_PromptGenerator,
)

NODE_CLASS_MAPPINGS = {
    "XB_MiniMax_ScriptWriter": XB_MiniMax_ScriptWriter,
    "XB_MiniMax_ShotFormatter": XB_MiniMax_ShotFormatter,
    "XB_MiniMax_SceneDispatcher": XB_MiniMax_SceneDispatcher,
    "XB_MiniMax_VideoDispatcher": XB_MiniMax_VideoDispatcher,
    "XB_MiniMax_AudioDispatcher": XB_MiniMax_AudioDispatcher,
    "XB_MiniMax_PromptGenerator": XB_MiniMax_PromptGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_MiniMax_ScriptWriter": "MiniMax - 🎬 剧本编剧",
    "XB_MiniMax_ShotFormatter": "MiniMax - 📋 分镜格式化",
    "XB_MiniMax_SceneDispatcher": "MiniMax - 🎯 场景元素调度",
    "XB_MiniMax_VideoDispatcher": "MiniMax - 🎬 视频调度",
    "XB_MiniMax_AudioDispatcher": "MiniMax - 🎧 音频调度",
    "XB_MiniMax_PromptGenerator": "MiniMax - ✍️ 提示词生成器",
}
