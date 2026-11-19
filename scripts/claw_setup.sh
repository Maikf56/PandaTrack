#!/bin/bash
# 逐行验证 ClawBrowser API key（不回显值），找到后执行安装
set -u
CRED="$HOME/.pandatrack-secrets/clawbrowser.txt"
CLAW=~/tools/clawctl-linux-amd64/clawctl
FOUND=""
i=0
while IFS= read -r line; do
  i=$((i+1))
  line=$(echo "$line" | tr -d '\r')
  [ -z "$line" ] && continue
  len=${#line}
  [ "$len" -lt 16 ] && { echo "行$i: 长度=$len 跳过(过短)"; continue; }
  "$CLAW" config set --api-key "$line" >/dev/null 2>&1
  id_out=$("$CLAW" identity 2>&1)
  if echo "$id_out" | grep -qiE 'valid|authenticated|account|email|ok'; then
    echo "行$i: 长度=$len → 有效 (identity: $(echo "$id_out" | head -1 | sed 's/[A-Za-z0-9._%+-]*@[A-Za-z0-9.-]*/***@***/g'))"
    FOUND="$line"
    break
  else
    echo "行$i: 长度=$len → 无效 ($(echo "$id_out" | head -1 | cut -c1-60))"
  fi
done < "$CRED"
if [ -z "$FOUND" ]; then
  echo "结果: 凭据文件中未找到有效 API key"
  exit 1
fi
echo "API_KEY 已配置（写入 clawctl config, mode 0600）"
"$CLAW" install --no-api-key-prompt 2>&1 | tail -8
