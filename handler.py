"""检测 LLM 内容审查/禁止内容错误并自动重启对话流的事件处理器。

当 Gemini 或其他 LLM 返回 PROHIBITED_CONTENT、prompt_blocked 等内容审查错误时，
自动重启对应的对话流以恢复服务。
"""

from __future__ import annotations

import time
from typing import Any

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BaseEventHandler
from src.core.components.types import EventType
from src.kernel.event import EventDecision
from src.kernel.llm.exceptions import LLMAPIError, LLMContentFilterError

logger = get_logger("content_filter_restart")

# Gemini API 内容审查错误关键词
_GEMINI_BLOCKED_KEYWORDS = frozenset({
    "prohibited_content",
    "prompt_blocked",
    "blocked by gemini api",
    "safety",
    "content_policy",
})

# 通用内容审查错误关键词
_CONTENT_FILTER_KEYWORDS = frozenset({
    "content_filter",
    "content policy",
    "violates",
    "safety guidelines",
    "inappropriate",
    "nsfw",
    "harmful",
    "unsafe",
})


def _is_content_filter_error(error: BaseException) -> bool:
    """判断错误是否为内容审查/禁止内容相关错误。"""

    if isinstance(error, LLMContentFilterError):
        return True

    if isinstance(error, LLMAPIError):
        error_msg = str(error).lower()
        # 检查 Gemini 特有的 blocked 错误
        if any(kw in error_msg for kw in _GEMINI_BLOCKED_KEYWORDS):
            return True
        # 检查通用内容审查关键词
        if error.status_code == 400 and any(
            kw in error_msg for kw in _CONTENT_FILTER_KEYWORDS
        ):
            return True

    return False


class ContentFilterRestartHandler(BaseEventHandler):
    """内容审查错误自动重启处理器。

    订阅 ON_LLM_REQUEST_FAILED 事件，检测到内容审查/禁止内容错误时
    自动重启对应的对话流。
    """

    name = "content_filter_restart_handler"
    description = "检测 LLM 内容审查错误并自动重启对话流"
    init_subscribe: list[EventType | str] = [EventType.ON_LLM_REQUEST_FAILED]

    def __init__(self, plugin: Any) -> None:
        super().__init__(plugin)
        # 每个流在冷却窗口内的最大重启次数
        self._max_restarts_per_window: int = 3
        # 冷却窗口（秒）
        self._cooldown_window: float = 300.0
        # 按流记录重启时间戳
        self._restart_counts: dict[str, list[float]] = {}

    def _check_cooldown(self, stream_id: str) -> bool:
        """检查流是否在重启冷却期内。返回 True 表示应跳过重启。"""

        now = time.monotonic()
        timestamps = self._restart_counts.get(stream_id, [])

        # 清理过期的时间戳
        timestamps = [t for t in timestamps if now - t < self._cooldown_window]
        self._restart_counts[stream_id] = timestamps

        if len(timestamps) >= self._max_restarts_per_window:
            logger.warning(
                f"流 {stream_id[:8]} 在冷却窗口内已重启 {len(timestamps)} 次，"
                f"跳过本次重启"
            )
            return True

        return False

    def _record_restart(self, stream_id: str) -> None:
        """记录一次重启事件。"""

        now = time.monotonic()
        self._restart_counts.setdefault(stream_id, []).append(now)

    async def execute(
        self, event_name: str, params: dict[str, Any]
    ) -> tuple[EventDecision, dict[str, Any]]:
        """处理 LLM 请求失败事件，检测内容审查错误并重启流。"""

        error = params.get("error")
        error_type = params.get("error_type", "")
        error_message = params.get("error_message", "")
        request_name = params.get("request_name", "")

        if not isinstance(error, BaseException) or not _is_content_filter_error(error):
            return EventDecision.SUCCESS, params

        # 获取 stream_id（存在 meta_data 中）
        meta_data = params.get("meta_data", {})
        stream_id = meta_data.get("stream_id", "") if isinstance(meta_data, dict) else ""
        if not stream_id:
            logger.debug(
                f"内容审查错误但无法获取 stream_id，跳过重启: "
                f"request={request_name}, error_type={error_type}"
            )
            return EventDecision.SUCCESS, params

        logger.warning(
            f"检测到内容审查错误，准备重启流: stream={stream_id[:8]}, "
            f"request={request_name}, model={params.get('model_identifier', '')}, "
            f"error_type={error_type}, message={error_message[:200]}"
        )

        # 冷却检查
        if self._check_cooldown(stream_id):
            return EventDecision.SUCCESS, params

        # 执行重启并清空上下文
        try:
            from src.app.plugin_system.api import stream_api
            from src.core.transport.distribution.stream_loop_manager import (
                get_stream_loop_manager,
            )

            manager = get_stream_loop_manager()
            success = await manager.restart_stream_loop(stream_id)

            if success:
                self._record_restart(stream_id)
                logger.info(
                    f"内容审查错误触发流重启成功: stream={stream_id[:8]}, "
                    f"request={request_name}"
                )
            else:
                logger.warning(
                    f"内容审查错误触发流重启失败（流可能未运行）: "
                    f"stream={stream_id[:8]}, request={request_name}"
                )

            # 清空上下文，避免残留的被审查内容再次触发
            cleared = await stream_api.load_and_clear_context(stream_id)
            if cleared:
                logger.info(
                    f"内容审查错误后清空上下文成功: stream={stream_id[:8]}"
                )
            else:
                logger.warning(
                    f"内容审查错误后清空上下文失败: stream={stream_id[:8]}"
                )
        except Exception as e:
            logger.error(
                f"内容审查错误触发流重启/清空上下文异常: stream={stream_id[:8]}, "
                f"request={request_name}, error={e}"
            )

        return EventDecision.SUCCESS, params


__all__ = ["ContentFilterRestartHandler"]
