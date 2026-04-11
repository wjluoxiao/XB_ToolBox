class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
anyType = AnyType("*")

MAX_PORTS = 20

class XB_DynamicBus:
    """
    极客版动态数据总线 (N进N出)。
    后端只负责提供最高 20 个数据通道，前端负责完美的视觉重构。
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
        # 严格按顺序将接收到的数据穿透送出，没接线的地方送出 None
        res = [kwargs.get(f"in_{i}") for i in range(1, MAX_PORTS + 1)]
        return tuple(res)