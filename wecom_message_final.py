import logging
import json
import re
from typing import Mapping

from werkzeug import Request, Response
from dify_plugin import Endpoint
from dify_plugin.config.logger_format import plugin_logger_handler

from utils.crypto import WeComCryptor


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)


class WeComMessageEndpoint(Endpoint):
    def _build_wecom_res(self, message_id: str, content: str, finish: bool, timestamp: str, nonce: str, cryptor: WeComCryptor) -> str:
        body = {
            "msgtype": "stream",
            "stream": {
                "id": message_id,
                "finish": finish,
                "content": content,
            }
        }

        encrypted = cryptor.encrypt_response(
                plain=json.dumps(body, ensure_ascii=False),
                timestamp=timestamp,
                nonce=nonce,
        )
        return json.dumps(encrypted, ensure_ascii=False)

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
            payload = cryptor.decrypt(signature=signature, timestamp=timestamp, nonce=nonce, ciphertext=encrypt)
        except Exception as exc:
            return Response(status=400, response=f"decrypt_failed:{exc}")

        content = str(payload.get("text", {}).get("content")).strip()
        if not content:
            return Response(status=200, response="success")

        message_id = payload.get("msgid")
        if self.session.storage.exist(f"wecom_msg_{message_id}"):
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
            self.session.storage.set(f"wecom_msg_{message_id}", b"processing")

        if payload.get("msgtype") == "stream":
            stream_id = payload.get("stream", {}).get("id")
            if self.session.storage.exist(f"wecom_msg_{stream_id}"):
                logger.info(f"Duplicate stream detected: {stream_id}")

                result = self.session.storage.get(f"wecom_msg_{stream_id}").decode()
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
                    self.session.storage.delete(f"wecom_msg_{stream_id}")
                return Response(status=200, response=res, mimetype="application/json")
            else:
                logger.info(f"Processing new stream: {stream_id}")
                self.session.storage.set(f"wecom_msg_{stream_id}", b"processing")

        try:
            app = settings.get("app")
            user_id = payload.get("from", {}).get("userid", "wecom-user")

            # Support resetting conversation
            if content.strip() in ("新对话", "重置对话", "清除记忆", "/new", "/reset"):
                self.session.storage.delete(f"conv_{user_id}")
                answer = "✅ 对话已重置，可以开始新对话。"
            else:
                # Load existing conversation_id for multi-turn
                conversation_id = None
                if self.session.storage.exist(f"conv_{user_id}"):
                    conversation_id = self.session.storage.get(f"conv_{user_id}").decode()

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
                for event in response_stream:
                    if new_conversation_id is None:
                        new_conversation_id = event.get("conversation_id", "")
                    if event.get("event") in ("message", "agent_message"):
                        answer += event.get("answer", "")
                    elif event.get("event") == "message_end":
                        metadata = event.get("metadata", {})
                        if isinstance(metadata, dict):
                            for res in metadata.get("retriever_resources", []):
                                ref_doc = res.get("document_name", "")
                                if ref_doc:
                                    references.append(ref_doc)
                # Save conversation_id for next turn
                if new_conversation_id:
                    self.session.storage.set(f"conv_{user_id}", new_conversation_id.encode())
                # Append reference list (deduplicated, sequential numbers)
                if references:
                    seen = set()
                    unique_docs = []
                    for doc in references:
                        cleaned = doc.replace("\\", "/").rsplit("/", 1)[-1]
                        if cleaned not in seen:
                            seen.add(cleaned)
                            unique_docs.append(cleaned)
                    if unique_docs:
                        answer += "\n\n---\n📚 参考文档：\n"
                        for idx, doc_name in enumerate(unique_docs, 1):
                            answer += f"{idx}. {doc_name}\n"
                # Filter <think> blocks from reasoning models
                answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
                # Remove all inline citation markers like [1], [10], [8.1.2]
                answer = re.sub(r"\[\d+(?:\.\d+)*\]", "", answer)
        except Exception as exc:
            answer = f"Errors：{exc}"

        if len(answer) > 5000:
            answer = answer[:5000] + "..."

        stream_id = message_id
        self.session.storage.set(f"wecom_msg_{stream_id}", answer.encode())
        res = self._build_wecom_res(
            message_id=stream_id,
            content=answer,
            finish=True,
            timestamp=timestamp,
            nonce=nonce,
            cryptor=cryptor,
        )
        return Response(status=200, response=res, mimetype="application/json")

        logger.info(f'DECRYPTED PAYLOAD: {json.dumps(payload, ensure_ascii=False)[:500]}')
