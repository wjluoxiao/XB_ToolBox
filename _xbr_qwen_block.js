/* ============================================================================
 *  🖼️ Qwen2.1提示词预设（融入「🖼️ 生图提示词预设」的同一个面板）
 *  ---------------------------------------------------------------------------
 *  节点表面新增：2 个按钮（🤖 LLM设置 ｜ ✨ 预设参数）
 *                + 提示词框标题行（右侧「📋 复制」）+ 参数设定显示（只读摘要 5 行）
 *                + 「📝 提示词」端口接线 → 提示词框锁定（二选一）
 *  弹窗：导演台同款二级弹窗（底部：自动保存 + 字号 + 界面缩放 + 取消/💾 保存）
 *  配置：manager_settings.qwen = { run.seed_control, extra_settings }（Generate Text 的全量参数走节点 widget，由弹窗读写）
 *  说明：本块所有标识符统一 xbr/XBR 前缀，避免与生图预设面板既有函数/常量重名。
 * ========================================================================== */

const XBR_SEED_MODES = ["randomize", "fixed", "increment", "decrement"];const XBR_SEED_LABEL = { randomize: "随机", fixed: "固定", increment: "增加", decrement: "减少" };
/** 模版三态：自动 = 按有没有接参考图判断；文生图 / 图生图 = 手动指定 */
const XBR_IO_MODES = ["自动", "文生图", "图生图"];
const XBR_SAMPLING_MODES = ["on", "off"];
const XBR_MTP_MODES = ["auto", "off", "2", "3", "4", "5"];
const XBR_PANEL_BUTTONS = [
  { id: "llm", label: "🤖 LLM设置", title: "🤖 LLM设置", subtitle: "模型选择 = 官方 Load CLIP；参数设置 = 官方 Generate Text 全量参数。执行节点即生成，没有开关。" },
  { id: "preset", label: "✨ 预设参数", title: "✨ 预设参数", subtitle: "输出语言 / 空latent类型 / 预设模式 / 设定词 / SKILL。提示词正文在节点上的提示词框里编辑。" },
];
/** 全部收进弹窗的节点 widget（节点表面只留画幅参数 / 生成数量） */
const XBR_QWEN_WIDGETS = [
  "clip_name", "clip_type", "device",
  "max_length", "sampling_mode", "temperature", "top_k", "top_p", "min_p",
  "repetition_penalty", "presence_penalty", "seed", "control_after_generate",
  "thinking", "use_default_template", "mtp", "skill_name", "skill_mode", "io_mode",
];
/** 种子控制 widget 名（ComfyUI 见到名为 seed 的 widget 会自动配一个 control_after_generate）*/
const XBR_SEED_CTL_WIDGET = "control_after_generate";
/** SKILL 三态：自动 = 按预设模式适配；手动 = 用选择的那一个；不用 = 完全不生效 */
const XBR_SKILL_MODES = ["自动", "手动", "不用"];

/* ── 数值 / 解析助手 ─────────────────────────────────────── */
function xbrNum(v, d, lo, hi) {
  let x = Number(v);
  if (!Number.isFinite(x)) x = d;
  if (lo !== undefined) x = Math.max(lo, x);
  if (hi !== undefined) x = Math.min(hi, x);
  return x;
}
function xbrInt(v, d, lo, hi) { return Math.round(xbrNum(v, d, lo, hi)); }
function xbrFlag(v, d) {
  if (v === undefined || v === null || v === "") return d;
  return (typeof v === "string") ? ["1", "true", "yes", "on", "开启"].includes(v.trim().toLowerCase()) : !!v;
}
function xbrPick(v, allowed, d) { return allowed.includes(v) ? v : d; }

/** 本节点配置默认值（manager_settings.qwen：只放不在节点 widget 上的东西） */
function xbrQwenDefaults() {
  return {
    extra_settings: "",
  };
}
/** 解析 manager_settings.qwen（缺失 / 非法一律安全回落） */
function xbrParseQwen(raw) {
  const d = (raw && typeof raw === "object") ? raw : {};
  return { extra_settings: String(d.extra_settings ?? "") };
}

