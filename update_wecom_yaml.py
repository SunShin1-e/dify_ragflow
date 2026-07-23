"""Add ragflow_base_url setting to wecom.yaml"""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/group/wecom.yaml"

with open(path) as f:
    content = f.read()

new_setting = """
  - name: ragflow_base_url
    type: text-input
    required: false
    label:
      en_US: RAGFlow Base URL
      zh_Hans: RAGFlow 访问地址
    placeholder:
      en_US: e.g. http://192.168.1.100:9381
      zh_Hans: 例如 http://192.168.1.100:9381
    help:
      en_US: Base URL of RAGFlow for document download links in reference list
      zh_Hans: RAGFlow 的访问地址，用于参考文档的下载链接"""

old = "\nendpoints:"
if old in content and "ragflow_base_url" not in content:
    content = content.replace(old, new_setting + old)
    with open(path, "w") as f:
        f.write(content)
    print("[OK] wecom.yaml updated")
elif "ragflow_base_url" in content:
    print("[INFO] ragflow_base_url already exists")
else:
    print("[ERROR] endpoints: not found")

# Print current state
with open(path) as f:
    for line in f.readlines():
        if "ragflow" in line.lower():
            print(line.rstrip())
