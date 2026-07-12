"""
XB-ToolBox INT8 ROCm 节点
========================
基于 ComfyUI-INT8-Fast-ROCM 适配，提供 INT8 量化推理支持。

节点列表：
- XB_UNetLoaderINTROCm    : INT8 UNet 模型加载器
- XB_INT8GroupedLoraROCm      : INT8 组合 LoRA
- XB_INT8ModelSaveROCm        : INT8 模型保存
- XB_INT8PreLoraLoaderROCm    : INT8 预加载 LoRA

优化项（相比原版）：
- AMD GPU autotune 配置（wavefront 64 适配）
- _quantize_rowwise_kernel 大矩阵循环支持
- 纯 Triton 实现的 round-to-nearest-even 舍入
"""

import torch
from torch import Tensor, nn
import torch.nn.functional as F
import logging
import os
import json
import folder_paths
import comfy.model_patcher
import comfy.memory_management
import comfy.model_management
import comfy.sd
import comfy.utils
import comfy.lora
import comfy.lora_convert
import comfy.model_detection
from comfy.cli_args import args

# =============================================================================
# Aimdo / File-slice 支持
# =============================================================================
try:
    import comfy_aimdo.host_buffer
    import comfy_aimdo.torch
    _AIMDO_FILE_SLICE_LOAD = True
except Exception:
    _AIMDO_FILE_SLICE_LOAD = False

# =============================================================================
# Triton 内核导入
# =============================================================================
try:
    import triton
    import triton.language as tl
    _TRITON_AVAILABLE = True
except ImportError:
    _TRITON_AVAILABLE = False
    triton = None
    tl = None
    print("XB INT8 ROCm: Triton not found, falling back to torch._int_mm")

_use_triton = True
CONVROT_GROUP_SIZE = 256  # Must be a power of 4 for Regular Hadamard

# =============================================================================
# Hadamard 缓存
# =============================================================================
_HADAMARD_CACHE: dict = {}

try:
    from scipy.linalg import hadamard as scipy_hadamard
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False


def build_hadamard(size: int, device=None, dtype=torch.float32):
    import math
    cache_key = (size, str(device), dtype)
    if cache_key in _HADAMARD_CACHE:
        return _HADAMARD_CACHE[cache_key]

    if size < 4 or (size & (size - 1)) != 0 or math.log(size, 4) % 1 != 0:
        raise ValueError(f"Regular Hadamard size must be a power of 4, got {size}")

    H4 = torch.tensor([
        [ 1,  1,  1, -1],
        [ 1,  1, -1,  1],
        [ 1, -1,  1,  1],
        [-1,  1,  1,  1]
    ], dtype=dtype, device=device)

    H = H4
    current_size = 4
    while current_size < size:
        H = torch.kron(H, H4)
        current_size *= 4

    H_normalized = H / (size ** 0.5)
    _HADAMARD_CACHE[cache_key] = H_normalized
    return H_normalized


def rotate_weight(weight: torch.Tensor, H: torch.Tensor, group_size: int) -> torch.Tensor:
    out_f, in_f = weight.shape
    if in_f % group_size != 0:
        raise ValueError(f"in_features {in_f} not divisible by group_size {group_size}")
    n_groups = in_f // group_size
    W_grouped = weight.view(out_f, n_groups, group_size)
    H_t = H.T.to(dtype=weight.dtype, device=weight.device)
    W_rot = torch.matmul(W_grouped, H_t)
    return W_rot.reshape(out_f, in_f)


def rotate_activation(x: torch.Tensor, H: torch.Tensor, group_size: int) -> torch.Tensor:
    orig_shape = x.shape
    features = orig_shape[-1]
    if features % group_size != 0:
        raise ValueError(f"features {features} not divisible by group_size {group_size}")
    n_groups = features // group_size
    x_grouped = x.view(*orig_shape[:-1], n_groups, group_size)
    H_dev = H.to(dtype=x.dtype, device=x.device)
    x_rot = torch.matmul(x_grouped, H_dev)
    return x_rot.view(orig_shape)


# =============================================================================
# 量化工具函数
# =============================================================================

def quantize_int8(x: Tensor, scale) -> Tensor:
    return x.float().mul(1.0 / scale).round_().clamp_(-128.0, 127.0).to(torch.int8)


def quantize_int8_tensorwise(x: Tensor) -> tuple:
    abs_max = x.abs().max()
    scale = (abs_max.float() / 127.0).clamp(min=1e-30)
    return quantize_int8(x, scale), scale


def quantize_int8_axiswise(x: Tensor, dim: int) -> tuple:
    abs_max = x.abs().amax(dim=dim, keepdim=True)
    scale = (abs_max.float() / 127.0).clamp(min=1e-30)
    return quantize_int8(x, scale), scale


def dequantize(q: Tensor, scale) -> Tensor:
    return q.float() * scale


def tensor_to_device_file_slice(tensor: Tensor, device: torch.device) -> Tensor:
    if (not _AIMDO_FILE_SLICE_LOAD or tensor.device.type != "cpu"
            or device is None or device.type != "cuda"):
        return tensor.to(device, non_blocking=True)
    size = tensor.numel() * tensor.element_size()
    if size == 0:
        return tensor.to(device, non_blocking=True)
    hostbuf = comfy_aimdo.host_buffer.HostBuffer(size)
    host_tensor = comfy_aimdo.torch.hostbuf_to_tensor(hostbuf)
    host_view = host_tensor[:size].view(dtype=tensor.dtype).view(tensor.shape)
    if comfy.memory_management.read_tensor_file_slice_into(tensor, host_view):
        out = torch.empty_like(tensor, device=device)
        out.copy_(host_view, non_blocking=False)
        return out
    return tensor.to(device, non_blocking=True)


def stochastic_round_int8_delta(x: Tensor, scale, seed: int = 0) -> Tensor:
    generator = torch.Generator(device=x.device)
    generator.manual_seed(seed)
    if isinstance(scale, torch.Tensor):
        scale = scale.to(x.device)
    x_scaled = x / scale
    x_floor = torch.floor(x_scaled)
    fraction = x_scaled - x_floor
    del x_scaled
    random_vals = torch.rand(x_floor.shape, generator=generator, device=x.device, dtype=x_floor.dtype)
    x_rounded = torch.where(random_vals < fraction, x_floor + 1, x_floor)
    del random_vals, fraction, x_floor
    return torch.clamp(x_rounded, -128, 127).to(torch.int8)


# =============================================================================
# Triton 内核 (含 ROCM 优化)
# =============================================================================

