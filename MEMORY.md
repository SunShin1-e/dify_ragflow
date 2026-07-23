# Dify + RAGFlow 集成项目

## 架构
- **本地开发**：Dify 和 RAGFlow 在 WSL Ubuntu Docker 中运行，容器名前缀 `docker-`
- **服务器生产**：Dify（容器名前缀 `dify-`）和 RAGFlow（`ragflow-ragflow-cpu-1`）部署在 Ubuntu 服务器
- Dify Web: `http://10.18.11.77:3000`（本地）/ `http://ragflow.incubecn.com:3000`（生产）
- RAGFlow Web: `http://10.18.11.77:8088`（本地）/ `http://ragflow.incubecn.com`（生产）
- 公网入口 `58.251.17.234` 反向代理到内网 RAGFlow

## RAGFlow 知识库
- 名称: 制度知识库，ID: `1b0585b07cf311f195d99158db8cae63`
- 租户ID: `fa9051b87cf011f195d99158db8cae63`
- API Key: `ragflow-KnPefRsc2ssn-4gpIR6IG9ehnv4izDerTnoiZ1NzByw`（生产）/ `ragflow-euytj2bGcUvyd60l8bgS2Q1INre0TgAPzhm-bl0xaQQ`（本地）
- 嵌入模型: `text-embedding-v3@Tongyi-Qianwen`
- 搜索模型: `deepseek-v4-flash@DeepSeek`

## Dify 配置
- 外部知识库 API: `http://ragflow-ragflow-cpu-1:80/api/v1/dify`（生产）/ `http://docker-ragflow-cpu-1:80/api/v1/dify`（本地）
- API 容器名: `dify-api-1`（生产）/ `docker-api-1`（本地）
- Plugin Daemon: `dify-plugin_daemon-1`（生产）/ `docker-plugin_daemon-1`（本地）

## wecom-bot 生产版（已上线，2026-07-23）

### 核心变化（对比官方原版 137 行）
- **API 调用**：从内部 API（`session.app.chat.invoke`）切换到外部 Service API（`/v1/chat-messages`），Dify 源码零侵入
- **用户标识**：传入企微 userid，外部 API 原生支持非 UUID 用户
- **响应模式**：blocking → streaming，手动解析 SSE 流
- **SSE 解析**：字节缓冲避免中文乱码
- **响应加速**：文本消息毫秒级返回，API 调用挪到流式轮询
- **多轮对话**：conversation_id 持久化到 Redis storage
- **用户反馈**：支持企微 feedback_event 回传 Dify
- **参考文档**：提取 retriever_resources 并生成 Markdown 下载链接
- **错误重试**：3 次重试 + 指数退避，区分网络/业务错误
- **App 隔离**：所有 storage key 按 `raw_app_id` 隔离
- **命令支持**：`/fbkey`（配置 API Key）、`/new`、`/reset`（重置对话）

### 硬编码配置
- `DIFY_API_BASE = "http://dify-api-1:5001"`（生产第 40 行）
- `RAGFLOW_BASE_URL = "http://ragflow.incubecn.com"`（生产第 42 行）
- API Key 通过企微发 `/fbkey app-xxx` 配置

### 部署路径
- 插件文件：`/opt/dify/docker/volumes/plugin_daemon/cwd/langgenius/wecom-bot-0.0.6@.../endpoints/wecom_message.py`
- 部署后重启：`sudo docker restart dify-plugin_daemon-1`

### 文档位置
- 源码：`D:\work\dify_ragflow\wecom_message_v3.py`
- base64 传输文件：`D:\work\dify_ragflow\wecom_v3.b64`
- 改动详解：`D:\work\dify_ragflow\wecom-bot 生产版改动详解.md`

## RAGFlow nginx doc-download 持久化（2026-07-21）

### 问题
容器每次启动 `entrypoint.sh` 从模板 `ragflow.conf.python` 执行 `cp -f` 覆盖 `ragflow.conf`。

### 方案
挂载宿主机模板文件，doc-download 写在宿主机上，`cp -f` 的源就是含路由的版本：
1. 宿主机 `/opt/ragflow/docker/nginx/ragflow.conf.python` 中插入 doc-download 路由
2. `docker-compose.yml` 新增挂载 `./nginx/ragflow.conf.python:/etc/nginx/conf.d/ragflow.conf.python`
3. 容器重建后自动生效

### 文档
- 方案说明：`D:\work\dify_ragflow\RAGFlow nginx 下载路由持久化方案.md`

## 公网下载链路
`用户 → ragflow.incubecn.com → 58.251.17.234（反向代理）→ 10.18.11.77:8088 → RAGFlow nginx doc-download 路由 → 文档下载`

## 已知问题和解决

1. **Infinity 5432 端口暴露**：外部安全扫描器用非 PG 协议连 5432 导致 Infinity 假死 → RAGFlow 卡住。修复：`docker-compose-base.yml` 中改为 `127.0.0.1:5432:5432`（待部署）
2. **Dify API 连接数偏低**：`SERVER_WORKER_CONNECTIONS=10` → 建议调为 50（待部署）
3. **Dify Schema 缓存**：插件设置页新增字段不显示，通过硬编码 + `/fbkey` 兜底
4. **NAT 回流**：服务器 curl 公网域名 302，因为内网走公网再回来被拦，不影响外部用户
5. **RAGFlow 元数据编辑卡死**：Infinity 假死导致整个服务卡住，重启 Infinity 恢复

## 相关仓库
- GitLab：`git@gitlab.incubecn.com:it-ai-instance/in3.knowledgebase.git`（dev 分支）
- 本地代码：`D:\work\dify_ragflow\`
- 知识库源码：`D:\work\06.源码仓库\in3.knowledgebase\`

## 服务器重启后需要执行
```bash
# RAGFlow ↔ Dify 网络互通
docker network connect dify_default ragflow-ragflow-cpu-1
# 验证 RAGFlow 就绪
docker logs ragflow-ragflow-cpu-1 | grep "RAGFlow server is ready"
```
