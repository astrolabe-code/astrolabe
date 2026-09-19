"""Astrolabe · `manage.py curate` —— **维护者手工修补图**（`GRAPH-STORAGE.md` G1）

---

# ⚠★★ 这不是主入口 —— ★★ **主入口在网页上**

> **用户原话（`B157`）**：「**修补节点是项目创建者自己修补，不是我这个管理员帮他修补。**
> 所以，**必须在网页上能操作**。」

★★ **正常路径**：★ 项目创建者在网页上改 ⇒ `POST /api/projects/<ref>/graph/edit/`
（★ 视图 `web/views/curate.py`，★ 审计里的 actor 是**他本人的账号**）。

⚠★ **本命令的定位收窄为**：★ **事故处理 / 运维**（★ 服务器上直接操作、批量修数据）。
  ★ **它走同一套权限**（`graph.curate.can_curate()`）——
  ⇒ ★★ 所以 `--by` 必须是**该项目的创建者**，★ 或 **`is_staff` 账号**
    （⚠ 后者会被审计标记为「**管理员代改**」，★ 与"他自己改的"**分得开**）。

---

# ★★ 与「重新解析」的区别（`B155` / `B156`）

> **用户原话**：「**在图上改，维护者知道自己在改什么，他删除错了，是他的事**，
> 而**重新解析是大范围改变的，而且是系统干的**。」

| | ★ **本命令**（手工修补） | ❌ 重新解析 |
|---|---|---|
| 粒度 | ★ **一次一个**节点 / 边 | ❌ 整图重建 |
| 谁 | ★ **人** | ❌ 系统 |
| 锚点 | ★ **局部**（不动别人） | ❌❌ 全部行号错位 |

---

# ★ 用法

```bash
# 看一眼这个项目上被人补过什么
python manage.py curate summary proj_xxxx

# ★ 补一个解析漏掉的函数（最常见的用法）
python manage.py curate add-node proj_xxxx \\
    --uid 'file#a.py:foo' --kind function --name foo --file a.py --line 12 \\
    --by admin --reason '解析漏了这个函数（模板里定义的）'

# 改一个节点（⚠ 只改你点名的字段）
python manage.py curate update-node proj_xxxx --vid 42 \\
    --set name=do_foo,line=20 --by admin --reason '名字解析成了宏展开后的形式'

# 删一个不该在的节点（★ 会连带删它的边，命令会告诉你几条）
python manage.py curate delete-node proj_xxxx --vid 42 \\
    --by admin --reason '这是个解析误报'

# 补 / 改 / 删边
python manage.py curate add-edge   proj_xxxx --from-vid 1 --to-vid 2 --type calls \\
    --by admin --reason '调用没识别出来'
python manage.py curate update-edge proj_xxxx --edge 3 --set type=imports \\
    --by admin --reason '类型认错了'
python manage.py curate delete-edge proj_xxxx --edge 3 \\
    --by admin --reason '这条边是误报'
```

---

# ⚠★ `--by` 与 `--reason` 都是**必填**

★ 这不是为难维护者 —— ★ 用户说「**他删除错了，是他的事**」，★ **所以不阻拦任何操作**。
★★ 但「**记下是谁、为什么**」是**另一件事**：★ 它服务的是**半年后的你自己**
（★ "我当时为什么删了这条边？"），⚠ 而且**删掉的东西在别处再也查不到了**。

⇒ ★ 两者**都不设默认值** —— ★ **无法省略**。
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from graph import curate


def _parse_set(raw: str) -> dict:
    """★ 解析 `--set a=1,b=hello` ⇒ `{"a": "1", "b": "hello"}`（⚠ 值一律按字符串给）。"""
    out: dict[str, str] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise CommandError(f"--set 的每一项都要是 key=value（收到 {item!r}）")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _coerce(fields: dict, int_keys: tuple[str, ...]) -> dict:
    """★ 把应该取整数的字段转成 `int`（⚠ 否则会把 `\"20\"` 写进行号字段）。"""
    out = {}
    for k, v in fields.items():
        if k in int_keys:
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                raise CommandError(f"{k} 必须是整数（收到 {v!r}）") from None
        else:
            out[k] = v
    return out


class Command(BaseCommand):
    help = "维护者手工修补图（GRAPH-STORAGE.md G1 的唯一例外）"

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=[
                "summary",
                "add-node", "update-node", "delete-node",
                "add-edge", "update-edge", "delete-edge",
            ],
            help="要做什么",
        )
        parser.add_argument("project_ref", help="项目标识")

        # ---- 谁 / 为什么（★ 两个都必填，⚠ 刻意不给默认值）----
        parser.add_argument(
            "--by", required=True,
            help="以【谁】的身份操作 —— ⚠★ 必须是该项目的创建者，或 is_staff 账号"
                 "（★ 后者会被审计标为「管理员代改」）",
        )
        parser.add_argument("--reason", default="",
                            help="**为什么改**（★ 除 summary 外必填 —— 给半年后的你自己看）")

        # ---- 节点 ----
        parser.add_argument("--uid", default="")
        parser.add_argument("--kind", default="")
        parser.add_argument("--name", default="")
        parser.add_argument("--file", default="", dest="file_path")
        parser.add_argument("--line", type=int, default=0)
        parser.add_argument("--line-end", type=int, default=0, dest="line_end")
        parser.add_argument("--lang", default="")
        parser.add_argument("--signature", default="")
        parser.add_argument("--doc", default="")
        parser.add_argument("--qname", default="")
        parser.add_argument("--vid", type=int, default=0)

        # ---- 边 ----
        parser.add_argument("--from-vid", type=int, default=0, dest="from_vid")
        parser.add_argument("--to-vid", type=int, default=0, dest="to_vid")
        parser.add_argument("--type", default="")
        parser.add_argument("--edge", type=int, default=0)

        # ---- 改哪些字段 ----
        parser.add_argument("--set", default="", dest="set_",
                            help="要改的字段，形如 name=foo,line=12")

    # ------------------------------------------------------------------

    def handle(self, *args, **opts):
        action = opts["action"]
        project_ref = opts["project_ref"]

        # ★ 解析操作者（⚠ 必须真实存在 —— 否则审计里会是一个空 actor）
        User = get_user_model()
        by = User.objects.filter(username=opts["by"]).first()
        if by is None:
            raise CommandError(f"找不到用户：{opts['by']}（--by 必须是真实存在的账号）")

        if action == "summary":
            return self._summary(project_ref)

        reason = (opts["reason"] or "").strip()
        if not reason:
            raise CommandError("必须给 --reason（★ 记下为什么改 —— 见命令文档）")

        try:
            if action == "add-node":
                r = self._add_node(project_ref, by, reason, opts)
            elif action == "update-node":
                r = curate.update_node(
                    project_ref, opts["vid"], by=by, reason=reason,
                    **_coerce(_parse_set(opts["set_"]), ("line", "line_end")),
                )
            elif action == "delete-node":
                r = curate.delete_node(project_ref, opts["vid"], by=by, reason=reason)
            elif action == "add-edge":
                r = curate.add_edge(
                    project_ref, by=by, reason=reason,
                    from_vid=opts["from_vid"], to_vid=opts["to_vid"],
                    type=opts["type"], line=(opts["line"] or None),
                )
            elif action == "update-edge":
                r = curate.update_edge(
                    project_ref, opts["edge"], by=by, reason=reason,
                    **_coerce(_parse_set(opts["set_"]), ("line",)),
                )
            else:  # delete-edge
                r = curate.delete_edge(project_ref, opts["edge"], by=by, reason=reason)
        except ValueError as exc:
            # ⚠★ **`by` / `reason` 缺失时 curate 会抛** —— ★ 翻译成人话，
            #   ❌ 不要让它变成一坨 traceback
            raise CommandError(str(exc)) from exc

        if not r.ok:
            raise CommandError(r.message or "修补失败")

        self.stdout.write(self.style.SUCCESS(f"✅ {r.message}"))
        if r.detail.get("cascaded_edge_count"):
            self.stdout.write(
                self.style.WARNING(
                    f"   ⚠ 连带删除了 {r.detail['cascaded_edge_count']} 条边"
                    "（★ 删除的审计里存了它们的完整快照）"
                )
            )
        self.stdout.write(f"   graph_rev 已 +1 ⇒ ★ 邻域缓存会自然换到新代际")

    # ------------------------------------------------------------------

    def _add_node(self, project_ref, by, reason, opts):
        if not opts["name"] or not opts["file_path"] or opts["line"] < 1:
            raise CommandError("add-node 需要 --name / --file / --line（line >= 1）")
        kind = opts["kind"] or "function"
        return curate.add_node(
            project_ref, by=by, reason=reason,
            # ★★ `uid` 不给就按**解析器的同一形态**兜一个：`<kind>#<path>#<name>`
            #   （见 `codeparser/base.py::ParsedNode.uid`）
            #   ⚠★ **格式必须与解析器一致** —— 否则同一个逻辑节点会有**两种 uid 形态**，
            #      ★ 而 uid 正是"把两处记录认成同一个节点"的依据（`B117`）⇒ **会对不上**。
            uid=opts["uid"] or f"{kind}#{opts['file_path']}#{opts['name']}",
            kind=kind,
            name=opts["name"],
            qname=opts["qname"],
            file_path=opts["file_path"],
            line=opts["line"],
            line_end=opts["line_end"] or None,
            lang=opts["lang"],
            signature=opts["signature"],
            doc=opts["doc"],
        )

    def _summary(self, project_ref: str) -> None:
        s = curate.manual_summary(project_ref)
        self.stdout.write(f"项目          : {s['project_ref']}")
        self.stdout.write(f"graph_rev     : {s['graph_rev']}")
        self.stdout.write(
            f"节点          : {s['total_nodes']}"
            + (f"（★ 其中 {s['manual_nodes']} 个是人补的）" if s["manual_nodes"] else "")
        )
        self.stdout.write(
            f"边            : {s['total_edges']}"
            + (f"（★ 其中 {s['manual_edges']} 条是人补的）" if s["manual_edges"] else "")
        )
        if s["nodes"]:
            self.stdout.write("")
            self.stdout.write("★ 人补的节点：")
            for n in s["nodes"]:
                self.stdout.write(f"   vid={n['vid']:<8} {n['name']:<28} {n['file_path']}:{n['line']}")