/* ── 节点 widget 读写 ─────────────────────────────────────── */
function xbrWidget(node, name) { return (node?.widgets || []).find((w) => w?.name === name); }
function xbrWidgetVal(node, name) { return readWidgetValue(xbrWidget(node, name)); }
/** fire=true 时同步触发该 widget 原有回调（基础面板靠回调做步长/预设句框/尺寸联动） */
function xbrSetWidget(node, name, val, fire) {
  const w = xbrWidget(node, name);
  setWidgetValue(w, val);
  if (fire) { try { w?.callback?.(val); } catch (_) {} }
}
function xbrHint(text) { return el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", text); }
function xbrWidgetOptions(node, name) {
  const w = xbrWidget(node, name);
  const o = w?.options?.values ?? w?.options;
  return Array.isArray(o) ? o.slice() : [];
}
function xbrCurJson(node) {
  try {
    const raw = readWidgetValue(findWidget(node, "manager_settings"));
    const d = JSON.parse(raw || "{}");
    return (d && typeof d === "object") ? d : {};
  } catch (_) { return {}; }
}
function xbrSaveJson(node, patch) {
  const cur = xbrCurJson(node);
  Object.assign(cur, patch || {});
  persistSettings(node, cur);
  return cur;
}

/* ── 预设设定词（三视图 / 四视图 / 五视图 / 背景纯透明的设定文本）─────────────
 * · 用户改过的按「模式|模版|语言」存进节点（基础面板的 preset_texts 存档）；
 * · 弹窗读「存档 → 当前模版默认」，提交时同步写 widget + 存档。 */
function xbrPresetStore(node) {
  try { return parsePresetTexts(xbrCurJson(node).preset_texts); } catch (_) { return {}; }
}
function xbrPresetTextFor(node, mode, lang, io) {
  const key = presetKeyOf(mode, io, lang);
  const t = xbrPresetStore(node)[key];
  // 存档里的值等于任一默认 / 旧条款 → 视为「没改过」 → 用当前模版的默认（无预设 = 空）
  if (t && String(t).trim() && !isDefaultPresetText(mode, t)) return t;
  return (presetTextOf(mode, lang, io) || "");
}
/** 当前模版（文生图 / 图生图）：自动 → 按「🖼️ 图像」有没有接线判断 */
function xbrResolveIo(node, ioRaw) {
  const has = (typeof modeHasImage === "function") && modeHasImage(node);
  return (typeof resolveIoMode === "function") ? resolveIoMode(ioRaw, has) : "文生图";
}

/* ── 本节点不做在线 API / 本地 llama-cpp：模型走官方 Load CLIP，参数走官方 Generate Text ── */

/* ── 控件：数字 / 密码 / 单选行 / 种子行 ─────────────────── */
function xbrNumberControl(value, opts, onChange) {
  const i = el("input", BOX_CSS + "min-width:0;");
  i.type = "number";
  i.value = value ?? 0;
  if (opts) {
    if (opts.min !== undefined) i.min = opts.min;
    if (opts.max !== undefined) i.max = opts.max;
    i.step = opts.step ?? 1;
  }
  i.addEventListener("change", () => {
    let v = parseFloat(i.value);
    if (!Number.isFinite(v)) v = opts?.min ?? 0;
    if (opts?.min !== undefined) v = Math.max(opts.min, v);
    if (opts?.max !== undefined) v = Math.min(opts.max, v);
    i.value = v;
    onChange(v);
  });
  return i;
}
function xbrPasswordControl(value, placeholder, onChange) {
  const i = el("input", BOX_CSS + "min-width:0;");
  i.type = "password";
  i.value = value ?? "";
  if (placeholder) i.placeholder = placeholder;
  i.autocomplete = "new-password";
  i.spellcheck = false;
  i.addEventListener("change", () => onChange(i.value.trim()));
  return i;
}
function xbrTextControl(value, placeholder, onChange) {
  const i = el("input", BOX_CSS + "min-width:0;");
  i.type = "text";
  i.value = value ?? "";
  if (placeholder) i.placeholder = placeholder;
  i.spellcheck = false;
  i.addEventListener("change", () => onChange(i.value.trim()));
  return i;
}
/** 导演台同款「种子 + 生成后控制（随机/固定/增加/减少）」一行 */
function xbrSeedRow(run, onChange) {
  const g = el("div", "display:flex;align-items:center;gap:10px;margin-bottom:10px;");
  g.append(el("label", "flex:0 0 160px;font-size:13px;color:#999;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;", "种子"));
  const i = xbrNumberControl(run.seed, { min: 0, max: Number.MAX_SAFE_INTEGER, step: 1 }, (v) => { run.seed = Math.round(v); onChange?.(); });
  i.style.flex = "1 1 0";
  const ctrl = smallBtn("", "flex:1 1 0;min-width:0;background:#b45309;border:1px solid #d97706;color:#fff;text-align:center;", "生成后控制：点击在 随机 / 固定 / 增加 / 减少 间切换", null);
  const cur = () => (XBR_SEED_LABEL[run.seed_control] ? run.seed_control : "randomize");
  const render = () => {
    ctrl.textContent = "🔁 " + XBR_SEED_LABEL[cur()];
    ctrl.title = "生成后控制：随机 = 每次运行后自动换新种子；固定 = 锁定当前值；增加/减少 = 每次运行后 ±1。点击切换";
  };
  ctrl.addEventListener("click", () => {
    run.seed_control = XBR_SEED_MODES[(XBR_SEED_MODES.indexOf(cur()) + 1) % XBR_SEED_MODES.length];
    render();
    onChange?.();
  });
  render();
  g.append(i, ctrl);
  return g;
}

/* ── 弹窗外壳（与生图预设面板同风格；底部：自动保存 + 字号 + 界面缩放）── */
let xbrModal = null;
function xbrDialog({ label, title, subtitle, width = 820, autoSaveRef = null, onCommit = null, onImmediate = null, onChange = null, onClose = null }) {
  const overlay = el("div", "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:10300;display:flex;align-items:center;justify-content:center;overflow:auto;");
  const dialog = el("section", `background:#1c1c1e;border:1px solid #333;border-radius:8px;width:${width}px;max-width:94vw;` +
    "max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 40px rgba(0,0,0,.6);flex:0 0 auto;color:#ddd;font-size:13px;");
  dialog.dataset.xbrProModal = label;
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", label);

  const header = el("div", "padding:18px 20px;border-bottom:1px solid #444;");
  header.append(el("div", "font-size:17px;font-weight:700;color:#eee;", title));
  if (subtitle) header.append(el("div", "font-size:12px;color:#999;margin-top:5px;line-height:1.6;", subtitle));
  const body = el("div", "padding:16px 20px;overflow-y:auto;flex:1;min-height:200px;");
  const error = el("div", "color:#e55;font-size:12px;margin:0 20px;min-height:14px;");
  const footer = el("div", "padding:12px 20px;border-top:1px solid #444;display:flex;justify-content:flex-end;gap:10px;align-items:center;background:#18181a;border-bottom-left-radius:8px;border-bottom-right-radius:8px;");
  const left = el("div", "display:flex;align-items:center;gap:16px;margin-right:auto;flex-wrap:wrap;");

  let autoCb = null;
  if (autoSaveRef) {
    const autoRow = el("label", "display:flex;align-items:center;gap:6px;font-size:13px;color:#999;cursor:pointer;user-select:none;");
    autoCb = el("input", "width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;");
    autoCb.type = "checkbox";
    autoCb.checked = autoSaveRef.value !== false;
    autoCb.title = "开启后：弹窗内改动会自动保存（防抖）；关闭后需手动点「💾 保存」";
    autoCb.addEventListener("change", () => { autoSaveRef.value = autoCb.checked; try { onImmediate?.(); } catch (_) {} });
    autoRow.append(autoCb, el("span", "", "自动保存"));
    left.append(autoRow);
  }
  const zoomRow = buildZoomRow(dialog);
  zoomRow.title = "调整面板文本编辑字号（与本节点其它面板共享记忆）";
  const uiRow = buildUIRow(dialog);
  uiRow.title = "调整整个弹窗界面大小（不缩放网页/画布；Ctrl/⌘+滚轮 也可）";
  left.append(zoomRow, uiRow);

  const cancelBtn = el("button", "background:transparent;border:1px solid #555;color:#fff;border-radius:4px;padding:8px 20px;font-size:14px;cursor:pointer;font-family:inherit;", "取消");
  const saveBtn = onCommit ? el("button", "background:#2d5a88;color:#fff;border:none;border-radius:4px;padding:8px 20px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;", "💾 保存") : null;
  footer.append(left, cancelBtn);
  if (saveBtn) footer.append(saveBtn);
  dialog.append(header, body, error, footer);
  overlay.append(dialog);
  document.body.append(overlay);
  zoomApplyContainer(dialog);
  uiApply(dialog);
  bindWheelZoom(dialog);

  let timer = null;
  const close = () => {
    clearTimeout(timer);
    try { overlay.remove(); } catch (_) {}
    if (xbrModal && xbrModal.overlay === overlay) xbrModal = null;
    try { onClose?.(); } catch (_) {}
  };
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
  document.addEventListener("keydown", onKey, true);
  cancelBtn.addEventListener("click", close);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      if (saveBtn.disabled) return;
      saveBtn.disabled = true;
      saveBtn.textContent = "保存中…";
      error.textContent = "";
      try { await onCommit(); close(); }
      catch (e) { error.textContent = "保存失败：" + ((e && e.message) || e); saveBtn.disabled = false; saveBtn.textContent = "💾 保存"; }
    });
  }
  // 自动保存（导演台同款：改动后防抖提交）
  body.addEventListener("change", () => {
    try { onChange?.(); } catch (_) {}
    if (autoSaveRef && autoSaveRef.value === false) { try { onImmediate?.(); } catch (_) {} return; }
    clearTimeout(timer);
    timer = setTimeout(() => { try { onCommit?.(); } catch (_) {} }, 800);
  });
  const shell = { overlay, dialog, body, error, close };
  xbrModal = shell;
  return shell;
}

