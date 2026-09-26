/**
 * XB-llama - ✨ 提示词增强反推 — 前端
 * ============================================================
 * 节点表面（零选项参数，交互对齐「短剧导演台」）：
 *   ① 按钮区（grid：跟随节点宽度等分拉伸，导演台同款蓝框按钮）
 *        🤖 大语言模型配置 ｜ ✨ 提示词增强预设 ｜ 📖 使用说明
 *   ② 手写提示词编辑框（右上角「📋 复制」按钮；「📝 提示词」端口接线后自动锁定）
 *   ③ 参数设定显示（只读摘要 4 行：LLM后端/语言/模型 ｜ 增强预设 ｜ 反推预设 ｜ 温度等采样参数）
 *
 * 弹窗（导演台同款）：居中 overlay + `#1c1c1e` 面板 + header（标题/副标题）+ 内容 + 底部「取消 / 💾 保存」
 *   · 🤖 大语言模型配置 = 复刻导演台「大语言模型配置」面板（去掉「开关」「故事扩写设置」两组）
 *   · ✨ 提示词增强预设 = 增强预设 / 反推预设 / 追加设定
 *   · 📖 使用说明
 *   弹窗内改动 800ms 防抖自动保存（可关），「💾 保存」立即提交（写 manager_settings + 表面 widget）；
 *   弹窗底部左侧：自动保存开关 + 界面缩放（−/＋，Ctrl/⌘+滚轮），对齐导演台
 *
 * 尺寸铁律（照抄导演台）：容器 100% + overflow:hidden；提示词框 flex:1 吃剩余高；
 *   refreshSize 只在初始化/加载工作流跑几次（computeSize 下限保护，只增不减）；
 *   打字 / 保存 / onResize 一律不 setSize、不重排。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { installNodes2BoxResize } from "./xb_compat.js";

const NODE_TYPE = "XB_llamaPromptReverse";
const API_ENDPOINT = "/xb_toolbox/llm_api_settings";

const MIN_W = 460;
const MIN_PROMPT_H = 170;   // 提示词编辑框最小高度
const MIN_INFO_H = 98;      // 参数设定显示固定高度（4 行含换行）
const BTN_H = 30;           // 导演台按钮高度
const DOM_FIXED_H = 30 + 6 + 17 + 6 + MIN_INFO_H + 18;   // 按钮 + 标题行 + 间距 + 信息区 + 内边距

const PANELS = [
  { id: "llm", label: "🤖 大语言模型配置", title: "🤖 大语言模型配置" },
  { id: "preset", label: "✨ 提示词增强预设", title: "✨ 提示词增强预设" },
  { id: "help", label: "📖 使用说明", title: "📖 使用说明" },
];
const PANEL_SUBTITLE = {
  llm: "大模型后端与推理配置；保存后重新执行节点生效。",
  preset: "增强预设（= 提示词设定）与反推预设；手写提示词请在节点上的编辑框里填写。",
  help: "端口与交互说明。",
};
const READONLY = new Set(["help"]);

const BACKENDS = [
  { value: "本地模型", label: "本地模型 [local]" },
  { value: "在线 API", label: "在线API [api]" },
];
const INFERENCE_MODES = ["one by one", "images", "video"];
const OUTPUT_LANGS = ["中文 [ZH]", "英文 [EN]"];
// 生成后控制（导演台同款）：随机 / 固定 / 增加 / 减少
const SEED_MODES = ["randomize", "fixed", "increment", "decrement"];
const SEED_LABEL = { randomize: "随机", fixed: "固定", increment: "增加", decrement: "减少" };

/* ============================================================
 *  无状态 UI 助手
 * ============================================================ */

