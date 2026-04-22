import asyncio
import json
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger("AIAnswer.llm")


class LLMClient:
    """OpenAI 兼容格式的 SSE 流式 LLM 客户端。

    持续消费 ``trigger_queue`` 中的提问上下文，向远端大模型发起
    ``stream=true`` 请求，并将生成的 token 实时推入 ``output_queue``。
    """

    def __init__(
        self,
        trigger_queue: asyncio.Queue,
        output_queue: asyncio.Queue,
        api_base: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        system_prompt: str = "回答该提问，口语化并简短精炼",
        max_tokens: int = 150,
        temperature: float = 0.7,
    ):
        self.trigger_queue = trigger_queue
        self.output_queue = output_queue
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature

        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        self._running = True
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30, connect=10)
        )
        logger.info("LLMClient started (model=%s)", self.model)

        while self._running:
            try:
                payload = await asyncio.wait_for(self.trigger_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if not isinstance(payload, dict):
                continue

            context = payload.get("context", "")
            if not context:
                continue

            await self._chat(context)

    async def stop(self) -> None:
        self._running = False
        if self._session:
            await self._session.close()
        logger.info("LLMClient stopped")

    async def _chat(self, context: str) -> None:
        """发起一次 SSE 流式对话。"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": context},
            ],
            "stream": True,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        url = f"{self.api_base}/chat/completions"

        try:
            async with self._session.post(
                url, headers=headers, json=body
            ) as response:
                if response.status == 401:
                    logger.error("LLM API 401 Unauthorized — 请检查 API Key")
                    await self.output_queue.put("[错误: API Key 无效]")
                    return
                if response.status != 200:
                    text = await response.text()
                    logger.error("LLM API error %s: %s", response.status, text)
                    await self.output_queue.put(f"[错误: LLM 请求失败 {response.status}]")
                    return

                # 通知 UI 新回答开始
                await self.output_queue.put({"type": "answer_start"})

                async for line in response.content:
                    line = line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[len("data: "):]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    delta = (
                        chunk.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if delta:
                        await self.output_queue.put(
                            {"type": "answer_token", "content": delta}
                        )

                # 回答结束标记
                await self.output_queue.put({"type": "answer_end"})

        except asyncio.TimeoutError:
            logger.error("LLM request timeout")
            await self.output_queue.put("[错误: LLM 请求超时]")
        except Exception as exc:
            logger.error("LLM request exception: %s", exc)
            await self.output_queue.put(f"[错误: {exc}]")
