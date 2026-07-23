"""Fix wecom-bot plugin: streaming + citation + filter think tags + clean doc names."""
import sys, re

path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    content = f.read()

# ======== Fix 1: filter <think> tags ========
old_think = """            if references:
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, ref_doc in references:
                    answer += f"[{ref_pos}] {ref_doc}\\n"
        except Exception as exc:
            answer = f"Errors：{exc}\""""

new_think = """            if references:
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, ref_doc in references:
                    # Clean document name: strip path prefix, keep only filename
                    cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                    answer += f"[{ref_pos}] {cleaned}\\n"
            # Filter out <think>...</think> blocks from reasoning models
            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
        except Exception as exc:
            answer = f"Errors：{exc}\""""

if old_think in content:
    content = content.replace(old_think, new_think)
    print("[OK] Fix applied: filter <think> tags + clean doc names")
else:
    # Try to find what's currently there
    print("[WARN] Exact pattern not found, trying partial match...")
    # Check for just the think filtering issue (add think filter to existing code)
    old2 = """            answer = ""
            references = []
            for event in response_stream:
                if event.get("event") in ("message", "agent_message"):
                    answer += event.get("answer", "")
                elif event.get("event") == "message_end":
                    metadata = event.get("metadata", {})
                    if isinstance(metadata, dict):
                        for res in metadata.get("retriever_resources", []):
                            ref_doc = res.get("document_name", "")
                            ref_pos = res.get("position", "?")
                            if ref_doc:
                                references.append((ref_pos, ref_doc))
            if references:
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, ref_doc in references:
                    answer += f"[{ref_pos}] {ref_doc}\\n"
        except Exception as exc:
            answer = f"Errors：{exc}\""""

    new2 = """            answer = ""
            references = []
            for event in response_stream:
                if event.get("event") in ("message", "agent_message"):
                    answer += event.get("answer", "")
                elif event.get("event") == "message_end":
                    metadata = event.get("metadata", {})
                    if isinstance(metadata, dict):
                        for res in metadata.get("retriever_resources", []):
                            ref_doc = res.get("document_name", "")
                            ref_pos = res.get("position", "?")
                            if ref_doc:
                                references.append((ref_pos, ref_doc))
            if references:
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, ref_doc in references:
                    # Clean document name: strip path prefix, keep only filename
                    cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                    answer += f"[{ref_pos}] {cleaned}\\n"
            # Filter out <think>...</think> blocks from reasoning models
            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
        except Exception as exc:
            answer = f"Errors：{exc}\""""

    if old2 in content:
        content = content.replace(old2, new2)
        print("[OK] Fix applied (partial match): filter <think> tags + clean doc names")
    else:
        print("[ERROR] Cannot find code pattern to fix. Manual intervention needed.")
        for i, line in enumerate(content.split("\n")):
            if "references" in line or "retriever_resources" in line or "answer +=" in line:
                print(f"  L{i}: {line.strip()}")

if applied := (old_think in content or (old2 in content if 'old2' in dir() else False)):
    # Need to ensure `import re` is at top of file
    if "import re" not in content.split("\n")[0:5] and "import re\n" not in content.split("\n")[0:5]:
        # Add import re if not present
        content = content.replace("import json\n", "import json\nimport re\n", 1)
        if "import re" not in content.split("\n")[0:5]:
            content = content.replace("import logging\n", "import logging\nimport re\n", 1)

    with open(path, "w") as f:
        f.write(content)
    print("Done. File saved.")
else:
    print("Skipping save - no changes applied.")
