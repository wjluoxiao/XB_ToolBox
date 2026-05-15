class XB_Dashboard_Zen:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {}}
    RETURN_TYPES = ()
    FUNCTION = "do_nothing"
    CATEGORY = "XB_ToolBox/Dashboard"
    def do_nothing(self, **kwargs):
        return ()