🌐 [English](README.md) | [简体中文](README_zh.md)

# 🧰 ComfyUI XB-BOX (小白工具箱)

---

## 🌟 核心理念

**XB_ToolBox** 的主旨是帮助刚接触 ComfyUI 的新手 AI 玩家快速上手工作流，让本地部署运行更简单便捷，是一个包含前端交互和底层内存调度的综合型 ComfyUI 扩展套件。

- **参数大一统**：整合了工作流中使用频率高但分散的参数节点，通过一个中枢节点即可设置常用的图片/视频基础参数。
- **可视化教学**：提供了可视化分块预览和参数雷达节点，让新手更直观地理解解码器/编码器的时空分块以及重叠（Overlap）的底层原理。
- **操作体验革命**：首创“镜像克隆台”，可将复杂工作流中的主要操作节点一键克隆至统一面板，让创作面板极度整洁高效。
- **极限显存压榨**：通过 **“时空分块劫持”、“UNet / Checkpoint 动态显存外包”** 以及 **“LiteGraph 交互深度定制”**，让消费级显卡也能流畅运行原本会直接 OOM 的 14B~22B 超大 3D-DiT 视频大模型。

---

![界面截图](docs/01.png)
![界面截图](docs/02.png)
![界面截图](docs/03.png)
![界面截图](docs/04.png)

![界面截图](docs/05.png)
![界面截图](docs/06.png)

---

## 🗺️ 节点总览 — 141 个节点

| 分类 | 节点数 | 亮点 |
|------|:---:|---|
| 🎛️ 参数与媒体 I/O | 7 | 图片 / 视频参数大全、海螺 H3 参数、视频加载与拼接、万能参数 |
| 🧊 显存优化 | 25 | 17 个「官方套皮」采样器 / VAE（分级清理）、分块交换、SageAttention、GGUF 加载 V1–V3 |
| 🎬 长视频接力流水线 | 19 | InfiniteTalk / SCAIL / Wan Animate 无限接力、LTX-2.3 流式、视频合并、分镜切割、数字人参数 |
| 🎥 Wan 节点族 | 24 | 图生视频、首尾帧、VACE、Fun、Camera、Phantom、HuMo、SCAIL、Dancer、Sound、InfiniteTalk——全部内置 VAE 分块 |
| 🎵 音频与语音 | 15 | 音频切片 ×4、CosyVoice3 ×10、播放声音 |
| 🧠 本地 LLM（XB-llama） | 17 | 模型加载、指令推理、推理参数、提示词增强 / 反推、分镜、MiniMax H3 预设 |
| 🖼️ 生图预设 | 4 | 生图提示词预设 / Pro、Qwen2.1 预设、神笔画板 |
| 🖼️ 专用编码器 | 3 | FLUX 多图编码、Qwen 图像编辑编码（+ Plus） |
| 🎨 超级路由 | 2 | Bernini 提示词路由、K2 风格路由 |
| 🎵 YuE2 音乐 | 5 | 风格提示、歌词、乐谱工作台、翻唱准备、转谱导入 |
| ✂️ 人物分割 | 2 | ONNX 人物分割（AMD 走 DirectML GPU） |
| 💬 漫画 | 3 | 台词解析、精确坐标渲染、自动气泡渲染 |
| 🧰 工具与接线 | 11 | 批量加载、批量缩放、列表分发、字符串合并、引用任意、状态开关、画布标签、MSR、名称广播 |
| 📊 硬件面板 | 1 | 显存 / 内存 / CPU / GPU / 磁盘 实时面板 |

> 节点数直接取自 `__init__.py` 的 `NODE_CLASS_MAPPINGS`。

---

### ✨ 核心节点

#### 1. 🎬 媒体参数与时空可视化

