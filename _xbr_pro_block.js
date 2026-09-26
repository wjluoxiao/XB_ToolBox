/* ============================================================================
 *  ✨ 提示词增强反推（融合进「🖼️ 生图提示词预设Pro」）
 *  ---------------------------------------------------------------------------
 *  节点表面新增：3 个按钮（🤖 大语言模型配置 ｜ ✨ 提示词增强预设 ｜ 📖 使用说明）
 *                + 「✅ 启用 LLM 反推」开关（节点表面参数，默认关）
 *                + 提示词框标题行（右侧「📋 复制」）+ 参数设定显示（只读摘要）
 *                + 「📝 提示词」端口接线 → 提示词框锁定（二选一）
 *  弹窗：导演台同款二级弹窗（底部：自动保存 + 字号 + 界面缩放 + 取消/💾 保存）
 *  配置：manager_settings.llm = { model, run, params, extra_system }（与后端 _llm_section 对齐）
 *  说明：本块所有标识符统一 xbr/XBR 前缀，避免与生图预设面板既有函数/常量重名。
 * ========================================================================== */

const XBR_DEFAULT_PROVIDER = "OpenAI 兼容 (OpenAI/DeepSeek/Qwen/GLM/Kimi/Ollama/vLLM/LM Studio)";
const XBR_API_DEFAULTS = {
  provider: XBR_DEFAULT_PROVIDER,
  model: "deepseek-v4-flash-vision-exp",
  api_key: "",
  base_url: "https://api.deepseek.com/v1",
  temperature: 0.6,
  max_tokens: 8192,
  thinking: "disabled",
};
const XBR_BACKENDS = [
  { value: "本地模型", label: "本地模型 [local]" },
  { value: "在线 API", label: "在线API [api]" },
];
const XBR_INFERENCE_MODES = ["one by one", "images", "video"];
const XBR_SEED_MODES = ["randomize", "fixed", "increment", "decrement"];
const XBR_SEED_LABEL = { randomize: "随机", fixed: "固定", increment: "增加", decrement: "减少" };
const XBR_PANEL_BUTTONS = [
  { id: "llm", label: "🤖 LLM设置", title: "🤖 LLM设置", subtitle: "LLM 反推的后端与推理配置；本弹窗里的「输出语言」是全节点唯一的语言设置（决定词表加载语言 + 最终提示词语言）。" },
  { id: "preset", label: "✨ 增强预设", title: "✨ 增强预设", subtitle: "空latent类型 / 预设模式 / 增强预设（= 提示词设定）/ 反推预设 / 追加设定。提示词正文在节点上的提示词框里编辑。" },
  { id: "help", label: "📖 使用说明", title: "📖 使用说明", subtitle: "端口 / 按钮 / 保存说明。" },
];
const XBR_API_ENDPOINT = "/xb_toolbox/llm_api_settings";

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

