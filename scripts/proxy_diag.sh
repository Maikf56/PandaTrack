#!/bin/bash
# SOCKS5 握手诊断（凭据脱敏：不回显 user/pass）
set -u
CRED="$HOME/.pandatrack-secrets/udealproxy.txt"
# 取第一条形如 域名:端口:用户:密码 的行（跳过中文标题行）
line=$(grep -E '^[a-zA-Z0-9._-]+:[0-9]+:' "$CRED" | head -1)
host=$(echo "$line" | cut -d: -f1)
port=$(echo "$line" | cut -d: -f2)
user=$(echo "$line" | cut -d: -f3)
pass=$(echo "$line" | cut -d: -f4)
echo "解析: host=$host port=$port user_prefix=$(echo "$user" | sed 's/custom-[0-9]*/custom-***/') pass_len=${#pass}"
echo "--- TCP 直连网关 ---"
timeout 8 bash -c "cat < /dev/null > /dev/tcp/$host/$port" && echo "TCP 可达" || echo "TCP 不可达"
echo "--- DNS ---"
getent hosts "$host" || echo "DNS 解析失败"
echo "--- curl SOCKS5 握手（详细，凭据已隐藏）---"
curl -v --max-time 20 --socks5-hostname "$host:$port" -U "$user:$pass" https://ipinfo.io/json 2>&1 \
  | sed "s/$user/***USER***/g; s/$pass/***PASS***/g" | tail -30