function el(tag, css, text) {
  const e = document.createElement(tag);
  if (css) e.style.cssText = css;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function notify(msg, type = "success") {
  try {
    if (app?.ui?.toast) { app.ui.toast.add({ text: msg, type }); return; }
  } catch (_) {}
  console.log(`[XB-提示词增强反推] ${msg}`);
}
function findWidget(node, name) { return (node?.widgets || []).find((w) => w?.name === name); }
function readWidgetValue(w) { return w ? (w._state?.value ?? w.value) : undefined; }
function setWidgetValue(w, val) {
  if (!w) return;
  try { w.value = val; } catch (_) {}
  try { if (w._state) w._state.value = val; } catch (_) {}
  try { w._node?.setDirtyCanvas?.(true, true); } catch (_) {}
}
function refreshNodes2View(node) {
  try { if (node && Array.isArray(node.widgets)) node.widgets = node.widgets.slice(); } catch (_) {}
  try { node?.graph?.trigger?.("node:slot-label:changed", { nodeId: node.id, slotType: 2 }); } catch (_) {}
  try { node?.setDirtyCanvas?.(true, true); } catch (_) {}
}

function ensureStyle() {
  if (document.getElementById("xbr-style")) return;
  const st = el("style", "");
  st.id = "xbr-style";
  st.textContent = [
    ".xbr-input{box-sizing:border-box;background:var(--comfy-input-bg,#2a2a2a);color:var(--fg-color,#ddd);" +
      "border:1px solid var(--border-color,#444);border-radius:4px;padding:6px 10px;font-size:13px;outline:none;font-family:inherit;}",
    ".xbr-input:hover{background:var(--comfy-input-bg-hover,#3a3a3a);}",
    ".xbr-input:focus{border-color:#5b9bd5;}",
    ".xbr-input option{background:var(--comfy-menu-bg,#2a2a2a);}",
    ".xbr-modal input[type='checkbox']{width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;}",
    ".xbr-modal textarea{line-height:1.5;}",
  ].join("\n");
  document.head.append(st);
}

/* ============================================================
 *  控件工厂
 * ============================================================ */

function sectionTitle(text) {
  return el("div", "font-size:12px;font-weight:600;color:var(--descrip-text,#999);margin:14px 0 8px;letter-spacing:.4px;", text);
}
function hint(text) {
  return el("div", "font-size:11px;color:#888;line-height:1.6;margin:2px 0 8px;", text);
}
function field(labelText, control, labelW = 160) {
  const g = el("div", "display:flex;align-items:center;gap:12px;margin-bottom:10px;");
  g.append(el("label", `flex:0 0 ${labelW}px;font-size:13px;color:var(--descrip-text,#999);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;`, labelText));
  control.style.flex = "1 1 0";
  control.style.minWidth = "0";
  if (["INPUT", "SELECT", "TEXTAREA"].includes(control.tagName)) control.classList.add("xbr-input");
  g.append(control);
  return g;
}
function selectControl(options, value, onChange) {
  const s = el("select", "flex:1 1 0;min-width:0;");
  s.className = "xbr-input";
  for (const o of options) {
    const v = (typeof o === "object" && o !== null && o.value !== undefined) ? String(o.value) : String(o);
    const t = (typeof o === "object" && o !== null && o.label) ? String(o.label) : String(o);
    const op = el("option", "", t);
    op.value = v;
    if (v === String(value)) op.selected = true;
    s.append(op);
  }
  s.addEventListener("change", () => onChange(s.value));
  return s;
}
function textControl(value, placeholder, onChange) {
  const i = el("input", "flex:1 1 0;min-width:0;");
  i.className = "xbr-input";
  i.type = "text";
  i.value = value ?? "";
  if (placeholder) i.placeholder = placeholder;
  i.spellcheck = false;
  i.addEventListener("change", () => onChange(i.value.trim()));
  return i;
}
function passwordControl(value, placeholder, onChange) {
  const i = el("input", "flex:1 1 0;min-width:0;");
  i.className = "xbr-input";
  i.type = "password";
  i.value = value ?? "";
  if (placeholder) i.placeholder = placeholder;
  i.autocomplete = "new-password";
  i.addEventListener("change", () => onChange(i.value.trim()));
  return i;
}
function numberControl(value, opts, onChange) {
  const i = el("input", "flex:1 1 0;min-width:0;");
  i.className = "xbr-input";
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
function checkboxControl(value, labelText, onChange) {
  const w = el("label", "display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px;color:var(--fg-color,#ddd);margin-bottom:8px;");
  const c = el("input", "width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;");
  c.type = "checkbox";
  c.checked = !!value;
  c.addEventListener("change", () => onChange(c.checked));
  w.append(c, el("span", "", labelText));
  return w;
}
/** 导演台同款「方形勾选单选」：一组 checkbox 互斥，至少保留一个选中 */
function squareRadio(options, value, onChange) {
  const row = el("div", "display:flex;align-items:center;gap:16px;min-width:0;flex:1;flex-wrap:wrap;");
  const boxes = [];
  for (const o of options) {
    const lab = el("label", "display:flex;align-items:center;gap:6px;font-size:13px;color:var(--descrip-text,#999);cursor:pointer;");
    const c = el("input", "width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;");
    c.type = "checkbox";
    c.checked = String(o.value) === String(value);
    c.addEventListener("change", () => {
      if (c.checked) {
        boxes.forEach((x) => { if (x !== c) x.checked = false; });
        onChange(o.value);
      } else if (boxes.every((x) => !x.checked)) {
        c.checked = true;   // 至少一个
      }
    });
    lab.append(c, el("span", "", o.label));
    row.append(lab);
    boxes.push(c);
  }
  return row;
}
function textareaControl(value, placeholder, rows, onChange) {
  const t = el("textarea", "width:100%;resize:vertical;");
  t.className = "xbr-input";
  t.value = value ?? "";
  t.rows = rows || 4;
  if (placeholder) t.placeholder = placeholder;
  t.spellcheck = false;
  t.addEventListener("change", () => onChange(t.value));
  return t;
}
function smallBtn(text, css, title) {
  const b = el("button", "border:1px solid var(--border-color,#555);background:var(--comfy-button-bg,#333);" +
    "color:var(--fg-color,#eee);border-radius:4px;padding:5px 12px;font-size:12px;cursor:pointer;white-space:nowrap;" + (css || ""), text);
  b.type = "button";
  if (title) b.title = title;
  return b;
}

/**
 * 导演台同款「种子 + 生成后控制」一行：
 *   种子 [数字框] [🔁 随机]（点击在 随机/固定/增加/减少 间循环；后端按该模式算下一次种子并回写）
 */
function seedControlRow(run, onChange) {
  const g = el("div", "display:flex;align-items:center;gap:10px;margin-bottom:10px;");
  g.append(el("label", "flex:0 0 160px;font-size:13px;color:var(--descrip-text,#999);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;", "种子"));
  const i = el("input", "flex:1 1 0;min-width:0;");
  i.className = "xbr-input";
  i.type = "number";
  i.value = run.seed ?? 0;
  i.min = 0; i.max = Number.MAX_SAFE_INTEGER; i.step = 1;
  i.addEventListener("change", () => {
    let v = Math.round(parseFloat(i.value));
    if (!Number.isFinite(v) || v < 0) v = 0;
    i.value = v;
    run.seed = v;
    onChange?.();
  });
  const ctrl = smallBtn("", "flex:1 1 0;min-width:0;background:#b45309;border:1px solid #d97706;color:#fff;text-align:center;");
  const cur = () => (SEED_LABEL[run.seed_control] ? run.seed_control : "randomize");
  const render = () => {
    ctrl.textContent = "🔁 " + SEED_LABEL[cur()];
    ctrl.title = "生成后控制（control_after_generate）：随机 = 每次运行后自动换新种子；固定 = 锁定当前值；增加/减少 = 每次运行后 +1/−1。点击切换";
  };
  ctrl.addEventListener("mousedown", (e) => e.stopPropagation());
  ctrl.addEventListener("click", (e) => {
    e.stopPropagation();
    run.seed_control = SEED_MODES[(SEED_MODES.indexOf(cur()) + 1) % SEED_MODES.length];
    render();
    onChange?.();
  });
  render();
  g.append(i, ctrl);
  return g;
}

/* ── 界面缩放（导演台同款：整个弹窗按比例缩放，独立于网页/画布；Ctrl/⌘+滚轮）── */
const UI_ZOOM_MIN = 0.5, UI_ZOOM_MAX = 3.0, UI_ZOOM_STEP = 0.05;
let _uiZoom = null;
function uiZoomGet() {
  if (_uiZoom == null) {
    try { const v = parseFloat(localStorage.getItem("xbr_ui_zoom") || ""); if (Number.isFinite(v) && v > 0) _uiZoom = v; } catch (_) {}
  }
  return _uiZoom == null ? 1 : _uiZoom;
}
function uiZoomSet(v) {
  const snapped = Math.round(Math.max(UI_ZOOM_MIN, Math.min(UI_ZOOM_MAX, v)) / UI_ZOOM_STEP) * UI_ZOOM_STEP;
  _uiZoom = Math.round(snapped * 100) / 100;
  try { localStorage.setItem("xbr_ui_zoom", String(_uiZoom)); } catch (_) {}
}
function uiZoomStep(dir) { uiZoomSet(uiZoomGet() + dir * UI_ZOOM_STEP); return uiZoomGet(); }
function uiZoomApply(elem) {
  if (!elem) return;
  const z = uiZoomGet();
  elem.dataset.xbrUiTarget = "1";
  if (elem.dataset.xbrUiMaxH == null) {
    const cs = parseFloat(getComputedStyle(elem).maxHeight);
    elem.dataset.xbrUiMaxH = Number.isFinite(cs) ? String(cs) : "none";
  }
  elem.style.zoom = String(z);
  // zoom 会把 max-height 一并放大 → 用 min(原上限, 视口高×0.92/zoom) 保证视觉高度恒定不溢出
  const orig = parseFloat(elem.dataset.xbrUiMaxH);
  const cap = Math.round((window.innerHeight * 0.92) / z);
  elem.style.maxHeight = (Number.isFinite(orig) ? Math.min(orig, cap) : cap) + "px";
}
window.addEventListener("resize", () => {
  document.querySelectorAll("[data-xbr-ui-target]").forEach((elem) => { try { uiZoomApply(elem); } catch (_) {} });
});
function uiZoomSyncLabels(target) {
  try {
    target.querySelectorAll?.(".xbr-ui-zoom-val").forEach((elem) => { elem.textContent = Math.round(uiZoomGet() * 100) + "%"; });
  } catch (_) {}
}
function buildUIRow(target) {
  const row = el("span", "display:inline-flex;align-items:center;gap:4px;user-select:none;");
  row.append(el("span", "font-size:11px;color:#888;white-space:nowrap;", "界面"));
  const mk = (t, d) => {
    const b = smallBtn(t, "width:22px;height:22px;padding:0;line-height:1;font-size:13px;border:1px solid #8a6d3b;background:#5a4a2a;color:#ffd98a;", d > 0 ? "放大整个界面（不缩放网页/画布）" : "缩小整个界面（不缩放网页/画布）");
    b.addEventListener("mousedown", (e) => e.stopPropagation());
    b.addEventListener("click", (e) => { e.stopPropagation(); uiZoomStep(d); uiZoomApply(target); uiZoomSyncLabels(target); });
    return b;
  };
  const val = el("span", "min-width:40px;text-align:center;font-size:12px;color:#ffd98a;font-variant-numeric:tabular-nums;", Math.round(uiZoomGet() * 100) + "%");
  val.classList.add("xbr-ui-zoom-val");
  row.append(mk("−", -1), val, mk("+", 1));
  return row;
}
function bindUIWheel(target) {
  if (!target) return;
  target.addEventListener("wheel", (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    e.stopPropagation();
    uiZoomStep(e.deltaY < 0 ? 1 : -1);
    uiZoomApply(target);
    uiZoomSyncLabels(target);
  }, { passive: false });
}

/* ============================================================
 *  配置读写（与后端 DEFAULT_SETTINGS 逐字段对齐）
 * ============================================================ */

function defaultSettings() {
  return {
    auto_save: true,
    model: { model: "", mmproj: "None", chat_handler: "None", n_ctx: 8192, vram_limit: -1, image_min_tokens: 0, image_max_tokens: 0 },
    run: { inference_mode: "one by one", max_frames: 24, max_size: 256, seed: 0, seed_control: "randomize", force_offload: false, save_states: false },
    params: {
      max_tokens: 6144, top_k: 40, top_p: 0.9, min_p: 0.05, typical_p: 1.0, temperature: 0.6,
      repeat_penalty: 1.12, frequency_penalty: 0.0, present_penalty: 0.0,
      mirostat_mode: 0, mirostat_eta: 0.1, mirostat_tau: 5.0, state_uid: -1,
    },
    extra_system: "",
    output_lang: OUTPUT_LANGS[0],
  };
}

const num = (v, d, lo, hi) => {
  let x = Number(v);
  if (!Number.isFinite(x)) x = d;
  if (lo !== undefined) x = Math.max(lo, x);
  if (hi !== undefined) x = Math.min(hi, x);
  return x;
};
const whole = (v, d, lo, hi) => Math.round(num(v, d, lo, hi));
const flag = (v, d) => (v === undefined || v === null || v === "" ? d
  : (typeof v === "string" ? ["1", "true", "yes", "on", "开启"].includes(v.trim().toLowerCase()) : !!v));
const pick = (v, allowed, d) => (allowed.includes(v) ? v : d);

function parseSettings(raw) {
  let data = {};
  if (raw && typeof raw === "object") data = raw;
  else if (typeof raw === "string" && raw.trim()) { try { data = JSON.parse(raw) || {}; } catch (_) { data = {}; } }

  const cfg = defaultSettings();
  const m = (data.model && typeof data.model === "object") ? data.model : {};
  cfg.model.model = String(m.model ?? "");
  cfg.model.mmproj = String(m.mmproj ?? "None");
  cfg.model.chat_handler = String(m.chat_handler ?? "None");
  cfg.model.n_ctx = whole(m.n_ctx, cfg.model.n_ctx, 1024, 327680);
  cfg.model.vram_limit = whole(m.vram_limit, cfg.model.vram_limit, -1, 1024);
  cfg.model.image_min_tokens = whole(m.image_min_tokens, 0, 0, 4096);
  cfg.model.image_max_tokens = whole(m.image_max_tokens, 0, 0, 4096);

  const r = (data.run && typeof data.run === "object") ? data.run : {};
  cfg.run.inference_mode = pick(r.inference_mode, INFERENCE_MODES, cfg.run.inference_mode);
  cfg.run.max_frames = whole(r.max_frames, cfg.run.max_frames, 2, 1024);
  cfg.run.max_size = whole(r.max_size, cfg.run.max_size, 128, 16384);
  cfg.run.seed = whole(r.seed, cfg.run.seed, 0, Number.MAX_SAFE_INTEGER);
  cfg.run.seed_control = pick(r.seed_control, SEED_MODES, cfg.run.seed_control);
  cfg.run.force_offload = flag(r.force_offload, cfg.run.force_offload);
  cfg.run.save_states = flag(r.save_states, cfg.run.save_states);
  cfg.auto_save = flag(data.auto_save, true);

  const p = (data.params && typeof data.params === "object") ? data.params : {};
  cfg.params.max_tokens = whole(p.max_tokens, cfg.params.max_tokens, 0, 262144);
  cfg.params.top_k = whole(p.top_k, cfg.params.top_k, 0, 1000);
  cfg.params.top_p = num(p.top_p, cfg.params.top_p, 0, 1);
  cfg.params.min_p = num(p.min_p, cfg.params.min_p, 0, 1);
  cfg.params.typical_p = num(p.typical_p, cfg.params.typical_p, 0, 1);
  cfg.params.temperature = num(p.temperature, cfg.params.temperature, 0, 2);
  cfg.params.repeat_penalty = num(p.repeat_penalty, cfg.params.repeat_penalty, 0, 10);
  cfg.params.frequency_penalty = num(p.frequency_penalty, cfg.params.frequency_penalty, 0, 1);
  cfg.params.present_penalty = num(p.present_penalty, cfg.params.present_penalty, 0, 2);
  cfg.params.mirostat_mode = whole(p.mirostat_mode, cfg.params.mirostat_mode, 0, 2);
  cfg.params.mirostat_eta = num(p.mirostat_eta, cfg.params.mirostat_eta, 0, 1);
  cfg.params.mirostat_tau = num(p.mirostat_tau, cfg.params.mirostat_tau, 0, 10);
  cfg.params.state_uid = whole(p.state_uid, cfg.params.state_uid, -1, 999999);

  cfg.extra_system = String(data.extra_system ?? "");
  cfg.output_lang = pick(String(data.output_lang ?? ""), OUTPUT_LANGS, cfg.output_lang);
  return cfg;
}

function loadDraft(node) {
  const cfg = parseSettings(readWidgetValue(findWidget(node, "manager_settings")));
  return {
    settings: cfg,
    backend: pick(String(readWidgetValue(findWidget(node, "backend")) ?? ""), BACKENDS.map((b) => b.value), BACKENDS[0].value),
    preset: String(readWidgetValue(findWidget(node, "preset")) ?? ""),
    task_preset: String(readWidgetValue(findWidget(node, "task_preset")) ?? ""),
  };
}

function commitDraft(node, draft) {
  const s = draft.settings;
  setWidgetValue(findWidget(node, "manager_settings"), JSON.stringify({
    auto_save: s.auto_save !== false,
    model: s.model, run: s.run, params: s.params,
    extra_system: s.extra_system, output_lang: s.output_lang,
  }));
  setWidgetValue(findWidget(node, "backend"), draft.backend);
  setWidgetValue(findWidget(node, "preset"), draft.preset);
  setWidgetValue(findWidget(node, "task_preset"), draft.task_preset);
  node.setDirtyCanvas?.(true, true);
}

/* ============================================================
 *  外部数据：模型候选表 / API 设置
 * ============================================================ */

let MODEL_LISTS = null;

async function loadModelLists(force) {
  if (MODEL_LISTS && !force) return MODEL_LISTS;
  try {
    const resp = await api.fetchApi("/object_info/XB_llamaModelLoader");
    const data = await resp.json();
    const req = data?.XB_llamaModelLoader?.input?.required || {};
    MODEL_LISTS = {
      model: Array.isArray(req.model?.[0]) ? req.model[0] : [],
      mmproj: Array.isArray(req.mmproj?.[0]) ? req.mmproj[0] : ["None"],
      chat_handler: Array.isArray(req.chat_handler?.[0]) ? req.chat_handler[0] : ["None"],
    };
  } catch (_) {
    MODEL_LISTS = { model: [], mmproj: ["None"], chat_handler: ["None"] };
  }
  return MODEL_LISTS;
}

function widgetOptions(node, name) {
  const w = findWidget(node, name);
  const o = w?.options?.values ?? w?.options;
  return Array.isArray(o) ? o.slice() : [];
}

async function fetchApiSettings() {
  const resp = await api.fetchApi(API_ENDPOINT);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
  return { settings: data.settings || {}, providers: data.providers || [] };
}

async function putApiSettings(payload) {
  const resp = await api.fetchApi(API_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || !data?.ok) throw new Error(data?.error || `HTTP ${resp.status}`);
  return data.settings || payload;
}

/* ============================================================
 *  弹窗外壳（导演台同款）
 * ============================================================ */

let openShell = null;

function buildDialog({ label, title, subtitle, width = 820, footerExtraFactory = null, onSave = null, saveLabel = "💾 保存", onClose = null }) {
  ensureStyle();
  const overlay = el("div", "position:fixed;inset:0;background:rgba(0,0,0,0.78);z-index:9999;display:flex;" +
    "align-items:center;justify-content:center;overflow:auto;");
  const dialog = el("section", `background:#1c1c1e;border:1px solid #333;border-radius:8px;width:${width}px;max-width:94vw;` +
    "max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 40px rgba(0,0,0,0.6);flex:0 0 auto;");
  dialog.className = "xbr-modal";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-label", label);

  const header = el("div", "padding:18px 20px;border-bottom:1px solid var(--border-color,#444);");
  header.append(el("div", "font-size:17px;font-weight:700;color:var(--fg-color,#eee);", title));
  if (subtitle) header.append(el("div", "font-size:12px;color:var(--descrip-text,#999);margin-top:5px;line-height:1.6;", subtitle));
  dialog.append(header);

  const body = el("div", "padding:16px 20px;overflow-y:auto;flex:1;min-height:200px;");
  dialog.append(body);

  const error = el("div", "color:#e55;font-size:12px;margin:0 20px;min-height:14px;");
  const footer = el("div", "padding:14px 20px;border-top:1px solid var(--border-color,#444);display:flex;" +
    "justify-content:flex-end;gap:10px;align-items:center;background:#18181a;border-bottom-left-radius:8px;border-bottom-right-radius:8px;");
  if (footerExtraFactory) {
    // 导演台同款：底部左侧放「自动保存 + 界面缩放」，与右侧「取消/保存」同行
    const left = el("div", "display:flex;align-items:center;gap:16px;margin-right:auto;flex-wrap:wrap;");
    for (const item of (footerExtraFactory(dialog) || [])) if (item) left.append(item);
    footer.append(left);
  }
  const cancelBtn = smallBtn("取消", "padding:8px 20px;font-size:14px;background:transparent;");
  footer.append(cancelBtn);
  let saveBtn = null;
  if (onSave) {
    saveBtn = smallBtn(saveLabel, "padding:8px 20px;font-size:14px;font-weight:600;background:#2d5a88;border:none;color:#fff;");
    footer.append(saveBtn);
  }
  dialog.append(error, footer);
  overlay.append(dialog);
  document.body.append(overlay);
  // 应用已记忆的界面缩放（未设置过 = 100%）+ Ctrl/⌘+滚轮缩放
  uiZoomApply(dialog);
  bindUIWheel(dialog);

  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    if (openShell && openShell.overlay === overlay) openShell = null;
    try { onClose?.(); } catch (_) {}
  };
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
  document.addEventListener("keydown", onKey, true);
  cancelBtn.addEventListener("click", close);
  overlay.addEventListener("pointerdown", (e) => { if (e.target === overlay) close(); });

  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      if (saveBtn.disabled) return;
      saveBtn.disabled = true;
      saveBtn.textContent = "保存中…";
      error.textContent = "";
      try {
        await onSave();
        close();
      } catch (e) {
        error.textContent = String(e?.message || e);
        saveBtn.disabled = false;
        saveBtn.textContent = saveLabel;
      }
    });
  }
  return { overlay, dialog, body, error, close, saveBtn };
}

