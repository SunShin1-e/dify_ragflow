# RAGFlow nginx 下载路由持久化方案

## 背景

wecom-bot 生产版在企微回复中使用 `[文档名](http://host/doc-download/文档ID)` 格式的 Markdown 下载链接。这依赖 RAGFlow 容器内 nginx 的一层代理路由，将 `/doc-download/` 请求自动附加 API Token 后转发到文档下载 API。

如果直接在容器内手动修改 nginx 配置文件，容器重建后会丢失。

## 问题

RAGFlow 容器的启动脚本 `entrypoint.sh` 在每次启动时，会从模板文件重新生成 nginx 配置：

```bash
cp -f /etc/nginx/conf.d/ragflow.conf.python /etc/nginx/conf.d/ragflow.conf
```

无论之前怎么改 `/etc/nginx/conf.d/ragflow.conf`，容器一重启就被模板覆盖。

## 方案

**核心思路**：不阻止覆盖，而是改变覆盖的源文件——让 `cp -f` 的源文件变成宿主机上已包含 doc-download 的版本。

### 步骤

**1. 导出容器内模板到宿主机**

```bash
sudo docker exec ragflow-ragflow-cpu-1 cat /etc/nginx/conf.d/ragflow.conf.python > /opt/ragflow/docker/nginx/ragflow.conf.python
```

**2. 编辑宿主机模板文件**

在 `location ~ ^/(v1|api) {` 前面插入 doc-download 路由：

```nginx
    location ~ ^/doc-download/([^/]+)$ {
        proxy_set_header Authorization "Bearer ragflow-你的API Token";
        rewrite ^/doc-download/(.*)$ /api/v1/documents/$1 break;
        proxy_pass http://localhost:9380;
        proxy_pass_header Content-Disposition;
        include proxy.conf;
    }
```

**3. docker-compose.yml 新增挂载**

在 `ragflow-cpu` 服务的 `volumes` 下新增一行：

```yaml
volumes:
  - ./nginx/ragflow.conf.python:/etc/nginx/conf.d/ragflow.conf.python
```

**4. 重建容器**

```bash
cd /opt/ragflow/docker && sudo docker compose down && sudo docker compose up -d
```

## 原理

```
容器启动流程：
  ① Docker 挂载宿主机文件 → 覆盖容器内 ragflow.conf.python（含 doc-download）
  ② entrypoint.sh 执行 cp -f → 用含 doc-download 的模板覆盖 ragflow.conf
  ③ nginx 启动 → 读取 ragflow.conf → doc-download 路由生效
```

宿主机模板是 cp 的**源**，entrypoint.sh 的覆盖操作自然把 doc-download 写入最终配置。

## 为什么不用其他方式

| 方式 | 问题 |
|------|------|
| 直接改容器内 `ragflow.conf` | 容器重建丢失 |
| 挂载宿主机 `ragflow.conf` | 被 entrypoint.sh 用模板覆盖 |
| 改容器内模板 `ragflow.conf.python` | 容器重建恢复镜像原样 |
| **挂载宿主机模板** | ✅ 模板本身就是源，entrypoint 覆盖操作正好用它 |

## 验证

```bash
# 确认容器内 nginx 配置包含 doc-download
sudo docker exec ragflow-ragflow-cpu-1 grep -A3 "doc-download" /etc/nginx/conf.d/ragflow.conf

# 确认下载可用
curl -sI "http://ragflow.incubecn.com/doc-download/任意文档ID" 
```
