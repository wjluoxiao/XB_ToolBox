import torch

# ============================================================
# XB_SageAttentionAccelerator — SageAttention 加速器
# ============================================================
class XB_SageAttentionAccelerator:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "preset": ([
                    "内置模式 A (128x128x32)", 
                    "内置模式 B (128x64x96)", 
                    "内置模式 C (128x16x16)", 
                    "内置模式 D (64x64x16)", 
                    "自定模式 A (机智启动器)",
                    "自定模式 B (机智启动器)",
                    "自定模式 C (机智启动器)",
                ], {"default": "内置模式 C (128x16x16)"}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "patch"
    CATEGORY = "XB_ToolBox/VRAM_Hacks"

    def patch(self, model, preset):
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
        
        def attention_override_sage(func, q, k, v, heads, mask=None, attn_precision=None, skip_reshape=False, skip_output_reshape=False, **kwargs):
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
            
            # 🛡️ 有attn_mask → sageattn内核不支持，退回原生SDPA并警告
            if mask is not None:
                print("\033[93m[SageAttn]\033[0m: Attention mask detected — falling back to SDPA.")
                return func(q, k, v, heads, mask=mask, attn_precision=attn_precision,
                           skip_reshape=skip_reshape, skip_output_reshape=skip_output_reshape, **kwargs)
            
            # 传递is_causal（sageattn有独立的causal内核）
            is_causal = kwargs.get("is_causal", False)
            out = sageattn(q, k, v, is_causal=is_causal, tensor_layout=tensor_layout, sage_config=selected_cfg).to(in_dtype)
            
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