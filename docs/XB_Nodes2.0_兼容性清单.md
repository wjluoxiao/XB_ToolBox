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
| `XB_ModelLoaderV1/V2/V3_GGUF`、`XB_DigitalHumanParams_Dual`、`XB_AudioSlicerV3`、`XB_ImagePromptPreset`、`XB_llamaStoryboardProcessorPro` | `js/xb_model_loader_v*_gguf.js`、`js/xb_int8_lora.js`、`js/xb_digital_human_dual.js`、`js/xb_audio_slicer_v3.js`、`js/xb_image_prompt_preset.js`、`js/xb_storyboard_processor.js` | 用 `w.type="hidden"; w.computeSize=()=>[0,-4]` 隐藏 LoRA 槽位/mutes/内部字段 → 2.0 只认 `hidden`，这些“隐藏”项会以 0 高度 legacy 画布部件残留（行高/错位） | 统一加一层工具函数：`hideWidget(w){w.type="hidden";w.hidden=true;w.options&&(w.options.hidden=true)}` / `showWidget` 还原；`xb_llama_pro.js` 里的 `widget._state.type` 写法可参考 |
| `XB_VideoParamsMaster`、`XB_ImageParamsMaster`、`XB_HailuoH3VideoParams`、`XB_llamaMiniMaxPreset`、`XB_llamaMiniMaxRef2va` | `js/xb_video.js`、`js/xb_hailuo_video.js`、`js/xb_minimax_hailuo_link.js` | 轮询 + `w.inputEl || w.element` 直改 DOM：2.0 里数字/下拉是 Vue 组件，`element` 不存在 → 赋值仍靠 `w.value=/callback()` 兜底（可用），但**只读、配色、`step` 等“表面美化”全丢** | 值同步保留；外观改走 `options`（如 `read_only`、`step`、`precision`），不要依赖 `element.style` |
| `XB_VideoLoader` | `js/xb_video_loader.js` | DOM 预览 widget 把指针事件转发给 `app.canvas._mousedown_callback / processSelect / snapToGrid`；2.0 下节点是 DOM，转发会造成选择/拖拽异常 | 用 `settings.getSettingValue("Comfy.VueNodes.Enabled")` 分支：2.0 下关闭转发 |
| `XB_NodeStatusSwitch`、`XB_ListDispatcher`、`XB_RoleSceneDispatcher`、`XB_llamaStoryboardProcessor`、`XB_MSR`、`XB_Comic*`、`XB_NodeSizer` 覆盖的 ~80 个节点 | `js/xb_status_switch.js`、`js/xb_list_dispatcher.js`、`js/xb_role_scene_dispatcher.js`、`js/xb_storyboard_processor.js`、`js/xb_node_sizer.js`、`js/xb_comic.js` | `node.setSize(node.computeSize())` / `node.size[0]=…` / 覆盖 `computeSize`、`onResize` 做“最小宽度/最小高度锁定” → 2.0 下尺寸由 DOM 回写，锁定基本无效（可接受降级） | 最小宽度改用 `node.min_width`（已有做法）+ 容器 CSS `min-width` |
| `XB_ImagePromptPreset`（尺寸部分） | `js/xb_image_prompt_preset.js` | 已用 `getMinHeight` / `computeLayoutSize`（2.0 友好 👍），但 `cv.onDrawForeground` 逐帧 `widget.width` 补丁、`lockMinWidth` 在 2.0 是死代码 | 保留（无害）；宽度交给 DOM flex 即可 |
| `XB_llamaModelLoaderPro` | `js/xb_llama_model_loader_pro.js` | **已恢复（2026-10-08）**：Pro 节点重新落地到 XB（复刻 JZL 的 `JZL_LlamaModelLoaderPro`），类名 `XB_llamaModelLoaderPro`、显示名 `XB-llama - 🚀 模型加载Pro`。中文条目已由旧键 `XB_LlamaModelLoaderPro` 更名为 `XB_llamaModelLoaderPro`，并在末尾补上 `backend` / `gpu_device`。隐藏法实测在 2.0 下两种状态（折叠/展开）均正常 | 保持同步；`scale` 等已由 DOM 主导，无需额外处理 |

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
| `js/xb_llama_model_loader_pro.js` | **新建（2026-10-08）**：配套 `XB_llamaModelLoaderPro`（复刻 JZL 的模型加载 Pro，节点双输出 Llama模型 + 推理参数）。旧版曾删除的 `js/xb_llama_pro.js` 不再恢复 |
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
    | ~~`XB_ModelLoaderV1`~~ | ⛔ 该节点已于 2026-10-08 按用户要求删除（连同 V2/V3 与对应 `js/xb_model_loader_v1~v3.js`）；仅保留 `XB_ModelLoaderV1/V2/V3_GGUF` |
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

