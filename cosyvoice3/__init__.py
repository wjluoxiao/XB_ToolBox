"""
XB CosyVoice3 - Advanced Text-to-Speech for ComfyUI
Zero-shot voice cloning, cross-lingual synthesis, and instruction-based control
"""

import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

# Import nodes
from .nodes.model_loader import XB_CosyVoice3_ModelLoader
from .nodes.zero_shot import XB_CosyVoice3_ZeroShot
from .nodes.cross_lingual import XB_CosyVoice3_CrossLingual
from .nodes.voice_conversion import XB_CosyVoice3_VoiceConversion
from .nodes.audio_crop import XB_CosyVoice3_AudioCrop
from .nodes.dialog import XB_CosyVoice3_Dialog
from .nodes.instruct2 import XB_CosyVoice3_Instruct2
from .nodes.save_speaker import XB_CosyVoice3_SaveSpeaker
from .nodes.speaker_clone import XB_CosyVoice3_SpeakerClone
from .nodes.speaker_instruct2 import XB_CosyVoice3_SpeakerInstruct2

# Node class mappings
NODE_CLASS_MAPPINGS = {
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

# Node display name mappings
NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_CosyVoice3_ModelLoader": "XB CosyVoice3 Model Loader",
    "XB_CosyVoice3_ZeroShot": "XB CosyVoice3 Zero-Shot Clone",
    "XB_CosyVoice3_CrossLingual": "XB CosyVoice3 Cross-Lingual",
    "XB_CosyVoice3_VoiceConversion": "XB CosyVoice3 Voice Conversion",
    "XB_CosyVoice3_AudioCrop": "XB CosyVoice3 Audio Crop",
    "XB_CosyVoice3_Dialog": "XB CosyVoice3 Dialog",
    "XB_CosyVoice3_Instruct2": "XB CosyVoice3 Instruct2",
    "XB_CosyVoice3_SaveSpeaker": "XB CosyVoice3 Save Speaker",
    "XB_CosyVoice3_SpeakerClone": "XB CosyVoice3 Speaker Clone",
    "XB_CosyVoice3_SpeakerInstruct2": "XB CosyVoice3 Speaker Instruct2",
}

# ASCII art banner
ascii_art = """
⡎⠑ ⢀⡀ ⢀⣀ ⡀⢀ ⡇⢸ ⢀⡀ ⠄ ⢀⣀ ⢀⡀ ⢉⡹
⠣⠔ ⠣⠜ ⠭⠕ ⣑⡺ ⠸⠃ ⠣⠜ ⠇ ⠣⠤ ⠣⠭ ⠤⠜
"""
print(f"\033[35m{ascii_art}\033[0m")
print("XB CosyVoice3 Custom Nodes Loaded - Version 1.2.1")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
