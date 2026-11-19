#!/usr/bin/env python3
"""SOCKS5 握手字节级诊断。输出只含协议握手码，不回显凭据。"""
import socket, sys, re
from pathlib import Path

CRED = Path.home() / ".pandatrack-secrets" / "udealproxy.txt"
line = next(l for l in CRED.read_text().splitlines()
            if re.match(r"^[a-zA-Z0-9._-]+:[0-9]+:", l))
host, port, user, pwd = line.split(":")
port = int(port)
print(f"网关 {host}:{port} 用户前缀 {user[:16]}... 密码长度 {len(pwd)}")

def handshake(methods: bytes, label: str):
    s = socket.create_connection((host, port), timeout=15)
    s.settimeout(15)
    # 方法协商: VER=05, NMETHODS, METHODS
    s.sendall(b"\x05" + bytes([len(methods)]) + methods)
    try:
        resp = s.recv(2)
        print(f"[{label}] 方法协商回复: VER=0x{resp[0]:02x} METHOD=0x{resp[1]:02x}"
              + (" (无需认证)" if resp[1:] == b"\x00" else
                 " (用户名密码)" if resp[1:] == b"\x02" else
                 " (不接受任何方法=0xFF)" if resp[1:] == b"\xff" else "")
              if len(resp) == 2 else f"[{label}] 异常回复: {resp!r}")
        return s, resp
    except (ConnectionResetError, socket.timeout) as e:
        print(f"[{label}] 握手被断开: {type(e).__name__}")
        s.close()
        return None, None

# 尝试1: 用户名密码认证
s, resp = handshake(b"\x02", "用户密码认证")
if s and resp and len(resp) == 2 and resp[1] == 0x02:
    # 发送用户名密码 (RFC 1929)
    auth = b"\x01" + bytes([len(user)]) + user.encode() + bytes([len(pwd)]) + pwd.encode()
    s.sendall(auth)
    r = s.recv(2)
    print(f"  认证回复: VER=0x{r[0]:02x} STATUS=0x{r[1]:02x}"
          + (" = 成功" if r[1:] == b"\x00" else " = 失败"))
    if r[1:] == b"\x00":
        # 请求连接 ipinfo.io:80
        target = b"ipinfo.io"
        req = b"\x05\x01\x00\x03" + bytes([len(target)]) + target + b"\x00\x50"
        s.sendall(req)
        rr = s.recv(32)
        print(f"  CONNECT 回复: REP=0x{rr[1]:02x}"
              + (" = 成功" if rr[1:2] == b"\x00" else f" = 失败码{rr[1:2].hex()}"))
    s.close()

# 尝试2: 无认证（IP 白名单模式探测）
s2, resp2 = handshake(b"\x00", "无认证/白名单模式")
if s2:
    s2.close()

# 尝试3: 同时代销两种认证
s3, resp3 = handshake(b"\x00\x02", "两种方法同时提供")
if s3:
    s3.close()
