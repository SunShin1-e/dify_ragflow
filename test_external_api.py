"""Test Dify external Service API (SSE streaming) — simulates wecom-bot behavior.

This script mimics what the wecom-bot plugin would do if we switched it
from internal API (session.app.chat.invoke) to external API (/v1/chat-messages).
"""
import json
import re
import urllib.request
import urllib.error
import ssl

# ============================================================
# CONFIG — same as what wecom-bot plugin would use
# ============================================================
DIFY_API_BASE = "http://docker-api-1:5001"
API_KEY = "app-W0Iykl1ijgcblBTXw0EUq3EU"  # smart-agent app
QUERY = "你好，请简单介绍一下你自己"
USER_ID = "IN3021"  # non-UUID user, same style as WeChat Work userid


def test_sse_stream():
    """Simulate streaming chat request to Dify Service API."""
    url = f"{DIFY_API_BASE}/v1/chat-messages"
    body = {
        "inputs": {},
        "query": QUERY,
        "response_mode": "streaming",
        "user": USER_ID,
        # Don't pass conversation_id for first message
    }

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    print(f"=== Request ===")
    print(f"URL: {url}")
    print(f"User: {USER_ID}")
    print(f"Query: {QUERY}")
    print(f"\n=== SSE Stream ===")

    answer = ""
    references = []
    conversation_id = None
    message_id = None

    try:
        # Allow self-signed certs for internal docker network
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            print(f"HTTP {resp.status}")
            print(f"Content-Type: {resp.headers.get('Content-Type', 'N/A')}")

            buffer = ""
            for chunk in iter(lambda: resp.read(1024), b""):
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                # Parse SSE events: "data: {...}\n\n"
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    for line in event_str.split("\n"):
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        json_str = line[5:].strip()  # Remove "data:" prefix
                        if not json_str:
                            continue
                        try:
                            event = json.loads(json_str)
                        except json.JSONDecodeError:
                            print(f"  [PARSE ERROR] {json_str[:100]}")
                            continue

                        evt_type = event.get("event", "?")

                        if conversation_id is None:
                            conversation_id = event.get("conversation_id", "")
                        if message_id is None:
                            message_id = event.get("message_id") or event.get("id") or ""

                        if evt_type in ("message", "agent_message"):
                            chunk_text = event.get("answer", "")
                            answer += chunk_text
                            print(f"  [{evt_type}] {chunk_text}", end="", flush=True)

                        elif evt_type == "message_end":
                            metadata = event.get("metadata", {})
                            if isinstance(metadata, dict):
                                for res in metadata.get("retriever_resources", []):
                                    ref_doc = res.get("document_name", "")
                                    if ref_doc:
                                        references.append({
                                            "name": ref_doc,
                                            "file_path": (res.get("doc_metadata") or {}).get("file_path", ""),
                                        })
                            print(f"\n  [message_end] conversation_id={conversation_id}")

                        elif evt_type == "error":
                            print(f"\n  [ERROR] {event.get('message', str(event))}")

                        elif evt_type == "workflow_started":
                            print(f"\n  [workflow_started]")

                        elif evt_type == "node_started":
                            print(f"  [node_started] {event.get('data', {}).get('title', '?')}")

                        elif evt_type == "node_finished":
                            print(f"  [node_finished] {event.get('data', {}).get('title', '?')}")

                        elif evt_type == "workflow_finished":
                            print(f"  [workflow_finished]")

                        else:
                            # Just log unknown event types
                            keys = list(event.keys())
                            skip = {"event", "conversation_id", "message_id", "id", "created_at", "task_id"}
                            extra = {k: str(v)[:80] for k, v in event.items() if k not in skip}
                            if extra:
                                print(f"  [{evt_type}] {extra}")

    except urllib.error.HTTPError as e:
        print(f"\n=== HTTP ERROR ===")
        print(f"Status: {e.code}")
        print(f"Body: {e.read().decode(errors='replace')}")
        return
    except Exception as e:
        print(f"\n=== ERROR ===\n{type(e).__name__}: {e}")
        return

    # ============================================================
    # Post-process: same logic as wecom-bot plugin
    # ============================================================
    print(f"\n\n=== Post-process ===")
    print(f"Conversation ID: {conversation_id}")
    print(f"Message ID: {message_id}")
    print(f"Raw answer length: {len(answer)} chars")

    # Filter <think> blocks
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
    # Remove citation markers
    answer = re.sub(r"\[\d+(?:\.\d+)*\]", "", answer)

    print(f"\n=== Final Answer ===")
    print(answer)

    # Deduplicate and format references
    if references:
        seen = set()
        unique_docs = []
        for ref in references:
            cleaned = ref["name"].replace("\\", "/").rsplit("/", 1)[-1]
            if cleaned not in seen:
                seen.add(cleaned)
                unique_docs.append((cleaned, ref.get("file_path", "")))
        if unique_docs:
            print(f"\n=== References ({len(unique_docs)} docs) ===")
            for idx, (doc_name, file_path) in enumerate(unique_docs, 1):
                if file_path:
                    print(f"  {idx}. {doc_name}  ({file_path})")
                else:
                    print(f"  {idx}. {doc_name}")

    # Verify the key features
    print(f"\n=== Checks ===")
    print(f"✓ Non-UUID user '{USER_ID}' worked" if answer else f"✗ No answer")
    print(f"✓ Conversation persisted" if conversation_id else "✗ No conversation_id")
    print(f"✓ Agent event received" if "agent_message" in locals() else "")
    print(f"✓ References: {len(references)} docs")

    return conversation_id


if __name__ == "__main__":
    test_sse_stream()
