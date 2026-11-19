#!/usr/bin/env python3
"""本地中转 socks5 代理 + geo 服务本地应答（解决 clawctl geo 预检对
ipinfo.io/ipapi.co 的间歇性 406/429 依赖）。

设计：
- 监听 127.0.0.1:1080（无认证 socks5）。
- CONNECT 目标为 ipinfo.io:443 / ipapi.co:443 → 本地 8443 应答（TLS 自签证书，
  返回真实出口 geo JSON，缓存复用保证 clawctl 多次探测结果一致）。
- 其余 CONNECT → udealproxy 粘IP出口（Socks5 认证中转），浏览器实际流量走住宅池。

启动前置：服务器上已生成 CA 并装入系统信任（Go 程序读系统 CA 池）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from pathlib import Path

import requests

LOG = logging.getLogger("local_relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

LISTEN = ("127.0.0.1", 1080)
CERT_FILE = Path.home() / ".pandatrack-secrets" / "geo.crt"
KEY_FILE = Path.home() / ".pandatrack-secrets" / "geo.key"

UP_HOST, UP_PORT = "us.udealproxy.com", 6666
UP_USER, UP_PASS = "", ""  # main() 注入：粘IP会话，geo 与浏览器流量同出口
GEO_CACHE_TTL = 25 * 60  # 与粘IP窗口一致，保证探测结果稳定

GEO_HOSTS = {"ipinfo.io": 8443, "ipapi.co": 8444}

_geo_cache: dict = {"data": None, "at": 0.0}


def _base_credentials() -> tuple[str, str]:
    """按 PT_PROXY_REGION 选州级出口线路（02 §5.8 换出口回炉）。

    默认 us（泛美）；设为 us_texas / us_ohio 等可轮换州级池。区域值来自
    环境变量，改出口只需重启 relay（systemd EnvironmentFile），不碰 profile。
    """
    import os
    import re
    from pathlib import Path as P
    region = os.environ.get("PT_PROXY_REGION", "us")
    cred = P.home() / ".pandatrack-secrets" / "udealproxy.txt"
    # 凭据用户名形如 userId-<acct>-region-<region>[-session-xxx]
    pat = re.compile(
        rf"^us\.udealproxy\.com:6666:(userId-[^:]*-region-{re.escape(region)}):([^:]+)$")
    for l in cred.read_text().splitlines():
        m = pat.match(l.strip())
        if m:
            LOG.info("选用出口区域: %s", region)
            return m.group(1), m.group(2)
    raise SystemExit(f"未找到 udealproxy 区域 {region} 的凭据")


def get_sticky_proxy() -> dict:
    """使用与浏览器流量相同的粘IP会话（UP_USER），保证 geo 与出口一致。"""
    return {"http": f"socks5h://{UP_USER}:{UP_PASS}@{UP_HOST}:{UP_PORT}",
            "https": f"socks5h://{UP_USER}:{UP_PASS}@{UP_HOST}:{UP_PORT}"}


def fetch_geo() -> dict:
    """经粘IP出口查询真实出口 geo，要求美国住宅 IP；机房/非美则换会话重试。"""
    import secrets
    global UP_USER
    now = time.time()
    if _geo_cache["data"] and now - _geo_cache["at"] < GEO_CACHE_TTL:
        return _geo_cache["data"]
    base, pwd = _base_credentials()
    for attempt in range(1, 9):
        UP_USER = base + f"-session-{secrets.token_hex(3)}-sessTime-30"
        UP_PASS = pwd
        try:
            r = requests.get(
                "http://ip-api.com/json?fields=status,message,query,country,"
                "countryCode,region,regionName,city,timezone,isp,org,hosting",
                proxies=get_sticky_proxy(), timeout=20,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            j = r.json()
        except Exception as e:
            LOG.warning("geo 查询 #%d 失败: %s", attempt, e)
            time.sleep(1)
            continue
        if j.get("status") != "success":
            LOG.warning("geo 查询 #%d 接口失败: %s", attempt, j.get("message"))
            time.sleep(1)
            continue
        ok = (j.get("countryCode") == "US" and not j.get("hosting"))
        LOG.info("出口 #%d: ip=%s %s/%s hosting=%s isp=%s → %s",
                 attempt, j["query"], j.get("countryCode"), j.get("timezone"),
                 j.get("hosting"), j.get("isp"), "合格" if ok else "不合格,换会话")
        if ok:
            _geo_cache["data"] = j
            _geo_cache["at"] = now
            return j
        time.sleep(1)
    raise RuntimeError("8 次尝试均未获得美国住宅出口")
    return j


def geo_payload(host: str) -> bytes:
    g = fetch_geo()
    if host == "ipinfo.io":
        body = {
            "ip": g["query"], "city": g["city"], "region": g["regionName"],
            "country": g["countryCode"], "countryCode": g["countryCode"],
            "loc": f"{g.get('lat', 0)},{g.get('lon', 0)}",
            "timezone": g["timezone"], "org": g.get("org", g.get("isp", "")),
        }
    else:  # ipapi.co
        body = {
            "ip": g["query"], "version": "IPv4", "city": g["city"],
            "region": g["regionName"], "region_code": g["region"][:2] if g.get("region") else "",
            "country": g["countryCode"], "country_name": g["country"],
            "continent_code": "NA", "latitude": g.get("lat"), "longitude": g.get("lon"),
            "timezone": g["timezone"], "org": g.get("org", g.get("isp", "")),
            "asn": "", "currency": "USD", "languages": "en", "country_code": g["countryCode"],
        }
    return json.dumps(body).encode()


async def handle_geo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                     host: str):
    """本地 HTTPS geo 应答（外层已 TLS 解包）。极简 HTTP/1.1 处理。"""
    try:
        while True:
            line = await reader.readline()
            if not line:
                return
            if line in (b"\r\n", b"\n"):
                break
        body = geo_payload(host)
        head = ("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()
        writer.write(head + body)
        await writer.drain()
    except Exception as e:
        LOG.warning("geo 应答失败(%s): %s", host, e)
    finally:
        writer.close()


async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter):
    try:
        while True:
            data = await r.read(65536)
            if not data:
                break
            w.write(data)
            await w.drain()
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def upstream_connect(host: str, port: int) -> tuple[asyncio.StreamReader,
                                                           asyncio.StreamWriter]:
    """经 udealproxy socks5 建立 CONNECT 隧道（RFC 1929 认证）。"""
    r, w = await asyncio.open_connection(UP_HOST, UP_PORT)
    w.write(b"\x05\x01\x02")  # 用户名密码认证
    await w.drain()
    resp = await r.readexactly(2)
    LOG.info("上游协商: %s", resp.hex())
    if resp[1] != 0x02:
        raise RuntimeError(f"上游方法协商失败: {resp!r}")
    u = UP_USER.encode()
    p = UP_PASS.encode()
    w.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
    await w.drain()
    auth = await r.readexactly(2)
    LOG.info("上游认证: %s (user_len=%d)", auth.hex(), len(u))
    if auth[1] != 0x00:
        raise RuntimeError("上游认证失败")
    d = host.encode()
    w.write(b"\x05\x01\x00\x03" + bytes([len(d)]) + d + port.to_bytes(2, "big"))
    await w.drain()
    rep = await r.readexactly(4)
    LOG.info("上游CONNECT %s:%s REP=%s", host, port, rep.hex())
    if rep[1] != 0x00:
        raise RuntimeError(f"上游 CONNECT 失败 REP={rep[1]}")
    atyp = rep[3]
    if atyp == 1:            # BND.ADDR(4) + BND.PORT(2)
        await r.readexactly(6)
    elif atyp == 3:          # LEN + ADDR + PORT
        n = (await r.readexactly(1))[0]
        await r.readexactly(n + 2)
    elif atyp == 4:          # ADDR(16) + PORT(2)
        await r.readexactly(18)
    return r, w


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        ver, n = await reader.readexactly(2)
        methods = await reader.readexactly(n)
        if 0x00 not in methods:
            writer.write(b"\x05\xff")
            await writer.drain()
            return
        writer.write(b"\x05\x00")
        await writer.drain()
        hdr = await reader.readexactly(4)
        if hdr[1] != 1:  # 仅支持 CONNECT
            writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
            await writer.drain()
            return
        atyp = hdr[3]
        if atyp == 3:
            n = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(n)).decode()
        elif atyp == 1:
            host = ".".join(str(b) for b in await reader.readexactly(4))
        else:
            import socket
            host = socket.inet_ntoa(await reader.readexactly(4))  # IPv6 简化拒绝
            return
        port = int.from_bytes(await reader.readexactly(2), "big")

        if host in GEO_HOSTS and port == 443:
            lr, lw = await asyncio.open_connection("127.0.0.1", GEO_HOSTS[host])
            writer.write(b"\x05\x00\x00\x01" + b"\x00" * 4 + (8443).to_bytes(2, "big"))
            await writer.drain()
            LOG.info("geo 截胡: %s", host)
            await asyncio.gather(pipe(reader, lw), pipe(lr, writer))
            return

        ur, uw = await upstream_connect(host, port)
        writer.write(b"\x05\x00\x00\x01" + b"\x00" * 4 + (1080).to_bytes(2, "big"))
        await writer.drain()
        await asyncio.gather(pipe(reader, uw), pipe(ur, writer))
    except Exception as e:
        LOG.warning("会话失败: %s %s", type(e).__name__, e)
        try:
            writer.write(b"\x05\x01\x00\x01" + b"\x00" * 6)
            await writer.drain()
        except Exception:
            pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    global UP_USER, UP_PASS
    UP_PASS = _base_credentials()[1]
    # fetch_geo 负责生成粘IP会话（要求美国住宅出口），geo 与浏览器流量同会话
    g = fetch_geo()
    LOG.info("geo 预热完成: %s (%s/%s)", g["query"], g["countryCode"], g["timezone"])

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)

    async def tls_geo(reader, writer):
        try:
            inner_r, inner_w = await ctx.start_server(lambda: None).__await__() if False else (None, None)
        except Exception:
            pass
    # TLS 层：用 ssl 协议包装 —— asyncio.start_server 的 ssl 参数直接做
    server = await asyncio.start_server(handle_client, *LISTEN)
    tls1 = await asyncio.start_server(lambda r, w: handle_geo(r, w, "ipinfo.io"),
                                      "127.0.0.1", 8443, ssl=ctx)
    tls2 = await asyncio.start_server(lambda r, w: handle_geo(r, w, "ipapi.co"),
                                      "127.0.0.1", 8444, ssl=ctx)
    LOG.info("中转就绪: socks5://%s:%s  geo(ipinfo)=8443 geo(ipapi)=8444", *LISTEN)
    async with server, tls1, tls2:
        await asyncio.gather(server.serve_forever(), tls1.serve_forever(),
                             tls2.serve_forever())


if __name__ == "__main__":
    asyncio.run(main())
