# Dify + RAGFlow + wecom-bot 从 0 到 1 部署指南（外接数据库版）

## 一、架构概览

```
┌─────────────────────────────────────────────────────┐
│                    服务器（Docker）                    │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  Dify     │  │ RAGFlow  │  │ wecom-bot v3     │  │
│  │  (容器)   │  │ (容器)    │  │ (插件，Dify 内)  │  │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │
│       │              │                 │             │
└───────┼──────────────┼─────────────────┼─────────────┘
        │              │                 │
   ┌────┴────┐   ┌─────┴──────┐         │
   │PostgreSQL│   │   MySQL    │         │
   └─────────┘   └────────────┘         │
   ┌────────┐    ┌──────────┐           │
   │ Redis  │    │  MinIO   │           │
   │(共享)  │    └──────────┘           │
   └────────┘    ┌──────────┐           │
                 │Infinity  │           │
                 │或 ES     │           │
                 └──────────┘           │
                                        │
                              ┌─────────┴─────────┐
                              │   企业微信服务器     │
                              └───────────────────┘
```

**全部数据库使用外部实例**，Docker 容器只跑应用，不跑数据库。容器销毁/重建不影响数据。

---

## 二、前置准备

### 2.1 外部数据库清单

| 数据库 | 用途 | 端口 |
|--------|------|------|
| MySQL 8.0+ | RAGFlow 主库（知识库、用户、文档元数据） | 3306 |
| Redis 6+ | Dify 缓存/队列 + RAGFlow 缓存 | 6379 |
| PostgreSQL 15+ | Dify 主库（应用、用户、对话记录） | 5432 |
| MinIO | RAGFlow 文件存储（文档原始文件） | 9000 |
| Infinity 或 ES 8+ | RAGFlow 搜索引擎（切片和元数据索引） | 23817 / 9200 |

### 2.2 创建数据库和用户

**MySQL（RAGFlow 用）**：
```sql
CREATE DATABASE rag_flow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ragflow'@'%' IDENTIFIED BY '你的密码';
GRANT ALL PRIVILEGES ON rag_flow.* TO 'ragflow'@'%';
FLUSH PRIVILEGES;
```

**PostgreSQL（Dify 用）**：
```sql
CREATE USER dify WITH PASSWORD '你的密码';
CREATE DATABASE dify OWNER dify;
GRANT ALL PRIVILEGES ON DATABASE dify TO dify;
```

**Redis**：确保端口 6379 可从 Docker 网络访问，设置密码或不设（内网使用）。

**MinIO**：创建 bucket（如 `ragflow`），记下 Access Key 和 Secret Key。

---

## 三、RAGFlow 部署

### 3.1 目录结构

```bash
mkdir -p /opt/ragflow/docker/nginx
```

### 3.2 docker-compose.yml（精简版，无内置数据库）

```yaml
services:
  ragflow-cpu:
    image: infiniflow/ragflow:v0.26.4
    profiles:
      - cpu
    command:
      - --enable-adminserver
      - --init-model-provider-tables
    ports:
      - "8088:80"      # Web 界面
      - "9380:9380"    # HTTP API
      - "9381:9381"    # Admin API
    volumes:
      - ./ragflow-logs:/ragflow/logs
      - ./service_conf.yaml.template:/ragflow/conf/service_conf.yaml.template
      - ./entrypoint.sh:/ragflow/entrypoint.sh
      - ./nginx/ragflow.conf.python:/etc/nginx/conf.d/ragflow.conf.python
    environment:
      - MYSQL_HOST=你的MySQL地址
      - MYSQL_PORT=3306
      - MYSQL_USER=ragflow
      - MYSQL_PASSWORD=你的MySQL密码
      - MYSQL_DBNAME=rag_flow
      - REDIS_HOST=你的Redis地址
      - REDIS_PORT=6379
      - REDIS_PASSWORD=你的Redis密码（可选）
      - MINIO_HOST=你的MinIO地址
      - MINIO_PORT=9000
      - MINIO_USER=你的MinIO_AccessKey
      - MINIO_PASSWORD=你的MinIO_SecretKey
      - INFINITY_HOST=你的Infinity地址  # 如果用外部 Infinity
    networks:
      - ragflow
    restart: unless-stopped

networks:
  ragflow:
    external: true
```

### 3.3 nginx 下载路由

**目标**：让 `/doc-download/{id}` 可公开下载文档，自动附加 API Token。

1. 从容器导出模板：
```bash
docker run --rm infiniflow/ragflow:v0.26.4 cat /etc/nginx/conf.d/ragflow.conf.python > /opt/ragflow/docker/nginx/ragflow.conf.python
```

