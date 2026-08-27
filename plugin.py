"""Content Filter Restart 插件——检测 LLM 内容审查错误并自动重启对话流。"""

from __future__ import annotations

from typing import cast

from src.app.plugin_system.api.log_api import get_logger
from src.app.plugin_system.base import BasePlugin, register_plugin

from .handler import ContentFilterRestartHandler

logger = get_logger("content_filter_restart")


@register_plugin
class ContentFilterRestartPlugin(BasePlugin):
    """内容审查错误自动重启插件。

    订阅 ON_LLM_REQUEST_FAILED 事件，当检测到 Gemini PROHIBITED_CONTENT、
    prompt_blocked 或其他内容审查相关错误时，自动重启对应的对话流。
    """

    plugin_name = "content_filter_restart"
    configs: list[type] = []
    dependent_components: list[str] = []

    def get_components(self) -> list[type]:
        return [ContentFilterRestartHandler]
