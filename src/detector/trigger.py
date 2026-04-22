import asyncio
import logging
import threading
import time
from typing import Optional

from src.detector.buffer import TextBuffer

logger = logging.getLogger("AIAnswer.detector")


class TriggerDetector:
    """基于关键词匹配的提问检测器（手动确认模式）。

    持续消费 ASR 文本队列。当检测到触发词后进入收集阶段，
    通过 notify_queue 通知 UI 提示用户。用户按下「结束提问」
    按钮后设置 finish_event，检测器从触发词位置截取到当前
    文本末尾作为完整上下文，推入 trigger_queue 供 LLM 回答。
    """

    def __init__(
        self,
        text_queue: asyncio.Queue,
        trigger_queue: asyncio.Queue,
        notify_queue: asyncio.Queue,
        finish_event: threading.Event,
        triggers: Optional[list] = None,
        cooldown_seconds: float = 5.0,
    ):
        self.text_queue = text_queue
        self.trigger_queue = trigger_queue
        self.notify_queue = notify_queue
        self.finish_event = finish_event
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
        self._current_trigger: Optional[str] = None
        self._collecting = False

    async def start(self) -> None:
        self._running = True
        logger.info(
            "TriggerDetector started (triggers=%d, cooldown=%.1fs, mode=manual_confirm)",
            len(self.triggers),
            self.cooldown_seconds,
        )
        while self._running:
            # 收集阶段：检查用户是否按下「结束提问」
            if self._collecting:
                if self.finish_event.is_set():
                    self.finish_event.clear()
                    await self._flush_on_confirm()
                    continue

            # 获取下一条 ASR 文本
            try:
                text = await asyncio.wait_for(self.text_queue.get(), timeout=0.3)
            except asyncio.TimeoutError:
                continue

            if not isinstance(text, str) or not text.strip():
                continue

            if text == self._last_text:
                continue
            self._last_text = text

            self._buffer.update(text)
            matched = self._detect(text)

            if self._collecting:
                # 收集中：检查是否出现不同触发词，切换为新触发词
                if matched and matched != self._current_trigger:
                    now = time.time()
                    if now - self._last_trigger_time >= self.cooldown_seconds:
                        self._current_trigger = matched
                        self._last_trigger_time = now
                        logger.info("New trigger while collecting: '%s'", matched)
                        await self.notify_queue.put(
                            {"type": "question_detected", "trigger": matched}
                        )
                continue

            # 空闲状态：检测触发词
            if matched:
                now = time.time()
                if now - self._last_trigger_time < self.cooldown_seconds:
                    logger.debug("Trigger '%s' hit but in cooldown", matched)
                    continue
                self._collecting = True
                self._current_trigger = matched
                self._last_trigger_time = now
                logger.info(
                    "Trigger detected: '%s', waiting for user confirm...", matched
                )
                await self.notify_queue.put(
                    {"type": "question_detected", "trigger": matched}
                )

    async def _flush_on_confirm(self) -> None:
        """用户确认后，从 buffer 提取完整上下文并发送给 LLM。"""
        if not self._collecting or not self._current_trigger:
            return

        trigger = self._current_trigger
        context = self._buffer.get_context_from_trigger(trigger)
        if not context:
            logger.warning("No context after confirm for trigger '%s'", trigger)
            self._collecting = False
            self._current_trigger = None
            await self.notify_queue.put({"type": "question_sent"})
            return

        payload = {
            "type": "question_triggered",
            "context": context,
            "timestamp": time.time(),
            "matched_trigger": trigger,
        }
        await self.trigger_queue.put(payload)
        logger.info(
            "Trigger fired (manual confirm): '%s' | context: %s",
            trigger,
            context[:80],
        )
        self._collecting = False
        self._current_trigger = None
        await self.notify_queue.put({"type": "question_sent"})

    def confirm_and_send(self) -> None:
        """由 UI 线程调用：用户按下「结束提问」按钮时设置事件。"""
        self.finish_event.set()

    def cancel_collect(self) -> None:
        """由 UI 线程调用：取消当前收集状态（如回退到空闲）。"""
        self._collecting = False
        self._current_trigger = None
        self.finish_event.set()
        logger.info("Collect cancelled by user")

    def stop(self) -> None:
        self._running = False
        self._collecting = False
        self._current_trigger = None
        logger.info("TriggerDetector stopped")

    def _detect(self, text: str) -> Optional[str]:
        """顺序检查触发词，返回首个命中的词，未命中返回 None。"""
        for trigger in self.triggers:
            if trigger in text:
                return trigger
        return None
