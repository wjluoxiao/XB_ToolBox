/**
 * XB-BOX 快速开关三件套（参考 rgthree-comfy 的 Fast Muter / Fast Groups Muter / Any Switch）
 * =====================================================================================
 *   XB_DisableGroups（禁用分组）· XB_DisableNodes（禁用节点）
 *     —— 不接线：面板/右键菜单里勾选目标，点一行就能「静音 / 绕过 / 恢复」。
 *        状态直接读写画布上节点自己的 mode（随工作流保存，和其他插件互通）。
 *   XB_AnySwitch（切换任意）
 *     —— 动态任意类型输入（默认 any_01 / any_02，连满自动追加）；没有选择控件，
 *        与 rgthree 一致：永远输出第一个非空的输入。
 *
 * 两个「禁用」节点是**纯前端控制节点**（Python 端无输入无输出，不参与执行）：
 *   面板用 DOM widget 画（经典 + Nodes 2.0 都能点），选择结果存 node.properties。
 *   Nodes 2.0 下容器高度用 bindNodes2NodeFill 跟随节点，列表在容器内滚动。
 *   分组 / 节点都可以是子工作流（子图）里的，跨图定位后直接改它们的 mode。
 */

import { app } from "../../scripts/app.js";
import { bindNodes2NodeFill, isNodes2 } from "./xb_compat.js";

const TYPE_GROUPS = "XB_DisableGroups";
const TYPE_NODES = "XB_DisableNodes";
const TYPE_SWITCH = "XB_AnySwitch";

const MODE_ALWAYS = 0;    // 正常
const MODE_NEVER = 2;     // 静音（mute）
const MODE_BYPASS = 4;    // 绕过（bypass）

const PANEL_MIN_H = 34;    // 单行时的最小面板高度
const ROW_GAP = 3;
const PANEL_PAD = 12;      // 容器上下 padding 6px + 6px
const MIN_W = 260;

const PROP_GROUPS = "xb_groups";     // ["分组标题", …]
const PROP_NODES = "xb_nodes";       // [{ id, title }, …]
const PROP_MODE = "xb_off_mode";     // "mute" | "bypass"
const PROP_RESTRICT = "xb_toggle_restrict";   // "multi"（多选可全关全开）| "one"（永远保持一个开启）

/* ── 小工具 ───────────────────────────────────────────────────────────── */
const graphOf = (node) => node?.graph || app.graph;

/** 控件所在图的顶层根图（子图节点内部的 LGraph 有 rootGraph 指回去） */
function rootGraphOf(node) {
  const g = graphOf(node);
  return (g && (g.rootGraph || g)) || app.graph;
}

/**
 * 画布树：根图 + 所有子图（含嵌套）。
 * sg = 子图节点的 id 路径（根图为空串），用于跨子图唯一定位分组 / 节点。
 */
function graphTree(root) {
  const out = [];
  const walk = (g, sg, depth) => {
    if (!g || depth > 8) return;
    out.push({ graph: g, sg });
    for (const n of (g._nodes || [])) {
      if (n && n.subgraph) walk(n.subgraph, sg ? `${sg}/${n.id}` : String(n.id), depth + 1);
    }
  };
  walk(root || app.graph, "", 0);
  return out;
}

/** 子图路径 → 可读名字，如 "New Subgraph › 子子图" */
function sgTitleOf(root, sg) {
  if (!sg) return "";
  const names = [];
  let g = root || app.graph;
  for (const part of String(sg).split("/")) {
    const n = g ? (g._nodes || []).find((x) => String(x.id) === part) : null;
    if (!n) { names.push(`#${part}`); break; }
    names.push(n.title || n.type || `#${part}`);
    g = n.subgraph;
  }
  return names.join(" › ");
}

/** 分组条目 key：子图路径 + 标题 */
const groupKey = (sg, title) => `${sg || ""}\u0001${title}`;
/** 节点条目 key：子图路径 + 节点 id */
const nodeKey = (sg, id) => `${sg || ""}\u0001${id}`;

function allGroupsExt(root) {
  const out = [];
  for (const { graph, sg } of graphTree(root)) {
    for (const g of allGroups(graph)) out.push({ graph, sg, group: g, title: g.title });
  }
  return out;
}

function findGroupExt(root, sg, title) {
  const all = allGroupsExt(root);
  return all.find((x) => x.sg === (sg || "") && x.title === title)
    || all.find((x) => x.title === title)          // 子图改名 / 结构变化后的兜底
    || null;
}

function allNodesExt(root) {
  const out = [];
  for (const { graph, sg } of graphTree(root)) {
    for (const n of (graph?._nodes || [])) if (n) out.push({ graph, sg, node: n });
  }
  return out;
}

function findNodeExt(root, sg, id) {
  const all = allNodesExt(root);
  return all.find((x) => x.sg === (sg || "") && String(x.node.id) === String(id))
    || all.find((x) => String(x.node.id) === String(id))
    || null;
}

function ensureProps(node) {
  if (!node.properties || typeof node.properties !== "object") node.properties = {};
  return node.properties;
}

function markDirty(graph) {
  try { graph?.setDirtyCanvas?.(true, true); } catch (_) { /* ignore */ }
  try { app.canvas?.setDirty?.(true, true); } catch (_) { /* ignore */ }
}

function mkBtn(text, tip, onClick, css) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = text;
  if (tip) b.title = tip;
  b.style.cssText = "font-size:11px;line-height:1.2;height:22px;padding:0 8px;border-radius:5px;"
    + "border:1px solid #555;background:#2b2b2b;color:#ddd;cursor:pointer;white-space:nowrap;font-family:inherit;"
    + (css || "");
  b.addEventListener("pointerdown", (e) => e.stopPropagation());
  b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); onClick?.(e); });
  b.addEventListener("mouseenter", () => { b.style.background = "#3a3a3a"; });
  b.addEventListener("mouseleave", () => { b.style.background = "#2b2b2b"; });
  return b;
}

function allGroups(graph) {
  const list = graph?._groups || graph?.groups || [];
  return Array.from(list).filter((g) => g && typeof g.title === "string");
}

