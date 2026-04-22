import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("AIAnswer.asr")


class BaseASR(ABC):
    """语音识别抽象基类。

    所有 ASR 实现必须提供 ``start()`` 和 ``stop()`` 协程，
    并在识别到新文本时将其推入 ``text_queue``（供提问检测使用）
    以及可选的 ``ui_queue``（供界面实时展示字幕）。
    """

    def __init__(
        self,
        audio_queue: asyncio.Queue,
        text_queue: asyncio.Queue,
        sample_rate: int = 16000,
        ui_queue: Optional[asyncio.Queue] = None,
    ):
        self.audio_queue = audio_queue
        self.text_queue = text_queue
        self.ui_queue = ui_queue
        self.sample_rate = sample_rate
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """启动识别循环。"""

    @abstractmethod
    async def stop(self) -> None:
        """停止识别并释放资源。"""
