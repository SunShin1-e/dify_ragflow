"""Fix: clean doc names + filter think tags + add re import."""
import re

path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    content = f.read()

# Step 1: Add import re
if "import re\n" not in content[:200]:
    content = content.replace("import json\n", "import json\nimport re\n", 1)
    print("[OK] Added import re")

# Step 2: Clean doc names + filter think tags
old = '                    answer += f"[{ref_pos}] {ref_doc}\\n"\n        except Exception as exc:\n            answer = f"Errors：{exc}"'
new = '                    cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]\n                    answer += f"[{ref_pos}] {cleaned}\\n"\n            # Filter <think> blocks from reasoning models\n            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)\n        except Exception as exc:\n            answer = f"Errors：{exc}"'

if old in content:
    content = content.replace(old, new)
    print("[OK] Step 2: clean doc names + filter think tags")
else:
    print("[WARN] Step 2 pattern not found, checking...")
    for i, line in enumerate(content.split("\n")):
        if "ref_doc" in line:
            print(f"  L{i}: {repr(line.strip())}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