/* ── 弹窗内容：🤖 大语言模型配置 ─────────────────────────── */
/* ── 弹窗内容：🤖 LLM设置（官方 Load CLIP + 官方 Generate Text）─────── */
function xbrRenderLlm(body, node, draft, ctx) {
  const s = draft.settings.qwen;

  body.append(makeSectionTitle("模型选择（官方 Load CLIP）"));
  const clips = xbrWidgetOptions(node, "clip_name");
  if (clips.length) body.append(field("模型", selectControl(clips, draft.clip_name, (v) => { draft.clip_name = v; })));
  else body.append(field("模型", xbrTextControl(draft.clip_name, "models/text_encoders 里没有模型", (v) => { draft.clip_name = v; })));
  body.append(field("类型", selectControl(xbrWidgetOptions(node, "clip_type"), draft.clip_type, (v) => { draft.clip_type = v; })));
  body.append(field("设备", selectControl(xbrWidgetOptions(node, "device"), draft.device, (v) => { draft.device = v; })));
  body.append(xbrHint("与官方 Load CLIP 完全一致：模型来自 ComfyUI/models/text_encoders；Qwen-Image 系文本编码器请选 类型 = qwen_image。"));

  body.append(makeSectionTitle("参数设置（官方 Generate Text 全量参数）"));
  const t = draft.text;
  body.append(field("最大长度 max_length", xbrNumberControl(t.max_length, { min: 1, max: 32768, step: 1 }, (v) => { t.max_length = Math.round(v); })));
  body.append(field("采样模式 sampling_mode", selectControl(XBR_SAMPLING_MODES, t.sampling_mode, (v) => { t.sampling_mode = v; ctx.rerender(); })));
  if (t.sampling_mode === "on") {
    body.append(field("temperature", xbrNumberControl(t.temperature, { min: 0.01, max: 2.0, step: 0.000001 }, (v) => { t.temperature = v; })));
    body.append(field("top_k", xbrNumberControl(t.top_k, { min: 0, max: 1000, step: 1 }, (v) => { t.top_k = Math.round(v); })));
    body.append(field("top_p", xbrNumberControl(t.top_p, { min: 0, max: 1, step: 0.01 }, (v) => { t.top_p = v; })));
    body.append(field("min_p", xbrNumberControl(t.min_p, { min: 0, max: 1, step: 0.01 }, (v) => { t.min_p = v; })));
    body.append(field("repetition_penalty", xbrNumberControl(t.repetition_penalty, { min: 0, max: 5, step: 0.01 }, (v) => { t.repetition_penalty = v; })));
    body.append(field("presence_penalty", xbrNumberControl(t.presence_penalty, { min: 0, max: 5, step: 0.01 }, (v) => { t.presence_penalty = v; })));
    const holder = { seed: t.seed, seed_control: xbrPick(t.ctl, XBR_SEED_MODES, "randomize") };
    body.append(xbrSeedRow(holder, () => { t.seed = holder.seed; t.ctl = holder.seed_control; }));
    body.append(xbrHint("点「🔁」切换生成后控制：随机 = 运行后自动换新种子；固定 = 锁定；增加 / 减少 = 运行后 ±1。"
      + "这里与 ComfyUI 原生的种子控制是同一个值，两处改哪个都一样。"));
  } else {
    body.append(xbrHint("采样模式 = off：贪心解码，下面的 temperature / top_k / top_p / min_p / 惩罚项 / 种子都不参与。"));
  }
  body.append(field("思考模式 thinking", checkboxControl(t.thinking, "模型支持时以思考模式生成；思考内容不会进入输出", (v) => { t.thinking = v; })));
  body.append(field("使用内置模板 use_default_template", checkboxControl(t.use_default_template, "使用模型自带的系统提示词 / 对话模板", (v) => { t.use_default_template = v; })));
  body.append(field("mtp", selectControl(XBR_MTP_MODES, t.mtp, (v) => { t.mtp = v; })));
  body.append(xbrHint("mtp：多 token 预测投机解码，没有 MTP 权重时无效；与官方 Generate Text 同义。"));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "提示词正文在节点上的提示词框里编辑；「📝 提示词」端口接线后该框锁定。"));
}

