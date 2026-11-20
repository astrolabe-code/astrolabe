#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★★ AI 内核（纯能力，零 HTTP、零路由）。

所有者原话（2026-11-20）：「建一个ai内核的目录吧，现在这个内核与其他功能
混在一起，太乱了。」

## 模块划分

| 模块 | 职责 |
|---|---|
| `prompts.py` | 五个 system 提示词（BASE / ASK / COMPLETE / TITLE / QUESTIONS） |
| `client.py` | OpenAI 兼容客户端：配置、redact、stream_chat、chat_with_tools、取消令牌 |
| `tools.py` | 暴露给模型的只读工具（cypher / read_file / read_board / read_notes / search_notes）+ 执行器 |
| `events.py` | 问答 / 出题的流式事件生成器 |
| `context.py` | 运行时上下文（ROOT / CONN，由 main 注入，避免反向依赖） |
| `log.py` | 诊断日志（写 stderr，不污染 stdout 的 JSON 协议） |

## 边界

· 内核**不碰** HTTP 路由、不做响应序列化、不写图库。
· `main.py` 只负责「把请求转成对内核的调用，把事件写回 stdout」。
· 改 AI 行为只进这个目录，不用去 2500 行的 main.py 里翻。

## 依赖方向（单向，无环）

```
main.py ──> ai_core.events ──> ai_core.tools ──> ai_core.client ──> ai_core.prompts
   │              │                  │
   └──────────────┴──────────────────┴──> ai_core.log
```
"""

from ai_core.client import (  # noqa: F401
    BASE_SYSTEM,
    CancelledError,
    QUESTIONS_SYSTEM,
    active,
    cancel_token,
    chat_once,
    chat_with_tools,
    new_cancel_token,
    stream_chat,
)
from ai_core.events import _ask_events  # noqa: F401
from ai_core.tools import READ_TOOLS  # noqa: F401

__all__ = [
    'READ_TOOLS',
    'BASE_SYSTEM',
    'QUESTIONS_SYSTEM',
    'CancelledError',
    'active',
    'cancel_token',
    'chat_once',
    'chat_with_tools',
    'new_cancel_token',
    'stream_chat',
    '_ask_events',
]