/** 分组内的节点（优先用 LiteGraph 的 _children，回退到包围盒命中） */
function groupNodes(group) {
  if (!group) return [];
  const kids = Array.isArray(group._children) ? group._children : null;
  if (kids && kids.length) return kids.filter((c) => c && c.id != null && c.type);
  const graph = group.graph || app.graph;
  const x = group.pos?.[0] ?? 0;
  const y = group.pos?.[1] ?? 0;
  const w = group.size?.[0] ?? 0;
  const h = group.size?.[1] ?? 0;
  if (!(w > 0 && h > 0)) return [];
  return (graph?._nodes || []).filter((n) => {
    const cx = (n.pos?.[0] || 0) + (n.size?.[0] || 0) / 2;
    const cy = (n.pos?.[1] || 0) + (n.size?.[1] || 0) / 2;
    return cx >= x && cx <= x + w && cy >= y && cy <= y + h;
  });
}


/** 节点属于哪个分组（没有则空串） */
function groupTitleOf(graph, target) {
  for (const g of allGroups(graph)) {
    if (groupNodes(g).some((n) => n === target || n.id === target.id)) return g.title;
  }
  return "";
}



function setModes(nodes, mode) {
  let n = 0;
  const graphs = new Set();
  for (const node of nodes) {
    try {
      node.mode = mode;
      n++;
      if (node.graph) graphs.add(node.graph);
    } catch (_) { /* ignore */ }
  }
  // 子图里的节点只会在自己的图上重绘，所以要逐个标脏
  for (const g of graphs) markDirty(g);
  markDirty(app.graph);
  return n;
}

