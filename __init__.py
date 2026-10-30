import os
import traceback

from server import PromptServer
from aiohttp import web

HAS_TKINTER = False
try:
    import tkinter as tk
    from tkinter import filedialog
    HAS_TKINTER = True
except ImportError:
    pass  # 静默放行，不要让整个节点加载失败

@PromptServer.instance.routes.post("/xb_toolbox/choose_folder")
async def choose_folder(request):
    if not HAS_TKINTER:
        return web.json_response({"path": "", "error": "当前整合包环境缺少弹窗依赖，请手动输入或粘贴文件夹路径。"})
    
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder_path = filedialog.askdirectory()
        root.destroy()
        return web.json_response({"path": folder_path})
    except Exception as e:
        return web.json_response({"path": "", "error": f"弹窗调用失败: {str(e)}"})


from .nodes_audio_slicer import handle_audio_waveform
from .nodes_model_loader_v1 import _filter_by_keyword

@PromptServer.instance.routes.post("/xb_toolbox/audio_waveform")
async def get_audio_waveform(request):
    return await handle_audio_waveform(request)


@PromptServer.instance.routes.get("/xb_toolbox/yue2_recipes")
async def yue2_recipes(request):
    """YuE2 风格配方表：前端「YuE2 风格提示」节点联动用，与 yue2_styles.RECIPES 同一数据源"""
    from .yue2_styles import GENRES, RECIPES
    return web.json_response({"recipes": RECIPES, "genres": GENRES})


@PromptServer.instance.routes.post("/xb_toolbox/model_list")
async def get_model_list(request):
    """根据关键字返回过滤后的模型/CLIP/VAE/LoRA列表"""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"})
    keyword = data.get("keyword", "")
    if not keyword:
        return web.json_response({"models": [], "clips": [], "vaes": [], "loras": []})
    return web.json_response({
        "models": sorted(set(_filter_by_keyword("diffusion_models", keyword) + _filter_by_keyword("unet_gguf", keyword))),
        "clips": sorted(set(_filter_by_keyword("text_encoders", keyword) + _filter_by_keyword("clip_gguf", keyword))),
        "vaes": _filter_by_keyword("vae", keyword),
        "loras": _filter_by_keyword("loras", keyword),
    })


def print_success(msg):
    print(f"\033[92m{msg}\033[0m")  

def print_error(msg):
    print(f"\033[91m{msg}\033[0m")  

def print_warning(msg):
    print(f"\033[93m{msg}\033[0m")  

# 启动 banner 上的 JZL 像素字
XB_LOGO = "\n".join([
    "     ██╗███████╗██╗",
    "     ██║╚══███╔╝██║",
    "     ██║  ███╔╝ ██║",
    "██   ██║ ███╔╝  ██║",
    "╚█████╔╝███████╗███████╗",
    " ╚════╝ ╚══════╝╚══════╝",
])

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js")

