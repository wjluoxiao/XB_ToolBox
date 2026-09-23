import { app } from "../../scripts/app.js";
import { isNodes2, sizeDomWidget } from "./xb_compat.js";

// ============================================================
// XB_CanvasLabel — 文字标签节点
// ============================================================
// 【Nodes 2.0 适配说明】
//   经典模式：整个节点靠劫持 LGraphCanvas.drawNode + node.draw() 画文字（本文件上半部分，逻辑不变）。
//   Nodes 2.0：节点由 DOM 渲染，drawNode() 会直接 early-return —— 上面那套一根线都画不出来。
//     → 追加一个 DOM widget 承载文字（CSS 做颜色/字号/对齐/背景/圆角/旋转），并把节点底色设为透明，
//       让它看起来与经典模式一样是“一张贴纸”。
//   onDblClick（画布坐标）在 2.0 不触发 → 双击编辑文字改挂在 DOM 元素上；右键菜单两边都可用。

// ---- 1. 劫持 drawNode（隐藏默认边框/标题）----
const oldDrawNode = LGraphCanvas.prototype.drawNode;
LGraphCanvas.prototype.drawNode = function (node, ctx) {
    if (node.comfyClass !== "XB_CanvasLabel" && node.type !== "XB_CanvasLabel")
        return oldDrawNode.apply(this, arguments);

    // ⚠️ Nodes 2.0：文字改由 DOM 贴纸渲染。画布这边**必须一件事都不做**——
    //    旧写法在调用原实现（2.0 会 early-return）后仍然执行 `node.draw(ctx)`，
    //    而 2.0 的画布依旧渲染在 DOM 节点后面 ⇒ 画布文字 + DOM 贴纸重叠 = 用户看到的「两排字/重影」
    //    （实测截图：同一行文字前后错位叠了两层）。
    if (isNodes2()) return oldDrawNode.apply(this, arguments);

    node.bgcolor = node.color = "transparent";
    // ⚠️ 不要再「临时把 node.title 置空」来隐藏标题：前端经典渲染器在标题为空时会**回退绘制
    //    `#<节点id> <包名>`**（实测出现 "#122 XB_ToolBox"）→ 反而多出一行字。
    //    标题栏统一交给 rgthree 同款 `title_mode = NO_TITLE` 类静态属性（见 beforeRegisterNodeDef）。
    const result = oldDrawNode.apply(this, arguments);
    if (node.draw) node.draw(ctx);
    return result;
};

// ---- 2. Nodes 2.0：DOM 渲染的“贴纸” ----
// 兜底 CSS：本节点的“节点徽标”一律不显示（2.0 下徽标是 DOM，普通节点上是 `#id 包名`）
const XB_LABEL_STYLE_ID = "xb-canvas-label-style";
function ensureXbLabelStyle() {
    if (document.getElementById(XB_LABEL_STYLE_ID)) return;
    const st = document.createElement("style");
    st.id = XB_LABEL_STYLE_ID;
    st.textContent = `[data-xb-label-root] [class*="badge" i]{display:none!important}\n[data-xb-label-root] [class*="node-id" i]{display:none!important}`;
    document.head.appendChild(st);
}

