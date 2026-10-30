/**
 * XB-BOX 参考图库选择器（姿态 / 穿搭）
 * ============================================================
 * 由「XB-BOX - 🖼️ 生图预设」的「🎬 姿态参考图选择 / 👚 穿搭参考图选择」两个按钮打开。
 *
 * · 首次打开必须先**手动绑定**目录（使用确认 + 绝对路径），绑定信息只存本机
 *   <user_dir>/xb_toolbox/gallery.json，工作流里只存库内相对路径；
 * · 带素材清单的图库（目录下有 data/*.json）：体系 / 分类 / 视角 / 标签筛选 +
 *   按姿势编号分组 + 视角条 + 收藏 / 最近使用 + 加载更多；
 * · 普通图片文件夹（无清单）：按文件名多宫格 + 搜索 + 排序 + 加载更多；
 * · 单选（一个端口一张图）→ 回填节点内部字段 pose_ref / outfit_ref。
 *
 * 视觉沿用本包弹窗风格（#1c1c1e / 880px / 圆角 8px）。
 */

import { api } from "../../scripts/api.js";

const KIND_LABEL = { pose: "🎬 姿态参考图", costume: "👚 穿搭参考图" };
const ANGLE_ORDER = ["正面", "斜侧", "侧面", "俯视", "仰视"];
const PAGE = 48;
const LS = "xb_ref_gallery.v1.";

// ── 请求 / 图片地址 ──────────────────────────────────────────────
async function req(path, options = {}) {
  const init = { ...options };
  if (options.body) {
    init.body = JSON.stringify(options.body);
    init.headers = { ...(options.headers || {}), "Content-Type": "application/json" };
  }
  const resp = await api.fetchApi("/xb_toolbox/gallery" + path, init);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || "图库请求失败，请检查 ComfyUI 的运行状态。");
  return data;
}

function imageUrl(kind, item, thumb) {
  const query = new URLSearchParams({ kind, path: item.path, thumb: thumb ? "1" : "0" });
  if (thumb && item.thumb) query.set("thumb_path", item.thumb);
  return api.apiURL("/xb_toolbox/gallery/image?" + query.toString());
}

// ── 小工具 ──────────────────────────────────────────────────────
function el(tag, css = "", text = "") {
  const node = document.createElement(tag);
  if (css) node.style.cssText = css;
  if (text) node.textContent = text;
  return node;
}

function mkBtn(label, css, onClick) {
  const btn = el("button", "font-family:inherit;cursor:pointer;border-radius:5px;" + css, label);
  btn.type = "button";
  btn.addEventListener("pointerdown", (e) => e.stopPropagation());
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    onClick?.(e);
  });
  return btn;
}

function readLocal(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(LS + key));
    return Array.isArray(fallback) ? (Array.isArray(value) ? value : fallback) : (value ?? fallback);
  } catch (_) {
    return fallback;
  }
}

function writeLocal(key, value) {
  try { localStorage.setItem(LS + key, JSON.stringify(value)); } catch (_) { /* 隐私模式下忽略 */ }
}

const groupKey = (item) => JSON.stringify([item.system, item.group]);
const angleRank = (item) => {
  const index = ANGLE_ORDER.indexOf(item.angle);
  return index < 0 ? ANGLE_ORDER.length : index;
};

