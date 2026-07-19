"""
XB_Sage_BlockSwap — Sage + 分块 黄金搭档

将 XB_SageAttentionAccelerator（Sage注意力加速）与 XB_UNetBlockSwap（物理分块交换）
合并为一个节点，实现两个节点串联的效果：先挂载 Sage 加速补丁，再做分块显存优化。
"""

import gc
import sys
import torch
import traceback
from typing import Optional

import comfy.model_management as mm
from comfy.patcher_extension import CallbacksMP
from comfy.model_patcher import ModelPatcher
from comfy.ldm.modules.attention import wrap_attn

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable


# ──────────────────────────────────────────────
# 复用自 nodes_blockswap.py 的工具函数
# ──────────────────────────────────────────────

def _is_dynamic_vram_active() -> bool:
    """仅当用户显式传参 --enable-dynamic-vram 时视为动态显存激活，分块节点休眠。"""
    if "--enable-dynamic-vram" in sys.argv:
        print("\n\033[93m[XB Sage+分块]\033[0m: ⚠️ 检测到 --enable-dynamic-vram，动态显存已启用。分块功能自动休眠。")
        return True
    return False


def _is_unsupported_model(diffusion_model) -> Optional[str]:
    """检测已知不支持物理分块的模型架构。"""
    model_type = type(diffusion_model).__name__
    blacklist = ["Lumina", "Lumina2", "ZImage", "HunyuanDiT", "ErnieImageModel"]
    for b in blacklist:
        if b in model_type:
            return model_type
    return None


# ──────────────────────────────────────────────
# 合并节点
# ──────────────────────────────────────────────

