# wecom-bot v3 改动详解

## 概述

在原版 wecom-bot 插件基础上做了 7 处改动，核心目标是**将对话调用从 Dify 内部 API 切换到外部 Service API**，从而实现 Dify 源码零侵入部署，并修复编码、响应速度、反馈等多个问题。

---

## 改动 1：核心——对话调用从内部 API 切换到外部 Service API

### 为什么要改

原版插件通过 `self.session.app.chat.invoke()` 调用 Dify **内部 API**（`/inner/api/invoke/app`）。内部 API 的 `_get_user` 方法只认 UUID 格式的用户 ID，企业微信用户 ID（如 `zhangsan`、`IN3021`）不是 UUID，会导致 `user not found` 错误。之前需要在 Dify 源码中修改 `_get_user` 和 `plugin.py` 两处才能支持。

外部 Service API（`/v1/chat-messages`）原生通过 `EndUserService.get_or_create_end_user()` 处理用户，天然支持任意格式的 user 参数，不需要改 Dify 源码。

### 具体怎么改

**删除的代码**：
```python
response_stream = self.session.app.chat.invoke(
    app_id=app.get("app_id"),
    query=content,
    user=user_id,
    inputs={},
    response_mode="streaming",
    conversation_id=conversation_id,
)
```

**替换为**：新增 `_call_dify_service_api()` 方法（约 100 行），通过 `urllib.request` 发送 HTTP POST 请求到 `http://dify-api-1:5001/v1/chat-messages`，手动解析 SSE 流。调用处改为：
```python
result = self._call_dify_service_api(
    query=content,
    user_id=user_id,
    api_key=api_key,
    conversation_id=conversation_id,
)
```

### 新增的 `_call_dify_service_api` 方法做了什么

1. 拼请求体 `{"inputs": {}, "query": "...", "response_mode": "streaming", "user": "...", "conversation_id": "..."}`
2. 带 API Key 认证头发送 HTTP POST
3. 解析 SSE 响应流，提取三类事件：
   - `message` / `agent_message` → 拼接 answer
   - `message_end` → 提取 reference 文档列表（含文档名、file_path、document_id）
   - `error` → 返回错误信息
4. 返回结构化 dict：`{ok, answer, conversation_id, message_id, references}`

---

## 改动 2：SSE 解析修复（中文乱码）

### 为什么要改

原版及早期 v3 版本中，SSE 流按 `chunk.decode("utf-8", errors="replace")` 解析，当 TCP 分包把一个多字节 UTF-8 中文切到两个 chunk 时，`decode` 会把残缺字节替换成 `�`（�）。

### 具体怎么改

**改前**：
```python
buffer = ""
for chunk in iter(lambda: resp.read(1024), b""):
    buffer += chunk.decode("utf-8", errors="replace")  # 半个汉字 → �
    while "\n\n" in buffer:
        evt_str, buffer = buffer.split("\n\n", 1)
```

**改后**：改为**字节级缓冲**，只在遇到完整 SSE 事件分隔符（`\n\n`）后才解码：
```python
buffer = b""
for chunk in iter(lambda: resp.read(1024), b""):
    buffer += chunk              # 累积原始字节
    while b"\n\n" in buffer:     # 只在事件边界解码
        evt_bytes, buffer = buffer.split(b"\n\n", 1)
        evt_str = evt_bytes.decode("utf-8")
```

### 为什么安全

SSE 分隔符 `\n\n` 是 ASCII 字节（0x0a 0x0a），不会出现在 UTF-8 多字节序列内部，按此边界解码的永远是完整 UTF-8 文本。

---

## 改动 3：响应加速（企微"正在回答"窗口快速弹出）

### 为什么要改

原版流程：用户发消息 → 插件收到 → 调 LLM（阻塞 10-30 秒）→ 返回结果。企微在 10-30 秒内收不到任何响应，用户看不到"正在回答"状态，体验差。

### 具体怎么改

重新拆分了消息处理流程，新增两个方法：

**`_invoke()` 中的文本消息处理**——不再调 API，仅存储上下文并**立即返回**：
```python
# 存储上下文供后续流式轮询使用
ctx = json.dumps({"user_id": user_id, "content": content})
self.session.storage.set(f"wemctx_{app}_{msgid}", ctx.encode())
self.session.storage.set(f"wemsg_{app}_{msgid}", b"processing")
# 立即返回 finish=false → 企微显示"正在回答"
res = self._build_wecom_res(msgid, "", finish=False, ...)
return Response(200, response=res)
```

