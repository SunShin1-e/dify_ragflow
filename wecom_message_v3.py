"""
wecom-bot plugin — v3 (纯外部 API 版)

与 v2 的区别：
  - 对话改用 Dify 外部 Service API (/v1/chat-messages)，不再走内部 API
  - Dify 源码零侵入：不需要改 _get_user、plugin.py
  - 需要配置 dify_service_api_key（对话 + 反馈共用）

变更点摘要：
  v2:  self.session.app.chat.invoke(...)          ← 内部 API，需改 Dify
  v3:  _call_dify_service_api(...) → urllib SSE  ← 外部 API，零侵入
"""
import hashlib
import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Mapping

from werkzeug import Request, Response
from dify_plugin import Endpoint
from dify_plugin.config.logger_format import plugin_logger_handler

from utils.crypto import WeComCryptor

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)

# ── constants ──────────────────────────────────────────────
FEEDBACK_TYPE_LIKE = 1
FEEDBACK_TYPE_DISLIKE = 2
FEEDBACK_TYPE_CANCEL = 3

# Dify Service API base URL（容器内网地址）
# 如果你的 Dify API 容器不叫 docker-api-1，请修改这里
DIFY_API_BASE = "http://dify-api-1:5001"
# RAGFlow 外部访问地址（用于生成文档下载链接）
RAGFLOW_BASE_URL = "http://10.18.11.77:8088"

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2
MAX_ANSWER_LEN = 5000

# SSL 网络错误的特征关键词
NETWORK_ERROR_KW = (
    "ssl", "decryption_failed", "bad_record_mac",
    "sslerror", "connection", "remotedisconnected",
    "unexpected_eof", "timeout", "remote end closed",
    "protocol", "tls", "empty response",
)


# ── helpers ────────────────────────────────────────────────
def _make_feedback_token(app_id: str) -> str:
    """为每个 app 生成一个确定性的 feedback API token（免手动配置）"""
    return "app-fb-" + hashlib.md5(app_id.encode()).hexdigest()[:16]


def _is_network_error(exc: Exception) -> bool:
    return any(kw in str(exc).lower() for kw in NETWORK_ERROR_KW)