/* ── 选择对话框（分组 / 节点）──────────────────────────────────────────── */
function openPicker(node, kind) {
  const root = rootGraphOf(node);
  const props = ensureProps(node);
  const isGroups = kind === "groups";

  // 条目：{ key, label, sub, group, sg, title|nodeId }
  const entries = [];
  if (isGroups) {
    for (const { graph, sg, group } of allGroupsExt(root)) {
      const sgName = sgTitleOf(root, sg);
      entries.push({
        key: groupKey(sg, group.title),
        label: group.title || "（未命名分组）",
        sub: `${groupNodes(group).length} 个节点${sgName ? ` · 子图 ${sgName}` : ""}`,
        group: sgName ? `子图 ${sgName}` : "",
        sg,
        title: group.title,
      });
    }
  } else {
    for (const { graph, sg, node: n } of allNodesExt(root)) {
      if (!n || n === node) continue;
      if (n.type === TYPE_GROUPS || n.type === TYPE_NODES) continue;   // 控制节点本身不列
      const sgName = sgTitleOf(root, sg);
      const innerGrp = groupTitleOf(graph, n);
      const isSg = !!n.subgraph;
      const groupParts = [sgName ? `子图 ${sgName}` : "", innerGrp].filter(Boolean);
      entries.push({
        key: nodeKey(sg, n.id),
        label: n.title || n.type || `#${n.id}`,
        sub: [isSg ? "子工作流" : String(n.type || ""), sgName ? `子图 ${sgName}` : ""].filter(Boolean).join(" · "),
        group: groupParts.join(" / ") || "（未分组）",
        sg,
        nodeId: n.id,
      });
    }
  }

  const propGroups = Array.isArray(props[PROP_GROUPS]) ? props[PROP_GROUPS] : [];
  const propNodes = Array.isArray(props[PROP_NODES]) ? props[PROP_NODES] : [];
  const savedGroupKeys = propGroups.map((x) => (typeof x === "string"
    ? groupKey("", x)
    : groupKey(x?.sg || "", x?.title ?? "")));
  const savedNodeKeys = propNodes.map((x) => nodeKey(x?.sg || "", x?.id));

  const selected = new Set(isGroups ? savedGroupKeys : savedNodeKeys);

  // 已选项按上次保存的顺序排在前面，其余保持画布顺序（排序是稳定的）
  const savedOrder = isGroups ? savedGroupKeys : savedNodeKeys;
  if (savedOrder.length) {
    const rank = new Map(savedOrder.map((k, i) => [k, i]));
    entries.sort((a, b) => (rank.has(a.key) ? rank.get(a.key) : Number.MAX_SAFE_INTEGER)
      - (rank.has(b.key) ? rank.get(b.key) : Number.MAX_SAFE_INTEGER));
  }

  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;z-index:10300;background:rgba(0,0,0,.72);"
    + "display:flex;overflow:auto;";
  const panel = document.createElement("div");
  panel.style.cssText = "width:660px;max-width:94vw;max-height:86vh;margin:auto;flex:0 0 auto;display:flex;flex-direction:column;"
    + "background:#1c1c1e;border:1px solid #333;border-radius:8px;color:#ddd;font:13px/1.55 system-ui,sans-serif;"
    + "box-shadow:0 20px 40px rgba(0,0,0,.6);overflow:hidden;";

  const head = document.createElement("div");
  head.style.cssText = "padding:12px 16px;background:#232326;border-bottom:1px solid #3a3a3a;display:flex;align-items:center;gap:10px;";
  const hTitle = document.createElement("div");
  hTitle.textContent = isGroups ? "⚙️ 选择要控制的分组" : "⚙️ 选择要控制的节点";
  hTitle.style.cssText = "flex:1 1 auto;font-size:15px;font-weight:700;color:#eee;";
  const hClose = mkBtn("✕", "关闭", () => close());
  head.append(hTitle, hClose);

  const bar = document.createElement("div");
  bar.style.cssText = "padding:10px 16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;border-bottom:1px solid #2c2c2e;";
  const search = document.createElement("input");
  search.type = "text";
  search.placeholder = isGroups ? "搜索分组…" : "搜索节点名 / 类型…";
  search.style.cssText = "flex:1 1 220px;min-width:160px;height:26px;background:#1e1e1e;color:#ddd;"
    + "border:1px solid #444;border-radius:5px;padding:0 8px;font-size:12px;font-family:inherit;";
  const countEl = document.createElement("span");
  countEl.style.cssText = "color:#8a8a8a;font-size:12px;font-variant-numeric:tabular-nums;";
  const hintEl = document.createElement("span");
  hintEl.textContent = "⠿ 拖拽可调整顺序";
  hintEl.style.cssText = "color:#6f7883;font-size:11px;";
  bar.append(search, hintEl, countEl);

  const list = document.createElement("div");
  list.style.cssText = "flex:1 1 auto;min-height:0;overflow-y:auto;padding:8px 12px;display:flex;flex-direction:column;gap:3px;";

  const foot = document.createElement("div");
  foot.style.cssText = "padding:10px 16px;border-top:1px solid #3a3a3a;display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap;background:#18181a;";

  const close = () => { try { overlay.remove(); } catch (_) { /* ignore */ } };

  // 拖拽排序：被拖的行"浮起"跟随指针，落点用虚线占位框提示
  let dragKey = null, dragStartY = 0, dragging = false;
  const moveEntry = (key, targetKey, after) => {
    const from = entries.findIndex((x) => x.key === key);
    if (from < 0 || key === targetKey) return;
    const [it] = entries.splice(from, 1);
    let to = entries.findIndex((x) => x.key === targetKey);
    if (to < 0) { entries.push(it); return; }
    if (after) to += 1;
    entries.splice(to, 0, it);
  };
  const startDrag = (key, ev) => {
    const src = list.querySelector(`[data-xb-row="${CSS.escape(key)}"]`);
    if (!src) return;
    dragKey = key;
    dragStartY = ev.clientY;
    dragging = false;
    const srcRect = src.getBoundingClientRect();
    const grabY = ev.clientY - srcRect.top;
    let ghost = null, ph = null, cursorStyle = null;

    const ensureArtifacts = () => {
      if (ph) return;
      // 面板高度锁死：否则插入占位框会让面板变高、margin:auto 重新居中，
      // 整个列表会整体上移（实测 17px），落点判断就会偏。
      panel.style.height = `${Math.round(panel.getBoundingClientRect().height)}px`;
      // 源行留在原位但淡出 + 虚线框，表示"它被拿起来了"
      src.style.opacity = "0.28";
      src.style.borderStyle = "dashed";
      src.style.borderColor = "#5c5c5c";
      // 浮起的幽灵行
      ghost = src.cloneNode(true);
      ghost.removeAttribute("data-xb-row");
      ghost.setAttribute("data-xb-ghost", "1");
      ghost.style.cssText += `;position:fixed;left:${srcRect.left}px;top:${srcRect.top}px;width:${srcRect.width}px;`
        + "box-sizing:border-box;z-index:10360;pointer-events:none;margin:0;"
        + "background:#33343a;border:1px solid #f59e0b;border-radius:6px;"
        + "box-shadow:0 14px 30px rgba(0,0,0,.65),0 0 0 1px rgba(245,158,11,.25);"
        + "transform:scale(1.02);opacity:.98;";
      document.body.append(ghost);
      // 落点占位（虚线槽）
      ph = document.createElement("div");
      ph.setAttribute("data-xb-ph", "1");
      ph.style.cssText = `flex:0 0 auto;height:${Math.round(srcRect.height)}px;box-sizing:border-box;`
        + "border-radius:5px;border:2px dashed #f59e0b;background:rgba(245,158,11,.10);pointer-events:none;";
      cursorStyle = document.createElement("style");
      cursorStyle.textContent = "*{cursor:grabbing !important;}";
      document.head.append(cursorStyle);
    };
    const placePh = (e) => {
      // 用"第一个中线在指针下方的行"决定落点，不受占位框插入导致的位移影响
      const rows = Array.from(list.querySelectorAll("[data-xb-row]")).filter((r) => r !== src);
      for (const row of rows) {
        const rect = row.getBoundingClientRect();
        if (e.clientY < rect.top + rect.height / 2) { row.before(ph); return; }
      }
      if (rows.length) rows[rows.length - 1].after(ph);
    };
    const cleanup = () => {
      ghost?.remove();
      ph?.remove();
      cursorStyle?.remove();
      panel.style.height = "";
      src.style.opacity = "1";
      src.style.borderStyle = "solid";
      src.style.borderColor = "#333";
    };
    const onMove = (e) => {
      if (!dragKey) return;
      if (!dragging && Math.abs(e.clientY - dragStartY) < 3) return;
      dragging = true;
      ensureArtifacts();
      ghost.style.top = `${Math.round(e.clientY - grabY)}px`;
      // 靠近列表上下边缘时自动滚动
      const lr = list.getBoundingClientRect();
      if (e.clientY < lr.top + 22) list.scrollTop -= 12;
      else if (e.clientY > lr.bottom - 22) list.scrollTop += 12;
      placePh(e);
    };
    const finish = (commit) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      const from = dragKey;
      dragKey = null;
      dragging = false;
      // 用虚线槽的位置推算插入点：优先"插到下一行之前"，否则"插到上一行之后"
      let targetKey = null, after = false;
      if (commit && ph) {
        let next = ph.nextElementSibling;
        while (next && !next.hasAttribute("data-xb-row")) next = next.nextElementSibling;
        if (next) {
          targetKey = next.getAttribute("data-xb-row");
        } else {
          let prev = ph.previousElementSibling;
          while (prev && !prev.hasAttribute("data-xb-row")) prev = prev.previousElementSibling;
          if (prev) { targetKey = prev.getAttribute("data-xb-row"); after = true; }
        }
      }
      cleanup();
      if (commit && from && targetKey && targetKey !== from) {
        moveEntry(from, targetKey, after);
        render();
      }
    };
    const onUp = () => finish(true);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  const render = () => {
    const q = search.value.trim().toLowerCase();
    list.replaceChildren();
    let shown = 0;
    let lastGroup = null;
    for (const it of entries) {
      if (!isGroups && it.group !== lastGroup) {
        lastGroup = it.group;
        const gh = document.createElement("div");
        gh.textContent = `— ${it.group} —`;
        gh.style.cssText = "margin:6px 0 2px;color:#7f8c99;font-size:11px;";
        list.append(gh);
      }
      if (q && !(`${it.label} ${it.sub} ${it.group}`.toLowerCase().includes(q))) continue;
      shown++;
      const row = document.createElement("label");
      row.style.cssText = "display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:5px;cursor:pointer;"
        + "background:#242424;border:1px solid #333;";
      row.dataset.xbRow = it.key;
      const grip = document.createElement("span");
      grip.textContent = "⠿";
      grip.title = "拖拽调整顺序";
      grip.style.cssText = "flex:0 0 auto;color:#6b7480;font-size:14px;line-height:1;cursor:grab;user-select:none;"
        + "padding:2px 4px;margin:-2px 0;touch-action:none;";
      grip.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        e.stopPropagation();
        try { grip.setPointerCapture?.(e.pointerId); } catch (_) { /* ignore */ }
        startDrag(it.key, e);
      });
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selected.has(it.key);
      cb.style.cssText = "width:15px;height:15px;accent-color:#f59e0b;cursor:pointer;flex:0 0 auto;";
      cb.addEventListener("change", () => {
        if (cb.checked) selected.add(it.key); else selected.delete(it.key);
        syncCount();
      });
      const name = document.createElement("span");
      name.textContent = it.label;
      name.style.cssText = "flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#e6e6e6;";
      const sub = document.createElement("span");
      sub.textContent = it.sub || "";
      sub.style.cssText = "flex:0 0 auto;color:#7d8792;font-size:11px;";
      row.append(grip, cb, name, sub);
      list.append(row);
    }
    if (!shown) {
      const empty = document.createElement("div");
      empty.textContent = isGroups ? "当前画布上没有分组" : "没有匹配的节点";
      empty.style.cssText = "padding:16px;color:#8a8a8a;text-align:center;";
      list.append(empty);
    }
    syncCount();
  };

  const syncCount = () => { countEl.textContent = `已选 ${selected.size} / ${entries.length}`; };

  const selectAll = (on) => {
    const q = search.value.trim().toLowerCase();
    for (const it of entries) {
      if (q && !(`${it.label} ${it.sub} ${it.group}`.toLowerCase().includes(q))) continue;
      if (on) selected.add(it.key); else selected.delete(it.key);
    }
    render();
  };

  const confirm = () => {
    // 顺序 = 列表里的顺序（可拖拽调整），不是勾选先后
    const chosen = entries.filter((it) => selected.has(it.key));
    if (isGroups) {
      // 根图分组仍写成字符串（兼容旧工作流），子图分组写成 { sg, title }
      props[PROP_GROUPS] = chosen.map((it) => (it.sg ? { sg: it.sg, title: it.title } : it.title));
    } else {
      props[PROP_NODES] = chosen.map((it) => {
        const hit = findNodeExt(root, it.sg, it.nodeId);
        const item = { id: it.nodeId, title: hit?.node?.title || "" };
        if (it.sg) item.sg = it.sg;
        return item;
      });
    }
    markDirty(root);
    refreshRows(node);
    close();
  };

  const cancel = mkBtn("取消", "放弃修改", close);
  const ok = mkBtn("确定", "保存选择", confirm, "border-color:#3f86d0;background:#22456b;color:#eaf4ff;font-weight:600;");
  foot.append(
    mkBtn("全选", "选中当前筛选结果里的全部条目", () => selectAll(true)),
    mkBtn("清空", "取消全部选择", () => selectAll(false)),
    cancel, ok,
  );

  search.addEventListener("input", render);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  panel.append(head, bar, list, foot);
  overlay.append(panel);
  document.body.append(overlay);
  render();
  setTimeout(() => { try { search.focus(); } catch (_) { /* ignore */ } }, 30);
}

