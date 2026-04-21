import folder_paths

# ==========================================
# 🎛️ 动态总线底层依赖 (我们的终极破壁武器 AnyType)
# ==========================================
class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
anyType = AnyType("*")

MAX_PORTS = 20

# ==========================================
# 节点 1：动态数据总线
# ==========================================
class XB_DynamicBus:
    """
    极客版动态数据总线 (N进N出)。
    """
    @classmethod
    def INPUT_TYPES(s):
        inputs = {f"in_{i}": (anyType, ) for i in range(1, MAX_PORTS + 1)}
        return {"required": {}, "optional": inputs}

    RETURN_TYPES = tuple([anyType] * MAX_PORTS)
    RETURN_NAMES = tuple([f"out_{i}" for i in range(1, MAX_PORTS + 1)])
    FUNCTION = "route"
    CATEGORY = "小白工具箱/布线整理"

    def route(self, **kwargs):
        res = [kwargs.get(f"in_{i}") for i in range(1, MAX_PORTS + 1)]
        return tuple(res)


# ==========================================
# 节点 2：UNet 名称分发器 (一键换挡中枢)
# ==========================================
class XB_UNetNameBroadcaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "unet_name": (folder_paths.get_filename_list("unet"), ),
            }
        }

    # 🟢 核心修复：把 "STRING" 改为 anyType，强行突破前端的类型隔离！
    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("UNet名称",)
    FUNCTION = "broadcast"
    CATEGORY = "小白工具箱/布线整理"

    def broadcast(self, unet_name):
        return (unet_name,)


# ==========================================
# 节点 3：CLIP 名称分发器 (一键换挡中枢)
# ==========================================
class XB_CLIPNameBroadcaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip_name": (folder_paths.get_filename_list("clip"), ),
            }
        }

    # 🟢 核心修复：同样使用 anyType 强行突破！
    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("CLIP名称",)
    FUNCTION = "broadcast"
    CATEGORY = "小白工具箱/布线整理"

    def broadcast(self, clip_name):
        return (clip_name,)