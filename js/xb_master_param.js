import { app } from "../../scripts/app.js";

// ============================================================
// XB_MasterParameter — 万能参数控制器 UI
// ============================================================

const MODE_CONFIGS = {
    "Free Mode": { min: 0, max: 9999, dragStep: 10, snapRound: 1, precision: 0, def: 0 },
    "Model Mode": { min: 0, max: 50, dragStep: 10, snapRound: 1, precision: 0, def: 0 },
    "Encode Mode": { min: 64, max: 3840, dragStep: 320, snapRound: 32, precision: 0, def: 64 },
    "Decode Mode": { min: 64, max: 3840, dragStep: 320, snapRound: 32, precision: 0, def: 64 },
    "Ratio Mode": { min: 0.00, max: 1.00, dragStep: 0.1, snapRound: 0.01, precision: 2, def: 0.50 },
    "Other Mode": { min: -99999.00, max: 99999.00, dragStep: 0.1, snapRound: 0.01, precision: 2, def: 1.00 }
};

app.registerExtension({
    name: "xiaobai.masterparams",
    async nodeCreated(node) {
        if (node.comfyClass === "XB_MasterParameter") {
            const wMode = node.widgets.find(w => w.name === "mode");
            const wValueOrig = node.widgets.find(w => w.name === "value");

            if (wMode && wValueOrig) {
                const valueWidgetIndex = node.widgets.indexOf(wValueOrig);

                node._xb_shadow_widgets = {};
                for (const [mName, cfg] of Object.entries(MODE_CONFIGS)) {
                    const w = node.addWidget("number", "value", cfg.def, function(v){}, {
                        min: cfg.min, 
                        max: cfg.max, 
                        step: cfg.dragStep, 
                        round: cfg.snapRound, 
                        precision: cfg.precision
                    });
                    node._xb_shadow_widgets[mName] = node.widgets.pop();
                }

                node.swapWidget = function(modeName) {
                    const currIdx = node.widgets.findIndex(w => w.name === "value");
                    if (currIdx > -1) {
                        node.widgets.splice(currIdx, 1);
                    }

                    const targetW = node._xb_shadow_widgets[modeName];
                    if (targetW) {
                        targetW.name = "value"; 
                        node.widgets.splice(valueWidgetIndex, 0, targetW);
                    }
                    app.graph.setDirtyCanvas(true, true);
                };

                node.swapWidget(wMode.value);
                
                const origModeCb = wMode.callback;
                wMode.callback = function(v) {
                    node.swapWidget(v);
                    if (origModeCb) return origModeCb.apply(this, arguments);
                };

                const onConfigure = node.onConfigure;
                node.onConfigure = function(info) {
                    if (onConfigure) onConfigure.apply(this, arguments);
                    
                    if (wMode.value) {
                        node.swapWidget(wMode.value);
                        
                        if (info && info.widgets_values && info.widgets_values.length > valueWidgetIndex) {
                            const savedVal = info.widgets_values[valueWidgetIndex];
                            const activeW = node.widgets.find(w => w.name === "value");
                            if (activeW && savedVal !== undefined) {
                                activeW.value = savedVal;
                            }
                        }
                    }
                };
            }
        }
    }
});