# ── endpoint ───────────────────────────────────────────────
class WeComMessageEndpoint(Endpoint):
    # ============================================================
    # 企业微信消息加解密 / 构建回复
    # ============================================================
    def _build_wecom_res(
        self, message_id: str, content: str, finish: bool,
        timestamp: str, nonce: str, cryptor: WeComCryptor,
    ) -> str:
        body = {
            "msgtype": "stream",
            "stream": {
                "id": message_id,
                "finish": finish,
                "content": content,
                "feedback": {"id": message_id},
            },
        }
        encrypted = cryptor.encrypt_response(
            plain=json.dumps(body, ensure_ascii=False),
            timestamp=timestamp,
            nonce=nonce,
        )
        return json.dumps(encrypted, ensure_ascii=False)

    # ============================================================
    # 外部 Service API 调用（替代 session.app.chat.invoke）
    # ============================================================
    def _call_dify_service_api(
        self, query: str, user_id: str, api_key: str,
        conversation_id: str | None = None,
    ) -> dict:
        """调用 Dify Service API /v1/chat-messages，返回 dict。

        成功返回:
            {"ok": True, "answer": str, "conversation_id": str,
             "message_id": str, "references": list[dict]}

        失败返回:
            {"ok": False, "error": str, "is_network": bool}
        """
        url = f"{DIFY_API_BASE}/v1/chat-messages"
        body = {
            "inputs": {},
            "query": query,
            "response_mode": "streaming",
            "user": user_id,
        }
        if conversation_id:
            body["conversation_id"] = conversation_id

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        # SSL 上下文：对内网地址关闭证书校验
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        answer = ""
        new_conversation_id = ""
        message_id = ""
        references: list[dict] = []

        try:
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                if resp.status != 200:
                    return {
                        "ok": False,
                        "error": f"HTTP {resp.status}",
                        "is_network": False,
                    }

                buffer = b""
                for chunk in iter(lambda: resp.read(1024), b""):
                    if not chunk:
                        break
                    buffer += chunk

                    while b"\n\n" in buffer:
                        evt_bytes, buffer = buffer.split(b"\n\n", 1)
                        evt_str = evt_bytes.decode("utf-8")
                        for line in evt_str.split("\n"):
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            json_str = line[5:].strip()
                            if not json_str:
                                continue
                            try:
                                event = json.loads(json_str)
                            except json.JSONDecodeError:
                                continue

                            # 收集 conversation_id 和 message_id
                            if not new_conversation_id:
                                new_conversation_id = event.get("conversation_id", "")
                            if not message_id:
                                message_id = (
                                    event.get("message_id")
                                    or event.get("id")
                                    or ""
                                )

                            evt_type = event.get("event", "")

                            if evt_type in ("message", "agent_message"):
                                answer += event.get("answer", "")
                            elif evt_type == "message_end":
                                metadata = event.get("metadata", {})
                                if isinstance(metadata, dict):
                                    for res in metadata.get("retriever_resources", []):
                                        ref_doc = res.get("document_name", "")
                                        if ref_doc:
                                            references.append({
                                                "name": ref_doc,
                                                "file_path": (
                                                    res.get("doc_metadata") or {}
                                                ).get("file_path", ""),
                                                "document_id": res.get("document_id", ""),
                                                "dataset_id": res.get("dataset_id", ""),
                                            })
                            elif evt_type == "error":
                                error_msg = event.get("message", "") or str(event)
                                return {
                                    "ok": False,
                                    "error": error_msg,
                                    "is_network": _is_network_error(Exception(error_msg)),
                                }

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode(errors="replace")[:500]
            except Exception:
                pass
            return {
                "ok": False,
                "error": f"HTTP {e.code}: {error_body}",
                "is_network": False,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "is_network": _is_network_error(e),
            }

        # 空应答检测
        if not answer.strip():
            return {
                "ok": False,
                "error": "Empty response from agent (LLM call may have failed)",
                "is_network": True,  # 可重试
            }

        return {
            "ok": True,
            "answer": answer,
            "conversation_id": new_conversation_id,
            "message_id": message_id,
            "references": references,
        }

    # ============================================================
    # 反馈回传（跟 v2 一样，外部 API）
    # ============================================================
    def _send_feedback_to_dify(
        self, dify_message_id: str, user_id: str,
        rating: str | None, content: str | None,
        api_key: str,
    ) -> bool:
        try:
            url = f"{DIFY_API_BASE}/v1/messages/{dify_message_id}/feedbacks"
            body = {"rating": rating, "user": user_id}
            if content:
                body["content"] = content
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                if resp.status == 200:
                    logger.info(
                        f"Feedback submitted: message={dify_message_id}, "
                        f"rating={rating}, user={user_id}"
                    )
                    return True
                else:
                    logger.warning(
                        f"Feedback submission returned {resp.status}: "
                        f"{resp.read().decode(errors='replace')}"
                    )
                    return False
        except urllib.error.HTTPError as e:
            logger.error(
                f"Feedback HTTP error {e.code}: "
                f"{e.read().decode(errors='replace') if e.fp else 'N/A'}"
            )
            return False
        except Exception as e:
            logger.error(f"Feedback submission failed: {e}")
            return False

    def _handle_feedback_event(
        self, payload: dict, timestamp: str, nonce: str,
        cryptor: WeComCryptor, settings: Mapping, app_id: str,
    ) -> Response:
        """处理企业微信 feedback_event 回调（和 v2 一样）"""
        event = payload.get("event", {})
        feedback = event.get("feedback_event", {})

        feedback_id = feedback.get("id", "")
        feedback_type = feedback.get("type", 0)
        feedback_content = feedback.get("content", "")
        inaccurate_reasons = feedback.get("inaccurate_reason_list", [])

        if feedback_type == FEEDBACK_TYPE_LIKE:
            rating = "like"
        elif feedback_type == FEEDBACK_TYPE_DISLIKE:
            rating = "dislike"
            if inaccurate_reasons:
                reason_map = {
                    1: "与问题无关", 2: "内容不完整",
                    3: "内容有错误", 4: "数据分析错误",
                }
                reason_texts = [
                    reason_map.get(r, f"原因{r}")
                    for r in inaccurate_reasons
                ]
                reasons_str = "；".join(reason_texts)
                feedback_content = (
                    f"{feedback_content} [{reasons_str}]"
                    if feedback_content else reasons_str
                )
        elif feedback_type == FEEDBACK_TYPE_CANCEL:
            rating = None
        else:
            return Response(status=200, response="success")

        # 查找映射
        storage_key = f"fb_{app_id}_{feedback_id}"
        if not self.session.storage.exist(storage_key):
            logger.warning(
                f"Feedback mapping not found for feedback_id={feedback_id}"
            )
            return Response(status=200, response="success")

        try:
            stored = self.session.storage.get(storage_key).decode()
            dify_message_id, user_id = stored.split("|", 1)
        except Exception:
            logger.error(f"Failed to decode feedback mapping for {feedback_id}")
            return Response(status=200, response="success")

        # 获取 API Key：优先用配置的 Key，其次 /fbkey 命令，最后自动生成
        api_key = (settings.get("dify_service_api_key") or "").strip()
        if not api_key and self.session.storage.exist(f"fbkey_{app_id}"):
            api_key = self.session.storage.get(f"fbkey_{app_id}").decode().strip()
        if not api_key:
            api_key = _make_feedback_token(app_id) if app_id else ""
        if not api_key:
            logger.warning(
                "dify_service_api_key not configured, skipping feedback"
            )
            return Response(status=200, response="success")

        self._send_feedback_to_dify(
            dify_message_id=dify_message_id,
            user_id=user_id,
            rating=rating,
            content=feedback_content,
            api_key=api_key,
        )
        return Response(status=200, response="success")

    # ============================================================
    # 对话处理（提取到独立方法，供流式轮询复用）
    # ============================================================
    def _do_chat(
        self, content: str, user_id: str, api_key: str,
        raw_app_id: str, message_id: str,
        ragflow_base_url: str = "",
    ) -> str:
        """执行完整对话流程，返回答案字符串（已含参考文档/过滤）。"""
        answer: str

        # ------ /fbkey 命令 ------
        if content.startswith("/fbkey "):
            fb_key = content.split(" ", 1)[1].strip()
            if fb_key:
                self.session.storage.set(f"fbkey_{raw_app_id}", fb_key.encode())
                return "✅ Dify API Key 已配置。"
            else:
                return "⚠️ 请提供有效的 API Key。格式：/fbkey app-xxxxxxxxxxxx"

        # ------ 重置对话 ------
        if content.strip() in ("新对话", "重置对话", "清除记忆", "/new", "/reset"):
            self.session.storage.delete(f"conv_{raw_app_id}_{user_id}")
            return "✅ 对话已重置，可以开始新对话。"

        # ------ 正常对话 ------
        if not api_key:
            return (
                "⚠️ 尚未配置 Dify API Key，无法调用应用。\n"
                "请在插件设置中填写 dify_service_api_key，"
                "或通过企业微信发送 /fbkey 命令配置。"
            )

        conversation_id = None
        if self.session.storage.exist(f"conv_{raw_app_id}_{user_id}"):
            conversation_id = (
                self.session.storage.get(f"conv_{raw_app_id}_{user_id}").decode()
            )

        # 重试逻辑
        last_error = None
        result = None

        for attempt in range(MAX_RETRIES):
            try:
                result = self._call_dify_service_api(
                    query=content,
                    user_id=user_id,
                    api_key=api_key,
                    conversation_id=conversation_id,
                )
                if result["ok"]:
                    last_error = None
                    break
                else:
                    last_error = Exception(result["error"])
                    if not result.get("is_network"):
                        break
            except Exception as exc:
                last_error = exc
                if not _is_network_error(exc):
                    break

            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (attempt + 1)
                logger.warning(
                    f"Attempt {attempt + 1}/{MAX_RETRIES} failed "
                    f"(retrying in {delay}s): {last_error}"
                )
                time.sleep(delay)

        # 处理结果
        if result and result["ok"]:
            answer = result["answer"]
            new_conversation_id = result["conversation_id"]
            dify_message_id = result["message_id"]
            references = result["references"]

            if new_conversation_id:
                self.session.storage.set(
                    f"conv_{raw_app_id}_{user_id}",
                    new_conversation_id.encode(),
                )

            if dify_message_id:
                self.session.storage.set(
                    f"fb_{raw_app_id}_{message_id}",
                    f"{dify_message_id}|{user_id}".encode(),
                )

            if references:
                seen = set()
                unique_docs = []
                for ref in references:
                    cleaned = (
                        ref["name"].replace("\\", "/").rsplit("/", 1)[-1]
                    )
                    if cleaned not in seen:
                        seen.add(cleaned)
                        unique_docs.append(
                            (cleaned, ref.get("file_path", ""), ref.get("document_id", ""))
                        )
                if unique_docs:
                    answer += "\n\n---\n📚 参考文档：\n"
                    for idx, (doc_name, file_path, doc_id) in enumerate(unique_docs, 1):
                        if doc_id and ragflow_base_url:
                            link = f"{ragflow_base_url.rstrip('/')}/doc-download/{doc_id}"
                            answer += f'{idx}. [{doc_name}]({link})\n'
                        else:
                            answer += f"{idx}. {doc_name}\n"
                        if file_path:
                            answer += f"   📁 {file_path}\n"

            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
            answer = re.sub(r"\[\d+(?:\.\d+)*\]", "", answer)

        else:
            error_str = str(last_error).lower() if last_error else ""
            if _is_network_error(Exception(error_str)):
                logger.error(
                    f"LLM invoke failed after {MAX_RETRIES} attempts: {last_error}"
                )
                answer = (
                    "抱歉，服务暂时不可用，请稍后重试。\n"
                    "如持续遇到此问题，请联系管理员。"
                )
            else:
                logger.error(f"LLM invoke failed (non-network): {last_error}")
                answer = "抱歉，处理您的请求时出现了错误，请稍后重试。"

        return answer

    def _handle_stream_poll(
        self, payload: dict, raw_app_id: str,
        timestamp: str, nonce: str, cryptor: WeComCryptor,
        settings: Mapping,
    ) -> Response:
        """处理企微流式轮询：首次轮询时真正调 LLM，后续轮询返回缓存结果。"""
        stream_id = payload.get("stream", {}).get("id")

        # 已知的 stream —— 返回缓存结果
        if self.session.storage.exist(f"wemsg_{raw_app_id}_{stream_id}"):
            result = self.session.storage.get(
                f"wemsg_{raw_app_id}_{stream_id}"
            ).decode()
            if result == "processing":
                # 首次轮询：尝试获取处理锁，执行实际对话
                lock_key = f"weml_{raw_app_id}_{stream_id}"
                if not self.session.storage.exist(lock_key):
                    self.session.storage.set(lock_key, b"running")

                    # 获取文本消息上下文
                    ctx_key = f"wemctx_{raw_app_id}_{stream_id}"
                    if self.session.storage.exist(ctx_key):
                        ctx = json.loads(
                            self.session.storage.get(ctx_key).decode()
                        )
                        user_id = ctx.get("user_id", "wecom-user")
                        content = ctx.get("content", "")
                    else:
                        user_id = "wecom-user"
                        content = ""

                    logger.info(f"User: {user_id}")

                    # 获取 API Key
                    api_key = (settings.get("dify_service_api_key") or "").strip()
                    if not api_key and self.session.storage.exist(
                        f"fbkey_{raw_app_id}"
                    ):
                        api_key = (
                            self.session.storage.get(f"fbkey_{raw_app_id}")
                            .decode().strip()
                        )

                    ragflow_base_url = (
                        (settings.get("ragflow_base_url") or "").strip()
                        or RAGFLOW_BASE_URL
                    )

                    try:
                        answer = self._do_chat(
                            content=content,
                            user_id=user_id,
                            api_key=api_key,
                            raw_app_id=raw_app_id,
                            message_id=stream_id,
                            ragflow_base_url=ragflow_base_url,
                        )
                    except Exception as exc:
                        logger.exception(f"Unexpected error: {exc}")
                        answer = "抱歉，处理您的请求时出现了未知错误，请稍后重试。"

                    if len(answer) > MAX_ANSWER_LEN:
                        answer = answer[:MAX_ANSWER_LEN] + "..."

                    self.session.storage.set(
                        f"wemsg_{raw_app_id}_{stream_id}", answer.encode(),
                    )
                    # 清理
                    self.session.storage.delete(lock_key)
                    self.session.storage.delete(ctx_key)

                # 还在处理中，返回空
                res = self._build_wecom_res(
                    message_id=stream_id, content="", finish=False,
                    timestamp=timestamp, nonce=nonce, cryptor=cryptor,
                )
                return Response(
                    status=200, response=res, mimetype="application/json",
                )
            else:
                # 结果已就绪
                res = self._build_wecom_res(
                    message_id=stream_id, content=result, finish=True,
                    timestamp=timestamp, nonce=nonce, cryptor=cryptor,
                )
                self.session.storage.delete(f"wemsg_{raw_app_id}_{stream_id}")
                return Response(
                    status=200, response=res, mimetype="application/json",
                )

        # 未知 stream（已处理完毕或过期）
        logger.info(f"Unknown stream (already handled): {stream_id}")
        res = self._build_wecom_res(
            message_id=stream_id, content="", finish=False,
            timestamp=timestamp, nonce=nonce, cryptor=cryptor,
        )
        return Response(status=200, response=res, mimetype="application/json")

    # ============================================================
    # 主入口
    # ============================================================
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        # ── 解密 ──
        token = settings.get("token")
        encoding_key = settings.get("encoding_aes_key")
        if not token or not encoding_key:
            return Response(status=400, response="missing token or encoding key")

        signature = r.args.get("msg_signature")
        timestamp = r.args.get("timestamp")
        nonce = r.args.get("nonce")
        if not all([signature, timestamp, nonce]):
            return Response(status=400, response="missing signature params")

        try:
            body = r.get_json(force=True)
        except Exception as exc:
            return Response(status=400, response=f"invalid json: {exc}")

        encrypt = body.get("encrypt") if isinstance(body, Mapping) else None
        if not encrypt:
            return Response(status=400, response="missing encrypt")

        cryptor = WeComCryptor(token=token, encoding_aes_key=encoding_key)
        try:
            payload = cryptor.decrypt(
                signature=signature, timestamp=timestamp,
                nonce=nonce, ciphertext=encrypt,
            )
        except Exception as exc:
            return Response(status=400, response=f"decrypt_failed:{exc}")

        raw_app_id = (settings.get("app") or {}).get("app_id", "") or "noapp"

        # ── 事件回调（反馈）──
        if payload.get("msgtype") == "event":
            event = payload.get("event", {})
            if event.get("eventtype") == "feedback_event":
                return self._handle_feedback_event(
                    payload=payload, timestamp=timestamp, nonce=nonce,
                    cryptor=cryptor, settings=settings, app_id=raw_app_id,
                )
            else:
                logger.info(f"Ignoring unknown event type: {event.get('eventtype')}")
                return Response(status=200, response="success")

        # ── 文本消息 ──
        content = str(payload.get("text", {}).get("content")).strip()
        if not content:
            return Response(status=200, response="success")

        message_id = payload.get("msgid")

        # 消息去重
        if self.session.storage.exist(f"wemsg_{raw_app_id}_{message_id}"):
            logger.info(f"Duplicate message: {message_id}")
            return Response(
                status=200,
                response=self._build_wecom_res(
                    message_id=message_id, content="", finish=False,
                    timestamp=timestamp, nonce=nonce, cryptor=cryptor,
                ),
                mimetype="application/json",
            )

        # 流式轮询 —— 可能执行实际 LLM 调用
        if payload.get("msgtype") == "stream":
            return self._handle_stream_poll(
                payload=payload, raw_app_id=raw_app_id,
                timestamp=timestamp, nonce=nonce, cryptor=cryptor,
                settings=settings,
            )

        # 普通文本消息 —— 存入上下文，立即返回以让企微显示「正在回答」
        user_id = payload.get("from", {}).get("userid", "wecom-user")
        logger.info(f"User: {user_id}")

        ctx = json.dumps({"user_id": user_id, "content": content}, ensure_ascii=False)
        self.session.storage.set(f"wemctx_{raw_app_id}_{message_id}", ctx.encode())
        self.session.storage.set(f"wemsg_{raw_app_id}_{message_id}", b"processing")

        res = self._build_wecom_res(
            message_id=message_id, content="", finish=False,
            timestamp=timestamp, nonce=nonce, cryptor=cryptor,
        )
        return Response(status=200, response=res, mimetype="application/json")
