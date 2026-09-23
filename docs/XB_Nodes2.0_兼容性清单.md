# XB_ToolBox × ComfyUI “Nodes 2.0” 兼容性排查清单

> 排查日期：2026-09-22
> 环境：ComfyUI `0.37.0` / `comfyui-frontend-package 1.52.7`（`Z:\AI_work\ComfyUI`）
> 方法：读前端产物源码（`GraphView-*.js` / `settingStore-*.js` / `core-*.js`）+ 运行实例 `/object_info` 全量节点比对（XB 节点 155 个）
> **状态：已实施（见第六节）** —— `XB_Dashboard_Zen` / `XB_DynamicBus` 已删除，其余节点已按 2.0 适配。
> 注：一～五节是最初的排查结论（保留作为依据）；六节是实际改了哪些文件。

---

## 一、Nodes 2.0 是什么（判定依据）

设置项：`Comfy.VueNodes.Enabled` → “Modern Node Design (Nodes 2.0)”（实验性，默认关，菜单里也有 `Experimental: Enable Nodes 2.0`）。
开启后节点由 **DOM/Vue 渲染**，不再走 LiteGraph 画布绘制。关键证据：

| 事实 | 源码位置（前端 1.52.7） |
| --- | --- |
| 开启后 `LGraphCanvas.drawNode()` **直接 early return**（只做 `_setConcreteSlots/arrange`） | `settingStore-*.js` |
| 节点级 `onDrawForeground` / `onDrawBackground` 只出现在**经典模式**的 DOM-overlay 代码里 | `GraphView-*.js`（2 处，同一段） |
| `onMouseDown` / `onDblClick` 只由**画布**的指针处理链触发 | `settingStore-*.js` |
| 画布 widget 仍会被画：`WidgetLegacy` 把 `widget.draw(ctx,node,w,y,h)` 画进独立 `<canvas>`，高度取 `widget.computeSize(w)[1]`，鼠标转发给 `widget.mouse` | `settingStore-*.js`（`__name:`WidgetLegacy``） |
| DOM widget 官方支持：`WidgetDOM` 把 `widget.element` 挂进节点 DOM | `GraphView-*.js`（`__name:`WidgetDOM``） |
| widget 类型映射表（含 aliases）：`button/string/int/float/boolean/combo/color/textarea/chart/imagecompare/galleria/markdown/textPreview/audiorecord/audioUI/load3D/…`；**未知类型 → 回退 WidgetLegacy** | `settingStore-*.js`（`EN=[[…]]` + `getComponent()`） |
| 可见性只看 `widget.options.hidden` / `widget.hidden`（`isWidgetVisible(){return!(this.collapsed||e.hidden||e.advanced&&!this.showAdvanced)}`） | `settingStore-*.js` |
| DOM widget 高度走 `computeLayoutSize()`：`options.getMinHeight()` 或 CSS 变量 `--comfy-widget-min-height`，缺省 **50px** | `settingStore-*.js`（`DOMWidgetImpl`） |
| 节点尺寸由 DOM 布局回写 node：`useLayoutSync().flushPendingChanges` 里 `r.size=[domW,domH]; r.onResize?.()` | `settingStore-*.js` |
| 官方 core 隐藏 widget 的正确姿势：`setWidgetHidden = (w,h)=>{ w.hidden=h; registry.getWidget(w.widgetId)?.options ? … : w.options.hidden=h }` | `core-*.js`（CreateBoundingBoxes / Painter） |

### 由此得出 5 条“兼容规则”

1. **节点级画布绘制在 2.0 下完全不执行**（`onDrawForeground` / `onDrawBackground` / 覆盖 `LGraphCanvas.prototype.drawNode` / `node.draw`）。
2. **节点级鼠标钩子不可用**（`onMouseDown` / `onDblClick` 的 `pos` 命中测试）。
3. **画布 widget（`addWidget(...,{draw})`）在 2.0 仍可用**（WidgetLegacy 兜底），但高度只认 `computeSize()[1]`。
4. **DOM widget 在 2.0 是首选**，但高度要用 `options.getMinHeight/getHeight`（或 `--comfy-widget-min-height` CSS 变量），`computeSize` 不再决定节点高度。
5. **`widget.type="hidden"` 在 2.0 不再隐藏**；必须 `w.hidden = true` **且** `w.options.hidden = true`（经典模式仍要靠 `type='hidden'`，所以两者都要写）。