/** 筛选：空格分词 AND + 各维度精确匹配（收藏 / 最近 为集合过滤） */
function filterItems(items, state, favorites, recent) {
  const words = String(state.query || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  const favSet = new Set(favorites);
  const recSet = new Set(recent);
  const result = items.filter((item) =>
    (!state.system || item.system === state.system) &&
    (!state.category || item.category === state.category) &&
    (!state.angle || item.angle === state.angle) &&
    (!state.tag || (item.tags || []).includes(state.tag)) &&
    (state.collection !== "favorites" || favSet.has(item.id)) &&
    (state.collection !== "recent" || recSet.has(item.id)) &&
    words.every((word) => String(item.search || "").includes(word)));
  if (state.collection === "recent") {
    const rank = new Map(recent.map((id, index) => [id, index]));
    result.sort((a, b) => (rank.get(a.id) ?? 1e9) - (rank.get(b.id) ?? 1e9));
  }
  return result;
}

function buildGroups(items) {
  const groups = new Map();
  for (const item of items) {
    const key = groupKey(item);
    if (!groups.has(key)) groups.set(key, { key, items: [] });
    groups.get(key).items.push(item);
  }
  for (const group of groups.values()) group.items.sort((a, b) => angleRank(a) - angleRank(b));
  return groups;
}

// ── 弹窗外壳（本包统一风格：宽弹窗 + 字号 / 界面缩放，与本包其它 mod 面板同一套记忆） ──
// 字号 = 弹窗整体 font-size（px）；界面 = 整体 zoom（%）。两项都存在 localStorage，
// 与「添加预设 / 编辑预设」等弹窗共用同一组键 → 在一个弹窗里调好，其它弹窗一致。
const MODAL_FONT_KEY = "xb_ipp_modal_font";
const MODAL_ZOOM_KEY = "xb_ipp_modal_zoom";
const FONT_MIN = 10, FONT_MAX = 30, FONT_DEF = 15;
const ZOOM_MIN = 0.6, ZOOM_MAX = 2.0, ZOOM_STEP = 0.05;
const DIALOG_WIDTH = 1280;

function fontGet() {
  try {
    const value = parseInt(localStorage.getItem(MODAL_FONT_KEY) || "", 10);
    if (Number.isFinite(value)) return Math.max(FONT_MIN, Math.min(FONT_MAX, value));
  } catch (_) {}
  return FONT_DEF;
}
function fontSet(value) {
  const next = Math.max(FONT_MIN, Math.min(FONT_MAX, Math.round(value)));
  try { localStorage.setItem(MODAL_FONT_KEY, String(next)); } catch (_) {}
  return next;
}
function zoomGet() {
  try {
    const value = parseFloat(localStorage.getItem(MODAL_ZOOM_KEY) || "");
    if (Number.isFinite(value) && value > 0) return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, value));
  } catch (_) {}
  return 1;
}
function zoomSet(value) {
  const stepped = Math.round(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, value)) / ZOOM_STEP) * ZOOM_STEP;
  const next = Math.round(stepped * 100) / 100;
  try { localStorage.setItem(MODAL_ZOOM_KEY, String(next)); } catch (_) {}
  return next;
}

/** 把字号 / 界面缩放套到弹窗上
 *  ⚠️ zoom 会等比放大整个盒子：宽度 / 高度上限必须先按 zoom 折回布局像素，
 *     否则「界面 >100%」时卡片会顶出屏幕、出现横向挤压与字叠字。 */
function applyScale(card) {
  if (!card) return;
  const font = fontGet();
  const zoom = zoomGet();
  card.style.fontSize = font + "px";
  card.style.zoom = String(zoom);
  card.style.width = `min(${DIALOG_WIDTH}px, calc(96vw / ${zoom}))`;
  card.style.maxHeight = `calc(90vh / ${zoom})`;
  card.querySelectorAll("textarea, input[type=search], input[type=text]").forEach((node) => {
    node.style.fontSize = "1em";
  });
}

