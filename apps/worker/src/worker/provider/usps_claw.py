"""ClawExecutor：ClawBrowser 采集执行器（模块 02 §3.1 / §3.3 / §5.8）。

把已验证的 claw_e2e.sh 产品化。设计要点：
- 命令执行层(CommandRunner)与 relay 控制层(RelayControl)可注入，使暖场、
  出口轮换、页面分类等核心逻辑可离线纯逻辑单测；真实执行注入
  SubprocessRunner / SystemdRelayControl 走服务器 clawctl。
- 首页暖场是强制前置（02 §66）：换出口/换环境重建会话后必须重新暖场。
- 命中 challenge 换州级出口回炉（§5.8），最多 max_exits 个候选；准入失败
  （网关不可达/探测失败）也换候选出口，但二者 error_class 不同。
- 证据脱敏：单号用 tracking_ref，出口/prof ile 只用引用，不落 Cookie/凭据/HTML。
"""
from __future__ import annotations

import json
import random
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from worker.provider.contracts import tracking_ref
from worker.provider.errors import ProviderError

USPS_HOME = "https://www.usps.com/"
# 查询参数名可配置（02 定稿实测 tLabels 可用；《爬虫方案分析》§2.3 称必须
# qtc_tLabels1，双参数对照实验因 ClawBrowser 流量额度暂缓）。恢复实测后
# 若裁定 qtc_tLabels1，改环境变量 PT_USPS_TRACK_PARAM 即可，无需改代码。
DEFAULT_TRACK_PARAM = "tLabels"


def _track_param() -> str:
    import os
    return os.environ.get("PT_USPS_TRACK_PARAM", DEFAULT_TRACK_PARAM).strip() or \
        DEFAULT_TRACK_PARAM


def track_url(numbers: list[str]) -> str:
    return ("https://tools.usps.com/go/TrackConfirmAction?"
            f"{_track_param()}={','.join(numbers)}")

# 州级出口优先顺序（02 §123 实测通过率：texas/ohio 约 2/5，加州/纽约/佛州 0/12）。
DEFAULT_STATES = (
    "us_texas", "us_ohio", "us_newjersey", "us_illinois", "us_virginia", "us",
)


@runtime_checkable
class CommandRunner(Protocol):
    """命令执行抽象：run(argv, timeout) -> stdout 文本。"""

    def run(self, argv: list[str], *, timeout: int = 60) -> str: ...


class SubprocessRunner:
    """真实执行：直接跑 clawctl（shell=False，参数不拼接，防注入）。"""

    def run(self, argv: list[str], *, timeout: int = 60) -> str:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        if cp.returncode != 0:
            raise ProviderError("browser_crash",
                                f"cmd failed rc={cp.returncode}: {shlex.join(argv[:3])}")
        return cp.stdout.strip()


@runtime_checkable
class RelayControl(Protocol):
    """出口控制抽象：换区域 + 读出口 geo。"""

    def switch_region(self, region: str) -> None: ...
    def exit_geo(self) -> dict: ...


class NoopRelayControl:
    """离线单测用：记录切换，返回合格美国住宅出口。"""

    def __init__(self) -> None:
        self.regions: list[str] = []

    def switch_region(self, region: str) -> None:
        self.regions.append(region)

    def exit_geo(self) -> dict:
        return {"countryCode": "US", "hosting": False, "query": "12.34.56.78"}


