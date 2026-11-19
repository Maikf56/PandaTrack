#!/bin/bash
# L2 冒烟: ClawBrowser 指纹会话 + udealproxy 代理 → 加载 USPS 跟踪页 → CDP 抓取验证
# 输出脱敏: 不回显代理凭据
set -u
CLAW="$HOME/tools/clawctl-linux-amd64/clawctl"
PROXY_CRED="$HOME/.pandatrack-secrets/udealproxy.txt"
TRACK_FILE="$HOME/.pandatrack-secrets/sample_tracking.txt"

# 1) 取泛美 session 粘IP行（L1 已实测可用）
pline=$(grep -E '^[a-zA-Z0-9._-]+:[0-9]+:.*-session-' "$PROXY_CRED" | head -1)
[ -z "$pline" ] && pline=$(grep -E '^[a-zA-Z0-9._-]+:[0-9]+:' "$PROXY_CRED" | head -1)
phost=$(echo "$pline" | cut -d: -f1)
pport=$(echo "$pline" | cut -d: -f2)
puser=$(echo "$pline" | cut -d: -f3)
ppass=$(echo "$pline" | cut -d: -f4)
echo "代理: $phost:$pport 用户前缀=$(echo "$puser" | cut -c1-20)... (粘IP行: $(echo "$puser" | grep -q session && echo 是 || echo 否))"

# 2) 取第一个真实单号
tno=$(head -1 "$TRACK_FILE" | tr -d '\r')
echo "样本单号: ${tno:0:6}...(长度${#tno})"

# 3) 创建指纹 profile（幂等：存在则复用）
export CLAWCTL_PROXY_PASSWORD="$ppass"
if ! "$CLAW" profiles inspect smoke1 >/dev/null 2>&1; then
  "$CLAW" profiles create smoke1 --manual-proxy --proxy-scheme socks5 \
    --proxy-host "$phost" --proxy-port "$pport" --proxy-username "$puser" \
    --country US 2>&1 | grep -v "$ppass" | tail -3
else
  echo "profile smoke1 已存在，复用"
fi

# 4) 启动会话并打开跟踪页
url="https://tools.usps.com/go/TrackConfirmAction?tLabels=$tno"
echo "--- 启动会话（首次需下载内核，可能较久）---"
"$CLAW" start --profile smoke1 --url "$url" --country US --no-remote --timeout 8m 2>&1 | tail -6

echo "--- endpoint ---"
"$CLAW" endpoint --profile smoke1 2>&1 | tail -2

echo "--- CDP 抓取页面状态 ---"
# 通过 clawctl eval 抓页面标题与正文片段，判断是否过 Akamai
"$CLAW" eval "JSON.stringify({title: document.title, url: location.href, len: document.body ? document.body.innerText.length : 0, snippet: document.body ? document.body.innerText.slice(0, 400) : ''})" 2>&1 | tail -5