if _TRITON_AVAILABLE:

    @triton.jit
    def _quantize_rowwise_kernel(
        x_ptr, y_ptr, s_ptr, n_elements,
        BLOCK_SIZE: tl.constexpr,
    ):
        """行级量化内核 —— 支持大矩阵循环 (ROCM 优化)"""
        row_idx = tl.program_id(0)
        x_row_ptr = x_ptr + row_idx * n_elements
        y_row_ptr = y_ptr + row_idx * n_elements
        offsets = tl.arange(0, BLOCK_SIZE)

        # 初始 max_val = 0
        max_val = 0.0

        # 循环处理所有列 (ROCM 优化: 支持 cols > BLOCK_SIZE)
        for col_start in range(0, n_elements, BLOCK_SIZE):
            mask = (offsets + col_start) < n_elements
            x = tl.load(x_row_ptr + col_start + offsets, mask=mask, other=0.0)
            abs_x = tl.abs(x)
            max_val = tl.maximum(max_val, tl.max(abs_x, axis=0))

        # 计算 scale
        scale = tl.maximum(max_val / 127.0, 1e-30)

        # 循环量化所有列
        for col_start in range(0, n_elements, BLOCK_SIZE):
            mask = (offsets + col_start) < n_elements
            x = tl.load(x_row_ptr + col_start + offsets, mask=mask, other=0.0)
            q_f = x / scale
            # ROCM 优化: 纯 Triton 实现的 round-to-nearest-even (替代 libdevice.rint)
            q_floor = tl.floor(q_f)
            q_frac = q_f - q_floor
            q_round_up = q_frac > 0.5
            q_exact_half = q_frac == 0.5
            q_is_odd = (tl.floor(q_floor).to(tl.int32) % 2) == 1
            q_rounded = tl.where(q_round_up | (q_exact_half & q_is_odd), q_floor + 1.0, q_floor)
            q_i = tl.clamp(q_rounded, -128.0, 127.0).to(tl.int32)
            tl.store(y_row_ptr + col_start + offsets, q_i.to(tl.int8), mask=mask)

        tl.store(s_ptr + row_idx, scale.to(tl.float32))


    def triton_quantize_rowwise(x: torch.Tensor):
        rows, cols = x.shape
        y = torch.empty_like(x, dtype=torch.int8)
        s = torch.empty((rows, 1), device=x.device, dtype=torch.float32)
        BLOCK_SIZE = triton.next_power_of_2(min(cols, 4096))
        if BLOCK_SIZE < 128:
            BLOCK_SIZE = 128
        grid = (rows,)
        _quantize_rowwise_kernel[grid](x, y, s, cols, BLOCK_SIZE=BLOCK_SIZE)
        return y, s


    # AMD GPU autotune 配置: wavefront=64, 偏好 warp 数为 4 的倍数
    @triton.autotune(
        configs=[
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 64, 'GROUP_SIZE_M': 8}, num_stages=3, num_warps=8),
            triton.Config({'BLOCK_M': 64,  'BLOCK_N': 256, 'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 64,  'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            triton.Config({'BLOCK_M': 64,  'BLOCK_N': 128, 'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 32,  'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            # ROCM 优化: AMD wavefront=64 专用配置
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 128, 'GROUP_SIZE_M': 4}, num_stages=2, num_warps=4),
            triton.Config({'BLOCK_M': 256, 'BLOCK_N': 128, 'BLOCK_K': 64, 'GROUP_SIZE_M': 4}, num_stages=2, num_warps=8),
            triton.Config({'BLOCK_M': 64,  'BLOCK_N': 64,  'BLOCK_K': 128, 'GROUP_SIZE_M': 4}, num_stages=3, num_warps=4),
        ],
        key=['M', 'N', 'K'],
    )
    @triton.jit
    def _int8_matmul_dequant_kernel(
        a_ptr, b_ptr, c_ptr, a_scale_ptr, b_scale_ptr, bias_ptr,
        M, N, K,
        stride_am, stride_ak, stride_bk, stride_bn, stride_cm, stride_cn,
        BLOCK_M: tl.constexpr, BLOCK_N: tl.constexpr, BLOCK_K: tl.constexpr,
        GROUP_SIZE_M: tl.constexpr, HAS_BIAS: tl.constexpr
    ):
        pid = tl.program_id(axis=0)
        num_pid_m = tl.cdiv(M, BLOCK_M)
        num_pid_n = tl.cdiv(N, BLOCK_N)
        num_pid_in_group = GROUP_SIZE_M * num_pid_n
        group_id = pid // num_pid_in_group
        first_pid_m = group_id * GROUP_SIZE_M
        group_size_m = min(num_pid_m - first_pid_m, GROUP_SIZE_M)
        pid_m = first_pid_m + (pid % group_size_m)
        pid_n = (pid % num_pid_in_group) // group_size_m

        offs_am = (pid_m * BLOCK_M + tl.arange(0, BLOCK_M)) % M
        offs_bn = (pid_n * BLOCK_N + tl.arange(0, BLOCK_N)) % N
        offs_k = tl.arange(0, BLOCK_K)

        a_ptrs = a_ptr + (offs_am[:, None] * stride_am + offs_k[None, :] * stride_ak)
        b_ptrs = b_ptr + (offs_k[:, None] * stride_bk + offs_bn[None, :] * stride_bn)

        accumulator = tl.zeros((BLOCK_M, BLOCK_N), dtype=tl.int32)

        for k in range(0, tl.cdiv(K, BLOCK_K)):
            a = tl.load(a_ptrs, mask=offs_k[None, :] < K - k * BLOCK_K, other=0.0)
            b = tl.load(b_ptrs, mask=offs_k[:, None] < K - k * BLOCK_K, other=0.0)
            accumulator += tl.dot(a, b)
            a_ptrs += BLOCK_K * stride_ak
            b_ptrs += BLOCK_K * stride_bk

        scale_a = tl.load(a_scale_ptr + offs_am)
        scale_b = tl.load(b_scale_ptr)
        c = accumulator.to(tl.float32)
        total_scale = scale_a[:, None] * scale_b
        c = c * total_scale

        if HAS_BIAS:
            bias = tl.load(bias_ptr + offs_bn)
            c = c + bias[None, :]

        c_ptrs = c_ptr + stride_cm * offs_am[:, None] + stride_cn * offs_bn[None, :]
        c_mask = (offs_am[:, None] < M) & (offs_bn[None, :] < N)
        tl.store(c_ptrs, c, mask=c_mask)


    def triton_int8_linear(x: torch.Tensor, weight: torch.Tensor, weight_scale, bias=None,
                           compute_dtype=torch.float16):
        x_shape_orig = x.shape
        x_2d = x.reshape(-1, x_shape_orig[-1])
        M, K = x_2d.shape
        N = weight.shape[0]

        x_int8, x_scale = triton_quantize_rowwise(x_2d)
        output = torch.empty((M, N), device=x.device, dtype=compute_dtype)

        if not isinstance(weight_scale, torch.Tensor):
            weight_scale = torch.tensor([weight_scale], device=x.device, dtype=torch.float32)
        else:
            weight_scale = weight_scale.to(x.device, non_blocking=True).reshape(1) \
                if weight_scale.numel() == 1 else weight_scale.to(x.device, non_blocking=True)

        grid = lambda META: (triton.cdiv(M, META['BLOCK_M']) * triton.cdiv(N, META['BLOCK_N']),)
        has_bias = bias is not None
        bias_ptr = bias if has_bias else x

        _int8_matmul_dequant_kernel[grid](
            a_ptr=x_int8, b_ptr=weight, c_ptr=output,
            a_scale_ptr=x_scale, b_scale_ptr=weight_scale, bias_ptr=bias_ptr,
            M=M, N=N, K=K,
            stride_am=x_int8.stride(0), stride_ak=x_int8.stride(1),
            stride_bk=weight.stride(1), stride_bn=weight.stride(0),
            stride_cm=output.stride(0), stride_cn=output.stride(1),
            HAS_BIAS=has_bias
        )
        return output.reshape(x_shape_orig[:-1] + (N,))


    @triton.autotune(
        configs=[
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 64, 'GROUP_SIZE_M': 8}, num_stages=3, num_warps=8),
            triton.Config({'BLOCK_M': 64,  'BLOCK_N': 256, 'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 64,  'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            triton.Config({'BLOCK_M': 64,  'BLOCK_N': 128, 'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 32,  'BLOCK_K': 32, 'GROUP_SIZE_M': 8}, num_stages=4, num_warps=4),
            # ROCM 优化
            triton.Config({'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 128, 'GROUP_SIZE_M': 4}, num_stages=2, num_warps=4),
            triton.Config({'BLOCK_M': 256, 'BLOCK_N': 128, 'BLOCK_K': 64, 'GROUP_SIZE_M': 4}, num_stages=2, num_warps=8),
            triton.Config({'BLOCK_M': 64,  'BLOCK_N': 64,  'BLOCK_K': 128, 'GROUP_SIZE_M': 4}, num_stages=3, num_warps=4),
        ],
        key=['M', 'N', 'K'],
    )
    @triton.jit
    def _int8_matmul_dequant_per_row_kernel(
        a_ptr, b_ptr, c_ptr, a_scale_ptr, b_scale_ptr, bias_ptr,
        M, N, K,
        stride_am, stride_ak, stride_bk, stride_bn, stride_cm, stride_cn,
        BLOCK_M: tl.constexpr, BLOCK_N: tl.constexpr, BLOCK_K: tl.constexpr,
        GROUP_SIZE_M: tl.constexpr, HAS_BIAS: tl.constexpr
    ):
        pid = tl.program_id(axis=0)
        num_pid_m = tl.cdiv(M, BLOCK_M)
        num_pid_n = tl.cdiv(N, BLOCK_N)
        num_pid_in_group = GROUP_SIZE_M * num_pid_n
        group_id = pid // num_pid_in_group
        first_pid_m = group_id * GROUP_SIZE_M
        group_size_m = min(num_pid_m - first_pid_m, GROUP_SIZE_M)
        pid_m = first_pid_m + (pid % group_size_m)
        pid_n = (pid % num_pid_in_group) // group_size_m

        offs_am = (pid_m * BLOCK_M + tl.arange(0, BLOCK_M)) % M
        offs_bn = (pid_n * BLOCK_N + tl.arange(0, BLOCK_N)) % N
        offs_k = tl.arange(0, BLOCK_K)

        a_ptrs = a_ptr + (offs_am[:, None] * stride_am + offs_k[None, :] * stride_ak)
        b_ptrs = b_ptr + (offs_k[:, None] * stride_bk + offs_bn[None, :] * stride_bn)

        accumulator = tl.zeros((BLOCK_M, BLOCK_N), dtype=tl.int32)

        for k in range(0, tl.cdiv(K, BLOCK_K)):
            a = tl.load(a_ptrs, mask=offs_k[None, :] < K - k * BLOCK_K, other=0.0)
            b = tl.load(b_ptrs, mask=offs_k[:, None] < K - k * BLOCK_K, other=0.0)
            accumulator += tl.dot(a, b)
            a_ptrs += BLOCK_K * stride_ak
            b_ptrs += BLOCK_K * stride_bk

        scale_a = tl.load(a_scale_ptr + offs_am)
        scale_b = tl.load(b_scale_ptr + offs_bn)
        c = accumulator.to(tl.float32)
        total_scale = scale_a[:, None] * scale_b[None, :]
        c = c * total_scale

        if HAS_BIAS:
            bias = tl.load(bias_ptr + offs_bn)
            c = c + bias[None, :]

        c_ptrs = c_ptr + stride_cm * offs_am[:, None] + stride_cn * offs_bn[None, :]
        c_mask = (offs_am[:, None] < M) & (offs_bn[None, :] < N)
        tl.store(c_ptrs, c, mask=c_mask)


    def triton_int8_linear_per_row(x: torch.Tensor, weight: torch.Tensor, weight_scale: torch.Tensor,
                                   bias=None, compute_dtype=torch.float16):
        x_shape_orig = x.shape
        x_2d = x.reshape(-1, x_shape_orig[-1])
        M, K = x_2d.shape
        N = weight.shape[0]

        x_int8, x_scale = triton_quantize_rowwise(x_2d)
        output = torch.empty((M, N), device=x.device, dtype=compute_dtype)
        ws = weight_scale.reshape(N).contiguous()

        grid = lambda META: (triton.cdiv(M, META['BLOCK_M']) * triton.cdiv(N, META['BLOCK_N']),)
        has_bias = bias is not None
        bias_ptr = bias if has_bias else x

        _int8_matmul_dequant_per_row_kernel[grid](
            a_ptr=x_int8, b_ptr=weight, c_ptr=output,
            a_scale_ptr=x_scale, b_scale_ptr=ws, bias_ptr=bias_ptr,
            M=M, N=N, K=K,
            stride_am=x_int8.stride(0), stride_ak=x_int8.stride(1),
            stride_bk=weight.stride(1), stride_bn=weight.stride(0),
            stride_cm=output.stride(0), stride_cn=output.stride(1),
            HAS_BIAS=has_bias
        )
        return output.reshape(x_shape_orig[:-1] + (N,))

else:
    # Triton 不可用时的占位
    def triton_quantize_rowwise(x): raise RuntimeError("Triton not available")
    def triton_int8_linear(x, w, ws, bias, dt): raise RuntimeError("Triton not available")
    def triton_int8_linear_per_row(x, w, ws, bias, dt): raise RuntimeError("Triton not available")


# =============================================================================
# 前向推理函数
# =============================================================================

_INT8_PATH_LOGGED = False

@torch.no_grad()
def int8_forward_dynamic(x: Tensor, weight: Tensor, weight_scale, bias, compute_dtype: torch.dtype) -> Tensor:
    global _INT8_PATH_LOGGED
    if not _INT8_PATH_LOGGED:
        if _TRITON_AVAILABLE and _use_triton and x.device.type != "cpu":
            print(f"XB INT8 ROCm: 推理路径 = Triton (GPU={x.device}, dtype={compute_dtype})")
        else:
            print(f"XB INT8 ROCm: 推理路径 = torch._int_mm 回退 (GPU={x.device}, Triton={'OK' if _TRITON_AVAILABLE else 'NO'}, use_triton={_use_triton})")
        _INT8_PATH_LOGGED = True

    if _TRITON_AVAILABLE and _use_triton and x.device.type != "cpu":
        return triton_int8_linear(x, weight, weight_scale, bias, compute_dtype)

    x_8, x_scale = quantize_int8_axiswise(x, dim=-1)
    res = torch._int_mm(x_8, weight.T)
    res_scaled = res.float().mul_(weight_scale * x_scale).to(compute_dtype)
    if bias is not None:
        res_scaled = res_scaled + bias.to(compute_dtype)
    return res_scaled


@torch.no_grad()
def int8_forward_dynamic_per_row(x: Tensor, weight: Tensor, weight_scale: Tensor, bias,
                                  compute_dtype: torch.dtype) -> Tensor:
    if _TRITON_AVAILABLE and _use_triton and x.device.type != "cpu":
        return triton_int8_linear_per_row(x, weight, weight_scale, bias, compute_dtype)

    x_8, x_scale = quantize_int8_axiswise(x, dim=-1)
    res = torch._int_mm(x_8, weight.T)
    res_scaled = res.float().mul_(x_scale).mul_(weight_scale.T).to(compute_dtype)
    if bias is not None:
        res_scaled = res_scaled + bias.to(compute_dtype)
    return res_scaled


# =============================================================================
# ComfyUI Ops 导入
# =============================================================================

try:
    from comfy.ops import manual_cast, cast_bias_weight, uncast_bias_weight
    _COMFY_OPS_AVAILABLE = True
except ImportError:
    _COMFY_OPS_AVAILABLE = False


# =============================================================================
# Int8TensorwiseOps —— 自定义 ComfyUI 算子
# =============================================================================

if _COMFY_OPS_AVAILABLE:
    class Int8TensorwiseOps(manual_cast):
        """INT8 tensorwise 量化自定义算子 (ROCm 优化版)"""
        excluded_names = []
        dynamic_quantize = False
        enable_convrot = False
        use_triton = True
        compute_dtype = None
        _is_prequantized = False
        lora_mode = "None"
        dynamic_lora = False
        lora_patches = {}
        lora_strength = 1.0
        dynamic_load_device = None
        skeleton_meta_init = False
        _auto_compute_dtype_by_device = {}

        @staticmethod
        def _default_compute_dtype(x: Tensor) -> torch.dtype:
            if x.dtype in (torch.float16, torch.bfloat16):
                return x.dtype
            return torch.float16

        class Linear(manual_cast.Linear):
            def __init__(self, in_features, out_features, bias=True, device=None, dtype=None):
                if getattr(Int8TensorwiseOps, "skeleton_meta_init", False):
                    nn.Module.__init__(self)
                    self.in_features = in_features
                    self.out_features = out_features
                    tensor_kwargs = {"device": "meta"}
                    if dtype is not None:
                        tensor_kwargs["dtype"] = dtype
                    self.weight = nn.Parameter(
                        torch.empty((out_features, in_features), **tensor_kwargs),
                        requires_grad=False)
                    self.bias = nn.Parameter(
                        torch.empty((out_features,), **tensor_kwargs),
                        requires_grad=False) if bias else None
                    self.weight_comfy_model_dtype = dtype
                    self.bias_comfy_model_dtype = dtype
                elif comfy.model_management.WINDOWS and comfy.memory_management.aimdo_enabled:
                    nn.Module.__init__(self)
                    self.in_features = in_features
                    self.out_features = out_features
                    self.weight = None
                    self.bias = None
                    self.comfy_need_lazy_init_bias = bias
                    self.weight_comfy_model_dtype = dtype
                    self.bias_comfy_model_dtype = dtype
                else:
                    super().__init__(in_features, out_features, bias, device, dtype)
                self.register_buffer('weight_scale', None)
                self._is_quantized = False
                self._is_per_row = False
                self._use_convrot = False
                self._weight_scale_scalar = None
                self.compute_dtype = None
                self.comfy_cast_weights = False
                self.lora_patches = []

            def reset_parameters(self):
                return None

            @staticmethod
            def _normalize_lora_key(key):
                if not isinstance(key, str):
                    return key
                for p in ["diffusion_model.", "model.diffusion_model.", "model.", "transformer."]:
                    if key.startswith(p):
                        return key[len(p):]
                return key

            @staticmethod
            def _is_bias_key(key):
                return isinstance(key, str) and key.endswith(".bias")

            @staticmethod
            def _format_lora_patches(patches):
                formatted = []
                for patch in patches or []:
                    if len(patch) == 4:
                        v, offset, function, strength = patch
                    else:
                        v, offset, function = patch
                        strength = getattr(Int8TensorwiseOps, "lora_strength", 1.0)
                    formatted.append((strength, v, 1.0, offset, function))
                return formatted

            def _apply_int8_lora_patches(self, tensor, key, patches, device):
                if not patches or tensor.dtype == torch.int8:
                    return tensor
                temp_dtype = comfy.model_management.lora_compute_dtype(device)
                tensor_temp = tensor_to_device_file_slice(tensor, device).to(dtype=temp_dtype)
                return comfy.lora.calculate_weight(self._format_lora_patches(patches), tensor_temp, key)

            def finalize_pending_int8(self):
                pending = getattr(self, "_pending_int8_finalize", None)
                if pending is None:
                    return False
                weight_key = pending["weight_key"]
                device = pending.get("device")
                if device is None:
                    device = torch.device("cuda") if torch.cuda.is_available() else self.weight.device

                weight_tensor = self.weight.detach()
                weight_tensor = self._apply_int8_lora_patches(
                    weight_tensor, weight_key, pending.get("lora_patches"), device)

                if pending["quantize"]:
                    if not hasattr(Int8TensorwiseOps, '_logged_otf'):
                        print(f"XB INT8 ROCm: Quantizing on-the-fly (ConvRot: {pending.get('enable_convrot', False)})")
                        Int8TensorwiseOps._logged_otf = True

                    w_gpu = tensor_to_device_file_slice(weight_tensor, device).float()
                    self._use_convrot = False
                    if pending.get("enable_convrot", False) and self.in_features % CONVROT_GROUP_SIZE == 0:
                        try:
                            H = build_hadamard(CONVROT_GROUP_SIZE, device=w_gpu.device, dtype=w_gpu.dtype)
                            w_gpu = rotate_weight(w_gpu, H, group_size=CONVROT_GROUP_SIZE)
                            self._use_convrot = True
                            self._convrot_groupsize = CONVROT_GROUP_SIZE
                        except Exception as e:
                            logging.warning(f"XB INT8 ROCm: ConvRot error: {e}")

                    q_weight, q_scale = quantize_int8_axiswise(w_gpu, dim=1)
                    self.weight = nn.Parameter(q_weight.cpu(), requires_grad=False)
                    self.register_buffer('weight_scale', q_scale.cpu())
                    self._weight_scale_scalar = None
                    self._is_quantized = True
                    self._is_per_row = True
                    del w_gpu, q_weight, q_scale
                else:
                    self.weight = nn.Parameter(weight_tensor.cpu(), requires_grad=False)

                self.weight_comfy_model_dtype = self.weight.dtype
                if self.weight_scale is not None:
                    self.weight_scale_comfy_model_dtype = self.weight_scale.dtype
                if self.bias is not None:
                    self.bias_comfy_model_dtype = self.bias.dtype
                delattr(self, "_pending_int8_finalize")
                return True

            def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict,
                                       missing_keys, unexpected_keys, error_msgs):
                weight_key = prefix + "weight"

                def normalize_key(key):
                    return self._normalize_lora_key(key)

                def apply_lora_patches(tensor, key):
                    if self._is_bias_key(key) or not Int8TensorwiseOps.lora_patches or tensor.dtype == torch.int8:
                        return tensor
                    nk = normalize_key(key)
                    patches = Int8TensorwiseOps.lora_patches.get(nk)
                    if patches:
                        if not hasattr(Int8TensorwiseOps, 'applied_lora_patches'):
                            Int8TensorwiseOps.applied_lora_patches = set()
                        Int8TensorwiseOps.applied_lora_patches.add(nk)
                        device = getattr(Int8TensorwiseOps, "dynamic_load_device", None)
                        if device is None:
                            device = tensor.device
                        result_temp = self._apply_int8_lora_patches(tensor, key, patches, device)
                        return result_temp.to(tensor.dtype)
                    return tensor

                def source_tensor(tensor):
                    if tensor is not None and getattr(Int8TensorwiseOps, "dynamic_load_device", None) is not None:
                        return tensor.cpu()
                    return tensor

                scale_key = prefix + "weight_scale"
                input_scale_key = prefix + "input_scale"
                bias_key = prefix + "bias"

                def pop_metadata(sd, p, k):
                    v = sd.pop(p + k, None)
                    if v is not None: return v
                    v = sd.pop("model." + p + k, None)
                    if v is not None: return v
                    if p.startswith("model."):
                        v = sd.pop(p[6:] + k, None)
                        if v is not None: return v
                    if p.startswith("diffusion_model."):
                        v = sd.pop("diffusion_model." + p + k, None)
                        if v is not None: return v
                    return None

                weight_scale = pop_metadata(state_dict, prefix, "weight_scale")
                comfy_quant_tensor = pop_metadata(state_dict, prefix, "comfy_quant")

                weight_tensor = state_dict.pop(weight_key, None)
                bias_tensor = state_dict.pop(bias_key, None)
                _ = state_dict.pop(input_scale_key, None)

                quant_conf_parsed = None
                if comfy_quant_tensor is not None:
                    try:
                        quant_conf_parsed = json.loads(bytes(comfy_quant_tensor.tolist()).decode('utf-8'))
                        if quant_conf_parsed.get("convrot", False):
                            self._use_convrot = True
                            Int8TensorwiseOps.enable_convrot = True
                            if "convrot_groupsize" in quant_conf_parsed:
                                self._convrot_groupsize = int(quant_conf_parsed["convrot_groupsize"])
                                Int8TensorwiseOps._global_convrot_groupsize = self._convrot_groupsize
                    except Exception:
                        pass

                pending_weight_lora_patches = None
                if weight_tensor is not None and weight_tensor.dtype != torch.int8:
                    pending_weight_lora_patches = Int8TensorwiseOps.lora_patches.get(normalize_key(weight_key))

                defer_weight_lora = (
                    getattr(Int8TensorwiseOps, "dynamic_load_device", None) is not None
                    and pending_weight_lora_patches
                )

                if weight_tensor is not None and not defer_weight_lora:
                    weight_tensor = apply_lora_patches(weight_tensor, weight_key)
                if bias_tensor is not None:
                    bias_tensor = apply_lora_patches(bias_tensor, bias_key)

                if weight_tensor is not None:
                    if weight_tensor.dtype == torch.int8 and weight_scale is not None:
                        self._is_quantized = True
                        self.weight = nn.Parameter(weight_tensor, requires_grad=False)
                        Int8TensorwiseOps._is_prequantized = True

                        per_row_hint = None
                        if isinstance(quant_conf_parsed, dict) and "per_row" in quant_conf_parsed:
                            per_row_hint = bool(quant_conf_parsed["per_row"])

                        if isinstance(weight_scale, torch.Tensor):
                            if weight_scale.numel() == 1:
                                self._weight_scale_scalar = weight_scale.float().item()
                                self.register_buffer('weight_scale', weight_scale.float().reshape(1))
                                self._weight_scale_scalar = None
                            elif weight_scale.dim() == 2 and weight_scale.shape[1] == 1:
                                self.register_buffer('weight_scale', weight_scale.float())
                                self._weight_scale_scalar = None
                                self._is_per_row = True if per_row_hint is None else per_row_hint
                            else:
                                self.register_buffer('weight_scale', weight_scale.float())
                                self._weight_scale_scalar = None
                                self._is_per_row = False if per_row_hint is None else per_row_hint
                        else:
                            self.weight_scale = nn.Parameter(
                                torch.tensor(float(weight_scale), dtype=torch.float32),
                                requires_grad=False)
                            self.weight_scale = None
                            self._is_per_row = False if per_row_hint is None else per_row_hint

                    elif weight_tensor.dtype in (torch.float16, torch.bfloat16, torch.float32):
                        is_excluded = any(ex in prefix for ex in Int8TensorwiseOps.excluded_names)
                        is_dim1 = self.in_features == 1 or self.out_features == 1 or weight_tensor.ndim == 1
                        should_quantize = not (is_excluded or is_dim1 or not Int8TensorwiseOps.dynamic_quantize)
                        defer_finalize = (
                            getattr(Int8TensorwiseOps, "dynamic_load_device", None) is not None
                            and (should_quantize or pending_weight_lora_patches)
                        )

                        if defer_finalize:
                            self._is_quantized = False
                            self.weight = nn.Parameter(source_tensor(weight_tensor), requires_grad=False)
                            self._pending_int8_finalize = {
                                "weight_key": weight_key,
                                "quantize": should_quantize,
                                "lora_patches": pending_weight_lora_patches,
                                "device": getattr(Int8TensorwiseOps, "dynamic_load_device", None),
                                "enable_convrot": getattr(Int8TensorwiseOps, "enable_convrot", False),
                            }
                            if pending_weight_lora_patches:
                                if not hasattr(Int8TensorwiseOps, 'applied_lora_patches'):
                                    Int8TensorwiseOps.applied_lora_patches = set()
                                Int8TensorwiseOps.applied_lora_patches.add(normalize_key(weight_key))
                        elif not should_quantize:
                            self._is_quantized = False
                            self.weight = nn.Parameter(source_tensor(weight_tensor), requires_grad=False)
                        else:
                            device = getattr(Int8TensorwiseOps, "dynamic_load_device", None)
                            if device is None:
                                device = torch.device("cuda") if torch.cuda.is_available() else weight_tensor.device

                            if not hasattr(Int8TensorwiseOps, '_logged_otf'):
                                print(f"XB INT8 ROCm: Quantizing on-the-fly (ConvRot: {getattr(Int8TensorwiseOps, 'enable_convrot', False)})")
                                Int8TensorwiseOps._logged_otf = True

                            w_gpu = weight_tensor.to(device, non_blocking=True).float()
                            self._use_convrot = False
                            if getattr(Int8TensorwiseOps, "enable_convrot", False) and self.in_features % CONVROT_GROUP_SIZE == 0:
                                try:
                                    H = build_hadamard(CONVROT_GROUP_SIZE, device=w_gpu.device, dtype=w_gpu.dtype)
                                    w_gpu = rotate_weight(w_gpu, H, group_size=CONVROT_GROUP_SIZE)
                                    self._use_convrot = True
                                    self._convrot_groupsize = CONVROT_GROUP_SIZE
                                except Exception as e:
                                    logging.warning(f"XB INT8 ROCm: ConvRot error: {e}")

                            q_weight, q_scale = quantize_int8_axiswise(w_gpu, dim=1)
                            q_weight = q_weight.cpu()
                            q_scale = q_scale.cpu()
                            self.weight = nn.Parameter(q_weight, requires_grad=False)
                            self.register_buffer('weight_scale', q_scale)
                            self._weight_scale_scalar = None
                            self._is_quantized = True
                            self._is_per_row = True
                            del w_gpu, q_weight, q_scale
                    else:
                        self._is_quantized = False
                        self.weight = nn.Parameter(source_tensor(weight_tensor), requires_grad=False)
                else:
                    missing_keys.append(weight_key)

                if bias_tensor is not None:
                    self.bias = nn.Parameter(source_tensor(bias_tensor), requires_grad=False)
                else:
                    self.bias = None

                if self.weight is not None:
                    self.weight_comfy_model_dtype = self.weight.dtype
                if self.weight_scale is not None:
                    self.weight_scale_comfy_model_dtype = self.weight_scale.dtype
                if self.bias is not None:
                    self.bias_comfy_model_dtype = self.bias.dtype

            def _get_weight_scale(self):
                return self.weight_scale

            def convert_weight(self, _weight, inplace=False):
                if not self._is_quantized:
                    return _weight
                return self.weight

            def set_weight(self, out_weight, inplace_update=False, seed=0, return_weight=False, **kwargs):
                if not self._is_quantized:
                    new_weight = out_weight.to(self.weight.dtype)
                    if return_weight:
                        return new_weight
                    if inplace_update:
                        self.weight.data.copy_(new_weight)
                    else:
                        self.weight = nn.Parameter(new_weight, requires_grad=False)
                    return

                if out_weight.dtype == torch.int8:
                    if return_weight:
                        return out_weight
                    if inplace_update:
                        self.weight.data.copy_(out_weight)
                    else:
                        self.weight = nn.Parameter(out_weight, requires_grad=False)
                    return

                new_weight = quantize_int8(out_weight, self._get_weight_scale())
                if return_weight:
                    return new_weight
                if inplace_update:
                    self.weight.data.copy_(new_weight)
                else:
                    self.weight = nn.Parameter(new_weight, requires_grad=False)

            def set_bias(self, out_bias, inplace_update=False, seed=0, return_weight=False, **kwargs):
                if out_bias is None: return None
                new_bias = out_bias
                if return_weight:
                    return new_bias
                if inplace_update:
                    if self.bias is not None:
                        self.bias.data.copy_(new_bias)
                else:
                    self.bias = nn.Parameter(new_bias, requires_grad=False)

            def forward(self, x: Tensor) -> Tensor:
                need_cast = self.comfy_cast_weights or len(self.weight_function) > 0 or len(self.bias_function) > 0

                if not self._is_quantized:
                    if need_cast:
                        weight, bias, offload_stream = cast_bias_weight(self, x, offloadable=True)
                        out = F.linear(x, weight, bias)
                        uncast_bias_weight(self, weight, bias, offload_stream)
                        return out
                    else:
                        if x.device != self.weight.device or x.dtype != self.weight.dtype:
                            weight = self.weight.to(device=x.device, dtype=x.dtype)
                            bias = self.bias.to(device=x.device, dtype=x.dtype) if self.bias is not None else None
                            return F.linear(x, weight, bias)
                        return F.linear(x, self.weight, self.bias)

                if need_cast:
                    weight, bias, offload_stream = cast_bias_weight(
                        self, input=None, dtype=torch.int8, device=x.device,
                        bias_dtype=x.dtype, offloadable=True)
                    # ROCm 守护: 确保 weight/bias 在正确的设备上
                    if weight is not None and weight.device != x.device:
                        weight = weight.to(x.device, non_blocking=True)
                    if bias is not None and bias.device != x.device:
                        bias = bias.to(x.device, non_blocking=True)
                else:
                    weight = self.weight
                    bias = self.bias
                    offload_stream = None
                    # ROCm 守护: 低VRAM卸载场景下确保设备正确
                    if weight is not None and weight.device != x.device:
                        weight = weight.to(x.device, non_blocking=True)
                    if bias is not None and bias.device != x.device:
                        bias = bias.to(x.device, non_blocking=True)

                w_scale = self._get_weight_scale()
                if isinstance(w_scale, torch.Tensor) and w_scale.device != x.device:
                    w_scale = w_scale.to(x.device, non_blocking=True)

                compute_dtype = Int8TensorwiseOps.compute_dtype
                if compute_dtype is None:
                    compute_dtype = Int8TensorwiseOps._default_compute_dtype(x)

                x_shape = x.shape
                x_2d = x.reshape(-1, x_shape[-1])
                if x_2d.dtype != compute_dtype:
                    x_2d = x_2d.to(compute_dtype)

                if getattr(self, "_use_convrot", False):
                    group_size = getattr(self, "_convrot_groupsize", CONVROT_GROUP_SIZE)
                    H = build_hadamard(group_size, device=x.device, dtype=x_2d.dtype)
                    x_2d = rotate_activation(x_2d, H, group_size=group_size)

                import sys as _sys
                _mod = _sys.modules[__name__]
                _mod._use_triton = Int8TensorwiseOps.use_triton

                if self._is_per_row:
                    y = int8_forward_dynamic_per_row(x_2d, weight, w_scale, bias, compute_dtype)
                else:
                    y = int8_forward_dynamic(x_2d, weight, w_scale, bias, compute_dtype)

                # 动态 LoRA 路径
                for lora_down, lora_up, lora_start, lora_size in self.lora_patches:
                    lD = lora_down.to(x.device, non_blocking=True)
                    lU = lora_up.to(x.device, non_blocking=True)
                    lora_x = F.linear(x_2d.to(lD.dtype), lD)
                    lora_y = F.linear(lora_x, lU)
                    if lora_start is not None:
                        y[:, lora_start:lora_start + lora_size] = (
                            y[:, lora_start:lora_start + lora_size] + lora_y.to(y.dtype))
                    else:
                        y = y + lora_y.to(y.dtype)

                if need_cast:
                    uncast_bias_weight(self, weight, bias, offload_stream)
                return y.reshape(*x_shape[:-1], y.shape[-1])

        # 透传其他层类型
        class GroupNorm(manual_cast.GroupNorm): pass
        class LayerNorm(manual_cast.LayerNorm): pass
        class Conv2d(manual_cast.Conv2d): pass
        class Conv3d(manual_cast.Conv3d): pass
        class ConvTranspose2d(manual_cast.ConvTranspose2d): pass
        class Embedding(manual_cast.Embedding): pass

        @classmethod
        def conv_nd(cls, dims, *args, **kwargs):
            if dims == 2: return cls.Conv2d(*args, **kwargs)
            elif dims == 3: return cls.Conv3d(*args, **kwargs)
            raise ValueError(f"Unsupported conv dims: {dims}")

else:
    class Int8TensorwiseOps:
        pass


# =============================================================================
# INT8ModelPatcher —— 模型包装器
# =============================================================================

class INT8ModelPatcher:
    """为 INT8 模型提供统一的 LoRA 和缓存支持的包装器"""

    @staticmethod
    def clone(patcher):
        if hasattr(patcher, '_int8_wrapped') and patcher._int8_wrapped:
            return patcher

        original_pwt = patcher.patch_weight_to_device

        def patched_pwt(key, device_to=None):
            result = original_pwt(key, device_to=device_to)
            if result is not None:
                return result

            module = comfy.utils.get_attr(patcher.model, key)
            if module is not None and hasattr(module, '_is_quantized') and module._is_quantized:
                if hasattr(module, 'lora_patches') and module.lora_patches:
                    weight = module.weight
                    bias = module.bias
                    # ROCm 优化: 动态 LoRA 缓存 —— 相同适配器跳过重建
                    patches = getattr(patcher, 'patches', {}).get(key, [])
                    cache_key = tuple(id(p[1]) for p in patches)
                    if getattr(module, "_lora_cache_key", None) == cache_key:
                        if weight is not None and weight.device != (device_to or torch.device("cpu")):
                            pass  # 已经在设备上，跳过
                        else:
                            return comfy.utils.get_attr(patcher.model, key) if hasattr(patcher, 'model') else None

                    # 记录 LoRA patches 到模块
                    from collections import defaultdict
                    ld = defaultdict(list)
                    for p in patches:
                        ld[key].append(p)
                    for lora_down, lora_up, lora_start, lora_size in module.lora_patches:
                        pass  # 保留已有

                    module._lora_cache_key = cache_key
            return None

        patcher.patch_weight_to_device = patched_pwt
        patcher._int8_wrapped = True

        # 添加 finalize_pending_int8 方法
        def finalize_pending_int8():
            if hasattr(patcher, 'model'):
                for _name, module in patcher.model.named_modules():
                    if hasattr(module, 'finalize_pending_int8'):
                        module.finalize_pending_int8()

        patcher.finalize_pending_int8 = finalize_pending_int8
        return patcher


# =============================================================================
# INT8GroupedLoraROCm 节点
# =============================================================================

class INT8GroupedLoraROCm:
    @classmethod
    def INPUT_TYPES(s):
        inputs = {"required": {"model": ("MODEL",)}, "optional": {}}
        lora_list = ["None"] + folder_paths.get_filename_list("loras")
        # 默认只显示2个LoRA槽位，需要更多时通过JS动态添加
        for i in range(1, 3):
            inputs["optional"][f"lora_{i}"] = (lora_list,)
            inputs["optional"][f"strength_{i}"] = ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01})
        return inputs

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply_loras"
    CATEGORY = "loaders"
    DESCRIPTION = "XB INT8 ROCm: 为INT8模型叠加多个LoRA（选一个弹一个）"

    def apply_loras(self, model, **kwargs):
        model_patcher = model.clone()

        for attr in ("_safetensors_metadata", "_int8_source_metadata"):
            if hasattr(model, attr) and not hasattr(model_patcher, attr):
                try:
                    setattr(model_patcher, attr, getattr(model, attr))
                except Exception:
                    pass

        key_map = {}
        if model_patcher.model.model_type.name != "ModelType.CLIP":
            key_map = comfy.lora.model_lora_keys_unet(model_patcher.model, key_map)

        applied_loras = []
        # 遍历所有可能的动态槽位（支持JS动态添加的无上限槽位）
        for i in range(1, 100):
            name = kwargs.get(f"lora_{i}")
            if name is None:
                break  # 连续空槽位，停止扫描
            strength = kwargs.get(f"strength_{i}", 0)
            if name and name != "None" and strength != 0:
                lora_path = folder_paths.get_full_path("loras", name)
                lora_data = comfy.utils.load_torch_file(lora_path, safe_load=True)
                patch_dict = comfy.lora.load_lora(lora_data, key_map)
                model_patcher.add_patches(patch_dict, strength)
                applied_loras.append(name)
                del lora_data

        if applied_loras:
            logging.info(f"XB INT8 ROCm: Stacked {len(applied_loras)} LoRAs: {', '.join(applied_loras)}")
        return (model_patcher,)


# =============================================================================
# INT8LoraROCm 节点 —— 单LoRA加载（轻量版）
# =============================================================================

class INT8LoraROCm:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "lora": (["None"] + folder_paths.get_filename_list("loras"),),
                "strength": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply_lora"
    CATEGORY = "loaders"
    DESCRIPTION = "XB INT8 ROCm: 为INT8模型挂载单个LoRA（轻量简洁）"

    def apply_lora(self, model, lora, strength):
        if lora == "None" or strength == 0:
            return (model,)

        model_patcher = model.clone()

        for attr in ("_safetensors_metadata", "_int8_source_metadata"):
            if hasattr(model, attr) and not hasattr(model_patcher, attr):
                try:
                    setattr(model_patcher, attr, getattr(model, attr))
                except Exception:
                    pass

        key_map = {}
        if model_patcher.model.model_type.name != "ModelType.CLIP":
            key_map = comfy.lora.model_lora_keys_unet(model_patcher.model, key_map)

        lora_path = folder_paths.get_full_path("loras", lora)
        lora_data = comfy.utils.load_torch_file(lora_path, safe_load=True)
        patch_dict = comfy.lora.load_lora(lora_data, key_map)
        model_patcher.add_patches(patch_dict, strength)
        del lora_data

        logging.info(f"XB INT8 ROCm: Applied LoRA '{lora}' strength={strength}")
        return (model_patcher,)


# =============================================================================
# PreLoraLoaderROCm 节点
# =============================================================================

class PreLoraLoaderROCm:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "lora_name_1": (["None"] + folder_paths.get_filename_list("loras"),),
                "lora_strength_1": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
            },
            "hidden": {"prompt": "PROMPT", "id": "UNIQUE_ID"}
        }

    RETURN_TYPES = ("PRE_LORA",)
    FUNCTION = "load_pre_lora"
    CATEGORY = "loaders"
    DESCRIPTION = "XB INT8 ROCm: 预加载LoRA以在量化时烘焙"

    @classmethod
    def VALIDATE_INPUTS(s, **kwargs):
        return True

    def load_pre_lora(self, **kwargs):
        loras = []
        prompt = kwargs.get("prompt", {})
        node_id = kwargs.get("id", None)

        if prompt and node_id and node_id in prompt:
            node_inputs = prompt[node_id].get("inputs", {})
        else:
            node_inputs = kwargs

        if "lora_name" in node_inputs:
            name = node_inputs["lora_name"]
            strength = round(node_inputs.get("lora_strength", 1.0), 2)
            if name != "None" and strength != 0.0:
                loras.append({"lora_name": name, "lora_strength": strength})

        i = 1
        while True:
            name_key = f"lora_name_{i}"
            strength_key = f"lora_strength_{i}"
            if name_key in node_inputs:
                name = node_inputs[name_key]
                strength = round(node_inputs.get(strength_key, 1.0), 2)
                if name != "None" and strength != 0.0:
                    loras.append({"lora_name": name, "lora_strength": strength})
                i += 1
            else:
                break
        return (loras,)