/* ── 弹窗内容：✨ 预设参数（生图预设 + 设定词 + SKILL）───────────── */
function xbrRenderPreset(body, node, draft, ctx) {
  // 注：原「追加设定（可留空）」已按用户要求删除（不再往系统提示词里拼【额外要求】）
  body.append(makeSectionTitle("生图预设"));
  body.append(field("输出语言", selectControl(LANGS, draft.lang, (v) => {
    draft.lang = v;
    // 换语言 → 未改过设定词时取该语言的「存档 → 默认」（同一模版）
    if (!draft.presetTouched) draft.presetText = xbrPresetTextFor(node, draft.mode, v, xbrResolveIo(node, draft.ioMode));
    ctx.rerender();
  })));
  body.append(xbrHint("输出语言决定：词表与设定词按哪种语言加载、生成文本是中文还是英文。"));
  body.append(field("空latent类型", selectControl(LATENT_KINDS, draft.kind, (v) => { draft.kind = v; })));
  body.append(xbrHint("空latent类型：选你正在用的模型即可（形状 / 下采样 / 尺寸步长自动适配 8/16/32）。"));
  // ── 模版（文生图 / 图生图）：决定用哪一套设定词（每个预设模式都有两套）──
  body.append(field("模版", radioRow(XBR_IO_MODES, draft.ioMode, (v) => {
    draft.ioMode = v;
    // 换模版 → 未改过时立即换成对应那套设定词，改过的按「模式|模版|语言」存着不会被冲掉
    if (!draft.presetTouched) draft.presetText = xbrPresetTextFor(node, draft.mode, draft.lang, xbrResolveIo(node, v));
    ctx.rerender();
  })));
  body.append(xbrHint("模版：自动 = 按「🖼️ 图像」有没有接线判断；文生图 / 图生图 = 手动指定。每个预设模式都有两套设定词，切模版会直接换掉下面「设定词」那一栏的内容。"));
  body.append(field("预设模式", selectControl(MODES, draft.mode, (v) => {
    draft.mode = v;
    // 换模式 → 立刻取该「模式 × 模版」的设定词（用户改过的存档 → 默认），改过的不会被冲掉
    draft.presetTouched = false;
    draft.presetText = xbrPresetTextFor(node, v, draft.lang, xbrResolveIo(node, draft.ioMode));
    ctx.rerender();     // 有/无设定词的模式之间切换 → 重画「设定词」区
  })));
  // 当前模版 + 本档提示
  const needsImg = (typeof modeNeedsImage === "function") && modeNeedsImage(draft.mode);
  const hasImgNow = (typeof modeHasImage === "function") && modeHasImage(node);
  const ioNow = xbrResolveIo(node, draft.ioMode);
  body.append(el("div", "font-size:11px;color:#8fb;line-height:1.7;margin:2px 0 4px;",
    "当前模版：" + ioNow
    + (draft.ioMode === "自动" ? ("（自动：" + (hasImgNow ? "检测到 🖼️ 图像已接线" : "未接 🖼️ 图像") + "）")
                              : "（手动指定）")
    + (needsImg ? "　❗本档属于图生图档" : "")));
  body.append(el("div", "font-size:11px;color:" + (needsImg ? "#d9a441" : "#888") + ";line-height:1.7;margin:2px 0 8px;",
    (draft.mode === MODE_TP)
      ? "无预设：接不接参考图、哪个模版，都不会前置设定词（下面「设定词」栏保持空白；想加就自己写）。"
      : (needsImg
          ? (ioNow === "文生图"
              ? "⚠️ 本档属于「图生图」，但当前是文生图模版：下面用的是从零生成的写法（不依赖任何输入图）。接图或把模版改成图生图即可切回去。"
              : "本档属于「图生图」：设定词按输入图改写场景，需接参考图（🖼️ 图像）。")
          : (ioNow === "图生图"
              ? "本档属于「文生图」，当前用图生图模版：设定词末尾会追加「以输入图为准」的条款，需接参考图。"
              : "本档属于「文生图」：不接图也行；接图后把模版改成「图生图」（或保持自动）会追加「以输入图为准」的条款。"))));

  // ── 设定词（按「模式 × 模版 × 语言」取；只在弹窗里编辑，节点表面不显示）──
  //    无预设档：这一栏**照样显示**，只是内容空白（用户可以自己写）
  const modeDef = presetTextOf(draft.mode, draft.lang, ioNow);
  {
    body.append(makeSectionTitle("设定词（" + ioNow + "模版）"));
    draft.presetText = String(draft.presetText || "");
    if (modeDef && !draft.presetText.trim()) draft.presetText = modeDef;
    const taP = textareaControl(draft.presetText, (v) => { draft.presetText = v; draft.presetTouched = true; },
      "width:100%;box-sizing:border-box;min-height:180px;resize:vertical;");
    taP.placeholder = modeDef
      ? "该模式在「" + ioNow + "」模版下的设定词；改过的按「模式 + 模版 + 语言」记进节点，换模式 / 换模版 / 换语言都不丢"
      : "无预设：本档不前置设定词（保持空白即可；在这里写内容就会作为设定词置顶）";
    taP.spellcheck = false;
    body.append(taP);
    const taRow = el("div", "display:flex;align-items:center;gap:10px;margin:6px 0 4px;");
    if (modeDef) {
      taRow.append(smallBtn("♻️ 恢复默认", "border:1px solid #555;background:#2a2a2a;color:#ccc;padding:4px 10px;",
        "把设定词恢复为该模式 × 该模版 × 该语言的默认文本",
        () => { draft.presetText = modeDef; draft.presetTouched = false; ctx.rerender(); }));
    }
    taRow.append(el("span", "font-size:11px;color:#888;",
      !modeDef ? (draft.presetText.trim() ? "当前 = 自定义" : "当前 = 空白（不前置设定词）")
               : (draft.presetText === modeDef ? "当前 = 默认" : "当前 = 自定义")));
    body.append(taRow);
    if (modeDef) {
      body.append(el("div", "font-size:11px;color:#888;line-height:1.75;margin:6px 0 8px;",
        "· 设定词会作为【参考设定】送给文本编码器；\n"
        + "· 最终输出时，设定词由节点原封不动加在生成结果的最顶端；\n"
        + "· 改过的设定词随节点保存，换模式 / 换模版 / 换语言都会取回你改过的那一版。"));
    } else {
      body.append(el("div", "font-size:11px;color:#888;line-height:1.75;margin:6px 0 8px;",
        "· 无预设档：不管接不接参考图，节点都不会自动前置设定词；\n"
        + "· 如果在这一栏写了内容，它会作为【参考设定】送模型、并原封不动置于最终提示词最顶端。"));
    }
  }

  body.append(makeSectionTitle("SKILL（系统提示词）"));
  const skillOpts = xbrWidgetOptions(node, "skill_name");
  if (!skillOpts.length) skillOpts.push("不使用");
  if (!skillOpts.includes(draft.skill)) draft.skill = skillOpts[0];
  if (!XBR_SKILL_MODES.includes(draft.skillMode)) draft.skillMode = "自动";
  body.append(field("SKILL 模式", radioRow(XBR_SKILL_MODES, draft.skillMode, (v) => { draft.skillMode = v; ctx.rerender(); })));
  if (draft.skillMode === "手动") {
    body.append(field("SKILL选择", selectControl(skillOpts, draft.skill, (v) => { draft.skill = v; })));
  } else if (draft.skillMode === "自动") {
    const autoFile = (typeof modeSkillHint === "function") ? modeSkillHint(draft.mode) : "-";
    body.append(el("div", "font-size:11px;color:#8fb;margin:2px 0 8px;",
      "自动：本档（" + draft.mode + "）→ " + autoFile));
  } else {
    body.append(el("div", "font-size:11px;color:#d9a441;margin:2px 0 8px;",
      "不用：SKILL 完全不生效（即使下面选过文件也不会送进模型）。"));
  }
  const foxRow = el("div", "display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:2px 0 8px;");
  foxRow.append(smallBtn("📂 打开 SKILL 文件夹", "border:1px solid #555;background:#2a2a2a;color:#ccc;padding:4px 10px;",
    "在资源管理器里打开 support_llama/skills，方便新增 / 编辑技能文件",
    async () => {
      try {
        const r = await fetch("/xb_toolbox/skill_folder");
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false) notify("打开失败：" + (j.info || r.status), "error");
        else notify("已打开：" + (j.path || "skills"), "success");
      } catch (e) { notify("打开失败：" + ((e && e.message) || e), "error"); }
    }));
  body.append(foxRow);
  body.append(xbrHint("技能文件放在 XB_ToolBox/support_llama/skills（.txt / .md）：选中后整段作为模型自带系统提示词的替换内容（= 官方 Generate Text 的 system_prompt）。"));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.75;margin:6px 0 8px;",
    "· 自动（默认）= 按预设模式适配：图生图档 → system_prompt_edit，其余 → system_prompt_t2i；\n"
    + "· 手动 = 用「SKILL选择」里选中的那个文件；\n"
    + "· 不用 = 完全不生效（哪怕选了文件）；\n"
    + "· 「🤖 LLM设置 → 使用内置模板」关闭时，SKILL 不生效（与官方同义）；\n"
    + "· 新增技能文件后刷新页面即可出现在下拉里。"));
}

