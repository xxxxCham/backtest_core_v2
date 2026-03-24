"""Multi-LLM orchestration layer for the parallel builder workspace."""

from .download_manager import install_missing_models, plan_missing_downloads
from .model_discovery import ModelInventory, discover_local_models
from .registry import (
    DEFAULT_MULTI_LLM_CONFIG_PATH,
    DEFAULT_MULTI_LLM_PROFILE,
    get_profile_definition,
    get_profile_role_pools,
    list_profile_names,
    load_multi_llm_config,
    resolve_profile_assignments,
    save_multi_llm_profile,
)
from .session_manager import MultiLLMCycleResult, MultiLLMSessionManager

__all__ = [
    "DEFAULT_MULTI_LLM_CONFIG_PATH",
    "DEFAULT_MULTI_LLM_PROFILE",
    "ModelInventory",
    "MultiLLMCycleResult",
    "MultiLLMSessionManager",
    "discover_local_models",
    "get_profile_definition",
    "get_profile_role_pools",
    "install_missing_models",
    "list_profile_names",
    "load_multi_llm_config",
    "plan_missing_downloads",
    "resolve_profile_assignments",
    "save_multi_llm_profile",
]
