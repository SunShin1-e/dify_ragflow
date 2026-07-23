#!/bin/bash
# ============================================================
# Dify + RAGFlow 一键启动 & 修复脚本 (v2)
# 用法: bash ~/ragflow/docker/start_all.sh
# ============================================================
# v2 改进:
#   - 先启 RAGFlow（带 redis），再启 Dify，避免 redis 容器冲突
#   - wecom-bot 部署 v3（外部 API 版）
#   - 去掉 set -e，逐命令容错
#   - 部署插件后重启 plugin_daemon
#   - 覆盖 entrypoint 后重启 RAGFlow
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[OK]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC}  $1"; }
info()  { echo -e "${BLUE}[..]${NC}  $1"; }

# ---- 路径 ----
RAGFLOW_DIR="$HOME/ragflow/docker"
DIFY_DIR="$HOME/dify/docker"
PATCH_SRC="$RAGFLOW_DIR"
DESKTOP="/mnt/c/Users/zhengkun.deng/Desktop"

# ---- 等待函数 ----
wait_for_healthy() {
    local container=$1 max_wait=${2:-60} elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        local status
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "missing")
        [ "$status" = "healthy" ] && return 0
        sleep 2; elapsed=$((elapsed + 2))
    done
    return 1
}

wait_for_log() {
    local container=$1 pattern=$2 max_wait=${3:-60} elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        docker logs "$container" 2>&1 | grep -q "$pattern" && return 0
        sleep 2; elapsed=$((elapsed + 2))
    done
    return 1
}

echo ""
echo "============================================="
echo "  Dify + RAGFlow 一键启动 (v2)"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================="
echo ""

# ============================================================
# 1. 先启动 RAGFlow（带 redis），避免 redis 容器冲突
# ============================================================
info "正在启动 RAGFlow 及依赖 (redis, mysql, es, minio)..."
cd "$RAGFLOW_DIR"
docker compose up -d 2>&1 | grep -v "orphan\|level=warning" || true

info "等待 RAGFlow 就绪 (通常 ~30s)..."
wait_for_log "docker-ragflow-cpu-1" "RAGFlow server is ready" 120 && \
    log "RAGFlow 就绪" || warn "RAGFlow 启动可能未完成，继续..."

# ============================================================
# 2. 再启动 Dify（会直接连上 RAGFlow 已有的 redis）
# ============================================================
info "正在启动 Dify..."
cd "$DIFY_DIR"
docker compose up -d 2>&1 | grep -v "orphan\|level=warning" || true

info "等待 Dify 数据库..."
wait_for_healthy "docker-db_postgres-1" 30 && log "PostgreSQL 就绪" || warn "PostgreSQL 超时"

info "等待 Dify API..."
wait_for_healthy "docker-api-1" 90 && log "Dify API 就绪" || warn "Dify API 超时，继续..."

# ============================================================
# 3. 确保 Redis 有正确的网络别名
# ============================================================
info "确保 Redis 网络配置..."
# RAGFlow 和 Dify 共享 redis 容器，需要别名 redis
docker network disconnect docker_default docker-redis-1 2>/dev/null || true
docker network connect --alias redis docker_default docker-redis-1 2>/dev/null && \
    log "Redis 网络别名 ok" || warn "Redis 网络修复失败"

# ============================================================
# 4. RAGFlow <-> Dify 网络互通
# ============================================================
info "连接 RAGFlow → Dify 网络..."
if docker inspect docker-ragflow-cpu-1 2>/dev/null | grep -q "docker_default"; then
    log "RAGFlow 已在 Dify 网络中"
else
    docker network connect docker_default docker-ragflow-cpu-1 2>/dev/null && \
        log "RAGFlow 已加入 Dify 网络" || warn "连接失败"
fi

# ============================================================
# 5. 部署补丁文件到 RAGFlow
# ============================================================
info "部署 RAGFlow 补丁..."