try:
    from .nodes_vis import XB_VRAM_Calculator, XB_ChunkVisualization
    from .nodes_vram import XTX_Data_Radar
    from .nodes_video import XB_VideoParamsMaster, XB_ImageParamsMaster, XB_ImageParamsMasterMini, XB_MasterParameter, XB_VideoLoader, XB_VideoCombine
    from .nodes_blockswap import XB_UNetBlockSwap, XB_CheckpointBlockSwap 
    from .nodes_blockswap_sage import XB_Sage_BlockSwap
    from .nodes_wiring import XB_UNetNameBroadcaster, XB_CLIPNameBroadcaster
    from .nodes_memory_viz import XB_MemoryVisualization
    from .nodes_wan_vae import (XB_WanImageToVideo, XB_WanFirstLastFrameToVideo, XB_WanSoundImageToVideo, XB_WanFunControlToVideo, XB_WanVaceToVideo, XB_Wan22FunControlToVideo, XB_WanInfiniteTalkToVideo, XB_WanInfiniteTalkToVideo_Single, XB_WanInfiniteTalkToVideo_Dual, XB_WanFunInpaintToVideo, XB_WanCameraImageToVideo, XB_WanPhantomSubjectToVideo, XB_WanHuMoImageToVideo, XB_Wan22ImageToVideoLatent, XB_WanSoundImageToVideoExtend, XB_WanSCAILToVideo, XB_WanSCAILToVideoPro, XB_WanDancerVideo, XB_WanDanceSwitcher, XB_WanDancerCombo, XB_BerniniConditioning)
    from .nodes_batch import XB_BatchFolderLoader, XB_BatchFolderBatchLoader
    from .nodes_pipeline import XB_Wan_ParamBus, XB_Wan_RelayNode, XB_Wan_InfiniteRelayNode, XB_Video_Merger, XB_StoryboardSlicer,XB_WanAnimate_ParamBus,XB_WanAnimate_RelayNode, XB_WanInfiniteTalk_ParamBus, XB_WanInfiniteTalk_RelayNode, XB_Wan_InfiniteRelayNode_New, XB_WanAnimate_RelayNode_New, XB_WanInfiniteTalk_RelayNode_New, XB_WanSCAIL_ParamBus_New, XB_WanSCAIL_RelayNode_New, XB_WanInfiniteTalk_RelayNode_MultiRef, XB_WanInfiniteTalk_RelayNode_AllInOne
    from .nodes_ltx_streamer import XB_LTX23_InfiniteStreamer
    from .nodes_sageatt import XB_SageAttentionAccelerator
    from .nodes_wan import XB_WanCompileSettings, XB_WanAnimateToVideo

    from .nodes_label import XB_CanvasLabel
    from .nodes_audio_slicer import XB_AudioSlicer, XB_AudioSlicerV1, XB_AudioSlicerV2, XB_AudioSlicerV3
    from .nodes_digital_human import XB_DigitalHumanParams_Single, XB_DigitalHumanParams_Dual
    from .nodes_model_loader_gguf import XB_ModelLoaderV1_GGUF, XB_ModelLoaderV2_GGUF, XB_ModelLoaderV3_GGUF
    from .nodes_status_switch import XB_NodeStatusSwitch
    from .nodes_fast_toggle import XB_DisableGroups, XB_DisableNodes, XB_AnySwitch
    from .nodes_flux_encode import XB_FluxMultiImageEncode
    from .nodes_qwen_encode import XB_TextEncodeQwenImageEdit, XB_TextEncodeQwenImageEditPlus
    from .nodes_image_scale import XB_ImageScale, XB_ImageScalePixels
    from .nodes_shenbi import XB_ShenBi
    from .nodes_hailuo_video import XB_HailuoH3VideoParams
    from .nodes_list_dispatcher import XB_ListDispatcher
    from .nodes_batch_images import XB_BatchImages
    from .nodes_reference_any import XB_ReferenceAny
    from .nodes_segmentation import XB_HumanSegModelLoader, XB_HumanSegmentation

    # 注册视频转码端点（预览窗口实时缩放依赖）
    from . import xb_video_server
    from .nodes_vanilla_wrappers import (XB_KSampler, XB_KSamplerAdvanced,
                                          XB_SamplerCustom, XB_SamplerCustomAdvanced,
                                          XB_VAEDecode, XB_VAEDecodeTiled,
                                          XB_VAEDecodeTiledImage,
                                          XB_VAEEncode, XB_VAEEncodeTiled,
                                          XB_VAEEncodeTiledImage,
                                          XB_VAEEncodeForInpaint,
                                          _AliasVAEDecodeTemporal)
    from .nodes_string_merge import XB_StringMerge
    from .nodes_clip_text_edit import XB_CLIPTextEdit
    from .nodes_lora_loader import XB_TripleLoraLoader, XB_TripleLoraLoaderModelOnly
    from .nodes_msr import XB_MSR
    from .nodes_comic import XB_ComicPromptParser, XB_ComicTextRenderer, XB_AutoBubbleTextRenderer
    from .nodes_super import XB_BerniniPromptRouter, XB_K2StyleRouter

    # ── Llama 节点 (LLM/VLM) ──
    try:
        from .nodes_llama import (
            XB_llamaModelLoader, XB_llamaModelLoaderPro, XB_llamaInstruct, XB_llamaParameters,
            XB_llamaUnloadModel, XB_llamaCleanStates,
            XB_llamaBBoxes2BBox, XB_llamaUnpackCodeBlock, XB_llamaPromptEnhancer,
            XB_llamaMiniMaxPreset, XB_llamaMiniMaxRef2vaPreset,
            XB_llamaStoryboardEnhancer, XB_llamaStoryboardInstruct,
            XB_llamaStoryboardProcessor, XB_llamaStoryboardProcessorPro,
            XB_RoleSceneDispatcher,
        )
        # ── 提示词增强反推（模型加载器 + 指令推理 + 提示词增强预设 + 推理参数 + LLM-API 设置 五合一）──
        from .nodes_llama_prompt_reverse import XB_llamaPromptReverse
        _LLAMA_AVAILABLE = True
    except ImportError as e:
        print_warning(f"[XB-llama] llama-cpp-python 未安装, Llama/MiniMax 节点不可用: {e}")
        _LLAMA_AVAILABLE = False

    # ── 🖼️ 生图提示词预设Pro（生图提示词预设 + 提示词增强反推 融合）──
    try:
        from .nodes_image_prompt_preset_pro import XB_ImagePromptPresetPro
        _PRO_AVAILABLE = True
    except Exception as e:
        print_warning(f"[XB-BOX] 生图提示词预设Pro 未加载：{e}")
        _PRO_AVAILABLE = False

    # ── 🖼️ Qwen2.1提示词预设（生图提示词预设 + 官方 Load CLIP + 官方 Generate Text）──
    try:
        from .nodes_qwen_prompt_preset import XB_QwenPromptPreset
        _QWEN_AVAILABLE = True
    except Exception as e:
        print_warning(f"[XB-BOX] Qwen2.1提示词预设 未加载：{e}")
        _QWEN_AVAILABLE = False

    # ── 🎵 YuE2 音乐节点（风格提示 / 歌词 / 乐谱工作台 / 翻唱准备 / 转谱导入）──
    try:
        from .nodes_yue2_style import XB_YuE2StylePrompt
        from .nodes_yue2_lyrics import XB_YuE2Lyrics
        from .nodes_yue2_score import XB_YuE2ScoreWorkbench, XB_YuE2CoverPrep
        from .nodes_yue2_transcription import XB_YuE2Transcription
        _YUE2_AVAILABLE = True
    except Exception as e:
        print_warning(f"[XB-BOX] YuE2 音乐节点 未加载：{e}")
        _YUE2_AVAILABLE = False

    # ── CosyVoice3 音频节点 ──
    from .cosyvoice3.nodes.model_loader import XB_CosyVoice3_ModelLoader
    from .cosyvoice3.nodes.zero_shot import XB_CosyVoice3_ZeroShot
    from .cosyvoice3.nodes.cross_lingual import XB_CosyVoice3_CrossLingual
    from .cosyvoice3.nodes.voice_conversion import XB_CosyVoice3_VoiceConversion
    from .cosyvoice3.nodes.audio_crop import XB_CosyVoice3_AudioCrop
    from .cosyvoice3.nodes.dialog import XB_CosyVoice3_Dialog
    from .cosyvoice3.nodes.instruct2 import XB_CosyVoice3_Instruct2
    from .cosyvoice3.nodes.save_speaker import XB_CosyVoice3_SaveSpeaker
    from .cosyvoice3.nodes.speaker_clone import XB_CosyVoice3_SpeakerClone
    from .cosyvoice3.nodes.speaker_instruct2 import XB_CosyVoice3_SpeakerInstruct2

    # ── 🎬 保存视频（Create Video + Save Video 二合一，依赖新版 V3 API）──
    try:
        from .nodes_save_video import XB_SaveVideo
        _SAVE_VIDEO_AVAILABLE = True
    except Exception as e:
        print_warning(f"[XB-BOX] 保存视频节点 未加载：{e}")
        _SAVE_VIDEO_AVAILABLE = False

    # ── 🎬 加载视频（Load Video + Get Video Components 二合一，依赖新版 V3 API）──
    try:
        from .nodes_load_video import XB_LoadVideo
        _LOAD_VIDEO_AVAILABLE = True
    except Exception as e:
        print_warning(f"[XB-BOX] 加载视频节点 未加载：{e}")
        _LOAD_VIDEO_AVAILABLE = False

    # ── 生图提示词预设（提示词 + 空latent 一体化）──
    from .nodes_image_prompt_preset import XB_ImagePromptPreset

    # ── 生图预设（生图提示词预设 + 姿态参考图 / 穿搭参考图）──
    # 同时 import xb_gallery → 注册 /xb_toolbox/gallery/* 端点（图库绑定、素材清单、图片读取）
    try:
        from . import xb_gallery  # noqa: F401
        from .nodes_image_preset import XB_ImagePreset
        _IMAGE_PRESET_AVAILABLE = True
    except Exception as e:
        print_warning(f"[XB-BOX] 生图预设节点 未加载：{e}")
        _IMAGE_PRESET_AVAILABLE = False

    # ── 播放声音（复刻 pysssss PlaySound，自带音频资源）──
    from .nodes_play_sound import XB_PlaySound

    NODE_CLASS_MAPPINGS = { 
        "XB_VRAM_Calculator": XB_VRAM_Calculator,
        "XB_ChunkVisualization": XB_ChunkVisualization,
        "XTX_Data_Radar": XTX_Data_Radar,
        "XB_VideoParamsMaster": XB_VideoParamsMaster,
        "XB_ImageParamsMaster": XB_ImageParamsMaster,
        "XB_ImageParamsMasterMini": XB_ImageParamsMasterMini, 
        "XB_ShenBi": XB_ShenBi,
        "XB_ImagePromptPreset": XB_ImagePromptPreset,
        "XB_PlaySound": XB_PlaySound,
        "XB_MasterParameter": XB_MasterParameter,
        "XB_VideoLoader": XB_VideoLoader,
        "XB_VideoCombine": XB_VideoCombine,
        "XB_UNetBlockSwap": XB_UNetBlockSwap,
        "XB_CheckpointBlockSwap": XB_CheckpointBlockSwap,
        "XB_Sage_BlockSwap": XB_Sage_BlockSwap,
        "XB_UNetNameBroadcaster": XB_UNetNameBroadcaster,
        "XB_CLIPNameBroadcaster": XB_CLIPNameBroadcaster,
        "XB_MemoryVisualization": XB_MemoryVisualization,
        "XB_WanImageToVideo": XB_WanImageToVideo,
        "XB_WanFirstLastFrameToVideo": XB_WanFirstLastFrameToVideo,
        "XB_WanFunControlToVideo": XB_WanFunControlToVideo,
        "XB_WanVaceToVideo": XB_WanVaceToVideo,
        "XB_Wan22FunControlToVideo": XB_Wan22FunControlToVideo,
        "XB_WanSoundImageToVideo": XB_WanSoundImageToVideo,
        "XB_WanInfiniteTalkToVideo": XB_WanInfiniteTalkToVideo,
        "XB_WanInfiniteTalkToVideo_Single": XB_WanInfiniteTalkToVideo_Single,
        "XB_WanInfiniteTalkToVideo_Dual": XB_WanInfiniteTalkToVideo_Dual,
                "XB_WanFunInpaintToVideo": XB_WanFunInpaintToVideo,
        "XB_WanCameraImageToVideo": XB_WanCameraImageToVideo,
        "XB_WanPhantomSubjectToVideo": XB_WanPhantomSubjectToVideo,
        "XB_WanHuMoImageToVideo": XB_WanHuMoImageToVideo,
        "XB_Wan22ImageToVideoLatent": XB_Wan22ImageToVideoLatent,
        "XB_WanSoundImageToVideoExtend": XB_WanSoundImageToVideoExtend,
        "XB_WanSCAILToVideo": XB_WanSCAILToVideo,
        "XB_WanSCAILToVideoPro": XB_WanSCAILToVideoPro,
        "XB_WanDancerVideo": XB_WanDancerVideo,
        "XB_WanDanceSwitcher": XB_WanDanceSwitcher,
        "XB_WanDancerCombo": XB_WanDancerCombo,
        "XB_BerniniConditioning": XB_BerniniConditioning,
        "XB_BatchFolderLoader": XB_BatchFolderLoader,
        "XB_BatchFolderBatchLoader": XB_BatchFolderBatchLoader,
        "XB_Wan_ParamBus": XB_Wan_ParamBus,
        "XB_Wan_RelayNode": XB_Wan_RelayNode,
        "XB_Wan_InfiniteRelayNode": XB_Wan_InfiniteRelayNode,
        "XB_Video_Merger": XB_Video_Merger,
        "XB_StoryboardSlicer": XB_StoryboardSlicer,
        "XB_SageAttentionAccelerator": XB_SageAttentionAccelerator,
        # ── 借尸还魂：旧 ROCm 节点 ID → 别名类（兼容旧参数名） ──
        # ── 新原版优化节点 ──
        "XB_KSampler": XB_KSampler,
        "XB_KSamplerAdvanced": XB_KSamplerAdvanced,
        "XB_SamplerCustom": XB_SamplerCustom,
        "XB_SamplerCustomAdvanced": XB_SamplerCustomAdvanced,
        "XB_VAEDecode": XB_VAEDecode,
        "XB_VAEDecodeTiled": XB_VAEDecodeTiled,
        "XB_VAEDecodeTiledImage": XB_VAEDecodeTiledImage,
        "XB_VAEEncode": XB_VAEEncode,
        "XB_VAEEncodeTiled": XB_VAEEncodeTiled,
        "XB_VAEEncodeTiledImage": XB_VAEEncodeTiledImage,
        "XB_VAEEncodeForInpaint": XB_VAEEncodeForInpaint,
        "XB_WanCompileSettings": XB_WanCompileSettings,
        "XB_WanAnimateToVideo": XB_WanAnimateToVideo,
        "XB_WanAnimate_ParamBus": XB_WanAnimate_ParamBus,
        "XB_WanAnimate_RelayNode": XB_WanAnimate_RelayNode,
        "XB_WanInfiniteTalk_ParamBus": XB_WanInfiniteTalk_ParamBus,
        "XB_WanInfiniteTalk_RelayNode": XB_WanInfiniteTalk_RelayNode,
        "XB_Wan_InfiniteRelayNode_New": XB_Wan_InfiniteRelayNode_New,
        "XB_WanAnimate_RelayNode_New": XB_WanAnimate_RelayNode_New,
        "XB_WanInfiniteTalk_RelayNode_New": XB_WanInfiniteTalk_RelayNode_New,
        "XB_WanSCAIL_ParamBus_New": XB_WanSCAIL_ParamBus_New,
        "XB_WanSCAIL_RelayNode_New": XB_WanSCAIL_RelayNode_New,
        "XB_WanInfiniteTalk_RelayNode_MultiRef": XB_WanInfiniteTalk_RelayNode_MultiRef,
        "XB_WanInfiniteTalk_RelayNode_AllInOne": XB_WanInfiniteTalk_RelayNode_AllInOne,
        "XB_LTX23_InfiniteStreamer": XB_LTX23_InfiniteStreamer,
        "XB_NodeStatusSwitch": XB_NodeStatusSwitch,
        "XB_DisableGroups": XB_DisableGroups,
        "XB_DisableNodes": XB_DisableNodes,
        "XB_AnySwitch": XB_AnySwitch,
        "XB_FluxMultiImageEncode": XB_FluxMultiImageEncode,
        "XB_TextEncodeQwenImageEdit": XB_TextEncodeQwenImageEdit,
        "XB_TextEncodeQwenImageEditPlus": XB_TextEncodeQwenImageEditPlus,
        "XB_ImageScale": XB_ImageScale,
        "XB_ImageScalePixels": XB_ImageScalePixels,
        "XB_HailuoH3VideoParams": XB_HailuoH3VideoParams,
        "XB_ListDispatcher": XB_ListDispatcher,
        "XB_BatchImages": XB_BatchImages,
        "XB_ReferenceAny": XB_ReferenceAny,
        "XB_HumanSegmentation": XB_HumanSegmentation,
        "XB_HumanSegModelLoader": XB_HumanSegModelLoader,
        "XB_CanvasLabel": XB_CanvasLabel,
        "XB_AudioSlicer": XB_AudioSlicer,
        "XB_AudioSlicerV1": XB_AudioSlicerV1,
        "XB_AudioSlicerV2": XB_AudioSlicerV2,
        "XB_AudioSlicerV3": XB_AudioSlicerV3,
        "XB_DigitalHumanParams_Single": XB_DigitalHumanParams_Single,
        "XB_DigitalHumanParams_Dual": XB_DigitalHumanParams_Dual,
        "XB_ModelLoaderV1_GGUF": XB_ModelLoaderV1_GGUF,
        "XB_ModelLoaderV2_GGUF": XB_ModelLoaderV2_GGUF,
        "XB_ModelLoaderV3_GGUF": XB_ModelLoaderV3_GGUF,
        "XB_StringMerge": XB_StringMerge,
        "XB_CLIPTextEdit": XB_CLIPTextEdit,
        "XB_TripleLoraLoader": XB_TripleLoraLoader,
        "XB_TripleLoraLoaderModelOnly": XB_TripleLoraLoaderModelOnly,
        "XB_MSR": XB_MSR,
        "XB_ComicPromptParser": XB_ComicPromptParser,
        "XB_ComicTextRenderer": XB_ComicTextRenderer,
        "XB_AutoBubbleTextRenderer": XB_AutoBubbleTextRenderer,
        "XB_BerniniPromptRouter": XB_BerniniPromptRouter,
        "XB_K2StyleRouter": XB_K2StyleRouter,
        # ── CosyVoice3 音频节点 ──
        "XB_CosyVoice3_ModelLoader": XB_CosyVoice3_ModelLoader,
        "XB_CosyVoice3_ZeroShot": XB_CosyVoice3_ZeroShot,
        "XB_CosyVoice3_CrossLingual": XB_CosyVoice3_CrossLingual,
        "XB_CosyVoice3_VoiceConversion": XB_CosyVoice3_VoiceConversion,
        "XB_CosyVoice3_AudioCrop": XB_CosyVoice3_AudioCrop,
        "XB_CosyVoice3_Dialog": XB_CosyVoice3_Dialog,
        "XB_CosyVoice3_Instruct2": XB_CosyVoice3_Instruct2,
        "XB_CosyVoice3_SaveSpeaker": XB_CosyVoice3_SaveSpeaker,
        "XB_CosyVoice3_SpeakerClone": XB_CosyVoice3_SpeakerClone,
        "XB_CosyVoice3_SpeakerInstruct2": XB_CosyVoice3_SpeakerInstruct2,
    }

    # ── 🖼️ 生图预设（生图提示词预设 + 姿态/穿搭参考图）──
    if _IMAGE_PRESET_AVAILABLE:
        NODE_CLASS_MAPPINGS.update({
            "XB_ImagePreset": XB_ImagePreset,
        })

    # ── 🎬 保存视频 ──
    if _SAVE_VIDEO_AVAILABLE:
        NODE_CLASS_MAPPINGS.update({
            "XB_SaveVideo": XB_SaveVideo,
        })

    # ── 🎬 加载视频 ──
    if _LOAD_VIDEO_AVAILABLE:
        NODE_CLASS_MAPPINGS.update({
            "XB_LoadVideo": XB_LoadVideo,
        })

    # ── 条件注册 Llama 节点 ──
    if _LLAMA_AVAILABLE:
        NODE_CLASS_MAPPINGS.update({
            "XB_llamaModelLoader": XB_llamaModelLoader,
            "XB_llamaModelLoaderPro": XB_llamaModelLoaderPro,
            "XB_llamaInstruct": XB_llamaInstruct,
            "XB_llamaParameters": XB_llamaParameters,
            "XB_llamaUnloadModel": XB_llamaUnloadModel,
            "XB_llamaCleanStates": XB_llamaCleanStates,
            "XB_llamaBBoxes2BBox": XB_llamaBBoxes2BBox,
            "XB_llamaUnpackCodeBlock": XB_llamaUnpackCodeBlock,
            "XB_llamaPromptEnhancer": XB_llamaPromptEnhancer,
            "XB_llamaMiniMaxPreset": XB_llamaMiniMaxPreset,
            "XB_llamaMiniMaxRef2va": XB_llamaMiniMaxRef2vaPreset,
            "XB_llamaStoryboardEnhancer": XB_llamaStoryboardEnhancer,
            "XB_llamaStoryboardInstruct": XB_llamaStoryboardInstruct,
            "XB_llamaStoryboardProcessor": XB_llamaStoryboardProcessor,
            "XB_llamaStoryboardProcessorPro": XB_llamaStoryboardProcessorPro,
            "XB_RoleSceneDispatcher": XB_RoleSceneDispatcher,
            "XB_llamaPromptReverse": XB_llamaPromptReverse,
        })

    # ── 生图提示词预设Pro ──
    if _PRO_AVAILABLE:
        NODE_CLASS_MAPPINGS.update({
            "XB_ImagePromptPresetPro": XB_ImagePromptPresetPro,
        })

    # ── Qwen2.1提示词预设 ──
    if _QWEN_AVAILABLE:
        NODE_CLASS_MAPPINGS.update({
            "XB_QwenPromptPreset": XB_QwenPromptPreset,
        })

    # ── 🎵 YuE2 音乐节点 ──
    if _YUE2_AVAILABLE:
        NODE_CLASS_MAPPINGS.update({
            "XB_YuE2StylePrompt": XB_YuE2StylePrompt,
            "XB_YuE2Lyrics": XB_YuE2Lyrics,
            "XB_YuE2ScoreWorkbench": XB_YuE2ScoreWorkbench,
            "XB_YuE2CoverPrep": XB_YuE2CoverPrep,
            "XB_YuE2Transcription": XB_YuE2Transcription,
        })

    NODE_DISPLAY_NAME_MAPPINGS = { 
        "XB_VRAM_Calculator": "XB-BOX - VRAM Calculator",
        "XB_ChunkVisualization": "XB-BOX - Chunk Visualization",
        "XTX_Data_Radar": "XB-BOX - Data Radar",
        "XB_VideoParamsMaster": "XB-BOX - Video Params Master", 
        "XB_ImageParamsMaster": "XB-BOX - Image Params Master",
        "XB_ImageParamsMasterMini": "XB-BOX - Image Params Master Mini",
        "XB_ShenBi": "XB-BOX - 🖌️ ShenBi Brush",
        "XB_ImagePromptPreset": "XB-BOX - Image Prompt Preset",
        "XB_ImagePreset": "XB-BOX - 🖼️ 生图提示词预设（图）",
        "XB_PlaySound": "XB-BOX - 🔊 播放声音",
        "XB_MasterParameter": "XB-BOX - Master Parameter",
        "XB_VideoLoader": "XB-BOX - 🎬 视频加载器（修复预览BUG）",
        "XB_VideoCombine": "XB-BOX - 🎬 视频拼接输出",
        "XB_UNetBlockSwap": "XB-BOX - UNet Block Swap",
        "XB_CheckpointBlockSwap": "XB-BOX - Checkpoint Block Swap",
        "XB_Sage_BlockSwap": "XB-BOX - Acceleration + BlockSwap Duo",
        "XB_UNetNameBroadcaster": "XB-BOX - UNet Name Broadcaster",
        "XB_CLIPNameBroadcaster": "XB-BOX - CLIP Name Broadcaster",
        "XB_MemoryVisualization": "XB 📊 硬件监控面板 (Memory Visualization)",
        "XB_WanImageToVideo": "XB-BOX - Wan Image2Video",
        "XB_WanFirstLastFrameToVideo": "XB-BOX - Wan First/Last Frame2Video",
        "XB_BatchFolderLoader": "XB-BOX - 📂 图片序列加载",
        "XB_BatchFolderBatchLoader": "XB-BOX - 📂 图片批量加载",
        "XB_Wan_ParamBus": "XB-BOX - Wan Param Bus",
        "XB_Wan_RelayNode": "XB-BOX - Wan Relay Node",
        "XB_Wan_InfiniteRelayNode": "XB-BOX - Wan Infinite Relay Node",
        "XB_Video_Merger": "XB-BOX - Video Merger",
        "XB_StoryboardSlicer": "XB-BOX - Storyboard Slicer",
        "XB_SageAttentionAccelerator": "XB-BOX - Acceleration Mode Selector",
        # ── 借尸还魂：旧节点名 + 新的优化版显示名 ──
        # ── 新优化版节点 ──
        "XB_KSampler": "XB-BOX - 采样器（原版优化）",
        "XB_KSamplerAdvanced": "XB-BOX - 高级采样器（原版优化）",
        "XB_SamplerCustom": "XB-BOX - 自定义采样器（原版优化）",
        "XB_SamplerCustomAdvanced": "XB-BOX - 自定义高级采样器（原版优化）",
        "XB_VAEDecode": "XB-BOX - VAE解码（原版优化）",
        "XB_VAEDecodeTiled": "XB-BOX - VAE分块解码（原版优化）",
        "XB_VAEDecodeTiledImage": "XB-BOX - VAE分块解码·图片（原版优化）",
        "XB_VAEEncode": "XB-BOX - VAE编码（原版优化）",
        "XB_VAEEncodeTiled": "XB-BOX - VAE分块编码（原版优化）",
        "XB_VAEEncodeTiledImage": "XB-BOX - VAE分块编码·图片（原版优化）",
        "XB_VAEEncodeForInpaint": "XB-BOX - VAE修补编码（原版优化）",
        "XB_WanCompileSettings": "XB-BOX - ⚡ Wan 编译设置",
        "XB_WanAnimateToVideo": "XB-BOX - 🎬 Wan 动画转视频",
        "XB_WanAnimate_ParamBus": "XB-BOX - 🎬 Animate 动作迁移总线",
        "XB_WanAnimate_RelayNode": "XB-BOX - 🏃‍♀️ Animate 无限接力点",
        "XB_WanInfiniteTalk_ParamBus": "XB-BOX - 🎵 InfiniteTalk 无限对口型总线",
        "XB_WanInfiniteTalk_RelayNode": "XB-BOX - 🏃 InfiniteTalk 无限对口型接力点",
        "XB_Wan_InfiniteRelayNode_New": "XB-BOX - 🆕 Wan 无限接力点 (New)",
        "XB_WanAnimate_RelayNode_New": "XB-BOX - 🆕 Animate 无限接力点 (New)",
        "XB_WanInfiniteTalk_RelayNode_New": "XB-BOX - 🆕 InfiniteTalk 无限接力点 (New)",
        "XB_WanSCAIL_ParamBus_New": "XB-BOX - 🆕 SCAIL 总线 (New)",
        "XB_WanSCAIL_RelayNode_New": "XB-BOX - 🆕 SCAIL 无限接力点 (New)",
        "XB_WanInfiniteTalk_RelayNode_MultiRef": "XB-BOX - 🆕 InfiniteTalk 无限接力点 (多图)",
        "XB_WanInfiniteTalk_RelayNode_AllInOne": "XB-BOX - 🆕 InfiniteTalk 无限接力点 (全能)",
        "XB_LTX23_InfiniteStreamer": "XB-BOX - 🔄 LTX2.3 数字人无限时长对口型",
        "XB_NodeStatusSwitch": "XB-BOX - ⚡ 节点状态开关",
        "XB_DisableGroups": "XB-BOX - 🚫 禁用分组",
        "XB_DisableNodes": "XB-BOX - 🚫 禁用节点",
        "XB_AnySwitch": "XB-BOX - 🔀 切换任意",
        "XB_FluxMultiImageEncode": "XB-BOX - 🖼️ FLUX多图编码",
        "XB_TextEncodeQwenImageEdit": "XB-BOX - 📝 Qwen图像编辑编码",
        "XB_TextEncodeQwenImageEditPlus": "XB-BOX - 📝 Qwen图像编辑编码Plus",
        "XB_ImageScale": "XB-BOX - 📐 批量缩放图像",
        "XB_ImageScalePixels": "XB-BOX - 📐 批量缩放图像（像素）",
        "XB_HailuoH3VideoParams": "XB-BOX - 🌊 海螺H3视频参数",
        "XB_ListDispatcher": "XB-BOX - 📋 列表分发",
        "XB_BatchImages": "XB-BOX - 🖼️ 批量图像",

        "XB_ReferenceAny": "XB-BOX - 🔗 引用任意",
        "XB_HumanSegmentation": "XB-BOX - ✂️ 人物分割 (DirectML/ROCm)",
        "XB_HumanSegModelLoader": "XB-BOX - 📥 人物分割模型加载",
        "XB_CanvasLabel": "XB-BOX - 🏷️ Canvas Label (文字标签)",
        "XB_AudioSlicer": "XB-BOX - 🎵 音频切片（基础）",
        "XB_AudioSlicerV1": "XB-BOX - 🎵 音频切片V1（单人）",
        "XB_AudioSlicerV2": "XB-BOX - 🎵 音频切片V2（双人）",
        "XB_AudioSlicerV3": "XB-BOX - 🎵 音频切片V3（高级）",
        "XB_DigitalHumanParams_Single": "XB-BOX - 🤖 数字人参数调节（单人）",
        "XB_DigitalHumanParams_Dual": "XB-BOX - 🤖 数字人参数调节（双人）",
        "XB_ModelLoaderV1_GGUF": "XB-BOX - 📦 模型加载大全V1 (GGUF)",
        "XB_ModelLoaderV2_GGUF": "XB-BOX - 📦 模型加载大全V2 (GGUF)",
        "XB_ModelLoaderV3_GGUF": "XB-BOX - 📦 模型加载大全V3 (GGUF)",
        "XB_WanInfiniteTalkToVideo": "XB-BOX - 🎵 语音转视频分块",
        "XB_WanInfiniteTalkToVideo_Single": "XB-BOX - 🎵 语音转视频分块（单人）",
        "XB_WanInfiniteTalkToVideo_Dual": "XB-BOX - 🎵 语音转视频分块（双人）",
        "XB_StringMerge": "XB-BOX - 📝 字符串合并",
        "XB_CLIPTextEdit": "XB-BOX - 📝 CLIP 文本编辑",
        "XB_TripleLoraLoader": "XB-BOX - 🔗 三连 LoRA 加载",
        "XB_TripleLoraLoaderModelOnly": "XB-BOX - 🔗 三连 LoRA 加载（仅模型）",
        "XB_MSR": "XB-BOX - 🎞️ MSR 多图合成帧序列",
        "XB_ComicPromptParser": "XB-BOX - 📝 漫画提示词智能解析",
        "XB_ComicTextRenderer": "XB-BOX - 💬 漫画文字渲染 (精确坐标)",
        "XB_AutoBubbleTextRenderer": "XB-BOX - 🤖 漫画文字渲染 (全自动带涂改液)",
        "XB_BerniniConditioning": "XB-BOX - 🎨 Bernini 条件注入（VAE分块）",
        "XB_BerniniPromptRouter": "XB-BOX - 🧠 Bernini 提示词路由（超级节点）",
        "XB_K2StyleRouter": "XB-BOX - 🎨 K2 风格切换路由（超级节点）",
        # ── CosyVoice3 音频节点 ──
        "XB_CosyVoice3_ModelLoader": "XB-BOX - 🔊 CosyVoice3 模型加载",
        "XB_CosyVoice3_ZeroShot": "XB-BOX - 🎤 CosyVoice3 零样本克隆",
        "XB_CosyVoice3_CrossLingual": "XB-BOX - 🌐 CosyVoice3 跨语言合成",
        "XB_CosyVoice3_VoiceConversion": "XB-BOX - 🔄 CosyVoice3 语音转换",
        "XB_CosyVoice3_AudioCrop": "XB-BOX - ✂️ CosyVoice3 音频裁剪",
        "XB_CosyVoice3_Dialog": "XB-BOX - 💬 CosyVoice3 多人对话",
        "XB_CosyVoice3_Instruct2": "XB-BOX - 🎭 CosyVoice3 指令控制",
        "XB_CosyVoice3_SaveSpeaker": "XB-BOX - 💾 CosyVoice3 保存说话人",
        "XB_CosyVoice3_SpeakerClone": "XB-BOX - 🗣️ CosyVoice3 说话人克隆",
        "XB_CosyVoice3_SpeakerInstruct2": "XB-BOX - 🎭 CosyVoice3 说话人指令",
    }

    # ── 🎬 保存视频 显示名 ──
    if _SAVE_VIDEO_AVAILABLE:
        NODE_DISPLAY_NAME_MAPPINGS.update({
            "XB_SaveVideo": "XB-BOX - 🎬 保存视频",
        })

    # ── 🎬 加载视频 显示名 ──
    if _LOAD_VIDEO_AVAILABLE:
        NODE_DISPLAY_NAME_MAPPINGS.update({
            "XB_LoadVideo": "XB-BOX - 🎬 加载视频",
        })

    # ── 条件注册 Llama 显示名 ──
    if _LLAMA_AVAILABLE:
        NODE_DISPLAY_NAME_MAPPINGS.update({
            "XB_llamaModelLoader": "XB-llama - 📦 模型加载器",
            "XB_llamaModelLoaderPro": "XB-llama - 🚀 模型加载Pro",
            "XB_llamaInstruct": "XB-llama - 💬 指令推理",
            "XB_llamaParameters": "XB-llama - ⚙️ 推理参数",
            "XB_llamaUnloadModel": "XB-llama - 🗑️ 卸载模型",
            "XB_llamaCleanStates": "XB-llama - 🧹 清理状态",
            "XB_llamaBBoxes2BBox": "XB-llama - 🔍 BBoxes取BBox",
            "XB_llamaUnpackCodeBlock": "XB-llama - 📝 解包代码块",
            "XB_llamaPromptEnhancer": "XB-llama - ✨ 提示词增强预设",
            "XB_llamaMiniMaxPreset": "XB-llama - ✨ MiniMax-fl2va提示词预设",
            "XB_llamaMiniMaxRef2va": "XB-llama - ✨ MiniMax-ref2va提示词预设",
            "XB_llamaStoryboardEnhancer": "XB-llama - ✨ 分镜增强预设",
            "XB_llamaStoryboardInstruct": "XB-llama - 💬 分镜推理",
            "XB_llamaStoryboardProcessor": "XB-llama - 🎞️ 分镜词处理器",
            "XB_llamaStoryboardProcessorPro": "XB-llama - 🎞️ 分镜词处理器Pro",
            "XB_RoleSceneDispatcher": "XB-llama - 🎬 角色场景调度器",
            "XB_llamaPromptReverse": "XB-llama - ✨ 提示词增强反推",
        })

    # ── 生图提示词预设Pro 显示名 ──
    if _PRO_AVAILABLE:
        NODE_DISPLAY_NAME_MAPPINGS.update({
            "XB_ImagePromptPresetPro": "XB-BOX - 🖼️ 生图提示词预设Pro",
        })

    # ── Qwen2.1提示词预设 显示名 ──
    if _QWEN_AVAILABLE:
        NODE_DISPLAY_NAME_MAPPINGS.update({
            "XB_QwenPromptPreset": "XB-BOX - 🖼️ Qwen2.1提示词预设",
        })

    # ── 🎵 YuE2 音乐节点 显示名 ──
    if _YUE2_AVAILABLE:
        NODE_DISPLAY_NAME_MAPPINGS.update({
            "XB_YuE2StylePrompt": "XB-BOX - 🎵 YuE2 风格提示",
            "XB_YuE2Lyrics": "XB-BOX - 🎵 YuE2 歌词",
            "XB_YuE2ScoreWorkbench": "XB-BOX - 🎵 YuE2 乐谱工作台",
            "XB_YuE2CoverPrep": "XB-BOX - 🎵 YuE2 翻唱准备",
            "XB_YuE2Transcription": "XB-BOX - 🎵 YuE2 转谱导入",
        })

    print_success("\n" + XB_LOGO)
    print_success("="*50)
    print_success("🚀 [XB-BOX] XB_ToolBox Core Modules Loaded Successfully!")
    print_success("="*50 + "\n")

except Exception as e:
    print_error("\n" + "="*50)
    print_error("🚨 [XB-BOX] FATAL ERROR: XB_ToolBox Loading Failed!")
    print_error(f"❌ Error Detail: {str(e)}")
    traceback.print_exc()  
    print_error("="*50 + "\n")

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']