class SystemdRelayControl:
    """真实出口控制：改 relay.env → 重启 relay → 经 socks5 读出口 geo。

    与 claw_rotate.sh 已验证逻辑一致；出口引用脱敏，凭据不进入本类。
    """

    def __init__(self, *, env_file: str, service: str = "pandatrack-relay",
                 socks5: str = "127.0.0.1:1080", runner=None,
                 geo_cert: str | None = None) -> None:
        self.env_file = env_file
        self.service = service
        self.socks5 = socks5
        self._runner = runner or SubprocessRunner()
        # relay 对 ipinfo.io 做本地自签证书应答（scripts/local_relay.py），
        # exit_geo 必须信任该证书，否则 SSL 校验失败（P7-e2e 修复）。
        self.geo_cert = geo_cert or str(
            Path.home() / ".pandatrack-secrets" / "geo.crt")

    def switch_region(self, region: str) -> None:
        Path(self.env_file).write_text(f"PT_PROXY_REGION={region}\n", encoding="utf-8")
        self._runner.run(["sudo", "systemctl", "restart", self.service], timeout=30)

    def exit_geo(self) -> dict:
        import requests
        r = requests.get(
            "https://ipinfo.io/json",
            proxies={"http": f"socks5h://{self.socks5}",
                     "https": f"socks5h://{self.socks5}"},
            timeout=15,
            verify=self.geo_cert,
        )
        return r.json()


@dataclass(slots=True)
class CollectedPage:
    """一次页面取得结果（交给 Provider 做解析与闸门）。"""

    html: str
    http_status: int
    warmed_up: bool
    exit_region: str
    exit_ref: str            # 脱敏出口引用（geo ip 哈希片段）
    profile_ref: str
    exit_attempt: int        # 第几个候选出口取得
    collected_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ExecutorConfig:
    claw_bin: str = "clawctl"
    profile: str = "smoke1"
    states: tuple[str, ...] = DEFAULT_STATES
    warmup_wait_s: int = 8
    page_wait_s: int = 12
    switch_wait_s: int = 6
    max_exits: int = 5
    rotate_states: bool = True       # 每次换出口是否随机化州级池顺序
    ensure_session: bool = True      # 采集前自动拉起未运行的 profile 会话
    session_start_wait_s: int = 10   # start 后等待会话就绪


