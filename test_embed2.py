"""Test RAGFlow embedding model - find correct config and test."""
import sys
sys.path.insert(0, "/ragflow")

# Find the actual API key from RAGFlow config
from common.settings import init_settings
init_settings()

import common.settings as settings
# Check what's available
for attr in dir(settings):
    v = getattr(settings, attr)
    # Look for dict-like attributes that might contain LLM configs
    if isinstance(v, dict) and len(v) > 0:
        keys = list(v.keys())
        # Check if any key contains tongyi or qwen
        key_str = str(keys[:5])
        if any("tongyi" in str(k).lower() or "qwen" in str(k).lower() for k in keys):
            print(f"Found attr: {attr}, keys: {list(v.keys())[:10]}")
            for k, cfg in v.items():
                if isinstance(cfg, dict):
                    print(f"  {k}: api_key={cfg.get('api_key', 'N/A')[:10]}..., model={cfg.get('model_name', 'N/A')}")
