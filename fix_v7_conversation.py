"""Fix: add multi-turn conversation support (memory)."""
path = "/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/wecom_message.py"

with open(path, "r") as f:
    content = f.read()

# === Replace the entire try block with conversation-aware version ===
old = """        try:
            app = settings.get("app")
            user_id = payload.get("from", {}).get("userid", "wecom-user")
            response_stream = self.session.app.chat.invoke(
                app_id=app.get("app_id"),
                query=content,
                user=user_id,
                inputs={},
                response_mode="streaming",
            )
            answer = ""
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
                # Only show references actually cited in the answer ([1], [2], etc.)
                cited = set(int(m) for m in re.findall(r"\\[(\\d+)\\]", answer))
                answer += "\\n\\n---\\n📚 参考文档：\\n"
                for ref_pos, ref_doc in references:
                    if ref_pos in cited:
                        cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                        answer += f"[{ref_pos}] {cleaned}\\n"
            # Filter <think> blocks from reasoning models
            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
        except Exception as exc:
            answer = f"Errors：{exc}\""""

new = """        try:
            app = settings.get("app")
            user_id = payload.get("from", {}).get("userid", "wecom-user")

            # Support resetting conversation
            if content.strip() in ("新对话", "重置对话", "清除记忆", "/new", "/reset"):
                self.session.storage.delete(f"conv_{user_id}")
                answer = "✅ 对话已重置，可以开始新对话。"
            else:
                # Load existing conversation_id for multi-turn
                conversation_id = None
                if self.session.storage.exist(f"conv_{user_id}"):
                    conversation_id = self.session.storage.get(f"conv_{user_id}").decode()

                response_stream = self.session.app.chat.invoke(
                    app_id=app.get("app_id"),
                    query=content,
                    user=user_id,
                    inputs={},
                    response_mode="streaming",
                    conversation_id=conversation_id,
                )
                answer = ""
                references = []
                new_conversation_id = None
                for event in response_stream:
                    if new_conversation_id is None:
                        new_conversation_id = event.get("conversation_id", "")
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
                # Save conversation_id for next turn
                if new_conversation_id:
                    self.session.storage.set(f"conv_{user_id}", new_conversation_id.encode())
                if references:
                    # Only show references actually cited in the answer ([1], [2], etc.)
                    cited = set(int(m) for m in re.findall(r"\\[(\\d+)\\]", answer))
                    answer += "\\n\\n---\\n📚 参考文档：\\n"
                    for ref_pos, ref_doc in references:
                        if ref_pos in cited:
                            cleaned = ref_doc.replace("\\\\", "/").rsplit("/", 1)[-1]
                            answer += f"[{ref_pos}] {cleaned}\\n"
                # Filter <think> blocks from reasoning models
                answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
        except Exception as exc:
            answer = f"Errors：{exc}\""""

if old in content:
    content = content.replace(old, new)
    print("[OK] Added multi-turn conversation support")
else:
    print("[WARN] Pattern not found")
    for i, line in enumerate(content.split("\n")):
        if "conversation_id" in line or "conv_" in line or "response_stream" in line:
            print(f"  L{i}: {repr(line.strip())}")

with open(path, "w") as f:
    f.write(content)
print("Done.")
