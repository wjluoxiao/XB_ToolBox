[README.md](https://github.com/user-attachments/files/26647944/README.md)
---

# 🧰 ComfyUI XB-BOX (小白工具箱)

The Ultimate Spatiotemporal & VRAM Management Toolset for ComfyUI.

专为突破显存极限与 DiT 视频大模型（WAN 2.2 / LTX 2.3）深度定制的终极架构级扩展套件。

---

## 🇨🇳 中文说明 (Chinese)

### 🌟 核心理念

**XB-BOX** 是一套从底层内存调度到前端交互体验进行全方位重构的 ComfyUI 插件。它通过 **“时空分块劫持”、“UNet / Checkpoint 动态显存外包”** 以及 **“LiteGraph 交互深度定制”**，让拥有 24G 显存（尤其是 AMD 7900XTX 等 ROCm 环境）的消费级显卡，也能流畅运行原本会直接 OOM 的 14B~22B 超大 3D-DiT 视频模型。

### ✨ 核心节点矩阵 (Node Matrix)

#### 1. 🧊 极限显存特攻 (VRAM & Model Optimizations)

- **🧊 采样分块大师 (Sampler Chunk Master)**：专为 WAN/LTX 开发。在潜空间（Latent）执行时空双轴切割（Spatial Tiles & Temporal Chunks）。原地劫持模型参数，内置 `rocm_optimized` 极致显存回收策略，彻底打破大张量 OOM 魔咒。

- **✂️ 模型分块交换 (Block Swap)**：支持 UNet 与 Checkpoint 模式。可将前 N 个核心块（Transformer Blocks）以及 Text/Image 嵌入层强制卸载至系统内存（RAM），用时间换取空间。

- **🧹 显存清理大师 (VRAM Cleaner)**：战前清场必备。提供“核爆级清理”，深度调用 `gc.collect()` 与 `torch.cuda.empty_cache()`，强行粉碎 PyTorch 缓存碎片。

#### 2. 🎬 媒体参数与时空可视化 (Media Params & Visualization)

- **🎬 图像参数大全 (Media Params Master)**：内置“自由/图片/视频”三大模式。在视频模式下，提供极客级“手自一体换挡引擎”，在官方预训练的“黄金桶分辨率”（如 480x832, 544x960, 720x1280）之间平滑切挡，并严格锁定 1+8N 物理安全帧数。

- **🧊 时空分块预览 (Chunk Visualization)**：独创双区雷达！左侧展示 2D 绝对镂空网格（S1, S2...），右侧通过 3D 画家算法渲染时间圆柱堆叠（T1, T2...），直观展示所有块的重叠区。

- **📟 可用显存计算 & 数据雷达**：预判 WAN/LTX 在不同量化（FP8/GGUF）下的显存驻留，并提供精确到 MB 级别的张量体积称重。

#### 3. 🎛️ 终极工作流 UI (Workflow UX/UI Enhancements)

- **🪄 XB 远程控制中心 (Dashboard Zen)**：利用 LiteGraph 底层特性开发的“镜像克隆台”。可将工作流中分散的任意组件批量“克隆”到一个固定面板中。双向数据同步，大动脉直连，打造属于你的定制化监控台。

- **🎛️ 动态总线 (Dynamic Bus)**：极度压缩尺寸的 N进N出 `AnyType` 万能节点。提供 UI 自定义类型标签与一键通道增减，拯救杂乱无章的节点面条线。

### 📦 安装指南 (Installation)

**方法一：通过 ComfyUI Manager**

搜索 `XB_ToolBox` 或 `小白工具箱` 进行安装。

**方法二：手动 Git 安装**

进入你的 ComfyUI `custom_nodes` 目录，执行以下命令：

Bash

```
git clone https://github.com/wjluoxiao/XB_ToolBox.git
```

*(注：本插件纯粹依赖 ComfyUI 原生生态，通过精妙的 Python/JS 架构实现，**无需安装任何额外 pip 依赖！** 即插即用。)*

### 📝 许可证 (License)

本项目基于 **Apache-2.0 License** 开源。在极度自由分享的同时，保障了核心架构代码的专利防御权。

---

## 🇬🇧 English Documentation

### 🌟 Core Philosophy

**XB-BOX** is a comprehensive ComfyUI extension that reconstructs everything from low-level memory scheduling to frontend interactive experiences. By utilizing **"Spatiotemporal Tiling Hijacking"**, **"UNet/Checkpoint Dynamic VRAM Offloading"**, and **"Deep LiteGraph UI Customization"**, it empowers consumer-grade GPUs with 24GB VRAM (especially AMD ROCm environments like 7900XTX) to smoothly execute 14B~22B massive 3D-DiT video models that would otherwise cause OOM crashes.

### ✨ Node Matrix

#### 1. 🧊 Extreme VRAM & Model Optimizations

- **🧊 Sampler Chunk Master**: Engineered specifically for WAN/LTX architectures. Executes Spatial Tiles & Temporal Chunks slicing at the latent level. Modifies model parameters in-place with a built-in `rocm_optimized` deep cache-clearing strategy to obliterate massive tensor OOMs.

- **✂️ Block Swap (UNet & Checkpoint)**: Forces the offloading of the first N core Transformer Blocks and Text/Image embedding layers to System RAM, trading execution time for critical VRAM space.

- **🧹 VRAM Cleaner**: The ultimate pre-generation sweeper. Provides "Nuclear-Level Cleaning" via deep `gc.collect()` and `torch.cuda.empty_cache()` calls to forcefully shatter PyTorch memory fragments.

#### 2. 🎬 Media Params & Spatiotemporal Visualization

- **🎬 Media Params Master**: Features three distinct modes (Free/Image/Video). In Video Mode, it deploys a geek-tier "Gear Shifting Engine", allowing seamless stepping between official "Golden Bucket" resolutions (e.g., 480x832, 544x960, 720x1280) while strictly enforcing 1+8N safe frame counts.

- **🧊 Chunk Visualization**: A unique dual-zone radar! The left displays 2D absolute hollow spatial grids (S1, S2...), while the right utilizes a 3D Painter's Algorithm to render temporal cylinder stacks (T1, T2...) highlighting exact overlap zones.

- **📟 VRAM Calculator & Data Radar**: Predicts VRAM retention for WAN/LTX across various quantizations (FP8/GGUF) and provides exact MB-level tensor volume weighing.

#### 3. 🎛️ Ultimate Workflow UX/UI Enhancements

- **🪄 Dashboard Zen (Remote Control Center)**: A "Mirror Cloning Console" developed via deep LiteGraph hacks. Batch clone any scattered components across your workflow into a unified dashboard. Features bi-directional value syncing and direct data bus routing for a personalized monitoring station.

- **🎛️ Dynamic Bus**: An ultra-compact N-in/N-out `AnyType` universal routing node. Features custom UI type labels and one-click port scaling to cure your messy workflow spaghetti.

### 📦 Installation

**Method 1: ComfyUI Manager**

Search for `XB_ToolBox` in the ComfyUI Manager to install.

**Method 2: Manual Git Clone**

Navigate to your ComfyUI `custom_nodes` directory and run:

Bash

```
git clone https://github.com/wjluoxiao/XB_ToolBox.git
```

*(Note: This extension relies purely on the native ComfyUI ecosystem via elegant Python/JS architecture. **Zero extra pip dependencies required!** Plug and play.)*

### 📝 License

This project is open-sourced under the **Apache-2.0 License**, granting extreme freedom for sharing while maintaining enterprise-level patent defense for its core architectural logic.
