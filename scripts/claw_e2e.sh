#!/bin/bash
# 端到端核心验证: 指纹会话 → USPS首页暖场(建立初始cookie) → 真实单号跟踪页 → L3解析
# 关键教训(2026-11-19): 跳过首页暖场直接打跟踪页必被 Akamai 硬拦(空正文+abck~-1~);
# 先 open www.usps.com 拿到正常首页(len>1000), 再 open 跟踪页即可拿到真实轨迹(tb>0)。
set -u
CLAW="$HOME/tools/clawctl-linux-amd64/clawctl"
tno=$(head -1 "$HOME/.pandatrack-secrets/sample_tracking.txt" | tr -d '\r')
url="https://tools.usps.com/go/TrackConfirmAction?tLabels=$tno"
echo "目标单号: ${tno:0:6}...(长度${#tno})"
echo "--- 步骤1: 首页暖场(建立 Akamai 初始会话) ---"
"$CLAW" --profile smoke1 open 'https://www.usps.com/' 2>&1 | grep -viE 'warning' | tail -1
sleep 8
"$CLAW" --profile smoke1 eval 'JSON.stringify({homeLen:document.body?document.body.innerText.length:0})' 2>&1 | grep -viE 'warning' | tail -1
echo "--- 步骤2: 带会话打开跟踪页 ---"
"$CLAW" --profile smoke1 open "$url" 2>&1 | grep -viE 'warning' | tail -2
echo "--- 等待页面加载（人类间隔）---"
sleep 12
echo "--- 页面标题 ---"
"$CLAW" --profile smoke1 eval "document.title" 2>&1 | grep -viE 'warning' | tail -2
echo "--- 正文摘要（判断 Akamai 拦截 or 真实轨迹）---"
"$CLAW" --profile smoke1 eval "document.body.innerText.slice(0, 600)" 2>&1 | grep -viE 'warning' | tail -4
echo "--- 事件块数量 ---"
"$CLAW" --profile smoke1 eval "JSON.stringify({tb_steps: document.querySelectorAll('.tb-step').length, summaries: document.querySelectorAll('.product_summary').length, tracking_number: (document.querySelector('.tracking-number')||{}).textContent})" 2>&1 | grep -viE 'warning' | tail -3
