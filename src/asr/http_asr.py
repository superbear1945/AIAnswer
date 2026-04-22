import asyncio
import io
import logging
import struct
from typing import Optional

import aiohttp

from src.asr.base import BaseASR

logger = logging.getLogger("AIAnswer.asr")


def _build_wav_header(data_len: int, sample_rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    """构造标准 WAV 文件头（PCM）。"""
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_len,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits,
        b"data",
        data_len,
    )
    return header


class HttpSegmentASR(BaseASR):
    """基于 HTTP 的通用分段语音识别客户端。

    兼容 OpenAI ``/v1/audio/transcriptions`` 接口，也兼容任何
    提供同类接口的云端或自建语音转写服务。

    工作原理：
    1. 持续从 ``audio_queue`` 读取音频 chunk，累积到本地 buffer。
    2. 每 ``segment_duration_ms``（默认 1500ms）将 buffer 打包为 WAV 文件，
       通过 HTTP POST 发送给识别服务。
    3. 收到返回文本后，推入 ``text_queue`` 与 ``ui_queue``。

    注意：这种方式相比 WebSocket 流式会有约 1~3 秒额外延迟，
    但胜在兼容面广，任何提供 HTTP API 的开源/第三方 ASR 都能接入。
    """

    def __init__(
        self,
        audio_queue: asyncio.Queue,
        text_queue: asyncio.Queue,
        api_base: str,
        api_key: str,
        model: str = "whisper-1",
        language: str = "zh",
        segment_duration_ms: int = 1500,
        sample_rate: int = 16000,
        ui_queue: Optional[asyncio.Queue] = None,
    ):
        super().__init__(audio_queue, text_queue, sample_rate, ui_queue)
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.language = language
        self.segment_duration_ms = segment_duration_ms
        self._session: Optional[aiohttp.ClientSession] = None
        self._transcribe_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._running = True
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30, connect=10)
        )
        logger.info(
            "HttpSegmentASR started (base=%s, model=%s, segment=%dms)",
            self.api_base,
            self.model,
            self.segment_duration_ms,
        )
        await self._collector()

    async def stop(self) -> None:
        self._running = False
        await self._cancel_transcribe_tasks()
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("HttpSegmentASR stopped")

    def _create_transcribe_task(self, audio_data: bytes) -> None:
        task = asyncio.create_task(self._transcribe(audio_data))
        self._transcribe_tasks.add(task)
        task.add_done_callback(self._transcribe_tasks.discard)

    async def _cancel_transcribe_tasks(self) -> None:
        if not self._transcribe_tasks:
            return

        tasks = list(self._transcribe_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._transcribe_tasks.clear()

    # ------------------------------------------------------------------ #
    # 内部协程
    # ------------------------------------------------------------------ #
    async def _collector(self) -> None:
        """音频收集与定时发送循环。"""
        buffer = bytearray()
        bytes_per_ms = self.sample_rate * 2 // 1000  # 16bit mono
        threshold = bytes_per_ms * self.segment_duration_ms
        last_send_time = asyncio.get_event_loop().time()

        while self._running:
            try:
                chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=0.2)
                buffer.extend(chunk)
            except asyncio.TimeoutError:
                pass

            now = asyncio.get_event_loop().time()
            elapsed_ms = (now - last_send_time) * 1000

            # 满足长度阈值 或 超过最大间隔（有数据时）
            if len(buffer) >= threshold or (buffer and elapsed_ms >= self.segment_duration_ms):
                audio_data = bytes(buffer)
                buffer.clear()
                last_send_time = now
                # 在后台并发识别，不阻塞采集
                self._create_transcribe_task(audio_data)

        # 停止后，发送剩余音频
        if buffer:
            await self._transcribe(bytes(buffer))

    async def _transcribe(self, audio_bytes: bytes) -> None:
        """将一段音频发送给 HTTP API 并处理返回。"""
        if not audio_bytes:
            return

        try:
            wav = io.BytesIO()
            wav.write(_build_wav_header(len(audio_bytes), self.sample_rate))
            wav.write(audio_bytes)
            wav.seek(0)

            url = f"{self.api_base}/audio/transcriptions"
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            data = aiohttp.FormData()
            data.add_field("file", wav, filename="audio.wav", content_type="audio/wav")
            data.add_field("model", self.model)
            data.add_field("language", self.language)
            data.add_field("response_format", "json")

            async with self._session.post(url, headers=headers, data=data) as resp:
                if resp.status == 401:
                    logger.error("ASR HTTP 401 — API Key 无效")
                    return
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("ASR HTTP %s: %s", resp.status, text)
                    return

                result = await resp.json()
                text = result.get("text", "")
                if text:
                    await self.text_queue.put(text)
                    if self.ui_queue is not None:
                        await self.ui_queue.put(text)
                    logger.debug("HttpSegmentASR text: %s", text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("HttpSegmentASR request error: %s", exc)