---

## 七、2026-10-17 复检（ComfyUI 0.41.2 / 前端 1.55.17）——DOM widget 行高机制变更

> 环境：`Comfy.VueNodes.Enabled = true`（Nodes 2.0）/ `comfyui-frontend-package 1.55.17`
> 方法：在运行实例里逐个创建 14 个「有 DOM widget」的节点，量 `节点模型高度 vs 节点 DOM 根部高度 vs widget 高度 / 内部行高`

### 7.1 新版前端的行高规则（关键变更，替代第一节的旧结论）

第一节写的「DOM widget 高度走 `computeLayoutSize().minHeight`」在 **1.55.x 已不成立**。现行源码事实：

| 事实 | 位置（前端 1.55.17） |
| --- | --- |
| `deriveWidgetRenderState(e) => { hasLayoutSize: typeof e.computeLayoutSize === 'function' }` | `settingStore-*.js` |
| `WidgetGrid`：`rowSize = (shouldExpand(type) || hasLayoutSize) ? 'auto' : 'min-content'`，并写进 `grid-template-rows` | `settingStore-*.js` |
| `DOMWidgetImpl` 原型上本就有 `computeLayoutSize` ⇒ 我们所有 DOM widget 的 `hasLayoutSize` **恒为 true** ⇒ 行高恒为 `auto` = **内容最大高度** | `settingStore-*.js` |
| `WidgetDOM` 包装层是 `<div class="flex flex-col *:flex-1">`，容器被 `flex:1` 拉满；祖先链全是 `min-height:auto` | `GraphView-*.js` |

⇒ **`options.getMinHeight` / `computeLayoutSize().minHeight` 不再决定行高**；
`height:100%` + 内容都是绝对定位/隐藏元素 ⇒ 内容高度 ≈ 0 ⇒ **行高塌成 1~2px，面板整个看不见**。

### 7.2 本轮修掉的 BUG：`XB_ShenBi` 显示窗塌成 1.33px

| 项 | 内容 |
| --- | --- |
| 现象 | Nodes 2.0 下「🖌️ 神笔」的显示窗只剩一行提示文字（`width`/`height:100%` 的容器被压成 **1.33px**），预览图看不见；经典模式正常 |
| 根因 | 显示窗依赖第一节的旧规则（只给 `computeLayoutSize`，让旧版 `_arrangeWidgets` 把剩余空间分给它）。1.55.17 下该机制不存在，行高 = 内容高度；显示窗内容是 `<img style="height:100%">`（未加载时 0）+ 绝对定位角标 ⇒ 内容高度 ≈ 0 |
| 修法 | `js/xb_shenbi.js`：`if (panel)` 块里调用公共助手 `installNodes2BoxResize(node, panelBox, {min: PANEL_MIN, max: 4000, deflt: PANEL_EXTRA})` —— 2.0 下给显示窗**确定像素高度**（默认 180px），并随节点尺寸手柄实时跟随；经典模式该助手自动空转（保留原弹性逻辑） |
| 实测 | 行高 `1.33px → 180px`、显示窗 `0 → 179px`、`__xbBoxResizeHooked = true`、截图确认白色画布窗口正常显示；经典模式行为不变 |
| 踩的坑 | 第一次写成 `installNodes2BoxResize(node, box, …)` —— `box` 是 `try` 块里的 `const`，在那个作用域外是 `ReferenceError`，被 `catch` 吞掉 ⇒ 看起来"改了没生效"。改为外层已保存的 `panelBox`（回退 `panel.element`）后立即生效。**教训：静默吞异常必须配合日志，否则会把作用域错误伪装成"前端不配合"** |

### 7.3 本轮复检结论（14 个 DOM widget 节点）

