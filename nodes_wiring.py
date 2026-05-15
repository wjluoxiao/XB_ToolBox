import folder_paths

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
anyType = AnyType("*")

MAX_PORTS = 20

class XB_DynamicBus:
    @classmethod
    def INPUT_TYPES(s):
        inputs = {f"in_{i}": (anyType, ) for i in range(1, MAX_PORTS + 1)}
        return {"required": {}, "optional": inputs}

    RETURN_TYPES = tuple([anyType] * MAX_PORTS)
    RETURN_NAMES = tuple([f"out_{i}" for i in range(1, MAX_PORTS + 1)])
    FUNCTION = "route"
    CATEGORY = "XB_ToolBox/Wiring"

    def route(self, **kwargs):
        res = [kwargs.get(f"in_{i}") for i in range(1, MAX_PORTS + 1)]
        return tuple(res)

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