/* ── 弹窗内容：📖 使用说明 ───────────────────────────────── */
function xbrRenderHelp(body) {
  const lines = [
    "【一句话】",
    "  生图提示词预设 + 官方 Load CLIP + 官方 Generate Text：",
    "  表面挑词拼正文 → 文本编码器把正文写成完整提示词 → 设定词置顶输出",
    "",
    "【节点做什么（执行顺序）】",
    "  1. 正文 = 提示词框（或外接 📝 提示词 端口）的字",
    "  2. 送模型 = 【参考设定·本档设定词】+【正文】",
    "     （选中 SKILL 时，SKILL 全文另作为系统提示词送到最前面）",
    "  3. 输出提示词 = 本档设定词原封不动置顶 + 模型生成的正文",
    "  4. 输出空latent = 按空latent类型/画幅参数生成的空 latent",
    "",
    "【三步上手 · 文生图】",
    "  1. 🤖 LLM设置 选模型（类型 qwen_image，设备 default）",
    "  2. ✨ 预设参数 选输出语言 + 空latent类型 + 预设模式",
    "     （文生图组）+ SKILL 模式（保持自动即可）",
    "  3. 📊 空latent 接采样器、📝 提示词 接文本编码器，点运行",
    "",
    "【三步上手 · 图生图（图像编辑）】",
    "  1. ✨ 预设参数 选一个图生图档位（如 保持主体换场景）",
    "  2. 参考图接 🖼️ 图像（多张就接多张，按连接顺序 = 第 1…N 张图）",
    "  3. SKILL 模式保持「自动」：图生图档会自动用 system_prompt_edit.txt",
    "     提示词框里写要求（改哪里 / 换成什么，例：把背景换成草地）",
    "  · 图生图不要接 📊 空latent：官方编辑链路是",
    "    输入图 → VAEEncode → 采样",
    "  · 提示词输出接文本编码器/编辑节点即可",
    "",
    "【节点表面】",
    "  · 第 1 行按钮：🤖 LLM设置 ｜ ✨ 预设参数",
    "  · 第 2 行按钮：🎨 风格 ｜ 📐 视角 ｜ 👤 主体 ｜ 🕺 姿态 ｜ 👗 装扮 ｜ 🎒 道具 ｜ 💡 光影 ｜ 🏞️ 背景",
    "  · 画幅比例 / 宽度 / 高度 / 生成数量：按空latent类型的官方步长自动对齐",
    "  · 提示词框右上角 📋 复制；下面是参数设定显示，实时告诉你当前配置",
    "  · 没有开关：执行节点就会用文本编码器生成",
    "",
    "【元素面板怎么用】",
    "  · 点选项行 = 加入提示词，再点一下 = 移除",
    "  · 悬停选项行可以看它的中文与英文写法",
    "  · 【添加详细描述】给该词条写补充说明，会跟着一起成句",
    "  · ➕ / ➖ 自建专属词条，✎ 编辑名称",
    "  · 搜索框与「全部加入」只作用于当前子类",
    "",
    "【🤖 LLM设置】",
    "  · 模型选择 = 官方 Load CLIP：模型 / 类型 / 设备，枚举与官方节点逐字一致",
    "  · 参数设置 = 官方 Generate Text 全量参数：max_length ｜ sampling_mode ｜ temperature ｜",
    "    top_k ｜ top_p ｜ min_p ｜ repetition_penalty ｜ presence_penalty ｜ seed ｜",
    "    thinking ｜ use_default_template ｜ mtp",
    "  · sampling_mode = off 是贪心解码，采样参数与种子都不参与",
    "  · 种子支持生成后控制：点 🔁 在 随机 / 固定 / 增加 / 减少 之间切换",
    "  · 同一套参数只保留一份模型缓存，换模型 / 换类型 / 换设备才重新加载",
    "",
    "【SKILL 技能（系统提示词）】",
    "  · 文件放 XB_ToolBox/support_llama/skills（.txt / .md）",
    "    面板里点「📂 打开 SKILL 文件夹」可直接打开，新增后刷新页面即出现在下拉",
    "  · SKILL 模式（常驻三选一，默认自动）：",
    "      ◆ 自动 = 按预设模式适配：图生图档 → system_prompt_edit.txt，其余 → system_prompt_t2i.txt",
    "      ◆ 手动 = 用「SKILL选择」里选中的那个文件",
    "      ◆ 不用 = SKILL 完全不生效（哪怕选过文件）",
    "  · 选中后整段作为模型的系统提示词（= 官方 Generate Text 的 system_prompt）",
    "  · 选中 SKILL 时不再叠加节点的【输出语言】提示——技能自带语言规则，避免打架",
    "  · 「使用内置模板」关掉时 SKILL 不生效（与官方同义）",
    "  · 这两个技能要求输出单行 JSON：正常，见【常见问题】",
    "",
    "【✨ 预设参数】",
    "  · 生图预设：输出语言 / 空latent类型 / 预设模式 / 设定词",
    "  · SKILL 模式（自动 / 手动 / 不用）：见上",
    "  · 设定词：见上（无预设档则不前置）",
    "",
    "【文生图 / 图生图两套模版（全自动切换）】",
    "  · 没接 🖼️ 图像 → 走文生图模版：从零生成的写法，不会出现「参考输入图」类条款",
    "  · 接了 🖼️ 图像 → 走图生图模版：自动追加「以输入图为准」的条款，按序号引用第 1…N 张图",
    "  · 两种模版不用手动切：面板会显示当前用的是哪套 + 自动追加的条款原文",
    "  · 图生图档没接图也不会报错：会自动改成从零生成的写法（并在日志里提醒）",
    "",
    "【预设模式 · 文生图组（不需要图）】",
    "  · 无预设：不前置任何设定词，只输出正文",
    "  · 人物三视图 / 人物四视图 / 人物五视图：角色概念设计图",
    "  · 背景纯透明：RGBA 透明背景",
    "  · 图文版面：UI 截图 / 文档试卷 / 标题海报（文字逐字、版面层级）",
    "  · 信息图：多面板科普拆解卡（编号引线 / 图例 / 色卡 / 时间轴）",
    "  · 多格分镜：N 格叙事插画（格数排布 / 每格必须有主体 / 一致性强约束）",
    "  · 广告分镜板：商业脚本视觉板（画面格 + 时间轴 + 台词 + 镜头说明）",
    "",
    "【预设模式 · 图生图组（需接参考图，没接会自动降级为文生图写法）】",
    "  · 保持主体换场景：商品/人物原貌 100% 保持，换场景换装",
    "  · 局部编辑：只改指定或标记区域，其余完全不变",
    "  · 老照片修复：去噪去划痕 + 提清晰度 + 自然上色",
    "  · 整图风格化：整图转媒介/画风，构图与文字位置不变",
    "  · 360°全景：单视角照片扩成等距圆柱全景（2:1 无缝）",
    "  · 多图指认合成：按图号指认（场景取某张、角色/物件取其余张）",
    "",
    "【每档设定词都能改】",
    "  · 设定词会在最终提示词最顶端原封不动出现，也可只作为模型参考",
    "  · 改过的按「模式 + 语言」记在节点里，换模式 / 换语言都不丢",
    "  · 点 ♻️ 恢复默认 一键回到内置文本",
    "",
    "【参数怎么调】",
    "  · max_length：图文版面 / 信息图 / 多格分镜 / 广告分镜板 这几个长输出档建议 1024~2048，否则排版细则会被截断",
    "  · 想稳定复现：sampling_mode = off，或把生成后控制改成 固定",
    "  · 想更发散：temperature 调高、top_p 调大",
    "  · 思考模式：模型支持时更稳，长一点；思考内容不会进入输出",
    "",
    "【输入端口】",
    "  · 📝 提示词：外接提示词；接线后节点上的提示词框会锁定",
    "  · 🖼️ 图像：参考图；一批图 = N 张参考图（不抽帧），官方最多 10 张",
    "    用「📦 批量图像」等多图节点直接接这里即可，按顺序 = 第 1…N 张图",
    "",
    "【输出端口】",
    "  · 📝 提示词：最终提示词 = 本档设定词置顶 + 生成正文",
    "  · 📊 空latent：文生图直接进采样器；图生图不要接它",
    "",
    "【空latent 类型】",
    "  Anima / Boogu / Flux2 / Hunyuan / Krea2 / Qwen-image / SD3 / SDXL / Z-image",
    "  选你正在用的模型即可：通道数、下采样、尺寸步长、batch 上限会自动切换",
    "",
    "【常见问题】",
    "  · 输出是一段 JSON（含 rewritten_prompt 字段）：",
    "    这是 SKILL 自带的输出契约，属正常现象。",
    "    想只取正文（去掉 JSON 外壳）可以加个解析开关，告诉我即可。",
    "  · 中文技能却输出英文描述：SKILL 里的语言规则优先，这符合技能设计",
    "  · 选了图生图档却没接图：日志会告警，结果只会按纯文字生成",
    "  · SKILL 看起来没生效：检查 🤖 LLM设置 → 使用内置模板 是否为开",
    "  · 报「未找到文本编码器模型」：把文本编码器放进 models/text_encoders 再在 🤖 LLM设置 里选它",
    "  · 加载失败先看类型：Qwen-Image 系文本编码器要选 qwen_image",
    "  · 报 HIP error: device kernel image is invalid / invalid kernel file：你的 ComfyUI 跑在核显上了",
    "    （多 GPU 机器上核显常被枚举成 cuda:0）→ 启动前设 HIP_VISIBLE_DEVICES=1 让 ComfyUI 用独显再试",
    "  · 生成慢 / 显存不够：设备改 cpu，或把 max_length 调小",
    "  · 结果太发散：温度调低、top_p 调小；想复现同一结果就把生成后控制改成固定",
    "  · 节点表面参数很少？故意的：选项都收在弹窗里",
    "  · 改完参数要重新执行节点才生效",
    "",
    "【保存】",
    "  · 弹窗底部：☑ 自动保存（默认开）、字号 A− / A+、界面 − / %",
    "  · 所有配置随工作流保存；「取消」丢弃未保存改动",
  ];
  body.append(el("div", "font-size:12px;color:#bbb;line-height:1.9;white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;", lines.join("\n")));
}

