/**
 * XB MiniMax 分镜处理中心 — ComfyUI 前端扩展
 * =============================================
 * 重拍模式: 链式 mute + 文件选择器(默认打开故事输出目录)
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "XB_MiniMax_ShotFormatter";
const MODE_ACTIVE = 0;
const MODE_MUTE = 2;

function muteUpstream(node, reshootMode) {
    const inp = (node.inputs || []).find(i => i.name === "shot_text");
    const graph = node.graph ?? app.graph;
    if (!graph) return;
    const target = reshootMode ? MODE_MUTE : MODE_ACTIVE;

    if (inp?.link) {
        const link = graph.links?.[inp.link] ?? graph._links?.get?.(inp.link);
        if (link) {
            const src = graph.getNodeById?.(link.origin_id);
            if (src && src.mode !== target) {
                src.mode = target;
                const pgInput = (src.inputs || []).find(i => i.name === "shot_text" || i.name === "bus");
                if (pgInput?.link) {
                    const pgLink = graph.links?.[pgInput.link] ?? graph._links?.get?.(pgInput.link);
                    if (pgLink) {
                        const pgSrc = graph.getNodeById?.(pgLink.origin_id);
                        if (pgSrc && pgSrc.mode !== target) pgSrc.mode = target;
                    }
                }
                graph.setDirtyCanvas?.(true, true);
            }
        }
    }

    const busInp = (node.inputs || []).find(i => i.name === "bus");
    if (busInp?.link) {
        const bLink = graph.links?.[busInp.link] ?? graph._links?.get?.(busInp.link);
        if (bLink) {
            const bSrc = graph.getNodeById?.(bLink.origin_id);
            if (bSrc && bSrc.mode !== target) { bSrc.mode = target; graph.setDirtyCanvas?.(true, true); }
        }
    }
}

app.registerExtension({
    name: "XB_ToolBox.MiniMaxShotFormatter",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = orig?.apply(this, arguments);
            const self = this;

            const wMode = (self.widgets || []).find(w => w.name === "reshoot_mode");
            if (wMode) {
                const origCb = wMode.callback;
                wMode.callback = function (value) {
                    origCb?.apply?.(this, arguments);
                    muteUpstream(self, value);
                    const bt = self.widgets?.find(w => w.name === "选择要重拍的分镜");
                    if (bt?.inputEl) bt.inputEl.style.display = value ? "inline-block" : "none";
                };
            }

            // 文件选择按钮
            setTimeout(() => {
                const btn = self.addWidget("button", "选择要重拍的分镜", "📁 选择要重拍的分镜", async () => {
                    // 从 Python 后端获取默认目录
                    let defaultDir = "";
                    try {
                        const resp = await api.fetchApi("/xb_toolbox/minimax_default_dir", { method: "POST" });
                        const data = await resp.json();
                        defaultDir = data.dir || "";
                    } catch (e) {}

                    api.fetchApi("/xb_toolbox/choose_txt_file", {
                        method: "POST",
                        body: JSON.stringify({ default_dir: defaultDir }),
                        headers: { "Content-Type": "application/json" }
                    }).then(r => r.json()).then(data => {
                        if (data.path) {
                            let wPath = self.widgets?.find(w => w.name === "_reshoot_path");
                            if (!wPath) {
                                wPath = self.addWidget("string", "_reshoot_path", "", () => {});
                                wPath.inputEl.style.display = "none";
                            }
                            wPath.value = data.path;
                            wPath.inputEl.value = data.path;
                            app.graph?.setDirtyCanvas?.(true, true);
                        }
                    }).catch(() => {});
                });
                btn.inputEl.style.display = wMode?.value ? "inline-block" : "none";
            }, 200);

            return r;
        };
    },
    async loadedGraphNode(node) {
        if (node.type === NODE_TYPE) {
            setTimeout(() => {
                const wMode = (node.widgets || []).find(w => w.name === "reshoot_mode");
                if (wMode) muteUpstream(node, wMode.value);
            }, 300);
        }
    },
});