# embedding_model_patched.py
if [ -f "$PATCH_SRC/embedding_model_patched.py" ]; then
    docker cp "$PATCH_SRC/embedding_model_patched.py" \
        docker-ragflow-cpu-1:/ragflow/rag/llm/embedding_model.py 2>/dev/null && \
        log "embedding_model.py" || warn "embedding_model 失败"
fi

# entrypoint.sh — 覆盖后需重启 RAGFlow
if [ -f "$PATCH_SRC/entrypoint.sh" ]; then
    docker cp "$PATCH_SRC/entrypoint.sh" \
        docker-ragflow-cpu-1:/ragflow/entrypoint.sh 2>/dev/null && {
        log "entrypoint.sh — 重启 RAGFlow 使其生效..."
        docker restart docker-ragflow-cpu-1 > /dev/null 2>&1
        sleep 5
        wait_for_log "docker-ragflow-cpu-1" "RAGFlow server is ready" 120 && \
            log "RAGFlow 已重新就绪" || warn "RAGFlow 重启后超时"
    } || warn "entrypoint 部署失败"
fi

# sitecustomize.py (bind mount，容器重启后自动生效)
if [ -f "$PATCH_SRC/sitecustomize.py" ]; then
    docker exec docker-ragflow-cpu-1 \
        test -f /ragflow/.venv/lib/python3.13/site-packages/sitecustomize.py 2>/dev/null && \
        log "sitecustomize.py (mount)" || {
        docker exec docker-ragflow-cpu-1 \
            tee /ragflow/.venv/lib/python3.13/site-packages/sitecustomize.py \
            < "$PATCH_SRC/sitecustomize.py" > /dev/null 2>&1 && \
            log "sitecustomize.py (copied)" || warn "sitecustomize 失败"
    }
fi

# inject_doc_download.py
if [ -f "$PATCH_SRC/inject_doc_download.py" ]; then
    docker exec docker-ragflow-cpu-1 \
        test -f /ragflow/docker/inject_doc_download.py 2>/dev/null && \
        log "inject_doc_download.py (mount)" || {
        docker exec docker-ragflow-cpu-1 \
            tee /ragflow/docker/inject_doc_download.py \
            < "$PATCH_SRC/inject_doc_download.py" > /dev/null 2>&1 && \
            log "inject_doc_download.py (copied)" || warn "inject_doc_download 失败"
    }
fi

# picture.py (VLM)
if [ -f "$DESKTOP/patch_picture.py" ]; then
    docker cp "$DESKTOP/patch_picture.py" \
        docker-ragflow-cpu-1:/ragflow/rag/app/picture.py 2>/dev/null && \
        log "picture.py (VLM)" || warn "picture.py 失败"
fi

# dify_retrieval_api.py (meta_fields 补丁)
if [ -f "$DESKTOP/dify_retrieval_api_patched.py" ]; then
    docker cp "$DESKTOP/dify_retrieval_api_patched.py" \
        docker-ragflow-cpu-1:/ragflow/api/apps/restful_apis/dify_retrieval_api.py 2>/dev/null && \
        log "dify_retrieval_api.py" || warn "dify_retrieval_api 失败"
fi

log "RAGFlow 补丁部署完成"

# ============================================================
# 6. 部署 wecom-bot 插件 (v3 外部 API 版)
# ============================================================
info "部署 wecom-bot 插件..."
PLUGIN_BASE="/app/storage/cwd/langgenius/wecom-bot-0.0.6@7cbd51badc147801f353d520198d0e97ac8b8d259af4e5ac8be679da2176d415"

# 优先 v3，回退 v2
WECOM_V3="/mnt/d/work/dify_ragflow/wecom_message_v3.py"
WECOM_V2="/mnt/d/work/dify_ragflow/wecom_message_v2.py"
PLUGIN_SRC=""
if [ -f "$WECOM_V3" ]; then
    PLUGIN_SRC="$WECOM_V3"
elif [ -f "$WECOM_V2" ]; then
    PLUGIN_SRC="$WECOM_V2"
    warn "v3 未找到，使用 v2 (内部 API 版)"
