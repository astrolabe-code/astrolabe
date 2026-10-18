"""★★★ 笔记导出包的**容器** —— `B232` / `B233` · 2026-10-18

## ★★★ 所有者原话（逐字）

> 「**这些导出文件是不可以被篡改的，你这 zip 文件，太容易篡改了。**」
> 「**可以，不过密钥应该对着打包好的 zip 文件的二进制数据算，也就是，
> 改 zip 文件的一个位，也不能通过。**」

## ★★ 为什么不是二进制 / MD5

```
⛔ 二进制 / 混淆 ——* 字节谁都能改，* 只是看着难改 ⚠
⛔ MD5 ——* 改完再重算一个就行（* 且 MD5 已有碰撞）⚠
✅ HMAC-SHA256(SECRET_KEY, zip_bytes) ——* 密钥只在服务器上 ⚠
```

## ★★ 容器格式

```
[ magic: "ASTROEXP1" (9B) ][ hmac: HMAC-SHA256 (32B) ][ payload: ZIP 字节 ]
```

⚠★ **签名对象是打包好的那一串 ZIP 字节**（`B233`）——
  ⛔ 不是文件名清单、⛔ 不是解包后的内容、⛔ 不是重新打包的结果。

⇒ 改 ZIP 里任何一个位 ⇒ 摘要全变 ⇒ 验签失败 ⇒ 拒绝恢复。
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import zipfile

#: ★ 魔数（* 拿错文件当场识别）⚠
MAGIC = b"ASTROEXP1"

#: ★ HMAC 长度（SHA-256 = 32 字节）
HMAC_LEN = 32

#: ★ 导出包扩展名
EXTENSION = ".astrolabe-backup"


def _key() -> bytes:
    """★ 签名密钥 = Django 的 `SECRET_KEY`（* 只在服务器上）⚠"""
    from django.conf import settings

    raw = getattr(settings, "SECRET_KEY", "") or ""
    return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)


def pack(zip_bytes: bytes) -> bytes:
    """★★ 把 ZIP 字节封成**带签名的容器**（`B232`③）⚠"""
    digest = hmac.new(_key(), zip_bytes, hashlib.sha256).digest()
    return MAGIC + digest + zip_bytes


def unpack(blob: bytes) -> tuple[bytes | None, str | None]:
    """★★ 验签并取出 ZIP 字节（* `(zip_bytes, None)` 或 `(None, 错误文案)`）⚠

    ⚠★ **先验签再解包** —— ⛔ 不验签就解包等于没防（`B232`②）⚠
    """
    if len(blob) < len(MAGIC) + HMAC_LEN:
        return None, "文件太小，不是有效的导出包"
    if blob[: len(MAGIC)] != MAGIC:
        return None, "文件格式不对（不是本站导出的笔记备份）"

    digest = blob[len(MAGIC) : len(MAGIC) + HMAC_LEN]
    zip_bytes = blob[len(MAGIC) + HMAC_LEN :]

    expect = hmac.new(_key(), zip_bytes, hashlib.sha256).digest()
    # ⚠ `compare_digest` —— 恒定时间比较，⛔ 不用 `==`（时序侧信道）
    if not hmac.compare_digest(digest, expect):
        return None, "文件已被篡改（签名校验不通过）—— 无法用于恢复"

    return zip_bytes, None


def build_zip(files: dict[str, bytes], manifest: dict) -> bytes:
    """★★ 把「文件名 → 内容」与 manifest 打包成 ZIP 字节 ⚠

    Args:
        files: `{文件名: 字节}`（* 每篇笔记一个 `.md`）
        manifest: 项目级清单（* `B231`②ⓑ）
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def read_zip(zip_bytes: bytes) -> tuple[dict[str, bytes] | None, dict | None, str | None]:
    """★★ 解包 ZIP ⇒ `(文件字典, manifest, 错误文案)` ⚠

    ⚠ 只读**白名单内的名字**（* `manifest.json` 与 `notes/*.md`）——
      ⛔ 不解出路径穿越的文件名（* `../` 之类）⚠
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                return None, None, "包里没有 manifest.json"
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            files = {
                n: zf.read(n)
                for n in names
                if n != "manifest.json" and not n.endswith("/")
            }
    except zipfile.BadZipFile:
        return None, None, "ZIP 数据损坏"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, "manifest.json 解析失败"

    for name in files:
        # ⚠ 路径穿越 / 奇怪名字一律拒收 ⚠
        if name.startswith("/") or ".." in name.split("/"):
            return None, None, f"包里有非法文件名：{name!r}"
    return files, manifest, None