/* ============================================================
 *  在线 API 默认配置
 *  （复刻导演台：字段直接内嵌在「大语言模型配置」二级弹窗里，没有三级菜单；
 *    配置仍存 ComfyUI user 目录，API Key 不写入工作流）
 * ============================================================ */

const DEFAULT_PROVIDER = "OpenAI 兼容 (OpenAI/DeepSeek/Qwen/GLM/Kimi/Ollama/vLLM/LM Studio)";
const API_DEFAULTS = {
  provider: DEFAULT_PROVIDER,
  model: "deepseek-v4-flash-vision-exp",
  api_key: "",
  base_url: "https://api.deepseek.com/v1",
  temperature: 0.6,
  max_tokens: 8192,
  thinking: "disabled",
};

function normApiInfo(raw) {
  const x = { ...API_DEFAULTS, ...(raw && typeof raw === "object" ? raw : {}) };
  x.provider = String(x.provider || "").trim() || DEFAULT_PROVIDER;
  x.model = String(x.model ?? "").trim() || API_DEFAULTS.model;
  x.base_url = String(x.base_url ?? "").trim() || API_DEFAULTS.base_url;
  x.api_key = String(x.api_key ?? "");
  x.temperature = num(x.temperature, API_DEFAULTS.temperature, 0, 2);
  x.max_tokens = whole(x.max_tokens, API_DEFAULTS.max_tokens, 1, 262144);
  x.thinking = (x.thinking === "enabled") ? "enabled" : "disabled";
  return x;
}

