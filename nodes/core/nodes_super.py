"""
XB_ToolBox - 超级复合节点 (Super Composite Nodes)
=====================================================
此文件专门收纳"将重度子图重构为单一原生节点"的超级节点。

设计理念：
    在 ComfyUI 中，使用大量互斥开关（Fast Muter）+ 多路选择器（Any Switch）
    构建的逻辑子图，每次刷新时前端都要遍历所有隐藏节点的连线状态，
    导致界面卡顿、拖拽掉帧。将这些子图重构为单一 Python 原生节点，
    用字典映射替代布尔短路计算，前端渲染开销降为 O(1)。

依赖说明：
    ✅ 本文件所有节点均为纯 ComfyUI 原生 API 实现，零第三方依赖。
    ✅ 不需要安装 rgthree、comfyui-easy-use 等任何第三方插件。
    ✅ 仅依赖 ComfyUI 核心框架（nodes、folder_paths 等标准库）。
"""


class XB_BerniniPromptRouter:
    """
    Bernini 超级提示词路由节点
    ============================
    完美替代原版 Bernini 风格切换子图（12个互斥开关 + Any Switch + Fast Muter + StringConcatenate）。
    
    原版痛点：
        - 前端 12 个 toggle + Fast Muter 互斥逻辑，每次点击都触发 O(N) 连线遍历
        - 30+ 个隐藏小节点导致工作流刷新/拖拽严重卡顿
        - 用户可能误操作同时点亮多个开关导致输出异常
    
    本节点优势：
        - 12 选 1 的下拉菜单，天然互斥，零前端渲染开销
        - 单节点替代整个子图，工作流瞬间清爽
        - 增加分隔符选项，防止英文句号与提示词黏连影响 T5 切词
    
    零第三方依赖 | 纯 ComfyUI 原生 API
    """

    _MODES = {
        "文生图 (Text to Image)": "You are a helpful assistant specialized in text-to-image generation.",
        "主体生图 (Subject to Image)": "You are a helpful assistant specialized in subject-to-image generation.",
        "图像编辑 (Image Editing)": "You are a helpful assistant specialized in image editing.",
        "文生视频 (Text to Video)": "You are a helpful assistant specialized in text-to-video generation.",
        "图生视频 (Image to Video)": "You are a helpful assistant specialized in image-to-video generation.",
        "视频编辑 (Video Editing)": "You are a helpful assistant specialized in video editing.",
        "视频编辑 - 特征同步 (Propagation)": "You are a helpful assistant specialized in video editing on content propagation.",
        "视频编辑 - 参考引导 (Reference)": "You are a helpful assistant specialized in video editing with reference.",
        "视频编辑 - 内容植入 (Ads Insertion)": "You are a helpful assistant specialized in ads insertion.",
        "视频编辑 - 动作/位置 (Action)": "You are a helpful assistant for editing. You may need to adjust the subject's action or position.",
        "视频编辑 - 风格/动态 (Style)": "You are a helpful assistant for editing. You might need to adjust the video's style, lighting, colors, textures, and the subject's pose or action.",
        "默认模式 (Default)": "You are a helpful assistant.",
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # 核心路由：原生下拉菜单替代 12 个互斥 toggle（O(1) 字典查找 vs O(N) 前端轮询）
                "mode": (list(cls._MODES.keys()), {
                    "default": "视频编辑 - 参考引导 (Reference)",
                    "tooltip": "选择当前工作模式，自动匹配对应的 AI 系统指令前缀"
                }),
                # 用户输入的提示词（替代原版 PrimitiveStringMultiline 节点）
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "在此输入你的描述词，将自动拼接在系统指令之后"
                }),
                # 分隔符：防止英文句号与首字母黏连导致 T5 编码器切词失败
                "separator": (["加空格 (推荐)", "加换行符", "无分隔符 (原版)"], {
                    "default": "加空格 (推荐)",
                    "tooltip": "系统指令与用户提示词之间的分隔方式"
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("超级提示词",)
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, mode, prompt, separator):
        # 1. 根据下拉菜单选择，O(1) 字典映射获取系统指令前缀
        system_prompt = self._MODES[mode]

        # 2. 如果用户没写提示词，只返回系统前缀
        if not prompt.strip():
            return (system_prompt,)

        # 3. 处理分隔符逻辑
        if separator == "加空格 (推荐)":
            sep_char = " "
        elif separator == "加换行符":
            sep_char = "\n"
        else:
            sep_char = ""

        # 4. 字符串缝合（原版 StringConcatenate 的等价逻辑）
        final_prompt = f"{system_prompt}{sep_char}{prompt.strip()}"

        return (final_prompt,)


class XB_K2StyleRouter:
    """
    K2 风格切换路由节点
    ====================
    完美替代原版 K2 风格切换子图（10个互斥开关 + Any Switch + Fast Muter + anythingIndexSwitch）。

    原版痛点：
        - 前端 10 个 toggle + Fast Muter 互斥逻辑，每次点击都触发 O(N) 连线遍历
        - 20+ 个隐藏小节点导致工作流刷新/拖拽严重卡顿
        - 3 条输出线（Lora索引、激活词、提示词）需手动对齐

    本节点优势：
        - 10 选 1 的下拉菜单，天然互斥，零前端渲染开销
        - 单节点同时输出 Lora 切换索引 + 风格激活词 + 用户提示词
        - "关闭LORA"选项自动输出空激活词，配合下游 Lora 节点实现旁路

    零第三方依赖 | 纯 ComfyUI 原生 API
    """

    _STYLES = {
        "单色水墨晕染风格":   {"index": 0, "trigger": "monochrome ink wash style"},
        "单色点彩/点绘风格":   {"index": 1, "trigger": "monochrome stippling style"},
        "儿童涂鸦画风格":     {"index": 2, "trigger": "naive expressive sketch style"},
        "厚涂油画风格":       {"index": 3, "trigger": "textured abstract style"},
        "隔窗雨景风格":       {"index": 4, "trigger": "rainy window style"},
        "紫色复古动漫风格":   {"index": 5, "trigger": "purple retro anime style"},
        "装饰艺术水彩风格":   {"index": 6, "trigger": "art deco watercolor style"},
        "空灵动态虚影风格":   {"index": 7, "trigger": "ethereal motion blur style"},
        "古典塔罗牌风格":     {"index": 8, "trigger": "vintage tarot style"},
        "关闭LORA":          {"index": 9, "trigger": ""},
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # 核心路由：原生下拉菜单替代 10 个互斥 toggle
                "style": (list(cls._STYLES.keys()), {
                    "default": "单色水墨晕染风格",
                    "tooltip": "选择风格模式，自动匹配 Lora 索引和激活词"
                }),
                # 用户输入的提示词（原版 node 430 PrimitiveStringMultiline，透传输出）
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "在此输入你的描述词，将原样透传至下游"
                }),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "STRING")
    RETURN_NAMES = ("切换Lora", "激活词", "提示词")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Pipeline"

    def process(self, style, prompt):
        # O(1) 字典映射：一次查找同时获取 Lora 索引和激活词
        info = self._STYLES[style]

        # 输出：Lora索引 (INT) | 风格激活词 (STRING) | 用户提示词透传 (STRING)
        return (info["index"], info["trigger"], prompt.strip())
