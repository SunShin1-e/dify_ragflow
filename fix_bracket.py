"""Fix citation regex to handle multi-level [8.1.2] markers."""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    lines = f.readlines()

new_line = '                answer = re.sub(r"\[\d+(?:\.\d+)*\]", "", answer)\n'

for i, line in enumerate(lines):
    # Find the remove-citation re.sub line
    if "answer = re.sub" in line:
        old_line = line
        lines[i] = new_line
        print(f"L{i}: {repr(old_line.strip())}")
        print(f"  -> {repr(new_line.strip())}")
        break

with open(path, "w") as f:
    f.writelines(lines)
print("Done.")
