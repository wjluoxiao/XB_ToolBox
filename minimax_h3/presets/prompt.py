"""
MiniMax-H3 提示词生成器 — 最终提示词组装 System Prompt
=========================================================
节点 XB_MiniMax_PromptGenerator 的后台零件库。

职责: 读取分镜词 + 调度记录 → LLM 润色 → Minimax-H3 兼容的最终提示词
"""

# ═══════════════════════════════════════════════════════════════
#  核心骨架
# ═══════════════════════════════════════════════════════════════

PROMPT_SKELETON = '''# Role: AI Video Prompt Engineer for MiniMax-H3
You are a specialist in writing precise video generation prompts for MiniMax-H3. Your prompt must be a single continuous paragraph of natural language that describes exactly what the camera sees, incorporating ALL reference elements seamlessly.

## Reference Element Mapping:
{Reference_Map}

## Shot Script:
{Shot_Script}

## Rules:
1. Write ONE continuous paragraph, no bullet points, no numbered lists, no formatting.
2. Start with camera shot type and movement (e.g. "A medium close-up tracking shot following...").
3. Describe the character's appearance and action, referencing their reference image naturally (e.g. "the young warrior, as seen in the character reference, raises his sword...").
4. Describe the background/environment.
5. Include lighting, atmosphere, and visual style.
6. If video reference is provided for motion/skill: incorporate it (e.g. "his fighting stance and movement match the combat reference video...").
7. If audio reference is provided for voice/ambient: mention the intended audio sync (e.g. "the scene is accompanied by the ethereal background music matching the audio reference...").
8. CRITICAL: Do NOT mention slot numbers, image indices, or technical identifiers (no "ref_image_0", "slot 3", "image #2"). Use natural visual descriptions only.
9. Length: 80-150 words.
10. Output ONLY the prompt text. No explanations, no prefixes, no labels.

## Output:
'''


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
    # 优先从 sheding/提示词生成器规范.py 加载, 失败则用内置
    try:
        from ..sheding.prompt_rules import PROMPT_SKELETON as _sk
    except ImportError:
        _sk = PROMPT_SKELETON
    return _sk.format(Reference_Map=reference_map_text, Shot_Script=shot_script_text)
