"""Test Dify API response speed: TTFB + full completion time."""
import time, json, ssl, urllib.request

DIFY_API_BASE = "http://docker-api-1:5001"
API_KEY = "app-W0Iykl1ijgcblBTXw0EUq3EU"
QUERY = "你好"

url = f"{DIFY_API_BASE}/v1/chat-messages"
body = json.dumps({
    "inputs": {}, "query": QUERY,
    "response_mode": "streaming", "user": "test",
}).encode("utf-8")
req = urllib.request.Request(url, data=body, headers={
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}, method="POST")

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# === Test 1: TTFB (time to first byte) ===
t0 = time.time()
resp = urllib.request.urlopen(req, timeout=120, context=ctx)
first_byte = time.time()
print(f"HTTP {resp.status}")
print(f"TTFB (first byte): {first_byte - t0:.3f}s")

# === Test 2: Time to first answer token ===
t_first_token = None
buf = b""
answer_len = 0
event_count = 0

try:
    for chunk in iter(lambda: resp.read(4096), b""):
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            evt_bytes, buf = buf.split(b"\n\n", 1)
            event_count += 1
            for line in evt_bytes.split(b"\n"):
                if not line.startswith(b"data:"):
                    continue
                try:
                    evt = json.loads(line[5:])
                except Exception:
                    continue
                t = evt.get("event", "")
                if t in ("message", "agent_message"):
                    ans = evt.get("answer", "")
                    answer_len += len(ans)
                    if t_first_token is None:
                        t_first_token = time.time()

    t_end = time.time()
    print(f"First token: {t_first_token - t0:.3f}s" if t_first_token else "No answer")
    print(f"Total time: {t_end - t0:.3f}s")
    print(f"Events: {event_count} | Answer: {answer_len} chars")
    print(f"Throughput: {answer_len / (t_end - t_first_token):.0f} chars/s" if t_first_token else "")

    # Summary for weekly report
    print(f"\n=== 速度总结 ===")
    print(f"首字节: {(first_byte - t0)*1000:.0f}ms")
    print(f"首token: {(t_first_token - t0)*1000:.0f}ms" if t_first_token else "N/A")
    print(f"总耗时: {(t_end - t0):.1f}s")

except Exception as e:
    print(f"ERROR: {e}")
