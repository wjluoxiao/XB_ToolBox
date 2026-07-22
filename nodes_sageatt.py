"""
XB-SageAttention Accelerator
=============================
保持原版 KJNodes 设计, 仅添加 GPU 信息日志。

工作模式:
  - 关闭:           直接透传模型
  - 自动:           委托 KJNodes auto 逻辑 (sageattn 默认参数)
  - 内置模式 A~D:   自定义 sage_config (M/N/GROUP/WAVE/WARP/NSTAGES)
  - 自定模式 A~C:   自定义 sage_config (配合外部调参软件)

A卡兼容:
  - RDNA3:  Sage 1.0.6 不支持 sage_config, 选中内置/自定时会 fallback 到 SDPA
  - RDNA4:  Sage 2.2.0 完全兼容
  - N卡:    Sage 2.x 完全兼容
"""

import torch
from comfy.ldm.modules.attention import wrap_attn


# ── GPU 信息 (仅日志用途) ──
def _is_rocm():
    try:
        return torch.cuda.is_available() and hasattr(torch.version, "hip") and torch.version.hip is not None
    except Exception:
        return False

def _gpu_label():
    try:
        if not torch.cuda.is_available():
            return "CPU"
        if _is_rocm():
            arch = ""
            try:
                raw = torch.cuda.get_device_properties(0).gcnArchName
                arch = " " + raw.split(":")[0] if raw else ""
            except Exception:
                pass
            return f"ROCm{arch}"
        return "CUDA"
    except Exception:
        return "Unknown"

_GPU = _gpu_label()
print(f"[XB-SageAttn] GPU: {_GPU}, Sage节点已就绪")


# ══════════════════════════════════════════════════════════
#  XB_SageAttentionAccelerator (保持原版设计)
# ══════════════════════════════════════════════════════════

