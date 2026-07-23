import os
import sys

print("=== Before embedding_model import ===")
for v in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY"]:
    print(f"{v}={os.environ.get(v, 'NOT SET')}")

sys.path.insert(0, "/ragflow")
from rag.llm import embedding_model

print("=== After embedding_model import ===")
for v in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    print(f"{v}={os.environ.get(v, 'NOT SET')}")

# Test connectivity to dashscope
print("=== Testing connectivity ===")
import requests
try:
    r = requests.get("https://dashscope.aliyuncs.com", timeout=10)
    print(f"Direct: status={r.status_code}")
except Exception as e:
    print(f"Direct: {e}")

# Try with explicit no-proxy
try:
    r = requests.get("https://dashscope.aliyuncs.com", timeout=10, proxies={"http": None, "https": None})
    print(f"No-proxy: status={r.status_code}")
except Exception as e:
    print(f"No-proxy: {e}")