| 节点 | DOM widget 高度 | 结论 |
| --- | --- | --- |
| `XB_ShenBi` | 0 → **179** | ✅ 本轮修复（见 7.2） |
| `XB_AudioSlicer` | 0 | ✅ 正常：未选音频时播放器 `display:none`（设计如此） |
| `XB_VideoLoader` | 0 | ✅ 正常：与官方 `LoadVideo` 空态一致（实测官方也是 0），载入视频后由 `<video>` 固有比例撑开 |
| `XB_AudioSlicerV1/V2/V3` | 92 / 193 / 267 | ✅ 内容自定高度，行高稳定 |
| `XB_DigitalHumanParams_Single/Dual` | 92 / 267 | ✅ 同上 |
| `XB_ImagePromptPreset / Pro / XB_QwenPromptPreset` | 413 / 614 / 670 | ✅ 已走 `installNodes2BoxResize` |
| `XB_llamaPromptReverse` | 449 | ✅ 同上 |
| `XB_CanvasLabel` | 80 | ✅ 贴纸文字正常 |
| `XB_WanDancerCombo` | 92 | ✅ 同上 |
| `XB_ModelLoaderV1_GGUF`（33 widget / 12 行） | — | ✅ `hideWidget` 生效：隐藏项**不占行**（旧 B 组问题已解决） |

### 7.4 已知但**不需要改**的现象

* **节点 DOM 根部比 `node.size[1]` 高**（如 `XB_AudioSlicerV3` 466 → 851）：2.0 把输入/参数渲染成 DOM 行，行高比画布版高；**官方节点同样如此**（实测 KSampler +54、CheckpointLoaderSimple +58、EmptyLatentImage +66）。属前端行为，且可见卡片高度由 DOM 决定，不影响交互。
* 隐藏内部字段（`internal_prompt` / `manager_settings` / `three_view_text`）高度为 0：正确（已 `hideWidget`）。
---

## 八、2026-10-17 复检（神笔专用）

**问题 1：神笔节点刷新瞬间会多出一个「官方图片预览窗」。**

* 成因：2.0 的官方预览不在 `node.widgets` 里，而是 Vue 的节点内容组件渲染的 `.image-preview`；
  它由 `NodeContent` 的 `media` 计算属性驱动，源码条件是
  `if (!node || !output?.images?.length || node.hideOutputImages || …) return;`。
  早前用 CSS `display:none` 隐藏 ⇒ 属性/CSS 生效前会有一次渲染（闪一下），而且 DOM 里仍然存在。
* 修法：给节点打 **`node.hideOutputImages = true`**（官方 `ImageCompositor` 用的就是同一个开关），
  在 `setupNode`（`onNodeCreated`）与 `onConfigure` 里各设一次 ⇒ **官方预览根本不会被渲染**，
  DOM 里查不到 `.image-preview`，也不再需要 CSS 补丁。

**问题 2：神笔显示窗在 2.0 下是固定 180px，不能跟着节点变大（对比官方 Create Bounding Boxes 的编辑框）。**

* 修法：改用新的 `bindNodes2BoxFill(node, box, { min })`（`js/xb_compat.js`）——把显示窗高度绑到前端
  自带的 CSS 变量 `--node-height`（= 节点高度 + 固定余量），减去一次性标定出的 chrome：
  `height = calc(var(--node-height, 3000px) - K)`。纯 CSS 跟随，拖大拖小都跟手（不会「只能变大不能变小」）。
* 实测（Nodes 2.0）：节点 700 → 显示窗 **361**；节点 420 → **132**；经典模式还原 `height:100%` 原布局。

保留：`XB_ImagePromptPreset` 等仍用 `installNodes2BoxResize`（按指针位移改固定 px），行为不变。

---

## 九、2026-10-17 复检（文字标签 XB_CanvasLabel）

用户报的三个现象其实同源：**DOM 贴纸的生命周期只在 onNodeCreated 里决定了一次**。

| 现象 | 根因 | 修法 |
| --- | --- | --- |
| Nodes 2.0 下节点拖不动 | 整块节点就是一张贴纸（`pointer-events:auto`），而 2.0 的节点拖拽由 `useNodePointerInteractions` 处理、只要 `pointerdown` 落在 widget 行上就不再拖（官方 Note 节点拖正文区同样不动） | 贴纸 + 官方 `WidgetDOM` 行 wrapper 都设 `pointer-events:none`，事件直接命中节点根元素 ⇒ 抓哪都能拖 |
| 关掉 2.0 变双层文字 | 切回经典时 DOM 贴纸残留（官方 `WidgetLegacy` 还会把它重新挂到画布容器），画布这边也照常画一遍 | 检测到 `isNodes2()` 变 false → 摘掉 DOM widget + 删掉残留元素（含被挪到画布容器里的），节点色恢复 `#fff0` |
| 打开 2.0 文字消失 | 创建节点时是经典模式 → 从没建过贴纸；画布侧又 early-return | 检测到变成 2.0 → 现场建贴纸（模式判定放进 300ms tick，且要求"稳定两拍"再切换，避免设置异步回写导致刚拆又装） |

