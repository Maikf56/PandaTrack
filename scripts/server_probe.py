#!/usr/bin/env python3
"""服务器连通性探测（脱敏）。

凭据只由本脚本从本地凭据文件读取，用于建立 SSH 连接；
对外只输出连接状态与脱敏服务器指纹，不回显任何凭据值、认证头或环境变量。

用法: python scripts/server_probe.py [凭据文件相对路径]
默认凭据文件: 开发文档/02_辅助资料/服务器SSH.txt
输出字段: host(打码) / port / user(打码) / auth方式 / 连接结果 / uname / python版本 / 磁盘 / CPU核
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CRED = ROOT / "开发文档" / "02_辅助资料" / "服务器SSH.txt"

# 中文/英文标签 -> 字段。只在脚本内使用，不打印值。
LABEL_MAP = {
    "ip": "host", "服务器ip": "host", "服务器": "host", "地址": "host", "host": "host", "主机": "host",
    "端口": "port", "port": "port", "ssh端口": "port",
    "用户名": "user", "user": "user", "账号": "user", "用户": "user",
    "密码": "password", "password": "password", "pwd": "password", "passwd": "password",
    "密钥": "key", "privatekey": "key", "私钥": "key",
}


def mask(value: str | None, keep: int = 2) -> str:
    """打码：只保留首尾少量字符，用于确认字段解析正确，不构成凭据泄露。"""
    if not value:
        return "<空>"
    v = str(value)
    if len(v) <= keep * 2:
        return "*" * len(v)
    return v[:keep] + "*" * (len(v) - keep * 2) + v[-keep:]


def parse_cred(path: Path) -> dict[str, str]:
    """凭据文件为「中文标签行 + 下一行值」结构。只解析字段，不打印值。"""
    lines = [l.rstrip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    fields: dict[str, str] = {}

    for i, line in enumerate(lines):
        label = line.strip().rstrip("：:").lower().replace(" ", "")
        key = LABEL_MAP.get(label)
        if key and i + 1 < len(lines):
            val = lines[i + 1].strip()
            # 值行通常是纯值（不含中文标签），避免把下一个标签当值
            if val and not (re.search(r"[\u4e00-\u9fff]", val) and val.rstrip("：:").lower().replace(" ", "") in LABEL_MAP):
                fields.setdefault(key, val)

    # 裸 IPv4 行（前面无中文标签时兜底）
    if "host" not in fields:
        for val in lines:
            if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", val.strip()):
                fields["host"] = val.strip()
                break

    # 公钥行可能内嵌 PEM；如文件含私钥块也一并取（本文件通常只给公钥）
    text = "\n".join(lines)
    m = re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", text, re.S)
    if m:
        fields.setdefault("key", m.group(0))

    return fields


def load_pkey(key_text: str):
    import paramiko
    from io import StringIO
    for cls in (getattr(paramiko, "Ed25519Key", None), getattr(paramiko, "RSAKey", None)):
        if not cls:
            continue
        try:
            return cls.from_private_key(StringIO(key_text))
        except Exception:
            continue
    return None


def probe(fields: dict[str, str]) -> None:
    import paramiko

    host = fields.get("host")
    port = int(fields.get("port", "22"))
    user = fields.get("user", "root")

    print("=== 字段解析（脱敏）===")
    print(f"host : {mask(host)}")
    print(f"port : {port}")
    print(f"user : {mask(user, 3)}")
    print(f"auth : 本机私钥优先（凭据文件提供公钥配对）")
    print()

    if not host:
        print("结果: 失败 — 未能从凭据文件解析出服务器地址，脚本不猜测。")
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs = dict(hostname=host, port=port, username=user,
                  timeout=12, allow_agent=False, look_for_keys=False)
    auth_desc = []

    # 优先：本机私钥文件（凭据文件只给公钥）
    local_keys = sorted(Path.home().joinpath(".ssh").glob("*_ed25519")) if Path.home().joinpath(".ssh").exists() else []
    key_classes = [c for c in (getattr(paramiko, "Ed25519Key", None), getattr(paramiko, "RSAKey", None)) if c]
    for kf in local_keys:
        pkey = None
        for cls in key_classes:
            try:
                pkey = cls.from_private_key_file(str(kf))
                break
            except Exception:
                continue
        if pkey:
            kwargs["pkey"] = pkey
            auth_desc.append(f"本机私钥({kf.name})")
            break

    # 其次：凭据文件内嵌私钥
    if not auth_desc and fields.get("key"):
        pkey = load_pkey(fields["key"])
        if pkey:
            kwargs["pkey"] = pkey
            auth_desc.append("凭据内嵌私钥")

    # 最后：密码
    if fields.get("password"):
        kwargs["password"] = fields["password"]
        auth_desc.append("密码")

    if not auth_desc:
        print("结果: 失败 — 未找到可用私钥，凭据文件也无密码。")
        return

    print(f"尝试认证方式: {' + '.join(auth_desc)}")
    try:
        client.connect(**kwargs)
    except Exception as e:
        # 只打印异常类型，不打印可能含凭据的异常文本
        print(f"结果: 失败 — 连接异常类型 {type(e).__name__}（不输出异常正文以防泄露凭据）")
        print("建议: 核对凭据文件内容/格式，或由你确认连接参数后重试。")
        return

    print("结果: 成功 — SSH 连接建立")
    try:
        cmds = [
            ("uname", "uname -srmo 2>/dev/null | tr -d '\\n'"),
            ("python", "python3 --version 2>&1 | tr -d '\\n'"),
            ("git", "git --version 2>&1 | tr -d '\\n'"),
            ("node", "node --version 2>&1 | tr -d '\\n'"),
            ("disk", "df -h / 2>/dev/null | tail -1 | tr -s ' '"),
            ("cpu", "nproc 2>/dev/null | tr -d '\\n'"),
            ("os", ". /etc/os-release 2>/dev/null; echo ${PRETTY_NAME:-unknown} | tr -d '\\n'"),
        ]
        print("\n=== 服务器脱敏指纹 ===")
        for label, cmd in cmds:
            stdin, stdout, stderr = client.exec_command(cmd, timeout=10)
            out = stdout.read().decode("utf-8", "replace").strip()
            print(f"{label:8}: {out[:120]}")
    finally:
        client.close()


if __name__ == "__main__":
    rel = sys.argv[1] if len(sys.argv) > 1 else None
    cred = (ROOT / rel) if rel else DEFAULT_CRED
    if not cred.exists():
        print(f"凭据文件不存在: {cred.relative_to(ROOT)}")
        sys.exit(1)
    fields = parse_cred(cred)
    probe(fields)