/* ── 面板（DOM widget）────────────────────────────────────────────────── */
function buildPanel(node, kind) {
  const isGroups = kind === "groups";
  const container = document.createElement("div");
  container.style.cssText = "width:100%;height:100%;box-sizing:border-box;display:flex;flex-direction:column;"
    + `gap:4px;padding:${PANEL_PAD / 2}px;overflow:visible;background:#2b2b2b;border-radius:6px;`;

  // 节点表面只留「开关列表」——选择 / 禁用方式 / 切换模式 全部收进右键菜单
  const list = document.createElement("div");
  list.style.cssText = `flex:1 1 auto;min-height:0;overflow:visible;display:flex;flex-direction:column;gap:${ROW_GAP}px;`;
  container.append(list);

  node._xbPanelList = list;
  node._xbPanel = container;

  // DOM widget：经典模式按 computeSize 给高度，Nodes 2.0 按 computeLayoutSize 给最小高度
  const widget = node.addDOMWidget?.("xb_toggle_panel", "XB_TOGGLE_PANEL", container, {
    serialize: false,
    hideOnZoom: false,
  });
  if (widget) {
    try { delete widget.computeSize; } catch (_) { widget.computeSize = undefined; }
    widget.options = widget.options || {};
    widget.options.serialize = false;
    widget.options.getMinHeight = () => PANEL_MIN_H;
    widget.options.getHeight = () => "100%";
    widget.computeSize = () => [Math.max(MIN_W, Math.round(node.size?.[0] || MIN_W)), panelHeightOf(node)];
    widget.computeLayoutSize = () => ({ minHeight: panelHeightOf(node), maxHeight: undefined, minWidth: MIN_W });
  }
  node.min_width = MIN_W;
  node.minWidth = MIN_W;
  try { bindNodes2NodeFill(node, container, { min: PANEL_MIN_H }); } catch (_) { /* ignore */ }
  // 交给 applyPanelHeight 决定高度（不要在挂载瞬间无脑 setSize，否则刷新页面会先跳一下）
  setTimeout(() => { applyPanelHeight(node); }, 0);
}

function modeOffOf(node) {
  return ensureProps(node)[PROP_MODE] === "bypass" ? MODE_BYPASS : MODE_NEVER;
}

/** 切换模式：multi = 多选（可全关全开）／one = 永远保持一个开启 */
function restrictOf(node) {
  return ensureProps(node)[PROP_RESTRICT] === "one" ? "one" : "multi";
}

/** 当前行数据：[{ label, nodes, missing }]（分组/节点可能位于子工作流内部） */
function rowsOf(node) {
  const root = rootGraphOf(node);
  const props = ensureProps(node);
  const out = [];
  if (node.type === TYPE_GROUPS) {
    const items = Array.isArray(props[PROP_GROUPS]) ? props[PROP_GROUPS] : [];
    for (const it of items) {
      const title = typeof it === "string" ? it : (it?.title ?? "");
      const sg = typeof it === "string" ? "" : (it?.sg || "");
      const hit = findGroupExt(root, sg, title);
      const sgName = sgTitleOf(root, sg);
      out.push({
        label: title || "（未命名分组）",
        tip: sgName ? `子图 ${sgName}` : "",     // 子图信息只放 tooltip，不占显示名
        nodes: hit ? groupNodes(hit.group) : [],
        missing: !hit,
      });
    }
  } else {
    const items = Array.isArray(props[PROP_NODES]) ? props[PROP_NODES] : [];
    for (const it of items) {
      const sg = it?.sg || "";
      const hit = findNodeExt(root, sg, it?.id);
      // 兜底：子图被解开 / 重新打包导致 id 变了，就按标题在整棵树里找
      const n = hit?.node
        || (it?.title ? (allNodesExt(root).find((x) => x.node.title === it.title)?.node || null) : null);
      const sgName = sgTitleOf(root, sg);
      const title = it?.title || n?.title || `#${it?.id ?? "?"}`;
      out.push({
        label: title,                            // 只显示节点名，不加子图前缀
        tip: sgName ? `子图 ${sgName}` : "",
        nodes: n ? [n] : [],
        missing: !n,
      });
    }
  }
  return out;
}