---

## 二、需要改造的清单

### 🔴 A 组：功能直接失效（画布绘制 / 命中测试 → 必须改）

| 节点 | 文件 | 2.0 下的症状 | 建议改法 |
| --- | --- | --- | --- |
| `XB_CanvasLabel` | `js/xb_label.js` | 节点整体靠 `LGraphCanvas.prototype.drawNode` 劫持 + `nodeType.prototype.draw()` 绘制，`title_mode=NO_TITLE`；2.0 下变成默认外观的空节点，**文字/字体色/背景/圆角/角度/自动尺寸全丢**；双击打开属性面板（`LGraphCanvas.active_canvas.showShowNodePanel`）也失效 | 改为 `addDOMWidget` 承载文字（CSS 做颜色/字号/角度/圆角），标题与内容解耦；`onDblClick` 改成 DOM 内的 dblclick 或右键菜单 |
| `XB_DynamicBus` | `js/xb_wiring.js` | 端口类型文字 + `➕ ⭕ ➖` 三按钮画在 `onDrawForeground`，点击靠 `onMouseDown`+`getConnectionPos` 命中，双击改类型靠 `onDblClick`；2.0 下**按钮不显示也点不到**、类型文字消失、改类型无入口；`computeSize/onResize` 的高度锁定也不被采纳 | 三个动作改成真正的 `addWidget("button", …)`（或 3 个 DOM widget）；类型文字用 slot label / widget label 呈现 |
| `XB_Wan_RelayNode`、`XB_WanAnimate_RelayNode(_New)`、`XB_WanInfiniteTalk_RelayNode(_New/_MultiRef/_AllInOne)`、`XB_WanSCAIL_RelayNode_New` | `js/xb_relay_ui.js`、`js/xb_animate_relay_ui.js`、`js/xb_smart_ui.js` | ① 锁头蒙版画在 `onDrawForeground`；② `this.imgs=undefined` 阻止预览（`onDrawBackground`）失效 → 连了 `opt_end_image` 仍显示预览；③ `onMouseDown` 吃掉点击失效 → 被“锁定”的下拉/按钮仍可操作；④ `w.element.style.pointerEvents/opacity` 在 Vue 部件上不存在 | 锁定态改为：`w.hidden=true; w.options.hidden=true` 隐藏被接管部件（或 `options.disabled`），需要视觉提示就用一个 DOM widget 横幅；删除 `_img` 劫持与坐标命中 |
| `XB_Dashboard_Zen` | `js/xb_dashboard.js` | 代理节点靠 `proxyNode.imgs` / `onExecuted` 转发预览，2.0 预览由 DOM 组件渲染（读 `node.imgs`）→ 需实测；`setSize` / `LGraphGroup.size` 由 DOM 主导 | 验证镜像预览是否仍随动；否则改用 `node.imgs` 之外的标准预览通道或自带 DOM 预览容器 |

### 🟠 B 组：交互/外观降级（不致命，但体验受影响）

