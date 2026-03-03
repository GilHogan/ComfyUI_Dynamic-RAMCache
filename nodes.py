import gc
import logging
import time
import psutil
import ctypes
from ctypes import wintypes
import sys

caching = None
execution = None

# Import execution module
try:
    import execution
except ImportError:
    logging.error("[DynamicRAMCache] Failed to import execution module")
    logging.error("[DynamicRAMCache] This may be due to ComfyUI version update to 2025.10.31. Please check if module structure has changed.")
    
# Import caching module
try:
    from comfy_execution import caching
    # Check if RAMPressureCache class exists in the imported caching module
    if caching is not None and not hasattr(caching, 'RAMPressureCache'):
        logging.error("[DynamicRAMCache] RAMPressureCache class not found in caching module")
        logging.error("[DynamicRAMCache] This class may only exist in ComfyUI versions after 2025.10.31")
except ImportError:
    logging.error("[DynamicRAMCache] Failed to import caching module")
    logging.error("[DynamicRAMCache] This may be due to ComfyUI version update to 2025.10.31. Please check if module structure has changed.")

# Ensure both modules are successfully imported
if execution is None or caching is None:
    logging.error("[DynamicRAMCache] Critical module import failed, plugin may not work correctly")
    logging.error("[DynamicRAMCache] Plugin compatibility with ComfyUI 2025.10.31 needs to be verified. Module structure may have changed.")

# Windows API for accurate Committed Memory detection
class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('CommitTotal', ctypes.c_size_t),
        ('CommitLimit', ctypes.c_size_t),
        ('CommitPeak', ctypes.c_size_t),
        ('PhysicalTotal', ctypes.c_size_t),
        ('PhysicalAvailable', ctypes.c_size_t),
        ('SystemCache', ctypes.c_size_t),
        ('KernelTotal', ctypes.c_size_t),
        ('KernelPaged', ctypes.c_size_t),
        ('KernelNonpaged', ctypes.c_size_t),
        ('PageSize', ctypes.c_size_t),
        ('HandleCount', wintypes.DWORD),
        ('ProcessCount', wintypes.DWORD),
        ('ThreadCount', wintypes.DWORD),
    ]

def get_free_commit_gb():
    """Get available memory headroom in GB (Win: Commit, Linux: Available RAM)"""
    if sys.platform == 'win32':
        try:
            psapi = ctypes.windll.psapi
            perf_info = PERFORMANCE_INFORMATION()
            perf_info.cb = ctypes.sizeof(PERFORMANCE_INFORMATION)
            if psapi.GetPerformanceInfo(ctypes.byref(perf_info), perf_info.cb):
                page_size = perf_info.PageSize
                free_commit_bytes = (perf_info.CommitLimit - perf_info.CommitTotal) * page_size
                return free_commit_bytes / (1024**3)
        except Exception as e:
            logging.debug(f"[DynamicRAMCache] Windows API GetPerformanceInfo failed: {e}")
    
    # On Linux, virtual_memory().available is the most accurate indicator of pressure
    return psutil.virtual_memory().available / (1024**3)

class AlwaysEqualProxy(str):
    def __eq__(self, _):
        return True

    def __ne__(self, _):
        return False

any_type = AlwaysEqualProxy("*")

