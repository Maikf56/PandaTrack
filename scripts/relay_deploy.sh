#!/bin/bash
# 部署本地中转为 systemd 服务并验证 geo 截胡链路
set -u
sudo tee /etc/systemd/system/pandatrack-relay.service > /dev/null <<'EOF'
[Unit]
Description=PandaTrack local relay (socks5 + geo answer)
After=network-online.target

[Service]
User=ubuntu
ExecStart=/home/ubuntu/pandatrack/.venv/bin/python /home/ubuntu/pandatrack/scripts/local_relay.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now pandatrack-relay 2>&1 | tail -1
sleep 3
systemctl is-active pandatrack-relay
echo "--- 服务日志 ---"
sudo journalctl -u pandatrack-relay -n 5 --no-pager | tail -5
echo "--- 验证 geo 截胡（经中转请求 ipinfo.io，应返回真实出口 JSON）---"
sudo apt-get install -y -qq curl socks 2>/dev/null | tail -1
curl -sS --max-time 15 --socks5-hostname 127.0.0.1:1080 https://ipinfo.io/json | head -c 300
echo
curl -sS --max-time 15 --socks5-hostname 127.0.0.1:1080 https://ipapi.co/json/ | head -c 300
echo
echo "--- 验证普通流量走代理出口 ---"
curl -sS --max-time 20 --socks5-hostname 127.0.0.1:1080 "http://ip-api.com/json?fields=query,countryCode,timezone" | head -c 200
echo
echo RELAY_TEST_DONE
