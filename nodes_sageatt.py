import torch
from comfy.ldm.modules.attention import wrap_attn

# ============================================================
# XB_SageAttentionAccelerator — SageAttention 加速器
# ============================================================
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
        # ── 关闭：节点完全不生效，直接透传模型 ──
        if preset == "关闭":
            print("\033[96m[XB-BOX]\033[0m: SageAttention 已关闭，模型直接透传")
            return (model,)

        # ── 自动：一字不差使用 KJNodes 的 auto 逻辑 ──
        if preset == "自动":
            try:
                from sageattention import sageattn
            except ImportError:
                raise Exception("🚨 Error: sageattention module not found. Please verify installation.")

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

            print("\033[96m[XB-BOX]\033[0m: SageAttention 引擎切换至 \033[92m自动 (KJNodes auto)\033[0m")
            return (m,)

        # ── 内置/自定模式：使用指定 sage_config 参数 ──
        configs = {
            "内置模式 A (128x128x32)": {'M': 128,  'N': 128, 'GROUP': 32, 'WAVE': 2, 'WARP': 8, 'NSTAGES': 1},
            "内置模式 B (128x64x96)": {'M': 128,  'N': 64, 'GROUP': 96, 'WAVE': 3, 'WARP': 8, 'NSTAGES': 2},
            "内置模式 C (128x16x16)": {'M': 128,  'N': 16, 'GROUP': 16, 'WAVE': 2, 'WARP': 4, 'NSTAGES': 2},
            "内置模式 D (64x64x16)": {'M': 64,  'N': 64, 'GROUP': 16, 'WAVE': 4, 'WARP': 4, 'NSTAGES': 2},
            "自定模式 A (机智启动器)": {'M': 128, 'N': 128, 'GROUP': 16, 'WAVE': 4, 'WARP': 8, 'NSTAGES': 1},
            "自定模式 B (机智启动器)": {'M': 128, 'N': 16, 'GROUP': 8, 'WAVE': 2, 'WARP': 8, 'NSTAGES': 2},
            "自定模式 C (机智启动器)": {'M': 64, 'N': 128, 'GROUP': 96, 'WAVE': 2, 'WARP': 2, 'NSTAGES': 1},
        }

        selected_cfg = configs[preset]

        def attention_override_sage(func, q, k, v, heads, mask=None, attn_precision=None,
                                     skip_reshape=False, skip_output_reshape=False, **kwargs):
            try:
                from sageattention import sageattn
            except ImportError:
                raise Exception("🚨 Error: sageattention module not found. Please verify installation.")

            in_dtype = v.dtype

            if q.dtype == torch.float32 or k.dtype == torch.float32 or v.dtype == torch.float32:
                q, k, v = q.to(torch.float16), k.to(torch.float16), v.to(torch.float16)

            if skip_reshape:
                b, _, _, dim_head = q.shape
                tensor_layout = "HND"
            else:
                b, _, dim_head = q.shape
                dim_head //= heads
                q = q.view(b, -1, heads, dim_head)
                k = k.view(b, -1, heads, dim_head)
                v = v.view(b, -1, heads, dim_head)
                tensor_layout = "NHD"

            # 🛡️ 非2的幂Head Dim → 退回原生SDPA
            if dim_head not in (16, 32, 64, 128, 256):
                print("\033[93m[SageAttn]\033[0m: Unsupported head_dim ({}) — falling back to SDPA.".format(dim_head))
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            # 🛡️ 有attn_mask → sage_config 路径不支持，退回原生SDPA
            if mask is not None:
                print("\033[93m[SageAttn]\033[0m: Attention mask detected — falling back to SDPA.")
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

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

        print(f"\033[96m[XB-BOX]\033[0m: SageAttention engine switched to \033[92m{preset}\033[0m")

        return (m,)