/**
 * XB MiniMax ↔ HailuoH3 参数联动
 * ================================
 * 视频时长 (duration) 和画面比例 (aspect) 在两个节点间自动同步。
 * 修改任一个，另一个自动更新。节点可独立使用，同框则联动。
 */

import { app } from "../../scripts/app.js";

const MINIMAX_TYPE = "XB_llamaMiniMaxPreset";
const REF2VA_TYPE  = "XB_llamaMiniMaxRef2va";
const HAILUO_TYPE  = "XB_HailuoH3VideoParams";

// ── 格式转换 ────────────────────────────────────────────────────────

const RATIO_MAP = {
    "1:1":   "1:1 (Square)",
    "2:3":   "2:3 (Portrait Photo)",
    "3:2":   "3:2 (Photo)",
    "3:4":   "3:4 (Portrait Standard)",
    "4:3":   "4:3 (Standard)",
    "4:5":   "4:5 (Portrait Tall)",
    "5:4":   "5:4 (Landscape Tall)",
    "9:16":  "9:16 (Portrait Widescreen)",
    "16:9":  "16:9 (Widescreen)",
    "21:9":  "21:9 (Ultrawide)",
};
const RATIO_REV = {};
for (const [k, v] of Object.entries(RATIO_MAP)) RATIO_REV[v] = k;

function haiyoToMinimax(aspect)    { return RATIO_REV[aspect] || "16:9"; }
function minimaxToHaiyo(aspect)    { return RATIO_MAP[aspect] || "16:9 (Widescreen)"; }

// ── widget 派发 ─────────────────────────────────────────────────────

function dispatch(w, val) {
    if (!w) return;
    if (w.element) { w.element.value = val; w.element.dispatchEvent(new Event("input", { bubbles: true })); }
    if (w.callback) w.callback(val);
}

// ── 同步逻辑 ────────────────────────────────────────────────────────

function syncAll(graph) {
    if (!graph || !graph._nodes) return;

    const minimaxNodes = [];
    const haiyoNodes   = [];

    for (const node of graph._nodes) {
        if (node.type === MINIMAX_TYPE || node.type === REF2VA_TYPE)  minimaxNodes.push(node);
        if (node.type === HAILUO_TYPE)   haiyoNodes.push(node);
    }

    if (minimaxNodes.length === 0 || haiyoNodes.length === 0) return;

    // 从第一个 MiniMax 节点读取值
    const mmNode = minimaxNodes[0];
    const mmDur = mmNode.widgets?.find(w => w.name === "视频时长");
    const mmAsp = mmNode.widgets?.find(w => w.name === "画面比例");
    if (!mmDur || !mmAsp) return;

    const mmDurVal = Number(mmDur.value) || 8;
    const mmAspVal = mmAsp.value || "不指定 / Unspecified";

    // 跳过"不指定"
    if (mmAspVal === "不指定 / Unspecified") return;

    const ratioStr = mmAspVal.includes(" / ") ? mmAspVal : mmAspVal;
    const short = ratioStr; // 对于联动，直接用 dropdown 值中的比例部分

    // ── 同步到所有 Hailuo 节点 ──
    for (const hyNode of haiyoNodes) {
        if (hyNode._xb_linked_sync) continue;
        hyNode._xb_linked_sync = true;

        const hyDur = hyNode.widgets?.find(w => w.name === "duration");
        const hyAsp = hyNode.widgets?.find(w => w.name === "aspect_ratio");

        // 时长同步 (4-15 → clamp to valid range)
        if (hyDur) {
            const d = Math.max(1, Math.min(300, mmDurVal));
            if (Math.abs(Number(hyDur.value) - d) > 0.01) {
                hyDur.value = d;
                dispatch(hyDur, d);
            }
        }

        // 画幅比例同步
        // 从 MiniMax 的 dropdown 值中提取 "16:9" 之类
        if (hyAsp) {
            // 尝试匹配: 如果 mm 的值是 "16:9" 格式直接转, 否则从 dropdown 文本中提取
            let target = "";
            const mmClean = String(mmAspVal).trim();
            if (RATIO_MAP[mmClean]) {
                target = RATIO_MAP[mmClean];
            } else {
                // 尝试从 composite 格式 "Label / Label" 中提取
                for (const [k, v] of Object.entries(RATIO_MAP)) {
                    if (mmAspVal.includes(k)) { target = v; break; }
                }
            }
            if (target && hyAsp.value !== target) {
                hyAsp.value = target;
                dispatch(hyAsp, target);
            }
        }

        setTimeout(() => { hyNode._xb_linked_sync = false; }, 100);
    }
}

