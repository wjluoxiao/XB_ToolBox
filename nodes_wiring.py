import folder_paths

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
anyType = AnyType("*")

# ============================================================
# XB_UNetNameBroadcaster — UNet 名称广播器
# ============================================================
class XB_UNetNameBroadcaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "unet_name": (folder_paths.get_filename_list("unet"), ),
            }
        }

    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("UNet_Name",)
    FUNCTION = "broadcast"
    CATEGORY = "XB_ToolBox/Wiring"

    def broadcast(self, unet_name):
        return (unet_name,)

# ============================================================
# XB_CLIPNameBroadcaster — CLIP 名称广播器
# ============================================================
class XB_CLIPNameBroadcaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip_name": (folder_paths.get_filename_list("clip"), ),
            }
        }

    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("CLIP_Name",)
    FUNCTION = "broadcast"
    CATEGORY = "XB_ToolBox/Wiring"

    def broadcast(self, clip_name):
        return (clip_name,)