/* ============================================================
 *  弹窗内容：🤖 大语言模型配置（复刻导演台，去掉「开关」「故事扩写设置」）
 * ============================================================ */

function renderLlmPanel(body, node, draft, ctx) {
  const s = draft.settings;

  // ── 输出语言 ──
  body.append(sectionTitle("输出语言"));
  body.append(field("输出语言", selectControl(OUTPUT_LANGS, s.output_lang, (v) => { s.output_lang = v; })));

  // ── LLM 后端（方形勾选单选，导演台同款）──
  body.append(sectionTitle("LLM 后端"));
  body.append(field("LLM 后端", squareRadio(BACKENDS, draft.backend, (v) => { draft.backend = v; ctx.rerender(); })));

  // ── 本地 LLM 模型 ──
  const localBox = el("div", "");
  if (draft.backend !== "在线 API") {
    localBox.append(sectionTitle("本地 LLM 模型"));
    const lists = MODEL_LISTS || { model: [], mmproj: ["None"], chat_handler: ["None"] };
    const llm = s.model;
    const llmModels = lists.model.length ? lists.model : (llm.model ? [llm.model] : []);
    if (!llm.model && llmModels.length) llm.model = llmModels[0];   // 所见即所得：显示什么就存什么
    localBox.append(field("强制卸载", checkboxControl(s.run.force_offload, "LLM 用完即卸载（释放显存）", (v) => { s.run.force_offload = v; })));
    if (llmModels.length) localBox.append(field("模型", selectControl(llmModels, llm.model, (v) => { llm.model = v; })));
    else localBox.append(field("模型", textControl(llm.model, "未找到本地 LLM 模型（.gguf 放到 models/LLM）", (v) => { llm.model = v; })));
    localBox.append(field("视觉模块 mmproj", selectControl(lists.mmproj.length ? lists.mmproj : ["None"], llm.mmproj, (v) => { llm.mmproj = v; })));
    localBox.append(field("Chat Handler", selectControl(lists.chat_handler.length ? lists.chat_handler : ["None"], llm.chat_handler, (v) => { llm.chat_handler = v; })));
    localBox.append(field("上下文长度 n_ctx", numberControl(llm.n_ctx, { min: 1024, max: 327680, step: 128 }, (v) => { llm.n_ctx = Math.round(v); })));
    localBox.append(field("显存上限 vram_limit (GB)", numberControl(llm.vram_limit, { min: -1, max: 1024, step: 1 }, (v) => { llm.vram_limit = Math.round(v); })));
    localBox.append(field("图像最小 tokens", numberControl(llm.image_min_tokens, { min: 0, max: 4096, step: 32 }, (v) => { llm.image_min_tokens = Math.round(v); })));
    localBox.append(field("图像最大 tokens", numberControl(llm.image_max_tokens, { min: 0, max: 4096, step: 32 }, (v) => { llm.image_max_tokens = Math.round(v); })));

    const p = s.params;
    localBox.append(field("max_tokens", numberControl(p.max_tokens, { min: 0, max: 262144, step: 1 }, (v) => { p.max_tokens = Math.round(v); })));
    localBox.append(field("top_k", numberControl(p.top_k, { min: 0, max: 1000, step: 1 }, (v) => { p.top_k = Math.round(v); })));
    localBox.append(field("top_p", numberControl(p.top_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.top_p = v; })));
    localBox.append(field("min_p", numberControl(p.min_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.min_p = v; })));
    localBox.append(field("typical_p", numberControl(p.typical_p, { min: 0, max: 1, step: 0.01 }, (v) => { p.typical_p = v; })));
    localBox.append(field("temperature", numberControl(p.temperature, { min: 0, max: 2, step: 0.01 }, (v) => { p.temperature = v; })));
    localBox.append(field("repeat_penalty", numberControl(p.repeat_penalty, { min: 0, max: 10, step: 0.01 }, (v) => { p.repeat_penalty = v; })));
    localBox.append(field("frequency_penalty", numberControl(p.frequency_penalty, { min: 0, max: 1, step: 0.01 }, (v) => { p.frequency_penalty = v; })));
    localBox.append(field("present_penalty", numberControl(p.present_penalty, { min: 0, max: 2, step: 0.01 }, (v) => { p.present_penalty = v; })));
    localBox.append(field("mirostat_mode", numberControl(p.mirostat_mode, { min: 0, max: 2, step: 1 }, (v) => { p.mirostat_mode = Math.round(v); })));
    localBox.append(field("mirostat_eta", numberControl(p.mirostat_eta, { min: 0, max: 1, step: 0.01 }, (v) => { p.mirostat_eta = v; })));
    localBox.append(field("mirostat_tau", numberControl(p.mirostat_tau, { min: 0, max: 10, step: 0.01 }, (v) => { p.mirostat_tau = v; })));
    localBox.append(hint("本地模型参数（显存上限 -1 = 不限制，按显存感知层数计算的参考值）。"));
    body.append(localBox);
  }

  // ── 在线 API（复刻导演台：字段直接内嵌，无三级弹窗）──
  if (draft.backend === "在线 API") {
    const apiBox = el("div", "");
    apiBox.append(sectionTitle("在线 API"));
    const a = draft.api || (draft.api = { ...API_DEFAULTS });
    apiBox.append(field("服务商", selectControl(ctx.providers, a.provider, (v) => { a.provider = v; })));
    apiBox.append(field("模型", textControl(a.model, API_DEFAULTS.model, (v) => { a.model = v; })));
    apiBox.append(field("API Key", passwordControl(a.api_key, "sk-…（保存在本地，不写入工作流）", (v) => { a.api_key = v; })));
    apiBox.append(field("Base URL", textControl(a.base_url, API_DEFAULTS.base_url, (v) => { a.base_url = v; })));
    apiBox.append(field("temperature", numberControl(a.temperature, { min: 0, max: 2, step: 0.01 }, (v) => { a.temperature = v; })));
    apiBox.append(field("max_tokens", numberControl(a.max_tokens, { min: 1, max: 262144, step: 1 }, (v) => { a.max_tokens = Math.round(v); })));
    apiBox.append(field("thinking", selectControl(["disabled", "enabled"], a.thinking, (v) => { a.thinking = v; })));
    apiBox.append(hint("默认：deepseek-v4-flash-vision-exp ｜ https://api.deepseek.com/v1（可改）。配置保存在本地 ComfyUI user 目录，不会写入工作流。"));
    body.append(apiBox);
  }

  // ── 随机种子（含生成后控制：随机/固定/增加/减少，导演台同款）──
  body.append(sectionTitle("随机种子"));
  body.append(seedControlRow(s.run, () => ctx.touch?.()));
  body.append(hint("点击「🔁」切换生成后控制：随机 = 运行后自动换新种子；固定 = 锁定；增加/减少 = 运行后 ±1（后端算完会回写到这里）。"));

  // ── 指令推理 ──
  body.append(sectionTitle("指令推理"));
  const r = s.run;
  body.append(field("推理模式", selectControl(INFERENCE_MODES, r.inference_mode, (v) => { r.inference_mode = v; })));
  body.append(field("最大帧数", numberControl(r.max_frames, { min: 2, max: 1024, step: 1 }, (v) => { r.max_frames = Math.round(v); })));
  body.append(field("最大尺寸", numberControl(r.max_size, { min: 128, max: 16384, step: 64 }, (v) => { r.max_size = Math.round(v); })));
  body.append(field("保存对话状态", checkboxControl(r.save_states, "在内存中保留本次对话上下文（多轮连续反推）", (v) => { r.save_states = v; })));
  body.append(field("状态 UID", numberControl(s.params.state_uid, { min: -1, max: 999999, step: 1 }, (v) => { s.params.state_uid = Math.round(v); })));
  body.append(hint("手写提示词在节点上的编辑框里填写；「📝 提示词」端口接线后编辑框会锁定。"));
}

