"""Astrolabe · ② 作业层：worker 进程

★ 依据 ARCHITECTURE.md A2：worker 消费 Job、执行解析、写回结果；
  ⚠ 它【不对外提供 HTTP】。

★ 启动方式（deploy/docker-compose.yml 的 worker 服务）：
     python manage.py run_worker

★★ 长驻进程注意（旧项目的教训）：
   · 每轮先 `close_old_connections()` —— 避免陈旧 DB 连接
   · 收到 SIGTERM 后【跑完当前作业即退】（drain），不硬中断
"""

import logging
import os
import signal
import socket

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from jobs import queue
from jobs.models import Job
from jobs.tasks import execute

log = logging.getLogger("astrolabe.worker")


class Command(BaseCommand):
    help = "消费作业队列（② 作业层）"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="只处理一个作业后退出（调试用）")

    def handle(self, *args, **options):
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.stdout.write(f"[worker] 启动：{worker_id}")

        running = True

        def _stop(signum, frame):  # noqa: ARG001
            nonlocal running
            self.stdout.write("[worker] 收到停止信号 —— 当前作业跑完即退（drain）")
            running = False

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        while running:
            close_old_connections()  # ★ 长驻进程：避免陈旧连接
            job_id = queue.dequeue(timeout=5)
            if job_id is None:
                continue
            self._run_job(job_id, worker_id)
            if options["once"]:
                break

        self.stdout.write("[worker] 已退出")

    # ------------------------------------------------------------------

    def _run_job(self, job_id: int, worker_id: str) -> None:
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            log.warning("作业 %s 不存在，跳过", job_id)
            return

        if job.state != Job.STATE_QUEUED:
            log.warning("作业 %s 状态为 %s，跳过", job_id, job.state)
            return

        # ⚠★ **不在这里置 `running`、也不在这里收尾** —— ★ 全部交给 `tasks.execute()`。
        #   ⚠ 旧写法「先读 state 判断、再置 running」是 check-then-use：
        #     两个执行者（两个 worker，或 worker + 一次手动重跑）会**同时通过检查**
        #     ⇒ ★★ **同一个作业被跑两遍**（实测踩到过：图被写两次、outcome 互相覆盖，
        #       表现为「作业说没解析，图却有了」—— ⚠ 排查极其费劲）。
        self.stdout.write(f"[worker] 处理作业 {job_id}（kind={job.kind}）")
        outcome = execute(job, worker_id=worker_id)

        if outcome == "skipped":
            self.stdout.write(f"[worker] 作业 {job_id} 已被其他进程领取，跳过")
        elif outcome == "failed":
            self.stdout.write(f"[worker] 作业 {job_id} 失败")
        else:
            self.stdout.write(f"[worker] 作业 {job_id} 完成")