| 节点 | 文件 | 问题 | 建议 |
| --- | --- | --- | --- |
| `XB_ModelLoaderV1/V2/V3`、`XB_ModelLoaderV1/V2/V3_GGUF`、`XB_INT8GroupedLoraROCm`、`XB_DigitalHumanParams_Dual`、`XB_AudioSlicerV3`、`XB_ImagePromptPreset`、`XB_llamaStoryboardProcessorPro` | `js/xb_model_loader_v*.js`、`js/xb_int8_lora.js`、`js/xb_digital_human_dual.js`、`js/xb_audio_slicer_v3.js`、`js/xb_image_prompt_preset.js`、`js/xb_storyboard_processor.js` | 用 `w.type="hidden"; w.computeSize=()=>[0,-4]` 隐藏 LoRA 槽位/mutes/内部字段 → 2.0 只认 `hidden`，这些“隐藏”项会以 0 高度 legacy 画布部件残留（行高/错位） | 统一加一层工具函数：`hideWidget(w){w.type="hidden";w.hidden=true;w.options&&(w.options.hidden=true)}` / `showWidget` 还原；`xb_llama_pro.js` 里的 `widget._state.type` 写法可参考 |
| `XB_VideoParamsMaster`、`XB_ImageParamsMaster`、`XB_HailuoH3VideoParams`、`XB_llamaMiniMaxPreset`、`XB_llamaMiniMaxRef2va` | `js/xb_video.js`、`js/xb_hailuo_video.js`、`js/xb_minimax_hailuo_link.js` | 轮询 + `w.inputEl || w.element` 直改 DOM：2.0 里数字/下拉是 Vue 组件，`element` 不存在 → 赋值仍靠 `w.value=/callback()` 兜底（可用），但**只读、配色、`step` 等“表面美化”全丢** | 值同步保留；外观改走 `options`（如 `read_only`、`step`、`precision`），不要依赖 `element.style` |
| `XB_VideoLoader` | `js/xb_video_loader.js` | DOM 预览 widget 把指针事件转发给 `app.canvas._mousedown_callback / processSelect / snapToGrid`；2.0 下节点是 DOM，转发会造成选择/拖拽异常 | 用 `settings.getSettingValue("Comfy.VueNodes.Enabled")` 分支：2.0 下关闭转发 |
| `XB_NodeStatusSwitch`、`XB_ListDispatcher`、`XB_RoleSceneDispatcher`、`XB_llamaStoryboardProcessor`、`XB_INT8GroupedLoraROCm`、`XB_MSR`、`XB_Comic*`、`XB_NodeSizer` 覆盖的 ~80 个节点 | `js/xb_status_switch.js`、`js/xb_list_dispatcher.js`、`js/xb_role_scene_dispatcher.js`、`js/xb_storyboard_processor.js`、`js/xb_node_sizer.js`、`js/xb_comic.js` | `node.setSize(node.computeSize())` / `node.size[0]=…` / 覆盖 `computeSize`、`onResize` 做“最小宽度/最小高度锁定” → 2.0 下尺寸由 DOM 回写，锁定基本无效（可接受降级） | 最小宽度改用 `node.min_width`（已有做法）+ 容器 CSS `min-width` |
| `XB_ImagePromptPreset`（尺寸部分） | `js/xb_image_prompt_preset.js` | 已用 `getMinHeight` / `computeLayoutSize`（2.0 友好 👍），但 `cv.onDrawForeground` 逐帧 `widget.width` 补丁、`lockMinWidth` 在 2.0 是死代码 | 保留（无害）；宽度交给 DOM flex 即可 |
| （死代码）`XB_LlamaModelLoaderPro` | `js/xb_llama_pro.js` | 该节点名在 `/object_info` 中**不存在**（现名 `XB_llamaModelLoader`），扩展从不生效；其 `options.canvasOnly=true` 隐藏法在 2.0 里会让部件**整行消失**（`shouldRenderAsVue` 返回 false） | 要么把 `NODE_TYPE` 改为 `XB_llamaModelLoader` 并验证，要么删除该扩展 |

### 🟢 C 组：基本无需改动

- **纯后端节点（155 个里的大多数）**：抽样 `/object_info` 全量 XB 节点，widget 类型只有 `INT/FLOAT/BOOLEAN/STRING/COMBO`（`image_upload` 走 options），全部命中 2.0 映射表 → 自动正常渲染。
- **已用 `addDOMWidget` 的节点**：`XB_AudioSlicer(V1/V2/V3)`、`XB_DigitalHumanParams_Single/Dual`、`XB_WanDancerCombo`、`XB_ImagePromptPreset`、`XB_VideoLoader` → 官方支持（`WidgetDOM`）；建议补 `options.getMinHeight`（否则 2.0 下高度按缺省 50 / 内容自适应，可能过矮）。
- **`setDirtyCanvas` / `app.canvas.node_widget=null` / `LiteGraph.*` 常量 / `ComfyWidgets["STRING"]`**：2.0 下仍是安全调用（`app.canvas` 仍存在）。
- **`{"ui": {"text"/"gifs"/…}}`** 文本/媒体回显：core 已提供 2.0 对应部件（`textPreview` / 媒体预览），无需改动。

---

## 三、可直接复用的适配片段

