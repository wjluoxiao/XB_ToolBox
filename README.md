<div align="center">
  🌐 <a href="README.md">English</a> | <a href="README_zh.md">简体中文</a>
</div>
<br>

# 🧰 ComfyUI XB-BOX (XB_ToolBox)

---

## 🌟 Core Philosophy

The primary goal of **XB_ToolBox** is to help AI beginners new to ComfyUI quickly master workflows, making local deployment and execution simpler and more convenient. It is a comprehensive ComfyUI extension suite encompassing both front-end interaction and low-level memory scheduling.

- **Unified Parameters:** Integrates frequently used but scattered parameter nodes, allowing you to set essential image and video parameters from a single hub.
- **Visual Learning:** Provides visual chunking and parameter preview nodes, enabling beginners to intuitively understand the concepts of VAE/Encoder chunks, temporal slicing, and overlap effects.
- **UX Enhancements:** Introduces a user-friendly "Mirror Clone Console" (Dashboard) that clones major operation nodes from complex workflows into a unified, clean, and highly efficient control panel.
- **Extreme VRAM Optimization:** Through "Spatiotemporal Chunk Hijacking", "Dynamic VRAM Offloading for UNet/Checkpoints", and "Deep LiteGraph Customization", it allows consumer-grade GPUs to smoothly run massive 14B~22B 3D-DiT video models that would normally cause instant OOM (Out of Memory).

---

![界面截图](docs/01.png)
![界面截图](docs/02.png)
![界面截图](docs/03.png)
![界面截图](docs/04.png)

![界面截图](docs/05.png)
![界面截图](docs/06.png)
![界面截图](docs/04.png)

---

### ✨ Core Nodes

#### 1. 🎬 Media Parameters & Spatiotemporal Visualization

- **🖼️ Image Parameters Master**: Controls core image generation parameters (Width, Height, Batch Size, Strength) in one place. Enforces safe steps to prevent invalid inputs and automatically aligns dimensions when a fixed aspect ratio is selected.
- **🎬 Video Parameters Master**: Manages Width, Height, Frames, and FPS (Integer/Float). Features a geek-level "Auto-Manual Transmission Engine" that smoothly snaps to official pre-trained "Golden Buckets" (e.g., 480x832, 544x960) and strictly locks the physical frame count to the safe `1+8N` rule. Dynamically displays video duration based on frame rate.
- **🧊 Spatiotemporal Chunk Visualization**: An exclusive dual-zone radar! The 2D left panel visualizes spatial image chunks and overlap values, while the 3D right panel uses a painter's algorithm to render temporal cylinder stacks. Saves beginners from the exhaustion of blind parameter tuning.
- 🧊 **Storyboard Image Slicer:** Offers multiple modes to slice common 4-grid, 6-grid, 9-grid... images all at once and output multiple individual images. This makes image-to-video or start/end frame video generation much more convenient, and is highly effective for creating short dramas.
- **📟 VRAM Calculator & Data Radar**: Predicts VRAM footprint for WAN/LTX models under different quantizations (FP8/GGUF) and weighs tensor volumes with MB-level precision. Significantly reduces trial-and-error costs by helping users choose models fitting their VRAM capacity.

#### 2. 🧊 VRAM Optimization

- **🧊 Sampler Chunk Master**: Tailored for WAN/LTX. Performs spatiotemporal dual-axis slicing (Spatial Tiles & Temporal Chunks) in the Latent space. Hijacks model parameters in-place with an built-in `rocm_optimized` extreme memory reclamation strategy, breaking the large-tensor OOM curse.
- **✂️ Model Block Swap**: Supports both UNet and Checkpoint modes. Forcibly unloads the first N Transformer Blocks and Text/Image embedding layers to system RAM, trading time for space.
- **🧹 VRAM Cleaner**: Essential for pre-generation clearing. Delivers "nuclear-level cleanup" by deeply invoking `gc.collect()` and `torch.cuda.empty_cache()` to crush PyTorch cache fragmentation.

#### 3. 🎛️ Workflow Deployment Assistants

- **🪄 XB Dashboard Zen**: A "Mirror Clone Console" developed using low-level LiteGraph features. Batch-clones any scattered components in your workflow into a fixed panel. Features two-way data synchronization and direct arterial connections to create a clean, customized monitoring dashboard.
- **🎛️ Dynamic Bus**: An ultra-compact N-in/N-out `AnyType` universal bus node. Provides custom UI type labels and one-click channel addition/removal to save your workflow from "noodle wire" chaos.

#### 4. 🎵 YuE2 Music

YuE2 is a white-box song generator: it plans an editable ABC score from style + lyrics, then renders audio from that score. These nodes bring the official skill's symbolic-layer workflow into ComfyUI (the ABC parser is an in-node port of the official bounded-dialect implementation, standard library only, nothing leaves your machine).

