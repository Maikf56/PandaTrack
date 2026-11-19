#!/usr/bin/env python3
"""服务器连接诊断（脱敏）：核对用户名解析、本机私钥与凭据公钥是否配对。
只输出布尔结论与长度，不回显任何值。
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRED = ROOT / "开发文档" / "02_辅助资料" / "服务器SSH.txt"


def parse_fields():
    lines = [l.rstrip() for l in CRED.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    label_map = {"ssh端口": "port", "用户名": "user", "user": "user", "id/名称": "name", "公钥": "pubkey"}
    fields = {}
    for i, line in enumerate(lines):
        lab = line.strip().rstrip("：:").lower().replace(" ", "")
        if lab in label_map and i + 1 < len(lines):
            fields[label_map[lab]] = lines[i + 1].strip()
    for val in lines:
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", val.strip()):
            fields.setdefault("host", val.strip())
            break
    return fields


def derive_pub_from_priv(priv_path: Path) -> bytes | None:
    """从私钥文件派生 openssh 公钥 blob（不含注释）。"""
    import paramiko
    for cls in (getattr(paramiko, "Ed25519Key", None), getattr(paramiko, "RSAKey", None)):
        if not cls:
            continue
        try:
            k = cls.from_private_key_file(str(priv_path))
            return k.get_bytes()  # 原始公钥 blob
        except Exception:
            continue
    return None


def pub_blob_from_authorized(text: str) -> bytes | None:
    m = re.search(r"\b(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256)\s+([A-Za-z0-9+/=]+)", text)
    if not m:
        return None
    return base64.b64decode(m.group(1))


def main():
    f = parse_fields()
    user = f.get("user", "")
    print("=== 用户名解析 ===")
    print(f"user 长度={len(user)} 形态={'小写字母数字' if re.fullmatch(r'[a-z_][a-z0-9_-]*', user) else '非典型'}")

    cred_text = CRED.read_text(encoding="utf-8", errors="replace")
    cred_blob = pub_blob_from_authorized(cred_text)
    print("\n=== 公钥配对检查 ===")
    print(f"凭据文件含公钥: {'是' if cred_blob else '否'}")
    sshdir = Path.home().joinpath(".ssh")
    matched = None
    if sshdir.exists():
        for kf in list(sshdir.glob("*_ed25519")) + list(sshdir.glob("id_*")):
            if kf.name.endswith(".pub"):
                continue
            blob = derive_pub_from_priv(kf)
            if blob and cred_blob:
                ok = blob == cred_blob
                print(f"私钥 {kf.name}: {'与凭据公钥匹配' if ok else '不匹配'}")
                if ok:
                    matched = kf.name
    if not cred_blob:
        print("提示: 凭据文件未提取到标准公钥，可能无法自动比对。")
    print(f"\n结论: {'找到配对私钥 ' + matched if matched else '未找到与凭据公钥配对的私钥'}")


if __name__ == "__main__":
    main()