function installDomLabel(node) {
    ensureXbLabelStyle();
    const el = document.createElement("div");
    el.dataset.xbLabel = "1";
    el.style.cssText = [
        "box-sizing:border-box",
        "white-space:pre",
        "display:inline-block",
        "width:max-content",
        "max-width:100%",
        "transform-origin:center center",
        "user-select:none",
        "pointer-events:auto",
    ].join(";");

    const w = node.addDOMWidget("xb_label_view", "xb_label_view", el, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 40,
    });
    sizeDomWidget(node, w, 40);

    const clamp = (v, lo, hi, dflt) => {
        const n = Number(v);
        return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : dflt;
    };

    const render = () => {
        const p = node.properties || {};
        const fontSize = clamp(p.fontSize, 1, 800, 40);
        const pad = Math.max(0, Number(p.padding) || 0);
        const raw = String(node.title ?? "").replace(/\\n/g, "\n").replace(/\n*$/, "");
        const lines = raw.length === 0 ? [""] : raw.split("\n");
        const angle = parseInt(p.angle) || 0;

        el.textContent = lines.join("\n") || " ";
        el.style.font = fontSize + "px Arial";
        el.style.lineHeight = "1.15";
        el.style.color = p.fontColor || "#ffffff";
        el.style.textAlign = p.textAlign || "left";
        el.style.padding = pad + "px";
        el.style.background =
            p.backgroundColor && p.backgroundColor !== "transparent" ? p.backgroundColor : "transparent";
        el.style.borderRadius = clamp(p.borderRadius, 0, 400, 0) + "px";
        el.style.transform = angle ? `rotate(${angle}deg)` : "";

        // 让节点高度跟着文字走（Nodes 2.0 下节点尺寸由 DOM 主导，这里只做一次“够用”的设置）
        try {
            const h = Math.max(60, Math.round(fontSize * lines.length * 1.15 + pad * 2 + 24));
            node.setSize?.([Math.max(120, node.size?.[0] || 320), h]);
        } catch (_) { /* ignore */ }
    };

    node._xbLabelRender = render;
    render();

    // 2.0：给节点根元素打标记（Vue 重建 DOM 后需要重打）→ 配合上面的 CSS 关掉徽标
    const markRoot = () => {
        try {
            const root = el.closest?.("[data-node-id]") || node.domElement?.closest?.("[data-node-id]");
            if (root) root.setAttribute("data-xb-label-root", "1");
        } catch (_) { /* ignore */ }
    };
    markRoot();
    [60, 300, 1000].forEach((t) => setTimeout(markRoot, t));

    // 属性面板改 @fontSize / 通过其它入口改 properties 时没有统一回调 → 轻量轮询兜底（只在变化时重绘）
    let sig = "";
    node._xbLabelTimer = setInterval(() => {
        const p = node.properties || {};
        const s = [node.title, p.fontSize, p.fontColor, p.textAlign, p.backgroundColor, p.padding, p.borderRadius, p.angle].join("|");
        if (s !== sig) { sig = s; render(); }
    }, 300);

    // 双击贴纸 → 编辑文字（替代经典模式的 onDblClick）
    el.addEventListener("dblclick", (e) => {
        e.stopPropagation();
        const old = node.title || "";
        const val = prompt("输入文字（\\n 换行）:", old);
        if (val !== null && val !== old) {
            node.title = val || "机智罗";
            render();
        }
    });

    const origRemoved = node.onRemoved;
    node.onRemoved = function () {
        try { clearInterval(node._xbLabelTimer); } catch (_) { /* ignore */ }
        return origRemoved?.apply(this, arguments);
    };
}

