import os, json, ast

# 1. Validate nodes.py
ast.parse(open(r'd:\AI_JZL\XB_ToolBox\minimax_h3\nodes.py', encoding='utf-8').read())
print('nodes.py OK')

# 2. Update minimax_h3/__init__.py
init_content = '''"""
MiniMax-H3 一键漫剧创作 — 独立节点包
=====================================
总线信号链: ScriptWriter → ShotFormatter → SceneDispatcher → PromptGenerator
"""

import os as _os
WEB_DIRECTORY = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "js")

from .nodes import (
    XB_MiniMax_ScriptWriter,
    XB_MiniMax_ShotFormatter,
    XB_MiniMax_SceneDispatcher,
    XB_MiniMax_PromptGenerator,
)

NODE_CLASS_MAPPINGS = {
    "XB_MiniMax_ScriptWriter": XB_MiniMax_ScriptWriter,
    "XB_MiniMax_ShotFormatter": XB_MiniMax_ShotFormatter,
    "XB_MiniMax_SceneDispatcher": XB_MiniMax_SceneDispatcher,
    "XB_MiniMax_PromptGenerator": XB_MiniMax_PromptGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_MiniMax_ScriptWriter": "MiniMax - 🎬 剧本编剧",
    "XB_MiniMax_ShotFormatter": "MiniMax - 📋 分镜格式化",
    "XB_MiniMax_SceneDispatcher": "MiniMax - 🎯 场景调度器",
    "XB_MiniMax_PromptGenerator": "MiniMax - ✍️ 提示词生成器",
}
'''
open(r'd:\AI_JZL\XB_ToolBox\minimax_h3\__init__.py', 'w', encoding='utf-8').write(init_content)

# 3. Update XB_ToolBox main __init__.py - remove Bus references
main = open(r'd:\AI_JZL\XB_ToolBox\__init__.py', encoding='utf-8').read()
main = main.replace('XB_MiniMax_Bus,\n            ', '')
main = main.replace('            "XB_MiniMax_Bus": XB_MiniMax_Bus,\n', '')
main = main.replace('            "XB_MiniMax_Bus": "MiniMax - 🔗 总线",\n', '')
open(r'd:\AI_JZL\XB_ToolBox\__init__.py', 'w', encoding='utf-8').write(main)
ast.parse(open(r'd:\AI_JZL\XB_ToolBox\__init__.py', encoding='utf-8').read())
print('main __init__.py OK')

# 4. Update nodeDefs
for proj, pfx in [(r'd:\AI_JZL\XB_ToolBox', 'XB_'), (r'D:\AI_JZL\ComfyUI-JLZ-llama-cpp', 'JZL_')]:
    nd = os.path.join(proj, 'locales', 'zh', 'nodeDefs.json')
    with open(nd, encoding='utf-8') as f:
        data = json.load(f)

    data.pop(pfx + 'MiniMax_Bus', None)
    data.pop(pfx + 'MiniMax_RefDispatcher', None)
    data.pop(pfx + 'MiniMax_ShotRunner', None)

    data[pfx + 'MiniMax_ScriptWriter'] = {
        'display_name': 'MiniMax - 🎬 剧本编剧',
        'description': '总线生产者。拆解/生成故事为分镜序列。',
        'inputs': {
            'llm_backend': {'name': '🔧 LLM后端'}, 'mode': {'name': '📋 工作模式'},
            'story_name': {'name': '📛 故事名称'}, 'story_input': {'name': '📝 故事输入'},
            'story_style': {'name': '🎨 故事风格'}, 'shot_length': {'name': '🎬 分镜长度'},
            'llama_model': {'name': '🦙 Llama模型'}, 'parameters': {'name': '⚙️ 推理参数'},
            'api_response': {'name': '☁️ API响应'},
        },
        'outputs': {'0': {'name': '🔗 总线'}, '1': {'name': '📋 分镜文本'}},
    }

    data[pfx + 'MiniMax_ShotFormatter'] = {
        'display_name': 'MiniMax - 📋 分镜格式化',
        'description': '解析分镜文本为JSON，按镜保存TXT。总线透传。',
        'inputs': {'bus': {'name': '🔗 总线'}, 'shot_text': {'name': '📝 分镜文本'}},
        'outputs': {'0': {'name': '🔗 总线'}, '1': {'name': '📋 分镜JSON'}},
    }

    data[pfx + 'MiniMax_SceneDispatcher'] = {
        'display_name': 'MiniMax - 🎯 场景调度器',
        'description': '动态接入参考图，自动分类，读提示词TXT，输出给MiniMax-H3。支持重拍。',
        'inputs': {
            'bus': {'name': '🔗 总线'}, 'shots_json': {'name': '📋 分镜JSON'},
            'shot_index': {'name': '🔢 镜头编号'}, 'reshoot_mode': {'name': '🔄 重拍模式'},
            'reshoot_shot': {'name': '🎯 重拍镜头'},
        },
        'outputs': {
            '0': {'name': '🔗 总线'}, '1': {'name': '🖼️ ref_0'}, '2': {'name': '🖼️ ref_1'},
            '3': {'name': '🖼️ ref_2'}, '4': {'name': '🖼️ ref_3'}, '5': {'name': '🖼️ ref_4'},
            '6': {'name': '🖼️ ref_5'}, '7': {'name': '🖼️ ref_6'}, '8': {'name': '🖼️ ref_7'},
            '9': {'name': '🖼️ ref_8'}, '10': {'name': '✍️ 提示词'},
        },
    }

    data[pfx + 'MiniMax_PromptGenerator'] = {
        'display_name': 'MiniMax - ✍️ 提示词生成器',
        'description': '从总线获取LLM，读取分镜词和调度记录，生成Minimax-H3最终提示词。',
        'inputs': {'bus': {'name': '🔗 总线'}, 'shot_script': {'name': '📝 分镜脚本'}, 'shot_index': {'name': '🔢 镜头编号'}},
        'outputs': {'0': {'name': '✍️ H3提示词'}},
    }

    with open(nd, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'{pfx} nodeDefs OK ({len(data)} entries)')

# 5. Sync to JLZ
for f in ['nodes.py', '__init__.py']:
    src = os.path.join(r'd:\AI_JZL\XB_ToolBox\minimax_h3', f)
    dst = os.path.join(r'D:\AI_JZL\ComfyUI-JLZ-llama-cpp\minimax_h3', f)
    c = open(src, encoding='utf-8').read()
    c = c.replace('XB_MiniMax', 'JZL_MiniMax').replace('XB_ToolBox', 'JZL_ToolBox').replace('XB-llama', 'JZL-llama')
    open(dst, 'w', encoding='utf-8').write(c)
    ast.parse(open(dst, encoding='utf-8').read())
    print(f'JLZ {f} OK')

print('ALL DONE')
