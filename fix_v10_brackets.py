"""Fix: match multi-level citation markers like [8.1.2]"""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    content = f.read()

old = '                answer = re.sub(r"\[\d+(?:\.\d+)?\]", "", answer)'
new = '                answer = re.sub(r"\\[\\d+(?:\\.\\d+)*\\]", "", answer)'

if old in content:
    content = content.replace(old, new)
    print("[OK] Fixed to match multi-level citations [8.1.2]")
else:
    print("[WARN] Not found, checking...")
    for i, line in enumerate(content.split("\n")):
        if "citation" in line.lower() or "re.sub" in line:
            print(f"  L{i}: {repr(line.strip())}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
