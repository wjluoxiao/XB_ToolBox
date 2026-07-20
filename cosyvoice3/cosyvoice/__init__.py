import os
# 禁止 ANSI 颜色码，避免 Windows 控制台乱码
os.environ.setdefault("NO_COLOR", "1")
os.environ.setdefault("FORCE_COLOR", "0")

# 抑制 PyTorch AOTriton 警告（AMD ROCm 正常行为）
import warnings
warnings.filterwarnings("ignore", message=".*AOTriton backend.*")
warnings.filterwarnings("ignore", message=".*Triggered internally.*")
