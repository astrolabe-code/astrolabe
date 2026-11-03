# 安全基线 · 换机器时的完整清单（2026-11-03）

> 目的：**在另一台机器上重建时，不用凭记忆**。这里记录的是"当时做了什么、为什么、
> 怎么复现、怎么验证"。
>
> ⚠ `daemon.json` **本身不进仓库**（里面有本机的镜像源与 DNS），但内容全部抄在下面。

---

## 一、Docker 守护进程（`/etc/docker/daemon.json`）

```json
{
  "registry-mirrors": [
    "https://tb3726.356635.xyz",
    "https://docker.xuanyuan.me",
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io"
  ],
  "dns": ["223.5.5.5", "114.114.114.114"],
  "userns-remap": "default",
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
```

| 键 | 为什么必须有 | 换机器怎么填 |
|---|---|---|
| `userns-remap` | 容器内 root 映射成宿主 **100000**；逃逸出去也只是个无权账号 | 原样保留 |
| `log-opts` | 不给上限 ⇒ 日志写满磁盘 ⇒ 数据库写不进 ⇒ 整站挂 | 原样保留 |
| `registry-mirrors` | 国内拉镜像速度（实测 15MB/s vs 1.7MB/s）| **换成本机可用的源** |
| `dns` | 容器内解析 | 按需 |

⚠ 启用 userns 后的两个连带事实：

```
① 镜像/卷都存在 /var/lib/docker/100000.100000/ 下
   ⇒ 旧存储里的镜像与命名卷**看不见**，必须重新拉 / 重新搬
② 属主规则：宿主 uid = 100000 + 容器内 uid
   pgdata 999→100999 · redisdata 999:1000→100999:101000
   meilidata/uptime_data 0→100000 · data/* 1001→101001
```

---

## 二、主机层

```bash
# 1) 服务账号：data/ 归 astrolabe(1001)，源码归 ma
groupadd -g 1001 astrolabe && useradd -u 1001 -g 1001 -M -s /usr/sbin/nologin astrolabe
chown -R astrolabe:astrolabe /home/ma/astrolabe/data
usermod -aG astrolabe ma

# 2) 管理员账号**不进** docker / lxd 组（否则等于免密 root）
gpasswd -d ma docker; gpasswd -d ma lxd; gpasswd -d webapp docker

# 3) sudo 不复用凭据
echo 'Defaults timestamp_timeout=0' > /etc/sudoers.d/99-astrolabe-timeout
chmod 440 /etc/sudoers.d/99-astrolabe-timeout && visudo -c

# 4) SSH：保留密码登录但收紧试错窗口；fail2ban 顶爆破
#    /etc/ssh/sshd_config.d/99-astrolabe-hardening.conf
#      PasswordAuthentication yes
#      MaxAuthTries 3
#      LoginGraceTime 20
apt-get install -y fail2ban   # jail.local: maxretry 6 / bantime 1h / backend systemd

# 5) 容器健康自愈（宿主机侧，容器里没有 docker.sock）
cp deploy/systemd/astrolabe-healthwatch.sh /usr/local/bin/
cp deploy/systemd/astrolabe-healthwatch.{service,timer} /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now astrolabe-healthwatch.timer
```

⚠ `deploy/systemd/` 在 `.gitignore` 里（只在服务器上），换机器要单独拷。

---

## 三、容器层（都在 `docker-compose.yml` 里，进仓库）

```yaml
# 每个服务都要有
user: "1001:1001"                  # 非 root（nginx 用镜像自带的 101）
cap_drop: [ALL]                    # db/redis 只丢 7 项（entrypoint 要 chown/setuid）
security_opt: [no-new-privileges:true]
pids_limit: 256                    # nginx 128
mem_limit: ...                     # db 1g · redis/meili 512m · nginx 128m · kuma 256m
                                   # web 1g · worker 1.5g · heat/searchsync 256m

volumes:
  - /home/ma/astrolabe/app:/app:ro          # ★ 源码只读 ⇒ 被攻破也改不了自己的代码
  - /home/ma/astrolabe/data/uploads:/app/data/uploads   # 运行期可写

# 根文件系统只读（9 个容器全部开启，2026-11-03 实测）
read_only: true
tmpfs:
  - /tmp:size=64m                          # 各个都要
# 额外需要的（按容器）：
#   nginx          /var/cache/nginx:size=32m · /run:size=8m · /tmp:size=32m
#   db             /var/run/postgresql:size=16m（socket）
#   redis/meili/kuma  /tmp（数据都在各自的命名卷里）
```

