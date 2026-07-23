# RAGFlow nginx 下载路由配置说明

## 背景

企业微信机器人在回复中附带参考文档列表，用户点击文档名需要能直接下载原文。RAGFlow 的文档下载 API 需要登录认证，企业微信用户没有 RAGFlow 账号，因此需要在 nginx 层自动附加 API Token，实现免登录下载。

## 修改位置

**文件路径**：`/etc/nginx/conf.d/ragflow.conf`（RAGFlow 容器内部）

**访问方式**：
```bash
sudo docker exec -it ragflow-ragflow-cpu-1 vi /etc/nginx/conf.d/ragflow.conf
```

## 修改内容

在文件中找到以下行：

```nginx
    location ~ ^/(v1|api) {
```

**在该行紧前面**插入以下 7 行（不含行号）：

```nginx
    location ~ ^/doc-download/([^/]+)$ {
        proxy_set_header Authorization "Bearer ragflow-KnPefRsc2ssn-4gpIR6IG9ehnv4izDerTnoiZ1NzByw";
        rewrite ^/doc-download/(.*)$ /api/v1/documents/$1 break;
        proxy_pass http://localhost:9380;
        proxy_pass_header Content-Disposition;
        include proxy.conf;
    }

```

## 修改前后对比

**修改前：**
```nginx
    # ... 其他配置 ...

    location ~ ^/(v1|api) {
        proxy_pass http://127.0.0.1:9380;
        include proxy.conf;
        # ...
    }
```

**修改后：**
```nginx
    # ... 其他配置 ...

    location ~ ^/doc-download/([^/]+)$ {
        proxy_set_header Authorization "Bearer ragflow-KnPefRsc2ssn-4gpIR6IG9ehnv4izDerTnoiZ1NzByw";
        rewrite ^/doc-download/(.*)$ /api/v1/documents/$1 break;
        proxy_pass http://localhost:9380;
        proxy_pass_header Content-Disposition;
        include proxy.conf;
    }

    location ~ ^/(v1|api) {
        proxy_pass http://127.0.0.1:9380;
        include proxy.conf;
        # ...
    }
```

## 每行说明

| 行 | 作用 |
|----|------|
| `location ~ ^/doc-download/([^/]+)$ {` | 匹配 `/doc-download/文档ID` 格式的请求 |
| `proxy_set_header Authorization "Bearer xxx"` | 自动附加 RAGFlow API Token，实现免登录认证 |
| `rewrite ^/doc-download/(.*)$ /api/v1/documents/$1 break` | 把 `/doc-download/abc123` 重写为 `/api/v1/documents/abc123` |
| `proxy_pass http://localhost:9380` | 转发到 RAGFlow 后端服务 |
| `proxy_pass_header Content-Disposition` | 透传文件下载响应头（浏览器据此触发下载） |
| `include proxy.conf` | 引用 nginx 通用代理配置 |

## 生效方式

进入容器执行重载命令：

```bash
sudo docker exec ragflow-ragflow-cpu-1 nginx -s reload
```

## 验证方式

用浏览器或 curl 访问以下地址，应触发文件下载：

```
http://10.18.11.77:8088/doc-download/文档ID
```

文档 ID 可从 RAGFlow 知识库 → 文档列表中获取。

## 注意事项

1. 修改只影响 RAGFlow 容器内部 nginx，不影响宿主机或其他服务
2. RAGFlow 容器重建后配置文件会恢复默认，需要重新修改并重载
3. 如果使用一键启动脚本 `start_all_v2.sh`，启动时会自动完成此修改
4. Token（`ragflow-euytj2bGcUvyd60l8bgS2Q1INre0TgAPzhm-bl0xaQQ`）如被重置，需要同步更新此处

## 安全说明

- 路由只能用于下载文件，不能上传、修改或删除
- Token 仅限本租户的知识库范围
- 服务器 `10.18.11.77` 为公司内网 IP，仅内网可访问
- nginx 配置文件需要 root 权限才能修改
