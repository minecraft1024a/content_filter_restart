# content_filter_restart

LLM 内容审查错误自动重启插件。

## 功能

检测 LLM 请求失败事件中的内容审查/禁止内容错误，自动重启对应的对话流以恢复服务。

## 检测的错误类型

| 错误类型 | 匹配条件 | 典型来源 |
|---|---|---|
| `LLMContentFilterError` | 直接匹配 | OpenAI / Anthropic 内容过滤 |
| `LLMAPIError` (HTTP 400) | 消息包含 `prohibited_content`、`prompt_blocked`、`blocked by gemini api` 等关键词 | Gemini API |
| `LLMAPIError` (HTTP 400) | 消息包含 `content_filter`、`content policy`、`violates`、`nsfw` 等关键词 | 通用 |

## 典型错误日志

```
LLM 请求失败：model=gemini-3.5-flash-high, request=neo_default_chatter,
error_type=LLMAPIError, reason=Error code: 400 - {'error': {'message':
'request blocked by Gemini API: PROHIBITED_CONTENT', 'type': 'prompt_blocked'}}
```

## 工作原理

1. 订阅 `ON_LLM_REQUEST_FAILED` 事件
2. 判断错误是否为内容审查相关（见上表）
3. 通过 `stream.stream_id` 获取流 ID
4. 冷却检查：每个流 5 分钟窗口内最多重启 3 次
5. 调用 `StreamLoopManager.restart_stream_loop(stream_id)` 重启流

重启后：
- 旧的 stream loop task 被取消
- 旧的 chatter 生成器被销毁
- 新的 stream loop 启动，chatter 从头开始处理

## 冷却机制

| 参数 | 值 | 说明 |
|---|---|---|
| `_cooldown_window` | 300s (5 分钟) | 统计窗口 |
| `_max_restarts_per_window` | 3 | 窗口内最大重启次数 |

超过阈值后跳过重启并记录 warning 日志，防止无限循环。

## 安装

将 `content_filter_restart` 目录放入 Neo-MoFox 的 `plugins/` 目录下，重启 bot 即可。

```
plugins/
  content_filter_restart/
    __init__.py
    handler.py
    manifest.json
    plugin.py
```

## 配置

无需额外配置，插件即装即用。