class XB_SageAttentionAccelerator:
    """SageAttention 加速补丁节点。

    选项说明:
      - 关闭:           节点完全不生效，直接透传模型
      - 自动:           一字不差使用 KJNodes 的 auto 逻辑 (sageattn 默认参数)
      - 内置模式 A~D:   使用指定 sage_config 参数 (M/N/GROUP/WAVE/WARP/NSTAGES)
      - 自定模式 A~C:   自定义 sage_config 参数
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "preset": ([
                    "关闭",
                    "自动",
                    "内置模式 A (128x128x32)",
                    "内置模式 B (128x64x96)",
                    "内置模式 C (128x16x16)",
                    "内置模式 D (64x64x16)",
                    "自定模式 A (机智启动器)",
                    "自定模式 B (机智启动器)",
                    "自定模式 C (机智启动器)",
                ], {"default": "关闭"}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "patch"
    CATEGORY = "XB_ToolBox/VRAM_Hacks"

    def patch(self, model, preset):
        if preset == "关闭":
            print(f"\033[96m[XB-SageAttn]\033[0m: 已关闭, 模型透传 (GPU={_GPU})")
            return (model,)

        try:
            return self._apply_patch(model, preset)
        except Exception as e:
            import traceback
            print(f"\n\033[93m[XB-SageAttn 警告] 节点异常，自动跳过！工作流继续运行。\033[0m")
            print(f"\033[93m[XB-SageAttn 错误] GPU={_GPU}, preset={preset}\033[0m")
            print(f"\033[93m[XB-SageAttn 详情]\033[0m {e}")
            traceback.print_exc()
            return (model,)

    def _apply_patch(self, model, preset):
        # ── 自动：一字不差使用 KJNodes 的 auto 逻辑 ──
        if preset == "自动":
            from sageattention import sageattn

            def sage_func(q, k, v, is_causal=False, attn_mask=None, tensor_layout="NHD"):
                return sageattn(q, k, v, is_causal=is_causal, attn_mask=attn_mask, tensor_layout=tensor_layout)

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

            print(f"\033[96m[XB-SageAttn]\033[0m: 引擎 → \033[92m自动 (KJNodes auto)\033[0m (GPU={_GPU})")
            return (m,)

        # ── 内置/自定模式：使用指定 sage_config 参数 ──
        configs = {
            "内置模式 A (128x128x32)": {'M': 128,  'N': 128, 'GROUP': 32, 'WAVE': 2, 'WARP': 8, 'NSTAGES': 1},
            "内置模式 B (128x64x96)":  {'M': 128,  'N': 64,  'GROUP': 96, 'WAVE': 3, 'WARP': 8, 'NSTAGES': 2},
            "内置模式 C (128x16x16)":  {'M': 128,  'N': 16,  'GROUP': 16, 'WAVE': 2, 'WARP': 4, 'NSTAGES': 2},
            "内置模式 D (64x64x16)":   {'M': 64,   'N': 64,  'GROUP': 16, 'WAVE': 4, 'WARP': 4, 'NSTAGES': 2},
            "自定模式 A (机智启动器)": {'M': 128, 'N': 128, 'GROUP': 16, 'WAVE': 4, 'WARP': 8, 'NSTAGES': 1},
            "自定模式 B (机智启动器)": {'M': 128, 'N': 16,  'GROUP': 8,  'WAVE': 2, 'WARP': 8, 'NSTAGES': 2},
            "自定模式 C (机智启动器)": {'M': 64,  'N': 128, 'GROUP': 96, 'WAVE': 2, 'WARP': 2, 'NSTAGES': 1},
        }

        selected_cfg = configs[preset]
        from sageattention import sageattn

        _warned = {}

        def attention_override_sage(func, q, k, v, heads, mask=None, attn_precision=None,
                                     skip_reshape=False, skip_output_reshape=False, **kwargs):
            in_dtype = v.dtype

            # 3D/4D 维度校验
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

            if mask is not None:
                if "mask" not in _warned:
                    print("\033[93m[SageAttn]\033[0m: Attention mask detected — falling back to SDPA.")
                    _warned["mask"] = True
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            # 动态补零策略
            _STANDARD_DIMS = (16, 32, 64, 128, 256)
            _orig_dim_head = dim_head
            _pad_target = None
            if dim_head not in _STANDARD_DIMS:
                for _sd in _STANDARD_DIMS:
                    if _sd >= dim_head:
                        _pad_target = _sd
                        break
                if _pad_target is not None:
                    if "pad" not in _warned:
                        print("\033[96m[SageAttn]\033[0m: Padding dim_head {} → {} for SageAttention compatibility."
                              .format(dim_head, _pad_target))
                        _warned["pad"] = True
                    _scale = (float(_pad_target) / float(_orig_dim_head)) ** 0.25
                else:
                    if "large_dim" not in _warned:
                        print("\033[93m[SageAttn]\033[0m: dim_head ({}) exceeds max supported — falling back to SDPA."
                              .format(_orig_dim_head))
                        _warned["large_dim"] = True
                    return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                               skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            if q.dtype == torch.float32 or k.dtype == torch.float32 or v.dtype == torch.float32:
                q, k, v = q.to(torch.float16), k.to(torch.float16), v.to(torch.float16)

            if not skip_reshape:
                q = q.view(b, -1, heads, _orig_dim_head)
                k = k.view(b, -1, heads, _orig_dim_head)
                v = v.view(b, -1, heads, _orig_dim_head)

            _orig_q, _orig_k, _orig_v = q, k, v

            if _pad_target is not None:
                _pad_len = _pad_target - _orig_dim_head
                q = torch.nn.functional.pad(q, (0, _pad_len))
                k = torch.nn.functional.pad(k, (0, _pad_len))
                v = torch.nn.functional.pad(v, (0, _pad_len))
                q = q * _scale
                k = k * _scale
                dim_head = _pad_target

            is_causal = kwargs.get("is_causal", False)
            try:
                out = sageattn(q, k, v, is_causal=is_causal, tensor_layout=tensor_layout,
                               sage_config=selected_cfg).to(in_dtype)
            except Exception as e:
                if "sage_fallback" not in _warned:
                    print("\033[93m[SageAttn]\033[0m: SageAttention kernel failed (dim_head={}) — falling back to SDPA. "
                          "Error: {}".format(_orig_dim_head, str(e)[:120]))
                    _warned["sage_fallback"] = True
                if skip_reshape:
                    return func(_orig_q, _orig_k, _orig_v, heads, mask=mask, attn_precision=attn_precision,
                               skip_reshape=True, skip_output_reshape=skip_output_reshape, **kwargs)
                else:
                    q_3d = _orig_q.reshape(b, -1, heads * _orig_dim_head)
                    k_3d = _orig_k.reshape(b, -1, heads * _orig_dim_head)
                    v_3d = _orig_v.reshape(b, -1, heads * _orig_dim_head)
                    return func(q_3d, k_3d, v_3d, heads, mask=mask, attn_precision=attn_precision,
                               skip_reshape=False, skip_output_reshape=False, **kwargs)

            if _pad_target is not None:
                out = out[..., :_orig_dim_head]
                dim_head = _orig_dim_head

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

        print(f"\033[96m[XB-SageAttn]\033[0m: 引擎 → \033[92m{preset}\033[0m (GPU={_GPU})")

        return (m,)
