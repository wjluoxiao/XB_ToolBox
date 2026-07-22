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

        # ── 全局容错：任何异常（缺 sageattention / 缺 MSVC / DLL 错误 等）自动跳过 ──
        try:
            return self._apply_patch(model, preset)
        except Exception as e:
            import traceback
            print(f"\n\033[93m[XB_ToolBox 警告] SageAttention 节点异常，自动跳过！工作流继续运行。\033[0m")
            print(f"\033[93m[XB_ToolBox 错误信息]\033[0m {e}")
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
        from sageattention import sageattn

        _warned = {}  # 去重：每个警告只打印一次

        def attention_override_sage(func, q, k, v, heads, mask=None, attn_precision=None,
                                     skip_reshape=False, skip_output_reshape=False, **kwargs):
            in_dtype = v.dtype

            # 🛡️ 3D/4D 维度校验：非3D且非skip_reshape → 直接退回原生
            if q.ndim != 3 and not skip_reshape:
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            # ── 在修改 q/k/v 物理形态之前，先完成所有断路检查 ──
            if skip_reshape:
                # q 已是 4D: (b, heads, n, dim_head)，无需 reshape
                b, _, _, dim_head = q.shape
                tensor_layout = "HND"
            else:
                # q 是 3D: (b, n, heads*dim_head)，先提取维度信息，暂不 reshape
                b, _, d = q.shape
                dim_head = d // heads
                tensor_layout = "NHD"

            # 🛡️ 有attn_mask → SageAttention 不支持，退回原生SDPA
            if mask is not None:
                if "mask" not in _warned:
                    print("\033[93m[SageAttn]\033[0m: Attention mask detected — falling back to SDPA.")
                    _warned["mask"] = True
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            # ── 动态补零策略：非标 dim_head 补齐到标准值，让 SageAttention 满血加速 ──
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
                    # dim_head > 256，无法补零，降级 SDPA
                    if "large_dim" not in _warned:
                        print("\033[93m[SageAttn]\033[0m: dim_head ({}) exceeds max supported — falling back to SDPA."
                              .format(_orig_dim_head))
                        _warned["large_dim"] = True
                    return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                               skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)

            # ── 通过安全检查后，进行 dtype 转换和 reshape（用原始 dim_head）──
            if q.dtype == torch.float32 or k.dtype == torch.float32 or v.dtype == torch.float32:
                q, k, v = q.to(torch.float16), k.to(torch.float16), v.to(torch.float16)

            if not skip_reshape:
                q = q.view(b, -1, heads, _orig_dim_head)
                k = k.view(b, -1, heads, _orig_dim_head)
                v = v.view(b, -1, heads, _orig_dim_head)

            # 🛡️ 备份原始未补零张量 — fallback 时的救命稻草，防止维度爆炸
            _orig_q, _orig_k, _orig_v = q, k, v

            # ── 动态补零：在最后一维（head_dim）补零并对 Q/K 做温度修正 ──
            if _pad_target is not None:
                _pad_len = _pad_target - _orig_dim_head
                q = torch.nn.functional.pad(q, (0, _pad_len))
                k = torch.nn.functional.pad(k, (0, _pad_len))
                v = torch.nn.functional.pad(v, (0, _pad_len))
                # 修正 softmax 温度：SageAttn 内部用 sqrt(pad_dim)，我们需等效 sqrt(orig_dim)
                q = q * _scale
                k = k * _scale
                dim_head = _pad_target  # 后续代码（如 sageattn 计算）用 padded dim_head

            is_causal = kwargs.get("is_causal", False)
            try:
                out = sageattn(q, k, v, is_causal=is_causal, tensor_layout=tensor_layout,
                               sage_config=selected_cfg).to(in_dtype)
            except Exception as e:
                if "sage_fallback" not in _warned:
                    print("\033[93m[SageAttn]\033[0m: SageAttention kernel failed (dim_head={}) — falling back to SDPA. "
                          "Error: {}".format(_orig_dim_head, str(e)[:120]))
                    _warned["sage_fallback"] = True
                # 🛡️ 使用备份的原始未补零张量，避免 128 维 vs 120 维的形状爆炸
                if skip_reshape:
                    return func(_orig_q, _orig_k, _orig_v, heads, mask=mask, attn_precision=attn_precision,
                               skip_reshape=True, skip_output_reshape=skip_output_reshape, **kwargs)
                else:
                    q_3d = _orig_q.reshape(b, -1, heads * _orig_dim_head)
                    k_3d = _orig_k.reshape(b, -1, heads * _orig_dim_head)
                    v_3d = _orig_v.reshape(b, -1, heads * _orig_dim_head)
                    return func(q_3d, k_3d, v_3d, heads, mask=mask, attn_precision=attn_precision,
                               skip_reshape=False, skip_output_reshape=False, **kwargs)

            # ── 补零模式：切掉补零部分，恢复原始 dim_head ──
            if _pad_target is not None:
                out = out[..., :_orig_dim_head]
                dim_head = _orig_dim_head  # 恢复，供后续 reshape 使用

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