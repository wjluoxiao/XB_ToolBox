import { app } from "../../scripts/app.js";

// ============================================================
// XB_INT8GroupedLoraROCm — 动态 LoRA 槽位
// 选一个 → 自动弹出下一个 / 清空最后一个 → 自动收起
// ============================================================

const NODE_TYPE = "XB_INT8GroupedLoraROCm";
const MAX_SLOTS = 20;
const MIN_SLOTS = 2;

app.registerExtension({
    name: "XB_ToolBox.INT8LoraDynamic",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;

            const getLoraWidgets = () => (self.widgets || [])
                .filter(w => /^lora_\d+$/.test(w.name))
                .sort((a, b) => parseInt(a.name.split("_")[1]) - parseInt(b.name.split("_")[1]));

            const getLoRAValues = () => {
                const loras = getLoraWidgets();
                if (loras.length > 0 && Array.isArray(loras[0].options?.values)) {
                    return [...loras[0].options.values];
                }
                return ["None"];
            };

            const refreshSize = () => {
                const sz = self.computeSize();
                self.size[0] = sz[0];
                self.size[1] = sz[1];
                self.graph?.setDirtyCanvas?.(true, true);
            };

            self._int8AddLoraSlot = () => {
                const loras = getLoraWidgets();
                const lastIdx = loras.length ? parseInt(loras[loras.length - 1].name.split("_")[1]) : 0;
                if (lastIdx >= MAX_SLOTS) return;
                const newIdx = lastIdx + 1;
                if (self.widgets?.find(w => w.name === "lora_" + newIdx)) return;

                self.addWidget("combo", "lora_" + newIdx, "None", null, { values: getLoRAValues() });
                self.addWidget("number", "strength_" + newIdx, 1.0, null, {
                    min: -10.0, max: 10.0, step: 0.01
                });
                refreshSize();
            };

            self._int8RemoveLastSlot = () => {
                const loras = getLoraWidgets();
                if (loras.length <= MIN_SLOTS) return;
                const lastIdx = parseInt(loras[loras.length - 1].name.split("_")[1]);
                self.widgets = self.widgets.filter(w =>
                    w.name !== "lora_" + lastIdx && w.name !== "strength_" + lastIdx
                );
                refreshSize();
            };

            const origChange = self.onWidgetChanged;
            self.onWidgetChanged = function (name, value, oldValue, widget) {
                origChange?.apply(this, arguments);
                if (!name?.startsWith("lora_")) return;

                const idx = parseInt(name.split("_")[1]);
                const loras = getLoraWidgets();
                const lastIdx = loras.length ? parseInt(loras[loras.length - 1].name.split("_")[1]) : 0;

                if (value && value !== "None" && idx === lastIdx && lastIdx < MAX_SLOTS) {
                    self._int8AddLoraSlot();
                }

                if (value === "None" && idx === lastIdx && loras.length > MIN_SLOTS) {
                    self._int8RemoveLastSlot();
                }
            };

            return result;
        };
    }
});
