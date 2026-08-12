"""
MiniMax-H3 提示词生成器 — 最终提示词组装 System Prompt
=========================================================
节点 XB_MiniMax_PromptGenerator 的后台零件库。

职责: 读取分镜词 + 调度记录 → LLM 润色 → Minimax-H3 兼容的最终提示词
"""

# ═══════════════════════════════════════════════════════════════
#  核心骨架 (源: shed/prompt_rules.py)
# ═══════════════════════════════════════════════════════════════
# PROMPT_SKELETON 已移至 miniMax_h3/sheding/prompt_rules.py
# 通过 build_prompt_system() 中的 import 直接引用。


# ═══════════════════════════════════════════════════════════════
#  {Reference_Map} — 参考元素映射模板
# ═══════════════════════════════════════════════════════════════

def build_reference_map(
    images: dict = None,
    videos: dict = None,
    video_audios: dict = None,
    audios: dict = None,
) -> str:
    """
    根据调度记录构建参考元素映射表。

    images: {插槽名: 描述}  如 {"角色A": "一位身穿红袍的年轻女侠", "背景A": "竹林的清晨"}
    videos: {插槽名: 描述}  如 {"技能_降龙十八掌": "双掌推出, 金龙从掌中呼啸而出"}
    video_audios: {插槽名: 描述}
    audios: {插槽名: 描述}
    """
    images = images or {}
    videos = videos or {}
    video_audios = video_audios or {}
    audios = audios or {}

    lines = ["The following reference elements are provided for this shot:"]

    if images:
        lines.append("\n## Reference Images:")
        for slot_name, desc in images.items():
            lines.append(f"- {slot_name}: {desc}")

    if videos:
        lines.append("\n## Reference Videos (motion/skill/camera reference):")
        for slot_name, desc in videos.items():
            lines.append(f"- {slot_name}: {desc}")

    if video_audios:
        lines.append("\n## Reference Video Audio Tracks:")
        for slot_name, desc in video_audios.items():
            lines.append(f"- {slot_name}: {desc}")

    if audios:
        lines.append("\n## Reference Audio Tracks (voice/ambient):")
        for slot_name, desc in audios.items():
            lines.append(f"- {slot_name}: {desc}")

    return "\n".join(lines)


def build_prompt_system(reference_map_text: str, shot_script_text: str) -> str:
    from ..sheding.prompt_rules import PROMPT_SKELETON as _sk
    return _sk.format(Reference_Map=reference_map_text, Shot_Script=shot_script_text)
