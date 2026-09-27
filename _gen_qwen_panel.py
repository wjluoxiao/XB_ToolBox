"""
由 js/xb_image_prompt_preset.js 生成 js/xb_qwen_prompt_preset.js
（把「Qwen2.1提示词预设」的功能块 _xbr_qwen_block.js 注入进去）

用法：python _gen_qwen_panel.py     （基础面板更新后重跑一次即可）
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "js", "xb_image_prompt_preset.js")
BLOCK = os.path.join(ROOT, "_xbr_qwen_block.js")
DST = os.path.join(ROOT, "js", "xb_qwen_prompt_preset.js")

src = io.open(SRC, encoding="utf-8").read()
block = io.open(BLOCK, encoding="utf-8").read()

patches = [
    # 1. 节点类型
    ('const NODE_TYPE = "XB_ImagePromptPreset";',
     'const NODE_TYPE = "XB_QwenPromptPreset";'),
    # 2. 默认配置：加入本节点自己的配置段
    ("""    preset_texts: {},   // 用户改过的预设句（设定词）：{"模式|语言": "文本"}（换模式/换语言不丢）
  };""",
     """    preset_texts: {},   // 用户改过的预设句（设定词）：{"模式|语言": "文本"}（换模式/换语言不丢）
    qwen: xbrQwenDefaults(),        // Qwen2.1提示词预设：生成后控制 + 追加设定
  };"""),
    # 3. 解析：保留本节点配置段（元素面板保存时不会被丢掉）
    ("""  cfg.elements.rel = rel;
  return cfg;
}""",
     """  cfg.elements.rel = rel;
  cfg.qwen = xbrParseQwen(data.qwen);   // Qwen2.1提示词预设：生成后控制 + 追加设定
  return cfg;
}"""),
    # 4. 隐藏内部字段（生图预设三项 + 官方 Load CLIP 三项 + 官方 Generate Text 全量参数）
    ("""  const hideInternal = () => {
    hideWidget(findWidget(node, "internal_prompt"));
    hideWidget(findWidget(node, "manager_settings"));""",
     """  const hideInternal = () => {
    hideWidget(findWidget(node, "internal_prompt"));
    hideWidget(findWidget(node, "manager_settings"));
    // Qwen2.1提示词预设：这些参数只在弹窗里配置（节点表面不暴露）
    hideWidget(findWidget(node, "output_lang"));      // → ✨ 增强预设 弹窗
    hideWidget(findWidget(node, "latent_kind"));      // → ✨ 增强预设 弹窗
    hideWidget(findWidget(node, "preset_mode"));      // → ✨ 增强预设 弹窗
    hideWidget(findWidget(node, "three_view_text"));  // 设定词 → 只在弹窗里编辑
    for (const nm of XBR_QWEN_WIDGETS) hideWidget(findWidget(node, nm));"""),
    # 4b. 幽灵端口清理（同上名单）
    ("""      for (const nm of ["internal_prompt", "manager_settings"]) {""",
     """      for (const nm of ["internal_prompt", "manager_settings", "output_lang", "latent_kind",
                         "preset_mode", "three_view_text"].concat(XBR_QWEN_WIDGETS)) {"""),
    # 4c. 设定词在节点表面始终隐藏（基础面板的预设句框显/隐逻辑改成“只隐不显”）
    ("""  const applyPresetTextVisibility = () => {
    try {
      if (PRESET_TEXT_DEFAULT[surfaceOf().mode]) { showWidget(w3v); stylePresetTextBox(); } else hideWidget(w3v);
    } catch (_) {}""",
     """  const applyPresetTextVisibility = () => {
    try {
      // 设定词只在「✨ 增强预设」弹窗里编辑 → 节点表面始终隐藏
      hideWidget(w3v);
    } catch (_) {}"""),
    # 6. 按钮区：3 个按钮放**第一排**（8 个元素分类按钮之上）
    ("""  container.appendChild(btnRow);""",
     """  // 第 1 行按钮：🤖 LLM设置 ｜ ✨ 增强预设 ｜ 📖 使用说明
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
  promptBox.placeholder = "点上方按钮开面板、点选项行加入元素，或直接在这里写提示词…\\n执行节点时：这段文字会作为【正文】交给文本编码器生成完整提示词\\n「📝 提示词」端口接线后本框锁定";
  // 标题行（左标签 + 右「📋 复制」）+ 参数设定显示（同时挂上端口锁定与执行回写）
  const xbrHeadAndInfo = xbrBuildPromptHeader(node, promptBox);
  container.append(xbrHeadAndInfo[0], promptBox, xbrHeadAndInfo[1]);"""),
    # 8. 自动化定位锚点 + 清理已废弃的输入槽（历史工作流里会残留空端口）
    ("""  node.__ippSyncPromptBox = syncPromptBoxFromWidget;""",
     """  node._xbEl = container;   // 调试 / 自动化定位锚点
  // 已废弃端口（ref_images / video_frames）：早期版本建过的节点在旧工作流里会残留空槽，没连线就移除
  // （工作流恢复 inputs 可能晚于面板初始化 → 立刻做一次 + 稍后再做一次）
  const xbrDropDeadInputs = () => {
    for (const dead of ["ref_images", "video_frames"]) {
      const di = (node.inputs || []).findIndex((i) => i.name === dead && i.link == null);
      if (di >= 0) { try { node.removeInput(di); } catch (_) {} }
    }
  };
  xbrDropDeadInputs();
  setTimeout(xbrDropDeadInputs, 400);
  setTimeout(xbrDropDeadInputs, 1500);
  node.__ippSyncPromptBox = syncPromptBoxFromWidget;"""),
    # 9. 扩展名不能与其它面板重名（前端会拒绝注册第二个同名扩展）
    ('  name: "XB.ImagePromptPreset",',
     '  name: "XB.QwenPromptPreset",'),
    # 10. 高度常量：按钮多 1 行（+36）+ 参数设定显示信息区（5 行 130 + 6 间距）
    ("""  const DOM_FIXED_H = 116;  // 按钮区 2 行(66) + 标签(17) + 内边距/间距(≈33)""",
     """  const DOM_FIXED_H = 288;  // Qwen：按钮区 3 行(102) + 标签(17) + 信息区(130+6) + 内边距/间距(≈33)"""),
    ("""  const DOM_MIN_H = 411;    // DOM 区最小高度 = 按钮区 66 + 间距 12 + 标签 17 + 输入框 300 + 内边距 16""",
     """  const DOM_MIN_H = 583;    // Qwen：DOM 区最小高度 = 按钮区 102 + 间距 12 + 标签 17 + 输入框 300 + 信息区 136 + 内边距 16"""),
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