```js
// 1) 隐藏 / 恢复部件（经典 + Nodes 2.0 通吃）
const hideWidget = (w) => {
  if (!w) return;
  w.__xb = { type: w.type, hidden: w.hidden, optHidden: w.options?.hidden, cs: w.computeSize };
  w.type = "hidden";                    // 经典模式
  w.hidden = true;                      // Nodes 2.0（节点级 isWidgetVisible）
  if (w.options) w.options.hidden = true; // Nodes 2.0（Vue 响应式路径）
  if (!w.__xb.cs) w.computeSize = () => [0, -4];
};
const showWidget = (w) => {
  if (!w || !w.__xb) return;
  const s = w.__xb;
  w.type = s.type; w.hidden = s.hidden;
  if (w.options) w.options.hidden = s.optHidden;
  if (s.cs) w.computeSize = s.cs; else delete w.computeSize;
  delete w.__xb;
};

// 2) DOM widget 高度（2.0 官方口径）
const dom = node.addDOMWidget("xb_ui", "custom", el, { serialize: false });
dom.options.getMinHeight = () => 280;      // 或给 el 设 CSS: --comfy-widget-min-height:280px
dom.computeLayoutSize = () => ({ minHeight: 280, minWidth: 0 });

// 3) 需要判断当前渲染模式时
import { app } from "../../scripts/app.js";
const isNodes2 = () => {
  try { return app.ui?.settings?.getSettingValue?.("Comfy.VueNodes.Enabled") === true; }
  catch { return false; }
};
```

---

## 四、建议的验证步骤

1. 设置 → `Comfy` → `Nodes 2.0` → 勾选 **Modern Node Design (Nodes 2.0)**（或菜单 `Experimental: Enable Nodes 2.0`），`Ctrl+F5`。
2. 逐个自测 A 组 4 类节点 + B 组模型加载器/参数主控：重点看**隐藏槽位是否残留**、**按钮能否点击**、**预览是否被正确屏蔽**、**DOM 面板高度是否够**。
3. A 组改完后回归经典模式（关掉该设置）确认没退化。
4. 只改 JS 无需重启 ComfyUI（`Ctrl+F5`）；若同时动了 Python 的 `INPUT_TYPES` 必须重启服务。

## 六、已实施改动（2026-09-22）

### 6.1 删除节点

| 节点 | 删除内容 |
| --- | --- |
| `XB_Dashboard_Zen` | `nodes_dashboard.py`（整文件）、`js/xb_dashboard.js`、`__init__.py` 导入/映射/显示名、`locales/zh/nodeDefs.json` 条目、`js/xb_node_sizer.js` 尺寸表、`.tracking` |
| `XB_DynamicBus` | `js/xb_wiring.js`、`nodes_wiring.py` 里的 `XB_DynamicBus` 类（`XB_UNetNameBroadcaster`/`XB_CLIPNameBroadcaster` 保留）、`__init__.py`、`locales/zh/nodeDefs.json`、`.tracking` |

> ⚠️ 两个节点的**副作用删除**：`XB_DynamicBus` 是“万能连线中继”，老工作流里用到它的地方重启后会变成 missing node；
> 且其 `AnyType("*")` 通配端口能力没有替代节点。请先用其它转发节点（如 `XB_Wan_ParamBus`）替换后再删除工作流里的旧实例。

### 6.2 新增：`js/xb_compat.js`（公共兼容层）

导出：`isNodes2()`、`liveWidget()`、`findWidgets()`、`refreshWidgets()`、`hideWidget()/showWidget()/setWidgetHidden()`、
`showWidgetAs()`、`slotSize()`、`sizeDomWidget()`、`styleWidgetInput()`、`setWidgetValue()`、`ensureBanner()`、`installRelayLock()`。

三个关键能力：

1. **隐藏/恢复部件双模式兼容**：经典 `type="hidden" + computeSize=[0,-4]`；Nodes 2.0 `hidden=true + options.hidden=true`。
   （`refreshWidgets()` 用 `node.widgets = node.widgets.slice()` 触发 2.0 的响应式重新映射）
2. **DOM widget 高度双模式兼容**：`options.getMinHeight` + `computeLayoutSize()`（2.0）+ `computeSize()`（经典）+ CSS 变量 `--comfy-widget-min-height`。
3. **写值三通道**：`element/inputEl` → `widget.value` → `callback`（Nodes 2.0 的 Vue 部件没有 element，必须落到 `value`）。

### 6.3 逐文件改动