/* ── ✨ 提示词增强预设 ── */
function renderPresetPanel(body, node, draft, ctx) {
  const s = draft.settings;
  body.append(sectionTitle("增强预设（= 提示词设定 / system prompt）"));
  const presetOpts = widgetOptions(node, "preset");
  if (presetOpts.length) body.append(field("增强预设", selectControl(presetOpts, draft.preset, (v) => { draft.preset = v; })));
  body.append(hint("该预设内容即「🧩 提示词设定」输出的正文，同时作为本次推理的系统提示词。"));

  body.append(sectionTitle("反推预设"));
  const taskOpts = widgetOptions(node, "task_preset");
  if (taskOpts.length) {
    body.append(field("反推预设", selectControl(taskOpts, draft.task_preset, (v) => { draft.task_preset = v; })));
    const cur = String(draft.task_preset || "");
    if (cur.includes("BBox") || cur.startsWith("Vision -")) {
      body.append(hint("该预设为框选/检测类：预设里的 * 是必填占位符，由节点上的手写提示词或外接「📝 提示词」填入。"));
    }
  }

  body.append(sectionTitle("追加设定（可留空）"));
  const taExtra = textareaControl(s.extra_system, "追加在增强预设之后的额外要求（例：只输出一行、不要解释过程…）", 8, (v) => { s.extra_system = v; });
  taExtra.style.width = "100%";
  taExtra.style.boxSizing = "border-box";
  taExtra.style.minHeight = "200px";
  body.append(taExtra);
}

