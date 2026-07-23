"""Fix: simplify references - dedup, sequential numbering, no citation matching."""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    content = f.read()

old = """                if references:
                    # Only show references actually cited in the answer ([1], [2], etc.)
                    cited = set(int(m) for m in re.findall(r"\\[(\\d+)\\]", answer))
                    answer += "\\n\\n---\\n📚 参考文档：\\n"
                    for ref_pos, ref_doc in references:
                        if ref_pos in cited:
                            cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                            answer += f"[{ref_pos}] {cleaned}\\n\""""

new = """                if references:
                    # Deduplicate and show simple numbered list
                    seen = set()
                    unique_docs = []
                    for _, ref_doc in references:
                        cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                        if cleaned not in seen:
                            seen.add(cleaned)
                            unique_docs.append(cleaned)
                    if unique_docs:
                        answer += "\\n\\n---\\n📚 参考文档：\\n"
                        for idx, doc_name in enumerate(unique_docs, 1):
                            answer += f"{idx}. {doc_name}\\n\""""

if old in content:
    content = content.replace(old, new)
    print("[OK] Simplified references")
else:
    # Try finding the right pattern
    for i, line in enumerate(content.split("\n")):
        if "cited" in line or "ref_pos in cited" in line:
            print(f"  L{i}: {repr(line)}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
