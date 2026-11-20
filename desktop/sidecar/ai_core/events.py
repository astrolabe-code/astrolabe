#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 事件生成器（问答的流式事件流）。

从 main.py 抽出 —— 这里只管「把一次 AI 请求变成一串事件」，
⛔ 不管 HTTP 响应怎么写、不管进程主循环。

⚠ 出题走的是同一个 _ask_events，只是 system 参数不同 ——
  曾经的专用出题事件流已删除（2026-11-20）。
"""


import ai_core.client as ai
import graphdb
from ai_core import context
from ai_core.log import _log



def _ask_events(project, vid: int, question: str, system: str = "ask"):
    """针对当前节点提问（流式）。

    ★ 上下文与草稿**逐字相同** ⇒ 先跑过草稿的项目再问，能命中前缀缓存。
    ⛔ 不缓存回答：问题的组合太多，缓存命中率极低，存了只是占地方。
    """
    node = graphdb.get_code(context.root(), vid)
    if not node:
        _log("questions: node NOT FOUND vid=", vid)
        raise ValueError("节点不存在")
    _log("questions: node=", node.get("kind"), node.get("name"),
         "@", node.get("rel_path"))
    q = str(question or "").strip()
    if not q:
        raise ValueError("问题不能为空")

    # ★ 不再预读源码：只把节点本身交给模型，需要时它自己 read_file
    #   （所有者 2026-11-18：「让ai自己根据传入的类型，自行判断要读哪些节点信息」）
    messages = ai.build_ask_messages(node, "", "", [], [], [], q, system=system)
    # ★★ 建取消令牌，并把 token 作为第一个事件告诉前端
    #   （所有者 2026-11-19：「openwebui应该都可以的吧？这是标准配置吧？」）
    token, cancel_evt = ai.new_cancel_token()
    # ★ 日志：用 DevTools / 控制台能看到「这次回答的 token 是多少」，
    #   点停止后对照 /ai/cancel/ 的返回，确认取消的是同一次请求。
    print(f"[AI-CANCEL] start token={token} vid={vid}", flush=True)
    try:
        yield {"event": "started", "token": token}
        # ★ 允许模型顺着图谱再读几个节点（⛔ 只读，停止时立刻断 LLM 连接）
        yield from ai.chat_with_tools(
            messages,
            READ_TOOLS,
            _make_tool_executor(project),
            # ★★ 推理模型（DeepSeek R1 等）的思考也占 completion tokens：
            #   800 会被思考吃光、正文一个字都出不来（用户看到"思考到一半就没了"）
            max_tokens=4000,
            cancel=cancel_evt,
        )
    except ai.CancelledError:
        # 用户主动停止：不往前端抛错误，悄悄结束
        print(f"[AI-CANCEL] stopped by user token={token}", flush=True)
        yield {"event": "cancelled"}
    finally:
        ai.unregister_token(token)