class XB_Sage_BlockSwap:
    """Sage + 分块 黄金搭档。

    输入一个模型，同时应用：
      1. SageAttention 加速：用 sageattn 替换原生注意力计算，加速推理
      2. 物理分块交换（Block Swap）：将指定数量的模型块卸载到系统内存，节省显存

    效果等同于先接 XB_SageAttentionAccelerator 再接 XB_UNetBlockSwap。
    """

    # ── Sage 预设配置表 ──
    SAGE_CONFIGS = {
        "自动": None,  # 使用 KJNodes 的 auto 逻辑
        "内置模式 A (128x128x32)": {'M': 128, 'N': 128, 'GROUP': 32, 'WAVE': 2, 'WARP': 8, 'NSTAGES': 1},
        "内置模式 B (128x64x96)":  {'M': 128, 'N': 64,  'GROUP': 96, 'WAVE': 3, 'WARP': 8, 'NSTAGES': 2},
        "内置模式 C (128x16x16)":  {'M': 128, 'N': 16,  'GROUP': 16, 'WAVE': 2, 'WARP': 4, 'NSTAGES': 2},
        "内置模式 D (64x64x16)":   {'M': 64,  'N': 64,  'GROUP': 16, 'WAVE': 4, 'WARP': 4, 'NSTAGES': 2},
        "自定模式 A (机智启动器)": {'M': 128, 'N': 128, 'GROUP': 16, 'WAVE': 4, 'WARP': 8, 'NSTAGES': 1},
        "自定模式 B (机智启动器)": {'M': 128, 'N': 16,  'GROUP': 8,  'WAVE': 2, 'WARP': 8, 'NSTAGES': 2},
        "自定模式 C (机智启动器)": {'M': 64,  'N': 128, 'GROUP': 96, 'WAVE': 2, 'WARP': 2, 'NSTAGES': 1},
    }

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL", {"tooltip": "输入模型（UNet / DiT / Checkpoint）"}),
                "sage_preset": ([
                    "关闭",
                    "自动",
                    "内置模式 A (128x128x32)",
                    "内置模式 B (128x64x96)",
                    "内置模式 C (128x16x16)",
                    "内置模式 D (64x64x16)",
                    "自定模式 A (机智启动器)",
                    "自定模式 B (机智启动器)",
                    "自定模式 C (机智启动器)",
                ], {"default": "关闭", "tooltip": "SageAttention 加速模式。关闭=仅分块不加速。"}),
                "blocks_to_swap": ("INT", {
                    "default": 10,
                    "min": 0,
                    "max": 200,
                    "step": 1,
                    "tooltip": "卸载到系统内存的核心模块数量。0=关闭分块，数值越大越省显存但越慢。"
                }),
            },
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    CATEGORY = "XB_ToolBox/VRAM_Hacks"
    FUNCTION = "apply"

    def apply(self, model: ModelPatcher, blocks_to_swap: int, sage_preset: str):
        # ── 步骤 1：Sage 加速（先修改计算图：注意力算子替换） ──
        model = self._apply_sage_attention(model, sage_preset)

        # ── 步骤 2：分块交换（后注册 ON_LOAD 回调：物理显存闸门） ──
        model = self._apply_block_swap(model, blocks_to_swap)

        return (model,)

    # ════════════════════════════════════════════
    # 分块交换逻辑（来自 XB_UNetBlockSwap）
    # ════════════════════════════════════════════

    def _apply_block_swap(self, model: ModelPatcher, blocks_to_swap: int) -> ModelPatcher:
        if not isinstance(model, ModelPatcher):
            return model

        if _is_dynamic_vram_active():
            return model

        if blocks_to_swap == 0:
            print("\033[96m[XB Sage+分块]\033[0m: 分块数量为 0，跳过 Block Swap")
            return model

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory,
                        force_patch_weights, full_load):
            base_model = model_patcher.model
            main_device = model_patcher.load_device

            diffusion_model = getattr(base_model, 'diffusion_model', None)
            if not diffusion_model:
                return

            unsupported_name = _is_unsupported_model(diffusion_model)
            if unsupported_name:
                print(f"\033[93m[XB Sage+分块]\033[0m: 模型 ({unsupported_name}) "
                      f"属于高耦合架构，不支持物理分块。已自动跳过！")
                return

            all_blocks = []
            block_paths = [
                'transformer_blocks', 'blocks', 'down_blocks', 'up_blocks', 'mid_block',
                'layers', 'attention_blocks', 'input_blocks', 'middle_block', 'output_blocks',
                'double_blocks', 'single_blocks', 'joint_blocks'
            ]

            for path in block_paths:
                if hasattr(diffusion_model, path):
                    attr = getattr(diffusion_model, path)
                    if isinstance(attr, (list, torch.nn.ModuleList)):
                        for item in attr:
                            all_blocks.append(item)
                    elif isinstance(attr, torch.nn.Module) and path in ['mid_block', 'middle_block']:
                        all_blocks.append(attr)

            if not all_blocks:
                return

            total_blocks = len(all_blocks)
            if blocks_to_swap > total_blocks:
                effective = total_blocks
                tag = "匹配最大可分块参数"
            else:
                effective = blocks_to_swap
                tag = "匹配用户设置的参数"

            print(f"\033[96m[XB Sage+分块]\033[0m: 静态物理分块交换已激活！"
                  f"已找到 {total_blocks} 个引擎模块，分割 {effective} 个分块（{tag}）。")

            for b, block in tqdm(enumerate(all_blocks), total=total_blocks,
                                 desc="[Sage+分块] Slicing pipeline"):
                if b > effective:
                    block.to(main_device)
                else:
                    block.to(model_patcher.offload_device)

            mm.soft_empty_cache()
            gc.collect()

        model = model.clone()
        model.add_callback(CallbacksMP.ON_LOAD, swap_blocks)

        print(f"\033[96m[XB Sage+分块]\033[0m: ✅ Block Swap 回调已挂载 "
              f"(blocks_to_swap={blocks_to_swap})")
        return model

    # ════════════════════════════════════════════
    # Sage 加速逻辑（来自 XB_SageAttentionAccelerator）
    # ════════════════════════════════════════════

    def _apply_sage_attention(self, model: ModelPatcher, preset: str) -> ModelPatcher:
        if preset == "关闭":
            print("\033[96m[XB Sage+分块]\033[0m: SageAttention 已关闭，仅启用分块功能")
            return model

        # 全局容错
        try:
            return self._do_sage_patch(model, preset)
        except Exception as e:
            print(f"\n\033[93m[XB Sage+分块 警告] SageAttention 异常，自动跳过！"
                  f"分块功能仍然生效。\033[0m")
            print(f"\033[93m[XB Sage+分块 错误信息]\033[0m {e}")
            traceback.print_exc()
            return model

    def _do_sage_patch(self, model: ModelPatcher, preset: str) -> ModelPatcher:
        if preset == "自动":
            return self._sage_auto_mode(model)
        else:
            return self._sage_config_mode(model, preset)

    # ── 自动模式（KJNodes auto 逻辑） ──

    def _sage_auto_mode(self, model: ModelPatcher) -> ModelPatcher:
        from sageattention import sageattn

        def sage_func(q, k, v, is_causal=False, attn_mask=None, tensor_layout="NHD"):
            return sageattn(q, k, v, is_causal=is_causal,
                            attn_mask=attn_mask, tensor_layout=tensor_layout)

        @wrap_attn
        def attention_sage(q, k, v, heads, mask=None, attn_precision=None,
                            skip_reshape=False, skip_output_reshape=False, **kwargs):
            if kwargs.get("low_precision_attention", True) is False:
                from comfy.ldm.modules.attention import attention_pytorch
                return attention_pytorch(q, k, v, heads, mask=mask,
                                         skip_reshape=skip_reshape,
                                         skip_output_reshape=skip_output_reshape, **kwargs)
            in_dtype = v.dtype
            if q.dtype == torch.float32 or k.dtype == torch.float32 or v.dtype == torch.float32:
                q, k, v = q.to(torch.float16), k.to(torch.float16), v.to(torch.float16)
            if skip_reshape:
                b, _, _, dim_head = q.shape
                tensor_layout = "HND"
            else:
                b, _, dim_head = q.shape
                dim_head //= heads
                q, k, v = map(
                    lambda t: t.view(b, -1, heads, dim_head),
                    (q, k, v),
                )
                tensor_layout = "NHD"
            if mask is not None:
                if mask.ndim == 2:
                    mask = mask.unsqueeze(0)
                if mask.ndim == 3:
                    mask = mask.unsqueeze(1)
            out = sage_func(q, k, v, attn_mask=mask, is_causal=False,
                            tensor_layout=tensor_layout).to(in_dtype)
            if tensor_layout == "HND":
                if not skip_output_reshape:
                    out = out.transpose(1, 2).reshape(b, -1, heads * dim_head)
            else:
                if skip_output_reshape:
                    out = out.transpose(1, 2)
                else:
                    out = out.reshape(b, -1, heads * dim_head)
            return out

        m = model.clone()
        if "transformer_options" not in m.model_options:
            m.model_options["transformer_options"] = {}
        m.model_options["transformer_options"]["optimized_attention_override"] = \
            lambda func, *args, **kwargs: attention_sage.__wrapped__(*args, **kwargs)

        print("\033[96m[XB Sage+分块]\033[0m: SageAttention 引擎切换至 \033[92m自动 (KJNodes auto)\033[0m")
        return m

    # ── 内置/自定模式（sage_config 参数） ──

    def _sage_config_mode(self, model: ModelPatcher, preset: str) -> ModelPatcher:
        selected_cfg = self.SAGE_CONFIGS[preset]
        from sageattention import sageattn

        _warned = {}

        def attention_override_sage(func, q, k, v, heads, mask=None, attn_precision=None,
                                    skip_reshape=False, skip_output_reshape=False, **kwargs):
            in_dtype = v.dtype

            if q.ndim != 3 and not skip_reshape:
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            if skip_reshape:
                b, _, _, dim_head = q.shape
                tensor_layout = "HND"
            else:
                b, _, d = q.shape
                dim_head = d // heads
                tensor_layout = "NHD"

            if dim_head not in (16, 32, 64, 128, 256):
                if "dim_head" not in _warned:
                    print("\033[93m[XB Sage+分块]\033[0m: Unsupported head_dim ({}) "
                          "— falling back to SDPA.".format(dim_head))
                    _warned["dim_head"] = True
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            if mask is not None:
                if "mask" not in _warned:
                    print("\033[93m[XB Sage+分块]\033[0m: Attention mask detected "
                          "— falling back to SDPA.")
                    _warned["mask"] = True
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            if q.dtype == torch.float32 or k.dtype == torch.float32 or v.dtype == torch.float32:
                q, k, v = q.to(torch.float16), k.to(torch.float16), v.to(torch.float16)

            if not skip_reshape:
                q = q.view(b, -1, heads, dim_head)
                k = k.view(b, -1, heads, dim_head)
                v = v.view(b, -1, heads, dim_head)

            is_causal = kwargs.get("is_causal", False)
            out = sageattn(q, k, v, is_causal=is_causal, tensor_layout=tensor_layout,
                           sage_config=selected_cfg).to(in_dtype)

            if tensor_layout == "HND":
                if not skip_output_reshape:
                    out = out.transpose(1, 2).reshape(b, -1, heads * dim_head)
            else:
                if skip_output_reshape:
                    out = out.transpose(1, 2)
                else:
                    out = out.reshape(b, -1, heads * dim_head)

            return out

        m = model.clone()
        if "transformer_options" not in m.model_options:
            m.model_options["transformer_options"] = {}
        m.model_options["transformer_options"]["optimized_attention_override"] = attention_override_sage

        print(f"\033[96m[XB Sage+分块]\033[0m: SageAttention 引擎切换至 \033[92m{preset}\033[0m")
        return m
