"""★★ **Meilisearch 客户端**（`B238`）—— 只用标准库，⛔ 不引新依赖 ⚠

## ★ 配置（都在 `.env`）

```
MEILI_URL          http://meilisearch:7700      # 容器内用服务名
MEILI_MASTER_KEY   <32 字节随机>                # 生产模式必填
```

## ★★ 纪律

- ⚠ **所有调用都可能失败**（容器没起来 / key 错 / 网络断）
  ⇒ 抛 `MeiliError`，由调用方决定「降级回 PG」还是「报错」
- ⛔ 这里**不吞异常**（* 搜索引擎掉了要能看见，* 不像缓存可以静默降级）
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

#: 笔记索引的 uid（* 固定，* 重建走 `search_reindex`）⚠
NOTES_INDEX = "notes"


class MeiliError(RuntimeError):
    """Meilisearch 调用失败（* 连不上 / 401 / 任务失败）⚠"""


def base_url() -> str:
    return (os.environ.get("MEILI_URL") or "http://meilisearch:7700").rstrip("/")


def master_key() -> str:
    return (os.environ.get("MEILI_MASTER_KEY") or "").strip()


def enabled() -> bool:
    """★ 配了 key 才算启用（* 测试环境可以完全不配，* 搜索走 PG 回退）⚠"""
    return bool(master_key())


def _request(method: str, path: str, payload=None, timeout: float = 10.0):
    url = f"{base_url()}{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    key = master_key()
    if key:
        req.add_header("Authorization", f"Bearer {key}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise MeiliError(f"{method} {path} → {exc.code}: {detail}") from None
    except Exception as exc:  # 连接失败 / 超时 / JSON 坏
        raise MeiliError(f"{method} {path} → {exc}") from None


# ---------------------------------------------------------------------------
# 健康 / 任务
# ---------------------------------------------------------------------------

def health() -> dict:
    """★ 不需要 key（* 用来判断「服务在不在」）⚠"""
    return _request("GET", "/health", timeout=3.0)


def version() -> dict:
    return _request("GET", "/version")


def wait_task(task_uid: int, timeout: float = 120.0, interval: float = 0.2) -> dict:
    """★ 等一个异步任务跑完（* 建索引 / 写文档 / 改设置 都是异步的）⚠"""
    deadline = time.monotonic() + timeout
    while True:
        task = _request("GET", f"/tasks/{task_uid}")
        status = task.get("status")
        if status not in ("enqueued", "processing"):
            if status != "succeeded":
                raise MeiliError(f"任务 {task_uid} 失败：{task.get('error')}")
            return task
        if time.monotonic() > deadline:
            raise MeiliError(f"任务 {task_uid} 超时（{timeout}s）")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# 索引管理
# ---------------------------------------------------------------------------

def ensure_index(uid: str = NOTES_INDEX) -> None:
    """★ 建索引（* 已存在就跳过）⚠"""
    try:
        _request("GET", f"/indexes/{uid}")
        return
    except MeiliError:
        pass
    task = _request("POST", "/indexes", {"uid": uid, "primaryKey": "id"})
    wait_task(task["taskUid"])


def update_settings(uid: str, settings: dict) -> None:
    task = _request("PATCH", f"/indexes/{uid}/settings", settings)
    wait_task(task["taskUid"])


def delete_all_documents(uid: str = NOTES_INDEX) -> None:
    task = _request("DELETE", f"/indexes/{uid}/documents")
    wait_task(task["taskUid"])


def add_documents(uid: str, docs: list[dict]) -> None:
    """★ 批量写（* Meili 单次上限约 100MB / 10 万文档，* 我们按 500 一批足够）⚠"""
    if not docs:
        return
    task = _request("POST", f"/indexes/{uid}/documents", docs)
    wait_task(task["taskUid"])


def delete_document(uid: str, doc_id) -> None:
    task = _request("DELETE", f"/indexes/{uid}/documents/{doc_id}")
    wait_task(task["taskUid"])


def index_stats(uid: str = NOTES_INDEX) -> dict:
    return _request("GET", f"/indexes/{uid}/stats")


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def multi_search(queries: list[dict]) -> list[dict]:
    """★★ **一次请求查多组**（* Meilisearch `/multi-search`）⚠

    ⚠ 用途：* 「用户输入 + 前几个联想词」一起查，* 而不是先查一次、空了再补查 ⚠
    """
    if not queries:
        return []
    res = _request("POST", "/multi-search", {"queries": queries})
    return res.get("results") or []


def search(
    uid: str,
    q: str,
    *,
    limit: int = 20,
    offset: int = 0,
    sort: list[str] | None = None,
    filters: str | None = None,
) -> dict:
    payload: dict = {"q": q, "limit": limit, "offset": offset}
    if sort:
        payload["sort"] = sort
    if filters:
        payload["filter"] = filters
    return _request("POST", f"/indexes/{uid}/search", payload)