class ClawExecutor:
    """USPS 网页采集执行器（fail-closed：页面取不到就抛 ProviderError）。"""

    def __init__(self, runner: CommandRunner, relay: RelayControl,
                 *, config: ExecutorConfig | None = None,
                 sleeper=None, randomizer=None) -> None:
        self.runner = runner
        self.relay = relay
        self.cfg = config or ExecutorConfig()
        self._sleep = sleeper or time.sleep
        self._rand = randomizer or random.Random()
        self._warmed_regions: set[str] = set()  # 该出口是否已建立暖场会话

    # ---- 命令封装 ----
    def _claw(self, *args: str, timeout: int = 60) -> str:
        argv = [self.cfg.claw_bin, "--profile", self.cfg.profile, *args]
        return self.runner.run(argv, timeout=timeout)

    def _eval_json(self, js: str) -> dict:
        """eval 一个 JSON.stringify 表达式并解析；失败返回空 dict。

        clawctl eval 的输出是「JSON 字符串字面量再包一层」（带引号转义），
        需二次解析；一次解析后若仍是 str 继续解（P7-e2e 实测）。
        """
        raw = self._claw("eval", js, timeout=30)
        try:
            val = json.loads(raw.strip().splitlines()[-1])
            if isinstance(val, str):
                val = json.loads(val)
            return val if isinstance(val, dict) else {}
        except (ValueError, IndexError):
            return {}

    # ---- 出口准入（02 §3.1 三层）----
    def _switch_exit(self, region: str) -> None:
        self.relay.switch_region(region)
        self._sleep(self.cfg.switch_wait_s)
        self._warmed_regions.discard(region)  # 换出口后旧会话作废，需重新暖场

    def _exit_ok(self) -> bool:
        g = self.relay.exit_geo()
        return g.get("countryCode") == "US" and not g.get("hosting")

    # ---- 首页暖场（02 §66 强制前置）----
    def _warmup(self) -> bool:
        self._claw("open", USPS_HOME, timeout=60)
        self._sleep(self.cfg.warmup_wait_s)
        st = self._eval_json(
            "JSON.stringify({len:document.body?document.body.innerText.length:0})")
        return int(st.get("len", 0)) > 1000

    # ---- 跟踪页导航与抓取 ----
    def _open_tracking(self, numbers: list[str]) -> None:
        url = track_url(numbers)
        self._claw("open", url, timeout=90)
        self._sleep(self.cfg.page_wait_s)

    def _page_state(self) -> dict:
        return self._eval_json(
            "JSON.stringify({len:document.body?document.body.innerText.length:0,"
            "tb:document.querySelectorAll('.tb-step').length,"
            "ps:document.querySelectorAll('.product_summary').length,"
            "title:document.title,abckNeg:document.cookie.includes('~-1~')})")

    def _fetch_html(self) -> str:
        """抓取完整 DOM；eval 返回 JSON 字符串（带引号），需二次解析。"""
        raw = self._claw("eval", "document.documentElement.outerHTML", timeout=60)
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    # ---- 会话自愈 ----
    def _ensure_session(self) -> None:
        """profile 会话未运行则拉起（生产常驻形态必需，P7-e2e 教训）。

        status 输出含 'status: running' 即认为会话存活；clawctl 命令本身
        失败（如二进制缺失）不在此处拦截，交给上层错误分类。
        """
        if not self.cfg.ensure_session:
            return
        try:
            out = self._claw("status", timeout=30)
        except Exception:
            out = ""
        if "status: running" in out:
            return
        self._claw("start", timeout=90)
        self._sleep(self.cfg.session_start_wait_s)

    # ---- 主流程 ----
    def collect_page(self, numbers: list[str]) -> CollectedPage:
        """取得一页（≤35 单号）的真实 USPS 结果；全部候选失败则抛 ProviderError。

        流程（02 §3.1）：会话自愈 → 换出口 → 出口准入 → 首页暖场 →
        跟踪页 → 抓取。challenge/探测失败换下一个候选出口（§5.8），
        不原地等待挑战通过。
        """
        self._ensure_session()
        if not numbers or len(numbers) > 35:
            raise ProviderError("not_accepted",
                                f"Provider 批次须 1~35 条，实际 {len(numbers)}")
        states = list(self.cfg.states)
        if self.cfg.rotate_states:
            self._rand.shuffle(states)
        candidates = states[:self.cfg.max_exits]
        last_error = "page_type_unknown"
        last_geo = {}

        for idx, region in enumerate(candidates, start=1):
            try:
                self._switch_exit(region)
                last_geo = self.relay.exit_geo()
                # 准入第 1/2 层：出口 geo 不合格（非美/机房）换下一个。
                if not self._exit_ok():
                    last_error = "probe_bad_status"
                    continue
                # 准入第 3 层 + 会话前置：首页暖场。
                if not self._warmup():
                    last_error = "probe_empty_body"
                    continue
                self._warmed_regions.add(region)
                self._open_tracking(numbers)
                state = self._page_state()
                tb = int(state.get("tb", 0))
                text_len = int(state.get("len", 0))
                # 真实结果 = 有 tb-step 事件块；空正文 = 硬拦/challenge，换出口。
                if tb > 0 or text_len > 1000:
                    html = self._fetch_html()
                    return CollectedPage(
                        html=html, http_status=200, warmed_up=True,
                        exit_region=region,
                        exit_ref=tracking_ref(str(last_geo.get("query", ""))),
                        profile_ref=self.cfg.profile, exit_attempt=idx,
                    )
                # 空正文：已暖场 → challenge（换出口回炉，不等待）。
                last_error = "challenge"
            except ProviderError:
                raise
            except Exception as e:  # 浏览器/网络异常归类为可重试
                last_error = "browser_crash"
                continue
        raise ProviderError(last_error,
                            f"{len(candidates)} 个候选出口均未取得结果")

    def cleanup(self) -> None:
        """finally 清理浏览器会话目录（02 §3.1，约 500M/批）。"""
        self._claw("profiles", "rm", self.cfg.profile, timeout=30)
