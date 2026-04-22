import re
import time
from typing import Optional


class TextBuffer:
    """轻量级文本滑动窗口。

    仅保存最近一次 ASR 返回的完整文本（流式识别中的当前句子）。
    由于流式 ASR 会持续修正前文，历史中间版本不具备参考价值，
    因此只保留最终/最新版本即可。
    """

    def __init__(self, max_age_seconds: float = 60.0):
        self.max_age = max_age_seconds
        self._text: str = ""
        self._timestamp: float = 0.0

    def update(self, text: str) -> None:
        self._text = text
        self._timestamp = time.time()

    def get_text(self) -> str:
        if time.time() - self._timestamp > self.max_age:
            return ""
        return self._text

    def get_context(self, tail_sentences: int = 2) -> str:
        """按标点分句，返回末尾 *tail_sentences* 句作为上下文。"""
        text = self.get_text()
        if not text:
            return ""
        parts = re.split(r"([。！？.!?])", text)
        sentences = []
        i = 0
        while i < len(parts):
            if i + 1 < len(parts) and parts[i + 1] in "。！？.!？":
                sentences.append(parts[i] + parts[i + 1])
                i += 2
            else:
                if parts[i].strip():
                    sentences.append(parts[i])
                i += 1
        if not sentences:
            return text
        return "".join(sentences[-tail_sentences:])

    def get_context_from_trigger(self, trigger: str) -> str:
        """从触发词出现位置开始，截取到文本末尾作为完整提问上下文。

        如果触发词在文本中多次出现，取最后（最右）一次的位置。
        如果触发词不在当前文本中（流式修正导致消失），回退返回全部文本。
        如果文本为空或已过期，返回空字符串。
        """
        text = self.get_text()
        if not text:
            return ""
        idx = text.rfind(trigger)
        if idx < 0:
            return text
        return text[idx:]

    def clear(self) -> None:
        self._text = ""
        self._timestamp = 0.0
