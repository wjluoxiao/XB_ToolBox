"""
XB-ToolBox CLIP 文本编辑节点
============================
套皮官方 CLIP Text Encode (Prompt) + Conditioning Zero Out 两个节点：
输入一次提示词，同时输出正向条件与零化后负面条件。

设计原则与 nodes_vanilla_wrappers 一致：
  - 动态继承 nodes.CLIPTextEncode 的 INPUT_TYPES → 官方新增参数自动同步
  - 直接调用官方 CLIPTextEncode.encode 与 ConditioningZeroOut.zero_out，不做算法改写
"""

import copy
import inspect

import torch
import nodes


def _zero_out(conditioning):
    """官方 ConditioningZeroOut 缺失时的等价实现（与官方逻辑保持一致）。"""
    results = []
    for t in conditioning:
        d = t[1].copy()
        pooled_output = d.get("pooled_output", None)
        if pooled_output is not None:
            d["pooled_output"] = torch.zeros_like(pooled_output)
        results.append([torch.zeros_like(t[0]), d])
    return results


class XB_CLIPTextEdit:
    """CLIP 文本编辑 — 官方 CLIP Text Encode (Prompt) + Conditioning Zero Out 二合一。

    输入端口 clip 等同于 CLIP Text Encode (Prompt) 的 clip 输入。
    输出端口正向条件等同于 CLIP Text Encode (Prompt) 的条件输出；
    输出端口零化后负面条件等同于把该正向条件接入 Conditioning Zero Out 后的输出。
    """

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.CLIPTextEncode.INPUT_TYPES())
        required = inputs.setdefault("required", {})
        required.setdefault("clip", ("CLIP",))
        required.setdefault("text", ("STRING", {"multiline": True, "dynamicPrompts": True}))
        return inputs

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("正向条件", "零化后负面条件")
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/Text"
    DESCRIPTION = (
        "同时输出正向条件与零化后负面条件，省去 CLIP Text Encode + Conditioning Zero Out 两个节点。\n"
        "正向条件 = 官方 CLIP Text Encode (Prompt) 的输出。\n"
        "零化后负面条件 = 该正向条件接入官方 Conditioning Zero Out 后的输出。"
    )

    def encode(self, **kwargs):
        encode_fn = nodes.CLIPTextEncode().encode
        accepted = set(inspect.signature(encode_fn).parameters)
        positive, = encode_fn(**{k: v for k, v in kwargs.items() if k in accepted})

        zero_out_cls = getattr(nodes, "ConditioningZeroOut", None)
        if zero_out_cls is not None:
            negative, = zero_out_cls().zero_out(positive)
        else:
            negative = _zero_out(positive)
        return (positive, negative)
