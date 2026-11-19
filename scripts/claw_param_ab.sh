#!/bin/bash
# 双参数对照实测: tLabels vs qtc_tLabels1（裁定 USPS轨迹爬虫技术方案分析.md §2.3 的冲突）
# 判别标准: 页面 .tracking-number 是否包含我们的单号 + 事件块数量。
# 输出脱敏: 单号只显示前6位。
set -u
CLAW="$HOME/tools/clawctl-linux-amd64/clawctl"
tno=$(head -1 "$HOME/.pandatrack-secrets/sample_tracking.txt" | tr -d '\r')
echo "样本单号: ${tno:0:6}...(长度${#tno})"

mask() { sed -E "s/${tno:0:6}[A-Za-z0-9]*/${tno:0:6}***/g"; }

echo "--- 步骤1: 首页暖场 ---"
"$CLAW" --profile smoke1 open 'https://www.usps.com/' 2>&1 | grep -viE 'warning' | tail -1
sleep 8
"$CLAW" --profile smoke1 eval 'JSON.stringify({homeLen:document.body?document.body.innerText.length:0})' 2>&1 | grep -viE 'warning' | tail -1

run_variant() {
  local param="$1"
  local url="https://tools.usps.com/go/TrackConfirmAction?${param}=${tno}"
  echo "--- 变体: ${param} ---"
  "$CLAW" --profile smoke1 open "$url" 2>&1 | grep -viE 'warning' | tail -1
  sleep 12
  echo -n "title: "; "$CLAW" --profile smoke1 eval "document.title" 2>&1 | grep -viE 'warning' | tail -1 | mask
  "$CLAW" --profile smoke1 eval "JSON.stringify({param:'${param}', tn:(document.querySelector('.tracking-number')||{textContent:''}).textContent.trim(), tn_steps:document.querySelectorAll('.tb-step').length, summaries:document.querySelectorAll('.product_summary').length, bodyLen:document.body?document.body.innerText.length:0})" 2>&1 | grep -viE 'warning' | tail -1 | mask
}

# 顺序: tLabels → qtc_tLabels1 → 再跑一次 tLabels（排除顺序/缓存效应）
run_variant tLabels
run_variant qtc_tLabels1
run_variant tLabels
