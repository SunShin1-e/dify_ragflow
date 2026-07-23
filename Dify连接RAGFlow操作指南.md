# Dify 连接 RAGFlow 外部知识库 — 服务器管理员操作指南

## 前置条件

- Dify 和 RAGFlow 部署在同一台服务器上
- 都是用 Docker Compose 启动的
- Dify 的部署目录是 `~/dify/docker/`（不是的话下面所有路径对应改）

---

## 一、打通 Docker 网络

```bash
# 1. 查看 Dify 的网络名
docker network ls | grep dify
# 输出类似: docker_default   bridge   local
#            ^^^^^^^^^^^^ 这个就是 Dify 的网络名

# 2. 查看 RAGFlow 的容器名
docker ps --format "{{.Names}}" | grep ragflow
# 输出类似: ragflow-server
#            ^^^^^^^^^^^^^^ 这个就是 RAGFlow 的容器名

# 3. 把 RAGFlow 加入 Dify 的网络（把下面尖括号里的内容换成上面查到的实际名字）
docker network connect <Dify网络名> <RAGFlow容器名>

# 示例（假设 Dify 网络是 docker_default，RAGFlow 容器是 ragflow-server）：
docker network connect docker_default ragflow-server
```

---

## 二、确认 RAGFlow API 端口

```bash
docker ps --format "{{.Names}}\t{{.Ports}}" | grep ragflow
# 输出类似: ragflow-server   0.0.0.0:80->80/tcp, 0.0.0.0:9380->9380/tcp
#                                                                 ^^^^ 这个就是 API 端口
```

> 如果没看到 `9380`，记下实际的 API 端口号（通常就是 9380 或 80）。

---

## 三、测试 RAGFlow 的 Dify 端点

```bash
curl -s http://localhost:9380/api/v1/dify/retrieval \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"knowledge_id":"test","query":"test"}'
```

> 预期返回 `{"code":401,...}` 或 `{"code":404,...}`。
> 只要不是 `Connection refused` 就说明端点存在且可达。
> 如果端口不是 9380，替换成第二步查到的实际端口。

---

## 四、修改 Dify 配置文件

> Dify 部署目录假设是 `~/dify/docker/`，不是的话改成实际路径。

### 4.1 编辑 `~/dify/docker/.env`

在文件末尾添加一行：

```
SSRF_PROXY_ALLOW_PRIVATE_IPS=172.16.0.0/12
```

命令操作：

```bash
echo "SSRF_PROXY_ALLOW_PRIVATE_IPS=172.16.0.0/12" >> ~/dify/docker/.env
```

### 4.2 编辑 `~/dify/docker/envs/core-services/api.env`

在文件末尾添加两行：

```
PLUGIN_DAEMON_URL=http://plugin_daemon:5002
PLUGIN_DAEMON_KEY=<从 plugin-daemon.env 里复制>
```

命令操作：

```bash
# 先看一下 plugin-daemon.env 里的 KEY 值
grep PLUGIN_DAEMON_KEY ~/dify/docker/envs/core-services/plugin-daemon.env

# 把输出里的 KEY 值复制下来，然后执行（把 <KEY> 替换成实际值）：
cat >> ~/dify/docker/envs/core-services/api.env << 'EOF'
PLUGIN_DAEMON_URL=http://plugin_daemon:5002
PLUGIN_DAEMON_KEY=<KEY>
EOF
```

### 4.3 编辑 `~/dify/docker/envs/core-services/worker.env`

同样在末尾添加相同的两行：

```bash
cat >> ~/dify/docker/envs/core-services/worker.env << 'EOF'
PLUGIN_DAEMON_URL=http://plugin_daemon:5002
PLUGIN_DAEMON_KEY=<KEY>
EOF
```

### 4.4 重建 Dify 容器使配置生效

```bash
cd ~/dify/docker && docker compose up -d --force-recreate
```

等待容器全部启动（约 1-2 分钟）。

---

## 五、提供以下信息给我

全部操作完成后，把下面四个信息发给我：

| 序号 | 信息 | 获取方式 |
|------|------|----------|
| 1 | RAGFlow 容器名 | `docker ps --format "{{.Names}}" \| grep ragflow` |
| 2 | RAGFlow API 端口 | `docker ps \| grep ragflow` 里 `9380` 那一段 |
| 3 | RAGFlow API Key | RAGFlow Web 界面 → 右上角头像 → API → 创建密钥 |
| 4 | RAGFlow 知识库 ID | 进入知识库页面，浏览器地址栏 `id=` 后面的值 |

---

## 六、我在 Dify 界面操作

拿到上面四个信息后，我登录 Dify：

1. **知识库 → 外部知识库 API → 添加**

   | 字段 | 值 |
   |------|-----|
   | 名称 | RAGFlow |
   | API Endpoint | `http://<容器名>:80/api/v1/dify` |
   | API Key | `ragflow-xxxxx`（不加 Bearer 前缀） |

2. **知识库 → 连接外部知识库**

   | 字段 | 值 |
   |------|-----|
   | 外部知识库 API | 选 RAGFlow |
   | 外部知识库 ID | RAGFlow 知识库 ID |
   | Top K | 3 |
   | Score 阈值 | 0.5 |

完成。之后 RAGFlow 里更新文档，Dify 即时生效，不需要同步。