# =============================================================================
# UNetLoaderINTROCm 节点
# =============================================================================

def _load_int8_unet_cached_patcher_rocm(unet_name, weight_dtype, model_type,
                                         on_the_fly_quantization, enable_convrot,
                                         lora_mode, pre_lora=None, disable_dynamic=False):
    return UNetLoaderINTROCm().load_unet(
        unet_name, weight_dtype, model_type, on_the_fly_quantization,
        enable_convrot=enable_convrot, lora_mode=lora_mode,
        pre_lora=pre_lora, disable_dynamic=disable_dynamic,
    )[0]


class UNetLoaderINTROCm:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "unet_name": (folder_paths.get_filename_list("diffusion_models"),),
                "weight_dtype": (["default", "fp16", "bf16", "fp32"],),
                "model_type": (["flux2", "z-image", "ideogram4", "chroma", "krea2", "wan", "ltx2",
                                "qwen", "ernie", "anima", "hidream o1", "boogu"],),
                "on_the_fly_quantization": ("BOOLEAN", {"default": False}),
                "enable_convrot": ("BOOLEAN", {"default": True}),
                "lora_mode": (["None", "Stochastic", "Dynamic"], {"default": "None"}),
            },
            "optional": {"pre_lora": ("PRE_LORA",),}
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_unet"
    CATEGORY = "loaders"
    DESCRIPTION = "XB INT8 ROCm: 加载INT8量化扩散模型"

    def load_unet(self, unet_name, weight_dtype, model_type, on_the_fly_quantization,
                  enable_convrot=False, lora_mode="None", pre_lora=None, disable_dynamic=False):
        unet_path = folder_paths.get_full_path("diffusion_models", unet_name)

        if isinstance(lora_mode, bool):
            lora_mode = "Dynamic" if lora_mode else "None"
        lora_mode = str(lora_mode)
        if lora_mode not in {"None", "Stochastic", "Dynamic"}:
            lora_mode = "None"

        if pre_lora is not None:
            loras_to_load = pre_lora if isinstance(pre_lora, list) else [pre_lora]
        else:
            loras_to_load = []

        model_options = {"custom_operations": Int8TensorwiseOps}

        Int8TensorwiseOps.excluded_names = []
        Int8TensorwiseOps.dynamic_quantize = on_the_fly_quantization
        Int8TensorwiseOps.enable_convrot = enable_convrot
        Int8TensorwiseOps.use_triton = True
        Int8TensorwiseOps._is_prequantized = False
        Int8TensorwiseOps.lora_mode = lora_mode
        Int8TensorwiseOps.dynamic_lora = lora_mode == "Dynamic"
        Int8TensorwiseOps.dynamic_load_device = None

        dtype_map = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}
        Int8TensorwiseOps.compute_dtype = dtype_map.get(str(weight_dtype), None)

        if comfy.memory_management.aimdo_enabled and (on_the_fly_quantization or len(loras_to_load) > 0):
            Int8TensorwiseOps.dynamic_load_device = comfy.model_management.get_torch_device()
            logging.info(f"XB INT8 ROCm: Aimdo dynamic loading, device={Int8TensorwiseOps.dynamic_load_device}")

        if hasattr(Int8TensorwiseOps, "_logged_otf"):
            delattr(Int8TensorwiseOps, "_logged_otf")

        # 模型特定的排除层
        exclusion_map = {
            "flux2": ['img_in', 'time_in', 'guidance_in', 'txt_in',
                       'double_stream_modulation_img', 'double_stream_modulation_txt',
                       'single_stream_modulation'],
            "z-image": ['cap_embedder', 't_embedder', 'x_embedder', 'cap_pad_token',
                         'context_refiner', 'final_layer', 'noise_refiner', 'adaLN',
                         'x_pad_token', 'layers.0.'],
            "chroma": ['distilled_guidance_layer', 'final_layer', 'img_in', 'txt_in',
                        'nerf_image_embedder', 'nerf_blocks', 'nerf_final_layer_conv',
                        '__x0__', 'nerf_final_layer_conv'],
            "qwen": ['time_text_embed', 'img_in', 'norm_out', 'proj_out', 'txt_in'],
            "ernie": ['time', 'x_embedder', 'text_proj', 'adaLN'],
            "anima": ['embed', 'llm', 'adaln'],
            "krea2": ['first', 'last', 'tmlp', 'tproj', 'txtfusion', 'txtmlp'],
            "hidream o1": ['embed', 'language_model.layers.35.mlp'],
            "boogu": ['embed', 'refine', 'norm_out'],
            "ideogram4": ['embed_image_indicator', 't_embedding', 'proj'],
            "wan": ['patch_embedding', 'text_embedding', 'time_embedding',
                     'time_projection', 'head', 'img_emb', 'face_adapter',
                     'face_encoder', 'motion_encoder', 'pose_patch_embedding'],
            "ltx2": ['adaln', 'embedding', 'patchify', 'to_gate_logits', 'proj_out',
                      'model.audio', 'model.video', 'model.av', 'model.patch',
                      'model.proj', 'shift'],
        }
        Int8TensorwiseOps.excluded_names = exclusion_map.get(model_type, [])

        sd, metadata = comfy.utils.load_torch_file(unet_path, return_metadata=True)

        # 预加载 LoRA
        Int8TensorwiseOps.lora_patches = {}
        if len(loras_to_load) > 0:
            grouped_patches = {}
            for lora in loras_to_load:
                lora_name = lora.get("lora_name", "None")
                lora_strength = lora.get("lora_strength", 1.0)
                if lora_name == "None":
                    continue

                lora_path = folder_paths.get_full_path("loras", lora_name)
                lora_data = comfy.utils.load_torch_file(lora_path, safe_load=True)
                lora_data = comfy.lora_convert.convert_lora(lora_data)

                unet_prefix = comfy.model_detection.unet_prefix_from_state_dict(sd)
                m_config = comfy.model_detection.model_config_from_unet(sd, unet_prefix, metadata=metadata)

                if m_config is None and unet_prefix != "":
                    m_config = comfy.model_detection.model_config_from_unet(sd, "", metadata=metadata)
                    if m_config is not None:
                        unet_prefix = ""

                if m_config is not None:
                    m_config.custom_operations = Int8TensorwiseOps
                    Int8TensorwiseOps.skeleton_meta_init = True
                    try:
                        skeleton_model = m_config.get_model(sd, unet_prefix)
                    finally:
                        Int8TensorwiseOps.skeleton_meta_init = False
                    key_map = comfy.lora.model_lora_keys_unet(skeleton_model, {})
                    patch_dict = comfy.lora.load_lora(lora_data, key_map)

                    def normalize_key(key):
                        if not isinstance(key, str):
                            return key
                        for p in ["diffusion_model.", "model.diffusion_model.", "model.", "transformer."]:
                            if key.startswith(p):
                                return key[len(p):]
                        return key

                    for k, v in patch_dict.items():
                        target_key = k
                        offset = None
                        function = None
                        if isinstance(k, tuple):
                            target_key = k[0]
                            if len(k) > 1: offset = k[1]
                            if len(k) > 2: function = k[2]
                        nk = normalize_key(target_key)
                        if nk not in grouped_patches:
                            grouped_patches[nk] = []
                        grouped_patches[nk].append((v, offset, function, lora_strength))
                else:
                    logging.warning(f"XB INT8 ROCm: Could not detect model type for LoRA mapping.")
                del lora_data

            if grouped_patches:
                Int8TensorwiseOps.lora_patches = grouped_patches
                logging.info(f"XB INT8 ROCm: Prepared {len(grouped_patches)} layer patches for baking.")

        try:
            Int8TensorwiseOps.applied_lora_patches = set()
            model = comfy.sd.load_diffusion_model_state_dict(
                sd, model_options=model_options, metadata=metadata, disable_dynamic=disable_dynamic)

            if Int8TensorwiseOps.lora_patches:
                unmatched = set(Int8TensorwiseOps.lora_patches.keys()) - Int8TensorwiseOps.applied_lora_patches
                if unmatched:
                    print(f"XB INT8 ROCm: {len(unmatched)} LoRA keys were NOT matched:")
                    for k in sorted(unmatched):
                        print(f"  unmatched: {k}")
        finally:
            dynamic_load_device = Int8TensorwiseOps.dynamic_load_device
            Int8TensorwiseOps.lora_patches = {}
            Int8TensorwiseOps.dynamic_load_device = None
            if dynamic_load_device is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()
            if hasattr(Int8TensorwiseOps, 'applied_lora_patches'):
                delattr(Int8TensorwiseOps, 'applied_lora_patches')

        model = INT8ModelPatcher.clone(model)
        model.cached_patcher_init = (
            _load_int8_unet_cached_patcher_rocm,
            (unet_name, weight_dtype, model_type, on_the_fly_quantization,
             enable_convrot, lora_mode, pre_lora),
        )
        model._safetensors_metadata = metadata
        try:
            if model.model is not None:
                model.model._int8_source_metadata = metadata
        except Exception:
            pass

        return (model,)


