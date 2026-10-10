/**
 * XB-BOX - 🎵 YuE2 风格提示 — 前端面板
 * ============================================================
 * 节点：XB_YuE2StylePrompt（后端 nodes_yue2_style.py，V1 经典 API）
 * 职责：
 *   ① ✨ 配方联动：切换「配方」即把全部维度回填成该配方的预设值
 *      （配方表来自后端 /xb_toolbox/yue2_recipes，与 yue2_styles.RECIPES 同一数据源，
 *        避免前后端两份表不同步）
 *   ② 手动改动任一维度 → 自动把「配方」切回「自定义」，否则后端会用配方值
 *      覆盖你的手改（nodes_yue2_style._apply_recipe 是给 API/无界面调用兜底的）
 *   ③ 无关维度自动隐藏：纯音乐时藏人声音色/唱法/效果；填了精确 BPM 时藏「速度」档位
 *
 * 只 import xb_compat.js 的通用助手，其余为模块私有函数。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { hideWidget, refreshWidgets, setWidgetValue, showWidget } from "./xb_compat.js";

const NODE_TYPE = "XB_YuE2StylePrompt";
const RECIPE = "配方";
const CUSTOM = "自定义 / Custom";

const LANGUAGE = "演唱语言";
const VOCAL = "人声编制";
const VOCAL_SUB = ["人声音色", "人声唱法", "人声效果"];
const BPM_WIDGET = "BPM数值";
const TEMPO = "速度";
const MAX_DURATION = "max_duration";
const SEED = "seed";

// 与后端 nodes_yue2_style.py / yue2_styles.py 逐字一致
const INSTRUMENTAL_LANG = "纯音乐 / Instrumental";
const INSTRUMENTAL_VOCAL = "无主唱 / No Vocals";

function getWidget(node, name) {
    return (node?.widgets || []).find((w) => w?.name === name) || null;
}

// ── 配方表：后端单一数据源 ─────────────────────────────────────────
let recipeCache = null;
let recipeFetch = null;

function loadRecipes() {
    if (recipeCache) return Promise.resolve(recipeCache);
    if (!recipeFetch) {
        recipeFetch = api.fetchApi("/xb_toolbox/yue2_recipes")
            .then((r) => r.json())
            .then((d) => { recipeCache = (d && d.recipes) || {}; return recipeCache; })
            .catch(() => { recipeCache = {}; return recipeCache; });
    }
    return recipeFetch;
}

let applying = false;

function applyRecipe(node) {
    const recipeWidget = getWidget(node, RECIPE);
    const label = recipeWidget ? recipeWidget.value : CUSTOM;
    if (!label || label === CUSTOM) return;
    const values = recipeCache ? recipeCache[label] : null;
    if (!values) return;
    applying = true;
    for (const name of Object.keys(values)) {
        const w = getWidget(node, name);
        if (w && w.value !== values[name]) setWidgetValue(w, values[name]);
    }
    applying = false;
}

// ── 可见性：无关维度直接隐藏，减少面板噪音 ──────────────────────
function syncVisibility(node) {
    const lang = getWidget(node, LANGUAGE);
    const vocal = getWidget(node, VOCAL);
    const instrumental = (lang && lang.value === INSTRUMENTAL_LANG)
        || (vocal && vocal.value === INSTRUMENTAL_VOCAL);

    for (const name of VOCAL_SUB) {
        const w = getWidget(node, name);
        if (!w) continue;
        if (instrumental) hideWidget(node, w);
        else showWidget(node, w);
    }

    const bpm = getWidget(node, BPM_WIDGET);
    const tempo = getWidget(node, TEMPO);
    if (bpm && tempo) {
        if (Number(bpm.value) > 0) hideWidget(node, tempo);
        else showWidget(node, tempo);
    }
    refreshWidgets(node);
}

function resetRecipeIfEdited(node, changedWidget) {
    if (applying || changedWidget === RECIPE) return;
    const recipeWidget = getWidget(node, RECIPE);
    if (recipeWidget && recipeWidget.value !== CUSTOM) {
        setWidgetValue(recipeWidget, CUSTOM);
    }
}

function syncAll(node, changedWidget) {
    resetRecipeIfEdited(node, changedWidget);
    syncVisibility(node);
}

app.registerExtension({
    name: "XB.YuE2StylePrompt",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;

            const recipeWidget = getWidget(self, RECIPE);
            if (!recipeWidget) return result;

            loadRecipes().then(() => {
                applyRecipe(self);
                syncVisibility(self);
            });

            const onRecipeChanged = () => {
                loadRecipes().then(() => {
                    applyRecipe(self);
                    syncVisibility(self);
                });
            };

            // 通道一：包裹 widget.callback（经典画布必然触发）
            for (const w of self.widgets || []) {
                if (!w || w.name === MAX_DURATION || w.name === SEED) continue;
                const origCb = w.callback;
                w.callback = function () {
                    const value = origCb?.apply(this, arguments);
                    if (w.name === RECIPE) onRecipeChanged();
                    else syncAll(self, w.name);
                    return value;
                };
            }

            // 通道二：onWidgetChanged（Nodes 2.0 下 widget 对象可能被换成响应式代理，
            // 只包 callback 有可能挂空；两个通道都是幂等操作，重复触发无副作用）
            const origChanged = self.onWidgetChanged;
            self.onWidgetChanged = function (name, ...rest) {
                const value = origChanged?.apply(this, arguments);
                if (name === RECIPE) onRecipeChanged();
                else if (name !== MAX_DURATION && name !== SEED) syncAll(self, name);
                return value;
            };

            // 工作流载入：只恢复可见性，不重放配方
            // （重放会用配方值覆盖用户已保存的手改值）
            const onConfigure = self.onConfigure;
            self.onConfigure = function (info) {
                const value = onConfigure?.apply(this, arguments);
                requestAnimationFrame(() => syncVisibility(self));
                return value;
            };

            return result;
        };
    },
});
