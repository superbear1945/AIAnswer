import asyncio
import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import websockets

from src.asr.base import BaseASR

logger = logging.getLogger("AIAnswer.asr")


class StreamingASR(BaseASR):
    """讯飞语音听写（流式版）WebSocket 客户端。

    持续从 ``audio_queue`` 读取 PCM 音频 chunk，通过 WebSocket 实时发送至
    讯飞服务端，并将识别文本更新推送至 ``text_queue``。

    采用 ``dwa: wpgs`` 开启动态修正，服务端会在识别过程中对前文进行局部
    修正（``pgs=rpl``）。本实现每次直接按服务端返回的最新词列表重建当前
    句子文本，逻辑简洁且不易因索引错位导致乱码。
    """

    def __init__(
        self,
        audio_queue: asyncio.Queue,
        text_queue: asyncio.Queue,
        app_id: str,
        api_key: str,
        api_secret: str,
        sample_rate: int = 16000,
        ui_queue: Optional[asyncio.Queue] = None,
    ):
        super().__init__(audio_queue, text_queue, sample_rate, ui_queue)
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._last_text = ""

    # ------------------------------------------------------------------ #
    # 鉴权 URL 生成（RFC 1123 + HMAC-SHA256）
    # ------------------------------------------------------------------ #
    def _generate_url(self) -> str:
        host = "iat-api.xfyun.cn"
        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        signature_origin = f"host: {host}\ndate: {date}\nGET /v2/iat HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature_sha_base64 = base64.b64encode(signature_sha).decode("utf-8")

        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", '
            f'signature="{signature_sha_base64}"'
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode(
            "utf-8"
        )

        return (
            f"wss://{host}/v2/iat?"
            f"authorization={authorization}&"
            f"date={quote(date, safe='')}&"
            f"host={host}"
        )

    # ------------------------------------------------------------------ #
    # 帧构造
    # ------------------------------------------------------------------ #
    def _build_frame(self, audio_bytes: bytes, status: int) -> str:
        payload = {
            "common": {"app_id": self.app_id},
            "business": {
                "language": "zh_cn",
                "domain": "iat",
                "accent": "mandarin",
                "vad_eos": 3000,   # 3秒静音视为句子结束
                "dwa": "wpgs",     # 开启动态修正
            },
            "data": {
                "status": status,
                "format": f"audio/L16;rate={self.sample_rate}",
                "encoding": "raw",
                "audio": base64.b64encode(audio_bytes).decode("utf-8"),
            },
        }
        return json.dumps(payload)

    # ------------------------------------------------------------------ #
    # 消息解析与发布
    # ------------------------------------------------------------------ #
    def _parse_and_publish(self, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        code = data.get("code", -1)
        if code != 0:
            logger.warning("ASR error response: %s", data.get("message"))
            return

        result = data.get("data", {}).get("result", {})
        ws = result.get("ws", [])
        if not ws:
            return

        # 直接按服务端返回的词列表重建当前文本
        words = [item["cw"][0]["w"] for item in ws]
        text = "".join(words)

        if text and text != self._last_text:
            self._last_text = text
            # 使用 create_task 非阻塞推送；queue 本身有容量缓冲
            asyncio.create_task(self.text_queue.put(text))
            if self.ui_queue is not None:
                asyncio.create_task(self.ui_queue.put(text))
            logger.debug("ASR text update: %s", text)

    # ------------------------------------------------------------------ #
    # 核心协程
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        self._running = True
        url = self._generate_url()
        logger.info("Connecting to Xunfei ASR...")

        try:
            self._ws = await websockets.connect(url, ping_interval=20, ping_timeout=10)
        except Exception as exc:
            raise ConnectionError(f"无法连接讯飞 ASR: {exc}") from exc

        logger.info("Xunfei ASR connected")

        sender_task = asyncio.create_task(self._sender())
        receiver_task = asyncio.create_task(self._receiver())

        done, pending = await asyncio.wait(
            [sender_task, receiver_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
        for task in done:
            if task.exception():
                logger.error("ASR task exception: %s", task.exception())

    async def stop(self) -> None:
        self._running = False
        if self._ws and self._ws.open:
            # 发送空结束帧，通知服务端音频结束
            try:
                await self._ws.send(self._build_frame(b"", status=2))
                await asyncio.sleep(0.5)
                await self._ws.close()
            except Exception as exc:
                logger.warning("Error closing ASR websocket: %s", exc)
        logger.info("Xunfei ASR stopped")

    async def _sender(self) -> None:
        first = True
        while self._running:
            try:
                chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            status = 0 if first else 1
            first = False

            try:
                await self._ws.send(self._build_frame(chunk, status))
            except Exception as exc:
                logger.error("ASR send error: %s", exc)
                break

        # 退出循环后发送结束帧
        if self._ws and self._ws.open:
            try:
                await self._ws.send(self._build_frame(b"", status=2))
            except Exception as exc:
                logger.warning("ASR final send error: %s", exc)

    async def _receiver(self) -> None:
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                self._parse_and_publish(message)
        except websockets.ConnectionClosed:
            logger.info("ASR websocket closed by server")
        except Exception as exc:
            logger.error("ASR receiver error: %s", exc)