**新增 `_handle_stream_poll()`**——流式轮询时才真正调 LLM：
1. 检查存储中是否有缓存答案 → 有则直接返回
2. 如果是首次轮询（状态为 `"processing"`）→ 获取分布式锁 → 调 `_do_chat()` → 存答案
3. 还在处理中 → 返回空，企微继续轮询

**新增 `_do_chat()`**——从 `_invoke` 拆出的纯对话逻辑，包含：/fbkey 命令处理、重置对话、调用 LLM、引用处理、错误重试。

### 效果

```
改前：用户消息 → 等 10-30s → 看到回复
改后：用户消息 → 立刻看到"正在回答" → 等待 LLM 完成 → 看到回复
```

---

## 改动 4：反馈 API Key 优先级修复

### 为什么要改

原版代码中，反馈 API Key 的取值优先级为：
```python
api_key = _make_feedback_token(app_id)  # 总是有值（"app-fb-xxx"）
if not api_key:                            # 永远不进
    api_key = settings.get("dify_service_api_key")
```
`_make_feedback_token()` 总是返回非空字符串，导致用户配置的 `dify_service_api_key` 永远不被使用，反馈回传失败（401）。

### 具体怎么改

调整优先级，用户配置的优先于自动生成的：
```python
api_key = (settings.get("dify_service_api_key") or "").strip()  # 先取用户配置
if not api_key:
    api_key = storage.get(f"fbkey_{app_id}")         # 再取 /fbkey 命令
if not api_key:
    api_key = _make_feedback_token(app_id)            # 最后自动生成
```

---

## 改动 5：参考文档增加下载链接

### 为什么要改

原版只列出文档名，用户想查看原文需要在 RAGFlow 里搜索。我们利用企微流式消息支持 Markdown 链接的特性，将文档名变为可点击的下载链接。

### 具体怎么改

1. 从 Dify Service API 返回的 `retriever_resources` 中提取 `document_id`
2. 拼 Markdown 格式链接：`[文档名](http://ragflow地址/doc-download/文档ID)`
3. 企业微信渲染为可点击文本，URL 不暴露给用户

```python
# 拼 Markdown 链接
link = f"{ragflow_base_url}/doc-download/{doc_id}"
answer += f'{idx}. [{doc_name}]({link})\n'
```

---

## 改动 6：硬编码服务器相关配置

### DIFY_API_BASE
```python
# 第 40 行，改为实际 API 容器名
DIFY_API_BASE = "http://dify-api-1:5001"
```

### RAGFLOW_BASE_URL（选择硬编码的原因）
插件设置页的 `RAGFlow 访问地址` 字段因 Dify 的 schema 缓存问题不显示，无法通过 UI 配置。因此硬编码默认值：
```python
RAGFLOW_BASE_URL = "http://10.18.11.77:8088"
```
同时在 `_handle_stream_poll` 中保留从 settings 读取的逻辑，优先级：设置页 → 硬编码默认。

---

## 改动 7：并发处理的优化

v3 将文本消息的 API 调用后移到流式轮询阶段，每个消息的处理生命周期变为：

```
文本消息（毫秒级） → 存储上下文 → 立即响应
流式轮询（首次） → 获取处理锁 → 调 LLM（10-30s） → 存结果
流式轮询（后续） → 返回缓存结果
```

处理锁机制（`weml_` key）确保同一消息不会被多个流式轮询并发处理。

---

## 总结对比

| | 原版 | 修改版 |
|------|------|------|
| API 调用方式 | 内部 API（`session.app.chat.invoke`） | 外部 Service API（HTTP SSE） |
| 非 UUID 用户 | 需改 Dify 源码 `_get_user` + `plugin.py` | 原生支持，零改动 |
| 中文乱码 | 可能 | 字节缓冲修复 |
| 企微响应速度 | 10-30 秒后才显示"正在回答" | 毫秒级显示 |
| 参考文档 | 纯文本文件名 | 可点击 Markdown 下载链接 |
| 反馈回传 | API Key 优先级错误导致 401 | 已修复 |
| Dify 升级/迁移 | 需重新改源码 | 不受影响 |