| 文件 | 改动 |
| --- | --- |
| `js/xb_label.js` | **XB_CanvasLabel 双模式渲染**：经典模式保留原有 `drawNode` 劫持 + `node.draw()`；`isNodes2()` 时追加 DOM 贴纸 widget（CSS 做字号/颜色/对齐/背景/圆角/旋转）+ 节点底色透明，双击编辑文字改挂在 DOM 元素上（`onDblClick` 在 2.0 不触发），右键菜单两条通路共用 |
| `js/xb_relay_ui.js` | 删掉 `onDrawBackground` 抢 `imgs` / `onDrawForeground` 蒙版 / `onMouseDown` 拦截（2.0 全不执行）；改用 `installRelayLock`：连线接管时隐藏 `end_image_file`+上传按钮 + DOM 提示条 + 收走/归还 `node.imgs` |
| `js/xb_animate_relay_ui.js` | 同上（`独立参考图` 开关控制，提示条文案「参考图继承自总线全局图」） |
| `js/xb_smart_ui.js` | 改为复用 `installRelayLock`（靠 `node._xbRelayLock` 去重，不会与 `xb_relay_ui.js` 重复生效） |
| `js/xb_model_loader_v1/v2/v3(.js/_gguf.js)` 共 6 个 | LoRA 槽位的隐藏/显示改走 `hideWidget` / `showWidgetAs`（`type`+`hidden`+`options.hidden` 三写，并保留原 `computeSize`） |
| `js/xb_audio_slicer_v3.js`、`js/xb_digital_human_dual.js` | `mutes*_data` 隐形总线改 `hideWidget`；`total_display` 加 `options.read_only`；DOM widget 改 `sizeDomWidget` |
| `js/xb_audio_slicer(.js/_v1/_v2)`、`js/xb_wan_dancer_combo.js` | `duration_display` 加 `options.read_only`；DOM widget 改 `sizeDomWidget` |
| `js/xb_digital_human_single.js` | 同上限高/只读适配 |
| `js/xb_video.js`、`js/xb_hailuo_video.js`、`js/xb_minimax_hailuo_link.js` | 本地 `xb_dispatch`/`dispatch` 换成 `setWidgetValue`（原来只改 `element`，2.0 下值不落地）；显示字段加 `options.read_only` |
| `js/xb_list_dispatcher.js`、`js/xb_role_scene_dispatcher.js`、`js/xb_storyboard_processor.js` | 文本回显框加 `options.read_only`；`w.inputEl.xxx` 一律判空（2.0 的 Vue 部件可能没有 element，否则抛异常整个 `onExecuted` 中断） |
| `js/xb_video_loader.js` | 2.0 下不再把预览 DOM 的指针事件转发给 `app.canvas._mousedown_callback` 等（会使节点选择/拖拽错乱），并补 `computeLayoutSize()` 预览高度 |
| `js/xb_llama_pro.js` | **删除**：目标节点 `XB_LlamaModelLoaderPro` 已不存在（现由 JZL 包的 `JZL.LlamaModelLoaderPro` 提供），扩展永远不生效 |
| `.tracking` | 移除已删文件、加入 `js/xb_compat.js` |

### ⏱️ 追加：`XB_ImagePromptPreset` 两处 2.0 问题（2026-09-22 第二批）

