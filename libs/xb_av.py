"""
XB-ToolBox 音频/媒体容器打开工具
================================
PyAV 的健壮封装。

背景：部分 MP3 的 ID3 标签"声明为 UTF-8"却实际写入非 UTF-8 字节（例如中文
GBK/ANSI 标签、或损坏的 UTF-8），PyAV 在 open() 阶段就会解码容器元数据并抛出
UnicodeDecodeError，导致文件**完全打不开**（音频节点报加载失败、波形为空）。

退回 latin-1 重新打开即可：latin-1 是单字节编码，任意字节序列都合法，因此元数据
解码不会失败；音频轨道的解码数据与采样率不受影响（已实测）。
"""


def open_av(path, **kwargs):
    """打开媒体容器；遇到非 UTF-8 元数据时自动退回 latin-1 解码。

    用法与 av.open 完全一致（含 context manager）：
        with open_av(filepath) as container:
            ...
    """
    import av

    try:
        return av.open(path, **kwargs)
    except UnicodeDecodeError as exc:
        try:
            return av.open(path, metadata_encoding="latin-1", **kwargs)
        except TypeError:
            # 老版本 PyAV 不认识该参数 —— 报出原始的解码错误，避免用 TypeError 掩盖真因
            raise exc