const XBR_PANEL_RENDER = { llm: xbrRenderLlm, preset: xbrRenderPreset, help: xbrRenderHelp };

async function xbrOpenModal(node, panelId) {
  if (xbrModal) { try { xbrModal.close(); } catch (_) {} }
  const meta = XBR_PANEL_BUTTONS.find((b) => b.id === panelId) || XBR_PANEL_BUTTONS[0];
  const cur = xbrCurJson(node);
  const autoSaveRef = { value: cur.auto_save !== false };
  const draft = {
    settings: { qwen: xbrParseQwen(cur.qwen) },
    lang: xbrPick(String(xbrWidgetVal(node, "output_lang") ?? ""), LANGS, LANGS[0]),
    kind: xbrPick(String(xbrWidgetVal(node, "latent_kind") ?? ""), LATENT_KINDS, LATENT_KINDS[0]),
    mode: xbrPick(String(xbrWidgetVal(node, "preset_mode") ?? ""), MODES, MODES[0]),
    // 模版（自动 / 文生图 / 图生图）
    ioMode: (() => { const v = String(xbrWidgetVal(node, "io_mode") ?? ""); return XBR_IO_MODES.includes(v) ? v : "自动"; })(),
    // 设定词（三视图/四视图/五视图/背景纯透明）：弹窗内草稿 + 「用户是否改过」标记
    //   widget 里是「遗留默认句 / 任一内置预设句」→ 视为没改过 → 取「存档 → 当前模版默认」（无预设 = 空）
    presetText: (() => {
      const w = String(xbrWidgetVal(node, "three_view_text") ?? "");
      const md = xbrPick(String(xbrWidgetVal(node, "preset_mode") ?? ""), MODES, MODES[0]);
      const lg = xbrPick(String(xbrWidgetVal(node, "output_lang") ?? ""), LANGS, LANGS[0]);
      const ioW = String(xbrWidgetVal(node, "io_mode") ?? "");
      if (w.trim() && !isDefaultPresetText(md, w)) return w;
      return xbrPresetTextFor(node, md, lg, xbrResolveIo(node, XBR_IO_MODES.includes(ioW) ? ioW : "自动"));
    })(),
    presetTouched: false,
    // SKILL 选择（support_llama/skills 里的技能文件 = system_prompt）
    skill: String(xbrWidgetVal(node, "skill_name") ?? ""),
    skillMode: (() => { const v = String(xbrWidgetVal(node, "skill_mode") ?? ""); return XBR_SKILL_MODES.includes(v) ? v : "自动"; })(),
    // 官方 Load CLIP
    clip_name: String(xbrWidgetVal(node, "clip_name") ?? ""),
    clip_type: String(xbrWidgetVal(node, "clip_type") ?? "qwen_image"),
    device: String(xbrWidgetVal(node, "device") ?? "default"),
    // 官方 Generate Text 全量参数
    text: {
      max_length: xbrInt(xbrWidgetVal(node, "max_length"), 512, 1, 32768),
      sampling_mode: xbrPick(String(xbrWidgetVal(node, "sampling_mode") ?? "on"), XBR_SAMPLING_MODES, "on"),
      temperature: xbrNum(xbrWidgetVal(node, "temperature"), 0.7, 0.01, 2),
      top_k: xbrInt(xbrWidgetVal(node, "top_k"), 64, 0, 1000),
      top_p: xbrNum(xbrWidgetVal(node, "top_p"), 0.95, 0, 1),
      min_p: xbrNum(xbrWidgetVal(node, "min_p"), 0.05, 0, 1),
      repetition_penalty: xbrNum(xbrWidgetVal(node, "repetition_penalty"), 1.05, 0, 5),
      presence_penalty: xbrNum(xbrWidgetVal(node, "presence_penalty"), 0.0, 0, 5),
      seed: xbrInt(xbrWidgetVal(node, "seed"), 0, 0, Number.MAX_SAFE_INTEGER),
      ctl: String(xbrWidgetVal(node, XBR_SEED_CTL_WIDGET) ?? "randomize") || "randomize",
      thinking: xbrFlag(xbrWidgetVal(node, "thinking"), false),
      use_default_template: xbrFlag(xbrWidgetVal(node, "use_default_template"), true),
      mtp: xbrPick(String(xbrWidgetVal(node, "mtp") ?? "auto"), XBR_MTP_MODES, "auto"),
    },
  };

  const commit = async () => {
    xbrSetWidget(node, "output_lang", draft.lang, true);      // 语言设置
    xbrSetWidget(node, "latent_kind", draft.kind, true);      // 触发基础面板的步长/上限联动
    xbrSetWidget(node, "preset_mode", draft.mode, true);      // 触发预设句框显隐
    xbrSetWidget(node, "io_mode", draft.ioMode);               // 模版：自动 / 文生图 / 图生图
    xbrSetWidget(node, "skill_name", draft.skill);            // SKILL = 官方 system_prompt
    xbrSetWidget(node, "skill_mode", draft.skillMode);          // 自动 / 手动 / 不用
    // 设定词：写进节点 widget（原样）+ 按「模式|模版|语言」存档 → 换模式 / 换模版 / 换语言都不丢
    //   ⚠️ 一律写（包含「无预设」时写空串）→ 顺手把 widget 里的遗留默认句清掉
    try {
      const ioCommit = xbrResolveIo(node, draft.ioMode);
      node.__ippSetPreset?.(draft.presetText);
      node.__ippWritePreset?.(draft.mode, ioCommit, draft.lang, draft.presetText);
    } catch (_) {}
    // 官方 Load CLIP
    xbrSetWidget(node, "clip_name", draft.clip_name, true);
    xbrSetWidget(node, "clip_type", draft.clip_type, true);
    xbrSetWidget(node, "device", draft.device, true);
    // 官方 Generate Text 全量参数
    const t = draft.text;
    xbrSetWidget(node, "max_length", t.max_length);
    xbrSetWidget(node, "sampling_mode", t.sampling_mode);
    xbrSetWidget(node, "temperature", t.temperature);
    xbrSetWidget(node, "top_k", t.top_k);
    xbrSetWidget(node, "top_p", t.top_p);
    xbrSetWidget(node, "min_p", t.min_p);
    xbrSetWidget(node, "repetition_penalty", t.repetition_penalty);
    xbrSetWidget(node, "presence_penalty", t.presence_penalty);
    xbrSetWidget(node, "seed", t.seed);
    xbrSetWidget(node, XBR_SEED_CTL_WIDGET, t.ctl);   // 与原生种子控制同一份值
    xbrSetWidget(node, "thinking", t.thinking);
    xbrSetWidget(node, "use_default_template", t.use_default_template);
    xbrSetWidget(node, "mtp", t.mtp);
    xbrSaveJson(node, { qwen: draft.settings.qwen, auto_save: autoSaveRef.value !== false });
    try { node.__qbrRefreshInfo?.(); } catch (_) {}
  };
  const immediate = () => { xbrSaveJson(node, { auto_save: autoSaveRef.value !== false }); };

  const readonly = (panelId === "help");
  const body = xbrDialog({
    label: meta.title,
    title: meta.title,
    subtitle: meta.subtitle,
    autoSaveRef: readonly ? null : autoSaveRef,
    onCommit: readonly ? null : commit,
    onImmediate: readonly ? null : immediate,
    onChange: readonly ? null : () => { try { node.__qbrRefreshInfo?.(); } catch (_) {} },
  }).body;

  const ctx = {
    rerender: () => { body.replaceChildren(); renderInto(); },
    touch: () => {},
  };
  function renderInto() {
    try { XBR_PANEL_RENDER[panelId](body, node, draft, ctx); }
    catch (e) { body.append(el("div", "color:#e55;font-size:12px;", "面板渲染失败：" + ((e && e.message) || e))); }
  }
  renderInto();
}