/** 静音（2）与绕过（4）都算关闭，与当前禁用方式无关 */
function isOffMode(mode) {
  return mode === MODE_NEVER || mode === MODE_BYPASS;
}

/** 一行是否处于「开启」状态（读画布上节点的真实 mode） */
function rowEnabled(row) {
  return !!row.nodes.length && row.nodes.some((n) => !isOffMode(n.mode));
}

/** 点一行：按切换模式（多选 / 永远保持一个开启）改状态 */
function toggleRow(node, index) {
  const off = modeOffOf(node);
  const one = restrictOf(node) === "one";
  const rows = rowsOf(node);
  const row = rows[index];
  if (!row || !row.nodes.length) return true;
  const graph = graphOf(node);
  if (rowEnabled(row)) {
    // 永远保持一个开启 → 不许把最后一个开启的行关掉
    if (one && !rows.some((r, i) => i !== index && rowEnabled(r))) return false;
    setModes(row.nodes, off);
  } else {
    if (one) rows.forEach((r, i) => { if (i !== index) setModes(r.nodes, off); });
    setModes(row.nodes, MODE_ALWAYS);
  }
  return true;
}

/** 开关外观（纯 CSS 的小滑块） */
function buildSwitch(enabled, disabled) {
  const box = document.createElement("span");
  box.style.cssText = "flex:0 0 auto;position:relative;width:34px;height:18px;border-radius:9px;"
    + `background:${disabled ? "#3a3a3a" : enabled ? "#3f86d0" : "#4a4a4a"};`
    + "transition:background .15s;";
  const knob = document.createElement("span");
  knob.style.cssText = "position:absolute;top:2px;width:14px;height:14px;border-radius:7px;background:#fff;"
    + `left:${enabled ? "18px" : "2px"};transition:left .15s;`;
  box.append(knob);
  return box;
}

/** 已经被删掉的目标：连续两轮刷新都找不到 → 从选择里移除（选项跟着消失） */
function pruneMissingTargets(node) {
  // 载入 / 打包子图等过渡期不做清理，避免把还能找回的选项误删
  if (performance.now() - (node.__xbMountedAt || 0) < 3000) return false;
  const props = ensureProps(node);
  const key = node.type === TYPE_GROUPS ? PROP_GROUPS : PROP_NODES;
  const arr = Array.isArray(props[key]) ? props[key] : null;
  if (!arr || !arr.length) return false;
  const rows = rowsOf(node);
  const seen = node.__xbMissing || (node.__xbMissing = Object.create(null));
  const kept = [];
  let changed = false;
  let anyMissing = false;
  rows.forEach((row, i) => {
    const src = arr[i];
    const id = `${src?.sg || ""}\u0001${typeof src === "string" ? src : (src?.title ?? src?.id ?? i)}`;
    if (!row.missing) { delete seen[id]; kept.push(src); return; }
    anyMissing = true;
    seen[id] = (seen[id] || 0) + 1;
    if (seen[id] >= 2) { changed = true; return; }   // 第二次仍找不到 → 真的被删了
    kept.push(src);
  });
  if (!changed) {
    // 只是第一次没找到（可能是打包 / 撤销的中间状态）→ 稍后再确认一次
    if (anyMissing && !node.__xbPruneTimer) {
      node.__xbPruneTimer = setTimeout(() => { node.__xbPruneTimer = 0; refreshRows(node); }, 450);
    }
    return false;
  }
  props[key] = kept;
  markDirty(node.graph);
  return true;
}

/** 重画面板列表（读的是画布上节点的真实 mode；找不到的目标直接不显示） */
function refreshRows(node) {
  const list = node._xbPanelList;
  if (!list) return;
  pruneMissingTargets(node);
  const all = rowsOf(node);
  // 目标已被删除的行不显示（连同它的索引一起记下来，点击时仍按原始顺序定位）
  const rows = all.map((row, i) => ({ row, i })).filter((x) => !x.row.missing);
  const rowChanged = node.__xbRowCount !== rows.length;
  node.__xbRowCount = rows.length;
  list.replaceChildren();

  if (!rows.length) {
    const tip = document.createElement("div");
    tip.textContent = (node.type === TYPE_GROUPS
      ? "还没有选择分组 —— "
      : "还没有选择节点 —— ")
      + "右击本节点 →「" + (node.type === TYPE_GROUPS ? "选择分组" : "选择节点") + "…」勾选。";
    tip.style.cssText = "padding:10px;color:#8a8a8a;font-size:11px;line-height:1.6;";
    list.append(tip);
    applyPanelHeight(node, true);
    return;
  }

  for (const { row, i: idx } of rows) {
    const enabled = rowEnabled(row);
    const partial = enabled && row.nodes.some((n) => isOffMode(n.mode));

    const el = document.createElement("div");
    el.style.cssText = "display:flex;align-items:center;gap:8px;padding:3px 6px;border-radius:5px;"
      + `background:${enabled ? "#22456b" : "#1f1f1f"};`
      + `border:1px solid ${enabled ? "#3f86d0" : "#3a3a3a"};`
      + "cursor:pointer;";

    const name = document.createElement("span");
    name.textContent = row.label + (partial ? " ◐" : "");
    name.style.cssText = "flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
      + `font-size:12px;color:${enabled ? "#eaf4ff" : "#c8c8c8"};`;
    name.title = [row.tip, row.nodes.length ? `${row.nodes.length} 个节点` : ""].filter(Boolean).join(" · ");
    el.append(name, buildSwitch(enabled, false));

    el.addEventListener("pointerdown", (e) => e.stopPropagation());
    el.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      const ok = toggleRow(node, idx);
      refreshRows(node);
      if (!ok) {
        // 永远保持一个开启：拒绝全关 → 闪一下提示
        el.style.borderColor = "#e05555";
        setTimeout(() => { try { el.style.borderColor = enabled ? "#3f86d0" : "#3a3a3a"; } catch (_) { /* ignore */ } }, 450);
      }
    });
    el.addEventListener("mouseenter", () => { el.style.filter = "brightness(1.18)"; });
    el.addEventListener("mouseleave", () => { el.style.filter = ""; });
    list.append(el);
  }
  applyPanelHeight(node, rowChanged);
}