| 文件 | 问题（用户报） | 修法 |
| --- | --- | --- |
| `js/xb_image_prompt_preset.js` | ① 「预设句」显示成**一行输入栏**（不是多行框）。根因：`showWidget()` 在没有存档时写 `w.type = (st && st.type) \|\| "text"` —— 加载「预设模式=三视图」的工作流时 `applyPresetTextVisibility()` 直接 show（从未 hide 过，`widgetState` 为空）→ 把原生的 `customtext` 多行框改成 `type="text"` 单行输入 ② 即便类型对了，2.0 里真正渲染的 textarea 是前端 `Textarea` 组件（class 带 `scrollbar-gutter-stable`），默认 `min-height:4rem` + `overflow-y:hidden` → 长预设句被截断、也拉不高 ③ `w3v.element` / `inputEl` 在 2.0 是**已脱离文档**的老元素（实测 `connected=false`、高 0），照它改样式等于没改 | ① `showWidget()` 改为「有存档才还原 type/computeSize」，无存档时只清 `hidden/options.hidden`；并新增 `snapshotWidget(w3v)` 在初始化时先存一份原样 ② 给该节点注入样式 `[data-xb-ipp] textarea[class*="scrollbar-gutter-stable"]{min-height:132px;max-height:360px;overflow-y:auto!important;resize:vertical}`（面板自己的预览框没有这个 class，不受影响），节点元素打 `data-xb-ipp="1"` 作 CSS 作用域锚点（Vue 重建 DOM 后会重打）③ `stylePresetTextBox()` 追加 `livePresetBox()`：按值匹配找到**活的** textarea 再设 inline 高/滚动/可拉高 |
| `nodes_image_prompt_preset.py` | 节点底部挂着「显示高级输入」开关，但里面只有 `internal_prompt` / `manager_settings` 两个**被前端面板隐藏**的内部字段 → 点了没有任何可见变化，纯碍眼 | 去掉这两个字段的 `advanced=True`（表面隐藏改由面板 `hideInternal()` 负责）→ 开关消失。⚠️ 改 Python 必须重启 ComfyUI；重启后用 `/object_info/XB_ImagePromptPreset` 核对 `advanced` 个数=0 |

实测（2.0）：预设句框为 `TEXTAREA`、高 **132px**（min 132 / max 360）、`overflow-y:auto`、可上下拉伸，灌 40 行后 `scrollHeight 668`、`scrollTop` 可移到 200；`显示高级输入` 开关**已消失**；内部字段仍隐藏；控制台 0 报错。经典模式（1.0）行为不变（预设句框仍 38px、可滚）。

### ⏱️ 追加：面板输入框跟随节点拉伸 + CanvasLabel 双重文字（2026-09-22 第三批）

| 文件 | 问题 | 修法 |
| --- | --- | --- |
| `js/xb_compat.js` | 2.0 下面板里 `flex:1 1 auto` 的输入框不会随节点拉伸变高（节点高度由 DOM 内容主导，框停在 min-height） | 新增公共助手 `installNodes2BoxResize(node, box, {min,max,deflt})`：默认给确定高度 → **拖节点尺寸手柄时按「指针位移 ÷ 画布缩放」实时改框高**（两个方向都跟手，避开「按节点高度反推会自激」的坑）→ 切回经典模式自动还原原样行内值。用法见 `js/xb_image_prompt_preset.js` |
| `js/xb_image_prompt_preset.js` | 用户报：拉伸节点只有上面「预设句」框变大，下面面板的提示词框不变 | 对面板的 `promptBox` 调用 `installNodes2BoxResize`（min/deflt = 300） |
| `js/xb_label.js` | 用户报：**双重文字**（节点名 + 贴纸文字），且 2.0 下属性面板没有入口 | ① ✅ **照抄 rgthree-comfy 的 `Label`**（`web/comfyui/label.js` 结尾 `Label.title_mode = LiteGraph.NO_TITLE`）：把 `title_mode` 设成**类静态属性** `nodeType.title_mode = NO_TITLE`。⚠️ 只写 `nodeData.title_mode` 在 2.0 **不生效**（实测标题栏照样渲染）→ 写成静态后标题行高度 66 → **0**，节点名不再显示、也不再与贴纸文字重影 ② 2.0 会用「节点显示名」预填 `title`，导致贴纸文字变成节点名 → 创建时若标题仍是默认名（`nodeData.title/display_name/name/type` 或含 `Canvas Label/文字标签`）就换回默认文案「机智罗」 ③ 照抄 rgthree 的 `resizable=false` + `inResizeCorner() => false`（贴纸不参与拉伸）④ 2.0 右键菜单没有「属性」入口 → 把标签排版参数放进右键菜单：`🔤 字号…`、`↔️ 切换对齐`、`📐 内边距…`、`⭕ 圆角…`、`🔄 旋转角度…`（连同原有 编辑文字/字体颜色/背景颜色） |

实测（2.0）：生图预设节点面板提示词框默认 **300px**，拖节点手柄 +150 / +150 / −300 屏幕像素后 → **568 → 703 → 971 → 434**（节点高同步 960 → 1100 → 1370 → 840），松手稳定、0 报错；CanvasLabel 节点 `titleRowH = 0`、右键菜单含全部 8 个标签设置项。