顺带修掉两处隐患：

* 双击编辑原本挂在贴纸元素上（贴纸已穿透后收不到事件）→ 改挂**节点根元素**；
  判断"是否在输入框里"不能用 `closest()`（画布容器祖先链上有 `contenteditable`，会一路匹配到它），只判 `e.target` 自身标签。
* `prompt()` 在部分环境会抛 `prompt() is not supported` → 统一走 `askText()` 包一层 try/catch。

实测（Nodes 2.0）：贴纸 `pointer-events:none`；拖拽 200,200 → 230,220 生效；双击改字生效；
切经典：widget 摘除、`[data-xb-label]` 计数 0、节点尺寸由 `draw()` 重新算出（单层文字）；
再切回 2.0：贴纸自动重建、计数 1、可继续拖拽。

---

## 十、2026-10-17 复检（宽高步长：点「减小」不生效）

**现象**：`XB-BOX - 🖼️ 生图提示词预设` 的宽度/高度点右侧「增加」能变大，点左侧「减小」数值弹回原值、看起来"缩不小"。

**根因**（前端源码 `WidgetInputNumber-*.js`）：

```js
function useNumberStepCalculation(options, precision) {
  if (options.step2 !== undefined) return options.step2;   // ← 优先用 step2
  if (options.step !== undefined && options.step > 10) return options.step / 10;
  ...
}
```

2.0 的 +/- 按钮步长取 **`step2`**，而各节点只同步了 `options.step`（空 latent 类型的官方步长，如 Qwen-image / Hunyuan = 32），
`step2` 仍是注册时的 16。于是：点减小 → 1024−16＝1008 → JS 按 32 归一到 **1024**（弹回原值）；
点增加 → 1024+16＝1040 → 归一到 **1056**（确实变大）。所以才有"只能放大不能缩小"。

**修法**：所有「按类型/比例同步步长」的地方同时写 `step2`：

| 文件 | 说明 |
| --- | --- |
| `js/xb_image_prompt_preset.js`、`js/xb_image_prompt_preset_pro.js`、`js/xb_qwen_prompt_preset.js` | 空 latent 类型 → 宽高步长（8/16/32） |
| `js/xb_video.js` | 画幅比例 → 宽高步长；帧数 → 8/1 |
| `js/xb_digital_human_single.js`、`js/xb_digital_human_dual.js` | 画幅比例 → 宽高步长 |

**实测**（Nodes 2.0）：
* 生图提示词预设 + `Hunyuan`（步长 32）：`step=step2=32`，减小 1024 → 992 → 960 → 928，增加回到 960 → 992。
* Qwen2.1 提示词预设：`step=step2=32`，减小 1024 → 992 → 960 → 928。
* 视频参数主控（Free，步长 1）：减小 480 → 479 → 478 → 477。

---

## 十一、2026-10-17 复检（提示词框没贴住节点下边缘，底部留白）

**现象**：`生图提示词预设` / `Pro` / `Qwen2.1提示词预设` 把节点拉高后，提示词输入框不再变高，
面板底部（紫色区域）出现一片空白。

**根因**：原先只把「提示词框」用 `installNodes2BoxResize` 钉成固定 px（默认 300，拖拽时按指针位移改）。
框自己是变高了，但**容器高度仍由内容决定**（2.0 里 DOM widget 所在 grid 行是 `auto`），
节点比内容高出来的那部分就变成容器下方的空白。

**修法**：新增 `bindNodes2NodeFill(node, container, { min, bottomPad })`（`js/xb_compat.js`），
按 CSS 变量给出**容器**的确定高度：

```
容器 height/max-height = calc(var(--node-height, 3000px) - (容器顶部偏移 + 底部留白))
```

* `--node-height` 是前端按 `node.size[1] + 30` 写在 `.lg-node` 上的 CSS 变量，节点拉多高它就多高；
* 顶部偏移 = 容器相对节点根部的 y 距离（标题 + 原生输入行），**只与容器上方的内容有关**，与容器自身高度无关
  ⇒ 不会出现「改高度 → 撑高节点 → 再改高度」的自激（实测第一版用 `root.clientHeight` 反推就自激到 1300+px）；
