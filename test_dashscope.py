import sys
sys.path.insert(0, "/ragflow")
from rag.llm.embedding_model import QWenEmbed

try:
    embed = QWenEmbed(key="sk-test", model_name="text-embedding-v3")
    vts, used = embed.encode(["test"])
    print(f"SUCCESS: {len(vts)} vectors, {used} tokens")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