const XBR_INFERENCE_MODES_ = XBR_INFERENCE_MODES;
function xbrLlmDefaults() {
  return {
    model: { model: "", mmproj: "None", chat_handler: "None", n_ctx: 8192, vram_limit: -1, image_min_tokens: 0, image_max_tokens: 0 },
    run: { inference_mode: "one by one", max_frames: 24, max_size: 256, seed: 0, seed_control: "randomize", force_offload: false, save_states: false },
    params: {
      max_tokens: 6144, top_k: 40, top_p: 0.9, min_p: 0.05, typical_p: 1.0, temperature: 0.6,
      repeat_penalty: 1.12, frequency_penalty: 0.0, present_penalty: 0.0,
      mirostat_mode: 0, mirostat_eta: 0.1, mirostat_tau: 5.0, state_uid: -1,
    },
    extra_system: "",
  };
}
/** 解析 manager_settings.llm（缺失/非法一律安全回落） */
function xbrParseLlm(raw) {
  const d = (raw && typeof raw === "object") ? raw : {};
  const cfg = xbrLlmDefaults();
  const m = (d.model && typeof d.model === "object") ? d.model : {};
  cfg.model.model = String(m.model ?? "");
  cfg.model.mmproj = String(m.mmproj ?? "None");
  cfg.model.chat_handler = String(m.chat_handler ?? "None");
  cfg.model.n_ctx = xbrInt(m.n_ctx, cfg.model.n_ctx, 1024, 327680);
  cfg.model.vram_limit = xbrInt(m.vram_limit, cfg.model.vram_limit, -1, 1024);
  cfg.model.image_min_tokens = xbrInt(m.image_min_tokens, 0, 0, 4096);
  cfg.model.image_max_tokens = xbrInt(m.image_max_tokens, 0, 0, 4096);

  const r = (d.run && typeof d.run === "object") ? d.run : {};
  cfg.run.inference_mode = xbrPick(r.inference_mode, XBR_INFERENCE_MODES, cfg.run.inference_mode);
  cfg.run.max_frames = xbrInt(r.max_frames, cfg.run.max_frames, 2, 1024);
  cfg.run.max_size = xbrInt(r.max_size, cfg.run.max_size, 128, 16384);
  cfg.run.seed = xbrInt(r.seed, cfg.run.seed, 0, Number.MAX_SAFE_INTEGER);
  cfg.run.seed_control = xbrPick(r.seed_control, XBR_SEED_MODES, cfg.run.seed_control);
  cfg.run.force_offload = xbrFlag(r.force_offload, cfg.run.force_offload);
  cfg.run.save_states = xbrFlag(r.save_states, cfg.run.save_states);

  const p = (d.params && typeof d.params === "object") ? d.params : {};
  cfg.params.max_tokens = xbrInt(p.max_tokens, cfg.params.max_tokens, 0, 262144);
  cfg.params.top_k = xbrInt(p.top_k, cfg.params.top_k, 0, 1000);
  cfg.params.top_p = xbrNum(p.top_p, cfg.params.top_p, 0, 1);
  cfg.params.min_p = xbrNum(p.min_p, cfg.params.min_p, 0, 1);
  cfg.params.typical_p = xbrNum(p.typical_p, cfg.params.typical_p, 0, 1);
  cfg.params.temperature = xbrNum(p.temperature, cfg.params.temperature, 0, 2);
  cfg.params.repeat_penalty = xbrNum(p.repeat_penalty, cfg.params.repeat_penalty, 0, 10);
  cfg.params.frequency_penalty = xbrNum(p.frequency_penalty, cfg.params.frequency_penalty, 0, 1);
  cfg.params.present_penalty = xbrNum(p.present_penalty, cfg.params.present_penalty, 0, 2);
  cfg.params.mirostat_mode = xbrInt(p.mirostat_mode, cfg.params.mirostat_mode, 0, 2);
  cfg.params.mirostat_eta = xbrNum(p.mirostat_eta, cfg.params.mirostat_eta, 0, 1);
  cfg.params.mirostat_tau = xbrNum(p.mirostat_tau, cfg.params.mirostat_tau, 0, 10);
  cfg.params.state_uid = xbrInt(p.state_uid, cfg.params.state_uid, -1, 999999);
  cfg.extra_system = String(d.extra_system ?? "");
  return cfg;
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

/* ── 预设设定词（三视图 / 四视图 / 背景纯透明的设定文本）─────────────
 * · 用户改过的按「模式|语言」存进节点（基础面板的 preset_texts 存档）；
 * · 弹窗读「存档 → 默认」，提交时同步写 widget + 存档。 */
function xbrPresetStore(node) {
  try { return parsePresetTexts(xbrCurJson(node).preset_texts); } catch (_) { return {}; }
}
function xbrPresetTextFor(node, mode, lang) {
  const t = xbrPresetStore(node)[presetKeyOf(mode, lang)];
  return (t && String(t).trim()) ? t : (defaultPresetOf(mode, lang) || "");
}

/* ── 在线 API（存 ComfyUI user 目录，Key 不进工作流）──────── */
async function xbrApiGet() {
  const resp = await api.fetchApi(XBR_API_ENDPOINT);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
  return { settings: data.settings || {}, providers: data.providers || [] };
}
async function xbrApiPut(payload) {
  const resp = await api.fetchApi(XBR_API_ENDPOINT, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
  return data.settings || payload;
}
function xbrNormApi(raw) {
  const x = { ...XBR_API_DEFAULTS, ...(raw && typeof raw === "object" ? raw : {}) };
  x.provider = String(x.provider || "").trim() || XBR_DEFAULT_PROVIDER;
  x.model = String(x.model ?? "").trim() || XBR_API_DEFAULTS.model;
  x.base_url = String(x.base_url ?? "").trim() || XBR_API_DEFAULTS.base_url;
  x.api_key = String(x.api_key ?? "");
  x.temperature = xbrNum(x.temperature, XBR_API_DEFAULTS.temperature, 0, 2);
  x.max_tokens = xbrInt(x.max_tokens, XBR_API_DEFAULTS.max_tokens, 1, 262144);
  x.thinking = (x.thinking === "enabled") ? "enabled" : "disabled";
  return x;
}

/* ── 本地模型候选（取「📦 模型加载器」的 object_info，单一真相）── */
let xbrModelLists = null;
async function xbrLoadModelLists(force) {
  if (xbrModelLists && !force) return xbrModelLists;
  try {
    const resp = await api.fetchApi("/object_info/XB_llamaModelLoader");
    const data = await resp.json();
    const req = data?.XB_llamaModelLoader?.input?.required || {};
    xbrModelLists = {
      model: Array.isArray(req.model?.[0]) ? req.model[0] : [],
      mmproj: Array.isArray(req.mmproj?.[0]) ? req.mmproj[0] : ["None"],
      chat_handler: Array.isArray(req.chat_handler?.[0]) ? req.chat_handler[0] : ["None"],
    };
  } catch (_) {
    xbrModelLists = { model: [], mmproj: ["None"], chat_handler: ["None"] };
  }
  return xbrModelLists;
}

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
function xbrRenderLlm(body, node, draft, ctx) {
  const s = draft.settings.llm;

  body.append(makeSectionTitle("输出语言（全节点唯一的语言设置）"));
  body.append(field("输出语言", selectControl(LANGS, draft.lang, (v) => {
    draft.lang = v;
    // 换语言 → 未在弹窗里改过设定词时，跟着取该语言的「存档 → 默认」
    if (!draft.presetTouched) draft.presetText = xbrPresetTextFor(node, draft.mode, v);
  })));
  body.append(xbrHint("本项是唯一的语言设置：① 元素词表 / 预设句按哪种语言加载　② LLM 反推最终输出的提示词是中文还是英文。其他地方不再有语言选项。"));

  body.append(makeSectionTitle("提示词增强反推（总开关在节点表面的「启用 LLM 反推」）"));

  body.append(makeSectionTitle("LLM 后端"));
  body.append(field("LLM 后端", radioRow(XBR_BACKENDS, draft.backend, (v) => { draft.backend = v; ctx.rerender(); })));

  if (draft.backend !== "在线 API") {
    body.append(makeSectionTitle("本地 LLM 模型"));
    const lists = xbrModelLists || { model: [], mmproj: ["None"], chat_handler: ["None"] };
    const llm = s.model;
    const models = lists.model.length ? lists.model : (llm.model ? [llm.model] : []);
    if (!llm.model && models.length) llm.model = models[0];
    body.append(field("强制卸载", checkboxControl(s.run.force_offload, "LLM 用完即卸载（释放显存）", (v) => { s.run.force_offload = v; })));
    if (models.length) body.append(field("模型", selectControl(models, llm.model, (v) => { llm.model = v; })));
    else body.append(field("模型", xbrTextControl(llm.model, "未找到本地 LLM 模型（.gguf 放到 models/LLM）", (v) => { llm.model = v; })));
    body.append(field("视觉模块 mmproj", selectControl(lists.mmproj.length ? lists.mmproj : ["None"], llm.mmproj, (v) => { llm.mmproj = v; })));
    body.append(field("Chat Handler", selectControl(lists.chat_handler.length ? lists.chat_handler : ["None"], llm.chat_handler, (v) => { llm.chat_handler = v; })));
    body.append(field("上下文长度 n_ctx", xbrNumberControl(llm.n_ctx, { min: 1024, max: 327680, step: 128 }, (v) => { llm.n_ctx = Math.round(v); })));
    body.append(field("显存上限 vram_limit (GB)", xbrNumberControl(llm.vram_limit, { min: -1, max: 1024, step: 1 }, (v) => { llm.vram_limit = Math.round(v); })));
    body.append(field("图像最小 tokens", xbrNumberControl(llm.image_min_tokens, { min: 0, max: 4096, step: 32 }, (v) => { llm.image_min_tokens = Math.round(v); })));
    body.append(field("图像最大 tokens", xbrNumberControl(llm.image_max_tokens, { min: 0, max: 4096, step: 32 }, (v) => { llm.image_max_tokens = Math.round(v); })));

    const p = s.params;
    body.append(field("max_tokens", xbrNumberControl(p.max_tokens, { min: 0, max: 262144, step: 1 }, (v) => { p.max_tokens = Math.round(v); })));
    body.append(field("top_k", xbrNumberControl(p.top_k, { min: 0, max: 1000, step: 1 }, (v) => { p.top_k = Math.round(v); })));
    body.append(field("top_p", xbrNumberControl(p.top_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.top_p = v; })));
    body.append(field("min_p", xbrNumberControl(p.min_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.min_p = v; })));
    body.append(field("typical_p", xbrNumberControl(p.typical_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.typical_p = v; })));
    body.append(field("temperature", xbrNumberControl(p.temperature, { min: 0, max: 2, step: 0.01 }, (v) => { p.temperature = v; })));
    body.append(field("repeat_penalty", xbrNumberControl(p.repeat_penalty, { min: 0, max: 10, step: 0.01 }, (v) => { p.repeat_penalty = v; })));
    body.append(field("frequency_penalty", xbrNumberControl(p.frequency_penalty, { min: 0, max: 1, step: 0.01 }, (v) => { p.frequency_penalty = v; })));
    body.append(field("present_penalty", xbrNumberControl(p.present_penalty, { min: 0, max: 2, step: 0.01 }, (v) => { p.present_penalty = v; })));
    body.append(field("mirostat_mode", xbrNumberControl(p.mirostat_mode, { min: 0, max: 2, step: 1 }, (v) => { p.mirostat_mode = Math.round(v); })));
    body.append(field("mirostat_eta", xbrNumberControl(p.mirostat_eta, { min: 0, max: 1, step: 0.01 }, (v) => { p.mirostat_eta = v; })));
    body.append(field("mirostat_tau", xbrNumberControl(p.mirostat_tau, { min: 0, max: 10, step: 0.01 }, (v) => { p.mirostat_tau = v; })));
  }

  if (draft.backend === "在线 API") {
    body.append(makeSectionTitle("在线 API"));
    const a = draft.api || (draft.api = { ...XBR_API_DEFAULTS });
    body.append(field("服务商", selectControl(ctx.providers, a.provider, (v) => { a.provider = v; })));
    body.append(field("模型", xbrTextControl(a.model, XBR_API_DEFAULTS.model, (v) => { a.model = v; })));
    body.append(field("API Key", xbrPasswordControl(a.api_key, "sk-…（保存在本地，不写入工作流）", (v) => { a.api_key = v; })));
    body.append(field("Base URL", xbrTextControl(a.base_url, XBR_API_DEFAULTS.base_url, (v) => { a.base_url = v; })));
    body.append(field("temperature", xbrNumberControl(a.temperature, { min: 0, max: 2, step: 0.01 }, (v) => { a.temperature = v; })));
    body.append(field("max_tokens", xbrNumberControl(a.max_tokens, { min: 1, max: 262144, step: 1 }, (v) => { a.max_tokens = Math.round(v); })));
    body.append(field("thinking", selectControl(["disabled", "enabled"], a.thinking, (v) => { a.thinking = v; })));
    body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "默认：deepseek-v4-flash-vision-exp ｜ https://api.deepseek.com/v1（可改）。配置保存在本地 ComfyUI user 目录，不会写入工作流。"));
  }

  body.append(makeSectionTitle("随机种子"));
  body.append(xbrSeedRow(s.run, () => ctx.touch?.()));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "点「🔁」切换生成后控制：随机 = 运行后自动换新种子；固定 = 锁定；增加/减少 = 运行后 ±1（后端算完会回写）。"));

  body.append(makeSectionTitle("指令推理"));
  body.append(field("推理模式", selectControl(XBR_INFERENCE_MODES, s.run.inference_mode, (v) => { s.run.inference_mode = v; })));
  body.append(field("最大帧数", xbrNumberControl(s.run.max_frames, { min: 2, max: 1024, step: 1 }, (v) => { s.run.max_frames = Math.round(v); })));
  body.append(field("最大尺寸", xbrNumberControl(s.run.max_size, { min: 128, max: 16384, step: 64 }, (v) => { s.run.max_size = Math.round(v); })));
  body.append(field("保存对话状态", checkboxControl(s.run.save_states, "在内存中保留本次对话上下文（多轮连续反推）", (v) => { s.run.save_states = v; })));
  body.append(field("状态 UID", xbrNumberControl(s.params.state_uid, { min: -1, max: 999999, step: 1 }, (v) => { s.params.state_uid = Math.round(v); })));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "提示词正文在节点上的提示词框里编辑；「📝 提示词」端口接线后该框锁定。"));
}

