import { app } from "../../scripts/app.js";

// 📝 架构规则表：彻底分离，绝不互相污染
// dragStep: 控制拖拽速度和箭头增量 (原生会乘0.1)
// snapRound: 控制吸附刻度
const MODE_CONFIGS = {
    "自由模式": { min: 0, max: 9999, dragStep: 10, snapRound: 1, precision: 0, def: 0 },
    "模型模式": { min: 0, max: 50, dragStep: 10, snapRound: 1, precision: 0, def: 0 },
    "编码模式": { min: 64, max: 3840, dragStep: 320, snapRound: 32, precision: 0, def: 64 },
    "解码模式": { min: 64, max: 3840, dragStep: 320, snapRound: 32, precision: 0, def: 64 },
    "比例模式": { min: 0.00, max: 1.00, dragStep: 0.1, snapRound: 0.01, precision: 2, def: 0.50 },
    "其他模式": { min: -99999.00, max: 99999.00, dragStep: 0.1, snapRound: 0.01, precision: 2, def: 1.00 }
};

app.registerExtension({
    name: "xiaobai.masterparams",
    async nodeCreated(node) {
        if (node.comfyClass === "XB_MasterParameter") {
            const wMode = node.widgets.find(w => w.name === "mode");
            const wValueOrig = node.widgets.find(w => w.name === "value");

            if (wMode && wValueOrig) {
                // 1. 记录原位置，确保替换时不会跑到最下面
                const valueWidgetIndex = node.widgets.indexOf(wValueOrig);

                // 2. 核心架构：预先制造 6 个纯正的原生 Widget (影子分身)
                // 它们在创建的一瞬间就拥有了最完美的 step 和 round，再也不会被篡改
                node._xb_shadow_widgets = {};
                for (const [mName, cfg] of Object.entries(MODE_CONFIGS)) {
                    const w = node.addWidget("number", "value", cfg.def, function(v){}, {
                        min: cfg.min, 
                        max: cfg.max, 
                        step: cfg.dragStep, 
                        round: cfg.snapRound, 
                        precision: cfg.precision
                    });
                    // 创建完立刻从面板上摘下来，放进后台仓库
                    node._xb_shadow_widgets[mName] = node.widgets.pop();
                }

                // 3. 定义无缝换挡 (组件热替换) 核心逻辑
                node.swapWidget = function(modeName) {
                    // 卸载当前面板上的 value 组件
                    const currIdx = node.widgets.findIndex(w => w.name === "value");
                    if (currIdx > -1) {
                        node.widgets.splice(currIdx, 1);
                    }

                    // 从仓库中取出对应的组件，精准安插回原来的位置
                    const targetW = node._xb_shadow_widgets[modeName];
                    if (targetW) {
                        targetW.name = "value"; // 必须叫 value，否则 Python 后端读不到
                        node.widgets.splice(valueWidgetIndex, 0, targetW);
                    }
                    app.graph.setDirtyCanvas(true, true);
                };

                // 4. 初次加载：立刻换上当前模式的专属组件
                node.swapWidget(wMode.value);
                
                // 5. 监听下拉菜单切换：不再修改数字，而是直接“换人”！
                const origModeCb = wMode.callback;
                wMode.callback = function(v) {
                    node.swapWidget(v);
                    if (origModeCb) return origModeCb.apply(this, arguments);
                };

                // 6. 完美兼容 ComfyUI 的工作流加载 (F5 刷新或拖入图片时恢复数据)
                const onConfigure = node.onConfigure;
                node.onConfigure = function(info) {
                    if (onConfigure) onConfigure.apply(this, arguments);
                    
                    if (wMode.value) {
                        node.swapWidget(wMode.value);
                        
                        // 强制将加载的数据覆盖到换上来的组件里
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