> ⚠️ 上面第三批里「可见文字只有贴纸一处」是**只看 DOM** 得出的结论，**是错的**——画布那一份 DOM 查询看不到（见 6.7）。

### ⏱️ 6.7 「两排字」真正根因：2.0 下**画布和 DOM 各画了一份文字**（2026-09-22 第四批，已修）

| 项 | 内容 |
| --- | --- |
| 现象 | 用户报「**还是显示两排字**」。DOM 断言（贴纸 1 个、可见文字 1 处、titleRowH=0）全部通过，但**元素截图**里同一行字前后错位叠了两层（重影） |
| 根因 | 我们的 `LGraphCanvas.prototype.drawNode` 劫持在 2.0 下只让**原实现** early-return，**劫持函数自己还在往下跑 `node.draw(ctx)`** → 文字被画到画布上；而 2.0 的画布**依旧渲染在 DOM 节点后面**（DOM 节点是叠加在上面的）⇒ 画布文字 + DOM 贴纸 = 错位重影 |
| 修法 | `js/xb_label.js`：`drawNode` 劫持里 `if (isNodes2()) return oldDrawNode.apply(this, arguments);` —— 2.0 下**一个字都不画**，全部交给 DOM 贴纸 |
| 附带修掉 | 删掉经典分支里「临时把 `node.title`/`constructor.title` 置空」的土办法：前端经典渲染器在标题为空时会**回退绘制 `#<节点id> <包名>`**（实测出现 "#124 XB_ToolBox"）→ 反而多一行小字。标题栏统一由 `title_mode = NO_TITLE` 类静态属性跳过（rgthree 同款） |
| 实测 | 2.0：元素截图 = **一行干净文字**、无重影 ✓；经典：贴纸文字正常（标题栏不画，只剩前端自带的小徽标）✓ |
| 教训 | ① **画布绘制的残留只有在像素里才看得见**——验证「重影/重复渲染」必须截图，不能只查 DOM ② 2.0 下画布仍在（`document.querySelectorAll('canvas').length = 2`），"2.0 不再用画布" 是错的，正确说法是"2.0 不再用画布画节点" ③ 任何劫持 `drawNode`/`draw` 的代码都要显式判断 `isNodes2()` 并**彻底空转** |

> 经典模式下贴纸节点上方仍会出现前端自带的 `#<id> <包名>` 小徽标——**属前端行为、非本包问题**：同版本 rgthree `Label (rgthree)` 在经典模式下同样出现（实测 "#125 frontend_"）。

### ⏱️ 6.8 经典模式「显示节点名称」= 前端节点徽标（2026-09-22 第五批，已去除）

| 项 | 内容 |
| --- | --- |
| 现象 | 用户报：**非 2.0（经典）状态会显示节点的名称**，要求去掉 |
| 真身 | 前端给**每个**节点画的徽标：`ComfyNode.drawBadges()` → `LGraphBadge`，文本 = `#<节点id> <来源/包名>`。实测本节点 `n.drawBadges(ctx)` 画出 **"#127 XB_ToolBox"**（基准确认：hook `fillText` 抓到该字符串）；普通节点上它贴在标题栏里不显眼，但在**透明贴纸**上就是凭空多出一行“节点名” |
| 修法 | `js/xb_label.js`：`nodeType.prototype.drawBadges = function () {};`（本类型不画徽标）+ 2.0 侧给节点根元素打 `data-xb-label-root="1"` 并注入 CSS  `[data-xb-label-root] [class*="badge" i]{display:none!important}` 兜底 |
| 实测 | 经典模式：`n.drawBadges(ctx)` 由 **["#127 XB_ToolBox"] → []** ✓，截图只剩贴纸文字；2.0：根元素标记到位、可见文字仅 1 处、0 报错 |
| 排查手法 | 用 `CanvasRenderingContext2D.prototype.fillText` 打钩 + `new Error().stack` 抓绘制方，直接定位到 `LGraphBadge.draw ← ComfyNode.drawBadges ← LGraphCanvas.drawNode`；比翻前端压缩产物快得多 |

### 6.4 未改（属可接受降级，与 2.0 无关功能）

