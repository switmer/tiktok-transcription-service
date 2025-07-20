import os
from typing import List, Dict, Any
import logging
from .manager import TikTokAPIManager

logger = logging.getLogger(__name__)

def create_tiktok_api_manager() -> TikTokAPIManager:
    """
    Create and configure a TikTokAPIManager with adapters based on environment variables.
    
    Environment variables:
    - RAPIDAPI_KEY: Single RapidAPI key to use for all adapters (recommended)
    - RAPIDAPI_KEYS: Comma-separated list of RapidAPI keys (fallback to legacy)
    
    Adapter-specific keys (optional, will fallback to RAPIDAPI_KEY if not set):
    - RAPIDAPI_V2_KEYS: Keys specifically for v2 adapters
    - RAPIDAPI_API6_KEYS: Keys specifically for API6 adapters  
    - RAPIDAPI_DOWNLOADVIDEO_KEYS: Keys specifically for DownloadVideo adapters
    
    Hosts (optional):
    - RAPIDAPI_HOSTS, RAPIDAPI_V2_HOSTS, RAPIDAPI_API6_HOSTS, RAPIDAPI_DOWNLOADVIDEO_HOSTS
    
    Other:
    - ENABLE_TIKWM: Set to 'true' to enable TikWM adapter (default: true)
    """
    manager = TikTokAPIManager()
    
    # Get the primary API key (supports both single key and legacy multi-key format)
    primary_key = os.getenv("RAPIDAPI_KEY", "").strip()
    fallback_keys = os.getenv("RAPIDAPI_KEYS", "").strip()
    
    # Helper function to get keys for a specific adapter type
    def get_adapter_keys(adapter_env_var: str) -> List[str]:
        """Get keys for a specific adapter, with fallback to primary key."""
        # First try adapter-specific keys
        adapter_keys = os.getenv(adapter_env_var, "").strip()
        if adapter_keys:
            return [key.strip() for key in adapter_keys.split(",") if key.strip()]
        
        # Fallback to primary key
        if primary_key:
            return [primary_key]
            
        # Fallback to legacy multi-key format
        if fallback_keys:
            return [key.strip() for key in fallback_keys.split(",") if key.strip()]
        
        return []
    
    # Add RapidAPI v1 adapters
    rapidapi_keys = get_adapter_keys("RAPIDAPI_KEYS")
    if rapidapi_keys:
        hosts_env = os.getenv("RAPIDAPI_HOSTS", "").strip()
        
        if hosts_env:
            hosts = [host.strip() for host in hosts_env.split(",") if host.strip()]
            # Ensure we have enough hosts for all keys
            while len(hosts) < len(rapidapi_keys):
                hosts.append("tiktok-scraper7.p.rapidapi.com")  # Default host
        else:
            hosts = ["tiktok-scraper7.p.rapidapi.com"] * len(rapidapi_keys)
        
        for i, key in enumerate(rapidapi_keys):
            host = hosts[i] if i < len(hosts) else "tiktok-scraper7.p.rapidapi.com"
            try:
                manager.add_rapidapi_adapter(key, host)
                logger.info(f"Added RapidAPI v1 adapter {i+1} with host: {host}")
            except Exception as e:
                logger.error(f"Failed to add RapidAPI v1 adapter {i+1}: {e}")
    
    # Add RapidAPI v2 adapters
    rapidapi_v2_keys = get_adapter_keys("RAPIDAPI_V2_KEYS")
    if rapidapi_v2_keys:
        hosts_env = os.getenv("RAPIDAPI_V2_HOSTS", "").strip()
        
        if hosts_env:
            hosts = [host.strip() for host in hosts_env.split(",") if host.strip()]
            while len(hosts) < len(rapidapi_v2_keys):
                hosts.append("tiktok-scraper2.p.rapidapi.com")
        else:
            hosts = ["tiktok-scraper2.p.rapidapi.com"] * len(rapidapi_v2_keys)
        
        for i, key in enumerate(rapidapi_v2_keys):
            host = hosts[i] if i < len(hosts) else "tiktok-scraper2.p.rapidapi.com"
            try:
                manager.add_rapidapi_v2_adapter(key, host)
                logger.info(f"Added RapidAPI v2 adapter {i+1} with host: {host}")
            except Exception as e:
                logger.error(f"Failed to add RapidAPI v2 adapter {i+1}: {e}")
    
    # Add RapidAPI API6 adapters
    rapidapi_api6_keys = get_adapter_keys("RAPIDAPI_API6_KEYS")
    if rapidapi_api6_keys:
        hosts_env = os.getenv("RAPIDAPI_API6_HOSTS", "").strip()
        
        if hosts_env:
            hosts = [host.strip() for host in hosts_env.split(",") if host.strip()]
            while len(hosts) < len(rapidapi_api6_keys):
                hosts.append("tiktok-api6.p.rapidapi.com")
        else:
            hosts = ["tiktok-api6.p.rapidapi.com"] * len(rapidapi_api6_keys)
        
        for i, key in enumerate(rapidapi_api6_keys):
            host = hosts[i] if i < len(hosts) else "tiktok-api6.p.rapidapi.com"
            try:
                manager.add_rapidapi_api6_adapter(key, host)
                logger.info(f"Added RapidAPI API6 adapter {i+1} with host: {host}")
            except Exception as e:
                logger.error(f"Failed to add RapidAPI API6 adapter {i+1}: {e}")
    
    # Add RapidAPI DownloadVideo adapters
    rapidapi_downloadvideo_keys = get_adapter_keys("RAPIDAPI_DOWNLOADVIDEO_KEYS")
    if rapidapi_downloadvideo_keys:
        hosts_env = os.getenv("RAPIDAPI_DOWNLOADVIDEO_HOSTS", "").strip()
        
        if hosts_env:
            hosts = [host.strip() for host in hosts_env.split(",") if host.strip()]
            while len(hosts) < len(rapidapi_downloadvideo_keys):
                hosts.append("tiktok-download-video1.p.rapidapi.com")
        else:
            hosts = ["tiktok-download-video1.p.rapidapi.com"] * len(rapidapi_downloadvideo_keys)
        
        for i, key in enumerate(rapidapi_downloadvideo_keys):
            host = hosts[i] if i < len(hosts) else "tiktok-download-video1.p.rapidapi.com"
            try:
                manager.add_rapidapi_downloadvideo_adapter(key, host)
                logger.info(f"Added RapidAPI DownloadVideo adapter {i+1} with host: {host}")
            except Exception as e:
                logger.error(f"Failed to add RapidAPI DownloadVideo adapter {i+1}: {e}")
    
    # Add TikWM adapter if enabled
    enable_tikwm = os.getenv("ENABLE_TIKWM", "true").lower() == "true"
    if enable_tikwm:
        try:
            manager.add_tikwm_adapter()
            logger.info("Added TikWM adapter")
        except Exception as e:
            logger.error(f"Failed to add TikWM adapter: {e}")
    
    if not manager.adapters:
        logger.warning("No TikTok API adapters were configured!")
    else:
        logger.info(f"TikTok API Manager initialized with {len(manager.adapters)} adapters")
    
    return manager