/* ── 弹窗内容：✨ 提示词增强预设 ─────────────────────────── */
function xbrRenderPreset(body, node, draft, ctx) {
  const s = draft.settings.llm;

  body.append(makeSectionTitle("生图预设"));
  body.append(field("空latent类型", selectControl(LATENT_KINDS, draft.kind, (v) => { draft.kind = v; })));
  body.append(xbrHint("空latent类型：选你正在用的模型即可（形状 / 下采样 / 尺寸步长自动适配 8/16/32）。"));
  body.append(field("预设模式", selectControl(MODES, draft.mode, (v) => {
    draft.mode = v;
    // 换模式 → 立刻取该模式的设定词（用户改过的存档 → 默认），改过的不会被冲掉
    draft.presetTouched = false;
    draft.presetText = xbrPresetTextFor(node, v, draft.lang);
    ctx.rerender();     // 有/无设定词的模式之间切换 → 重画「设定词」区
  })));
  body.append(xbrHint("常规文生图 = 只输出正文；人物三视图 / 人物四视图 / 背景纯透明 = 最终提示词最顶端自动加上该模式的设定词。"));

  // ── 设定词（预设模式对应的设定文本；只在弹窗里编辑，节点表面不显示）──
  const modeDef = defaultPresetOf(draft.mode, draft.lang);
  if (modeDef) {
    body.append(makeSectionTitle("设定词"));
    if (!String(draft.presetText || "").trim()) draft.presetText = modeDef;
    const taP = textareaControl(draft.presetText, (v) => { draft.presetText = v; draft.presetTouched = true; },
      "width:100%;box-sizing:border-box;min-height:180px;resize:vertical;");
    taP.placeholder = "该模式的设定词（改过的按「模式 + 语言」记进节点，换模式 / 换语言都不丢）";
    taP.spellcheck = false;
    body.append(taP);
    const taRow = el("div", "display:flex;align-items:center;gap:10px;margin:6px 0 4px;");
    taRow.append(smallBtn("♻️ 恢复默认", "border:1px solid #555;background:#2a2a2a;color:#ccc;padding:4px 10px;",
      "把设定词恢复为该模式 × 该语言的默认文本",
      () => { draft.presetText = modeDef; draft.presetTouched = false; ctx.rerender(); }));
    taRow.append(el("span", "font-size:11px;color:#888;",
      String(draft.presetText || "") === modeDef ? "当前 = 默认" : "当前 = 自定义"));
    body.append(taRow);
    body.append(el("div", "font-size:11px;color:#888;line-height:1.75;margin:6px 0 8px;",
      "· 最终输出时，设定词会原封不动加在增强后提示词的最顶端；\n"
      + "· LLM 只增强正文，把设定词当作增强参考，不会改写它；\n"
      + "· 改过的设定词随节点保存，换模式 / 换语言都会取回你改过的那一版。"));
  } else {
    body.append(el("div", "font-size:11px;color:#888;line-height:1.75;margin:6px 0 8px;", "常规文生图 = 没有设定词，直接输出正文。"));
  }

  body.append(makeSectionTitle("增强预设（= 提示词设定 / system prompt）"));
  const presetOpts = xbrWidgetOptions(node, "preset");
  if (presetOpts.length) body.append(field("增强预设", selectControl(presetOpts, draft.preset, (v) => { draft.preset = v; })));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "该预设内容即「🧩 提示词设定」输出的正文，同时作为 LLM 反推的系统提示词。"));

  body.append(makeSectionTitle("反推预设"));
  const taskOpts = xbrWidgetOptions(node, "task_preset");
  if (taskOpts.length) body.append(field("反推预设", selectControl(taskOpts, draft.task_preset, (v) => { draft.task_preset = v; })));
  body.append(el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", "带 * 的预设里 * 是必填占位符，由节点上的提示词框或外接「📝 提示词」填入。"));

  body.append(makeSectionTitle("追加设定（可留空）"));
  const ta = textareaControl(s.extra_system, (v) => { s.extra_system = v; },
    "width:100%;box-sizing:border-box;min-height:200px;resize:vertical;");
  ta.placeholder = "追加在增强预设之后的额外要求（例：只输出一行、不要解释过程…）";
  ta.spellcheck = false;
  body.append(ta);
}

