"""Test RAGFlow embedding model with actual API key from config."""
import sys, os
sys.path.insert(0, "/ragflow")

# Import settings to get real API key
from common.settings import init_settings
init_settings()

# Now test the actual embedding
from rag.llm.embedding_model import QWenEmbed
import json

# Find Tongyi-Qianwen config
from common.settings import LLM_FACTORY
for k, v in LLM_FACTORY.items():
    if "tongyi" in k.lower() or "qwen" in k.lower():
        api_key = v.get("api_key", "")[:10] + "..."
        model = v.get("model_name", "?")
        base_url = v.get("base_url", "?")
        print(f"Found: {k}")
        print(f"  model: {model}, base_url: {base_url}, key: {api_key}")

print("\n=== Testing QWenEmbed with actual config ===")
try:
    # Get the real config
    for k, v in LLM_FACTORY.items():
        if "tongyi" in k.lower() or "qwen" in k.lower():
            embed = QWenEmbed(key=v.get("api_key"), model_name=v.get("model_name", "text-embedding-v3"))
            print(f"Calling encode(['你好'])...")
            vts, used = embed.encode(["你好"])
            print(f"SUCCESS: {len(vts)} vectors, dim={len(vts[0]) if vts else '?'}, tokens={used}")
            break
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