* `node.setSize()/computeSize()` 类尺寸预设（`xb_node_sizer.js`、`xb_status_switch.js`、`xb_list_dispatcher.js`、`xb_int8_lora.js`、`xb_comic.js` …）：2.0 由 DOM 布局回写尺寸，这些锁尺寸只在经典模式下生效。
* `xb_comic.js` / `xb_msr.js` / `xb_cosyvoice3.js` / `xb_folder_picker.js` / `xb_master_param.js` / `xb_string_merge.js` / `xb_reference_any.js` 等：只用标准画布 widget（`button/combo/number`），在 2.0 下由 `WidgetLegacy` 正常渲染，无需改动。
* `xb_memory_viz.js`（硬件监控面板）：自建悬浮 DOM 面板，不进节点渲染链，不受影响。

### 6.5 验证

* 43 个业务 JS 全部通过 Node 语法检查（`--check`，0 失败）。
* **已同步到部署副本** `Z:\AI_work\ComfyUI\custom_nodes\XB_ToolBox` 并**重启 ComfyUI** 做了实测：
  * `/object_info` 里 `XB_Dashboard_Zen` / `XB_DynamicBus` 已消失，同文件的 `XB_UNetNameBroadcaster` 仍在 ✓
  * `/extensions` 清单已包含 `xb_compat.js`，不再包含 `xb_dashboard.js` / `xb_wiring.js` / `xb_llama_pro.js` ✓
  * 打开 `Comfy.VueNodes.Enabled`（Nodes 2.0）实测 5 个代表性节点，无任何 JS 报错：

    | 节点 | 实测结果 |
    | --- | --- |
    | `XB_ModelLoaderV1` | 35 个 widget：21 个被隐藏（`type=hidden` + `hidden=true` + `options.hidden=true`），14 个可见并渲染为 DOM 控件 ✓ |
    | `XB_Wan_RelayNode` | `xb_relay_banner` 提示条已创建且处于隐藏（未连线=未锁定），`end_image_file` 正常可见 ✓ |
    | `XB_CanvasLabel` | DOM 贴纸已挂载（element 在文档中、字号 40px、颜色 #fff）✓ |
    | `XB_AudioSlicerV1` / `XB_DigitalHumanParams_Single` | DOM 面板 widget 正常渲染、节点自动撑高 ✓ |

* ⚠️ 生效前提：必须**重启 ComfyUI**（Python 删节点 + `/extensions` 启动快照 + 新增 JS 文件），且要同步到部署副本。

### 6.6 补记：2.0 下「隐藏后不重渲染」的真正解法（2026-09-22，修复 JZL 包时发现）

排查 JZL 短剧导演台时定位到一个 **2.0 通用坑**：在 `onNodeCreated` 等早期时机改完 `options.hidden`，
**数据是对的但界面上 widget 依然可见**（Vue 侧只有「已注册 widget 的值发生变化」时才重算可见性）。

实测**无效**的全部手段：改 `type` / `hidden` / `options.hidden` / `_state.type` / `_state.hidden` / `_state.options.hidden`、
`node.widgets = node.widgets.slice()`、`setDirtyCanvas`、`graph.incrementVersion()`、`setSize()`、`onResize()`、延时重试。

实测**有效**的唯一手段（已写进 `js/xb_compat.js` 的 `refreshWidgets`，所有 XB 调用点自动受益）：

```js
node.graph.trigger("node:slot-label:changed", { nodeId: node.id, slotType: 2 });
```

这是前端内部事件，会让 Vue 侧重新抽取节点数据（`extractVueNodeData`）→ 立即重渲染 → 隐藏/显示立刻生效。
用 try/catch 包裹，前端版本变化导致事件消失时最坏退回旧行为，不会报错。

另一个 2.0 通用坑（面板类节点）：DOM 渲染下 `height:100%` 解析不到确定高度，`flex:1 1 auto` 的子区会跟着内容无限长高
（提示词框 59 → 972px、节点被撑爆、没有滚动条）——必须给子区**确定像素高度**（配合 `ResizeObserver` + `onResize` 同步），
且重排不能放在 `ResizeObserver` 回调里同步执行（会刷 `ResizeObserver loop completed with undelivered notifications`，丢到 `requestAnimationFrame` 即消失）。

> 同轮修复的另一个包见 `D:\AI_JZL\ComfyUI-JZL-MiniMax-H3\docs\NODES2_COMPAT.md`（含面板高度公式与实测数值）。