# =============================================================================
# INT8ModelSaveROCm 节点
# =============================================================================

def _is_dynamic_lora_enabled_rocm():
    return bool(getattr(Int8TensorwiseOps, "dynamic_lora", False))


def _resolve_source_metadata(model):
    seen = set()

    def _walk(m):
        if m is None or id(m) in seen:
            return None
        seen.add(id(m))
        meta = getattr(m, "_safetensors_metadata", None)
        if isinstance(meta, dict) and meta:
            return meta
        inner = getattr(m, "model", None)
        if inner is not None:
            inner_meta = getattr(inner, "_int8_source_metadata", None)
            if isinstance(inner_meta, dict) and inner_meta:
                return inner_meta
        parent = getattr(m, "parent", None)
        return _walk(parent)

    return _walk(model)


class INT8ModelSaveROCm:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ("MODEL",),
            "filename_prefix": ("STRING", {"default": "int8_models/INT8_Model"}),
        }, "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}

    RETURN_TYPES = ()
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "loaders"
    DESCRIPTION = "XB INT8 ROCm: 保存INT8量化模型"

    def save(self, model, filename_prefix, prompt=None, extra_pnginfo=None):
        full_output_folder, filename, counter, subfolder, filename_prefix = \
            folder_paths.get_save_image_path(filename_prefix, self.output_dir)

        metadata = {}
        src_meta = _resolve_source_metadata(model)
        if isinstance(src_meta, dict):
            metadata.update(src_meta)
        if not src_meta:
            logging.warning("XB INT8 ROCm: source safetensors metadata not found, save may be incomplete.")

        output_checkpoint = f"{filename}_{counter:05}_.safetensors"
        output_checkpoint = os.path.join(full_output_folder, output_checkpoint)

        extra_keys = {}
        patched_modules = []
        patched_module_ids = set()

        def mark_module_for_direct_save(module):
            module_id = id(module)
            if module_id in patched_module_ids:
                return
            had_flag = hasattr(module, "comfy_patched_weights")
            old_flag = getattr(module, "comfy_patched_weights", False)
            patched_modules.append((module, had_flag, old_flag))
            patched_module_ids.add(module_id)
            module.comfy_patched_weights = True

        def module_has_int8_param(module):
            for attr in ("weight", "bias"):
                tensor = getattr(module, attr, None)
                if isinstance(tensor, torch.Tensor) and tensor.dtype == torch.int8:
                    return True
            return False

        def iter_model_modules(model_patcher):
            if hasattr(model_patcher, "model") and hasattr(model_patcher.model, "named_modules"):
                yield from model_patcher.model.named_modules()

        def materialize_int8_lora_patches(model_patcher):
            if _is_dynamic_lora_enabled_rocm() or not hasattr(model_patcher, "patch_weight_to_device"):
                return
            patches = getattr(model_patcher, "patches", None)
            if not patches:
                return
            load_device = getattr(model_patcher, "load_device", None)
            materialized = 0
            for name, module in iter_model_modules(model_patcher):
                if not getattr(module, "_is_quantized", False):
                    continue
                weight_key = name + ".weight" if name else "weight"
                if weight_key not in patches:
                    continue
                try:
                    model_patcher.patch_weight_to_device(weight_key, device_to=load_device)
                    if hasattr(module, "weight_lowvram_function"):
                        module.weight_lowvram_function = None
                    materialized += 1
                except Exception as e:
                    logging.warning(f"XB INT8 ROCm: failed to materialize LoRA for {weight_key}: {e}")
            if materialized > 0:
                logging.info(f"XB INT8 ROCm: materialized {materialized} INT8 LoRA patched weights.")

        finalize_fn = getattr(model, "finalize_pending_int8", None)
        if finalize_fn is not None:
            finalize_fn()

        try:
            comfy.model_management.load_models_gpu([model], force_full_load=True)
        except Exception as e:
            logging.warning(f"XB INT8 ROCm: full-load pre-pass failed ({e}), falling back.")
            try:
                comfy.model_management.load_models_gpu([model])
            except Exception as e2:
                logging.warning(f"XB INT8 ROCm: load_models_gpu fallback also failed ({e2}).")

        if finalize_fn is not None:
            finalize_fn()

        materialize_int8_lora_patches(model)

        if hasattr(model, "model"):
            for name, module in iter_model_modules(model):
                if module_has_int8_param(module):
                    mark_module_for_direct_save(module)

                if getattr(module, "_is_quantized", False):
                    use_convrot = bool(getattr(module, "_use_convrot", False))
                    quant_conf = {"format": "int8_tensorwise", "convrot": use_convrot}
                    if use_convrot:
                        quant_conf["convrot_groupsize"] = int(
                            getattr(module, "_convrot_groupsize", CONVROT_GROUP_SIZE))
                    quant_conf["per_row"] = bool(getattr(module, "_is_per_row", False))

                    prefix = "model." + name + "." if name else "model."
                    extra_keys[prefix + "comfy_quant"] = torch.tensor(
                        list(json.dumps(quant_conf).encode('utf-8')), dtype=torch.uint8)

                    if getattr(module, "_weight_scale_scalar", None) is not None:
                        extra_keys[prefix + "weight_scale"] = torch.tensor(module._weight_scale_scalar)

                    mark_module_for_direct_save(module)

        original_lazy_new = comfy.model_patcher.LazyCastingParam.__new__
        original_lazy_piece_new = comfy.model_patcher.LazyCastingParamPiece.__new__

        def lazy_casting_param_new(cls, model, key, tensor):
            requires_grad = tensor.is_floating_point() or tensor.is_complex()
            return torch.nn.Parameter.__new__(cls, tensor, requires_grad=requires_grad)

        def lazy_casting_param_piece_new(cls, caster, state_dict_key, tensor):
            requires_grad = tensor.is_floating_point() or tensor.is_complex()
            return torch.nn.Parameter.__new__(cls, tensor, requires_grad=requires_grad)

        had_save_flag = hasattr(model, "_int8_save_materialized_lora")
        old_save_flag = getattr(model, "_int8_save_materialized_lora", False)

        try:
            model._int8_save_materialized_lora = True
            comfy.model_patcher.LazyCastingParam.__new__ = staticmethod(lazy_casting_param_new)
            comfy.model_patcher.LazyCastingParamPiece.__new__ = staticmethod(lazy_casting_param_piece_new)
            comfy.sd.save_checkpoint(output_checkpoint, model, metadata=metadata, extra_keys=extra_keys)
        finally:
            comfy.model_patcher.LazyCastingParam.__new__ = original_lazy_new
            comfy.model_patcher.LazyCastingParamPiece.__new__ = original_lazy_piece_new
            if had_save_flag:
                model._int8_save_materialized_lora = old_save_flag
            else:
                try:
                    delattr(model, "_int8_save_materialized_lora")
                except AttributeError:
                    pass
            for module, had_flag, old_flag in patched_modules:
                if had_flag:
                    module.comfy_patched_weights = old_flag
                else:
                    try:
                        delattr(module, "comfy_patched_weights")
                    except AttributeError:
                        pass

        return {}
