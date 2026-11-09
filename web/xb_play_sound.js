import { app } from "../../scripts/app.js";

// ============================================================
// XB_PlaySound — 播放声音
//   复刻自 ComfyUI-Custom-Scripts (pysssss) 的 PlaySound 节点
//   音频资源: js/assets/notify.mp3 (随本扩展一起分发，独立运行)
// ============================================================

const NODE_TYPE = "XB_PlaySound";

// 音频元素缓存: 同一文件复用，避免重复 new Audio 造成的内存抖动
const audioCache = new Map();

function getAudio(url) {
    const key = url.href;
    let audio = audioCache.get(key);
    if (!audio) {
        audio = new Audio(key);
        audioCache.set(key, audio);
    }
    return audio;
}

/** 队列是否已空 */
function isQueueEmpty() {
    const size = app?.ui?.lastQueueSize;
    // 前端未暴露该字段时，按"已空"处理 → 保证能响
    if (typeof size !== "number") return true;
    return size === 0;
}

/** 解析音频文件路径 */
function resolveAudioUrl(file) {
    let name = (file || "").trim();
    if (!name) name = "notify.mp3";

    // 完整网址: 直接使用
    if (/^https?:\/\//i.test(name)) return new URL(name);

    // 裸文件名: 指向本扩展的 assets 目录
    if (!name.includes("/")) name = "assets/" + name;

    // 相对于本 JS 文件解析 → /extensions/XB_ToolBox/assets/xxx
    return new URL(name, import.meta.url);
}

/** 按 name 取 widget (兼容 any 端口是否为 widget 的差异) */
function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

/** 判断 mode 是否为 "on empty queue" (索引 + 字面双重判定) */
function isOnEmptyQueue(wMode) {
    if (!wMode) return false;
    const values = wMode.options?.values;
    if (Array.isArray(values)) {
        const idx = values.indexOf(wMode.value);
        if (idx >= 0) return idx === 1; // ["always", "on empty queue"]
    }
    return String(wMode.value).includes("empty");
}

app.registerExtension({
    name: "XB_ToolBox.PlaySound",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = async function () {
            onExecuted?.apply(this, arguments);

            const wMode = getWidget(this, "mode");
            const wVolume = getWidget(this, "volume");
            const wFile = getWidget(this, "file");

            // ── "队列结束时播放" 判定 ──
            if (isOnEmptyQueue(wMode)) {
                if (!isQueueEmpty()) {
                    // 队列还在跑，等一下再确认一次（防止前端计数延迟）
                    await new Promise((r) => setTimeout(r, 500));
                    if (!isQueueEmpty()) return;
                }
            }

            // ── 解析并播放 ──
            let url;
            try {
                url = resolveAudioUrl(wFile?.value);
            } catch (e) {
                console.warn("[XB-PlaySound] 音频路径无效:", wFile?.value, e);
                return;
            }

            try {
                const audio = getAudio(url);
                audio.volume = Math.min(1, Math.max(0, Number(wVolume?.value ?? 0.5)));
                audio.currentTime = 0;
                const p = audio.play();
                if (p?.catch) {
                    p.catch((err) => {
                        console.warn(
                            "[XB-PlaySound] 浏览器拦截了自动播放，请先与页面交互一次:",
                            err?.message || err
                        );
                    });
                }
            } catch (e) {
                console.warn("[XB-PlaySound] 播放失败:", e);
            }
        };
    },
});