// ── 反向同步: Hailuo → MiniMax ─────────────────────────────────────

function syncHaiyoToMinimax(graph) {
    if (!graph || !graph._nodes) return;

    const minimaxNodes = [];
    const haiyoNodes   = [];

    for (const node of graph._nodes) {
        if (node.type === MINIMAX_TYPE || node.type === REF2VA_TYPE)  minimaxNodes.push(node);
        if (node.type === HAILUO_TYPE)   haiyoNodes.push(node);
    }

    if (minimaxNodes.length === 0 || haiyoNodes.length === 0) return;

    const hyNode = haiyoNodes[0];
    const hyDur = hyNode.widgets?.find(w => w.name === "duration");
    const hyAsp = hyNode.widgets?.find(w => w.name === "aspect_ratio");
    if (!hyDur || !hyAsp) return;

    const hyDurVal = Math.round(Number(hyDur.value)) || 8;
    const hyAspVal = hyAsp.value || "16:9 (Widescreen)";
    const mmRatio = haiyoToMinimax(hyAspVal);

    for (const mmNode of minimaxNodes) {
        if (mmNode._xb_linked_sync) continue;
        mmNode._xb_linked_sync = true;

        const mmDur = mmNode.widgets?.find(w => w.name === "视频时长");
        const mmAsp = mmNode.widgets?.find(w => w.name === "画面比例");

        // 时长同步
        if (mmDur) {
            const d = Math.max(4, Math.min(15, hyDurVal));
            if (Number(mmDur.value) !== d) {
                mmDur.value = d;
                dispatch(mmDur, d);
            }
        }

        // 画幅比例同步
        if (mmAsp && mmRatio) {
            if (mmAsp.value !== mmRatio) {
                mmAsp.value = mmRatio;
                dispatch(mmAsp, mmRatio);
            }
        }

        setTimeout(() => { mmNode._xb_linked_sync = false; }, 100);
    }
}

// ── 扩展注册 ────────────────────────────────────────────────────────

app.registerExtension({
    name: "xiaobai.minimax.hailuo.link",

    init() {
        // 最后一帧值缓存，用于检测变化
        let lastMinimaxDur  = null;
        let lastMinimaxAsp  = null;
        let lastHaiyoDur    = null;
        let lastHaiyoAsp    = null;

        setInterval(() => {
            if (!app.graph || !app.graph._nodes) return;

            // 检测 MiniMax / Ref2VA 节点变化
            for (const node of app.graph._nodes) {
                if ((node.type !== MINIMAX_TYPE && node.type !== REF2VA_TYPE) || !node.widgets) continue;
                const wDur = node.widgets.find(w => w.name === "视频时长");
                const wAsp = node.widgets.find(w => w.name === "画面比例");
                if (!wDur || !wAsp) continue;

                const durVal = Number(wDur.value) || 8;
                const aspVal = wAsp.value || "";

                if (lastMinimaxDur !== durVal || lastMinimaxAsp !== aspVal) {
                    lastMinimaxDur = durVal;
                    lastMinimaxAsp = aspVal;
                    syncAll(app.graph);
                }
            }

            // 检测 Hailuo 节点变化
            for (const node of app.graph._nodes) {
                if (node.type !== HAILUO_TYPE || !node.widgets) continue;
                const wDur = node.widgets.find(w => w.name === "duration");
                const wAsp = node.widgets.find(w => w.name === "aspect_ratio");
                if (!wDur || !wAsp) continue;

                const durVal = Math.round(Number(wDur.value)) || 8;
                const aspVal = wAsp.value || "";

                if (lastHaiyoDur !== durVal || lastHaiyoAsp !== aspVal) {
                    lastHaiyoDur = durVal;
                    lastHaiyoAsp = aspVal;
                    syncHaiyoToMinimax(app.graph);
                }
            }
        }, 300); // 每300ms轮询一次
    },
});
