"""Fix RAGFlow issues: entrypoint crash, proxy bypass, dify endpoint."""
import os, sys

BASE = "/home/zhengkundeng/ragflow/docker"

# === Fix 1: entrypoint.sh server start ===
entrypoint_path = os.path.join(BASE, "entrypoint.sh")
with open(entrypoint_path, "r") as f:
    content = f.read()

old = """    while true; do
        echo "Attempt to start RAGFlow server..."
        "$PY" api/ragflow_server.py ${INIT_SUPERUSER_ARGS}
        echo "RAGFlow python server started."
        sleep 1;
    done &"""

new = """    # Start RAGFlow server (proxy bypass + auto-restart on crash)
    (
        while true; do
            echo "Attempt to start RAGFlow server..."
            unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY
            "$PY" api/ragflow_server.py ${INIT_SUPERUSER_ARGS} </dev/null
            echo "RAGFlow server exited, restarting in 2s..."
            sleep 2
        done
    ) &"""

if old in content:
    content = content.replace(old, new)
    with open(entrypoint_path, "w") as f:
        f.write(content)
    print("[OK] entrypoint.sh fixed")
else:
    print("[WARN] entrypoint pattern not found - may already be fixed")
    # Show current lines around server start
    for i, line in enumerate(content.split("\n")):
        if "RAGFlow server" in line or "ragflow_server" in line:
            print(f"  L{i}: {line.strip()}")

# === Fix 2: embedding_model_patched.py - add proxies=none to all requests.post calls ===
emb_path = os.path.join(BASE, "embedding_model_patched.py")
with open(emb_path, "r") as f:
    emb = f.read()

# Remove any previous botched proxy fixes
emb = emb.replace(
    '# Disable Docker Desktop proxy for direct API accessfor _p in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):    os.environ.pop(_p, None)',
    ''
)

# Add os.environ proxy clearing BEFORE dashscope import
if "import dashscope" in emb and 'os.environ.pop("HTTP_PROXY", None)' not in emb:
    emb = emb.replace(
        'import dashscope',
        '# Clear proxy env vars before dashscope import\n'
        'for _p in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):\n'
        '    os.environ.pop(_p, None)\n'
        'import dashscope'
    )
    print("[OK] embedding_model_patched.py proxy bypass added (pre-dashscope)")
else:
    print("[INFO] embedding_model_patched.py proxy fix already present")

# Add proxies={"http":None,"https":None} to all requests.post() calls
import re
count = 0
lines = emb.split("\n")
new_lines = []
for line in lines:
    new_lines.append(line)
    # Match lines like: response = requests.post(url, ...)
    if "requests.post(" in line and "proxies=" not in line:
        # Find the closing ) and insert proxies before it
        # Simple approach: add proxies to requests.post call
        if line.strip().endswith(")"):
            new_lines[-1] = line.rstrip(")").rstrip() + ", proxies={\"http\": None, \"https\": None})"
            count += 1
        elif line.strip().endswith("),"):
            new_lines[-1] = line.rstrip("),").rstrip() + ", proxies={\"http\": None, \"https\": None}),"
            count += 1

if count > 0:
    emb = "\n".join(new_lines)
    print(f"[OK] embedding_model_patched.py: added proxies=None to {count} requests.post calls")

with open(emb_path, "w") as f:
    f.write(emb)

# === Fix 3: docker-compose.yml - restore embedding model mount ===
compose_path = os.path.join(BASE, "docker-compose.yml")
with open(compose_path, "r") as f:
    compose = f.read()

# Ensure embedding model mount is enabled (not commented out)
compose = compose.replace(
    "#     - ./embedding_model_patched.py:/ragflow/rag/llm/embedding_model.py",
    "      - ./embedding_model_patched.py:/ragflow/rag/llm/embedding_model.py"
)
with open(compose_path, "w") as f:
    f.write(compose)
print("[OK] docker-compose.yml: embedding model mount restored")

print("\nAll fixes applied. Recreating container...")