/* ── 右键菜单（节点表面不再显示任何设置，全部收在这里）───────────────── */
function panelContentHeight(node) {
  const list = node._xbPanelList;
  if (!list) return 0;
  const kids = Array.from(list.children);
  if (!kids.length) return 0;
  let h = 0;
  for (const c of kids) h += c.offsetHeight || 0;
  return h + Math.max(0, kids.length - 1) * ROW_GAP;
}

function panelHeightOf(node) {
  return node.__xbPanelH || PANEL_MIN_H;
}

/** 内容区之外的"chrome"（= 容器顶部偏移 + 底部留白 - 标题栏）——Nodes 2.0 的 node.size 不含标题栏 */
function chromeOf(node) {
  const box = node._xbPanel;
  const root = box?.closest?.(".lg-node");
  if (!box || !root) return 0;
  let y = 0;
  let cur = box;
  while (cur && cur !== root) {
    y += cur.offsetTop || 0;
    cur = cur.offsetParent;
  }
  if (cur !== root) return 0;
  let header = 0;
  try {
    const hEl = root.querySelector(".lg-node-header");
    header = hEl ? hEl.offsetHeight : 0;
  } catch (_) { header = 0; }
  return Math.max(0, y - header) + 12;
}

/** 节点高度贴着开关数量走（不留空白，也不截断）——行数 / 行高变了都会重算 */
function applyPanelHeight(node, force) {
  const box = node._xbPanel;
  if (!box) return;
  if (node.__xbFitting) return;                 // 防止 setSize 引发的重排再触发自己
  const content = panelContentHeight(node);
  if (!content) return;                         // 还没渲染到 DOM，下次刷新再算
  const h = Math.max(PANEL_MIN_H, Math.round(content + PANEL_PAD));
  node.__xbPanelH = h;
  const want = Math.max(MIN_W, Math.round(node.size?.[0] || MIN_W));
  const nodeH = Math.round(node.size?.[1] || 0);
  // ⚠️ 刷新页面 / 载入工作流时不要重排高度：
  //    ① 字体还没就绪，量到的行高偏小（25 vs 32）；
  //    ② 存档里本来就有正确高度。
  //    所以刚挂载的一段窗口内只记录面板高度，不动 setSize。
  if (performance.now() < (node.__xbSkipFitUntil || 0)) return;
  // 收缩需连续两次量到同一个更小值才采纳（变高立即生效），避免字体/布局中间帧造成抖动；
  // 但差异很大时（老的存档高度偏差）直接改，不然会在载入后一秒才"跳"一下。
  const shrinkNow = (target) => target < nodeH - 2;
  const allowShrink = (target) => {
    if (force) return true;
    if (Math.abs(nodeH - target) > 12) return true;
    if (node.__xbShrinkCand === target) { node.__xbShrinkCand = null; return true; }
    node.__xbShrinkCand = target;
    return false;
  };
  const fit = (target) => {
    node.__xbFitting = true;
    try {
      node.setSize?.([want, target]);
      markDirty(node.graph);
      // 经典模式下 DOM widget 是绝对定位的浮层，尺寸变化后要整幅重绘，否则画布上会残留旧边框
      if (!isNodes2()) app.canvas?.draw?.(true, true);
    } finally {
      setTimeout(() => { node.__xbFitting = false; }, 80);
    }
  };
  // 载入的节点高度只做很小幅度的容差（老的存档高度可能略有偏差，但不该为了几像素去重排）
  const maybeFit = (target, tol) => {
    const diff = Math.abs(nodeH - target);
    if (diff <= tol) { node.__xbFitted = true; return; }
    // 挂载后的第一次校正直接生效（一次性把旧存档高度对齐），之后才走防抖逻辑
    if (!node.__xbFitted) {
      node.__xbFitted = true;
      fit(target);
      return;
    }
    if (node.__xbFromWorkflow && !force && diff <= 3) return;
    if (shrinkNow(target) && !allowShrink(target)) return;
    fit(target);
  };

  // 经典模式：DOM widget 的高度由 LiteGraph 的 computeSize 决定，节点高度也交给 computeSize
  // （这里不能用 Nodes 2.0 那套 nodeH - boxH 反推：经典模式容器高度不随 setSize 变，会一路膨胀）
  if (!isNodes2()) {
    const target = Math.round(node.computeSize?.()[1] || h + 40);
    maybeFit(target, 4);
    // 画布里 DOM widget 的高度是渲染时按旧尺寸铺的，直接钉住它，避免内容溢出到节点外
    const wrap = box.parentElement;
    if (wrap && wrap.classList?.contains("dom-widget") && wrap.style.height !== `${h}px`) wrap.style.height = `${h}px`;
    if (box.style.height !== `${h}px`) box.style.height = `${h}px`;
    return;
  }

  // 容器在节点内容区里的位置由布局决定（offsetTop 累加，与缩放无关）
  // ⚠️ 不能用 nodeH - boxH 反推：容器还没被 bindNodes2NodeFill 填满时量出来会偏大，
  //    之后 chrome + h 就会永远多出这几像素（实测 45 vs 38 ⇒ 节点永远高 7px）。
  const chrome = chromeOf(node) || node.__xbChrome || 0;
  node.__xbChrome = chrome;
  if (!chrome) return;
  maybeFit(chrome + h, 6);   // 几像素的差异不去动，避免载入时无意义的高度跳动
}

