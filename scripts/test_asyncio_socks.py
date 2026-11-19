import asyncio, re
from pathlib import Path

cred = [l for l in Path.home().joinpath(".pandatrack-secrets/udealproxy.txt").read_text().splitlines()
        if re.match(r"^us\.udealproxy\.com:6666:userId-[^:]+-region-us:[^:]+$", l.strip())][0]
host, port, user, pwd = cred.strip().split(":")


async def t():
    r, w = await asyncio.open_connection("us.udealproxy.com", 6666)
    w.write(b"\x05\x01\x02")
    await w.drain()
    resp = await r.readexactly(2)
    print("协商回复:", resp.hex())
    u, p = user.encode(), pwd.encode()
    w.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
    await w.drain()
    auth = await r.readexactly(2)
    print("认证回复:", auth.hex())
    d = b"www.usps.com"
    w.write(b"\x05\x01\x00\x03" + bytes([len(d)]) + d + (443).to_bytes(2, "big"))
    await w.drain()
    rep = await r.readexactly(4)
    print("CONNECT REP:", rep.hex())
    w.close()


asyncio.run(t())
print("OK")