2. 编辑 `/opt/ragflow/docker/nginx/ragflow.conf.python`，在 `location ~ ^/(v1|api) {` 前面插入：
```nginx
    location ~ ^/doc-download/([^/]+)$ {
        proxy_set_header Authorization "Bearer ragflow-你的API Token";
        rewrite ^/doc-download/(.*)$ /api/v1/documents/$1 break;
        proxy_pass http://localhost:9380;
        proxy_pass_header Content-Disposition;
        include proxy.conf;
    }
```

3. 启动：
```bash
cd /opt/ragflow/docker && docker compose --profile cpu up -d
```

4. 验证：
```bash
curl -sI "http://服务器IP:8088/doc-download/任意文档ID" | head -3
```

---

## 四、Dify 部署

### 4.1 准备 .env 文件

在 Dify 的 `.env` 中配置外部数据库：

```bash
# PostgreSQL（外部）
DB_USERNAME=dify
DB_PASSWORD=你的PostgreSQL密码
DB_HOST=你的PostgreSQL地址
DB_PORT=5432
DB_DATABASE=dify

# Redis（外部，与 RAGFlow 共享）
REDIS_HOST=你的Redis地址
REDIS_PORT=6379
REDIS_PASSWORD=你的Redis密码（可选）
```

### 4.2 启动 Dify

```bash
cd /opt/dify/docker && docker compose up -d
```

确认服务正常：
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep dify
```

---

## 五、wecom-bot v3 插件部署

### 5.1 安装插件

在 Dify Web 市场安装 wecom-bot 插件，配置三个必须项：

| 配置 | 说明 |
|------|------|
| Token | 企业微信回调 Token |
| Encoding AES Key | 企业微信回调加密 Key |
| App | 要绑定的 Dify 应用 |

### 5.2 生成适配新服务器的 v3 代码

1. 确认 Dify API 容器名：
```bash
docker ps --format "{{.Names}}" | grep api
# 例如：dify-api-1
```

2. 编辑 `wecom_message.py` 第 40、42 行：
```python
DIFY_API_BASE = "http://dify-api-1:5001"       # 改为实际容器名
RAGFLOW_BASE_URL = "http://服务器IP:8088"        # RAGFlow 外部地址
```

3. 生成 base64：
```bash
base64 -w0 wecom_message.py > wecom_v3.b64
```

### 5.3 部署

```bash
# 找到插件实际目录
PLUGIN_DIR=$(find /opt/dify/docker/volumes/plugin_daemon/ -name "wecom_message.py" -path "*/wecom-bot*" | head -1 | xargs dirname)

cd "$PLUGIN_DIR"
sudo base64 -d /tmp/wecom_v3.b64 > wecom_message.py
sudo docker restart dify-plugin_daemon-1

# 确认启动成功
sudo docker logs dify-plugin_daemon-1 --tail 20 | grep "wecom-bot.*ready"
```

### 5.4 配置 API Key

在企微机器人对话框发送：
```
/fbkey app-你的API密钥
```

---

## 六、网络互通

```bash
# RAGFlow 加入 Dify 网络
docker network connect dify_default ragflow-ragflow-cpu-1

# 如果 Redis 也在 Docker 里，确保别名正确
docker network connect --alias redis dify_default 你的Redis容器名
```

---

## 七、Dify 配置 RAGFlow 外部知识库

1. Dify Web → 知识库 → 外部知识库 → 添加
2. API 地址：`http://ragflow-ragflow-cpu-1:80/api/v1/dify`
3. API Key：RAGFlow 的 API Token

---

## 八、企业微信回调配置

1. 企业微信管理后台 → 应用管理 → 自建应用/智能机器人
2. 回调 URL 指向 Dify plugin daemon：
   ```
   http://你的服务器IP:5003/e/你的插件标识/
   ```
3. Token 和 Encoding AES Key 与插件设置页一致

---

## 九、验证清单

| 验证项 | 方法 | 预期 |
|--------|------|------|
| Dify 正常运行 | 访问 `http://IP:3000` | 登录页 |
| RAGFlow 正常运行 | 访问 `http://IP:8088` | 登录页 |
| 外部数据库连接 | Dify/RAGFlow 日志无 connection refused | — |
| 企微消息收发 | 发"你好" | 正常回复 |
| 知识库检索 | 发"请假流程" | 回复含参考文档 |
| 文档下载 | 点参考文档名 | 浏览器下载文件 |
| 多轮对话 | 连续发两条消息 | 记住上下文 |
| 对话重置 | 发"新对话" | 回复"对话已重置" |
| RAGFlow 重启 | `docker restart ragflow-ragflow-cpu-1` | 下载路由不丢失 |

---

## 十、外接数据库的好处

| | 内置数据库 | 外接数据库 |
|------|-----------|-----------|
| 容器重建 | 数据可能丢失 | 不受影响 |
| 备份 | 需进容器操作 | 用数据库自带工具 |
| 高可用 | 容器级 | 数据库自带主从/集群 |
| 资源利用 | 与业务容器抢内存 | 独立服务器 |
| 运维 | 分散在各容器 | 统一管理 |