* 容器有确定高度后，内部 `flex:1` 的输入框自然吃掉剩余空间；经典模式（无 `.lg-node`）立即还原行内原样。

对应用户看到的两个状态：
| 场景 | 修前 | 修后 |
| --- | --- | --- |
| 节点高 620 | 框 274px，面板底部空白 | 框 286px，贴住面板底（只剩 8px 内边距） |
| 节点高 820 | 框仍 274px，空白更大 | 框 437px |
| 节点高 1060 | 框 433px（跟不上） | 框 655px |
| 切回经典模式 | — | 内联样式还原 `height:100%`、max/min 清空 |

保留：`installNodes2BoxResize`（按指针位移）仍供其它节点使用，本次只把三个「提示词预设」节点换成撑满模式。

### 11.1 追加修复：节点高度随画布缩放变化（同批，2026-10-17）

**现象**：`生图提示词预设` 节点在滚轮缩放画布时会自己变大/变小（提示词框高度跟着变）。

**根因**：`bindNodes2NodeFill` 用 `getBoundingClientRect()` 量「容器顶部偏移」，
拿到的是**屏幕像素**（已被画布 `transform: scale()` 缩放过），却被当成 CSS/布局像素写进了
`calc(var(--node-height) - Npx)`。于是缩放比一变，减掉的 chrome 就变 ⇒ 容器高度、进而节点高度跟着变。

**修法**：按 `app.canvas.ds.scale` 折算回布局像素：

```js
const scale = Number(app?.canvas?.ds?.scale) || 1;
const top = Math.round((bb.top - rb.top) / scale);     // 屏幕像素 → 布局像素
```

（`clientHeight` / `offsetHeight` 不受 transform 影响，所以 `bindNodes2BoxFill`（神笔）与
JZL 导演台的 `bindDomWidgetMaxHeight` 本来就是缩放安全的，无需改动。）

**实测**（同一节点，改缩放后等 1s 采样）：

| 画布缩放 | 修前 容器布局高 | 修后 容器布局高 | 修后 屏幕高 |
| --- | --- | --- | --- |
| 100% | 437 | **437** | 437 |
| 50% | 328（自己长胖了） | **437** | 219（= 437×0.5） |
| 150% | 575（自己变瘦了） | **437** | 656（= 437×1.5） |
| 75% | 393 | **437** | 328（= 437×0.75） |

同类节点复核（同样稳定，不随缩放变）：`XB_ShenBi` 显示窗固定 218、JZL 短剧导演台面板固定 498。

### 11.2 追加修复：切换 Nodes 2.0 时节点"弹一下"（2026-10-18）

**现象**：`生成剧本查看器` / `生成视频查看器`（以及 `生图提示词预设`、`神笔`）切换 Nodes 2.0 时，
节点会先变长一下再缩回去（像弹簧）。

**根因**：切换时前端整块卸载/重建 `.lg-node`。重建后的这段窗口里：
* 我们写的 `max-height` 还没生效 → 长内容按"无上限"铺开一帧；
* 旧写法 `calc(var(--node-height, 3000px) - K)`，`--node-height` 一旦缺失就取兜底 **3000px** → 容器真的被撑到 ~2850px。

**修法**（`js/xb_compat.js` 与 JZL 的 `asset_manager.js` 同步）：
1. 读不到 `--node-height` 时**不写** `calc()`（不再用 3000px 兜底）；
2. 新增共享 `MutationObserver` 监听 `document.body` 的结构变化（节点 DOM 增删），
   在回调里同步重算 —— 回调发生在**绘制前**，因此中间态一帧都不会被看到；
3. 保留 500ms（XB）/ 500ms（JZL）轮询兜内容尺寸变化，节点删除后自动停表。

**实测**（长内容 3000px 塞进两个查看器，2 次完整开关，rAF 逐帧采样 327 帧）：

| 节点 | 帧数 | 根高度取值 | 结论 |
| --- | --- | --- | --- |
| 生成剧本查看器 | 327 | 只有 `450` | 无任何中间态 ✅ |
| 短剧导演台 | 327 | 只有 `650` | ✅ |
| 生图提示词预设 | 327 | `721`（经典）/ `745`（2.0） | 仅两档稳定值，无尖峰 ✅ |
| 神笔 | 327 | `460`（经典）/ `483`（2.0） | 同上 ✅ |

（两档值差异是「经典 vs 2.0」正常的渲染差异，不是闪动。）
