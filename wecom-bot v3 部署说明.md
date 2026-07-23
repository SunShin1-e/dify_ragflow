# wecom-bot v3 部署说明

## 一、v3 与原版插件的区别

原版 wecom-bot 插件从 Dify 市场安装后，通过 Dify 内部 API 调用应用，存在以下问题：

| 问题 | 原因 | v3 解决方案 |
|------|------|------------|
| 企微用户 ID 不被识别 | Dify 内部 API 只认 UUID 格式用户，企微用户是 `zhangsan` 这种字符串 | 改用 Dify 外部 Service API，原生支持非 UUID 用户 |
| 每次部署要改 Dify 源码 | 需要修改 `_get_user` 和 `plugin.py` 两处 | 外部 API 零侵入，不改 Dify |
| 中文回复偶尔乱码 | SSE 流按字符串 chunk 解码，多字节字符被截断 | 改为字节缓冲，完整事件边界才解码 |
| 企微"正在回答"窗口出现慢 | 文本消息直接调 API，阻塞到 LLM 返回才响应 | 文本消息立即返回，API 调用挪到流式轮询 |
| 参考文档无法下载 | 没有下载链接 | 通过 nginx 代理 + Markdown 链接支持点击下载 |
| 反馈点赞无法回传 | API Key 优先级错误 | 修复优先级：设置页 → /fbkey → 自动生成 |
| LLM 调用偶发网络错误 | 无重试 | 3 次重试 + 指数退避 |

---

## 二、具体代码改动

### 2.1 核心替换：内部 API → 外部 Service API

**原版代码：**
```python
# 调 Dify 内部 API —— 需要改 Dify 源码才能支持非 UUID 用户
response_stream = self.session.app.chat.invoke(
    app_id=app.get("app_id"),
    query=content,
    user=user_id,
    inputs={},
    response_mode="streaming",
    conversation_id=conversation_id,
)
```

**v3 代码：**
```python
# 调 Dify 外部 Service API —— 原生支持任意 user 格式
result = self._call_dify_service_api(
    query=content,
    user_id=user_id,
    api_key=api_key,
    conversation_id=conversation_id,
)
```

`_call_dify_service_api` 方法做的事：
1. `POST http://dify-api-1:5001/v1/chat-messages`
2. 手动解析 SSE 流（字节缓冲避免乱码）
3. 提取 `answer`、`conversation_id`、`message_id`、`references`
4. 返回结构化 dict

### 2.2 SSE 解析修复（解决中文乱码）

**原版：** 逐 chunk 解码字符串，UTF-8 多字节字符被 TCP 分包截断后变 `�`

```python
buffer = ""
buffer += chunk.decode("utf-8", errors="replace")  # 半个汉字 → �
```

**v3：** 改为字节缓冲，只在 SSE 事件边界（`\n\n`）解码

```python
buffer = b""
buffer += chunk                    # 累积原始字节
while b"\n\n" in buffer:          # 完整事件才解码
    evt_str = buffer.split(b"\n\n", 1)[0].decode("utf-8")
```

### 2.3 响应加速（企微"正在回答"窗口快速弹出）

**原版：** 收到文本消息 → 调 LLM（阻塞 10-30 秒）→ 返回

**v3：** 收到文本消息 → 存上下文 → **立即返回** `finish=false` → 企微显示"正在回答"→ 流式轮询时调 LLM

新增两个方法：
- `_do_chat()` — 从 `_invoke` 拆出的纯对话逻辑
- `_handle_stream_poll()` — 首次轮询获取锁调 `_do_chat`，后续轮询返回缓存

### 2.4 参考文档下载链接

```python
# 取 document_id，拼 Markdown 链接
link = f"{ragflow_base_url}/doc-download/{doc_id}"
answer += f"{idx}. [{doc_name}]({link})\n"
```

企业微信流式消息支持 Markdown 链接格式 `[文本](URL)`，文档名显示为可点击链接，URL 不暴露。

### 2.5 反馈 API Key 优先级修复

```python
# 原版：自动生成 token 总有值，用户配的 Key 永远用不上
api_key = _make_feedback_token(app_id)    # "app-fb-xxx"
if not api_key:                             # 永远不进
    api_key = settings.get("dify_service_api_key")

# v3：用户配的优先
api_key = (settings.get("dify_service_api_key") or "").strip()
if not api_key:
    api_key = storage.get(f"fbkey_{app_id}")   # /fbkey 命令
if not api_key:
    api_key = _make_feedback_token(app_id)     # 自动生成
```

---

## 三、部署前需要修改的配置

### 3.1 插件代码内（已改好，确认即可）

| 配置项 | 文件位置 | 当前值 | 说明 |
|--------|---------|--------|------|
| `DIFY_API_BASE` | `wecom_message.py` 第 40 行 | `http://dify-api-1:5001` | Dify API 容器名，用 `docker ps \| grep api` 确认 |
| `RAGFLOW_BASE_URL` | `wecom_message.py` 第 42 行 | `http://10.18.11.77:8088` | RAGFlow 外部访问地址（企微用户能访问的） |

