# wecom-bot 生产版 改动详解（对比官方原版）

## 概览

| | 官方原版 | 生产版 |
|------|---------|-----|
| 代码行数 | 137 行 | 675 行 |
| API 调用 | `session.app.chat.invoke()` 内部 API | `_call_dify_service_api()` 外部 Service API |
| 用户标识 | 不传 user | 传企微 userid，外部 API 原生支持 |
| 响应模式 | blocking（一次性返回） | streaming（SSE 流式解析） |
| 多轮对话 | ❌ | conversation_id 持久化 |
| 用户反馈 | ❌ | 点赞/点踩回传 Dify |
| 参考文档 | ❌ | 文档名 + 可点击下载链接 |
| 错误重试 | ❌ | 3 次重试 + 指数退避 |
| think 过滤 | ❌ | 正则去除 `<think>` 块 |
| 引用标记清洗 | ❌ | 去除 `[1]`、`[2.1]` 等标记 |
| App 隔离 | ❌ | 所有存储 key 按 app_id 隔离 |
| 响应速度 | 文本消息阻塞 10-30s | 文本消息毫秒级返回 |
| 命令支持 | ❌ | /fbkey、/new、/reset |
| 中文乱码 | 无（blocking 不走 SSE） | 字节缓冲修复 SSE 截断 |
| Dify 源码改动 | 需要（_get_user + plugin.py） | 零侵入 |

---

## 改动 1：核心——对话调用从内部 API 切换到外部 Service API

### 原版代码（137 行文件，不含 user 参数）

```python
try:
    app = settings.get("app")
    response = self.session.app.chat.invoke(
        app_id=app.get("app_id"),
        query=content,
        inputs={},
        response_mode="blocking",
    )
    answer = response.get("answer") or json.dumps(response, ensure_ascii=False)
except Exception as exc:
    answer = f"Errors：{exc}"
```

**原版问题**：
- 走 Dify 内部 API（`/inner/api/invoke/app`），需要改 Dify 源码才能支持非 UUID 用户
- `response_mode="blocking"` — Agent Chat App 不支持，会报 400
- 没有 `user` 参数 — 所有请求都以 plugin daemon 身份执行，无法区分用户

### 生产版 代码（新增 `_call_dify_service_api` 方法，~100 行）

```python
result = self._call_dify_service_api(
    query=content,
    user_id=user_id,          # ← 传入企微用户 ID
    api_key=api_key,
    conversation_id=conversation_id,
)
```

`_call_dify_service_api` 方法：
1. POST `http://dify-api-1:5001/v1/chat-messages`（外部 Service API）
2. 带 API Key 认证头
3. 手动解析 SSE 流（字节缓冲）
4. 提取 answer、conversation_id、message_id、references
5. 返回结构化 dict

---

## 改动 2：增加用户标识透传

### 原版

```python
response = self.session.app.chat.invoke(
    app_id=app.get("app_id"),
    query=content,
    inputs={},
    # 没有 user 参数
)
```

### 生产版

```python
user_id = payload.get("from", {}).get("userid", "wecom-user")
# ...
result = self._call_dify_service_api(
    query=content,
    user_id=user_id,    # ← 传入用户标识
    # ...
)
```

外部 Service API 通过 `EndUserService.get_or_create_end_user()` 原生支持任意格式 user，不需要改 Dify 源码。

---

## 改动 3：blocking → streaming + SSE 解析

### 原版

```python
response_mode="blocking"
answer = response.get("answer")  # 一次拿到完整结果
```

### 生产版

```python
response_mode="streaming"
# 手动解析 SSE 流，逐 token 拼接
for event in response_stream:
    if event.get("event") in ("message", "agent_message"):
        answer += event.get("answer", "")
```

**为什么改**：Dify 的 Agent Chat App 不支持 blocking 模式，调用会返回 400。

---

## 改动 4：SSE 中文乱码修复

### 原版

无此问题（blocking 模式下完整返回 JSON，不存在 TCP 分包截断）。

### 生产版

```python
# 字节缓冲，只在完整 SSE 事件边界解码
buffer = b""
buffer += chunk
while b"\n\n" in buffer:
    evt_str = buffer.split(b"\n\n", 1)[0].decode("utf-8")
```

SSE 分隔符 `\n\n` 是 ASCII（0x0a），不会出现在 UTF-8 多字节序列内部，按此边界解码永远是完整文本。

---

## 改动 5：响应加速

### 原版

```python
# _invoke 收到文本消息 → 直接调 API → 阻塞 10-30s → 返回
response = self.session.app.chat.invoke(...)
```

