#!/bin/bash
# 核心链路端到端验证（方案 02 §5.8）：命中 challenge 即换州级出口回炉。
# - 每个候选出口：改 relay.env → 重启 relay（换 IP+指纹区域）→ 重开 USPS 跟踪页
# - 检测到 tb-step 事件块 = 越过 Akamai、取得真实轨迹 → 成功退出
# - 空标题+混淆脚本 / abck~-1~ = challenge → 换下一个出口，不原地等待
# 出口顺序按方案 02 §3.3 实测通过率：texas/ohio 优先，泛美兜底。
set -u
CLAW="$HOME/tools/clawctl-linux-amd64/clawctl"
ENVF="$HOME/.pandatrack-secrets/relay.env"
TRACK_FILE="$HOME/.pandatrack-secrets/sample_tracking.txt"
STATES=(us_texas us_ohio us_newjersey us_illinois us_virginia us)
tno=$(head -1 "$TRACK_FILE" | tr -d '\r')
url="https://tools.usps.com/go/TrackConfirmAction?tLabels=$tno"
echo "样本单号: ${tno:0:6}...(长度${#tno})"

for region in "${STATES[@]}"; do
  echo "===== 换出口: $region ====="
  echo "PT_PROXY_REGION=$region" > "$ENVF"
  sudo systemctl restart pandatrack-relay >/dev/null 2>&1
  sleep 6
  # 1) 确认 relay 拿到美国住宅出口（geo 预检本身就是出口校验）
  exit_ip=$(curl -s --socks5-hostname 127.0.0.1:1080 --max-time 15 https://ipinfo.io/json 2>/dev/null | grep -o '"country": *"[A-Z]*"' | head -1)
  echo "出口geo: ${exit_ip:-未知}"

  # 2) 重建浏览器会话（换出口必须新 profile 会话，指纹/出口/geo 三者一致）
  "$CLAW" stop smoke1 >/dev/null 2>&1
  "$CLAW" start --profile-hint smoke1 --url "$url" --no-remote --timeout 3m >/dev/null 2>&1
  sleep 12

  # 3) 页面分类：tb-step>0 为真实结果；否则读特征判 challenge/其他
  st=$("$CLAW" --profile smoke1 eval 'JSON.stringify({len:document.body?document.body.innerText.length:0,tb:document.querySelectorAll(".tb-step").length,title:document.title,abckNeg:document.cookie.includes("~-1~")})' 2>/dev/null | tail -1)
  echo "页面: $st"
  if echo "$st" | grep -q '"tb":[1-9]'; then
    echo "===== ✅ $region 取得真实轨迹 ====="
    echo "--- 正文前500 ---"
    "$CLAW" --profile smoke1 eval 'document.body.innerText.slice(0,500)' 2>/dev/null | tail -2
    exit 0
  fi
  echo "× $region 未取得轨迹（challenge/拒绝），换下一个出口"
done
echo "===== 全部出口均未通过（符合方案概率预期，需按 §5.8 多轮回炉） ====="
exit 2