fi

if [ -n "$PLUGIN_SRC" ]; then
    docker cp "$PLUGIN_SRC" \
        "docker-plugin_daemon-1:${PLUGIN_BASE}/endpoints/wecom_message.py" 2>/dev/null && {
        log "wecom_message.py 已部署 ($(basename $PLUGIN_SRC))"
        # 重启 plugin daemon 以加载新代码
        docker restart docker-plugin_daemon-1 > /dev/null 2>&1
        log "plugin_daemon 已重启"
        # 等待 wecom-bot 启动（最多 20s）
        info "等待 wecom-bot 插件启动..."
        WECOM_READY=0
        for i in $(seq 1 10); do
            sleep 2
            if docker logs docker-plugin_daemon-1 --tail 30 2>&1 | grep -q "local runtime ready.*wecom-bot"; then
                WECOM_READY=1
                log "wecom-bot 插件运行正常"
                break
            fi
        done
        if [ $WECOM_READY -eq 0 ]; then
            warn "wecom-bot 可能未正常启动，请检查: docker logs docker-plugin_daemon-1 --tail 30"
        fi
        true  # 确保整个块返回成功，避免触发外层的 || warn
    } || warn "wecom_message.py 部署失败（plugin_daemon 可能未运行）"
else
    warn "未找到 wecom_message_v3.py 或 v2，跳过插件部署"
fi

# ============================================================
# 7. 注入 doc-download nginx 配置
# ============================================================
info "注入 doc-download nginx 代理..."
INJECT_RESULT=$(docker exec docker-ragflow-cpu-1 \
    python3 /ragflow/docker/inject_doc_download.py \
    /etc/nginx/conf.d/ragflow.conf 2>&1) && INJECT_EXIT=$? || INJECT_EXIT=$?
echo "  $INJECT_RESULT"

if [ $INJECT_EXIT -eq 0 ] || echo "$INJECT_RESULT" | grep -qi "already exists"; then
    sleep 2  # 等 nginx 就绪
    if docker exec docker-ragflow-cpu-1 nginx -s reload 2>/dev/null; then
        log "doc-download 代理已激活"
    else
        # nginx 重载失败但配置已注入，容器重启后自动生效
        log "doc-download 配置已注入 (下次重启生效)"
    fi
else
    warn "doc-download 注入失败: $INJECT_RESULT"
fi

# ============================================================
# 8. 重启 Dify 服务（确保连接新的 redis 别名）
# ============================================================
info "重启 Dify 服务（刷新连接）..."
docker restart docker-api-1 docker-worker-1 docker-worker_beat-1 docker-api_websocket-1 > /dev/null 2>&1
sleep 8
log "Dify 服务已重启"

# ============================================================
# 9. 状态 & 连通性检测
# ============================================================
echo ""
echo "============================================="
log "  全部启动完成!"
echo ""
echo "  Dify:     http://10.18.160.120:3000"
echo "  RAGFlow:  http://10.18.160.120:80"
echo "============================================="
echo ""
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | head -20
echo ""

info "连通性检测..."
docker exec docker-ragflow-cpu-1 \
    curl -s -o /dev/null --connect-timeout 5 https://dashscope.aliyuncs.com 2>/dev/null && \
    log "DashScope API 可达" || warn "DashScope 不可达 — 检查代理"

# 等待 API 就绪后重试连通检测
info "等待 Dify API 就绪后检测互通..."
DIFY_RAGFLOW_OK=0
for i in $(seq 1 5); do
    sleep 3
    if docker exec docker-api-1 \
        curl -s -o /dev/null --connect-timeout 5 http://docker-ragflow-cpu-1:80 2>/dev/null; then
        DIFY_RAGFLOW_OK=1
        log "Dify → RAGFlow 连通正常"
        break
    fi
done
[ $DIFY_RAGFLOW_OK -eq 0 ] && warn "Dify → RAGFlow 不可达 — 知识库检索将失败"

echo ""
