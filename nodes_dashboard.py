class XB_Dashboard_Zen:
    """ XB 远程控制中心 (终极版) """
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {}}
    RETURN_TYPES = ()
    FUNCTION = "do_nothing"
    CATEGORY = "小白工具箱/总控中心"
    def do_nothing(self, **kwargs):
        return ()