class DynamicRAMCacheControl:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "mode": (["CLASSIC (No Eviction)", "RAM_PRESSURE (Auto Purge)"], {"default": "RAM_PRESSURE (Auto Purge)"}),
                "cleanup_threshold": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 256.0, "step": 0.1, "tooltip": "Minimum free RAM to maintain (GB)"}),
            },
            "optional": {
                "any_input": (any_type, {}),
            }
        }

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("output_passthrough",)
    FUNCTION = "manage_cache"
    CATEGORY = "utils/dynamic_ramcache"

    def manage_cache(self, mode, cleanup_threshold, any_input=None):
        if caching is not None and execution is not None:
            self._execute_cache_logic(mode, cleanup_threshold)
        else:
            logging.warning("[DynamicRAMCache] Plugin disabled: Missing internal modules.")

        if any_input is not None:
            return (any_input,)
        else:
            try:
                from comfy_execution.graph import ExecutionBlocker
                return (ExecutionBlocker(None),)
            except ImportError:
                return (None,)

    def _execute_cache_logic(self, mode, cleanup_threshold):

        target_mode_ram = "RAM_PRESSURE" in mode

        executor = self._find_executor()
        
        if executor is None:
            logging.warning("[DynamicRAMCache] PromptExecutor not found.")
            return

        if not hasattr(executor, 'cache_args'):
            executor.cache_args = {}
        
        old_ram_arg = executor.cache_args.get('ram', 0)
        executor.cache_args['ram'] = cleanup_threshold

        cache_set = self._get_cache_set(executor)
        if cache_set is None:
            return

        current_cache = cache_set.outputs

        RAMPressureCacheClass = getattr(caching, 'RAMPressureCache', None)
        HierarchicalCacheClass = getattr(caching, 'HierarchicalCache', None)

        if not RAMPressureCacheClass:
            logging.error("[DynamicRAMCache] RAMPressureCache class not available in caching module")
            logging.error("[DynamicRAMCache] This class is required for RAM_PRESSURE mode and may only exist in ComfyUI versions after 2025.10.31")
            logging.error("[DynamicRAMCache] Please check your ComfyUI version or consider switching to CLASSIC mode")
            return
        
        if not HierarchicalCacheClass:
            logging.error("[DynamicRAMCache] HierarchicalCache class not available in caching module")
            return

        is_currently_ram = isinstance(current_cache, RAMPressureCacheClass)

        if target_mode_ram and not is_currently_ram:
            self._switch_to_ram_pressure(cache_set, current_cache, caching)
            logging.info(f"[DynamicRAMCache] Switched mode: CLASSIC -> RAM_PRESSURE (Headroom: {cleanup_threshold}GB)")
        
        elif not target_mode_ram and is_currently_ram:
            self._switch_to_classic(cache_set, current_cache, caching)
            logging.info(f"[DynamicRAMCache] Switched mode: RAM_PRESSURE -> CLASSIC")
        
        elif target_mode_ram and is_currently_ram:
            if old_ram_arg != cleanup_threshold:
                logging.info(f"[DynamicRAMCache] Updated RAM Headroom: {old_ram_arg}GB -> {cleanup_threshold}GB")

        if target_mode_ram and hasattr(cache_set.outputs, 'poll'):
            try:
                cache_set.outputs.poll(cleanup_threshold)
            except Exception:
                pass

    def _find_executor(self):
        for obj in gc.get_objects():
            if obj.__class__.__name__ == 'PromptExecutor':
                return obj
        return None

    def _get_cache_set(self, executor):
        if not hasattr(executor, 'caches'):
            logging.warning("[DynamicRAMCache] PromptExecutor has no 'caches' attribute.")
            return None
        
        cache_set = executor.caches

        if not hasattr(cache_set, 'outputs'):
            logging.warning("[DynamicRAMCache] CacheSet has no 'outputs' attribute.")
            return None
        return cache_set

    def _update_cache_set(self, cache_set, new_cache):

        cache_set.outputs = new_cache
        
        if hasattr(cache_set, 'all') and isinstance(cache_set.all, list):
            for i, item in enumerate(cache_set.all):
                if i == 0: 
                    cache_set.all[i] = new_cache

    def _switch_to_ram_pressure(self, cache_set, old_cache, caching_mod):
        key_class = getattr(old_cache, 'key_class', None)
        if not key_class:
            key_class = getattr(caching_mod, 'CacheKeySetInputSignature', None)

        new_cache = caching_mod.RAMPressureCache(key_class)
        self._migrate_cache_data(old_cache, new_cache)

        new_cache.timestamps = {}
        new_cache.used_generation = {}
        new_cache.children = {}
        new_cache.generation = 1
        new_cache.min_generation = 0

        now = time.time()
        for key in new_cache.cache:
            new_cache.timestamps[key] = now
            new_cache.used_generation[key] = 0 

        self._update_cache_set(cache_set, new_cache)

    def _switch_to_classic(self, cache_set, old_cache, caching_mod):
        key_class = getattr(old_cache, 'key_class', None)
        if not key_class:
            key_class = getattr(caching_mod, 'CacheKeySetInputSignature', None)

        new_cache = caching_mod.HierarchicalCache(key_class)
        self._migrate_cache_data(old_cache, new_cache)

        self._update_cache_set(cache_set, new_cache)

    def _migrate_cache_data(self, old_cache, new_cache):
        """迁移缓存核心数据"""
        # Fix for 'NullCache' object has no attribute 'cache'
        if hasattr(old_cache, 'cache'):
            new_cache.cache = old_cache.cache
        
        if hasattr(old_cache, 'subcaches'):
            new_cache.subcaches = old_cache.subcaches
            
        new_cache.dynprompt = getattr(old_cache, 'dynprompt', None)
        new_cache.cache_key_set = getattr(old_cache, 'cache_key_set', None)
        new_cache.initialized = getattr(old_cache, 'initialized', False)

class RAMCacheExtremeCleanup(DynamicRAMCacheControl):
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "purge_threshold": ("FLOAT", {"default": 256.0, "min": 0.1, "max": 256.0, "step": 0.1, "tooltip": "Minimum free RAM to maintain (GB)"}),
            },
            "optional": {
                "any_input": (any_type, {}),
            }
        }

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("output_passthrough",)
    FUNCTION = "extreme_cleanup"
    CATEGORY = "utils/dynamic_ramcache"

    def extreme_cleanup(self, purge_threshold, any_input=None):
        if caching is not None and execution is not None:
            executor = self._find_executor()
            if executor is None:
                logging.warning("[DynamicRAMCache] PromptExecutor not found.")
            else:
                if not hasattr(executor, 'cache_args'):
                    executor.cache_args = {}
                old_ram_arg = executor.cache_args.get('ram', 2.0)
                cache_set = self._get_cache_set(executor)
                if cache_set is not None:
                    RAMPressureCacheClass = getattr(caching, 'RAMPressureCache', None)
                    if RAMPressureCacheClass:
                        is_currently_ram = isinstance(cache_set.outputs, RAMPressureCacheClass)
                        old_mode = "RAM_PRESSURE (Auto Purge)" if is_currently_ram else "CLASSIC (No Eviction)"
                    else:
                        old_mode = "CLASSIC (No Eviction)"
                    self._execute_cache_logic("RAM_PRESSURE (Auto Purge)", purge_threshold)
                    self._execute_cache_logic(old_mode, old_ram_arg)
        else:
            logging.warning("[DynamicRAMCache] Plugin disabled: Missing internal modules.")

        if any_input is not None:
            return (any_input,)
        else:
            try:
                from comfy_execution.graph import ExecutionBlocker
                return (ExecutionBlocker(None),)
            except ImportError:
                return (None,)


