[README.md](https://github.com/user-attachments/files/26662024/README.md)
Markdown

---

# 🧰 ComfyUI XB-BOX (小白工具箱)

The Ultimate Spatiotemporal & VRAM Management Toolset for ComfyUI.

专为突破显存极限与 DiT 视频大模型（WAN 2.2 / LTX 2.3）深度定制的终极架构级扩展套件。

---

![Image](https://github.com/user-attachments/assets/19bd0104-5ad2-4ccc-9a0a-86d477024c3f) ![Image](https://github.com/user-attachments/assets/f8684258-f082-48b6-a4a3-e52f1cc701d1)

---

## 🇬🇧 English Documentation

### 🌟 Core Philosophy

The primary goal of **XB_ToolBox** is to help AI beginners quickly master ComfyUI workflows, making local deployment and operation simpler and more intuitive. It is a comprehensive ComfyUI extension suite rebuilt from the ground up, covering everything from low-level memory scheduling to front-end interactive UX.

It integrates commonly used but scattered parameter nodes, allowing users to set frequently used image and video parameters through a single, unified node.

It provides intuitive visual chunking and parameter preview nodes, helping beginners quickly understand the mechanics of encoder and decoder tiling/chunking.

It introduces a "Mirror Clone Dashboard" that simplifies highly complex workflows by cloning key operation widgets into a clean, centralized control panel!

Furthermore, through **"Spatiotemporal Chunk Hijacking"**, **"Dynamic VRAM Offloading for UNet/Checkpoints"**, and **"Deep LiteGraph UI Customization"**, it enables consumer-grade GPUs with 24GB VRAM (especially in AMD 7900XTX ROCm environments) to smoothly run massive 14B~22B 3D-DiT video models that would normally cause instant Out-Of-Memory (OOM) crashes.

### ✨ Node Matrix

#### 1. 🧊 Extreme VRAM & Model Optimizations

- **🧊 Sampler Chunk Master**: Developed specifically for WAN/LTX models. Executes dual-axis slicing (Spatial Tiles & Temporal Chunks) directly in the latent space. It hijacks model parameters in place and features a built-in `rocm_optimized` extreme VRAM recovery strategy, completely breaking the curse of large-tensor OOM.
- **✂️ Model Block Swap**: Supports both UNet and Checkpoint modes. Forcefully offloads the first N core blocks (Transformer Blocks) and Text/Image embedding layers to system RAM, trading generation time for VRAM space.
- **🧹 VRAM Cleaner**: Essential for pre-generation clearing. Provides "nuclear-level cleanup" by deeply invoking `gc.collect()` and `torch.cuda.empty_cache()` to forcibly shatter PyTorch memory fragments.

#### 2. 🎬 Media Params & Spatiotemporal Visualization

- **🎬 Media Params Master**: Features three built-in modes: Free, Image, and Video. In video mode, it provides a geek-level "manual/automatic shifting engine" to smoothly switch between official pre-trained "golden bucket resolutions" (e.g., 480x832, 544x960, 720x1280), strictly locking to the 1+8N physically safe frame counts.
- **🧊 Chunk Visualization**: Original dual-zone radar! The left side displays a 2D absolute hollow grid (S1, S2...), while the right side renders a temporal cylinder stack (T1, T2...) using a 3D painter's algorithm, intuitively visualizing the overlapping areas of all chunks.
- **📟 VRAM Calculator & Data Radar**: Predicts VRAM occupation for WAN/LTX under different quantizations (FP8/GGUF) and provides exact tensor volume weighing down to the megabyte.

#### 3. 🎛️ Ultimate Workflow UX/UI Enhancements

- **🪄 XB Dashboard Zen**: A "Mirror Clone Dashboard" developed utilizing LiteGraph's underlying features. It allows you to batch "clone" any scattered widgets in the workflow into a fixed, central panel. Featuring two-way data synchronization and direct pipeline connections to build your personalized control center.
- **🎛️ Dynamic Bus**: An extremely compact N-in, N-out `AnyType` universal node. Features UI-customizable type labels and one-click channel addition/removal, saving you from messy, tangled noodle wires.

### 📦 Installation

**Method 1: Via ComfyUI Manager**Search for `XB_ToolBox` in the ComfyUI Manager and click install.

**Method 2: Manual Git Installation**  
Navigate to your ComfyUI `custom_nodes` directory and run the following command:

```bash
git clone https://github.com/wjluoxiao/XB_ToolBox.git
```

*(Note: This plugin relies purely on the native ComfyUI ecosystem. Implemented through an elegant Python/JS architecture, **no additional pip dependencies are required!** Plug and play.)*

### 📝 License

This project is open-sourced under the **Apache-2.0 License**. While embracing extreme freedom of sharing, it ensures patent defense rights for the core architecture code.

---

## 🇨🇳 中文说明 (Chinese)

### 🌟 核心理念

**XB_ToolBox** 的主旨是帮助新手AI玩家快速上手ComfyUI工作流，让在本地部署运行更简单方便，是一套从底层内存调度到前端交互体验进行全方位重构的 ComfyUI 插件。

它整合了工作流常用但分散的参数节点，让大家可以通过一个节点设置常用的图片视频参数。

提供了更直观的可视化分块预览和参数预览节点，让新手更快理解解码器和编码器分块的原理。

提供了“镜像克隆台”这种可以把超级复杂的工作流，通过克隆主要操作节点，从而让工作流更加简洁的方案！

另一方面也通过 **“时空分块劫持”、“UNet / Checkpoint 动态显存外包”** 以及 **“LiteGraph 交互深度定制”**，让拥有 24G 显存（尤其是 AMD 7900XTX 等 ROCm 环境）的消费级显卡，也能流畅运行原本会直接 OOM 的 14B~22B 超大 3D-DiT 视频模型。

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
