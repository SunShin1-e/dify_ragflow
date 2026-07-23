"""Test if monkey-patched requests works with dashscope SDK."""
import sys
sys.path.insert(0, "/ragflow")

# Import embedding_model to trigger monkey-patch
from rag.llm.embedding_model import QWenEmbed

# Test with dashscope SDK directly (should use patched requests)
import dashscope
print("=== Test 1: dashscope SDK with fake key (expect 401, NOT SSL error) ===")
try:
    resp = dashscope.TextEmbedding.call(
        model="text-embedding-v3",
        input=["你好"],
        api_key="sk-fake-test-key",
        text_type="document",
    )
    print(f"status_code={resp.status_code}")
except Exception as e:
    error_msg = str(e)
    if "SSL" in error_msg or "EOF" in error_msg:
        print(f"FAIL - Still getting SSL error: {e}")
    else:
        print(f"OK - Not SSL error: {type(e).__name__}: {e}")

print("\n=== Test 2: Multiple concurrent calls ===")
import concurrent.futures
def do_call(i):
    try:
        resp = dashscope.TextEmbedding.call(
            model="text-embedding-v3",
            input=["测试"],
            api_key="sk-test-key",
            text_type="document",
        )
        return f"Call {i}: status={resp.status_code}"
    except Exception as e:
        return f"Call {i}: {type(e).__name__}: {e}"

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
    futures = [ex.submit(do_call, i) for i in range(5)]
    for f in concurrent.futures.as_completed(futures):
        print(f.result())
