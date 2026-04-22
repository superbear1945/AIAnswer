import asyncio
import logging
import threading
from typing import Optional

import pyaudio

logger = logging.getLogger("AIAnswer.audio")


class AudioCapture:
    """基于 pyaudio 的异步麦克风音频采集器。

    在独立后台线程中读取音频 chunk，通过 ``asyncio.Queue`` 推送给下游。
    由于 pyaudio 的 ``read()`` 是阻塞调用，我们将其放在 daemon 线程中运行，
    并通过 ``asyncio.run_coroutine_threadsafe`` 把数据送回 asyncio 事件循环。
    """

    FORMAT = pyaudio.paInt16
    CHANNELS = 1

    def __init__(
        self,
        queue: asyncio.Queue,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 200,
        device_index: Optional[int] = None,
    ):
        self.queue = queue
        self.sample_rate = sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self.device_index = device_index
        # 16bit = 2 bytes, mono = 1 channel
        self.chunk_size = int(sample_rate * 2 * chunk_duration_ms / 1000)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._capture_error: Optional[Exception] = None

    def _capture_loop(self) -> None:
        while self._running:
            try:
                data = self._stream.read(self.chunk_size, exception_on_overflow=False)
            except Exception as exc:
                if self._running:
                    logger.error("Audio read error: %s", exc)
                    self._capture_error = exc
                    self._running = False
                break

            # 将阻塞线程读到的数据推回 asyncio 队列
            try:
                asyncio.run_coroutine_threadsafe(
                    self.queue.put(data), self._loop
                ).result(timeout=1)
            except Exception:
                # 队列满或事件循环已关闭则静默丢弃，避免阻塞采集线程
                pass

    async def start(self) -> None:
        self._running = True
        self._capture_error = None
        self._loop = asyncio.get_running_loop()
        self._pa = pyaudio.PyAudio()

        try:
            self._stream = self._pa.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size,
            )
        except Exception as exc:
            self._pa.terminate()
            raise RuntimeError(f"无法打开麦克风: {exc}") from exc

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info(
            "AudioCapture started (rate=%d, chunk=%d bytes, device=%s)",
            self.sample_rate,
            self.chunk_size,
            self.device_index,
        )

        while self._running:
            await asyncio.sleep(0.1)

        if self._capture_error is not None:
            raise RuntimeError(f"麦克风采集中断: {self._capture_error}") from self._capture_error

    async def stop(self) -> None:
        self._running = False
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as exc:
                logger.warning("Error closing audio stream: %s", exc)
            finally:
                self._stream = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._pa:
            self._pa.terminate()
            self._pa = None
        logger.info("AudioCapture stopped")

    @staticmethod
    def list_devices() -> list[dict]:
        pa = pyaudio.PyAudio()
        devices = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append(
                    {
                        "index": i,
                        "name": info.get("name"),
                        "channels": info.get("maxInputChannels"),
                        "sample_rate": int(info.get("defaultSampleRate", 16000)),
                    }
                )
        pa.terminate()
        return devices