function shell(title) {
  const mask = el("div", "position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.78);"
    + "display:flex;overflow:auto;box-sizing:border-box;");
  const card = el("div", "margin:auto;flex:0 0 auto;display:flex;flex-direction:column;"
    + "background:#1c1c1e;border:1px solid #333;border-radius:8px;color:#ddd;"
    + "font-family:system-ui,sans-serif;line-height:1.65;box-shadow:0 20px 40px rgba(0,0,0,.6);overflow:hidden;");
  const head = el("div", "padding:14px 18px 12px;background:#232326;border-bottom:1px solid #3a3a3a;"
    + "display:flex;align-items:center;gap:12px;flex-wrap:wrap;");
  head.append(el("span", "flex:1 1 320px;min-width:200px;font-size:1.2em;font-weight:700;color:#eee;", title));

  // 顶部常驻条（放「禁用」勾选框等，切换视图时不会被清空）
  const top = el("div", "padding:8px 18px;background:#202024;border-bottom:1px solid #333;"
    + "display:flex;align-items:center;gap:12px;flex-wrap:wrap;");
  top.hidden = true;

  const body = el("div", "padding:14px 18px 16px;display:flex;flex-direction:column;gap:10px;overflow:auto;min-height:0;");
  const foot = el("div", "padding:10px 18px;border-top:1px solid #3a3a3a;background:#18181a;"
    + "display:flex;align-items:center;gap:10px;flex-wrap:wrap;");

  // 顶部工具条：字号 A−/A+ ｜ 界面 −/%/+ ｜ ✕
  const tools = el("span", "display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-weight:normal;");
  const fontVal = el("span", "min-width:26px;text-align:center;color:#e8a87c;font-variant-numeric:tabular-nums;", String(fontGet()));
  const zoomVal = el("span", "min-width:46px;text-align:center;color:#ffd98a;font-variant-numeric:tabular-nums;",
    Math.round(zoomGet() * 100) + "%");
  const refreshVals = () => {
    fontVal.textContent = String(fontGet());
    zoomVal.textContent = Math.round(zoomGet() * 100) + "%";
  };
  // 缩放变更后通知内容（如大图预览需要按新缩放重算可用高度）
  const scaleNow = () => {
    applyScale(card);
    try { card.dispatchEvent(new Event("xb-scale")); } catch (_) {}
  };
  const fontMinus = mkBtn("A−", "border:1px solid #5b9bd5;background:#2a4a6a;color:#cfe3f7;height:1.9em;padding:0 .55em;", () => {
    fontSet(fontGet() - 1);
    scaleNow();
    refreshVals();
  });
  const fontPlus = mkBtn("A+", "border:1px solid #5b9bd5;background:#2a4a6a;color:#cfe3f7;height:1.9em;padding:0 .55em;", () => {
    fontSet(fontGet() + 1);
    scaleNow();
    refreshVals();
  });
  const zoomMinus = mkBtn("−", "border:1px solid #8a6d3b;background:#5a4a2a;color:#ffd98a;height:1.9em;padding:0 .6em;", () => {
    zoomSet(zoomGet() - ZOOM_STEP);
    scaleNow();
    refreshVals();
  });
  const zoomPlus = mkBtn("+", "border:1px solid #8a6d3b;background:#5a4a2a;color:#ffd98a;height:1.9em;padding:0 .6em;", () => {
    zoomSet(zoomGet() + ZOOM_STEP);
    scaleNow();
    refreshVals();
  });
  tools.append(
    el("span", "color:#8a8a8a;font-size:.9em;", "字号"), fontMinus, fontVal, fontPlus,
    el("span", "color:#5a5a5a;", "|"),
    el("span", "color:#8a8a8a;font-size:.9em;", "界面"), zoomMinus, zoomVal, zoomPlus,
  );
  head.append(tools);

  const close = () => {
    try { mask.remove(); } catch (_) {}
    document.removeEventListener("keydown", onKey);
    mask.removeEventListener("wheel", onWheel);
    window.app?.canvas?.setDirty?.(true, true);
  };
  const onKey = (event) => { if (event.key === "Escape") close(); };
  // Ctrl/⌘ + 滚轮 = 调界面缩放（与本包元素面板一致）
  const onWheel = (event) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    zoomSet(zoomGet() + (event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP));
    scaleNow();
    refreshVals();
  };
  tools.append(mkBtn("✕", "border:1px solid #555;background:#2b2b2b;color:#ddd;height:1.9em;padding:0 .7em;", close));

  card.append(head, top, body, foot);
  mask.append(card);
  mask.addEventListener("pointerdown", (e) => { if (e.target === mask) close(); });
  mask.addEventListener("wheel", onWheel, { passive: false });
  document.addEventListener("keydown", onKey);
  document.body.append(mask);
  scaleNow();
  return { mask, card, top, body, foot, head, close, applyScale: scaleNow };
}

/**
 * 打开参考图选择器。
 * @param {{kind:"pose"|"costume", current?:string, onPick?:(sel:{path:string,name:string,id:string})=>void}} options
 */