企微 10-30 秒内收不到任何响应，用户看不到"正在回答"状态。

### 生产版

拆分为两个阶段：

**文本消息处理** — 存上下文 + 立即返回：
```python
ctx = json.dumps({"user_id": user_id, "content": content})
self.session.storage.set(f"wemctx_{app}_{msgid}", ctx.encode())
self.session.storage.set(f"wemsg_{app}_{msgid}", b"processing")
# 立即返回 finish=false → 企微显示"正在回答"
```

**流式轮询处理** `_handle_stream_poll()` — 首次轮询时执行 `_do_chat()`：
```python
if not self.session.storage.exist(lock_key):
    self.session.storage.set(lock_key, b"running")
    answer = self._do_chat(...)
```

效果：文本消息毫秒级响应，"正在回答"窗口立刻出现。

---

## 改动 6：增加用户反馈回传

### 原版

无反馈功能。

### 生产版

新增 `_handle_feedback_event()` 方法（~70 行），处理企微 `feedback_event` 回调：
- 映射企微反馈类型（1=like, 2=dislike, 3=cancel）到 Dify rating
- 查询 `fb_{app}_{msgid}` 映射找到对应的 Dify message_id
- 调 Dify Service API `POST /v1/messages/{id}/feedbacks` 回传反馈

---

## 改动 7：增加参考文档 + 下载链接

### 原版

无参考文档功能。

### 生产版

从 `message_end` 事件的 `retriever_resources` 提取文档信息：

```python
references.append({
    "name": ref_doc,
    "file_path": doc_metadata.get("file_path", ""),
    "document_id": res.get("document_id", ""),
})
```

展示时拼 Markdown 下载链接（企微支持）：

```python
link = f"{ragflow_base_url}/doc-download/{doc_id}"
answer += f'{idx}. [{doc_name}]({link})\n'
```

---

## 改动 8：增加多轮对话

### 原版

每次请求独立，无上下文记忆。

### 生产版

```python
# 加载已有会话
conversation_id = storage.get(f"conv_{app}_{user}")

# 调用 API 时传入
result = self._call_dify_service_api(..., conversation_id=conversation_id)

# 保存新会话 ID
storage.set(f"conv_{app}_{user}", new_conversation_id)
```

支持手动重置：`/new`、`/reset`、`新对话`、`重置对话`。

---

## 改动 9：增加错误重试

### 原版

```python
except Exception as exc:
    answer = f"Errors：{exc}"
```

### 生产版

```python
for attempt in range(MAX_RETRIES):  # 3 次
    try:
        result = self._call_dify_service_api(...)
        break
    except Exception as exc:
        if is_network_error(exc) and attempt < MAX_RETRIES - 1:
            time.sleep(2 * (attempt + 1))  # 2s → 4s → 6s
            continue
```

区分网络错误（可重试）和业务错误（不重试）。

---

## 改动 10：增加 App 隔离

### 原版

```python
# 所有 app 共用同一个存储 key
storage.set(f"wecom_msg_{message_id}", ...)
```

### 生产版

```python
raw_app_id = settings.get("app", {}).get("app_id", "") or "noapp"
# 所有 key 按 app 隔离
storage.set(f"wemsg_{raw_app_id}_{message_id}", ...)
storage.set(f"conv_{raw_app_id}_{user_id}", ...)
```

同一插件多次安装（绑不同 App）互不影响。

---

## 改动 11：增加 /fbkey 和 /new 命令

### 原版

无命令支持。

### 生产版

- `/fbkey app-xxx`：运行时配置 API Key
- `/new` / `/reset` / `新对话`：重置当前对话

---

## 改动 12：硬编码服务器配置

由于 Dify 插件 schema 缓存问题，设置页部分字段可能不显示，因此在代码中硬编码默认值：

```python
DIFY_API_BASE = "http://dify-api-1:5001"       # 第 40 行
RAGFLOW_BASE_URL = "http://ragflow.incubecn.com" # 第 42 行
```

---

## 不需要 Dify 源码改动了

这是 生产版 最重要的变化。原版使用内部 API 导致必须修改 Dify 的两处源码：

| Dify 源码文件 | 原版需要的改动 | 生产版 是否需要 |
|-------------|-------------|-----------|
| `app.py` 的 `_get_user` | 增加 session_id 匹配 + 自动创建 EndUser | ❌ 不需要 |
| `plugin.py` 的 `user_id` | 改为 `payload.user or user_model.id` | ❌ 不需要 |

因为外部 Service API 原生支持任意格式的 user 参数。
