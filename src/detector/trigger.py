import asyncio
import logging
import time
from typing import Optional

from src.detector.buffer import TextBuffer

logger = logging.getLogger("AIAnswer.detector")


class TriggerDetector:
    """基于关键词匹配的提问检测器。

    持续消费 ASR 文本队列，当检测到疑似提问语句且超过冷却时间后，
    将上下文推入 ``trigger_queue`` 供 LLM 回答。
    """

    def __init__(
        self,
        text_queue: asyncio.Queue,
        trigger_queue: asyncio.Queue,
        triggers: Optional[list] = None,
        cooldown_seconds: float = 5.0,
    ):
        self.text_queue = text_queue
        self.trigger_queue = trigger_queue
        self.triggers = triggers or [
            "问个问题",
            "请一位同学",
            "谁来回答",
            "怎么看",
            "有什么想法",
            "思考一下",
            "对吗",
            "是不是",
            "请回答",
            "哪位同学",
            "你的观点",
            "如何理解",
            "怎么看待",
            "有什么见解",
            "举例说明",
            "举例来讲",
        ]
        self.cooldown_seconds = cooldown_seconds

        self._running = False
        self._buffer = TextBuffer()
        self._last_text = ""
        self._last_trigger_time = 0.0

    async def start(self) -> None:
        self._running = True
        logger.info(
            "TriggerDetector started (triggers=%d, cooldown=%.1fs)",
            len(self.triggers),
            self.cooldown_seconds,
        )
        while self._running:
            try:
                text = await asyncio.wait_for(self.text_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if not isinstance(text, str) or not text.strip():
                continue

            # 流式 ASR 可能在同一句话内多次推送相同或微小修正文本，
            # 与上次完全一致则跳过，避免重复检测。
            if text == self._last_text:
                continue
            self._last_text = text

            self._buffer.update(text)
            matched = self._detect(text)
            if matched:
                now = time.time()
                if now - self._last_trigger_time < self.cooldown_seconds:
                    logger.debug("Trigger '%s' hit but in cooldown", matched)
                    continue

                context = self._buffer.get_context(tail_sentences=2)
                if not context:
                    context = text

                payload = {
                    "type": "question_triggered",
                    "context": context,
                    "timestamp": now,
                    "matched_trigger": matched,
                }
                await self.trigger_queue.put(payload)
                self._last_trigger_time = now
                logger.info("Trigger hit: '%s' | context: %s", matched, context[:80])

    def stop(self) -> None:
        self._running = False
        logger.info("TriggerDetector stopped")

    def _detect(self, text: str) -> Optional[str]:
        """顺序检查触发词，返回首个命中的词，未命中返回 None。"""
        for trigger in self.triggers:
            if trigger in text:
                return trigger
        return None