- **🖼️ 图片参数大全**：提供宽度、高度、生成数量、控制力度等核心参数。所有参数强制步长锁定，避免新手输入错误导致崩溃；选择固定宽高比时会自动对齐长边尺寸。
- **🎬 视频参数大全**：提供宽、高、帧数、帧率（支持浮点和整数）。内置极客级“手自一体换挡引擎”，在官方预训练的“黄金桶分辨率”（如 480x832, 720x1280）之间平滑切挡，并严格锁定 `1+8N` 的物理安全帧数。根据帧率即时推算并显示视频物理时长。
- **🧊 时空分块预览 (Chunk Visualization)**：独创双区雷达！左侧通过 2D 展示图像分块和重叠数值的可视化效果，右侧通过 3D 画家算法渲染时间圆柱堆叠。彻底终结新手盲目调试参数导致的精力耗费。
- **🧊 分镜图片切割**：提供多种模式，可以将常见的四宫格、六宫格、九宫格..图片一次性切割，并输出多个图片，更加方便图生视频或者首尾帧视频，对于做短剧十分有效。
- **📟 可用显存计算 & 数据雷达**：预判 WAN / LTX 等模型在不同量化（FP8/GGUF）下的显存驻留，并提供精确到 MB 级别的张量体积称重。方便新手根据显存容量精准选择模型，大幅降低试错成本。

#### 2. 🧊 显存优化

- **🧊 官方采样器 / VAE 套皮（17 个）**：一字不差地调用 ComfyUI 官方节点（动态 `INPUT_TYPES`、`**kwargs` 透传、不改底层算法），仅在执行前注入分级缓存清理（`不做任何清理` / `单次缓存清理` / `双次缓存清理` / `卸载显存模型`）。覆盖 `KSampler`、`KSamplerAdvanced`、`SamplerCustom(+Advanced)`、`VAEDecode(+Tiled / TiledImage)`、`VAEEncode(+Tiled / ForInpaint)`，并保留给旧工作流用的 `ROCm` 命名别名。
- **✂️ 分块交换 (Block Swap)**：支持 UNet 与 Checkpoint 两种模式，把前 N 个 Transformer 块与 Text/Image 嵌入层强制停放到系统内存（RAM），用时间换空间。
- **🧠 SageAttention 加速 / Sage + 分块 黄金搭档**：单独挂载注意力加速补丁（自动 / PyTorch SDPA / comfy-kitchen），或与物理分块交换合并为一个节点。
- **📦 GGUF 模型加载大全 V1 / V2 / V3**：把 GGUF UNet + GGUF CLIP + LoRA（多槽）+ VAE + Sage + BlockSwap 叠成一个节点；V2 增加高噪 / 低噪双 UNet，V3 增加双 CLIP、双 VAE。

#### 3. 🎛️ 工作流部署助手

- **🎛️ 参数总线 & 接力节点**：一个极度压缩的 `AnyType` 总线集中管理所有共享参数（模型、VAE、提示词、尺寸、帧率、清理档位），配合接力节点执行单段并累加结果——用 1 个节点替掉 10 节点子图，彻底告别“节点面条线”。
- **🧰 让工作流更省心的小工具**：列表分发（一份列表拆成 N 路）、引用任意（动态槽位单选开关）、节点状态开关（用布尔控制目标节点的 mute / bypass）、字符串合并、名称广播、画布标签、播放声音。
- **📊 镜像面板**：硬件监控面板把你关心的数字汇到一条常驻横条上——见第 13 节。

#### 4. 🎬 长视频接力流水线

两分钟的对口型视频，几乎任何显卡一次跑完都会 OOM。这组节点把任务拆成可复用的「接力」：**参数总线**集中管理全部共享参数（模型、VAE、尺寸、帧率、提示词、清理档位），每个**接力节点**跑完一段（编码 → 采样 → 解码 → 裁切 → 累加）后把累加结果交给下一棒。

- **🎵 InfiniteTalk 总线 / 接力**：单人、双人、多图参考，以及全能版；总线一次性编码音频并按段自动切片。
- **🏃 Wan Animate 总线 / 接力**：从驱动视频做动作迁移，同一套接力模式。
- **🆕 SCAIL 总线 / 接力**：SCAIL 姿态驱动视频接力。
- **🔄 LTX-2.3 无限流式**：单次采样（8 步）长视频流式生成 + 引导拼接。
- **🎬 视频合并 / 分镜切割 / 数字人参数**：合并片段、把多宫格分镜切成单图，以及数字人工作流的一站式参数与音频预处理。

#### 5. 🎥 Wan 节点族（24 个）

复刻 Wan 视频节点并**内置 VAE 分块**（空间 + 时间双重分块，削平解码显存峰值）：`ImageToVideo`、`FirstLastFrameToVideo`、`VaceToVideo`、`FunControl` / `FunInpaint`、`Camera`、`PhantomSubject`、`HuMo`、`SoundImageToVideo`（+ Extend）、`SCAIL`（+ Pro）、`Dancer`（+ 舞蹈切换器 / Dancer 综合）、`InfiniteTalkToVideo`（单人 / 双人 / 兼容旧工作流的 mode 切换）、`Wan22ImageToVideoLatent`、`WanVAEDecodeTiled`。