/* ── 弹窗内容：📖 使用说明 ───────────────────────────────── */
function xbrRenderHelp(body) {
  const lines = [
    "【本节点 = 生图提示词预设 + 提示词增强反推】",
    "",
    "【输入端口】",
    "  · 📝 提示词：外接提示词。接上线后节点上的提示词框会锁定（二选一）",
    "  · 🖼️ 图像：外接图像 / 视频帧（LLM 反推：图 → 提示词）",
    "",
    "【输出端口】",
    "  · 📝 提示词：最终提示词（未启用 LLM = 拼装好的提示词；启用 LLM = 设定词原样置顶 + LLM 增强后的正文）",
    "  · 📋 提示词列表：按行拆分",
    "  · 🧩 提示词设定：本次的提示词设定（增强预设 + 输出语言 + 追加设定）",
    "  · 🖼️ 空latent：按「空latent类型」生成（官方 latent_format 逐字段对齐）",
    "",
    "【节点表面】",
    "  · 第 1 行按钮：🤖 LLM设置（唯一语言设置 / 后端 / 采样参数）｜ ✨ 增强预设（空latent类型 / 预设模式 / 增强预设 / 反推预设 / 追加设定）｜ 📖 使用说明",
    "  · 第 2 行按钮：8 个元素分类（点选项行加入/移除提示词，【添加详细描述】写补充说明）",
    "  · ✅ 启用 LLM 反推：关（默认）= 原「生图提示词预设」行为；开 = 图/文 → 提示词",
    "  · 设定词：预设模式（三视图 / 四视图 / 背景纯透明）的设定文本，在「✨ 增强预设」弹窗里编辑；"
    + "改过的随节点保存，换模式 / 换语言不丢；输出时原封不动加在增强结果的顶端，也作为 LLM 的增强参考",
    "  · 提示词框右上角「📋 复制」；下方「参数设定显示」实时显示当前配置",
    "",
    "【保存】",
    "  · 弹窗底部：☑ 自动保存（默认开）+ 字号 + 界面缩放；「取消」丢弃未保存改动",
    "  · 配置随工作流保存；在线 API 的 Key 存在 ComfyUI user 目录，不进工作流",
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
    settings: { llm: xbrParseLlm(cur.llm) },
    backend: String(xbrWidgetVal(node, "backend") ?? XBR_BACKENDS[0].value),
    preset: String(xbrWidgetVal(node, "preset") ?? ""),
    task_preset: String(xbrWidgetVal(node, "task_preset") ?? ""),
    lang: xbrPick(String(xbrWidgetVal(node, "output_lang") ?? ""), LANGS, LANGS[0]),
    kind: xbrPick(String(xbrWidgetVal(node, "latent_kind") ?? ""), LATENT_KINDS, LATENT_KINDS[0]),
    mode: xbrPick(String(xbrWidgetVal(node, "preset_mode") ?? ""), MODES, MODES[0]),
    // 设定词（三视图/四视图/背景纯透明）：弹窗内草稿 + 「用户是否改过」标记
    presetText: String(xbrWidgetVal(node, "three_view_text") ?? ""),
    presetTouched: false,
  };

  let apiSaved = null, providers = [XBR_DEFAULT_PROVIDER];
  if (panelId === "llm") {
    try {
      const r = await xbrApiGet();
      apiSaved = xbrNormApi(r.settings);
      if (r.providers?.length) providers = r.providers;
    } catch (_) { apiSaved = xbrNormApi(node.__xbrProApiInfo); }
    node.__xbrProApiInfo = apiSaved;
    draft.api = { ...apiSaved };
  }

  const commit = async () => {
    if (panelId === "llm" && draft.api && apiSaved
      && JSON.stringify(xbrNormApi(draft.api)) !== JSON.stringify(apiSaved)) {
      try {
        apiSaved = xbrNormApi(await xbrApiPut(xbrNormApi(draft.api)));
        draft.api = { ...apiSaved };
        node.__xbrProApiInfo = apiSaved;
      } catch (e) { notify("API 配置保存失败：" + ((e && e.message) || e), "error"); }
    }
    xbrSetWidget(node, "output_lang", draft.lang, true);      // 唯一语言设置
    xbrSetWidget(node, "latent_kind", draft.kind, true);      // 触发基础面板的步长/上限联动
    xbrSetWidget(node, "preset_mode", draft.mode, true);      // 触发预设句框显隐
    // 设定词：写进节点 widget（原样）+ 按「模式|语言」存档 → 换模式 / 换语言都不丢
    try {
      if (defaultPresetOf(draft.mode, draft.lang)) {
        node.__ippSetPreset?.(draft.presetText);
        node.__ippWritePreset?.(draft.mode, draft.lang, draft.presetText);
      }
    } catch (_) {}
    xbrSetWidget(node, "backend", draft.backend, true);
    xbrSetWidget(node, "preset", draft.preset, true);
    xbrSetWidget(node, "task_preset", draft.task_preset, true);
    xbrSaveJson(node, { llm: draft.settings.llm, auto_save: autoSaveRef.value !== false });
    try { node.__xbrProRefreshInfo?.(); } catch (_) {}
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
    onChange: readonly ? null : () => { try { node.__xbrProRefreshInfo?.(); } catch (_) {} },
  }).body;

  const ctx = {
    providers,
    rerender: () => { body.replaceChildren(); renderInto(); },
    touch: () => {},
  };
  function renderInto() {
    try { XBR_PANEL_RENDER[panelId](body, node, draft, ctx); }
    catch (e) { body.append(el("div", "color:#e55;font-size:12px;", "面板渲染失败：" + ((e && e.message) || e))); }
  }
  renderInto();
  if (panelId === "llm" && xbrModelLists === null) xbrLoadModelLists().then(() => ctx.rerender());
}