/* ── 📖 使用说明 ── */
function renderHelpPanel(body) {
  const lines = [
    "【输入端口（只保留两个）】",
    "  · 📝 提示词：外接文本提示词。**接上线后，节点上的手写提示词编辑框会锁定不可编辑**（二选一）",
    "  · 🖼️ 图像：外接图像 / 视频帧（VLM 反推：图 → 提示词）",
    "",
    "【输出端口】",
    "  · 📝 提示词全量：合并后的完整提示词文本",
    "  · 📋 提示词列表：按行拆分的列表",
    "  · 🧩 提示词设定：本次使用的提示词设定（增强预设 + 输出语言 + 追加设定）",
    "",
    "【按钮 / 弹窗（二级，无三级菜单）】",
    "  · 🤖 大语言模型配置：输出语言 / LLM 后端（本地模型 · 在线API）/ 本地模型与采样参数 / 随机种子 / 指令推理",
    "      —— 选「在线API」时下方直接展开服务商 / 模型 / API Key / Base URL / temperature / max_tokens / thinking",
    "      —— 默认：deepseek-v4-flash-vision-exp ｜ https://api.deepseek.com/v1",
    "      —— 「随机种子」行带生成后控制：点「🔁」在 随机 / 固定 / 增加 / 减少 间切换（运行后自动算下一次种子）",
    "  · ✨ 提示词增强预设：增强预设 + 反推预设 + 追加设定",
    "  · 📖 使用说明：本页",
    "",
    "【节点表面】",
    "  · 手写提示词编辑框右上角有「📋 复制」按钮，一键复制当前文本",
    "  · 下方「参数设定显示」实时显示当前 LLM 后端 / 语言 / 模型 / 增强预设 / 反推预设 / 采样参数",
    "",
    "【保存 / 界面】",
    "  · 弹窗底部左侧：「自动保存」勾选框（默认开；关闭后需手动点「💾 保存」）+「界面 − 100% +」缩放",
    "  · 界面缩放作用于整个弹窗（不缩放网页/画布），Ctrl/⌘ + 滚轮 也可调，记忆在浏览器本地",
    "  · 「取消」丢弃未保存改动；配置随工作流保存；在线 API 的 Key 存在 ComfyUI user 目录，不进工作流",
  ];
  body.append(el("div", "font-size:12px;color:#bbb;line-height:1.9;white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;", lines.join("\n")));
}

const PANEL_RENDER = { llm: renderLlmPanel, preset: renderPresetPanel, help: renderHelpPanel };

async function openPanelModal(node, panelId) {
  if (openShell) { try { openShell.close(); } catch (_) {} }
  const meta = PANELS.find((p) => p.id === panelId) || PANELS[0];
  const draft = loadDraft(node);

  // 在线 API 配置（存本地 user 目录）——打开面板时就取回，字段直接内嵌
  let apiSaved = null;         // 打开时的基线（用于判断是否需要回写）
  let providers = [DEFAULT_PROVIDER];
  if (panelId === "llm") {
    try {
      const r = await fetchApiSettings();
      apiSaved = normApiInfo(r.settings);
      if (r.providers?.length) providers = r.providers;
    } catch (_) {
      apiSaved = normApiInfo(node.__xbrApiInfo);
    }
    node.__xbrApiInfo = apiSaved;
    draft.api = { ...apiSaved };
  }

  const ctx = {
    providers,
    rerender: () => { body.replaceChildren(); renderInto(); },
  };

  function renderInto() {
    try { PANEL_RENDER[panelId](body, node, draft, ctx); }
    catch (e) { body.append(el("div", "color:#e55;font-size:12px;", "面板渲染失败：" + ((e && e.message) || e))); }
  }

  // 提交：配置写回 widget；在线 API 字段有变动则回写本地配置文件
  const commit = async () => {
    if (panelId === "llm" && draft.api && apiSaved
      && JSON.stringify(normApiInfo(draft.api)) !== JSON.stringify(apiSaved)) {
      try {
        const saved = await putApiSettings(normApiInfo(draft.api));
        apiSaved = normApiInfo(saved);
        draft.api = { ...apiSaved };
        node.__xbrApiInfo = apiSaved;
      } catch (e) {
        notify("API 配置保存失败：" + (e?.message || e), "error");
      }
    }
    commitDraft(node, draft);
    node.__xbrUpdateInfo?.();
  };

  const shell = buildDialog({
    label: meta.title,
    title: meta.title,
    subtitle: PANEL_SUBTITLE[panelId],
    footerExtraFactory: READONLY.has(panelId) ? null : (dialog) => {
      const wrap = el("div", "display:flex;align-items:center;gap:16px;flex-wrap:wrap;");
      // 自动保存（随工作流保存；关闭后只能点「💾 保存」提交）
      const lab = el("label", "display:flex;align-items:center;gap:6px;font-size:13px;color:var(--descrip-text,#999);cursor:pointer;");
      const cb = el("input", "width:18px;height:18px;accent-color:#f59e0b;cursor:pointer;");
      cb.type = "checkbox";
      cb.checked = draft.settings.auto_save !== false;
      cb.title = "开启后：弹窗内改动会自动保存（防抖）；关闭后需手动点「💾 保存」";
      cb.addEventListener("change", () => {
        draft.settings.auto_save = cb.checked;
        commitDraft(node, draft);
        node.__xbrUpdateInfo?.();
        notify(cb.checked ? "已开启自动保存" : "已关闭自动保存（记得点「💾 保存」）");
      });
      lab.append(cb, el("span", "", "自动保存"));
      wrap.append(lab, buildUIRow(dialog));
      return [wrap];
    },
    onSave: READONLY.has(panelId) ? null : async () => { await commit(); notify("配置已保存，重新执行节点生效"); },
  });
  const body = shell.body;
  openShell = shell;

  renderInto();
  if (panelId === "llm" && MODEL_LISTS === null) loadModelLists().then(() => ctx.rerender());

  if (!READONLY.has(panelId)) {
    let timer = null;
    const schedule = () => {
      if (draft.settings.auto_save === false) return;   // 关了自动保存 → 只等「💾 保存」
      clearTimeout(timer);
      timer = setTimeout(() => { commit().catch(() => {}); }, 800);
    };
    ctx.touch = schedule;
    body.addEventListener("change", schedule);
  }
}

/* ============================================================
 *  节点挂载
 * ============================================================ */