def get_adapter_config_info() -> Dict[str, Any]:
    """Get information about adapter configuration from environment."""
    # Helper function to get keys for a specific adapter type (same as in create_tiktok_api_manager)
    primary_key = os.getenv("RAPIDAPI_KEY", "").strip()
    fallback_keys = os.getenv("RAPIDAPI_KEYS", "").strip()
    
    def get_adapter_keys(adapter_env_var: str) -> List[str]:
        adapter_keys = os.getenv(adapter_env_var, "").strip()
        if adapter_keys:
            return [key.strip() for key in adapter_keys.split(",") if key.strip()]
        if primary_key:
            return [primary_key]
        if fallback_keys:
            return [key.strip() for key in fallback_keys.split(",") if key.strip()]
        return []
    
    # Get actual configured keys for each adapter type
    v1_keys = get_adapter_keys("RAPIDAPI_KEYS")
    v2_keys = get_adapter_keys("RAPIDAPI_V2_KEYS") 
    api6_keys = get_adapter_keys("RAPIDAPI_API6_KEYS")
    downloadvideo_keys = get_adapter_keys("RAPIDAPI_DOWNLOADVIDEO_KEYS")
    
    enable_tikwm = os.getenv("ENABLE_TIKWM", "true").lower() == "true"
    
    return {
        "primary_key_set": bool(primary_key),
        "total_adapters_configured": (
            len(v1_keys) + len(v2_keys) + len(api6_keys) + 
            len(downloadvideo_keys) + (1 if enable_tikwm else 0)
        ),
        "adapters": {
            "rapidapi_v1": len(v1_keys),
            "rapidapi_v2": len(v2_keys),
            "rapidapi_api6": len(api6_keys),
            "rapidapi_downloadvideo": len(downloadvideo_keys),
            "tikwm": 1 if enable_tikwm else 0,
        },
        "configuration_method": (
            "PRIMARY_KEY" if primary_key else
            "LEGACY_MULTI_KEY" if fallback_keys else
            "ADAPTER_SPECIFIC" if any([
                os.getenv("RAPIDAPI_V2_KEYS"), 
                os.getenv("RAPIDAPI_API6_KEYS"),
                os.getenv("RAPIDAPI_DOWNLOADVIDEO_KEYS")
            ]) else
            "NONE"
        ),
        "environment_variables": {
            "RAPIDAPI_KEY": "SET" if primary_key else "NOT_SET",
            "RAPIDAPI_KEYS": "SET" if fallback_keys else "NOT_SET", 
            "RAPIDAPI_V2_KEYS": "SET" if os.getenv("RAPIDAPI_V2_KEYS") else "NOT_SET",
            "RAPIDAPI_API6_KEYS": "SET" if os.getenv("RAPIDAPI_API6_KEYS") else "NOT_SET",
            "RAPIDAPI_DOWNLOADVIDEO_KEYS": "SET" if os.getenv("RAPIDAPI_DOWNLOADVIDEO_KEYS") else "NOT_SET",
            "ENABLE_TIKWM": os.getenv("ENABLE_TIKWM", "true")
        }
    }