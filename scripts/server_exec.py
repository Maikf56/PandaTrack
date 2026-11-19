#!/usr/bin/env python3
"""在服务器上执行命令并流式输出（复用密钥配对连接逻辑）。

用法:
    python scripts/server_exec.py "命令" [--timeout 600]
退出码 = 远程命令退出码（认证失败等为负/特定码）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server_connect import DEFAULT_AUX, DEFAULT_CRED, load_pem, parse_conn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command")
    ap.add_argument("--timeout", type=int, default=600, help="命令最长运行秒数")
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
    try:
        client.connect(hostname=host, port=port, username=user, pkey=pkey,
                       timeout=15, allow_agent=False, look_for_keys=False)
    except Exception as e:
        print(f"连接失败: {type(e).__name__}", file=sys.stderr)
        return 126

    try:
        chan = client.get_transport().open_session()
        chan.settimeout(args.timeout)
        chan.exec_command(args.command)
        chunks = []
        start = time.time()
        while True:
            while chan.recv_ready():
                chunks.append(chan.recv(8192))
            if chan.exit_status_ready() and not chan.recv_ready():
                break
            if time.time() - start > args.timeout:
                chan.close()
                print(f"\n[server_exec] 超时({args.timeout}s)，命令被中止", file=sys.stderr)
                return 124
            time.sleep(0.15)
        while chan.recv_ready():
            chunks.append(chan.recv(8192))
        code = chan.recv_exit_status()
        text = b"".join(chunks).decode("utf-8", "replace")
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        return code
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