export async function openRefPicker({ kind, current = "", onPick } = {}) {
  const label = KIND_LABEL[kind] || "参考图";
  const ui = shell(label + " · 选择参考图");
  const kindName = kind === "pose" ? "姿态" : "穿搭";

  // ── 当前值（JSON：{path, name, disabled}） ─────────────────────
  const parseCurrent = () => {
    const text = String(current || "").trim();
    if (!text) return { path: "", name: "", disabled: false };
    if (text.startsWith("{")) {
      try {
        const data = JSON.parse(text) || {};
        return { path: String(data.path || ""), name: String(data.name || ""), disabled: !!data.disabled };
      } catch (_) {
        return { path: "", name: "", disabled: false };
      }
    }
    return { path: text, name: text.split("/").pop(), disabled: false };
  };
  const initial = parseCurrent();
  let disabled = initial.disabled;
  let currentPick = initial.path ? { path: initial.path, name: initial.name, id: "" } : null;

  /** 写回节点：禁用状态与所选素材一起写；close=false 时只更新不关窗 */
  const emit = (item, closeAfter) => {
    const picked = item || currentPick || { path: "", name: "", id: "" };
    try {
      onPick?.({ path: picked.path || "", name: picked.name || "", id: picked.id || "", disabled });
    } catch (err) {
      console.error("[XB-参考图库]", err);
    }
    if (closeAfter) ui.close();
  };

  // ── 顶部「禁用」勾选框（姿态/穿搭各自独立，随工作流保存） ───────
  const disableBox = el("input", "width:18px;height:18px;accent-color:#e07070;cursor:pointer;flex:0 0 auto;margin:0;");
  disableBox.type = "checkbox";
  disableBox.checked = disabled;
  disableBox.id = `xb-ref-disable-${kind}`;
  const disableText = el("span", "color:#ddd;cursor:pointer;user-select:none;", `🚫 禁用此参考图（不做任何输出）`);
  const disableWrap = el("label", "display:flex;align-items:center;gap:8px;cursor:pointer;padding:2px 0;");
  disableWrap.append(disableBox, disableText);
  const HINT_OFF = "勾选后本参考图不做任何输出（等同 mute）：接在它下游的节点会被直接跳过，不执行也不报错。";
  const HINT_ON = `已禁用：${kindName}图不做任何输出，下游节点会被跳过。取消勾选即恢复。`;
  const disableHint = el("span", "color:#8a8a8a;font-size:.88em;", HINT_OFF);
  ui.top.append(disableWrap, disableHint);
  ui.top.hidden = false;
  disableBox.addEventListener("change", () => {
    disabled = disableBox.checked;
    disableText.style.color = disabled ? "#ffb74d" : "#ddd";
    disableHint.style.color = disabled ? "#d9a441" : "#8a8a8a";
    disableHint.textContent = disabled ? HINT_ON : HINT_OFF;
    emit(null, false);   // 立即写回节点（不关窗，方便接着选图）
  });
  disableHint.textContent = disabled ? HINT_ON : HINT_OFF;
  disableText.style.color = disabled ? "#ffb74d" : "#ddd";

  // ── ① 绑定界面（未绑定 / 未确认时强制先绑定） ──────────────────
  async function showBinding(settings, message = "") {
    ui.body.replaceChildren();
    ui.foot.replaceChildren();
    const cfg = (settings && settings[kind]) || {};

    ui.body.append(el("div", "color:#ffb74d;line-height:1.75;white-space:pre-wrap;",
      `⚠️ 首次使用需手动绑定${kind === "pose" ? "姿态" : "穿搭"}参考图库目录。\n`
      + "· 整套图库：选择包含 data / img / thumbs 的目录"
      + "（目录里有 data/*.json 素材清单即可自动识别）\n"
      + "· 普通文件夹：任意装图片的目录即可（按文件名多宫格显示）\n"
      + "· 本节点不内置、不分发任何图库素材；请自行确认素材的合法来源与使用授权。"));

    const pathInput = el("input", "flex:1 1 320px;min-width:220px;height:2em;background:#1e1e1e;color:#ddd;"
      + "border:1px solid #444;border-radius:4px;padding:0 8px;font-size:1em;box-sizing:border-box;");
    pathInput.type = "text";
    pathInput.value = cfg.directory || "";
    pathInput.placeholder = "填写 ComfyUI 所在电脑上的绝对路径";

    const status = el("div", "color:#e07070;min-height:1.4em;white-space:pre-wrap;", message);

    const browse = mkBtn("📂 浏览本机目录", "border:1px solid #555;background:#2b2b2b;color:#ddd;height:2.2em;padding:0 12px;", async () => {
      try {
        const resp = await api.fetchApi("/xb_toolbox/choose_folder", { method: "POST" });
        const data = await resp.json();
        if (data.path) {
          pathInput.value = data.path;
          status.style.color = "#bbb";
          status.textContent = "已选择目录，勾选下方使用确认后点「检查并绑定」。";
        } else if (data.error) {
          status.style.color = "#e07070";
          status.textContent = data.error;
        }
      } catch (err) {
        status.style.color = "#e07070";
        status.textContent = "调用系统目录选择框失败：" + (err?.message || err);
      }
    });

    const row = el("div", "display:flex;gap:8px;align-items:center;flex-wrap:wrap;");
    row.append(pathInput, browse);

    const agreeRow = el("label", "display:flex;gap:8px;align-items:flex-start;cursor:pointer;color:#cfcfcf;line-height:1.6;");
    const agree = el("input", "width:18px;height:18px;accent-color:#f59e0b;margin-top:3px;flex:0 0 auto;");
    agree.type = "checkbox";
    agree.checked = !!(cfg.accepted && cfg.directory);
    agreeRow.append(agree, el("span", "",
      "我已确认合法获得该图库的使用权，并自行承担素材使用与合规责任（本插件只读取本机文件，不上传、不分发）。"));

    const save = mkBtn("✅ 检查并绑定", "background:#2d5a88;color:#fff;border:none;height:2.2em;padding:0 18px;font-weight:600;", async () => {
      save.disabled = true;
      status.style.color = "#bbb";
      status.textContent = "正在检查目录…";
      try {
        const data = await req("/settings", {
          method: "POST",
          body: { kind, directory: pathInput.value, accepted: agree.checked },
        });
        const cat = await req(`/catalogue?kind=${kind}`);
        status.style.color = "#7ed07e";
        status.textContent = cat.mode === "library"
          ? `已绑定：整套图库（${cat.count} 条 · 清单 ${cat.manifest}）`
          : `已绑定：普通文件夹（${cat.count} 张图片）`;
        await showGallery(data.settings);
      } catch (err) {
        status.style.color = "#e07070";
        status.textContent = err?.message || String(err);
      } finally {
        save.disabled = false;
      }
    });

    ui.body.append(row, agreeRow, status);
    ui.foot.append(el("span", "flex:1 1 auto;color:#8a8a8a;", "绑定信息只保存在本机 ComfyUI 用户目录，不写进工作流。"), save);
  }

  // ── ② 图库界面 ────────────────────────────────────────────────
  async function showGallery(settings, message = "") {
    ui.body.replaceChildren(el("div", "color:#bbb;", "正在读取图库…"));
    ui.foot.replaceChildren();

    let cat;
    try {
      cat = await req(`/catalogue?kind=${kind}&t=${Date.now()}`);
    } catch (err) {
      return showBinding(settings, err?.message || String(err));
    }

    const isLibrary = cat.mode === "library";
    // 只有素材带「姿势编号」时才能按姿势分组（穿搭库这类只有分类/标签的库 == 逐张浏览）
    const canGroup = isLibrary && cat.items.some((item) => item.group);
    const facets = cat.facets || {};
    const state = { query: "", system: "", category: "", angle: "", tag: "", collection: "all",
                    grouped: true, shown: PAGE, sort: "name" };
    let selected = null;

    // ── 筛选栏 ──
    const bar = el("div", "display:flex;gap:8px;align-items:center;flex-wrap:wrap;");
    const search = el("input", "flex:1 1 240px;min-width:160px;height:2em;background:#1e1e1e;color:#ddd;"
      + "border:1px solid #444;border-radius:4px;padding:0 8px;font-size:1em;box-sizing:border-box;");
    search.type = "search";
    search.placeholder = kind === "pose" ? "搜索姿势、编号、体系、分类、角度…" : "搜索款式、颜色、关键词、编号…";
    bar.append(search);

    const makeSelect = (caption, values, allLabel, onChange) => {
      const select = el("select", "height:2em;background:#1e1e1e;color:#ddd;border:1px solid #444;"
        + "border-radius:4px;padding:0 6px;font-size:1em;");
      select.add(new Option(allLabel, ""));
      for (const value of values) select.add(new Option(value, value));
      select.addEventListener("change", () => onChange(select.value));
      const wrap = el("label", "display:flex;gap:6px;align-items:center;color:#aaa;white-space:nowrap;");
      wrap.append(el("span", "", caption), select);
      return { wrap, select };
    };

    const categoriesFor = () => [...new Set(cat.items
      .filter((item) => !state.system || item.system === state.system)
      .map((item) => item.category)
      .filter(Boolean))];

    const sysSel = makeSelect("体系", facets.system || [], "全部体系", (value) => {
      state.system = value;
      state.category = "";
      refillCategories();
      render();
    });
    const catSel = makeSelect("分类", categoriesFor(), "全部分类", (value) => { state.category = value; render(); });
    const angSel = makeSelect("视角", facets.angle || [], "全部视角", (value) => { state.angle = value; render(); });
    const tagSel = makeSelect("标签", facets.tag || [], "全部标签", (value) => { state.tag = value; render(); });

    const refillCategories = () => {
      catSel.select.replaceChildren(new Option("全部分类", ""));
      for (const value of categoriesFor()) catSel.select.add(new Option(value, value));
      catSel.select.value = state.category;
    };

    if (isLibrary) {
      if ((facets.system || []).length) bar.append(sysSel.wrap);
      bar.append(catSel.wrap);
      if ((facets.angle || []).length) bar.append(angSel.wrap);
      if ((facets.tag || []).length) bar.append(tagSel.wrap);
    } else {
      bar.append(catSel.wrap);
      const sortSel = el("select", "height:2em;background:#1e1e1e;color:#ddd;border:1px solid #444;"
        + "border-radius:4px;padding:0 6px;font-size:1em;");
      sortSel.add(new Option("文件名 ↑", "name"));
      sortSel.add(new Option("文件名 ↓", "name-desc"));
      sortSel.addEventListener("change", () => { state.sort = sortSel.value; render(); });
      bar.append(sortSel);
    }

    bar.append(mkBtn("重置筛选", "border:1px solid #555;background:transparent;color:#ccc;height:2em;padding:0 10px;", () => {
      Object.assign(state, { query: "", system: "", category: "", angle: "", tag: "", collection: "all" });
      search.value = "";
      sysSel.select.value = "";
      angSel.select.value = "";
      tagSel.select.value = "";
      refillCategories();
      render();
    }));

    // ── 收藏 / 最近 ──
    const tabs = el("div", "display:flex;gap:6px;flex-wrap:wrap;");
    const tabButtons = [];
    if (isLibrary) {
      for (const [key, text] of [["all", "全部"], ["favorites", "♡ 收藏"], ["recent", "最近使用"]]) {
        const btn = mkBtn(text, "border:1px solid #555;background:#242424;color:#ccc;height:2em;padding:0 10px;", () => {
          state.collection = key;
          render();
        });
        btn.dataset.collection = key;
        tabButtons.push(btn);
        tabs.append(btn);
      }
      if (canGroup) {
        tabs.append(mkBtn("切换分组 / 逐张", "border:1px solid #555;background:transparent;color:#bbb;height:2em;padding:0 10px;", () => {
          state.grouped = !state.grouped;
          render();
        }));
      }
    }
    // 不能分组的库（没有姿势编号）不显示「切换分组」按钮，state.grouped 一并置 false
    if (!canGroup) state.grouped = false;

    const summary = el("div", "color:#9fc3e8;font-size:.95em;");
    const notice = el("div", "color:#e07070;min-height:1.2em;");
    notice.textContent = message || "";
    const grid = el("div", "display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;align-content:start;");
    const more = mkBtn("加载更多", "border:1px dashed #555;background:transparent;color:#bbb;height:2.2em;grid-column:1/-1;", () => {
      state.shown += PAGE;
      render(false);
    });

    if (isLibrary) ui.body.append(bar, tabs); else ui.body.append(bar);
    ui.body.append(summary, notice, grid, more);
    if (ui.body.firstElementChild && ui.body.firstElementChild.textContent === "正在读取图库…") {
      ui.body.firstElementChild.remove();
    }

    search.addEventListener("input", () => { state.query = search.value; render(); });

    const favorites = () => readLocal(`favorites.${kind}`, []);
    const recent = () => readLocal(`recent.${kind}`, []);

    // ── 卡片 ──
    function makeCard(item, groupItems) {
      const card = el("div", "position:relative;border:2px solid " + (selected?.id === item.id ? "#5b9bd5" : "#333")
        + ";border-radius:6px;overflow:hidden;background:#222;display:flex;flex-direction:column;");
      // 缩略图用 contain：姿势/服装都要看全，绝不裁切；背景压深色让留白不刺眼
      const img = el("img", "width:100%;height:9.6em;object-fit:contain;display:block;background:#101012;cursor:zoom-in;");
      img.loading = "lazy";
      img.decoding = "async";
      img.alt = item.name;
      img.src = imageUrl(kind, item, true);
      img.addEventListener("error", () => { img.style.opacity = "0.25"; img.title = "缩略图读取失败，请检查图库目录"; });
      img.addEventListener("click", () => preview(item, groupItems));

      // 编号角标（如 P001）：永远显示，不受下面文字省略号影响
      const badgeText = item.group || (kind === "pose" ? "" : item.id);
      if (badgeText) {
        const badge = el("div", "position:absolute;left:6px;top:6px;max-width:calc(100% - 12px);"
          + "background:rgba(0,0,0,.66);color:#9fd8ff;border:1px solid rgba(91,155,213,.55);border-radius:4px;"
          + "padding:0 6px;font-size:.76em;line-height:1.7;letter-spacing:.02em;"
          + "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none;", badgeText);
        badge.title = item.group ? `编号：${item.group}` : `ID：${item.id}`;
        card.append(badge);
      }

      const meta = el("div", "padding:6px 8px;font-size:.86em;line-height:1.5;overflow:hidden;");
      meta.append(el("div", "color:#8fd3ff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", item.name));
      const sub = [item.system, item.category, item.angle].filter(Boolean).join(" · ");
      if (sub) meta.append(el("div", "color:#8a8a8a;font-size:.92em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", sub));

      const actions = el("div", "display:flex;gap:5px;padding:0 8px 7px;");
      const pick = mkBtn(selected?.id === item.id ? "✓ 已选" : "选择",
        "flex:1 1 auto;min-width:0;border:1px solid #4a7a99;background:#24404f;color:#dff;height:1.9em;font-size:.8em;white-space:nowrap;overflow:hidden;", () => {
          selected = item;
          currentPick = item;
          render(false);
        });
      const fav = mkBtn(favorites().includes(item.id) ? "♥" : "♡",
        "flex:0 0 auto;border:1px solid #555;background:transparent;color:#e89;height:1.9em;font-size:.8em;padding:0 8px;", () => {
          const list = favorites();
          writeLocal(`favorites.${kind}`, list.includes(item.id)
            ? list.filter((id) => id !== item.id)
            : [...list, item.id]);
          render(false);
        });
      actions.append(pick, fav);
      card.append(img, meta, actions);

      if (isLibrary && state.grouped && Array.isArray(groupItems) && groupItems.length > 1) {
        const strip = el("div", "display:flex;gap:4px;padding:0 8px 8px;");
        for (const angle of ANGLE_ORDER) {
          const target = groupItems.find((value) => value.angle === angle);
          const isCurrent = !!(target && target.id === item.id);
          // 视角条只用单字（正/斜/侧/俯/仰）+ 悬停全名：卡片变窄或字号放大时也绝不换行挤压
          const angleBtn = mkBtn(angle.slice(0, 1), "flex:1 1 0;min-width:0;font-size:.78em;line-height:1.5;height:1.9em;padding:0;"
            + "white-space:nowrap;overflow:hidden;"
            + "border:1px solid " + (isCurrent ? "#5b9bd5" : "#444") + ";"
            + "background:" + (target ? (isCurrent ? "#2d5a88" : "#2a2a2a") : "transparent") + ";"
            + "color:" + (target ? "#ddd" : "#555") + ";", () => {
            if (target) preview(target, groupItems);
          });
          angleBtn.title = target ? `${angle} · 点击打开大图` : `${angle} 暂无素材`;
          strip.append(angleBtn);
        }
        card.append(strip);
      }
      return card;
    }

    // ── 大图预览 ──
    function preview(item, groupItems) {
      const view = shell(`预览 · ${item.name}`);
      const stage = el("div", "display:flex;justify-content:center;align-items:center;background:#111;"
        + "border-radius:6px;overflow:hidden;padding:4px;box-sizing:border-box;");
      // ⚠️ 只给 max-width / max-height + object-fit:contain：浏览器会按原图比例缩放，
      //    永远显示完整画面、不会被拉伸变形；两处上限都用**布局像素**（视口高度 ÷ 界面缩放），
      //    所以界面放大到 200% 时也不会顶出屏幕或把图片压扁。
      const img = el("img", "display:block;width:auto;height:auto;object-fit:contain;");
      const fit = () => {
        const zoom = zoomGet();
        img.style.maxWidth = "100%";
        img.style.maxHeight = Math.max(140, Math.round((window.innerHeight * 0.64) / zoom)) + "px";
      };
      fit();
      img.addEventListener("load", fit);
      img.src = imageUrl(kind, item, false);
      img.alt = item.name;
      // 字号 / 界面变更 → 重新按新缩放算可用高度
      view.card.addEventListener("xb-scale", fit);
      const onResize = () => {
        if (!document.body.contains(img)) { window.removeEventListener("resize", onResize); return; }
        fit();
      };
      window.addEventListener("resize", onResize);
      stage.append(img);

      // 明细：名称 / 编号 / 体系·分类·视角 / 素材 ID（编号与 ID 单列一行，避免被截断）
      const previewLines = (value) => [
        value.name,
        value.group ? `编号：${value.group}` : "",
        [value.system, value.category, value.angle].filter(Boolean).join(" · "),
        `ID：${value.id}`,
      ].filter(Boolean).join("\n");
      const info = el("div", "color:#bbb;white-space:pre-wrap;font-size:.95em;line-height:1.6;");
      info.textContent = previewLines(item);

      let currentItem = item;
      const angles = el("div", "display:flex;gap:5px;flex-wrap:wrap;");
      const paintAngles = () => {
        angles.replaceChildren();
        if (!isLibrary || !Array.isArray(groupItems) || groupItems.length < 2) return;
        for (const angle of ANGLE_ORDER) {
          const target = groupItems.find((value) => value.angle === angle);
          const btn = mkBtn(angle, "border:1px solid " + (target && target.id === currentItem.id ? "#5b9bd5" : "#444")
            + ";background:" + (target ? "#2a2a2a" : "transparent") + ";color:" + (target ? "#ddd" : "#555")
            + ";height:1.9em;padding:0 10px;white-space:nowrap;", () => {
            if (!target) return;
            currentItem = target;
            img.src = imageUrl(kind, target, false);
            info.textContent = previewLines(target);
            paintAngles();
          });
          btn.disabled = !target;
          angles.append(btn);
        }
      };
      paintAngles();

      view.body.append(stage, info, angles);
      const use = mkBtn("使用此图", "background:#2d5a88;color:#fff;border:none;height:2.2em;padding:0 18px;font-weight:600;", () => {
        selected = currentItem;
        currentPick = currentItem;
        view.close();
        render(false);
      });
      view.foot.append(el("span", "flex:1 1 auto;color:#8a8a8a;", "Esc 关闭"), use);
    }

    // ── 渲染 ──
    function render(reset = true) {
      if (reset) state.shown = PAGE;
      let items = filterItems(cat.items, state, favorites(), recent());
      if (!isLibrary && state.sort === "name-desc") items = [...items].reverse();
      const groups = isLibrary ? buildGroups(items) : new Map();

      let entries;
      if (isLibrary && state.grouped) {
        const seen = new Set();
        entries = [];
        for (const item of items) {
          const key = groupKey(item);
          if (seen.has(key)) continue;
          seen.add(key);
          entries.push({ item, group: groups.get(key)?.items || [item] });
        }
      } else {
        entries = items.map((item) => ({ item, group: null }));
      }

      grid.replaceChildren();
      for (const entry of entries.slice(0, state.shown)) grid.append(makeCard(entry.item, entry.group));
      if (!entries.length) {
        grid.append(el("div", "grid-column:1/-1;color:#888;padding:18px;",
          state.collection === "favorites" ? "还没有匹配的收藏。" :
          state.collection === "recent" ? "最近使用的素材会显示在这里。" :
          "没有匹配的素材，试试减少筛选条件。"));
      }
      summary.textContent = isLibrary && state.grouped
        ? `${entries.length} 组 · ${items.length} 张 / 共 ${cat.count}`
        : `${items.length} 张 / 共 ${cat.count}`;
      more.hidden = entries.length <= state.shown;
      if (!more.hidden) more.textContent = `加载更多 · 还有 ${entries.length - state.shown} 组/张`;

      for (const btn of tabButtons) {
        const active = btn.dataset.collection === state.collection;
        btn.style.background = active ? "#2d5a88" : "#242424";
        btn.style.color = active ? "#fff" : "#ccc";
        btn.style.borderColor = active ? "#5b9bd5" : "#555";
      }
      paintFooter();
    }

    // ── 底栏（当前选择 + 使用） ──
    function paintFooter() {
      ui.foot.replaceChildren();
      if (selected) {
        const thumb = el("img", "width:46px;height:46px;object-fit:contain;border-radius:4px;border:1px solid #444;background:#101012;flex:0 0 auto;");
        thumb.src = imageUrl(kind, selected, true);
        const label = (selected.group ? `[${selected.group}] ` : "") + selected.name;
        const text = el("span", "flex:1 1 auto;color:#ddd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", label);
        text.title = label;
        ui.foot.append(thumb, text);
      } else {
        ui.foot.append(el("span", "flex:1 1 auto;color:#8a8a8a;", "点卡片上的「选择」或大图里的「使用此图」"));
      }
      const use = mkBtn(disabled ? "✅ 保存（当前已禁用）" : (selected ? "✅ 使用此图" : "请先选一张"),
        "background:#2d5a88;color:#fff;border:none;height:2.2em;padding:0 18px;font-weight:600;", () => {
          if (!selected) return;
          const list = recent();
          writeLocal(`recent.${kind}`, [selected.id, ...list.filter((id) => id !== selected.id)].slice(0, 80));
          emit(selected, true);
        });
      use.disabled = !selected;
      const rebind = mkBtn("🔧 更换图库目录", "border:1px solid #555;background:transparent;color:#bbb;height:2.2em;padding:0 10px;", () => {
        req("/settings")
          .then((data) => showBinding(data.settings))
          .catch((err) => { notice.textContent = err?.message || String(err); });
      });
      ui.foot.append(rebind, use);
    }

    // 再次打开时高亮上次选择
    const currentPath = initial.path;
    if (currentPath) selected = cat.items.find((item) => item.path === currentPath) || null;
    if (selected) currentPick = selected;

    render();
  }

  // ── 入口 ──────────────────────────────────────────────────────
  try {
    const data = await req("/settings");
    const cfg = (data.settings || {})[kind] || {};
    if (cfg.accepted && cfg.directory) await showGallery(data.settings);
    else await showBinding(data.settings);
  } catch (err) {
    await showBinding({ [kind]: {} }, err?.message || String(err));
  }
}
