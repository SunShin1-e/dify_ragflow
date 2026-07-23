"""Hardcode RAGFlow base URL in wecom_message.py"""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path) as f:
    content = f.read()

# Replace settings.get with hardcoded URL, keeping settings as override
old = 'ragflow_url = settings.get("ragflow_base_url", "").rstrip("/")'
new = 'ragflow_url = settings.get("ragflow_base_url", "http://10.18.160.120:9381").rstrip("/")'

if old in content:
    content = content.replace(old, new)
    print("[OK] Hardcoded RAGFlow URL: http://10.18.160.120:9381")
else:
    print("[WARN] Pattern not found")
    for i, line in enumerate(content.split("\n")):
        if "ragflow" in line:
            print(f"  L{i}: {line.strip()}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
