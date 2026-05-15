import comfy.model_patcher
import torch

class XB_SageAttentionAccelerator:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "preset": ([
                    "Mode A (128x128x32)", 
                    "Mode B (128x64x96)", 
                    "Mode C (128x16x16)", 
                    "Mode D (64x64x16)", 
                ], {"default": "Mode C (128x16x16)"}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "patch"
    CATEGORY = "XB_ToolBox/VRAM_Hacks"

    def patch(self, model, preset):
        configs = {
            "Mode A (128x128x32)":     {'M': 128,  'N': 128, 'GROUP': 32, 'WAVE': 2, 'WARP': 8, 'NSTAGES': 1},
            "Mode B (128x64x96)":     {'M': 128,  'N': 64, 'GROUP': 96, 'WAVE': 3, 'WARP': 8, 'NSTAGES': 2},
            "Mode C (128x16x16)":     {'M': 128,  'N': 16, 'GROUP': 16, 'WAVE': 2, 'WARP': 4, 'NSTAGES': 2},
            "Mode D (64x64x16)":     {'M': 64,  'N': 64, 'GROUP': 16, 'WAVE': 4, 'WARP': 4, 'NSTAGES': 2},
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
                
            if mask is not None:
                if mask.ndim == 2: mask = mask.unsqueeze(0)
                if mask.ndim == 3: mask = mask.unsqueeze(1)
            
            out = sageattn(q, k, v, is_causal=False, tensor_layout=tensor_layout, sage_config=selected_cfg).to(in_dtype)
            
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