- **🎵 YuE2 Style Prompt**: Builds the official six-part `style` string (Language / Genre / Vocal / Tempo / Instruments / Musical Characteristics) with 13 one-click recipes and a genre library. Also exposes `max_duration` and `seed`, so the planner and the renderer share one seed for reproducible plans. Structure, key and meter stay out of `style` — they belong to the lyrics tags and the score.
- **🎵 YuE2 Lyrics**: Section tags with a picker (the official **eight-tag** vocabulary + community spellings + your own `[custom]` tags), a one-click instrumental skeleton, and singability checks (implementation notes leaking into lyrics, round-bracket role labels that get sung, empty sections, per-line syllable counts, and whether a tag is official).
- **🎵 YuE2 Score Workbench**: Inspect / strip chords / move the vocal melody to `Ins` / use an edited score, with the official rule set (grid, `Z2–Z4` compression, chord vocabulary, ties). Emits the processed score plus a readable report whose first line is the mode suggestion (`full` vs `melody`). Note the score carries **no instruments** — set those in the style node. Option names stay short; every explanation lives in the widget tooltip.
- **🎵 YuE2 Transcription Intake**: Reads SheetSage2 output (`score.abc` / `events.json`) from a folder or file, applies the mechanical normalizations from the official repair table (Markdown fences, BOM, curly quotes, `M:C`, `Q:81`, `K:B minor`), validates against the native dialect and emits a usable score. Semantic repairs (unrolling repeats, quantizing tuplets, adding rests) are deliberately left to you, with the official validator's own message shown.
- **🎵 YuE2 Cover Prep**: Builds cover conditions — which voice to keep x how to handle the harmony — and the harmony choice literally sets the downstream mode (chord-free → `melody`, a true cover; keep chords → `full`, closer to a re-record). The report carries the before/after event comparison and the official cover flow. A cover only supplies a symbolic melody; it does not preserve the source singer's identity or waveform.

Requires a ComfyUI build that ships the native `YuE2GenerateABC` / `YuE2GenerateMusic` nodes (bring them in with the official text-to-music workflow). The nodes here only emit STRING/FLOAT/INT, so they load on any build.

**Where each official capability lives** (so nothing is duplicated or missing):

| Official capability | Where it is |
|---|---|
| Planning/rendering parameters — `mode`, `max_abc_tokens`, `temperature`, `top_p`, `top_k`, `repetition_penalty`, `penalty_window`, `cfg_scale` | The official `YuE2GenerateABC` / `YuE2GenerateMusic` nodes. This package only feeds `style` / `max_duration` / `seed` into them. |
| Style, lyrics, section tags | 🎵 YuE2 Style Prompt / 🎵 YuE2 Lyrics (the official eight-tag vocabulary + community spellings + custom tags) |
| ABC inspect / strip chords / move voice / event compile / difference review | 🎵 YuE2 Score Workbench (a port of the official bounded-dialect implementation) |
| Cover conditions (chord-free → `melody`, keep chords → `full`, voice selection) | 🎵 YuE2 Cover Prep |
| Decoder choice (`YuE2-Vae` for listening, `YuE2-Vae-legacy` for benchmark reproduction) | Determined by the VAE you load; re-decoding cached latents needs no new generation. |
| Audio→score transcription (SheetSage2) **itself** | Not here — it needs a separate Python environment (Python 3.10/3.11 + torch 2.8/cu126). Use 🎵 YuE2 Transcription Intake to bring its `score.abc` / `events.json` back into the graph. |
| MERT2 features, `yue2 batch`, the `listen.py` HTML player, SongBench scoring | Not here — they are delivery/evaluation tooling rather than graph nodes. |

Handy official behaviours the nodes surface for you: `off` mode is automatic when the ABC input is empty, a truncated score fails structure validation, `mode=melody` rejects any chord symbol, and the planner and renderer can receive **different** lyrics (section-tags-only for planning, real words for singing).

**Instrumental needs three things, not just a style setting.** The official instrumental entry point (a) prefixes `Instrumental, ` and (b) forces four suppression conditions — `no vocals, no singing, no choir, no spoken words`. The style node now does exactly that when you pick 纯音乐. But style alone cannot remove singing: the score's `Vocal` voice must have **no sounding notes** (Score Workbench → "Vocal to Ins"), and the lyrics must be empty or section tags only (Lyrics node → "纯音乐骨架"). The official docs still say a file check cannot prove the absence of vocal leakage — confirm by listening.

---

### 📦 Installation

**Method 1: ComfyUI Manager (Recommended)**
Search for `XB_ToolBox` in the ComfyUI Manager and click install.

**Method 2: Manual Git Clone**
Navigate to your ComfyUI `custom_nodes` directory and run:

```bash
git clone https://github.com/wjluoxiao/XB_ToolBox.git
```

(Note: This extension relies purely on the native ComfyUI ecosystem through elegant Python/JS architecture. NO extra pip dependencies required! Plug and play.)

---

📝 License
This project is open-sourced under the Apache-2.0 License. It guarantees the freedom to share while protecting the patent defense rights of the core architecture code.

---