> 它们只是图里的成员节点——Wan 的**模型 / 采样器 / VAE / 文本编码**节点来自 [ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper)。`XB_WanAnimateToVideo` 与 `XB_WanCompileSettings` 完全独立自足。

#### 6. 🎵 音频与语音（15 个）

- **🎵 音频切片 ×4**：可视化波形 + 可拖拽截取：基础版、V1（单人）、V2（双人 + 间隔）、V3（高级，双轨混音）。
- **🔊 CosyVoice3 ×10**：模型加载（自动下载 + 缓存）、零样本克隆、跨语言合成、指令控风格、说话人预设保存 / 克隆、语音转换、多人对话、音频裁剪。预设存成 CosyVoice 兼容的 `.pt`，无需每次重传参考音频。
- **🔊 播放声音**：工作流跑完播放提示音。

#### 7. 🧠 本地 LLM 提示词套件（XB-llama，17 个）

本地 LLM / VLM 推理做提示词工作：模型加载（+ Pro，把全部推理参数收进一个面板）、指令推理、推理参数、卸载 / 清理状态、BBox 提取、解包代码块、提示词**增强**、提示词**反推**（五合一：加载器 + 参数 + API 设置 + 预设 + 推理）、分镜增强 / 推理 / 处理器（+ Pro）、MiniMax H3 提示词预设（`fl2va`、`ref2va`）以及角色场景调度器。

同时支持**本地模型**与**在线 API** 两种后端；API Key 存在 ComfyUI `user` 目录，不会写进工作流。

#### 8. 🖼️ 生图提示词预设（4 个）

- **🖼️ 生图提示词预设**：一个节点替掉「提示词框 + 画幅比例节点 + 官方空 latent」，宽高步长锁定并支持比例联动。
- **🖼️ 生图提示词预设 Pro**：同上，并内置 LLM 提示词增强 / 反推。
- **🖼️ Qwen2.1 提示词预设**：预设 + 元素面板，接官方 Load CLIP + Generate Text 链路。
- **🖌️ 神笔**：无输入端、只输出 Image 的画板节点（创作 / 编辑双模式），输出严格对齐设定分辨率。

#### 9. 🖼️ 专用编码器（3 个）

- **FLUX 多图编码**：缩放 → VAE 编码 → ReferenceLatent 串联，图片槽位自动扩展（最多 9 张）。
- **Qwen 图像编辑编码（+ Plus）**：移植官方 `TextEncodeQwenImageEdit` / `...Plus`，动态图片槽位最多 9 张。

#### 10. 🎨 超级路由（2 个）

**Bernini 提示词路由**与 **K2 风格路由**：把重度多开关子图（Fast Muter + Any Switch 链）重构成单一原生节点，前端刷新 / 拖拽开销从 O(n) 个隐藏节点降到 O(1)。

#### 11. ✂️ 分割与漫画（5 个）

- **✂️ 人物分割**：ONNX u2net（RMBG-1.4）模型加载 + 蒙版 / 抠图节点，AMD 上通过 DirectML 走 GPU。
- **💬 漫画 ×3**：从剧本里解析台词、按精确坐标渲染文字，或自动识别白色对话框并填入台词。

#### 12. 🧰 工具与接线（11 个）

批量文件夹 / 批量图像（自动跳过 mute 输入）、批量缩放（N 进 N 出）、列表分发、字符串合并（可每段换行）、引用任意、节点状态开关、画布标签、MSR 多图合成帧序列、UNet / CLIP 名称广播。

#### 13. 📊 硬件监控面板（1 个）

**XB 📊 硬件监控面板**：显存 / 内存 / CPU / GPU / 磁盘 / 页面文件实时监控，带逐模型显存拆分、aimdo 页级驻留热力图、历史曲线、主题，以及可吸附到 ComfyUI 顶栏的迷你条。完整说明见 [docs/XB_MemoryVisualization_manual.md](docs/XB_MemoryVisualization_manual.md)。

#### 14. 🎵 YuE2 音乐