/* ── 按钮区 / 提示词框标题行 / 参数设定显示 / 锁定 ─────────── */
function xbrBuildButtonRow(node) {
  const grid = el("div", "display:grid;grid-template-columns:repeat(" + Math.max(1, XBR_PANEL_BUTTONS.length) + ",1fr);grid-auto-rows:30px;gap:6px;flex:0 0 auto;");
  for (const b of XBR_PANEL_BUTTONS) {
    const btn = el("button", "width:100%;height:30px;box-sizing:border-box;display:flex;align-items:center;justify-content:center;border-radius:6px;border:2px solid #5b9bd5;background:#3a3a3a;color:#eee;font-size:13px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:inherit;", b.label);
    btn.title = `打开「${b.title}」弹窗`;
    btn.dataset.xbrProBtn = b.id;
    btn.addEventListener("mousedown", (e) => e.stopPropagation());
    btn.addEventListener("mouseenter", () => { btn.style.background = "#4a4a4a"; });
    btn.addEventListener("mouseleave", () => { btn.style.background = "#3a3a3a"; });
    btn.addEventListener("click", (e) => { e.stopPropagation(); xbrOpenModal(node, b.id); });
    grid.append(btn);
  }
  return grid;
}

/** 显示窗取值：去掉括号注释与语言标签（[ZH]/[EN]），只留干净的值 */
function xbrClean(v) {
  let s = String(v == null ? "" : v);
  s = s.replace(/\s*[\[［][^\]］]*[\]］]\s*$/g, "");      // 尾部 [ZH] / [EN] 之类的语言标签
  s = s.replace(/（[^）]*）|\([^)]*\)/g, "");                 // 中英文括号注释
  return s.trim();
}

