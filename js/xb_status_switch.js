/**
 * XB 节点状态开关 - ComfyUI 前端扩展
 * =====================================
 * 源自 ComfyUI-DaSiWa-Nodes 的 NodeStatusSwitch，适配 XB_ToolBox。
 *
 * 前端职责：
 *   1. 管理动态 target_XX 输入槽位（连接后自动扩展，最多99个）
 *   2. 队列时读取有效 enabled 值并设置目标节点的 mode
 *   3. 支持开关串联和实时镜像
 *
 * ComfyUI mode 值:
 *   0 = ALWAYS  (活跃)
 *   2 = NEVER   (静音/mute)
 *   4 = bypass  (绕过)
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const MODE_ACTIVE   = 0;
const MODE_MUTE     = 2;
const MODE_BYPASS   = 4;
const NODE_TYPE     = "XB_NodeStatusSwitch";
const TARGET_PREFIX = "target_";
const MAX_TARGETS   = 99;

function dlog(...args) {
    if (typeof window !== "undefined" && window.XB_SWITCH_DEBUG) {
        console.log("[XB Switch]", ...args);
    }
}

function getWidget(node, name) {
    return (node.widgets ?? []).find((w) => w.name === name);
}

function isTargetSlot(input) {
    return typeof input?.name === "string" && input.name.startsWith(TARGET_PREFIX);
}

function targetSlotName(n) {
    return `${TARGET_PREFIX}${String(n).padStart(2, "0")}`;
}

function countTargetSlots(node) {
    return (node.inputs ?? []).filter(isTargetSlot).length;
}

function isBoolWidget(w) {
    if (!w) return false;
    if (w.type === "toggle") return true;
    if (typeof w.type === "string" && w.type.toUpperCase().includes("BOOLEAN")) return true;
    if (typeof w.value === "boolean") return true;
    return false;
}

function findBoolWidget(node) {
    return node?.widgets?.find(isBoolWidget) ?? null;
}

function readBoolFromNode(node) {
    if (!node) return null;
    const w = findBoolWidget(node);
    if (w != null && typeof w.value === "boolean") return !!w.value;
    if (node.widgets) {
        for (const aw of node.widgets) {
            if (typeof aw?.value === "boolean") return !!aw.value;
        }
    }
    if (node.inputs) {
        for (const inp of node.inputs) {
            if (typeof inp?.widget?.value === "boolean") return !!inp.widget.value;
            if (typeof inp?.value === "boolean") return !!inp.value;
        }
    }
    if (Array.isArray(node.widgets_values)) {
        for (const v of node.widgets_values) {
            if (typeof v === "boolean") return v;
        }
        const first = node.widgets_values[0];
        if (first === "true" || first === true) return true;
        if (first === "false" || first === false) return false;
    }
    if (node.properties) {
        for (const v of Object.values(node.properties)) {
            if (typeof v === "boolean") return v;
        }
    }
    return null;
}

function resolveSourceNode(startNode, graph) {
    let current = startNode;
    const visited = new Set();
    while (current?.type?.includes?.("Reroute") && !visited.has(current.id)) {
        visited.add(current.id);
        const linkId = current.inputs?.[0]?.link;
        const link = linkId != null ? (graph.links?.[linkId] ?? graph._links?.get?.(linkId)) : null;
        if (!link) break;
        const allNodes = graph._nodes ?? graph.nodes ?? [];
        current = allNodes.find((n) => n.id === link.origin_id);
    }
    return current;
}

function readEnabled(switchNode, visited) {
    visited = visited ?? new Set();
    if (visited.has(switchNode.id)) return null;
    visited.add(switchNode.id);

    const graph = switchNode.graph ?? app.graph;
    const enabledInput = (switchNode.inputs ?? []).find((inp) => inp?.name === "enabled");

    if (enabledInput && enabledInput.link != null && graph) {
        const link = graph.links?.[enabledInput.link] ?? graph._links?.get?.(enabledInput.link);
        if (link) {
            const allNodes = graph._nodes ?? graph.nodes ?? [];
            const src = resolveSourceNode(allNodes.find((n) => n.id === link.origin_id), graph);
            if (src) {
                if (src.type === NODE_TYPE) {
                    const v = readEnabled(src, visited);
                    if (v != null) return v;
                } else {
                    const v = readBoolFromNode(src);
                    if (v != null) return v;
                }
            }
        }
    }
    const localW = getWidget(switchNode, "enabled");
    return localW != null ? !!localW.value : true;
}

function getTargetNodeIds(switchNode) {
    const graph = switchNode.graph ?? app.graph;
    if (!graph) return [];
    const ids = [];
    for (const input of switchNode.inputs ?? []) {
        if (!isTargetSlot(input)) continue;
        if (input.link == null) continue;
        const link = graph.links?.[input.link] ?? graph._links?.get?.(input.link);
        if (link && link.origin_id != null) {
            const allNodes = graph._nodes ?? graph.nodes ?? [];
            const src = resolveSourceNode(allNodes.find((n) => n.id === link.origin_id), graph);
            if (src) ids.push(src.id);
        }
    }
    return ids;
}

function sanitizeQueuePrompt(prompt) {
    if (!prompt || typeof prompt !== "object") return;
    for (const [nodeId, nodeData] of Object.entries(prompt)) {
        if (nodeData?.class_type !== NODE_TYPE) continue;
        delete prompt[nodeId];
    }
    for (const nodeData of Object.values(prompt)) {
        if (nodeData?.class_type !== NODE_TYPE) continue;
        if (!nodeData.inputs) continue;
        for (const key of Object.keys(nodeData.inputs)) {
            if (key.startsWith(TARGET_PREFIX)) delete nodeData.inputs[key];
        }
    }
}

function patchQueuePrompt() {
    if (api.__xbNodeStatusSwitchQueuePatched) return;
    const originalQueuePrompt = api.queuePrompt;
    api.queuePrompt = async function (index, prompt, ...args) {
        sanitizeQueuePrompt(prompt);
        return originalQueuePrompt.apply(this, [index, prompt, ...args]);
    };
    api.__xbNodeStatusSwitchQueuePatched = true;
}

function applySwitch(switchNode) {
    const triggerW = getWidget(switchNode, "trigger_on");
    const actionW  = getWidget(switchNode, "action");
    if (!triggerW || !actionW) return;

    const enabled        = readEnabled(switchNode);
    const triggerOn      = triggerW.value ?? "";
    const action         = actionW.value ?? "bypass";
    const activeWhenTrue = triggerOn.startsWith("true");
    const targetsActive  = activeWhenTrue ? enabled : !enabled;
    const actionMode     = action === "mute" ? MODE_MUTE : MODE_BYPASS;
    const targetMode     = targetsActive ? MODE_ACTIVE : actionMode;

    dlog("applySwitch", { nodeId: switchNode.id, enabled, triggerOn, action, targetsActive, targetMode });

    const graph = switchNode.graph ?? app.graph;
    if (!graph) return;
    const targetIds = getTargetNodeIds(switchNode);
    const allNodes  = graph._nodes ?? graph.nodes ?? [];
    for (const id of targetIds) {
        const target = allNodes.find((n) => n.id === id);
        if (target) target.mode = targetMode;
    }
}

function findDownstreamSwitches(switchNode, visited) {
    visited = visited ?? new Set();
    if (visited.has(switchNode.id)) return [];
    visited.add(switchNode.id);
    const graph = switchNode.graph ?? app.graph;
    if (!graph) return [];
    const allNodes = graph._nodes ?? graph.nodes ?? [];
    const linksMap = graph.links ?? graph._links;
    if (!linksMap) return [];
    const outIdx = (switchNode.outputs ?? []).findIndex((o) => o?.name === "enabled_out");
    if (outIdx < 0) return [];
    const outSlot = switchNode.outputs[outIdx];
    const linkIds = outSlot?.links ?? [];
    const found = [];
    const traceVisited = new Set();
    function traceDownstream(linkId) {
        if (traceVisited.has(linkId)) return;
        traceVisited.add(linkId);
        const link = linksMap?.[linkId] ?? linksMap?.get?.(linkId);
        const target = link ? allNodes.find((n) => n.id === link.target_id) : null;
        if (!target) return;
        if (target.type?.includes?.("Reroute")) {
            (target.outputs?.[0]?.links ?? []).forEach(traceDownstream);
        } else if (target.type === NODE_TYPE && target.inputs?.[link.target_slot]?.name === "enabled") {
            found.push(target, ...findDownstreamSwitches(target, visited));
        }
    }
    linkIds.forEach(traceDownstream);
    return found;
}

function applySwitchAndDownstream(switchNode) {
    applySwitch(switchNode);
    const downstream = findDownstreamSwitches(switchNode);
    for (const d of downstream) {
        const upstreamEnabled = readEnabled(switchNode);
        const localW = getWidget(d, "enabled");
        if (localW && localW.value !== upstreamEnabled) { localW.value = upstreamEnabled; }
        applySwitch(d);
    }
    const graph = switchNode.graph ?? app.graph;
    graph?.setDirtyCanvas?.(true, true);
}

function applyAllSwitches() {
    const allNodes = app.graph?._nodes ?? app.graph?.nodes ?? [];
    for (const n of allNodes) { if (n.type === NODE_TYPE) applySwitch(n); }
    app.graph?.setDirtyCanvas?.(true, true);
}

function patchGraphToPrompt() {
    if (app.__xbNodeStatusSwitchGraphToPromptPatched) return;
    const originalGraphToPrompt = app.graphToPrompt;
    app.graphToPrompt = async function (...args) {
        applyAllSwitches();
        const prompt = await originalGraphToPrompt.apply(this, args);
        sanitizeQueuePrompt(prompt);
        return prompt;
    };
    app.__xbNodeStatusSwitchGraphToPromptPatched = true;
}

patchQueuePrompt();
patchGraphToPrompt();

function syncTargetSlots(node) {
    const targetInputs = (node.inputs ?? []).filter(isTargetSlot);
    const connected = targetInputs.filter((inp) => inp.link != null).length;
    const desired = Math.min(connected + 1, MAX_TARGETS);
    while (countTargetSlots(node) < desired) {
        const nextNum = countTargetSlots(node) + 1;
        node.addInput(targetSlotName(nextNum), "*");
    }
    while (countTargetSlots(node) > desired) {
        const allInputs = node.inputs ?? [];
        for (let i = allInputs.length - 1; i >= 0; i--) {
            if (isTargetSlot(allInputs[i]) && allInputs[i].link == null) { node.removeInput(i); break; }
        }
    }
    node.setSize(node.computeSize());
}

function syncExternalToLocal(switchNode) {
    const enabledInput = (switchNode.inputs ?? []).find((inp) => inp?.name === "enabled");
    if (!enabledInput || enabledInput.link == null) return;
    const localW = getWidget(switchNode, "enabled");
    if (!localW) return;
    const graph = switchNode.graph ?? app.graph;
    if (!graph) return;
    const link = graph.links?.[enabledInput.link] ?? graph._links?.get?.(enabledInput.link);
    if (!link) return;
    const allNodes = graph._nodes ?? graph.nodes ?? [];
    const src = resolveSourceNode(allNodes.find((n) => n.id === link.origin_id), graph);
    if (!src) return;
    let externalValue;
    if (src.type === NODE_TYPE) { externalValue = readEnabled(src); }
    else { externalValue = readBoolFromNode(src); }
    if (externalValue == null) return;
    if (localW.value === externalValue) return;
    localW.value = externalValue;
    applySwitch(switchNode);
    graph.setDirtyCanvas?.(true, true);
}

let mirrorLoopRunning = false;
function mirrorFrame() {
    if (!mirrorLoopRunning) return;
    try {
        const allNodes = app.graph?._nodes ?? app.graph?.nodes ?? [];
        for (const n of allNodes) { if (n.type === NODE_TYPE) syncExternalToLocal(n); }
    } catch (_) {}
    requestAnimationFrame(mirrorFrame);
}
function startMirrorLoop() {
    if (mirrorLoopRunning) return;
    mirrorLoopRunning = true;
    requestAnimationFrame(mirrorFrame);
}
startMirrorLoop();

app.registerExtension({
    name: "XB_ToolBox.NodeStatusSwitch",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origCreated?.apply(this, arguments);
            const self = this;
            const hasOutput = (self.outputs ?? []).some((o) => o?.name === "enabled_out");
            if (!hasOutput) { self.addOutput("enabled_out", "BOOLEAN"); }
            if (countTargetSlots(self) === 0) { self.addInput(targetSlotName(1), "*"); }
            for (const w of self.widgets ?? []) {
                if (["enabled", "trigger_on", "action"].includes(w.name)) {
                    const origCb = w.callback;
                    w.callback = function (v) {
                        origCb?.apply?.(this, arguments);
                        applySwitchAndDownstream(self);
                    };
                }
            }
            const origConnect = self.onConnectionsChange;
            self.onConnectionsChange = function (type, index, slot, connected, link_info, ...rest) {
                origConnect?.apply?.(this, [type, index, slot, connected, link_info, ...rest]);
                syncTargetSlots(self);
                if (type === 1) applySwitchAndDownstream(self);
            };
        };
    }
});