YuE2 是「白盒」歌曲生成模型：先由 style + 歌词规划出一份可读可改的 ABC 谱面，再据谱渲染音频。这组节点把官方 skill 的符号层工作流搬进 ComfyUI（ABC 解析器是官方有界方言实现的节点内移植，纯标准库，不外传任何数据）。

- **🎵 YuE2 风格提示**：按官方 6 段式（语言 / 曲风 / 人声 / 速度 / 乐器 / 音乐特征）拼出 `style` 串，内置 13 条一键配方与曲风库；同时输出 `max_duration` 与 `seed`，让规划器与生成器共用同一个 seed，便于复现。段落结构、调式、调号、拍号一律不写进 `style`——它们属于歌词标签与谱面。
- **🎵 YuE2 歌词**：段落标签面板（官方 **8 个**段落词表 + 社区写法 + 自定义 `[标签]`）、一键「纯音乐骨架」，以及可唱性检查（实现说明混入歌词、圆括号角色标注会被唱出来、空段落、逐行音节统计、标签是否属于官方词表）。
- **🎵 YuE2 乐谱工作台**：只查看 / 去掉和弦 / 人声移到器乐轨 / 用编辑框，内置官方规则（网格、`Z2–Z4` 压缩、和弦词表、连音），输出处理后的谱面 + 中文报告（**首行就是模式建议** `full` / `melody`）。注意谱面里**没有乐器**——配器要在「风格提示」节点设定。选项只写选项名，说明一律在悬停 tooltip 里。
- **🎵 YuE2 转谱导入**：读入 SheetSage2 的产物（`score.abc` / `events.json`，目录或文件都行），按官方修谱表做机械规范化（Markdown 围栏 / BOM / 弯引号 / `M:C` / `Q:81` / `K:B minor`），再按原生方言校验并输出可用谱面。语义性修复（展开反复、量化三连音、补休止）故意留给你自己判断，节点只把官方校验器的原始报错和修谱提示原样给出。
- **🎵 YuE2 翻唱准备**：生成翻唱条件——保留哪条声部 × 如何处理和声，而「和声处理」直接决定下游 mode（去掉和弦→`melody` 真·翻唱；保留和弦→`full` 接近原版重录）。报告里带改动前后的事件比对与官方翻唱链路说明。翻唱只提供符号层旋律，不保留原唱歌手的音色与波形。

需要 ComfyUI 已带官方 `YuE2GenerateABC` / `YuE2GenerateMusic` 节点（用官方 text-to-music 工作流即可带入）。本组节点只输出 STRING/FLOAT/INT，因此任何版本都能正常加载。

**官方能力对照（哪些在这儿、哪些留在官方节点）**

| 官方能力 | 位置 |
|---|---|
| 规划/渲染参数：`mode`、`max_abc_tokens`、`temperature`、`top_p`、`top_k`、`repetition_penalty`、`penalty_window`、`cfg_scale` | 官方 `YuE2GenerateABC` / `YuE2GenerateMusic` 节点；本包只往它们喂 `style` / `max_duration` / `seed` |
| 风格、歌词、段落标签 | 🎵 YuE2 风格提示 / 🎵 YuE2 歌词（官方 8 词表 + 社区写法 + 自定义标签） |
| ABC 检视 / 去和弦 / 移轨 / 事件编译 / 差异审阅 | 🎵 YuE2 乐谱工作台（移植官方有界方言实现） |
| 翻唱条件（去和弦→`melody`、保留和弦→`full`、声部取舍） | 🎵 YuE2 翻唱准备 |
| 解码器选择（`YuE2-Vae` 试听 / `YuE2-Vae-legacy` 复现评测） | 由你加载的 VAE 决定；只换解码器重解码不需要重新生成 |
| 音频转谱（SheetSage2）**本身** | 不在本包内 —— 需要独立 Python 环境（Python 3.10/3.11 + torch 2.8/cu126）。用 🎵 YuE2 转谱导入把它的 `score.abc` / `events.json` 接回图里 |
| MERT2 特征、`yue2 batch`、`listen.py` 试听页、SongBench 评测 | 不在本包内 —— 属于交付/评测工具而非图节点 |

节点顺手替你兜住的官方行为：ABC 输入留空时官方节点会自动进入 `off` 模式；被截断的谱面会直接结构校验失败；`mode=melody` 不接受任何和弦记号；规划器与生成器可以吃**不同**的歌词（规划只用段落标签、演唱用实词）。