### 3.2 插件设置页（在 Dify Web 里配）

| 配置项 | 说明 | 是否必须 |
|--------|------|---------|
| Token | 企微回调 Token | ✅ |
| Encoding AES Key | 企微回调加密 Key | ✅ |
| App | 选择要绑定的 Dify 应用 | ✅ |
| RAGFlow 访问地址 | 用于文档下载链接（设置页缓存可能不显示，代码已硬编码） | 可选 |
| Dify 服务 API 密钥 | 用于调用 Dify API（也可通过 `/fbkey` 命令配置） | 可选 |

> **注意：** `RAGFlow 访问地址` 和 `Dify 服务 API 密钥` 可能因 Dify 插件 schema 缓存问题不显示在设置页。不影响使用 —— API Key 改在企业微信发 `/fbkey app-xxx` 配置，RAGFlow 地址已在代码里硬编码。

---

## 四、部署步骤

### 4.1 传输文件到服务器

文件在 `D:\work\dify_ragflow\wecom_v3.b64`，用 scp 或其他方式传到服务器的 `/tmp/`。

### 4.2 解码并部署

```bash
# 找到 wecom-bot 安装目录
cd /opt/dify/docker/volumes/plugin_daemon/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415/endpoints/

# 解码覆盖
sudo base64 -d /tmp/wecom_v3.b64 > wecom_message.py

# 确认（应该显示注释头）
head -3 wecom_message.py
```

### 4.3 注入 RAGFlow nginx 下载路由

```bash
# 写入注入脚本
sudo docker exec -i ragflow-ragflow-cpu-1 tee /tmp/inject_doc_download.py << 'EOF'
import sys
BLOCK = """    # doc-download proxy for public download
    location ~ ^/doc-download/([^/]+)$ {
        proxy_set_header Authorization "Bearer ragflow-euytj2bGcUvyd60l8bgS2Q1INre0TgAPzhm-bl0xaQQ";
        rewrite ^/doc-download/(.*)$ /api/v1/documents/$1 break;
        proxy_pass http://localhost:9380;
        proxy_pass_header Content-Disposition;
        include proxy.conf;
    }

"""
with open("/etc/nginx/conf.d/ragflow.conf", "r") as f:
    content = f.read()
if "doc-download" in content:
    print("SKIP: already exists")
else:
    content = content.replace(
        "    location ~ ^/(v1|api) {",
        BLOCK + "    location ~ ^/(v1|api) {", 1
    )
    with open("/etc/nginx/conf.d/ragflow.conf", "w") as f:
        f.write(content)
    print("OK")
EOF

# 执行注入
sudo docker exec ragflow-ragflow-cpu-1 python3 /tmp/inject_doc_download.py

# 重载 nginx
sudo docker exec ragflow-ragflow-cpu-1 nginx -s reload
```

### 4.4 验证下载路由

```bash
# 用实际的 document_id 测试（从 RAGFlow 页面获取）
curl -sI "http://10.18.11.77:8088/doc-download/你的文档ID" 2>&1 | head -3
# 应返回 HTTP/1.1 200
```

### 4.5 重启插件并配置 API Key

```bash
# 重启 plugin daemon
sudo docker restart dify-plugin_daemon-1

# 确认启动成功（看到 local runtime ready）
sudo docker logs dify-plugin_daemon-1 --tail 20 | grep "wecom-bot.*ready"
```

### 4.6 配置 API Key

在企业微信机器人对话框发送：
```
/fbkey app-xxxxxxxxxxxx
```

API Key 获取：Dify Web → 对应 App → API 访问 → API 密钥。

---

## 五、验证清单

| 验证项 | 预期结果 |
|--------|---------|
| 企业微信发"你好" | 正常回复，无乱码 |
| 企业微信发需要查知识库的问题 | 回复含参考文档列表，文档名可点击 |
| 点击文档名 | 触发文件下载 |
| 连续发两条消息 | 记住上下文（多轮对话） |
| 发"新对话" | 重置对话 |
| 点赞/点踩回复 | 反馈写入 Dify 日志 |

---

## 六、注意事项

1. **RAGFlow 容器重启后 nginx 下载路由会丢失**——用 `start_all_v2.sh` 启动会自动重新注入
2. **Dify 容器重建后插件文件丢失**——需要重新执行步骤 4.2
3. **API Key 存在插件 storage 中**——容器重建后持久化卷里保留，不用重新配
4. Dify 版本升级后 API 容器名可能变化——确认 `DIFY_API_BASE` 与实际容器名一致

---

## 七、文件清单

| 文件 | 说明 |
|------|------|
| `D:\work\dify_ragflow\wecom_message_v3.py` | v3 插件源码 |
| `D:\work\dify_ragflow\wecom_v3.b64` | base64 编码，用于部署 |
| `D:\work\dify_ragflow\start_all_v2.sh` | 一键启动脚本（含 nginx 注入） |
| `D:\work\dify_ragflow\inject_doc_download.py` | nginx 注入脚本（在 RAGFlow 容器 /tmp 里） |
