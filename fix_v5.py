"""Fix: remove dedup - keep all citation numbers for traceability."""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    content = f.read()

# Replace dedup block with simple display (no dedup)
old = """            if references:
                # Deduplicate by document name (keep first occurrence order)
                seen_docs = set()
                unique_refs = []
                for ref_pos, ref_doc in references:
                    cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                    if cleaned not in seen_docs:
                        seen_docs.add(cleaned)
                        unique_refs.append((ref_pos, cleaned))
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, cleaned in unique_refs:
                    answer += f"[{ref_pos}] {cleaned}\\n"
            # Filter <think> blocks from reasoning models"""

new = """            if references:
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, ref_doc in references:
                    cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                    answer += f"[{ref_pos}] {cleaned}\\n"
            # Filter <think> blocks from reasoning models"""

if old in content:
    content = content.replace(old, new)
    print("[OK] Removed dedup - all citations preserved")
else:
    print("[WARN] Pattern not found, checking...")
    for i, line in enumerate(content.split("\n")):
        if "references" in line or "seen_docs" in line or "unique_refs" in line:
            print(f"  L{i}: {repr(line.strip())}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
