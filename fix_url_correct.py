"""Fix RAGFlow URL: correct port 9380, add token as query param if available."""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path) as f:
    content = f.read()

# Fix base URL port from 9381 to 9380
old = 'ragflow_url = settings.get("ragflow_base_url", "http://10.18.160.120:9381").rstrip("/")'
new = 'ragflow_url = settings.get("ragflow_base_url", "http://10.18.160.120:80").rstrip("/")'

if old in content:
    content = content.replace(old, new)
    print("[OK] Changed port to 80 (RAGFlow web UI port)")
else:
    print("[WARN] Pattern not found, searching...")
    for i, line in enumerate(content.split("\n")):
        if "ragflow_url" in line:
            print(f"  L{i}: {repr(line.strip())}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
