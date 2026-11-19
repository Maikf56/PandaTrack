#!/usr/bin/env python3
"""通过 SFTP 上传本地文件/目录到服务器（复用密钥连接逻辑）。

用法:
    python scripts/server_upload.py <本地路径> <远程绝对路径>
本地为目录时递归上传全部文件（保持相对结构）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server_connect import DEFAULT_AUX, DEFAULT_CRED, load_pem, parse_conn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("local")
    ap.add_argument("remote")
    ap.add_argument("--cred", default=str(DEFAULT_CRED))
    args = ap.parse_args()

    import paramiko

    conn = parse_conn(Path(args.cred))
    host, port, user = conn.get("host"), int(conn.get("port", "22")), conn.get("user", "ubuntu")

    pkey = None
    for p in sorted(DEFAULT_AUX.glob("*.pem")):
        _, k = load_pem(p)
        if k:
            pkey = k
            break
    if pkey is None:
        print("未找到可用私钥", file=sys.stderr)
        return 125

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=user, pkey=pkey,
                   timeout=15, allow_agent=False, look_for_keys=False)

    local = Path(args.local)
    remote = args.remote.rstrip("/")
    uploaded = 0
    try:
        sftp = client.open_sftp()

        def mkdirs(path: str) -> None:
            parts = path.strip("/").split("/")
            cur = ""
            for part in parts:
                cur += "/" + part
                try:
                    sftp.stat(cur)
                except FileNotFoundError:
                    sftp.mkdir(cur)

        files = [local] if local.is_file() else [f for f in sorted(local.rglob("*")) if f.is_file()]
        is_single = local.is_file()
        # 单文件：remote 即完整目标路径（scp 语义）；目录：remote 为父目录，保持相对结构
        # 先用 shell mkdir -p 建全部目标目录（SFTP 逐级 mkdir 有权限怪癖）
        dirs = set()
        for f in files:
            if is_single:
                target = remote
            else:
                rel = f.relative_to(local)
                target = f"{remote}/{rel.as_posix()}"
            dirs.add(target.rsplit("/", 1)[0])
        if dirs:
            cmd = "mkdir -p " + " ".join(f"'{d}'" for d in sorted(dirs))
            _in, out, err = client.exec_command(cmd, timeout=30)
            rc = out.channel.recv_exit_status()
            if rc != 0:
                print(f"mkdir 失败: {err.read().decode('utf-8', 'replace')}", file=sys.stderr)
                return 1
        for f in files:
            if is_single:
                target = remote
                display = Path(remote).name
            else:
                rel = f.relative_to(local)
                target = f"{remote}/{rel.as_posix()}"
                display = rel.as_posix()
            sftp.put(str(f), target)
            uploaded += 1
            print(f"  ↑ {display} ({f.stat().st_size} B)")
        print(f"完成: 上传 {uploaded} 个文件 → {remote}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
