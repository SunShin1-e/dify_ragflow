import logging
import json
import re
import time
import urllib.request
import urllib.error
from typing import Mapping

from werkzeug import Request, Response
from dify_plugin import Endpoint
from dify_plugin.config.logger_format import plugin_logger_handler

from utils.crypto import WeComCryptor


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)

# WeChat Work feedback type constants
FEEDBACK_TYPE_LIKE = 1       # 准确（点赞）
FEEDBACK_TYPE_DISLIKE = 2    # 不准确（点踩）
FEEDBACK_TYPE_CANCEL = 3     # 取消反馈

# Dify Service API base URL (internal Docker network)
# !!! 必须根据服务器实际容器名修改 !!!
# 用 docker ps --format "table {{.Names}}" | grep api 查看
DIFY_API_BASE = "http://docker-api-1:5001"


def _make_feedback_token(app_id: str) -> str:
    """Generate a deterministic feedback API token from app_id.

    Each app gets a unique, stable token so no manual configuration is needed.
    Run the matching SQL to create the token in Dify's database:
      INSERT INTO api_tokens (id, app_id, type, token, tenant_id)
      SELECT gen_random_uuid(), '<app_id>', 'app',
             'app-fb-' || substr(md5('<app_id>'), 1, 16), tenant_id
      FROM apps WHERE id = '<app_id>';
    """
    import hashlib
    return "app-fb-" + hashlib.md5(app_id.encode()).hexdigest()[:16]


