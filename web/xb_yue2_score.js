/**
 * XB-BOX - 🎵 YuE2 乐谱工作台 — 前端面板
 * ============================================================
 * 节点：XB_YuE2ScoreWorkbench（后端 nodes_yue2_score.py，V1 经典 API）
 * 职责：按「操作」自动隐藏无关选项，让面板只显示当下真正生效的参数
 *   操作 = 用编辑框 / 编译事件 → 只显示「编辑框」
 *   操作 = 人声移到器乐轨        → 显示「和声处理」「重叠处理」
 *   其它操作（只查看 / 去掉和弦）→ 这三个都不显示
 *
 * ⚠️ 常量必须与 nodes_yue2_score.py 逐字一致；改后端文案要同步这里。
 */

import { app } from "../../scripts/app.js";
import { hideWidget, refreshWidgets, showWidget } from "./xb_compat.js";

const NODE_TYPE = "XB_YuE2ScoreWorkbench";
const OPERATION = "操作";
const EDITED = "编辑框";

// 仅「人声移到器乐轨」生效的两个选项
const MOVE_ONLY = ["和声处理", "重叠处理"];

// 与后端逐字一致的选项值
const OP_MOVE = "人声移到器乐轨 / Vocal to Ins";
const OP_EDITED = "用编辑框 / Use Edited";
const OP_COMPILE = "编译事件 / Compile Events";

function getWidget(node, name) {
    return (node?.widgets || []).find((w) => w?.name === name) || null;
}

function sync(node) {
    const operation = getWidget(node, OPERATION);
    if (!operation) return;
    const value = operation.value;

    const edited = getWidget(node, EDITED);
    if (edited) {
        if (value === OP_EDITED || value === OP_COMPILE) showWidget(node, edited);
        else hideWidget(node, edited);
    }

    for (const name of MOVE_ONLY) {
        const widget = getWidget(node, name);
        if (!widget) continue;
        if (value === OP_MOVE) showWidget(node, widget);
        else hideWidget(node, widget);
    }
    refreshWidgets(node);
}

app.registerExtension({
    name: "XB.YuE2ScoreWorkbench",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;
            if (!getWidget(self, OPERATION)) return result;

            requestAnimationFrame(() => sync(self));

            // 通道一：包裹 widget.callback（经典画布必然触发）
            const operation = getWidget(self, OPERATION);
            const origCb = operation.callback;
            operation.callback = function () {
                const value = origCb?.apply(this, arguments);
                sync(self);
                return value;
            };

            // 通道二：onWidgetChanged（Nodes 2.0 下 widget 对象可能被换成响应式代理）
            const origChanged = self.onWidgetChanged;
            self.onWidgetChanged = function (name, ...rest) {
                const value = origChanged?.apply(this, arguments);
                if (name === OPERATION) sync(self);
                return value;
            };

            // 工作流载入：只按当前值恢复可见性，不改任何参数
            const onConfigure = self.onConfigure;
            self.onConfigure = function (info) {
                const value = onConfigure?.apply(this, arguments);
                requestAnimationFrame(() => sync(self));
                return value;
            };

            return result;
        };
    },
});