⚠ 只读根系统的两个前提（漏了容器会起不来）：

```
① Python 服务必须禁掉 __pycache__ 写入：environment: PYTHONDONTWRITEBYTECODE=1
   （web / worker / heat / searchsync 四个都已设置）
② nginx 要留 /var/cache/nginx、/run、/tmp；postgres 要留 /var/run/postgresql（socket）

### 网络分段（三张网）

```
edge（可出网）   nginx · web · worker
data（internal）  web · worker · heat · searchsync · db · redis · meili   ← 出不了网
ops（可出网）     kuma · nginx · web
kuma 另挂 data（要探 meili 健康）
```

效果（实测）：

```
nginx → db/redis/meili     不可连 ✅
web   → db/redis/meili     可连   ✅
db/redis/meili 出网 + DNS   全部失败 ✅（Docker 29.x，CVE-2024-29018 不复现）
```

### 端口暴露（只有一条对外）

```
nginx   0.0.0.0:80 → 8080          ← 唯一公网入口
nginx   127.0.0.1:8090 → 8081      后台
db      127.0.0.1:15432            Navicat 走 SSH 隧道
redis   127.0.0.1:16379
meili   127.0.0.1:17700
kuma    127.0.0.1:3001
其余容器 **不发布端口**
```

---

## 四、应用层

```
Redis      --requirepass ${REDIS_PASSWORD}，废弃 CONFIG/FLUSHALL/FLUSHDB/DEBUG/MONITOR
           密码在 .env（不进 git），另存 /root/.redis_password（600）
PostgreSQL 运行时用 astrolabe_app（NOSUPERUSER，拥有对象 ⇒ 迁移可跑）
           建角色脚本：deploy/pg_app_role.sql
           实测：COPY TO PROGRAM / pg_read_file / CREATE ROLE 全部被拒
解析预算   站点级门禁（仅 superuser 可改），见核心 B 系列记录
队列公平   queue_max_jobs 50 / queue_user_max 3，事务内取锁判定
```

---

## 五、新机器重建顺序

```bash
# 1  装 Docker，按第一节写 /etc/docker/daemon.json，重启 docker
# 2  按第二节建账号/组、sudoers、sshd、fail2ban
# 3  准备目录：app/、data/{uploads,repos,static}、data/static 属主见第一节
# 4  拉镜像（或 docker load）→ 见 IMAGES.md 里的 tag 与 digest
# 5  docker compose build web
# 6  docker compose up -d
# 7  docker compose exec -T db psql -U astrolabe -d astrolabe -f - < pg_app_role.sql
#    再把 DB_APP_USER / DB_APP_PASSWORD 写进 .env，重建 web/worker/heat/searchsync
# 8  docker compose exec -T web python manage.py migrate
```

---

## 六、复检命令（一分钟跑完）

```bash
docker info --format '{{json .SecurityOptions}}'            # 要含 name=userns
docker ps -q | xargs -r docker inspect -f '{{.Name}} {{.HostConfig.Privileged}} {{join .HostConfig.CapDrop ","}}'  # 无 true
docker ps -q | xargs -r docker inspect -f '{{.Name}} {{index .HostConfig.LogConfig.Config "max-size"}}'           # 都是 10m
getent group docker                                          # 成员应为空
docker compose exec -T nginx nc -z -w2 db 5432 && echo 能连 ⚠ || echo 不可连 ✅
docker compose exec -T db bash -c 'timeout 3 bash -c "echo > /dev/tcp/1.1.1.1/443"' && echo 能出网 ⚠ || echo 出不去 ✅
```