class WeComMessageEndpoint(Endpoint):
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
                # Enable WeChat Work feedback (thumbs up/down)
                "feedback": {
                    "id": message_id,
                },
            },
        }

        encrypted = cryptor.encrypt_response(
            plain=json.dumps(body, ensure_ascii=False),
            timestamp=timestamp,
            nonce=nonce,
        )
        return json.dumps(encrypted, ensure_ascii=False)

    def _send_feedback_to_dify(
        self, dify_message_id: str, user_id: str,
        rating: str | None, content: str | None,
        api_key: str,
    ) -> bool:
        """
        Submit feedback to Dify Service API.
        Returns True on success, False on failure.
        """
        try:
            url = f"{DIFY_API_BASE}/v1/messages/{dify_message_id}/feedbacks"
            body = {
                "rating": rating,       # "like", "dislike", or None (cancel)
                "user": user_id,
            }
            if content:
                body["content"] = content

            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logger.info(
                        f"Feedback submitted to Dify: message={dify_message_id}, "
                        f"rating={rating}, user={user_id}"
                    )
                    return True
                else:
                    logger.warning(
                        f"Feedback submission returned {resp.status}: {resp.read().decode()}"
                    )
                    return False
        except urllib.error.HTTPError as e:
            logger.error(
                f"Feedback HTTP error {e.code}: {e.read().decode() if e.fp else 'N/A'}"
            )
            return False
        except Exception as e:
            logger.error(f"Feedback submission failed: {e}")
            return False

    def _handle_feedback_event(
        self, payload: dict, timestamp: str, nonce: str,
        cryptor: WeComCryptor, settings: Mapping, app_id: str,
    ) -> Response:
        """Handle WeChat Work feedback_event callback."""
        event = payload.get("event", {})
        feedback = event.get("feedback_event", {})

        feedback_id = feedback.get("id", "")
        feedback_type = feedback.get("type", 0)  # 1=like, 2=dislike, 3=cancel
        feedback_content = feedback.get("content", "")
        inaccurate_reasons = feedback.get("inaccurate_reason_list", [])

        # Map WeChat feedback type to Dify rating
        if feedback_type == FEEDBACK_TYPE_LIKE:
            rating = "like"
        elif feedback_type == FEEDBACK_TYPE_DISLIKE:
            rating = "dislike"
            # Append inaccurate reasons to content for richer feedback
            if inaccurate_reasons:
                reason_map = {
                    1: "与问题无关",
                    2: "内容不完整",
                    3: "内容有错误",
                    4: "数据分析错误",
                }
                reason_texts = [
                    reason_map.get(r, f"原因{r}")
                    for r in inaccurate_reasons
                ]
                reasons_str = "；".join(reason_texts)
                feedback_content = (
                    f"{feedback_content} [{reasons_str}]"
                    if feedback_content
                    else f"{reasons_str}"
                )
        elif feedback_type == FEEDBACK_TYPE_CANCEL:
            rating = None  # null to revoke
        else:
            logger.warning(f"Unknown feedback type: {feedback_type}")
            return Response(status=200, response="success")

        # Look up the Dify message_id from storage
        storage_key = f"fb_{app_id}_{feedback_id}"
        if not self.session.storage.exist(storage_key):
            logger.warning(
                f"Feedback event received but no Dify message mapping found "
                f"for feedback_id={feedback_id}"
            )
            return Response(status=200, response="success")

        try:
            stored = self.session.storage.get(storage_key).decode()
            dify_message_id, user_id = stored.split("|", 1)
        except Exception:
            logger.error(f"Failed to decode feedback mapping for {feedback_id}")
            return Response(status=200, response="success")

        # Submit to Dify — auto-generate token from app_id, no user config needed
        api_key = _make_feedback_token(app_id) if app_id else ""
        if not api_key:
            api_key = (settings.get("dify_service_api_key") or "").strip()
        if not api_key and self.session.storage.exist(f"fbkey_{app_id}"):
            api_key = self.session.storage.get(f"fbkey_{app_id}").decode().strip()
        if not api_key:
            logger.warning(
                "dify_service_api_key not configured (neither in settings nor /fbkey), "
                "skipping feedback submission"
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

    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
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

        # 提取 app_id，用于隔离不同 app 的存储 key
        raw_app_id = (settings.get("app") or {}).get("app_id", "") or "noapp"

        # --- Handle event callbacks (feedback, etc.) ---
        if payload.get("msgtype") == "event":
            event = payload.get("event", {})
            event_type = event.get("eventtype", "")

            if event_type == "feedback_event":
                return self._handle_feedback_event(
                    payload=payload, timestamp=timestamp, nonce=nonce,
                    cryptor=cryptor, settings=settings, app_id=raw_app_id,
                )
            else:
                logger.info(f"Ignoring unknown event type: {event_type}")
                return Response(status=200, response="success")

        # --- Handle text messages ---
        content = str(payload.get("text", {}).get("content")).strip()
        if not content:
            return Response(status=200, response="success")

        message_id = payload.get("msgid")
        if self.session.storage.exist(f"wemsg_{raw_app_id}_{message_id}"):
            logger.info(f"Duplicate message detected: {message_id}")
            res = self._build_wecom_res(
                message_id=message_id,
                content="",
                finish=False,
                timestamp=timestamp,
                nonce=nonce,
                cryptor=cryptor,
            )
            return Response(status=200, response=res, mimetype="application/json")
        else:
            logger.info(f"Processing new message: {message_id}")
            self.session.storage.set(f"wemsg_{raw_app_id}_{message_id}", b"processing")

        if payload.get("msgtype") == "stream":
            stream_id = payload.get("stream", {}).get("id")
            if self.session.storage.exist(f"wemsg_{raw_app_id}_{stream_id}"):
                logger.info(f"Duplicate stream detected: {stream_id}")

                result = self.session.storage.get(f"wemsg_{raw_app_id}_{stream_id}").decode()
                if result == "processing":
                    res = self._build_wecom_res(
                        message_id=stream_id,
                        content="",
                        finish=False,
                        timestamp=timestamp,
                        nonce=nonce,
                        cryptor=cryptor,
                    )
                else:
                    res = self._build_wecom_res(
                        message_id=stream_id,
                        content=result,
                        finish=True,
                        timestamp=timestamp,
                        nonce=nonce,
                        cryptor=cryptor,
                    )
                    self.session.storage.delete(f"wemsg_{raw_app_id}_{stream_id}")
                return Response(status=200, response=res, mimetype="application/json")
            else:
                # Stream ID not found in storage — the original message was
                # already processed and cleaned up.  Do NOT fall through to the
                # LLM call below: stream messages carry no text content, so
                # str(None) would become the literal string "None" as the query.
                logger.info(f"Unknown stream (already handled): {stream_id}")
                res = self._build_wecom_res(
                    message_id=stream_id,
                    content="",
                    finish=False,
                    timestamp=timestamp,
                    nonce=nonce,
                    cryptor=cryptor,
                )
                return Response(status=200, response=res, mimetype="application/json")

        try:
            app = settings.get("app")
            user_id = payload.get("from", {}).get("userid", "wecom-user")
            logger.info(f"DEBUG user_id: {user_id}")

            # Set Dify API key for feedback (via bot command, bypasses UI schema cache)
            if content.startswith("/fbkey "):
                fb_key = content.split(" ", 1)[1].strip()
                if fb_key:
                    self.session.storage.set(f"fbkey_{raw_app_id}", fb_key.encode())
                    logger.info(f"Dify feedback API key configured by user {user_id}")
                    answer = "✅ Dify 反馈 API Key 已配置，用户反馈将自动回传至 Dify。"
                else:
                    answer = "⚠️ 请提供有效的 API Key。格式：/fbkey app-xxxxxxxxxxxx"
            # Support resetting conversation
            elif content.strip() in ("新对话", "重置对话", "清除记忆", "/new", "/reset"):
                self.session.storage.delete(f"conv_{raw_app_id}_{user_id}")
                answer = "✅ 对话已重置，可以开始新对话。"
            else:
                # Load existing conversation_id for multi-turn
                conversation_id = None
                if self.session.storage.exist(f"conv_{raw_app_id}_{user_id}"):
                    conversation_id = self.session.storage.get(f"conv_{raw_app_id}_{user_id}").decode()

                # Retry logic: SSL/network errors are transient, retry up to 3 times
                MAX_RETRIES = 3
                RETRY_BASE_DELAY = 2  # seconds, exponential backoff: 2s → 4s → 6s
                last_error = None

                for attempt in range(MAX_RETRIES):
                    try:
                        response_stream = self.session.app.chat.invoke(
                            app_id=app.get("app_id"),
                            query=content,
                            user=user_id,
                            inputs={},
                            response_mode="streaming",
                            conversation_id=conversation_id,
                        )
                        answer = ""
                        references = []
                        new_conversation_id = None
                        dify_message_id = None
                        for event in response_stream:
                            if new_conversation_id is None:
                                new_conversation_id = event.get("conversation_id", "")
                            # Capture Dify message_id for feedback mapping
                            if dify_message_id is None:
                                dify_message_id = (
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
                                                "file_path": (res.get("doc_metadata") or {}).get("file_path", ""),
                                            })
                            elif evt_type == "error":
                                # Explicit error event from Dify API
                                stream_error_msg = event.get("message", "") or str(event)
                                logger.error(f"Stream error event: {stream_error_msg}")
                                raise Exception(stream_error_msg)

                        # After stream ends, check if we got a meaningful answer.
                        cleaned_answer = answer.strip()
                        if not cleaned_answer:
                            raise Exception("Empty response from agent (LLM call may have failed)")

                        # Success: store feedback mapping (wecom_msg_id → dify_message_id|user_id)
                        if dify_message_id:
                            feedback_key = f"fb_{raw_app_id}_{message_id}"
                            self.session.storage.set(
                                feedback_key,
                                f"{dify_message_id}|{user_id}".encode(),
                            )
                            logger.info(
                                f"Feedback mapping stored: {message_id} → {dify_message_id}"
                            )

                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                        error_str = str(exc).lower()
                        is_network_error = any(kw in error_str for kw in [
                            'ssl', 'decryption_failed', 'bad_record_mac',
                            'sslerror', 'connection', 'remotedisconnected',
                            'unexpected_eof', 'timeout', 'remote end closed',
                            'protocol', 'tls',
                            'empty response',
                        ])
                        if is_network_error and attempt < MAX_RETRIES - 1:
                            delay = RETRY_BASE_DELAY * (attempt + 1)
                            logger.warning(
                                f"LLM invoke attempt {attempt + 1}/{MAX_RETRIES} failed "
                                f"(network error, retrying in {delay}s): {exc}"
                            )
                            time.sleep(delay)
                            continue
                        else:
                            break

                # Handle final failure after retries exhausted
                if last_error is not None:
                    error_str = str(last_error).lower()
                    is_network_error = any(kw in error_str for kw in [
                        'ssl', 'decryption_failed', 'bad_record_mac',
                        'sslerror', 'connection', 'remotedisconnected',
                        'unexpected_eof', 'timeout', 'remote end closed',
                        'protocol', 'tls',
                        'empty response',
                    ])
                    if is_network_error:
                        logger.error(
                            f"LLM invoke failed after {MAX_RETRIES} attempts "
                            f"(network error): {last_error}"
                        )
                        answer = (
                            "抱歉，服务暂时不可用，请稍后重试。\n"
                            "如持续遇到此问题，请联系管理员。"
                        )
                    else:
                        logger.error(f"LLM invoke failed (non-network error): {last_error}")
                        answer = "抱歉，处理您的请求时出现了错误，请稍后重试。"

                # Only save conversation_id and process references on success
                if last_error is None:
                    if new_conversation_id:
                        self.session.storage.set(f"conv_{raw_app_id}_{user_id}", new_conversation_id.encode())
                    if references:
                        seen = set()
                        unique_docs = []
                        for ref in references:
                            cleaned = ref["name"].replace("\\", "/").rsplit("/", 1)[-1]
                            if cleaned not in seen:
                                seen.add(cleaned)
                                unique_docs.append((cleaned, ref.get("file_path", "")))
                        if unique_docs:
                            answer += "\n\n---\n📚 参考文档：\n"
                            for idx, (doc_name, file_path) in enumerate(unique_docs, 1):
                                if file_path:
                                    answer += f"{idx}. {doc_name}\n   📁 {file_path}\n"
                                else:
                                    answer += f"{idx}. {doc_name}\n"
                    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
                    answer = re.sub(r"\[\d+(?:\.\d+)*\]", "", answer)
        except Exception as exc:
            logger.exception(f"Unexpected error in wecom message handling: {exc}")
            answer = "抱歉，处理您的请求时出现了未知错误，请稍后重试。"

        if len(answer) > 5000:
            answer = answer[:5000] + "..."

        stream_id = message_id
        self.session.storage.set(f"wemsg_{raw_app_id}_{stream_id}", answer.encode())
        res = self._build_wecom_res(
            message_id=stream_id,
            content=answer,
            finish=True,
            timestamp=timestamp,
            nonce=nonce,
            cryptor=cryptor,
        )
        return Response(status=200, response=res, mimetype="application/json")
