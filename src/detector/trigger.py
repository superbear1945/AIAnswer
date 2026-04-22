import asyncio
import logging
import time
from typing import Optional

from src.detector.buffer import TextBuffer

logger = logging.getLogger("AIAnswer.detector")


class TriggerDetector:
    """基于关键词匹配的提问检测器。

    持续消费 ASR 文本队列，当检测到疑似提问语句且超过冷却时间后，
    等待一段收集时间让提问者说完实际内容，再将完整上下文推入
    ``trigger_queue`` 供 LLM 回答。
    """

    def __init__(
        self,
        text_queue: asyncio.Queue,
        trigger_queue: asyncio.Queue,
        triggers: Optional[list] = None,
        cooldown_seconds: float = 5.0,
        wait_seconds: float = 3.0,
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
        self.wait_seconds = wait_seconds

        self._running = False
        self._buffer = TextBuffer()
        self._last_text = ""
        self._last_trigger_time = 0.0
        self._collect_task: Optional[asyncio.Task] = None
        self._pending_trigger: Optional[str] = None

    async def start(self) -> None:
        self._running = True
        logger.info(
            "TriggerDetector started (triggers=%d, cooldown=%.1fs, wait=%.1fs)",
            len(self.triggers),
            self.cooldown_seconds,
            self.wait_seconds,
        )
        while self._running:
            try:
                text = await asyncio.wait_for(self.text_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if not isinstance(text, str) or not text.strip():
                continue

            if text == self._last_text:
                continue
            self._last_text = text

            self._buffer.update(text)
            matched = self._detect(text)

            if self._collect_task is not None:
                if matched and not self._is_same_trigger(matched):
                    self._collect_task.cancel()
                    self._collect_task = None
                    self._pending_trigger = None
                    self._start_collect(matched)
                else:
                    continue
                continue

            if matched:
                now = time.time()
                if now - self._last_trigger_time < self.cooldown_seconds:
                    logger.debug("Trigger '%s' hit but in cooldown", matched)
                    continue
                self._start_collect(matched)

    def _is_same_trigger(self, matched: str) -> bool:
        if self._pending_trigger is None:
            return False
        return matched == self._pending_trigger

    def _start_collect(self, matched: str) -> None:
        self._pending_trigger = matched
        self._collect_task = asyncio.create_task(self._collect_and_send(matched))
        logger.info(
            "Trigger detected: '%s', waiting %.1fs for question content...",
            matched,
            self.wait_seconds,
        )

    async def _collect_and_send(self, matched: str) -> None:
        try:
            await asyncio.sleep(self.wait_seconds)
        except asyncio.CancelledError:
            logger.debug("Collect cancelled for trigger '%s'", matched)
            return

        context = self._buffer.get_context(tail_sentences=2)
        if not context:
            logger.warning("No context after wait for trigger '%s'", matched)
            self._collect_task = None
            self._pending_trigger = None
            return

        payload = {
            "type": "question_triggered",
            "context": context,
            "timestamp": time.time(),
            "matched_trigger": matched,
        }
        await self.trigger_queue.put(payload)
        self._last_trigger_time = time.time()
        logger.info("Trigger fired: '%s' | context: %s", matched, context[:80])
        self._collect_task = None
        self._pending_trigger = None

    def stop(self) -> None:
        self._running = False
        if self._collect_task is not None:
            self._collect_task.cancel()
            self._collect_task = None
            self._pending_trigger = None
        logger.info("TriggerDetector stopped")

    def _detect(self, text: str) -> Optional[str]:
        """顺序检查触发词，返回首个命中的词，未命中返回 None。"""
        for trigger in self.triggers:
            if trigger in text:
                return trigger
        return None
