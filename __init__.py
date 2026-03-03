from .nodes import DynamicRAMCacheControl, RAMCacheExtremeCleanup, SmartRAMCacheCleanup

NODE_CLASS_MAPPINGS = {
    "DynamicRAMCacheControl": DynamicRAMCacheControl,
    "RAMCacheExtremeCleanup": RAMCacheExtremeCleanup,
    "SmartRAMCacheCleanup": SmartRAMCacheCleanup
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DynamicRAMCacheControl": "🔥 Dynamic RAM Cache Control",
    "RAMCacheExtremeCleanup": "🧹 RAM Cache Extreme Cleanup",
    "SmartRAMCacheCleanup": "🧠 Smart RAM Cache Cleanup"
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
