"""Fix: only show references actually cited in the answer text."""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    content = f.read()

# Replace: show all refs -> filter by cited positions in answer
old = """            if references:
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, ref_doc in references:
                    cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                    answer += f"[{ref_pos}] {cleaned}\\n"
            # Filter <think> blocks from reasoning models"""

new = """            if references:
                # Only show references actually cited in the answer ([1], [2], etc.)
                cited = set(int(m) for m in re.findall(r"\\[(\\d+)\\]", answer))
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, ref_doc in references:
                    if ref_pos in cited:
                        cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                        answer += f"[{ref_pos}] {cleaned}\\n"
            # Filter <think> blocks from reasoning models"""

if old in content:
    content = content.replace(old, new)
    print("[OK] Only show cited references")
else:
    print("[WARN] Pattern not found, checking...")
    for i, line in enumerate(content.split("\n")):
        if "references" in line or "ref_doc" in line:
            print(f"  L{i}: {repr(line.strip())}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
