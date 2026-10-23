"""★★ **项目索引**（`B241` · 2026-10-23）⚠

## ★ 为什么现在才做

* 早先项目只有个位数 ⇒ PG `icontains` + trgm + Redis 缓存已经够用（`B238` 的取舍）。
* 现在项目表已有 `node_count` / `edge_count` / `provider` / `repo_url` 真实列（`B239`），
  建索引**不用再回基图表算数** ⇒ 成本降下来了，搬进 Meili 变得划算 ✅

## ★ 索引范围

```
索引里放**全部项目**（含私有）
  · 公开搜索：filter = is_public=true AND state="active"  ⛔ 私有绝不出现在结果里
  · 工作区搜索（mine=1）：filter owner_id = 当前用户
  · 无论哪种，最终还要过一遍 PG 的可见性过滤（* 双保险）✅
```
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from core.models import Project

INDEX_SETTINGS = {
    # ★ 与 PG 口径一致：名称 / 简介 / 作者名
    "searchableAttributes": ["name", "desc", "owner"],
    # ★ 过滤：公开搜索只取公开且生效的
    "filterableAttributes": ["is_public", "state", "owner_id", "provider"],
    # ★ 排序：最新、节点数
    "sortableAttributes": ["created_at", "updated_at", "node_count"],
}


def _ts(dt) -> int:
    """★ 时间 → 毫秒整数（* 与笔记索引同口径）⚠"""
    return int(dt.timestamp() * 1000) if dt else 0


def build_document(p: "Project") -> dict:
    """★ 构造一份项目索引文档（* 字段全部来自项目表，不回基图）⚠"""
    return {
        "project_ref": p.project_ref,
        "name": p.name or "",
        "desc": (p.desc or "")[:2000],
        "owner": p.owner.get_username() if p.owner_id else "",
        "owner_id": p.owner_id or 0,
        "provider": p.provider or "",
        "repo_url": p.repo_url or "",
        # ★ 可见性：过滤用（* 私有项目也索引，* 但公开搜索会过滤掉）⚠
        "is_public": bool(p.is_public),
        "state": p.state or "",
        # ★ 两个计数（* 2026-10-23 起是真实列）✅
        "node_count": int(p.node_count or 0),
        "edge_count": int(p.edge_count or 0),
        "created_at": _ts(p.created_at),
        "updated_at": _ts(p.updated_at),
    }