class SmartRAMCacheCleanup(DynamicRAMCacheControl):
    _is_cleaning_in_progress = False
    _last_cleaned_timestamp = 0.0
    COOLDOWN_SECONDS = 2.0 

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "purge_threshold": ("FLOAT", {"default": 256.0, "min": 0.1, "step": 0.1, "tooltip": "Threshold used during purge (GB)"}),
                "min_free_ram_gb": ("FLOAT", {"default": 2.0, "min": 0.0, "step": 0.1, "tooltip": "Trigger purge if free RAM is below this (GB)"}),
                "min_commit_free_gb": ("FLOAT", {"default": 2.0, "min": 0.0, "step": 0.1, "tooltip": "Trigger purge if free Commit is below this (GB)"}),
            },
            "optional": {
                "any_input": (any_type, {}),
            }
        }

    RETURN_TYPES = (any_type,)
    RETURN_NAMES = ("output_passthrough",)
    FUNCTION = "smart_cleanup"
    CATEGORY = "utils/dynamic_ramcache"

    def smart_cleanup(self, purge_threshold, min_free_ram_gb, min_commit_free_gb, any_input=None):
        if SmartRAMCacheCleanup._is_cleaning_in_progress:
            return (any_input,) if any_input is not None else (None,)

        current_time = time.time()
        if (current_time - SmartRAMCacheCleanup._last_cleaned_timestamp) < SmartRAMCacheCleanup.COOLDOWN_SECONDS:
            return (any_input,) if any_input is not None else (None,)

        if caching is not None and execution is not None:
            # 获取当前内存状态
            vm = psutil.virtual_memory()
            free_ram_gb = vm.available / (1024**3)
            
            # 使用准确的 Windows Commit 检测逻辑
            free_commit_gb = get_free_commit_gb()

            needs_cleanup = False

            logging.info(f"[DynamicRAMCache] : Free RAM ({free_ram_gb:.2f}GB), Free Commit ({free_commit_gb:.2f}GB)")
            if min_free_ram_gb > 0 and free_ram_gb < min_free_ram_gb:
                logging.info(f"[DynamicRAMCache] ⚠️ Smart Cleanup Triggered: Free RAM ({free_ram_gb:.2f}GB) < {min_free_ram_gb}GB")
                needs_cleanup = True
            elif min_commit_free_gb > 0 and free_commit_gb < min_commit_free_gb:
                logging.info(f"[DynamicRAMCache] ⚠️ Smart Cleanup Triggered: Free Commit ({free_commit_gb:.2f}GB) < {min_commit_free_gb}GB")
                needs_cleanup = True

            if needs_cleanup:
                SmartRAMCacheCleanup._is_cleaning_in_progress = True
                try:
                    executor = self._find_executor()
                    if executor is None:
                        logging.warning("[DynamicRAMCache] PromptExecutor not found.")
                    else:
                        if not hasattr(executor, 'cache_args'):
                            executor.cache_args = {}
                        old_ram_arg = executor.cache_args.get('ram', 2.0)
                        cache_set = self._get_cache_set(executor)
                        if cache_set is not None:
                            RAMPressureCacheClass = getattr(caching, 'RAMPressureCache', None)
                            if RAMPressureCacheClass:
                                is_currently_ram = isinstance(cache_set.outputs, RAMPressureCacheClass)
                                old_mode = "RAM_PRESSURE (Auto Purge)" if is_currently_ram else "CLASSIC (No Eviction)"
                            else:
                                old_mode = "CLASSIC (No Eviction)"
                            
                            # 临时调高阈值强制触发清理
                            self._execute_cache_logic("RAM_PRESSURE (Auto Purge)", purge_threshold)
                            # 恢复原有模式和阈值
                            self._execute_cache_logic(old_mode, old_ram_arg)
                finally:
                    SmartRAMCacheCleanup._is_cleaning_in_progress = False
                    SmartRAMCacheCleanup._last_cleaned_timestamp = time.time()
        else:
            logging.warning("[DynamicRAMCache] Plugin disabled: Missing internal modules.")

        if any_input is not None:
            return (any_input,)
        else:
            try:
                from comfy_execution.graph import ExecutionBlocker
                return (ExecutionBlocker(None),)
            except ImportError:
                return (None,)