function addMenu(node, options) {
  const isGroups = node.type === TYPE_GROUPS;
  const graph = graphOf(node);
  const off = modeOffOf(node);
  const one = restrictOf(node) === "one";

  const setAll = (mode) => {
    const rows = rowsOf(node);
    rows.forEach((r) => setModes(r.nodes, mode));
    refreshRows(node);
  };

  const setRestrict = (value) => {
    ensureProps(node)[PROP_RESTRICT] = value;
    if (value === "one") {
      // 只保留第一个开启的行（没有开启的就打开第一项）
      const rows = rowsOf(node);
      const keep = rows.findIndex((r) => rowEnabled(r));
      rows.forEach((r, i) => {
        if (i === Math.max(0, keep)) setModes(r.nodes, MODE_ALWAYS);
        else setModes(r.nodes, off);
      });
    }
    refreshRows(node);
  };

  const setOffMode = (value) => {
    const next = value === "bypass" ? MODE_BYPASS : MODE_NEVER;
    ensureProps(node)[PROP_MODE] = value;
    if (next !== off) {
      // 已禁用的行跟随新方式，避免切换后误判为「开启」
      for (const r of rowsOf(node)) {
        if (r.nodes.length && r.nodes.every((n) => n.mode === off)) setModes(r.nodes, next);
      }
    }
    refreshRows(node);
  };

  options.unshift(
    {
      content: isGroups ? "⚙️ 选择分组…" : "⚙️ 选择节点…",
      callback: () => openPicker(node, isGroups ? "groups" : "nodes"),
    },
    {
      content: `${one ? "" : "✓ "}🔀 多选：可全关 / 全开`,
      callback: () => setRestrict("multi"),
    },
    {
      content: `${one ? "✓ " : ""}🔀 单选：永远保持一个开启`,
      callback: () => setRestrict("one"),
    },
    {
      content: `${off === MODE_NEVER ? "✓ " : ""}⛔ 禁用方式：静音（mute）`,
      callback: () => setOffMode("mute"),
    },
    {
      content: `${off === MODE_BYPASS ? "✓ " : ""}⛔ 禁用方式：绕过（bypass）`,
      callback: () => setOffMode("bypass"),
    },
    {
      content: "✓ 全部启用",
      callback: () => setAll(MODE_ALWAYS),
    },
    {
      content: "✗ 全部禁用",
      callback: () => {
        const rows = rowsOf(node);
        // 永远保持一个开启：全关时保留第一项
        if (one && rows.length) {
          rows.forEach((r, i) => setModes(r.nodes, i === 0 ? MODE_ALWAYS : off));
          refreshRows(node);
          return;
        }
        setAll(off);
      },
    },
    {
      content: "⇄ 全部反转",
      callback: () => {
        const rows = rowsOf(node);
        if (one) {
          // 永远保持一个开启：反转后若全关，则打开第一项
          rows.forEach((r) => {
            const on = rowEnabled(r);
            setModes(r.nodes, on ? off : MODE_ALWAYS);
          });
          if (rows.length && !rows.some((r) => rowEnabled(r))) {
            setModes(rows[0].nodes, MODE_ALWAYS);
          }
          refreshRows(node);
          return;
        }
        rows.forEach((r) => {
          const on = rowEnabled(r);
          setModes(r.nodes, on ? off : MODE_ALWAYS);
        });
        refreshRows(node);
      },
    },
    {
      content: "🔄 刷新列表",
      callback: () => refreshRows(node),
    },
    {
      content: "🗑 清空选择",
      callback: () => {
        const props = ensureProps(node);
        if (isGroups) props[PROP_GROUPS] = []; else props[PROP_NODES] = [];
        refreshRows(node);
      },
    },
    null,
  );
}

/* ── 节点安装 ─────────────────────────────────────────────────────────── */
function setupToggleNode(node) {
  if (node.__xbToggleReady) return;
  node.__xbToggleReady = true;
  node.__xbMountedAt = performance.now();
  // 从工作流载入的节点：存档里已有高度，前 1.5s 一律不动高度（避免刷新时先变矮再弹回）
  const props0 = ensureProps(node);
  const fromWorkflow = Array.isArray(props0[PROP_GROUPS]) || Array.isArray(props0[PROP_NODES]);
  node.__xbFromWorkflow = fromWorkflow;
  // 等布局/字体稳定（约 0.7s）后再做唯一一次高度校正，之后只随行数变化调整
  node.__xbSkipFitUntil = node.__xbMountedAt + 700;
  const kind = node.type === TYPE_GROUPS ? "groups" : "nodes";
  buildPanel(node, kind);
  refreshRows(node);

  // 画布有增删（分组改名 / 节点被删 / 子图内容变化）→ 低频刷新列表，不打断交互
  let lastSig = "";
  const sig = () => {
    const props = ensureProps(node);
    const modes = [];
    for (const r of rowsOf(node)) for (const n of r.nodes) modes.push(n.mode);
    const tree = graphTree(rootGraphOf(node));
    const nodes = tree.reduce((a, t) => a + (t.graph?._nodes || []).length, 0);
    const groups = tree.reduce((a, t) => a + (t.graph?._groups || []).length, 0);
    return `${groups}|${nodes}|${tree.length}|${node.size?.[1] || 0}`
      + `|${JSON.stringify(props[PROP_GROUPS] || null)}|${JSON.stringify(props[PROP_NODES] || null)}`
      + `|${restrictOf(node)}|${modeOffOf(node)}|${modes.join("")}`;
  };
  node.__xbTimer = setInterval(() => {
    if (!node.graph) return;
    const s = sig();
    if (s !== lastSig) { lastSig = s; refreshRows(node); return; }
    // 没有结构变化时也检查一下"已删除的目标"（载入的旧存档里可能带着已删条目）
    if (pruneMissingTargets(node)) { lastSig = sig(); refreshRows(node); return; }
    applyPanelHeight(node);        // 挂载 / 字体变化后校正高度
  }, 500);
  const prevRemoved = node.onRemoved;
  node.onRemoved = function (...args) {
    try { clearInterval(node.__xbTimer); } catch (_) { /* ignore */ }
    try { clearTimeout(node.__xbPruneTimer); } catch (_) { /* ignore */ }
    return prevRemoved?.apply(this, args);
  };
  // 挂载后补两次刷新（首帧可能量不到容器高度，靠这里对齐）
  setTimeout(() => { lastSig = sig(); refreshRows(node); }, 300);
  setTimeout(() => { lastSig = sig(); refreshRows(node); }, 1200);
  // 过了清理保护期后再回头看一次：旧存档里已删除的条目在这里被清掉
  setTimeout(() => { if (node.graph) { lastSig = sig(); refreshRows(node); } }, 3400);
}

