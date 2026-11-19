#!/bin/bash
# 轮询等待 Akamai 挑战完成并抓取结果
CLAW="$HOME/tools/clawctl-linux-amd64/clawctl"
for i in $(seq 1 8); do
  sleep 12
  out=$("$CLAW" --profile smoke1 eval 'JSON.stringify({len: document.body.innerText.length, abck_neg: document.cookie.includes("~-1~"), href: location.href.slice(0, 60)})' 2>/dev/null | tail -1)
  echo "[#$i] $out"
  echo "$out" | grep -q '"len":0' && continue
  echo "=== 页面有内容 ==="
  break
done
echo "--- 正文前500 ---"
"$CLAW" --profile smoke1 eval 'document.body.innerText.slice(0, 500)' 2>/dev/null | tail -2
echo "--- 事件结构 ---"
"$CLAW" --profile smoke1 eval 'JSON.stringify({tb: document.querySelectorAll(".tb-step").length, ps: document.querySelectorAll(".product_summary").length})' 2>/dev/null | tail -2
