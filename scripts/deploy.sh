#!/usr/bin/env bash
# PandaTrack 一键部署（在服务器仓库根目录执行）。
# 用法：
#   bash scripts/deploy.sh            # 完整部署（git pull + 迁移 + 构建 + 服务重启 + 冒烟）
#   SKIP_GIT_PULL=1 bash scripts/deploy.sh   # 跳过 git pull（本地改动调试用）
# 新服务器首次初始化（系统依赖/PostgreSQL/证书/DNS）见 docs/DEPLOY.md。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[警告]\033[0m %s\n' "$*"; }

# ---------- 0. 前置检查 ----------
log "0/7 前置检查"
for key in DATABASE_A_URL DATABASE_B_URL PT_DB_A_URL PT_DB_B_URL; do
  grep -q "^${key}=" .env || { echo "缺少 .env 键: ${key}"; exit 1; }
done
command -v python3 >/dev/null || { echo "缺少 python3"; exit 1; }
command -v npm >/dev/null    || { echo "缺少 npm（Node.js 20+）"; exit 1; }
[ -d .venv ] || { echo "缺少 .venv —— 先执行: python3 -m venv .venv && .venv/bin/pip install -e ."; exit 1; }
[ -f /etc/nginx/certs/ginzavog-fullchain.pem ] \
  || warn "未找到 TLS 证书 /etc/nginx/certs/ginzavog-fullchain.pem，nginx 步骤将跳过站点启用（先上传证书再重跑）"

# ---------- 1. 代码更新 ----------
log "1/7 代码更新"
if [ "${SKIP_GIT_PULL:-0}" = "1" ]; then
  echo "跳过 git pull"
else
  git pull --ff-only
fi

# ---------- 2. Python 依赖 ----------
log "2/7 Python 依赖同步"
.venv/bin/pip install -q -e .

# ---------- 3. 数据库迁移（幂等） ----------
log "3/7 数据库迁移"
url_a=$(grep '^DATABASE_A_URL=' .env | cut -d= -f2- | sed 's|postgresql+psycopg://|postgresql://|')
url_b=$(grep '^DATABASE_B_URL=' .env | cut -d= -f2- | sed 's|postgresql+psycopg://|postgresql://|')
.venv/bin/python scripts/migrate.py --database a --url "$url_a"
.venv/bin/python scripts/migrate.py --database b --url "$url_b"

# ---------- 4. 前端构建与发布 ----------
log "4/7 前端构建与发布"
(cd apps/web   && npm ci --no-audit --no-fund && npm run build)
(cd apps/admin && npm ci --no-audit --no-fund && npm run build)
sudo mkdir -p /var/www/pandatrack
sudo rsync -a --delete apps/web/dist/   /var/www/pandatrack/client/
sudo rsync -a --delete apps/admin/dist/ /var/www/pandatrack/admin/
sudo chown -R www-data:www-data /var/www/pandatrack

# ---------- 5. systemd 服务 ----------
log "5/7 systemd 服务安装与重启"
for unit in pandatrack-api.service pandatrack-worker.service pandatrack-health.service pandatrack-health.timer; do
  sudo cp "infra/systemd/$unit" /etc/systemd/system/
done
sudo systemctl daemon-reload
sudo systemctl enable --now pandatrack-api pandatrack-worker pandatrack-health.timer
sudo systemctl restart pandatrack-api pandatrack-worker
sudo systemctl restart pandatrack-health.timer 2>/dev/null || true

# ---------- 6. nginx ----------
log "6/7 nginx 站点"
if [ -f /etc/nginx/certs/ginzavog-fullchain.pem ]; then
  sudo cp infra/nginx/pandatrack.conf /etc/nginx/sites-available/pandatrack
  sudo ln -sf /etc/nginx/sites-available/pandatrack /etc/nginx/sites-enabled/pandatrack
  sudo nginx -t
  sudo systemctl reload nginx
else
  echo "跳过 nginx（证书缺失）"
fi

# ---------- 7. 冒烟 ----------
log "7/7 冒烟验证"
sleep 3
systemctl is-active pandatrack-api pandatrack-worker | sed 's/^/  service: /'
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/docs || true)
echo "  API /docs: $code"
for host in pandatrack.ginzavog.com pandaadmin.ginzavog.com; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' "https://$host/" --max-time 8 || true)
  echo "  https://$host/: $code"
done

log "部署完成。worker: journalctl -u pandatrack-worker -f"
