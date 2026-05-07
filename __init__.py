from .nodes import DynamicRAMCacheControl, RAMCacheExtremeCleanup, SmartRAMCacheCleanup, GlobalPhysicalRAMMonitor

NODE_CLASS_MAPPINGS = {
    "DynamicRAMCacheControl": DynamicRAMCacheControl,
    "RAMCacheExtremeCleanup": RAMCacheExtremeCleanup,
    "SmartRAMCacheCleanup": SmartRAMCacheCleanup,
    "GlobalPhysicalRAMMonitor": GlobalPhysicalRAMMonitor
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DynamicRAMCacheControl": "🔥 Dynamic RAM Cache Control",
    "RAMCacheExtremeCleanup": "🧹 RAM Cache Extreme Cleanup",
    "SmartRAMCacheCleanup": "🧠 Smart RAM Cache Cleanup",
    "GlobalPhysicalRAMMonitor": "🌐 Global Physical RAM Monitor"
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
