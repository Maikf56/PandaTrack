# PandaTrack 部署指南（新服务器从零到可访问）

> 日常更新只需在服务器仓库根目录执行 `bash scripts/deploy.sh`。
> 本文档只覆盖**新服务器首次初始化**。

## 0. 目标形态（01 §3.2 形态 A：同机同域）

| 组件 | 形态 |
|---|---|
| 客户端 | https://pandatrack.ginzavog.com → nginx 静态 `/var/www/pandatrack/client` + `/api/` 反代 127.0.0.1:8100 |
| 管理端 | https://pandaadmin.ginzavog.com → nginx 静态 `/var/www/pandatrack/admin` |
| API | systemd `pandatrack-api`（uvicorn，仅回环 8100） |
| 采集 | systemd `pandatrack-worker`（20s/轮）+ `pandatrack-relay`（本机 socks5 出口） |
| 巡检 | systemd `pandatrack-health.timer`（每小时） |

## 1. 系统依赖（Ubuntu 22.04/24.04）

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip \
    postgresql postgresql-contrib nginx git rsync curl
# Node.js 20+
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs
```

## 2. PostgreSQL 双库

```bash
sudo -u postgres psql -c "CREATE USER pandatrack WITH PASSWORD '<PW>';"
sudo -u postgres createdb -O pandatrack pandatrack_a
sudo -u postgres createdb -O pandatrack pandatrack_b
```

## 3. 代码与配置

```bash
git clone <REPO_URL> ~/pandatrack && cd ~/pandatrack
python3.12 -m venv .venv && .venv/bin/pip install -e .
```

创建 `.env`（必填键，`deploy.sh` 会校验）：

```ini
DATABASE_A_URL=postgresql+psycopg://pandatrack:<PW>@127.0.0.1:5432/pandatrack_a
DATABASE_B_URL=postgresql+psycopg://pandatrack:<PW>@127.0.0.1:5432/pandatrack_b
PT_DB_A_URL=postgresql+psycopg://pandatrack:<PW>@127.0.0.1:5432/pandatrack_a
PT_DB_B_URL=postgresql+psycopg://pandatrack:<PW>@127.0.0.1:5432/pandatrack_b
# 可选：防测试单号触发真实采集（逗号分隔）
PT_ENQUEUE_SKIP_NUMBERS=
```

## 4. DNS 与证书

- `pandatrack.ginzavog.com` / `pandaadmin.ginzavog.com` A 记录指向服务器 IP。
- 证书上传到 `/etc/nginx/certs/ginzavog-fullchain.pem` + `ginzavog-privkey.pem`
  （或用 certbot 签发后改 conf 路径）。

## 5. 采集运行时（可选，无它则仅入队不采集）

- ClawBrowser + clawctl 安装（`~/.local/bin/clawctl`），`clawctl config set --api-key <KEY>`。
- 本机出口 relay：`systemd pandatrack-relay`（scripts/local_relay.py）。
- 自签证书：`~/.pandatrack-secrets/geo.crt`。

## 6. 一键部署

```bash
bash scripts/deploy.sh
```

脚本按序完成：前置检查 → git pull → Python 依赖 → 幂等迁移(A/B) →
前端构建发布 → systemd 安装重启 → nginx 站点 → 冒烟（服务状态 + 双域名 200）。

## 7. 首个账号

- 管理端：向 `admin_user` 插入一行（`BRepository.hash_password()` 生成 scrypt 哈希）。
- 客户端：`customer` + `wallet` 各一行；或直接走前端注册接口。

## 8. 迁移旧服务器数据（可选）

```bash
# 旧机导出
pg_dump -Fc pandatrack_a > a.dump && pg_dump -Fc pandatrack_b > b.dump
# 新机导入
pg_restore -O -d pandatrack_a a.dump && pg_restore -O -d pandatrack_b b.dump
```

## 9. 验收清单

- [ ] `systemctl is-active pandatrack-api pandatrack-worker pandatrack-relay` 全 active
- [ ] `curl -sk https://pandatrack.ginzavog.com/api/v1/...` 鉴权 401（链路通）
- [ ] 双域名首页 200、静态资源 200
- [ ] `journalctl -u pandatrack-worker -f` 每 20s 一轮 cycle 报告
- [ ] 管理端/客户端登录成功
