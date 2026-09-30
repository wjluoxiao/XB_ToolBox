"""
由 js/xb_image_prompt_preset.js 生成 js/xb_image_prompt_preset_pro.js
（把「✨ 提示词增强反推」的功能块 _xbr_pro_block.js 注入进去）

用法：python _gen_pro_panel.py     （基础面板更新后重跑一次即可）
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "js", "xb_image_prompt_preset.js")
BLOCK = os.path.join(ROOT, "_xbr_pro_block.js")
DST = os.path.join(ROOT, "js", "xb_image_prompt_preset_pro.js")

src = io.open(SRC, encoding="utf-8").read()
block = io.open(BLOCK, encoding="utf-8").read()

patches = [
    # 0. 需要前端 API（模型候选表 / 在线 API 配置读写）
    ('import { app } from "../../scripts/app.js";\nimport { installNodes2BoxResize } from "./xb_compat.js";',
     'import { app } from "../../scripts/app.js";\nimport { api } from "../../scripts/api.js";\nimport { installNodes2BoxResize } from "./xb_compat.js";'),
    # 1. 节点类型
    ('const NODE_TYPE = "XB_ImagePromptPreset";',
     'const NODE_TYPE = "XB_ImagePromptPresetPro";'),
    # 2. 默认配置：加入 LLM 段
    ("""    preset_texts: {},   // 用户改过的预设句（设定词）：{"模式|语言": "文本"}（换模式/换语言不丢）
  };""",
     """    preset_texts: {},   // 用户改过的预设句（设定词）：{"模式|语言": "文本"}（换模式/换语言不丢）
    llm: xbrLlmDefaults(),          // 融合「✨ 提示词增强反推」的 LLM 配置段
  };"""),
    # 3. 解析：保留 LLM 段（元素面板保存时不会被丢掉）
    ("""  cfg.elements.rel = rel;
  return cfg;
}""",
     """  cfg.elements.rel = rel;
  cfg.llm = xbrParseLlm(data.llm);   // 融合「✨ 提示词增强反推」的 LLM 配置段
  return cfg;
}"""),
    # 4. 隐藏新增内部字段（含：输出语言 / 空latent类型 / 预设模式 —— 都改到弹窗里配置）
    ("""  const hideInternal = () => {
    hideWidget(findWidget(node, "internal_prompt"));
    hideWidget(findWidget(node, "manager_settings"));""",
     """  const hideInternal = () => {
    hideWidget(findWidget(node, "internal_prompt"));
    hideWidget(findWidget(node, "manager_settings"));
    // 融合「✨ 提示词增强反推」：这些参数只在弹窗里配置（节点表面不暴露）
    hideWidget(findWidget(node, "backend"));
    hideWidget(findWidget(node, "preset"));
    hideWidget(findWidget(node, "task_preset"));
    hideWidget(findWidget(node, "open_api_settings"));
    hideWidget(findWidget(node, "output_lang"));     // 语言只留：LLM设置 里的「输出语言」
    hideWidget(findWidget(node, "latent_kind"));     // → 「✨ 增强预设」弹窗
    hideWidget(findWidget(node, "preset_mode"));     // → 「✨ 增强预设」弹窗
    hideWidget(findWidget(node, "three_view_text")); // 设定词 → 只在「✨ 增强预设」弹窗里编辑（用户要求：不在节点表面显示）
    hideWidget(findWidget(node, "skill_name"));      // SKILL 选择 → 只在「✨ 预设参数」弹窗里选
    hideWidget(findWidget(node, "skill_mode"));      // SKILL 三态 → 只在「✨ 预设参数」弹窗里选
    hideWidget(findWidget(node, "io_mode"));         // 模版（文生图/图生图）→ 只在「✨ 预设参数」弹窗里选"""),
    # 4b. 幽灵端口清理（同上名单）
    ("""      for (const nm of ["internal_prompt", "manager_settings"]) {""",
     """      for (const nm of ["internal_prompt", "manager_settings", "backend", "preset", "task_preset",
                         "open_api_settings", "output_lang", "latent_kind", "preset_mode", "three_view_text",
                         "skill_name", "skill_mode", "io_mode"]) {"""),
    # 4c. 设定词在 Pro 节点表面始终隐藏（基础面板的预设句框显/隐逻辑在 Pro 里改成“只隐不显”）
    ("""  const applyPresetTextVisibility = () => {
    try {
      if (PRESET_TEXT_DEFAULT[surfaceOf().mode]) { showWidget(w3v); stylePresetTextBox(); } else hideWidget(w3v);
    } catch (_) {}""",
     """  const applyPresetTextVisibility = () => {
    try {
      // Pro：设定词只在「✨ 增强预设」弹窗里编辑 → 节点表面始终隐藏（不把选项参数暴露在外面）
      hideWidget(w3v);
    } catch (_) {}"""),
    # 6. 按钮区：反推相关 3 个按钮放**第一排**（风格…这八个按钮之上）
    ("""  container.appendChild(btnRow);""",
     """  // 第 1 行按钮（融合「✨ 提示词增强反推」）：🤖 LLM设置 ｜ ✨ 增强预设 ｜ 📖 使用说明
  container.appendChild(xbrBuildButtonRow(node));
  // 第 2 行：8 个元素分类按钮
  container.appendChild(btnRow);"""),
    # 7. 提示词框块：标题行（复制按钮）+ 参数设定显示（含端口锁定 / 执行回写）
    ("""  const promptLab = el("div", "font-size:12px;color:#bbb;flex:0 0 auto;", "📝 节点提示词（与面板预览框双向同步）");
  const promptBox = el("textarea", BOX_CSS + "width:100%;flex:1 1 auto;min-height:300px;resize:none;line-height:1.6;font-size:12px;overflow-y:auto;");
  promptBox.spellcheck = false;
  promptBox.placeholder = "点上方 8 个按钮开面板、点选项行加入元素，或直接在这里写提示词…";
  container.append(promptLab, promptBox);""",
     """  const promptBox = el("textarea", BOX_CSS + "width:100%;flex:1 1 auto;min-height:300px;resize:none;line-height:1.6;font-size:12px;overflow-y:auto;");
  promptBox.spellcheck = false;
  promptBox.placeholder = "点上方按钮开面板、点选项行加入元素，或直接在这里写提示词…\\n接了「🖼️ 图像」时：这里写的是修改要求，例：把背景换成草地 → 最终只输出修改后的画面提示词\\n「📝 提示词」端口接线后本框锁定";
  // 标题行（左标签 + 右「📋 复制」）+ 参数设定显示（Pro 新增；同时挂上端口锁定与执行回写）
  const xbrHeadAndInfo = xbrBuildPromptHeader(node, promptBox);
  container.append(xbrHeadAndInfo[0], promptBox, xbrHeadAndInfo[1]);"""),
    # 8. 自动化定位锚点
    ("""  node.__ippSyncPromptBox = syncPromptBoxFromWidget;""",
     """  node._xbEl = container;   // 调试 / 自动化定位锚点
  node.__ippSyncPromptBox = syncPromptBoxFromWidget;"""),
    # 9. 扩展名不能与基础面板重名（前端会拒绝注册第二个同名扩展）
    ('  name: "XB.ImagePromptPreset",',
     '  name: "XB.ImagePromptPresetPro",'),
    # 10. 高度常量：按钮多 1 行（+36）+ 新增「参数设定显示」信息区（116 + 6 间距）
    ("""  const DOM_FIXED_H = 116;  // 按钮区 2 行(66) + 标签(17) + 内边距/间距(≈33)""",
     """  const DOM_FIXED_H = 308;  // Pro：按钮区 3 行(102) + 标签(17) + 信息区(150+6) + 内边距/间距(≈33)"""),
    ("""  const DOM_MIN_H = 411;    // DOM 区最小高度 = 按钮区 66 + 间距 12 + 标签 17 + 输入框 300 + 内边距 16""",
     """  const DOM_MIN_H = 603;    // Pro：DOM 区最小高度 = 按钮区 102 + 间距 12 + 标签 17 + 输入框 300 + 信息区 156 + 内边距 16"""),
]

for old, new in patches:
    n = src.count(old)
    if n != 1:
        print("[FAIL] 锚点命中 %d 次（应为 1）：%r" % (n, old[:60]))
        sys.exit(1)
    src = src.replace(old, new)

# ══════════════════════════════════════════════════════════════════════════
#  ⚠️ Pro 专属裁剪（用户要求：删「模版选择」+ 删 Qwen2.1 相关预设模式）
#     只留 4 档模式（无预设 + 三·四·五视图），固定文生图，无图生图文本 / 无条款
# ══════════════════════════════════════════════════════════════════════════
_pt_i = src.index("const PRESET_TEXT_DEFAULT = {")
_pt_j = src.index("  [MODE_RGBA]: {", _pt_i)
PT_TEXT = src[_pt_i:_pt_j].rstrip() + "\n};\n"

PRO_ALIASES = '''const MODE_ALIASES = {
  // Pro 已删除的档位（含旧版带表情的名字）→ 一律归一到「无预设」，不再前置任何设定词
  "常规文生图": "无预设",
  "背景纯透明": "无预设",
  "图文版面": "无预设", "📱 图文版面": "无预设",
  "信息图": "无预设", "📊 信息图": "无预设",
  "多格分镜": "无预设", "🎞 多格分镜": "无预设",
  "广告分镜板": "无预设", "🎬 广告分镜板": "无预设",
  "保持主体换场景": "无预设", "🛍 保持主体换场景": "无预设",
  "局部编辑": "无预设", "✏️ 局部编辑": "无预设",
  "老照片修复": "无预设", "🧹 老照片修复": "无预设",
  "整图风格化": "无预设", "🎨 整图风格化": "无预设",
  "360°全景": "无预设", "🌐 360°全景": "无预设",
  "多图指认合成": "无预设", "🗂 多图指认合成": "无预设",
};
'''

rx_patches = [
    # 1) 模式常量 + MODES：只留 4 档
    (r'const MODE_RGBA = "背景纯透明";[\s\S]*?const MODES = \[[^\]]*\];\n',
     '// ⚠️ Pro 只有 4 档模式（无预设 + 三·四·五视图）：图生图 / 版面类档位已按要求删除\n'
     'const MODES = [MODE_TP, MODE_3V, MODE_4V, MODE_5V];\n'),
    # 2) 旧档位名 → 一律归一到「无预设」
    (r'const MODE_ALIASES = \{[\s\S]*?\n\};\n', PRO_ALIASES),
    # 3) 需要输入图的档位：Pro 没有
    (r'const MODE_NEEDS_IMAGE = \[[^\]]*\];\nconst modeNeedsImage = [^\n]*\nconst modeSkillHint = [^\n]*\n',
     'const MODE_NEEDS_IMAGE = [];   // Pro 无「必须接图」的档位\n'
     'const modeNeedsImage = (mode) => false;\n'
     'const modeSkillHint = (mode) => "system_prompt_t2i.txt";   // Pro 固定文生图 → 只推荐 t2i\n'),
    # 4) 模版条款：Pro 不追加任何条款
    (r'const IO_I2I_COMMON = \{[\s\S]*?\n/\*\* 节点是否接了参考图[\s\S]*?\n\}\n',
     '/** ⚠️ Pro 固定文生图：不追加任何模版条款（原「以输入图为准」条款随模版选择一并删除） */\n'
     'function modeIoClause(mode, hasImage, lang) { return ""; }\n'
     '/** 节点是否接了参考图（🖼️ 图像 端口有连线） */\n'
     'function modeHasImage(node) {\n'
     '  try {\n'
     '    const inp = (node.inputs || []).find((i) => i.name === "images");\n'
     '    return !!(inp && inp.link != null);\n'
     '  } catch (_) { return false; }\n'
     '}\n'),
    # 5) 模版助手全部硬编码为「文生图」
    (r'const ioModeOf = [^\n]*\n/\*\* 把「自动」按有没有接参考图解析成 文生图 / 图生图 \*/\n'
     r'const resolveIoMode = \(io, hasImage\) => \{\n[\s\S]*?\n\};\n',
     '/** ⚠️ Pro 固定文生图：模版选择已删除，这几个助手只为兼容旧的调用点而保留 */\n'
     'const ioModeOf = (v) => IO_T2I;\n'
     'const resolveIoMode = (io, hasImage) => IO_T2I;\n'),
    (r'const modeDefaultIo = \(mode\) => \(MODE_NEEDS_IMAGE\.includes\(mode\) \? IO_I2I : IO_T2I\);\n',
     'const modeDefaultIo = (mode) => IO_T2I;   // Pro 固定文生图\n'),
    # 6) 默认设定词表：只留 三·四·五视图（无预设无文本）
    (r'const PRESET_TEXT_DEFAULT = \{[\s\S]*?\n\};\n', PT_TEXT),
    # 7) 图生图档的「文生图版」表：Pro 已无图生图档 → 空表
    #    ⚠️ 这个字典的收尾是「  };」（两空格缩进），不能用 \n\}\;\n 当边界
    (r'const PRESET_TEXT_T2I = \{[\s\S]*?\n  \};\n',
     'const PRESET_TEXT_T2I = {};   // Pro 已无图生图档位（保留空表：基础代码按它取默认文本）\n'),
]

for pat, rep in rx_patches:
    src, n = re.subn(pat, rep, src, count=0)
    if n != 1:
        print("[FAIL] 正则补丁命中 %d 次（应为 1）：%r" % (n, pat[:60]))
        sys.exit(1)

# ── 裁剪结果自检（少一项就报错，避免生成出「半截」的 Pro 面板）──
need = [
    "const MODES = [MODE_TP, MODE_3V, MODE_4V, MODE_5V];",
    "const PRESET_TEXT_T2I = {};",
    'function modeIoClause(mode, hasImage, lang) { return ""; }',
    "const ioModeOf = (v) => IO_T2I;",
    "const resolveIoMode = (io, hasImage) => IO_T2I;",
    "const modeDefaultIo = (mode) => IO_T2I;",
    "const MODE_NEEDS_IMAGE = [];",
    "const modeNeedsImage = (mode) => false;",
    "const skillOpts = [SKILL_NONE_LABEL]",
]
gone = ["const MODE_PANO360", "Treat the subject in the input image as the single source of truth",
        'xbrSetWidget(node, "io_mode"']

anchor = "app.registerExtension({"
if src.count(anchor) != 1:
    print("[FAIL] registerExtension 锚点异常")
    sys.exit(1)
src = src.replace(anchor, block + "\n" + anchor)

miss = [k for k in need if k not in src]
left = [k for k in gone if k in src]
if miss or left:
    print("[FAIL] 裁剪自检：缺 %r；残留 %r" % (miss, left))
    sys.exit(1)
print("[OK] 裁剪自检通过（%d 项应存在 / %d 项应消失）" % (len(need), len(gone)))

io.open(DST, "w", encoding="utf-8", newline="\n").write(src)
print("[OK] 生成 %s（%d 字符）" % (DST, len(src)))
