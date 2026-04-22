import asyncio
import logging
import queue
import sys
import threading
import time
from pathlib import Path

# 将 src 加入模块搜索路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from tkinter import messagebox

from audio.capture import AudioCapture
from asr.http_asr import HttpSegmentASR
from asr.xunfei_ws import StreamingASR
from config.manager import ConfigManager
from detector.trigger import TriggerDetector
from llm.client import LLMClient
from ui.app import MainWindow, SettingsDialog
from utils.logger import setup_logger

logger = setup_logger("AIAnswer.main")


class AppController:
    def __init__(self):
        self.config = ConfigManager()
        self._finish_event = threading.Event()
        self.ui = MainWindow(
            on_start=self.on_start,
            on_stop=self.on_stop,
            on_settings=self.on_settings,
            on_finish_question=self.on_finish_question,
        )
        self._async_loop: asyncio.AbstractEventLoop = None
        self._async_thread: threading.Thread = None
        self._tk_queue: queue.Queue = queue.Queue()

        # 运行时引用（用于停止）
        self._audio_capture = None
        self._asr = None
        self._detector = None
        self._llm = None
        self._running = False

    # ------------------------------------------------------------------ #
    # 公共入口
    # ------------------------------------------------------------------ #
    def run(self):
        self.ui.run()

    # ------------------------------------------------------------------ #
    # 设置对话框
    # ------------------------------------------------------------------ #
    def on_settings(self):
        def save_handler(new_cfg):
            for section, values in new_cfg.items():
                for k, v in values.items():
                    self.config.set(f"{section}.{k}", v)
            logger.info("Configuration saved")

        SettingsDialog(self.ui.root, self.config, save_handler)

    # ------------------------------------------------------------------ #
    # 结束提问按钮回调
    # ------------------------------------------------------------------ #
    def on_finish_question(self):
        if self._detector:
            self._detector.confirm_and_send()

    # ------------------------------------------------------------------ #
    # 开始听课
    # ------------------------------------------------------------------ #
    def on_start(self):
        if self._running:
            return
        if not self._check_config():
            return

        self._running = True
        self._finish_event.clear()
        self.ui.set_running(True)
        self.ui.set_status("正在启动...")

        self._async_thread = threading.Thread(target=self._async_main, daemon=True)
        self._async_thread.start()

    def _check_config(self) -> bool:
        missing = []
        provider = self.config.get("asr.provider", "xunfei")
        if provider == "xunfei":
            if not self.config.get("asr.app_id"):
                missing.append("讯飞 ASR APPID")
            if not self.config.get("asr.api_key"):
                missing.append("讯飞 ASR APIKey")
            if not self.config.get("asr.api_secret"):
                missing.append("讯飞 ASR APISecret")
        elif provider == "http_asr":
            if not self.config.get("asr.api_base"):
                missing.append("ASR API Base")
            if not self.config.get("asr.model"):
                missing.append("ASR Model")
        if not self.config.get("llm.api_key"):
            missing.append("LLM API Key")

        if missing:
            msg = "以下配置项未填写，请先点击「设置」完成配置：\n\n" + "\n".join(
                missing
            )
            messagebox.showerror("配置不完整", msg)
            return False
        return True

    # ------------------------------------------------------------------ #
    # asyncio 后台线程
    # ------------------------------------------------------------------ #
    def _async_main(self):
        self._async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._async_loop)
        try:
            self._async_loop.run_until_complete(self._pipeline())
        except Exception as exc:
            logger.exception("Async pipeline crashed")
            self._tk_queue.put({"type": "error", "message": str(exc)})
        finally:
            self._running = False
            self._tk_queue.put({"type": "status", "content": "已停止"})

    async def _pipeline(self):
        audio_q = asyncio.Queue(maxsize=50)
        asr_text_q = asyncio.Queue(maxsize=100)
        asr_ui_q = asyncio.Queue(maxsize=100)
        trigger_q = asyncio.Queue(maxsize=10)
        llm_output_q = asyncio.Queue(maxsize=100)
        notify_q = asyncio.Queue(maxsize=10)

        self._audio_capture = AudioCapture(
            queue=audio_q,
            sample_rate=self.config.get("audio.sample_rate", 16000),
            chunk_duration_ms=self.config.get("audio.chunk_duration_ms", 200),
            device_index=self.config.get("audio.device_index"),
        )

        provider = self.config.get("asr.provider", "xunfei")
        if provider == "http_asr":
            self._asr = HttpSegmentASR(
                audio_queue=audio_q,
                text_queue=asr_text_q,
                ui_queue=asr_ui_q,
                api_base=self.config.get("asr.api_base", "https://api.openai.com/v1"),
                api_key=self.config.get("asr.api_key", ""),
                model=self.config.get("asr.model", "whisper-1"),
                language=self.config.get("asr.language", "zh"),
                segment_duration_ms=self.config.get("asr.segment_duration_ms", 1500),
                sample_rate=self.config.get("audio.sample_rate", 16000),
            )
        else:
            self._asr = StreamingASR(
                audio_queue=audio_q,
                text_queue=asr_text_q,
                ui_queue=asr_ui_q,
                app_id=self.config.get("asr.app_id"),
                api_key=self.config.get("asr.api_key"),
                api_secret=self.config.get("asr.api_secret"),
                sample_rate=self.config.get("audio.sample_rate", 16000),
            )
        self._detector = TriggerDetector(
            text_queue=asr_text_q,
            trigger_queue=trigger_q,
            notify_queue=notify_q,
            finish_event=self._finish_event,
            triggers=self.config.get("detector.triggers"),
            cooldown_seconds=self.config.get("detector.cooldown_seconds", 5.0),
        )
        self._llm = LLMClient(
            trigger_queue=trigger_q,
            output_queue=llm_output_q,
            api_base=self.config.get("llm.api_base", "https://api.openai.com/v1"),
            api_key=self.config.get("llm.api_key"),
            model=self.config.get("llm.model", "gpt-4o-mini"),
            system_prompt=self.config.get(
                "llm.system_prompt", "回答该提问，口语化并简短精炼"
            ),
            max_tokens=self.config.get("llm.max_tokens", 150),
            temperature=self.config.get("llm.temperature", 0.7),
        )

        # 桥接：把 asyncio 侧的队列数据搬运到 tkinter 队列
        async def bridge():
            while self._running:
                # LLM 输出（高优先级）
                try:
                    msg = llm_output_q.get_nowait()
                    self._tk_queue.put(msg)
                    continue
                except asyncio.QueueEmpty:
                    pass

                # 检测器通知（提问检测/发送确认）
                try:
                    msg = notify_q.get_nowait()
                    self._tk_queue.put(msg)
                    continue
                except asyncio.QueueEmpty:
                    pass

                # ASR 字幕文本
                try:
                    text = asr_ui_q.get_nowait()
                    self._tk_queue.put({"type": "asr_text", "content": text})
                    continue
                except asyncio.QueueEmpty:
                    pass

                await asyncio.sleep(0.05)

        tasks = [
            asyncio.create_task(self._audio_capture.start()),
            asyncio.create_task(self._asr.start()),
            asyncio.create_task(self._detector.start()),
            asyncio.create_task(self._llm.start()),
            asyncio.create_task(bridge()),
        ]

        self._tk_queue.put({"type": "status", "content": "运行中 | 正在监听..."})

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            if t.cancelled():
                continue
            exc = t.exception()
            if exc and not isinstance(exc, asyncio.CancelledError):
                logger.error("Task failed: %s", exc)
                self._tk_queue.put({"type": "error", "message": str(exc)})

    # ------------------------------------------------------------------ #
    # 停止听课
    # ------------------------------------------------------------------ #
    def on_stop(self):
        if not self._running:
            return
        self._running = False
        self.ui.set_status("正在停止...")

        if self._async_loop and self._async_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._do_stop(), self._async_loop)
            try:
                future.result(timeout=5)
            except Exception as exc:
                logger.error("Stop timeout/error: %s", exc)

        if self._async_thread and self._async_thread.is_alive():
            self._async_thread.join(timeout=3)

        self.ui.set_running(False)
        self.ui.set_status("已停止")

    async def _do_stop(self):
        if self._audio_capture:
            await self._audio_capture.stop()
        if self._asr:
            await self._asr.stop()
        if self._detector:
            self._detector.stop()
        if self._llm:
            await self._llm.stop()

    # ------------------------------------------------------------------ #
    # UI 队列桥接（由 AppController 主动轮询并推给 UI）
    # ------------------------------------------------------------------ #
    def poll_and_dispatch(self):
        """应在 tkinter 主线程中定期调用（如每 100ms）。"""
        try:
            while True:
                msg = self._tk_queue.get_nowait()
                self.ui.ui_queue.put(msg)
        except queue.Empty:
            pass


def main():
    controller = AppController()

    # 在 tkinter 的 idle 循环中定期把后台 asyncio 的队列数据搬运到 UI
    def _poll():
        controller.poll_and_dispatch()
        controller.ui.root.after(100, _poll)

    controller.ui.root.after(100, _poll)
    controller.run()


if __name__ == "__main__":
    main()
