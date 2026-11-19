#!/usr/bin/env python3
"""服务器 SSH 连接（密钥/密码双模式）+ 脱敏指纹采集。

认证优先级:
  1. --pem 指定的私钥文件（默认自动查找 开发文档/02_辅助资料/*.pem）
  2. --password-file 指定的密码文件
私钥与密码只由本脚本读取用于认证，绝不回显内容；
连接前先校验私钥公钥指纹是否与凭据卡公钥配对（只输出指纹与结论）。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CRED = ROOT / "开发文档" / "02_辅助资料" / "服务器SSH.txt"
DEFAULT_AUX = ROOT / "开发文档" / "02_辅助资料"


def mask(value: str | None, keep: int = 2) -> str:
    if not value:
        return "<空>"
    v = str(value)
    return v[:keep] + "*" * max(0, len(v) - keep * 2) + v[-keep:] if len(v) > keep * 2 else "*" * len(v)


def parse_conn(path: Path) -> dict[str, str]:
    """从凭据卡解析 host/port/user 与公钥指纹（不输出公钥内容）。"""
    lines = [l.rstrip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    label_map = {
        "ip": "host", "服务器ip": "host", "地址": "host", "host": "host", "主机": "host",
        "端口": "port", "port": "port", "ssh端口": "port",
        "用户名": "user", "user": "user", "账号": "user", "用户": "user",
    }
    fields: dict[str, str] = {}
    for i, line in enumerate(lines):
        label = line.strip().rstrip("：:").lower().replace(" ", "")
        key = label_map.get(label)
        if key and i + 1 < len(lines):
            val = lines[i + 1].strip()
            if val and not (re.search(r"[\u4e00-\u9fff]", val) and val.rstrip("：:").lower().replace(" ", "") in label_map):
                fields.setdefault(key, val)
    if "host" not in fields:
        for val in lines:
            if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", val.strip()):
                fields["host"] = val.strip()
                break
    # 凭据卡公钥指纹（ssh-keygen 风格 base64 SHA256）
    m = re.search(r"\b(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp\d+)\s+([A-Za-z0-9+/=]{20,})", "\n".join(lines))
    if m:
        blob = base64.b64decode(m.group(2))
        fields["cred_pub_fp"] = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
        fields["cred_pub_algo"] = m.group(1)
    return fields


def key_fp(pkey) -> str:
    blob = base64.b64decode(pkey.get_base64())
    return base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def load_pem(path: Path):
    import paramiko
    text = path.read_text(encoding="utf-8", errors="replace")
    head = text.splitlines()[0].strip() if text.strip() else "<空文件>"
    pkey = None
    classes = [c for c in (getattr(paramiko, "RSAKey", None), getattr(paramiko, "Ed25519Key", None),
                           getattr(paramiko, "ECDSAKey", None)) if c]
    for cls in classes:
        try:
            pkey = cls.from_private_key(io.StringIO(text))
            break
        except Exception:
            continue
    return head, pkey


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pem", help="私钥文件路径（默认自动查找辅助资料目录 *.pem）")
    ap.add_argument("--password-file", help="密码文件路径（无可用私钥时的备选）")
    ap.add_argument("--cred", default=str(DEFAULT_CRED))
    args = ap.parse_args()

    conn = parse_conn(Path(args.cred))
    host, port = conn.get("host"), int(conn.get("port", "22"))
    user = conn.get("user", "ubuntu")

    import paramiko

    # --- 认证材料：pem 优先 ---
    pkey, pem_desc = None, None
    pem_candidates = [Path(args.pem)] if args.pem else sorted(DEFAULT_AUX.glob("*.pem"))
    for cand in pem_candidates:
        if not cand.exists():
            continue
        head, k = load_pem(cand)
        if k:
            pkey, pem_desc = k, f"{cand.name}（{head} → {k.get_name()}）"
            break
        elif head != "<空文件>":
            print(f"pem {cand.name}: 格式头 {head}，但加载失败（可能损坏或加密）")

    print("=== 连接参数（脱敏）===")
    print(f"host : {mask(host)}   port: {port}   user: {user}")

    auth_kwargs: dict = dict(hostname=host, port=port, username=user, timeout=15,
                             allow_agent=False, look_for_keys=False)
    if pkey:
        auth_kwargs["pkey"] = pkey
        print(f"auth : 私钥 {pem_desc}")
        cred_fp = conn.get("cred_pub_fp")
        my_fp = key_fp(pkey)
        if cred_fp:
            ok = my_fp == cred_fp
            print(f"配对校验: {'✅ 与凭据卡公钥配对' if ok else '❌ 与凭据卡公钥不匹配'}")
            print(f"  私钥公钥指纹 : SHA256:{my_fp}")
            print(f"  凭据卡公钥指纹: SHA256:{cred_fp}（{conn.get('cred_pub_algo')}）")
            if not ok:
                print("结论: 私钥与凭据卡公钥不是同一密钥对，先停止连接，向用户确认。")
                return 4
        else:
            print("配对校验: 凭据卡无公钥可比对，跳过（直接尝试连接）")
    elif args.password_file:
        pw = next((l.strip() for l in Path(args.password_file).read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()), None)
        if not pw:
            print("结果: 失败 — 密码文件为空")
            return 1
        auth_kwargs["password"] = pw
        print("auth : 密码（已读取，不回显）")
    else:
        print("结果: 失败 — 未找到可加载的 .pem 私钥，也未提供 --password-file")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(**auth_kwargs)
    except paramiko.AuthenticationException:
        print("结果: 失败 — AuthenticationException。私钥配对但服务器未授权该公钥？核对绑定密钥时指定的用户名。")
        return 2
    except Exception as e:
        print(f"结果: 失败 — {type(e).__name__}")
        return 3

    print("\n结果: ✅ SSH 连接建立")
    cmds = [
        ("whoami", "whoami 2>/dev/null | tr -d '\\n'"),
        ("os", ". /etc/os-release 2>/dev/null; echo ${PRETTY_NAME:-unknown} | tr -d '\\n'"),
        ("uname", "uname -srmo 2>/dev/null | tr -d '\\n'"),
        ("python", "python3 --version 2>&1 | tr -d '\\n'"),
        ("pip", "python3 -m pip --version 2>&1 | head -1"),
        ("git", "git --version 2>&1 | tr -d '\\n'"),
        ("node", "node --version 2>&1 | tr -d '\\n'"),
        ("docker", "docker --version 2>&1 | tr -d '\\n'"),
        ("disk", "df -h / 2>/dev/null | tail -1 | tr -s ' '"),
        ("mem", "free -h 2>/dev/null | grep -i '^Mem' | tr -s ' '"),
        ("cpu", "nproc 2>/dev/null | tr -d '\\n'"),
    ]
    print("\n=== 服务器脱敏指纹 ===")
    try:
        for label, cmd in cmds:
            _in, out, _err = client.exec_command(cmd, timeout=10)
            print(f"{label:8}: {out.read().decode('utf-8', 'replace').strip()[:120]}")
    finally:
        client.close()
        print("\n(连接已关闭；私钥/密码未写入任何日志)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