/* ── 按钮区 / 提示词框标题行 / 参数设定显示 / 锁定 ─────────── */
function xbrBuildButtonRow(node) {
  const grid = el("div", "display:grid;grid-template-columns:repeat(3,1fr);grid-auto-rows:30px;gap:6px;flex:0 0 auto;");
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

/** 参数设定显示（只读摘要 7 行；按用户要求：不显示括号与注释） */
function xbrInfoLines(node, promptText) {
  const llm = xbrParseLlm(xbrCurJson(node).llm);
  const useLlm = !!xbrWidgetVal(node, "use_llm");
  const backend = String(xbrWidgetVal(node, "backend") ?? "");
  const pMode = String(xbrWidgetVal(node, "preset_mode") ?? "");
  const pDef = defaultPresetOf(pMode, String(xbrWidgetVal(node, "output_lang") ?? "")) || "";
  const pCur = String(xbrWidgetVal(node, "three_view_text") ?? "");
  const line1 = `🖼️ 空latent：${xbrClean(xbrWidgetVal(node, "latent_kind"))} ｜ ${xbrWidgetVal(node, "width")}x${xbrWidgetVal(node, "height")} ｜ 数量 ${xbrWidgetVal(node, "batch_size")}`;
  const line2 = `🎨 预设模式：${xbrClean(pMode)}`
    + (pDef ? ` ｜ 设定词：${(pCur.trim() && pCur !== pDef) ? "✏️ 自定义" : "默认"}` : " ｜ 设定词：无");
  const line3 = `🌐 输出语言：${xbrClean(xbrWidgetVal(node, "output_lang"))}`;
  const line4 = useLlm
    ? (backend === "在线 API"
      ? `🤖 LLM 反推：已启用 ｜ 在线API ｜ ${xbrClean((node.__xbrProApiInfo?.model) || XBR_API_DEFAULTS.model)}`
      : `🤖 LLM 反推：已启用 ｜ 本地模型 ｜ ${xbrClean(llm.model.model) || "未选择模型"}`)
    : "🤖 LLM 反推：未启用";
  const line5 = `✨ 增强预设：${xbrClean(xbrWidgetVal(node, "preset")) || "-"} ｜ 🎯 反推预设：${xbrClean(xbrWidgetVal(node, "task_preset")) || "-"}`;
  const line6 = `⚙️ 温度 ${llm.params.temperature} · top_k ${llm.params.top_k} · top_p ${llm.params.top_p} · max_tokens ${llm.params.max_tokens} ｜ ${xbrClean(llm.run.inference_mode)} ｜ 种子 ${llm.run.seed}`;
  const line7 = `📝 提示词：${(promptText || "").length} 字`;
  return [line1, line2, line3, line4, line5, line6, line7].join("\n");
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
  node.__xbrProRefreshInfo = refresh;
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

  // 生成后控制：后端算好的「下一次种子」回写进 manager_settings.llm.run.seed
  const prevExecuted = node.onExecuted;
  node.onExecuted = function (msg) {
    const r = prevExecuted?.apply(this, arguments);
    try {
      const ns = msg?.seed?.[0];
      if (ns !== undefined && ns !== null && ns !== "") {
        const cur = xbrCurJson(node);
        const llm = xbrParseLlm(cur.llm);
        if (Number(ns) !== Number(llm.run.seed)) {
          llm.run.seed = Math.max(0, Math.round(Number(ns)) || 0);
          xbrSaveJson(node, { llm });
        }
      }
      refresh();
    } catch (_) {}
    return r;
  };

  // 表面参数变化 → 摘要刷新（只 setDirtyCanvas，不动用 setSize）
  for (const nm of ["latent_kind", "output_lang", "preset_mode", "use_llm", "backend", "preset", "task_preset", "width", "height", "batch_size", "aspect_ratio"]) {
    const w = xbrWidget(node, nm);
    if (!w || w.__xbrProHooked) continue;
    w.__xbrProHooked = true;
    const orig = w.callback;
    w.callback = function (...a) {
      const r = orig?.apply(this, a);
      setTimeout(refresh, 0);
      return r;
    };
  }
  promptBox.addEventListener("input", () => { setTimeout(refresh, 0); });

  xbrApiGet().then((r) => { node.__xbrProApiInfo = xbrNormApi(r.settings); refresh(); }).catch(() => { refresh(); });
  setTimeout(refresh, 0);
  return [head, infoBox];
}
