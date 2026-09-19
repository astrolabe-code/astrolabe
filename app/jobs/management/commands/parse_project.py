"""Astrolabe · 调试命令：本地目录 → 解析 → 写图

⚠ **仅供开发调试** —— 它**绕过队列**直接同步执行。

正式链路是（`JOB-MODEL.md` J9）：
    ① Web 写 Job + 推队列  →  ② worker 消费  →  走的是同一个 `run_parse_job`

★ 用途：在没接前端之前，能**独立验证"解析 → 出图"这条链路是否通**。

用法：
    python manage.py parse_project /app/codeparser --project-ref proj_abcdef
    python manage.py parse_project /some/repo  --max-files 500

---

★★★ **`B155` 之后：同一个 `project_ref` 只能解析一次**（`B103`：图不可变）。

★ 不给 `--project-ref` ⇒ ★ **每次自动生成一个新的** ⇒ ⚠ 反复调试**直接就能跑** ✅
★ 给了**用过的** `--project-ref` ⇒ ★ 会打印「图已定版」并**明确告诉你怎么办**
  （★ **要另一个版本就换一个 ref** —— ★ 这正是"新建项目"那条路）。

⚠★ **刻意不提供 `--force` / `--replace`** ——
  ★ 用户明确说了「**解析完成之后不允许重新解析**……**解释里的"几行到几行"就失效了**」，
  ★★ 所以**不留一条"一不小心就覆盖"的后门**。
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from jobs.models import Job
from jobs.tasks import run_parse_job


class Command(BaseCommand):
    help = "把本地目录解析成图（⚠ 开发调试用，绕过队列）"

    def add_arguments(self, parser):
        parser.add_argument("path", help="项目根目录（绝对路径，容器内路径）")
        parser.add_argument(
            "--project-ref",
            default="",
            help="项目标识；不给则自动生成 proj_<hex>",
        )

    def handle(self, *args, **options):
        root = Path(options["path"]).resolve()
        if not root.is_dir():
            raise CommandError(f"不是目录：{root}")

        project_ref = options["project_ref"] or f"proj_{uuid.uuid4().hex[:27]}"

        self.stdout.write(f"项目标识: {project_ref}")
        self.stdout.write(f"目录    : {root}")

        # ★ 造一条真实的 Job 记录 —— 与正式链路走【同一个执行体】，避免两套代码
        job = Job.objects.create(
            project_ref=project_ref,
            kind=Job.KIND_PARSE,
            state=Job.STATE_RUNNING,
            payload={"path": str(root)},
            stage="启动",
            worker_id="cli",
        )

        started = time.monotonic()
        try:
            run_parse_job(job)
        except Exception as exc:  # noqa: BLE001
            job.state = Job.STATE_FAILED
            job.error_msg = str(exc)[:2000]
            job.save(update_fields=["state", "error_msg"])
            raise CommandError(f"解析失败：{exc}") from exc

        job.state = Job.STATE_DONE
        job.save(update_fields=["state"])

        elapsed = time.monotonic() - started
        payload = job.payload or {}
        summary = payload.get("summary", {})
        outcome = payload.get("outcome")

        # ★★ 定版闸门挡下了这次解析 —— ★ **这不是失败**，★ 而是"这个 ref 已经解析过了"
        if outcome == "already_built":
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("⚠ 这个 project_ref 已经解析过 —— 图不会重新生成"))
            self.stdout.write("  （B103：图不可变；★ 重新解析会让解释里的行区间全部失效）")
            self.stdout.write("")
            self.stdout.write("  ★ 要再跑一次，请【换一个 --project-ref】（★ 那就是「新建一个项目」）")
            return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅ 完成，用时 {elapsed:.1f}s"))
        self.stdout.write(f"  job_id      : {job.pk}")
        for key in (
            "files_seen", "files_parsed", "files_skipped",
            "by_lang", "nodes", "edges", "edges_skipped", "parse_errors",
        ):
            self.stdout.write(f"  {key:<13}: {summary.get(key)}")
