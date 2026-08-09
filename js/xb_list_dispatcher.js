/**
 * XB 列表分发 — 动态输出端口 + 显示框
 * =====================================
 * 复刻 kjnodes setupDynamicInputs 模式，改为输出端口管理。
 * "更新输出"按钮根据"输出数量"重建输出端口和显示框。
 */

import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const NODE_TYPE = "XB_ListDispatcher";
const MAX_OUTPUTS = 99;

// ── 复刻 kjnodes setupDynamicInputs，改为输出端口 ──
function setupDynamicOutputs(node) {
    const rebuild = () => {
        const wCount = node.widgets?.find(w => w.name === "输出数量");
        if (!wCount) return;
        const target = Math.min(MAX_OUTPUTS, Math.max(1, parseInt(wCount.value, 10) || 1));

        let current = (node.outputs || []).length;

        // 移除多余输出
        while (current > target) {
            const last = node.outputs[current - 1];
            if (!last.links || last.links.length === 0) {
                node.removeOutput(current - 1);
                current--;
            } else break;
        }

        // 添加缺失输出
        while (current < target) {
            const idx = current + 1;
            node.addOutput(`文本${idx}`, "STRING");
            current++;
        }

        // ── 同步显示框 ──
        let displays = (node.widgets || []).filter(w => w.name && w.name.startsWith("显示_"));
        while (displays.length > target) {
            const w = displays.pop();
            w.onRemove?.();
            const i = node.widgets.indexOf(w);
            if (i >= 0) node.widgets.splice(i, 1);
        }
        while (displays.length < target) {
            const idx = displays.length + 1;
            // 多行显示框：ComfyWidgets["STRING"] 支持 multiline 自动撑开
            const res = ComfyWidgets["STRING"](node, `显示_${idx}`, ["STRING", { multiline: true }], app);
            const dw = res.widget;
            if (dw.inputEl) {
                dw.inputEl.readOnly = true;
                dw.inputEl.style.backgroundColor = "#2a2a2a";
                dw.inputEl.style.color = "#bbbbbb";
                dw.inputEl.style.fontSize = "12px";
                dw.inputEl.style.border = "1px solid #444";
            }
            displays.push(dw);
        }

        node.setSize(node.computeSize());
        node.graph?.setDirtyCanvas?.(true, true);
    };

    // "更新输出" 按钮（防重复）
    if (!(node.widgets || []).find(w => w.name === "更新输出")) {
        node.addWidget("button", "更新输出", null, rebuild);
    }

    // 输出数量 callback 触发重建（API reload 时）
    const wCount = node.widgets?.find(w => w.name === "输出数量");
    if (wCount) {
        const origCb = wCount.callback;
        wCount.callback = function (value, canvas) {
            if (origCb) origCb.apply(this, arguments);
            if (!canvas) rebuild(); // bare = API reload, not interactive scrub
        };
    }

    return rebuild;
}

app.registerExtension({
    name: "XB_ToolBox.ListDispatcher",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            const rebuild = setupDynamicOutputs(this);

            // 用 configure 替代 setTimeout：widget 值此时已恢复（同 kjnodes 模式）
            const origConfigure = this.configure;
            this.configure = function (info) {
                if (origConfigure) origConfigure.apply(this, arguments);
                rebuild();
            };

            return r;
        };

        // Python 执行完毕 → ui.displays 回传
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (message?.displays) {
                const displays = (this.widgets || [])
                    .filter(w => w.name && w.name.startsWith("显示_"))
                    .sort((a, b) => parseInt(a.name.slice(3)) - parseInt(b.name.slice(3)));
                for (let i = 0; i < displays.length; i++) {
                    const v = i < message.displays.length ? message.displays[i] : "(空)";
                    if (displays[i].value !== v) displays[i].value = v;
                }
                this.setSize(this.computeSize());
                this.graph?.setDirtyCanvas?.(true, true);
            }
        };
    },

    async loadedGraphNode(node) {
        if (node.type !== NODE_TYPE) return;
        setTimeout(() => {
            const rebuild = setupDynamicOutputs(node);
            rebuild();
        }, 300);
    },
});