// ---- 3. 注册扩展 ----
app.registerExtension({
    name: "XB_ToolBox.CanvasLabel",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_CanvasLabel") return;

        nodeData.title_mode = LiteGraph.NO_TITLE;
        nodeData.collapsable = false;
        // ✅ 照抄 rgthree-comfy 的 Label（web/comfyui/label.js 结尾 `Label.title_mode = LiteGraph.NO_TITLE`）：
        //    title_mode 必须是**类静态属性**才会被 LiteGraph / 前端读取。
        //    ⚠️ 只写 nodeData.title_mode 在 Nodes 2.0 不生效（实测：标题栏照样渲染，
        //    于是「节点名一行 + 贴纸文字一行」= 用户看到的双重文字）；写成静态后标题行高度 66 → 0。
        nodeType.title_mode = LiteGraph.NO_TITLE;
        nodeType.collapsable = false;

        // 属性面板定义（颜色不设 @ → 不会在画布上生成输入框）
        nodeData["@fontSize"]        = { type: "number", default: 40 };
        nodeData["@textAlign"]       = { type: "combo",  values: ["left", "center", "right"], default: "left" };
        nodeData["@padding"]         = { type: "number", default: 0 };
        nodeData["@borderRadius"]    = { type: "number", default: 0 };
        nodeData["@angle"]           = { type: "number", default: 0 };

        // ---- onNodeCreated ----
        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnNodeCreated?.apply(this, arguments);

            const p = this.properties = this.properties || {};
            p.fontSize        = p.fontSize ?? 40;
            p.fontColor       = p.fontColor ?? "#ffffff";
            p.textAlign       = p.textAlign ?? "left";
            p.backgroundColor = p.backgroundColor ?? "transparent";
            p.padding         = p.padding ?? 0;
            p.borderRadius    = p.borderRadius ?? 0;
            p.angle           = p.angle ?? 0;

            // 2.0 会用「节点显示名」预填 title → 贴纸文字跟着变成节点名（与标题栏重影）。
            // 只在「看起来仍是默认名」时换成默认文案（用户自己改过的文字不动）。
            const defaultTitles = [nodeData.title, nodeData.display_name, nodeData.name, this.type].filter(Boolean);
            if (!this.title || defaultTitles.includes(this.title) || /Canvas\s*Label|文字标签/.test(String(this.title))) {
                this.title = "机智罗";
            }
            // 照抄 rgthree：贴纸不可拉伸（尺寸由文字排版自动定），透明色用 8 位 hex 写法
            this.resizable = false;
            this.color = this.bgcolor = "#fff0";
            this.size = [320, 80];

            if (isNodes2()) {
                // 2.0：节点本体透明 + DOM 贴纸承载内容
                this.color = "transparent";
                this.bgcolor = "transparent";
                installDomLabel(this);
            }
        };

        // ---- draw()：自定义绘制（仅经典模式会被调用）----
        nodeType.prototype.draw = function (ctx) {
            if (!this.flags) this.flags = {};
            this.flags.allow_interaction = !this.flags.pinned;
            ctx.save();

            const p = this.properties || {};
            const fontSize     = Math.max(1, Math.min(800, +p.fontSize || 40));
            const fontColor    = p.fontColor || "#ffffff";
            const textAlign    = p.textAlign || "left";
            const bgColor      = p.backgroundColor || "";
            const pad          = +p.padding || 0;
            const borderRadius = +p.borderRadius || 0;
            const angleDeg     = parseInt(p.angle) || 0;

            ctx.font = fontSize + "px Arial";

            const raw = (this.title || "").replace(/\\n/g, "\n").replace(/\n*$/, "");
            const lines = raw.length === 0 ? [""] : raw.split("\n");

            let maxW = 1;
            lines.forEach(s => { const w = ctx.measureText(s).width; if (w > maxW) maxW = w; });
            this.size[0] = maxW + pad * 2;
            this.size[1] = fontSize * lines.length + pad * 2;

            if (angleDeg) {
                const cx = this.size[0] / 2, cy = this.size[1] / 2;
                ctx.translate(cx, cy);
                ctx.rotate((angleDeg * Math.PI) / 180);
                ctx.translate(-cx, -cy);
            }

            if (bgColor && bgColor !== "transparent") {
                ctx.fillStyle = bgColor;
                ctx.beginPath();
                if (ctx.roundRect) {
                    ctx.roundRect(0, 0, this.size[0], this.size[1], [borderRadius]);
                } else if (borderRadius > 0) {
                    const r = borderRadius, w = this.size[0], h = this.size[1];
                    ctx.moveTo(r, 0); ctx.lineTo(w - r, 0);
                    ctx.quadraticCurveTo(w, 0, w, r); ctx.lineTo(w, h - r);
                    ctx.quadraticCurveTo(w, h, w - r, h); ctx.lineTo(r, h);
                    ctx.quadraticCurveTo(0, h, 0, h - r); ctx.lineTo(0, r);
                    ctx.quadraticCurveTo(0, 0, r, 0);
                } else {
                    ctx.rect(0, 0, this.size[0], this.size[1]);
                }
                ctx.fill();
            }

            ctx.fillStyle = fontColor;
            ctx.textBaseline = "top";
            ctx.textAlign = textAlign;

            let tx = textAlign === "center" ? this.size[0] / 2 : textAlign === "right" ? this.size[0] - pad : pad;
            lines.forEach((line, i) => ctx.fillText(line || " ", tx, pad + i * fontSize));

            ctx.restore();
        };

        // ---- 关掉「节点徽标」（经典模式）----
        // 经典模式下前端会给**每个**节点画徽标（`ComfyNode.drawBadges` → `LGraphBadge`），内容是
        // `#<节点id> <来源/包名>`，实测本节点是 "#127 XB_ToolBox"。普通节点上它贴在标题栏里看不出问题，
        // 但在透明贴纸上就是凭空多出来的一行“节点名称”（用户报障点）→ 本类型直接不画。
        // 2.0 下徽标是 DOM，用 `[data-xb-label-root]` + CSS 兜底（见 ensureXbLabelStyle）。
        nodeType.prototype.drawBadges = function () {};

        // ---- 双击 → 属性面板（经典模式；2.0 由 DOM 元素上的 dblclick 处理文字编辑）----
        // 照抄 rgthree Label 的 `inResizeCorner() { return this.resizable; }`：贴纸不可拉伸
        nodeType.prototype.inResizeCorner = function () { return false; };
        const origDblClick = nodeType.prototype.onDblClick;
        nodeType.prototype.onDblClick = function (e, pos, gc) {
            if (origDblClick) { const r = origDblClick.apply(this, arguments); if (r !== undefined && r !== false) return r; }
            LGraphCanvas.active_canvas.showShowNodePanel(this);
            return true;
        };

        // ---- 右键菜单 ----
        const origMenu = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (_, options) {
            origMenu?.apply(this, arguments);
            const self = this;
            const refresh = () => {
                self._xbLabelRender?.();
                self.setDirtyCanvas(true, true);
                app.graph.setDirtyCanvas(true, false);
            };
            options.unshift(
                { content: "✏️ 编辑文字", callback: () => {
                    const old = self.title || "";
                    const val = prompt("输入文字（\\n 换行）:", old);
                    if (val !== null && val !== old) {
                        self.title = val || "机智罗";
                        refresh();
                    }
                }},
                // 2.0 下节点标题栏被隐藏（照抄 rgthree 的 title_mode），属性面板在右键菜单里也没有入口
                // → 标签的排版参数直接放进右键菜单，两个模式都能改
                { content: "🔤 字号…", callback: () => {
                    const cur = Number(self.properties.fontSize) || 40;
                    const val = prompt("字号（1~800）:", String(cur));
                    const num = Number(val);
                    if (val !== null && Number.isFinite(num)) { self.properties.fontSize = Math.max(1, Math.min(800, Math.round(num))); refresh(); }
                }},
                { content: "↔️ 切换对齐（左→中→右）", callback: () => {
                    const order = ["left", "center", "right"];
                    const i = order.indexOf(self.properties.textAlign || "left");
                    self.properties.textAlign = order[(i + 1) % order.length];
                    refresh();
                }},
                { content: "📐 内边距…", callback: () => {
                    const cur = Number(self.properties.padding) || 0;
                    const val = prompt("内边距 px（0~400）:", String(cur));
                    const num = Number(val);
                    if (val !== null && Number.isFinite(num)) { self.properties.padding = Math.max(0, Math.min(400, Math.round(num))); refresh(); }
                }},
                { content: "⭕ 圆角…", callback: () => {
                    const cur = Number(self.properties.borderRadius) || 0;
                    const val = prompt("圆角 px（0~400）:", String(cur));
                    const num = Number(val);
                    if (val !== null && Number.isFinite(num)) { self.properties.borderRadius = Math.max(0, Math.min(400, Math.round(num))); refresh(); }
                }},
                { content: "🔄 旋转角度…", callback: () => {
                    const cur = Number(self.properties.angle) || 0;
                    const val = prompt("旋转角度（度，负值=逆时针）:", String(cur));
                    const num = Number(val);
                    if (val !== null && Number.isFinite(num)) { self.properties.angle = Math.round(num); refresh(); }
                }},
                { content: "🎨 字体颜色…", callback: () => {
                    const inp = document.createElement("input");
                    inp.type = "color";
                    inp.value = self.properties.fontColor || "#ffffff";
                    inp.style.cssText = "position:fixed;top:50%;left:50%;width:1px;height:1px;opacity:0.01;z-index:99999;";
                    document.body.appendChild(inp);
                    inp.oninput = function () {
                        self.properties.fontColor = this.value;
                        refresh();
                    };
                    inp.onchange = function () {
                        self.properties.fontColor = this.value;
                        refresh();
                        if (document.body.contains(this)) document.body.removeChild(this);
                    };
                    requestAnimationFrame(() => inp.click());
                }},
                { content: "🖌️ 背景颜色…", callback: () => {
                    const inp = document.createElement("input");
                    inp.type = "color";
                    inp.value = self.properties.backgroundColor === "transparent" ? "#000000" : (self.properties.backgroundColor || "#000000");
                    inp.style.cssText = "position:fixed;top:50%;left:50%;width:1px;height:1px;opacity:0.01;z-index:99999;";
                    document.body.appendChild(inp);
                    inp.oninput = function () {
                        self.properties.backgroundColor = this.value;
                        refresh();
                    };
                    inp.onchange = function () {
                        self.properties.backgroundColor = this.value;
                        refresh();
                        if (document.body.contains(this)) document.body.removeChild(this);
                    };
                    requestAnimationFrame(() => inp.click());
                }}
            );
        };
    },
});