/* ── 切换任意：动态任意类型输入 ───────────────────────────────────────── */
function inputUpstream(node, input) {
  try {
    const graph = graphOf(node);
    if (input?.link == null) return null;
    const link = graph.links?.[input.link];
    if (!link) return null;
    return graph.getNodeById?.(link.origin_id) || null;
  } catch (_) { return null; }
}

function setupAnySwitch(node) {
  if (node.__xbSwitchReady) return;
  node.__xbSwitchReady = true;
  node.min_width = 200;
  node.minWidth = 200;

  // 默认 2 个输入端口；连满后自动追加，断开后自动收回（至少保留 2 个）
  const MIN_SLOTS = 2;
  const nameOf = (i) => `any_${String(i + 1).padStart(2, "0")}`;
  // ⚠️ Nodes 2.0 里每个 widget 也会在 node.inputs 里占一个「widget 槽位」→ 只处理真正的数据槽位
  const dataInputs = () => (node.inputs || []).filter((i) => i && !i.widget);
  const dataIdx = () => (node.inputs || []).map((inp, i) => (inp && !inp.widget ? i : -1)).filter((i) => i >= 0);

  const stabilize = () => {
    if (node.__xbBusy || !node.inputs) return;
    node.__xbBusy = true;
    let changed = false;
    try {
      // ① 只留末尾一个空槽：中间的空槽收掉（后续端口自动上移，保持紧凑）
      let idxs = dataIdx();
      for (let k = idxs.length - 2; k >= 0; k--) {
        const inp = node.inputs[idxs[k]];
        if (inp && inp.link == null) { node.removeInput(idxs[k]); changed = true; }
      }
      // ② 不足 MIN_SLOTS 时补齐
      idxs = dataIdx();
      for (let i = idxs.length; i < MIN_SLOTS; i++) {
        node.addInput(nameOf(i), "*");
        changed = true;
      }
      // ③ 末尾端口已接线 → 再加一个空端口，保证总有可连的地方
      idxs = dataIdx();
      if (idxs.length && node.inputs[idxs[idxs.length - 1]].link != null) {
        node.addInput(nameOf(idxs.length), "*");
        changed = true;
      }
      // ④ 统一命名（后端按 any_01 / any_02 … 排序）+ 端口显示上游节点名
      dataInputs().forEach((inp, i) => {
        const nm = nameOf(i);
        if (inp.name !== nm) { inp.name = nm; changed = true; }
        const up = inputUpstream(node, inp);
        const label = up ? (up.title || up.type || "") : "";
        if ((inp.label || "") !== label) { inp.label = label; changed = true; }
      });
      // ⑤ 输出端口标签跟随第一个已连接输入的类型（与 rgthree 一致，没连接时保持 *）
      const out = node.outputs?.[0];
      if (out) {
        let t = "*";
        for (const inp of dataInputs()) {
          if (inp.link == null) continue;
          try { t = node.graph?.links?.[inp.link]?.type || "*"; } catch (_) { t = "*"; }
          break;
        }
        if ((out.label || "") !== t) { out.label = t; changed = true; }
      }
    } catch (_) { /* ignore */ } finally {
      node.__xbBusy = false;
    }
    if (changed) {
      markDirty(node.graph);
      try { node.setSize?.([node.size?.[0] || 220, node.computeSize?.()[1] || node.size?.[1] || 100]); } catch (_) { /* ignore */ }
    }
  };
  node.__xbStabilize = stabilize;

  const prevConn = node.onConnectionsChange;
  node.onConnectionsChange = function (...args) {
    const r = prevConn?.apply(this, args);
    setTimeout(stabilize, 0);
    return r;
  };
  const prevConfigure = node.onConfigure;
  node.onConfigure = function (...args) {
    const r = prevConfigure?.apply(this, args);
    setTimeout(stabilize, 60);
    return r;
  };

  // 新节点：先铺 2 个端口；恢复的工作流则按存档里的端口数走
  if (!dataInputs().length) for (let i = 0; i < MIN_SLOTS; i++) node.addInput(nameOf(i), "*");
  setTimeout(stabilize, 0);
  setTimeout(stabilize, 200);

  let lastSig = "";
  const timer = setInterval(() => {
    if (!node.graph) return;
    const sig = dataInputs().map((i) => `${i.name}:${i.link}`).join(",");
    if (sig !== lastSig) { lastSig = sig; stabilize(); }
  }, 700);
  const prevRemoved = node.onRemoved;
  node.onRemoved = function (...args) {
    try { clearInterval(timer); } catch (_) { /* ignore */ }
    return prevRemoved?.apply(this, args);
  };
}

/* ── 扩展注册 ─────────────────────────────────────────────────────────── */
app.registerExtension({
  name: "XB_ToolBox.FastToggle",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    const name = nodeData?.name;
    if (name !== TYPE_GROUPS && name !== TYPE_NODES && name !== TYPE_SWITCH) return;

    const prevCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = prevCreated?.apply(this, arguments);
      const self = this;
      setTimeout(() => {
        if (name === TYPE_SWITCH) setupAnySwitch(self);
        else setupToggleNode(self);
      }, 0);
      return r;
    };

    if (name === TYPE_GROUPS || name === TYPE_NODES) {
      const prevMenu = nodeType.prototype.getExtraMenuOptions;
      nodeType.prototype.getExtraMenuOptions = function (_, options) {
        prevMenu?.apply(this, arguments);
        try { addMenu(this, options); } catch (_) { /* ignore */ }
      };
    } else if (name === TYPE_SWITCH) {
      const prevMenu = nodeType.prototype.getExtraMenuOptions;
      nodeType.prototype.getExtraMenuOptions = function (_, options) {
        prevMenu?.apply(this, arguments);
        const self = this;
        options.unshift(
          { content: "🔄 刷新端口（整理空槽 / 同步上游名称）", callback: () => { try { self.__xbStabilize?.(); } catch (_) { /* ignore */ } } },
          null,
        );
      };
    }
  },

  async loadedGraphNode(node) {
    if (node?.type === TYPE_SWITCH) setTimeout(() => setupAnySwitch(node), 120);
    else if (node?.type === TYPE_GROUPS || node?.type === TYPE_NODES) setTimeout(() => setupToggleNode(node), 120);
  },
});

export const XB_FAST_TOGGLE = { version: 1 };