/** 参数设定显示（只读摘要 5 行）*/
function xbrInfoLines(node, promptText) {
  const qwen = xbrParseQwen(xbrCurJson(node).qwen);
  const genLen = Number(node.__qbrGenLen || 0);
  const model = xbrClean(xbrWidgetVal(node, "clip_name"));
  const modelShort = String(model).split(/[\\/]/).pop() || model;   // 只留文件名，不带目录
  const line1 = `📊 空 latent：${xbrClean(xbrWidgetVal(node, "latent_kind"))} ｜ ${xbrWidgetVal(node, "width")}x${xbrWidgetVal(node, "height")} ｜ 数量 ${xbrWidgetVal(node, "batch_size")}`;
  const line2 = `🤖 LLM 模型：${modelShort || "未选择"}`;
  const line3 = `⚙️ Text 参数: 最大长度 ${xbrWidgetVal(node, "max_length")} 丨 思考模式 ${xbrFlag(xbrWidgetVal(node, "thinking"), false) ? "开" : "关"} 丨 温度 ${xbrWidgetVal(node, "temperature")}`;
  const ctlRaw = xbrClean(xbrWidgetVal(node, XBR_SEED_CTL_WIDGET)) || "randomize";
  const line4 = `✨ 生成种子：${xbrWidgetVal(node, "seed")} ｜ ${XBR_SEED_LABEL[ctlRaw] || ctlRaw}`;
  const line5 = `📝 文本数量：${genLen} 字`;
  return [line1, line2, line3, line4, line5].join("\n");
}

/** 提示词框标题行（左标签 + 右复制）+ 参数设定显示；并挂上端口锁定/执行回写/摘要刷新 */
function xbrBuildPromptHeader(node, promptBox) {
  const head = el("div", "display:flex;align-items:center;gap:8px;flex:0 0 auto;");
  const lab = el("div", "font-size:12px;color:#bbb;", "📝 节点提示词（与面板预览框双向同步）");
  const copy = smallBtn("📋 复制", "margin-left:auto;", "复制提示词框内容", () => { copyText(promptBox.value || ""); });
  head.append(lab, copy);

  const infoBox = el("div", "flex:0 0 auto;height:150px;overflow:auto;background:#1c1c1e;border:1px solid #333;border-radius:6px;padding:6px 9px;font-size:11px;line-height:1.65;color:#b9c6d2;white-space:pre-wrap;box-sizing:border-box;font-family:ui-monospace,Consolas,monospace;");
  infoBox.dataset.captureWheel = "true";
  infoBox.title = "当前配置摘要（只读）";

  const refresh = () => { try { infoBox.textContent = xbrInfoLines(node, promptBox.value); } catch (_) {} };
  node.__qbrRefreshInfo = refresh;
  node.__ippRefreshInfo = refresh;   // 基础面板改了设定词存档也会来刷这条摘要

  // 「📝 提示词」端口接线 → 锁定提示词框（二选一）
  const updateLock = () => {
    try {
      const inp = (node.inputs || []).find((i) => i.name === "text");
      const linked = !!inp && inp.link != null;
      promptBox.readOnly = linked;
      promptBox.style.background = linked ? "#141416" : "#1d1d1d";
      promptBox.style.color = linked ? "#8a8a8a" : "#ccc";
      promptBox.title = linked ? "已由「📝 提示词」端口控制，断开连线后恢复编辑" : "";
      lab.textContent = linked ? "📝 提示词已锁定（由「📝 提示词」端口控制）" : "📝 节点提示词（与面板预览框双向同步）";
      lab.style.color = linked ? "#d9a441" : "#bbb";
    } catch (_) {}
  };
  const prevConn = node.onConnectionsChange;
  node.onConnectionsChange = function (...a) {
    const r = prevConn?.apply(this, a);
    setTimeout(updateLock, 0);
    return r;
  };
  updateLock();

  // 生成后控制：后端算好的「下一次种子」回写到 seed widget；同时记下本次生成文本字数（状态窗用）
  const prevExecuted = node.onExecuted;
  node.onExecuted = function (msg) {
    const r = prevExecuted?.apply(this, arguments);
    try {
      const ns = msg?.seed?.[0];
      if (ns !== undefined && ns !== null && ns !== "") {
        const cur = Number(xbrWidgetVal(node, "seed"));
        if (Number(ns) !== cur) xbrSetWidget(node, "seed", Math.max(0, Math.round(Number(ns)) || 0));
      }
      const gl = msg?.gen_len?.[0];
      if (gl !== undefined && gl !== null) node.__qbrGenLen = Number(gl) || 0;
      refresh();
    } catch (_) {}
    return r;
  };

  // 表面参数变化 → 摘要刷新（只 setDirtyCanvas，不动用 setSize）
  for (const nm of ["latent_kind", "output_lang", "preset_mode", "three_view_text", "aspect_ratio",
                    "width", "height", "batch_size", "clip_name", "clip_type", "device",
                    "max_length", "sampling_mode", "temperature", "top_k", "top_p", "min_p",
                    "repetition_penalty", "presence_penalty", "seed", "thinking",
                    "use_default_template", "mtp"]) {
    const w = xbrWidget(node, nm);
    if (!w || w.__qbrHooked) continue;
    w.__qbrHooked = true;
    const orig = w.callback;
    w.callback = function (...a) {
      const r = orig?.apply(this, a);
      setTimeout(refresh, 0);
      return r;
    };
  }
  promptBox.addEventListener("input", () => { setTimeout(refresh, 0); });

  setTimeout(refresh, 0);
  return [head, infoBox];
}
