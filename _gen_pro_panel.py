"""
由 js/xb_image_prompt_preset.js 生成 js/xb_image_prompt_preset_pro.js
（把「✨ 提示词增强反推」的功能块 _xbr_pro_block.js 注入进去）

用法：python _gen_pro_panel.py     （基础面板更新后重跑一次即可）
"""
import io
import os
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
    hideWidget(findWidget(node, "three_view_text")); // 设定词 → 只在「✨ 增强预设」弹窗里编辑（用户要求：不在节点表面显示）"""),
    # 4b. 幽灵端口清理（同上名单）
    ("""      for (const nm of ["internal_prompt", "manager_settings"]) {""",
     """      for (const nm of ["internal_prompt", "manager_settings", "backend", "preset", "task_preset",
                         "open_api_settings", "output_lang", "latent_kind", "preset_mode", "three_view_text"]) {"""),
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

anchor = "app.registerExtension({"
if src.count(anchor) != 1:
    print("[FAIL] registerExtension 锚点异常")
    sys.exit(1)
src = src.replace(anchor, block + "\n" + anchor)

io.open(DST, "w", encoding="utf-8", newline="\n").write(src)
print("[OK] 生成 %s（%d 字符）" % (DST, len(src)))