function setupNode(node) {
  ensureStyle();
  const widgetState = new WeakMap();

  const hideWidget = (w) => {
    if (!w) return;
    try {
      if (!widgetState.has(w)) {
        widgetState.set(w, { type: w.type, computeSize: w.computeSize, hidden: w.hidden, optHidden: w.options ? w.options.hidden : undefined });
      }
      if (w.element) w.element.style.display = "none";
      if (w.inputEl) w.inputEl.style.display = "none";
      w.type = "hidden";
      w.hidden = true;
      if (w.options) w.options.hidden = true;
      w.computeSize = () => [0, -4];
    } catch (_) {}
  };

  // 需要内部留存、但不出现在节点表面的 widget
  const OPTION_WIDGETS = ["backend", "preset", "task_preset", "open_api_settings", "custom_prompt", "manager_settings"];

  // ① 隐藏全部选项 widget
  const hideAllOptions = () => {
    for (const nm of OPTION_WIDGETS) hideWidget(findWidget(node, nm));
    refreshNodes2View(node);
  };
  hideAllOptions();

  // ② 清掉这些 widget 的「接线按钮」（端口只留 📝 提示词 / 🖼️ 图像）
  const killGhost = (connectOn) => {
    try {
      for (const nm of OPTION_WIDGETS) {
        const idx = (node.inputs || []).findIndex((i) => i.name === nm);
        if (idx < 0) continue;
        const inp = node.inputs[idx];
        // 断掉残留连线（老工作流可能把它们接过线）
        if (inp.link != null) {
          const lid = inp.link;
          const g = node.graph;
          try {
            const link = g?.links?.[lid];
            if (link) {
              const origin = g.getNodeById(link.origin_id);
              const ol = origin?.outputs?.[link.origin_slot]?.links;
              const k = Array.isArray(ol) ? ol.indexOf(lid) : -1;
              if (k >= 0) ol.splice(k, 1);
              delete g.links[lid];
            }
          } catch (_) {}
          inp.link = null;
        }
        node.inputs.splice(idx, 1);
        (node.inputs || []).forEach((i, k2) => { i.slot = k2; });
      }
      node.setDirtyCanvas?.(true, true);
    } catch (_) {}
  };

  const wCustom = findWidget(node, "custom_prompt");

  // ③ 容器
  let nodeBg = "#353535";
  try { nodeBg = node.bgcolor || (window.LiteGraph && window.LiteGraph.NODE_DEFAULT_BGCOLOR) || nodeBg; } catch (_) {}
  const container = el("div", `width:100%;height:100%;display:flex;flex-direction:column;gap:6px;padding:8px;box-sizing:border-box;overflow:hidden;background:${nodeBg};border-bottom-left-radius:8px;border-bottom-right-radius:8px;`);
  container.dataset.xbrRoot = "1";

  // ④ 按钮区：grid 等分 → 跟随节点宽度
  const btnGrid = el("div", `display:grid;grid-template-columns:repeat(${PANELS.length},1fr);grid-auto-rows:${BTN_H}px;gap:6px;flex:0 0 auto;`);
  for (const p of PANELS) {
    const b = el("button", [
      "width:100%", `height:${BTN_H}px`, "box-sizing:border-box",
      "display:flex", "align-items:center", "justify-content:center",
      "border-radius:6px", "border:2px solid #5b9bd5", "background:#3a3a3a", "color:#eee",
      "font-size:14px", "cursor:pointer", "white-space:nowrap", "overflow:hidden", "text-overflow:ellipsis",
      "padding:0 6px", "font-family:inherit",
    ].join(";"));
    b.type = "button";
    b.textContent = p.label;
    b.title = `打开「${p.title}」弹窗`;
    b.dataset.xbrPanelBtn = p.id;
    b.addEventListener("mousedown", (e) => e.stopPropagation());
    b.addEventListener("mouseenter", () => { b.style.background = "#4a4a4a"; });
    b.addEventListener("mouseleave", () => { b.style.background = "#3a3a3a"; });
    b.addEventListener("click", () => openPanelModal(node, p.id));
    btnGrid.append(b);
  }
  container.append(btnGrid);

  // ⑤ 提示词编辑框（标题行右侧「📋 复制」按钮）
  const promptWrap = el("div", "flex:1 1 auto;min-height:0;display:flex;flex-direction:column;gap:4px;");
  promptWrap.dataset.captureWheel = "true";
  const promptHead = el("div", "display:flex;align-items:center;gap:8px;flex:0 0 auto;");
  const lockHint = el("div", "font-size:11px;color:var(--descrip-text,#999);", "✍️ 手写提示词");
  promptHead.append(lockHint);
  const copyBtn = smallBtn("📋 复制", "margin-left:auto;padding:2px 8px;font-size:11px;border-radius:4px;", "复制提示词编辑框里的内容");
  copyBtn.addEventListener("mousedown", (e) => e.stopPropagation());
  copyBtn.addEventListener("click", async () => {
    const txt = promptBox.value || "";
    try { await navigator.clipboard.writeText(txt); notify("已复制提示词"); }
    catch (_) {
      try { promptBox.select(); document.execCommand?.("copy"); notify("已复制提示词"); } catch (e) { notify("复制失败：" + e, "error"); }
    }
  });
  promptHead.append(copyBtn);
  promptWrap.append(promptHead);

  const promptBox = el("textarea", "flex:1 1 auto;min-height:60px;width:100%;box-sizing:border-box;resize:none;line-height:1.5;" +
    "font-family:inherit;background:#1c1c1e;color:var(--fg-color,#ddd);border:1px solid var(--border-color,#444);" +
    "border-radius:6px;padding:8px 10px;font-size:13px;outline:none;");
  promptBox.value = String(readWidgetValue(wCustom) ?? "");
  promptBox.placeholder = "在这里写提示词 / 或带 * 预设的占位符内容（如 BBox 检测的目标名称）";
  promptBox.spellcheck = false;
  let promptTimer = null;
  promptBox.addEventListener("input", () => {
    if (promptBox.readOnly) return;
    clearTimeout(promptTimer);
    promptTimer = setTimeout(() => { setWidgetValue(wCustom, promptBox.value); node.setDirtyCanvas?.(true, true); }, 250);
  });
  promptBox.addEventListener("focus", () => { if (!promptBox.readOnly) promptBox.style.borderColor = "#5b9bd5"; });
  promptBox.addEventListener("blur", () => { promptBox.style.borderColor = "var(--border-color,#444)"; });
  promptWrap.append(promptBox);
  container.append(promptWrap);

  // ⑥ 「📝 提示词」端口接线 → 锁定编辑框（二选一）
  const textInput = () => (node.inputs || []).find((i) => i.name === "text");
  const updateLock = () => {
    try {
      const linked = !!textInput() && textInput().link != null;
      promptBox.readOnly = linked;
      promptBox.style.background = linked ? "#141416" : "#1c1c1e";
      promptBox.style.color = linked ? "#8a8a8a" : "var(--fg-color,#ddd)";
      promptBox.style.borderColor = linked ? "#5a5a5a" : "var(--border-color,#444)";
      promptBox.title = linked ? "已由「📝 提示词」端口控制，断开连线后恢复编辑" : "";
      lockHint.textContent = linked
        ? "🔒 手写提示词已锁定（由「📝 提示词」端口控制）"
        : "✍️ 手写提示词";
      lockHint.style.color = linked ? "#d9a441" : "var(--descrip-text,#999)";
    } catch (_) {}
  };
  node.__xbrUpdateLock = updateLock;

  // ⑦ 参数设定显示（只读摘要）
  const infoBox = el("div", `flex:0 0 auto;height:${MIN_INFO_H}px;overflow:auto;background:#1c1c1e;border:1px solid #333;` +
    "border-radius:6px;padding:6px 9px;font-size:11px;line-height:1.65;color:#b9c6d2;white-space:pre-wrap;box-sizing:border-box;font-family:ui-monospace,Consolas,monospace;");
  infoBox.dataset.captureWheel = "true";
  container.append(infoBox);

  const updateInfo = () => {
    const d = loadDraft(node);
    const s = d.settings;
    const lang = String(s.output_lang || "").includes("EN") ? "英文[EN]" : "中文[ZH]";
    const apiModel = (node.__xbrApiInfo?.model) || API_DEFAULTS.model;
    const line1 = d.backend === "在线 API"
      ? `🧠 LLM后端：在线API ｜ 语言：${lang} ｜ ${apiModel}`
      : `🧠 LLM后端：本地 ｜ 语言：${lang} ｜ ${s.model.model || "未选择模型"}`;
    const line2 = `✨ 增强预设：${d.preset || "-"}`;
    const line3 = `🎯 反推预设：${d.task_preset || "-"}`;
    const line4 = `⚙️ 温度 ${s.params.temperature} · top_k ${s.params.top_k} · top_p ${s.params.top_p} · max_tokens ${s.params.max_tokens} ｜ ${s.run.inference_mode} ｜ 种子 ${s.run.seed}`;
    infoBox.textContent = [line1, line2, line3, line4].join("\n");
  };
  node.__xbrUpdateInfo = updateInfo;

  // ⑧ DOM widget 挂载
  let refreshSize = () => {};
  const widget = node.addDOMWidget?.("xb_reverse_panel", "XB_REVERSE_PANEL", container, { serialize: false, hideOnZoom: false });
  const syncDomWidth = () => {
    try {
      const fullW = Number.isFinite(node.size?.[0]) ? node.size[0] : 0;
      if (widget && fullW && widget.width !== fullW) widget.width = fullW;
    } catch (_) {}
  };
  const lockMinWidth = () => {
    try {
      const w = Number.isFinite(node.size?.[0]) ? node.size[0] : 0;
      if (w >= MIN_W) return;
      node.setSize?.([MIN_W, Math.max(node.size?.[1] || 320, 320)]);
    } catch (_) {}
  };
  const DOM_MIN_H = BTN_H + MIN_PROMPT_H + MIN_INFO_H + DOM_FIXED_H;
  if (widget) {
    try { delete widget.computeSize; } catch (_) { widget.computeSize = undefined; }
    widget.options = widget.options || {};
    widget.options.serialize = false;
    widget.options.getMinHeight = () => DOM_MIN_H;
    widget.options.getHeight = () => "100%";
    widget.computeLayoutSize = () => ({ minHeight: DOM_MIN_H, maxHeight: undefined, minWidth: MIN_W });
    widget.options.onDraw = () => syncDomWidth();
    widget.options.afterResize = () => syncDomWidth();
  }
  node.min_width = MIN_W;
  node.minWidth = MIN_W;
  node._xbDomWidget = widget;
  node._xbSyncWidth = syncDomWidth;

  const widgetRowH = (w) => {
    try {
      const s = w && w.computeSize ? w.computeSize(node.size?.[0] || MIN_W) : null;
      if (Array.isArray(s) && Number.isFinite(s[1]) && s[1] > 0) return s[1];
    } catch (_) {}
    return (w && (w.type === "hidden" || w.hidden)) ? 0 : 26;
  };
  const minNodeHeight = () => {
    let h = 30;
    for (const w of (node.widgets || [])) h += widgetRowH(w);
    return Math.max(360, Math.round(h + DOM_FIXED_H + MIN_PROMPT_H + MIN_INFO_H));
  };

  refreshSize = () => {
    try {
      lockMinWidth();
      syncDomWidth();
      const size = node.computeSize?.();
      const computed = (Array.isArray(size) && Number.isFinite(size[1])) ? size[1] : 0;
      const need = Math.max(computed, minNodeHeight());
      if (!node.size || !Number.isFinite(node.size[1]) || node.size[1] < need) {
        node.setSize?.([node.size?.[0] || MIN_W, need]);
      }
    } catch (_) {}
    node.setDirtyCanvas?.(true, true);
  };
  refreshSize();
  requestAnimationFrame(refreshSize);
  setTimeout(refreshSize, 60);
  setTimeout(refreshSize, 1200);
  node._xbRefreshSize = refreshSize;
  node._xbEl = container;

  // Nodes 2.0：拖节点尺寸手柄时提示词框按指针位移实时跟随
  try {
    node._xbUninstallBoxResize = installNodes2BoxResize(node, promptBox, { min: MIN_PROMPT_H, max: 4000, deflt: MIN_PROMPT_H });
  } catch (e) { console.warn("[XB-提示词增强反推] 2.0 高度跟随安装失败", e); }

  // 节点 resize：同步宽度 + 防抖校正最小宽高
  let resizeTimer = null;
  let clamping = false;
  const prevOnResize = node.onResize;
  node.onResize = function (...args) {
    const rr = prevOnResize?.apply(this, args);
    try {
      syncDomWidth();
      if (!clamping) {
        const need = minNodeHeight();
        const cur = Number.isFinite(node.size?.[1]) ? node.size[1] : 0;
        if (cur < need) {
          clamping = true;
          try { node.setSize?.([node.size?.[0] || MIN_W, need]); } finally { clamping = false; }
        }
      }
      node.setDirtyCanvas?.(true, true);
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { lockMinWidth(); syncDomWidth(); node.setDirtyCanvas?.(true, true); }, 200);
    } catch (_) {}
    return rr;
  };

  // 连线状态变化 → 刷新锁定
  const prevOnConn = node.onConnectionsChange;
  node.onConnectionsChange = function (...args) {
    const r = prevOnConn?.apply(this, args);
    try { setTimeout(updateLock, 0); } catch (_) {}
    return r;
  };

  // 每帧同步 overlay 宽度
  try {
    const cv = node.graph?.canvas ?? window.app?.canvas;
    if (cv && !cv.__xbDomWidthPatch) {
      cv.__xbDomWidthPatch = true;
      const prevDraw = cv.onDrawForeground;
      cv.onDrawForeground = function () {
        const r = prevDraw?.apply(this, arguments);
        try {
          const g = window.app?.graph;
          const ns = g ? (g._nodes || g.nodes || []) : [];
          for (const n of ns) if (n && n._xbDomWidget && n._xbSyncWidth) n._xbSyncWidth();
        } catch (_) {}
        return r;
      };
    }
  } catch (_) {}

  // 执行结果 → 上次输出 + 摘要刷新
  const prevExecuted = node.onExecuted;
  node.onExecuted = function (msg) {
    const r = prevExecuted?.apply(this, arguments);
    try {
      const t = msg?.text?.[0];
      if (typeof t === "string" && t.length) node.__xbrLastOutput = t;
      // 生成后控制：后端算好的「下一次种子」回写到 manager_settings（随机/增加/减少）
      const ns = msg?.seed?.[0];
      if (ns !== undefined && ns !== null && ns !== "") {
        const cfg = parseSettings(readWidgetValue(findWidget(node, "manager_settings")));
        if (Number(ns) !== Number(cfg.run.seed)) {
          cfg.run.seed = Math.max(0, Math.round(Number(ns)) || 0);
          setWidgetValue(findWidget(node, "manager_settings"), JSON.stringify({
            auto_save: cfg.auto_save !== false,
            model: cfg.model, run: cfg.run, params: cfg.params,
            extra_system: cfg.extra_system, output_lang: cfg.output_lang,
          }));
        }
      }
      updateInfo();
    } catch (_) {}
    return r;
  };

  const syncFromWidgets = () => {
    const v = String(readWidgetValue(wCustom) ?? "");
    if (document.activeElement !== promptBox && promptBox.value !== v) promptBox.value = v;
    updateInfo();
    updateLock();
  };

  const boot = () => {
    hideAllOptions();
    killGhost();
    syncFromWidgets();
    refreshSize();
  };
  node.__xbrBoot = boot;
  setTimeout(boot, 0);
  setTimeout(boot, 200);
  [0, 150, 500, 1200].forEach((d) => setTimeout(killGhost, d));

  const prevConfigure = node.onConfigure;
  node.onConfigure = function (...args) {
    const r = prevConfigure?.apply(this, args);
    setTimeout(boot, 60);
    setTimeout(killGhost, 220);
    return r;
  };

  const prevRemoved = node.onRemoved;
  node.onRemoved = function (...args) {
    try { node._xbUninstallBoxResize?.(); } catch (_) {}
    try { openShell?.close?.(); } catch (_) {}
    return prevRemoved?.apply(this, args);
  };

  fetchApiSettings().then((r) => { node.__xbrApiInfo = normApiInfo(r.settings); updateInfo(); }).catch(() => { node.__xbrApiInfo = normApiInfo(null); updateInfo(); });
}

app.registerExtension({
  name: "XB.llamaPromptReverse",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_TYPE) return;
    const orig = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = orig?.apply(this, arguments);
      try { setupNode(this); } catch (e) { console.error("[XB-提示词增强反推]", e); }
      return r;
    };
  },
});
