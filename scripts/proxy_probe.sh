#!/bin/bash
# L1 代理出口探测：经 udealproxy Socks5 验证出口 IP 与 USPS 首页可达性
# 用法: proxy_probe.sh <区域过滤正则，留空测全部>
# 输出: 区域名 | 出口IP/国家 | USPS首页HTTP码 | 耗时。不输出凭据。
set -u
CRED="$HOME/.pandatrack-secrets/udealproxy.txt"
FILTER="${1:-}"
PASS_COUNT=0; TOTAL=0
while IFS=: read -r host port user pass; do
  [ -z "$host" ] && continue
  region="${user##*-region-}"
  if [ -n "$FILTER" ] && ! echo "$region" | grep -qE "$FILTER"; then continue; fi
  TOTAL=$((TOTAL+1))
  t0=$(date +%s%3N)
  ipinfo=$(curl -sS --max-time 15 --socks5-hostname "$host:$port" \
    -U "$user:$pass" https://ipinfo.io/json 2>&1 | head -c 300)
  t1=$(date +%s%3N)
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 25 \
    --socks5-hostname "$host:$port" -U "$user:$pass" \
    -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' \
    https://www.usps.com/ 2>/dev/null)
  t2=$(date +%s%3N)
  ip=$(echo "$ipinfo" | grep -o '"ip":"[^"]*"' | cut -d'"' -f4)
  country=$(echo "$ipinfo" | grep -o '"country":"[^"]*"' | cut -d'"' -f4)
  err=""
  echo "$ipinfo" | grep -q '"ip"' || err="IP查询失败"
  ok="FAIL"
  if [ "$code" = "200" ] && [ "$country" = "US" ]; then ok="PASS"; PASS_COUNT=$((PASS_COUNT+1)); fi
  printf '%-14s ip=%-16s country=%-4s usps_home=%s  ip查询=%sms 首页=%sms %s %s\n' \
    "$region" "${ip:--}" "${country:--}" "${code:-ERR}" "$((t1-t0))" "$((t2-t1))" "$ok" "$err"
done < "$CRED"
echo "----"
echo "通过: $PASS_COUNT / $TOTAL"
