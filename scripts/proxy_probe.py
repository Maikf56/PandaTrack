#!/usr/bin/env python3
"""L1 完整探测: 14 区域出口 IP 地理 + USPS 首页/跟踪页可达性。
输出仅含区域/IP地理/HTTP码/耗时，不回显凭据。"""
import re, sys, time, json
from pathlib import Path
import requests

CRED = Path.home() / ".pandatrack-secrets" / "udealproxy.txt"
TRACK_FILE = Path.home() / ".pandatrack-secrets" / "sample_tracking.txt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

lines = [l for l in CRED.read_text().splitlines()
         if re.match(r"^[a-zA-Z0-9._-]+:[0-9]+:[^:]+:[^:]+$", l.strip())]
filt = sys.argv[1] if len(sys.argv) > 1 else ""
proxy_url_cache = {}
results = []

sample_no = ""
if TRACK_FILE.exists():
    sample_no = TRACK_FILE.read_text().split()[0].strip()

for l in lines:
    host, port, user, pwd = l.strip().split(":")
    region = user.rsplit("-region-", 1)[-1]
    if filt and not re.search(filt, region):
        continue
    pu = f"socks5h://{user}:{pwd}@{host}:{port}"
    proxies = {"http": pu, "https": pu}
    row = {"region": region, "ip": None, "geo": None, "home": None,
           "track": None, "ip_ms": None, "home_ms": None}
    try:
        t0 = time.time()
        r = requests.get("https://ipinfo.io/json", proxies=proxies, timeout=20,
                         headers={"User-Agent": UA})
        row["ip_ms"] = int((time.time() - t0) * 1000)
        j = r.json()
        row["ip"] = j.get("ip")
        row["geo"] = f"{j.get('country')}/{j.get('region','')}/{j.get('city','')}"
    except Exception as e:
        row["geo"] = f"ERR:{type(e).__name__}"
    try:
        t0 = time.time()
        r = requests.get("https://www.usps.com/", proxies=proxies, timeout=25,
                         headers={"User-Agent": UA})
        row["home_ms"] = int((time.time() - t0) * 1000)
        row["home"] = r.status_code
    except Exception as e:
        row["home"] = f"ERR:{type(e).__name__}"
    if sample_no:
        try:
            r = requests.get(
                f"https://tools.usps.com/go/TrackConfirmAction?tLabels={sample_no}",
                proxies=proxies, timeout=30, headers={"User-Agent": UA})
            row["track"] = r.status_code
            row["track_len"] = len(r.text)
            row["track_has_js"] = "_arms" in r.text or "akam" in r.text.lower()
        except Exception as e:
            row["track"] = f"ERR:{type(e).__name__}"
    results.append(row)
    print(f"{region:<14} ip={row['ip'] or '-':<16} geo={row['geo'] or '-':<28} "
          f"home={row['home']:<8} ip查询={row['ip_ms'] or '-':>5}ms 首页={row['home_ms'] or '-':>5}ms "
          f"跟踪页={row.get('track','-')} 字节数={row.get('track_len','-')}")
    time.sleep(1)

ok = [r for r in results if r["home"] == 200]
print("----")
print(f"区域总数={len(results)} 首页200={len(ok)}")
if sample_no:
    print(f"样本单号: {sample_no[:8]}...(已脱敏)")
