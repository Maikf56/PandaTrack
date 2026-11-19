#!/usr/bin/env python3
"""验证 ClawBrowser 依赖的地理查询服务经代理的真实返回（定位启动失败根因）。"""
import re, time
from pathlib import Path
import requests

CRED = Path.home() / ".pandatrack-secrets" / "udealproxy.txt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
line = next(l for l in CRED.read_text().splitlines()
            if re.match(r"^[a-zA-Z0-9._-]+:[0-9]+:[^:]+:[^:]+$", l.strip()))
host, port, user, pwd = line.strip().split(":")
proxies = {"http": f"socks5h://{user}:{pwd}@{host}:{port}",
           "https": f"socks5h://{user}:{pwd}@{host}:{port}"}

for url in ["https://ipinfo.io/json", "https://ipapi.co/json/",
            "https://www.usps.com/"]:
    try:
        r = requests.get(url, proxies=proxies, timeout=20,
                         headers={"User-Agent": UA})
        body = r.text[:200].replace("\n", " ")
        print(f"{url}\n  HTTP {r.status_code} ctype={r.headers.get('content-type')} body[:200]={body!r}\n")
    except Exception as e:
        print(f"{url}\n  EXC {type(e).__name__}: {e}\n")
    time.sleep(1)
