"""SSE 真推送基础设施：PG LISTEN/NOTIFY → 进程内扇出（09 §3.1）。

链路：B 库触发器 trg_projection_event_notify 在 projection_event 新行时
pg_notify('pandatrack_projection', 定位载荷) → PgListener 后台线程的
LISTEN 连接收到 → NotifierHub 按 customer_id 扇出到订阅的 asyncio.Queue
→ events 路由即时取行推送。

设计要点：
- NOTIFY 载荷只含定位信息（event_id/operation_id/customer_id），事件正文
  由 BFF 按租户权限回读 projection_event（同库所有会话都能收 NOTIFY，
  正文不能放进载荷）；
- 断线自动重连；监听不可用时 events 路由自动降级回轮询（不丢事件，
  Last-Event-ID 游标语义不变）；
- Hub 与载荷解析是纯逻辑，可离线单测。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

import asyncio

log = logging.getLogger("pandatrack.api.notify")

DEFAULT_CHANNEL = "pandatrack_projection"


class NotifierHub:
    """customer_id → 订阅队列注册表；dispatch 由监听线程跨线程调用。"""

    def __init__(self) -> None:
        self._subs: dict[int, list[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---- 生命周期 ----
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定事件循环（应用启动时调用一次）。"""
        self._loop = loop

    # ---- 订阅（事件循环线程内调用）----
    def subscribe(self, customer_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(customer_id, []).append(q)
        return q

    def unsubscribe(self, customer_id: int, q: asyncio.Queue) -> None:
        queues = self._subs.get(customer_id)
        if queues and q in queues:
            queues.remove(q)
            if not queues:
                self._subs.pop(customer_id, None)

    # ---- 扇出（监听线程内调用，跨线程投递）----
    def dispatch(self, customer_id: int, payload: dict) -> int:
        """向该客户的全部订阅投递；返回投递的订阅数（0=无人订阅）。"""
        queues = self._subs.get(customer_id)
        if not queues:
            return 0
        loop = self._loop
        for q in queues:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(q.put_nowait, payload)
            else:  # 降级：测试/无循环环境直接投递
                q.put_nowait(payload)
        return len(queues)

    @property
    def subscriber_count(self) -> int:
        return sum(len(qs) for qs in self._subs.values())


def parse_notification(raw: str | None) -> tuple[int, dict] | None:
    """解析 NOTIFY 载荷 → (customer_id, payload)；损坏载荷返回 None（不投递）。

    payload 只含定位信息；customer_id 缺失按 0 处理（无人订阅即自然丢弃）。
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        customer_id = int(data.get("customer_id") or 0)
    except (ValueError, TypeError):
        return None
    return customer_id, data


class PgListener:
    """后台线程：LISTEN 通道 → hub.dispatch；断线指数退避重连。

    psycopg3 官方模式：for n in conn.notifies() 迭代通知（生成器内部处理
    socket 等待）。stop() 通过关闭连接打断阻塞的迭代器。
    connect 可注入（离线测试）；线程体不单测（由真实库集成测试覆盖触发
    器→LISTEN 全链路）。
    """

    def __init__(self, dsn: str, hub: NotifierHub, *,
                 channel: str = DEFAULT_CHANNEL,
                 connect: Callable[[str], Any] | None = None,
                 backoff_base: float = 1.0,
                 backoff_cap: float = 30.0,
                 logger=None) -> None:
        self._dsn = dsn
        self._hub = hub
        self._channel = channel
        self._connect = connect or _psycopg_connect
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._log = logger or log
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._conn: Any = None

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="pg-listener", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        conn = self._conn
        if conn is not None:  # 关闭连接打断阻塞的 notifies() 迭代
            try:
                conn.close()
            except Exception:
                pass
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=timeout)
        self._thread = None

    # ---- 载荷处理（纯逻辑，可单测）----
    def handle_notification(self, raw: str | None) -> int:
        """解析并扇出；返回投递数。损坏载荷静默忽略（计 0）。"""
        parsed = parse_notification(raw)
        if parsed is None:
            self._log.warning("malformed notification ignored")
            return 0
        customer_id, payload = parsed
        return self._hub.dispatch(customer_id, payload)

    # ---- 线程体 ----
    def _run(self) -> None:
        backoff = self._backoff_base
        while not self._stop.is_set():
            conn = None
            try:
                conn = self._connect(self._dsn)
                conn.autocommit = True
                self._conn = conn
                conn.execute(f"LISTEN {self._channel}")  # noqa: S608 通道名是常量
                backoff = self._backoff_base
                self._log.info("listening on %s", self._channel)
                for n in conn.notifies():
                    if n.channel == self._channel:
                        self.handle_notification(n.payload)
                    if self._stop.is_set():
                        break
            except Exception:
                if not self._stop.is_set():
                    self._log.exception("listener disconnected, retrying")
            finally:
                self._conn = None
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            if self._stop.is_set():
                break
            time.sleep(min(backoff, self._backoff_cap))
            backoff = min(backoff * 2, self._backoff_cap)


def _psycopg_connect(dsn: str) -> Any:
    import psycopg
    return psycopg.connect(dsn)


def make_listener(dsn: str, hub: NotifierHub, *,
                  channel: str = DEFAULT_CHANNEL) -> PgListener:
    return PgListener(dsn, hub, channel=channel)
