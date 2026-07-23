"""Fix wecom URL to use /doc-download/ proxy path"""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path) as f:
    content = f.read()

# Fix 1: URL path
old1 = 'url = f"{ragflow_url}/api/v1/datasets/{ds_id}/documents/{doc_id}"'
new1 = 'url = f"{ragflow_url}/doc-download/datasets/{ds_id}/documents/{doc_id}"'

if old1 in content:
    content = content.replace(old1, new1)
    print("[OK] URL path: /api/v1/ -> /doc-download/")
else:
    print("[WARN] Pattern not found, searching...")
    for i, line in enumerate(content.split("\n")):
        if "datasets" in line and "doc_id" in line:
            print(f"  L{i}: {repr(line.strip())}")

# Fix 2: Remove :80 port
old2 = '"http://10.18.160.120:80"'
new2 = '"http://10.18.160.120"'
if old2 in content:
    content = content.replace(old2, new2)
    print("[OK] Removed :80 port from URL")
else:
    print("[WARN] Port pattern not found")

with open(path, "w") as f:
    f.write(content)
print("Done.")
