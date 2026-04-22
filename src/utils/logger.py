import logging
import sys
from pathlib import Path


def setup_logger(name: str = "AIAnswer", level: int = logging.INFO) -> logging.Logger:
    """配置并返回一个格式统一的 logger。"""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
