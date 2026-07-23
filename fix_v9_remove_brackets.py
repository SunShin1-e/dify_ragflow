"""Fix: remove inline citation markers like [1], [2.1], [10] from answer text."""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    content = f.read()

old = '                # Filter <think> blocks from reasoning models\n                answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)'

new = '''                # Filter <think> blocks from reasoning models
                answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
                # Remove inline citation markers like [1], [10], [2.1]
                answer = re.sub(r"\[\d+(?:\.\d+)?\]", "", answer)'''

if old in content:
    content = content.replace(old, new)
    print("[OK] Added citation marker removal")
else:
    print("[WARN] Pattern not found")
    for i, line in enumerate(content.split("\n")):
        if "think" in line.lower():
            print(f"  L{i}: {repr(line.strip())}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
