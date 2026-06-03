import { app } from "../../scripts/app.js";

// ============================================================
// XB_CanvasLabel — 文字标签节点
// ============================================================

// ---- 1. 劫持 drawNode（隐藏默认边框/标题）----
const oldDrawNode = LGraphCanvas.prototype.drawNode;
LGraphCanvas.prototype.drawNode = function (node, ctx) {
    if (node.comfyClass !== "XB_CanvasLabel" && node.type !== "XB_CanvasLabel")
        return oldDrawNode.apply(this, arguments);

    node.bgcolor = node.color = "transparent";
    const savedTitle = node.title, savedCtor = node.constructor.title;
    node.title = node.constructor.title = "";
    const result = oldDrawNode.apply(this, arguments);
    node.title = savedTitle;
    node.constructor.title = savedCtor;
    if (node.draw) node.draw(ctx);
    return result;
};

// ---- 2. 注册扩展 ----
app.registerExtension({
    name: "XB_ToolBox.CanvasLabel",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_CanvasLabel") return;

        nodeData.title_mode = LiteGraph.NO_TITLE;
        nodeData.collapsable = false;

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

            this.title = this.title || "机智罗";
            this.size = [320, 80];
        };

        // ---- draw()：自定义绘制 ----
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

        // ---- 双击 → 属性面板 ----
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
            options.unshift(
                { content: "✏️ 编辑文字", callback: () => {
                    const old = self.title || "";
                    const val = prompt("输入文字（\\n 换行）:", old);
                    if (val !== null && val !== old) {
                        self.title = val || "机智罗";
                        self.setDirtyCanvas(true, true);
                        app.graph.setDirtyCanvas(true, false);
                    }
                }},
                { content: "🎨 字体颜色…", callback: () => {
                    const inp = document.createElement("input");
                    inp.type = "color";
                    inp.value = self.properties.fontColor || "#ffffff";
                    inp.style.cssText = "position:fixed;top:50%;left:50%;width:1px;height:1px;opacity:0.01;z-index:99999;";
                    document.body.appendChild(inp);
                    inp.oninput = function () {
                        self.properties.fontColor = this.value;
                        self.setDirtyCanvas(true, true);
                        app.graph.setDirtyCanvas(true, false);
                    };
                    inp.onchange = function () {
                        self.properties.fontColor = this.value;
                        self.setDirtyCanvas(true, true);
                        app.graph.setDirtyCanvas(true, false);
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
                        self.setDirtyCanvas(true, true);
                        app.graph.setDirtyCanvas(true, false);
                    };
                    inp.onchange = function () {
                        self.properties.backgroundColor = this.value;
                        self.setDirtyCanvas(true, true);
                        app.graph.setDirtyCanvas(true, false);
                        if (document.body.contains(this)) document.body.removeChild(this);
                    };
                    requestAnimationFrame(() => inp.click());
                }}
            );
        };
    },
});
