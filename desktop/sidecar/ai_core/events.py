#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 事件生成器（问答 / 出题的流式事件流）。

从 main.py 抽出 —— 这里只管「把一次 AI 请求变成一串事件」，
⛔ 不管 HTTP 响应怎么写、不管进程主循环。
"""

import json

import ai_core.client as ai
import graphdb
import store
from ai_core import context
from ai_core.log import _log
from ai_core.tools import READ_TOOLS, _make_tool_executor

def _question_line(line: str) -> dict | None:
    """解析一行模型输出为事件；只认固定前缀，⛔ 不做整段兜底。

    与 ai.parse_questions 的前缀保持一致；兜底（自由文字→简评）
    留给流结束时的 parse_questions，避免逐行重复触发。
    """
    v = str(line or "").strip().lstrip("-·•* 　").strip()
    if not v:
        return None
    for label in ("陷阱", "优化", "背景"):
        for sep in ("：", ":"):
            if v.startswith(label + sep):
                body = v[len(label) + 1 :].strip()
                return {"event": "question", "type": label, "text": body} if body else None
    for sep in ("：", ":"):
        if v.startswith("简评" + sep):
            body = v[3:].strip()
            return {"event": "question", "type": "简评", "text": body} if body else None
        if v.startswith("下一步" + sep):
            rest = v[4:].strip()
            name, _, why = rest.partition("——")
            if not why:
                name, _, why = rest.partition("-")
            if name.strip():
                return {"event": "next", "name": name.strip(), "why": why.strip()}
    return None


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


def _questions_events(project, vid: int, refresh: bool = False, token: str = ""):
    """出题（流式）：started / think / question / next / cancelled / done。

    ★ 与问答统一走 SSE（所有者 2026-11-19：「出题为什么不也改成流式输出？」）：
      · 问题逐条吐，写完一行就发一张卡片；
      · 思考过程也发，用户看得到 AI 在查什么；
      · started 带 token，停止逻辑与问答一致（⛔ 不再用响应头那套）。
    """
    _log("questions: start vid=", vid, "refresh=", refresh)
    act = ai.active()
    _log("questions: model=", act.get("model"), "provider=", act.get("id"))

    # 缓存命中：按同一套事件格式一次性吐完
    if not refresh:
        cached = store.get_ai_questions(context.conn(), vid, act["id"], act["model"])
        if cached:
            try:
                old = json.loads(cached)
                for it in (old.get("items") or []):
                    yield {
                        "event": "question",
                        "type": str(it.get("type") or ""),
                        "text": str(it.get("text") or ""),
                    }
                for nx in (old.get("next") or []):
                    yield {
                        "event": "next",
                        "name": str(nx.get("name") or ""),
                        "why": str(nx.get("why") or ""),
                    }
                yield {"event": "done", "cached": True}
                return
            except Exception:  # noqa: BLE001
                pass

    node = graphdb.get_code(context.root(), vid)
    if not node:
        raise ValueError("节点不存在")
    messages = ai.build_questions_messages({"node": node})

    token, cancel_evt = ai.new_cancel_token(token)
    yield {"event": "started", "token": token}

    # 完整文本：既用于逐行吐，也用于最后 parse_questions（含兜底）
    full: list[str] = []
    emitted: set[str] = set()  # 已发过的行，最后不重复发
    cancelled = False

    # ★ next_line：下一个待处理的完整行索引。
    #   ⚠ 不能每次重新遍历 full 又不去重 —— 同一行会被发多次；
    #     也不能像之前那样 `full[:] = [tail]` —— 那会把正文吞掉、
    #     导致 text 变空误触发 chat_once（表现为「模型没有返回任何内容」）。
    next_line = 0

    def take_complete(force: bool = False) -> list[str]:
        """只返回**新凑齐**的完整行；正文始终留在 full 里给整段解析。"""
        nonlocal next_line
        joined = "".join(full)
        lines = joined.split("\n")
        # 最后一段未写完，不算完整行（除非 force）
        usable = len(lines) if force else len(lines) - 1
        out = [
            ln.strip() for ln in lines[next_line:usable] if ln.strip()
        ]
        next_line = max(next_line, usable)
        return out

    try:
        for evt in ai.chat_with_tools(
            messages,
            READ_TOOLS,
            _make_tool_executor(project),
            max_tokens=3000,
            cancel=cancel_evt,
        ):
            kind = evt.get("event")
            if kind == "delta":
                full.append(str(evt.get("text") or ""))
                for ln in take_complete():
                    key = ln.strip()
                    if key in emitted:
                        continue
                    emitted.add(key)
                    out = _question_line(ln)
                    if out:
                        yield out
            elif kind == "think":
                yield evt
            elif kind in ("tool_use", "step"):
                _log("questions: model used tool", evt.get("name") or evt.get("round"))
            # step / tool_use / usage 不发：浮窗不需要

        # 收尾：把最后半行也处理掉
        for ln in take_complete(force=True):
            key = ln.strip()
            if key in emitted:
                continue
            emitted.add(key)
            out = _question_line(ln)
            if out:
                yield out

        text = "".join(full)
        _log("questions: collected text len=", len(text))
        if not text.strip():
            # ★ 工具链正常结束但一个字没吐 ⇒ 退回普通一次调用
            text = ai.chat_once(messages, max_tokens=3000)

        # ★ 整段解析一次（处理自由文字兜底），只补发还没发过的
        parsed = ai.parse_questions(text)
        _log("questions: parsed items=", len(parsed.get("items") or []),
             "next=", len(parsed.get("next") or []))
        for it in (parsed.get("items") or []):
            key = f"{it.get('type')}：{it.get('text')}"
            if key not in emitted:
                emitted.add(key)
                yield {
                    "event": "question",
                    "type": str(it.get("type") or ""),
                    "text": str(it.get("text") or ""),
                }
        # ★ 去重：逐行已发过的 next 不重复发
        for nx in (parsed.get("next") or []):
            # ⚠ key 必须与逐行时 emitted 存的原始行一致（含「 —— 」两侧的空格）
            nkey = f"下一步：{nx.get('name')} —— {nx.get('why')}"
            if nkey in emitted:
                continue
            emitted.add(nkey)
            yield {
                "event": "next",
                "name": str(nx.get("name") or ""),
                "why": str(nx.get("why") or ""),
            }

        # ★★ 一道保险：一条问题都没解析出来时，明确告诉用户原因，
        #   ⛔ 绝不让前端停在「模型没有返回任何内容」的空状态（无从排查）
        if not parsed.get("items") and not cancelled:
            yield {
                "event": "question",
                "type": "简评",
                "text": (
                    "这次没出题：模型只输出了思考、没有给出可提问的内容。"
                    "可能是 max_tokens 被思考用完，或这个节点确实没什么可问的。"
                    "可以点「换一批」重试。"
                ),
            }

        if parsed.get("items"):
            try:
                store.put_ai_questions(
                    context.conn(), vid, act["id"], act["model"],
                    json.dumps(parsed, ensure_ascii=False),
                )
            except Exception:  # noqa: BLE001
                pass
    except ai.CancelledError:
        _log("questions: cancelled by user")
        cancelled = True
        yield {"event": "cancelled"}
    except Exception as exc:
        _log("questions: EXCEPTION", type(exc).__name__, str(exc)[:300])
        if cancel_evt is not None and cancel_evt.is_set():
            cancelled = True
            yield {"event": "cancelled"}
        else:
            yield {
                "event": "question",
                "type": "简评",
                "text": f"出题失败：{ai.redact(str(exc))}",
            }
    finally:
        ai.unregister_token(token)

    yield {"event": "done", "cached": False}