**纯音乐要三步，光设风格不够。** 官方器乐入口会（a）把 style 规范成以 `Instrumental, ` 开头，并（b）强制补齐四个抑制条件 —— `no vocals, no singing, no choir, no spoken words`（哼唱、和声、念白一并排除）。风格提示节点选「纯音乐」后已按官方这样做。但**只靠 style 去不掉人声**：谱面里 `Vocal` 必须**没有发声音符**（🎵 乐谱工作台 →「人声移到器乐轨」），歌词必须是空或只有段落标签（🎵 歌词 →「纯音乐骨架」）。官方明确：文件检查无法证明没有人声泄漏，最终要听音确认。

---

### 📦 安装指南 (Installation)

**方法一：通过 ComfyUI Manager (推荐)**  
在管理器中搜索 `XB_ToolBox` 或 `小白工具箱` 进行一键安装。

**方法二：手动 Git 安装**  
进入你的 ComfyUI `custom_nodes` 目录，执行以下命令：

```bash
git clone https://github.com/wjluoxiao/XB_ToolBox.git
```

*(注：核心架构纯粹依赖 ComfyUI 原生生态，通过精妙的 Python/JS 实现，不魔改任何底层库。部分节点分组会额外导入第三方包，见下方。)*

#### 🔧 依赖说明

大部分节点零依赖，但有几组会额外导入第三方包。一次性安装：

```bash
pip install -r requirements.txt
```

| 节点分组 | 需要的包 |
|---|---|
| 音频切片、视频 I/O | `av`、`imageio-ffmpeg` |
| 漫画文字检测 | `easyocr`、`opencv-python` |
| 人物分割 | `onnxruntime`（A 卡改用 `onnxruntime-directml`） |
| 硬件监控面板 | `psutil`、`pythonnet`（已内置 `LibreHardwareMonitorLib.dll`） |
| 本地 LLM（XB-llama） | `diskcache`、`gguf`，以及 **`llama-cpp-python`**（需按你的显卡手动选装轮子） |
| CosyVoice3 | `modelscope`、`huggingface_hub`、`transformers`、`librosa`、`soundfile`、`HyperPyYAML`、`omegaconf`、`hydra-core`、`conformer`、`openai-whisper`、`tiktoken`、`scipy`、`einops` 等 |
| 音频波形接口 | `aiohttp` |

**可选配套扩展** —— 以下分组需要同时安装对应插件：

| 功能 | 需要安装 |
|---|---|
| Wan 节点族与接力流水线 | [ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper)（提供 Wan 模型 / 采样器 / VAE / 文本编码节点） |
| GGUF 模型加载 | [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) |
| YuE2 预设节点 | 已自带 `YuE2GenerateABC` / `YuE2GenerateMusic` 的 ComfyUI 版本 |

完全独立自足的节点会在自己的 docstring 里注明「零外部节点依赖」。

---

### 🙏 致谢

XB_ToolBox 站在 ComfyUI 生态的肩膀上，部分节点为移植 / 套壳 / 改编，感谢原作者：

- **VideoHelperSuite (VHS)** —— 视频加载 / 拼接与音频切片逻辑源自 VHS。
- **rgthree-comfy** —— `XB_ReferenceAny` 融合了 Fast Muter + Any Switch。
- **ComfyUI-KJNodes** —— `XB_StringMerge` 由 `JoinStringMulti` 重构而来；SageAttention 节点保持原版 KJNodes 设计。
- **ComfyUI-Custom-Scripts (pysssss)** —— `XB_PlaySound` 为独立重写实现。
- **ComfyUI-GGUF (city96)** —— GGUF 加载节点套壳其官方节点。
- **ComfyUI-WanVideoWrapper (kijai)** —— Wan 节点族的配套扩展。
- **ComfyUI-MemoryVisualization (kijai)** —— 硬件监控面板最初基于该项目，现已长出独立的主题、停靠与监控指标。
- **ComfyUI-llama-cpp_vlm** —— `XB-llama` 节点基于其适配。
- `XB_KSampler` 等节点一字不差地调用 **ComfyUI 官方节点**，只额外注入缓存清理。

---

### 📝 许可证 (License)

本项目基于 **Apache-2.0 License** 开源。在极度自由分享的同时，保障了核心架构代码的专利防御权。

---
