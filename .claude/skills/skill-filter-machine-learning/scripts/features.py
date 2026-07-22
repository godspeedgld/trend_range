"""特征工程框架：DataContext / BaseFeature / FeatureRegistry / FeatureEngineer。

设计：
  - DataContext（不可变 frozen dataclass）：OHLCV + 卡尔曼输出(innov/s/predict_value)；特征按需取。
  - BaseFeature（抽象基类）：每个特征实现 _compute_raw(批量向量化) 与 _update_raw(流式增量)；
    基类统一处理 ① warmup 掩码（前 warmup 根输出 NaN）② warmstart（compute 后回放喂齐流式状态，
    使 fit()->update() 无缝续接）。
  - FeatureRegistry：name → 特征类；按配置字符串动态实例化（"ma:30"、"macd:12,26,9"）。
  - FeatureEngineer：fit(ctx) 批量 → DataFrame；update(bar) 流式 → dict。

批量与流式数学一致（warmstart 保证状态一致；warmstart 后流式=批量尾部）。
起步特征：MA / EMA / MACD / RSI / ATR。新增：@FeatureRegistry.register + 继承 BaseFeature。
依赖：numpy、pandas。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ════════════════════════════════════════════════════════════
# DataContext（不可变）
# ════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class DataContext:
    """不可变数据上下文。close 必需，其余可选；特征按需 .get(field) 取。

    除 OHLCV 外，还可携带卡尔曼滤波输出（innov/s/predict_value），
    供"以滤波新息/预测为输入"的特征使用（由 AdaptiveKalmanFilter.fit 结果填充）。
    """
    close: pd.Series
    high: Optional[pd.Series] = None
    low: Optional[pd.Series] = None
    open: Optional[pd.Series] = None
    volume: Optional[pd.Series] = None
    # 卡尔曼输出（可选；批量=pd.Series，流式=标量）
    innov: Optional[pd.Series] = None        # 新息 ν = z − H·x⁻
    s: Optional[pd.Series] = None            # 新息协方差 S
    predict_value: Optional[pd.Series] = None  # 下一时刻预测 H·F·x⁺

    def get(self, field: str) -> pd.Series:
        v = getattr(self, field, None)
        if v is None:
            raise ValueError(f"DataContext 缺少字段 '{field}'（该特征需要它）")
        return v


# ════════════════════════════════════════════════════════════
# Registry
# ════════════════════════════════════════════════════════════
class FeatureRegistry:
    _reg: dict[str, type["BaseFeature"]] = {}

    @classmethod
    def register(cls, name: str):
        def deco(c):
            c.name = name
            cls._reg[name] = c
            return c
        return deco

    @classmethod
    def build(cls, spec) -> "BaseFeature":
        """按 spec 实例化。spec: "name:p1,p2,..." 或 {"name":..,"params":[..]}。"""
        if isinstance(spec, str):
            name, _, p = spec.partition(":")
            name = name.strip()
            params = [_num(x) for x in p.split(",")] if p else []
        else:
            name = spec["name"]
            params = list(spec.get("params", []))
        if name not in cls._reg:
            raise ValueError(f"未知特征 '{name}'（已注册: {list(cls._reg)}）")
        return cls._reg[name](*params)

    @classmethod
    def names(cls):
        return list(cls._reg)


def _num(x: str):
    x = x.strip()
    return float(x) if ("." in x or "e" in x.lower()) else int(x)


# ════════════════════════════════════════════════════════════
# BaseFeature
# ════════════════════════════════════════════════════════════
class BaseFeature:
    """特征基类。

    子类实现：
      _init_stream()   —— 初始化流式状态（缓冲/EMA 状态等）
      _compute_raw(ctx) —— 批量向量化计算，返回 {col: pd.Series}（不做 warmup 掩码）
      _update_raw(bar)  —— 流式增量一步，返回 {col: float}（不做 warmup 掩码；状态持续累积）
    子类设置：
      warmup           —— 前多少根输出 NaN（统一 warmup 策略）

    基类统一处理：warmup 掩码（compute/update 前 warmup 根 → NaN）；
    _warmstart(ctx) 在 compute 后回放整段，把流式状态喂齐 → fit() 后 update() 无缝续接。
    """
    name: str = ""
    required: tuple = ("close",)
    warmup: int = 0

    def __init__(self, *params):
        self.params = params
        self.tag = self.name + ("_" + "_".join(str(p) for p in params) if params else "")
        self.reset()

    def reset(self) -> None:
        """重置：_n_seen 归零 + 子类 _init_stream。"""
        self._n_seen = 0
        self._init_stream()

    def _init_stream(self) -> None:
        """子类覆盖：初始化流式缓冲/状态。"""
        pass

    # —— 批量 ——
    def compute(self, ctx: DataContext) -> dict:
        out = self._compute_raw(ctx)
        w = self.warmup
        for k, s in out.items():                       # 统一 warmup 掩码
            if isinstance(s, pd.Series) and w > 0:
                s = s.copy(); s.iloc[:w] = np.nan; out[k] = s
        self._warmstart(ctx)                            # 喂齐流式状态
        return out

    def _compute_raw(self, ctx: DataContext) -> dict:
        raise NotImplementedError

    # —— 流式 ——
    def update(self, bar: dict) -> dict:
        self._n_seen += 1
        out = self._update_raw(bar)
        if self._n_seen <= self.warmup:                 # 统一 warmup 掩码
            return {k: np.nan for k in out}
        return out

    def _update_raw(self, bar: dict) -> dict:
        raise NotImplementedError

    # —— warmstart：compute 后回放整段喂齐状态（默认实现；子类可覆盖为更高效的尾部种子）——
    def _warmstart(self, ctx: DataContext) -> None:
        self._n_seen = 0
        self._init_stream()
        n = len(ctx.close)
        fields = {f: ctx.get(f).to_numpy() for f in self.required}
        for i in range(n):
            bar = {f: float(fields[f][i]) for f in self.required}
            self._n_seen += 1
            self._update_raw(bar)

    def columns(self) -> list[str]:
        return [self.tag]


# ════════════════════════════════════════════════════════════
# 起步特征
# ════════════════════════════════════════════════════════════
@FeatureRegistry.register("ma")
class MA(BaseFeature):
    """简单移动平均 SMA(n)。"""
    required = ("close",)

    def __init__(self, n: int):
        self.n = int(n)
        super().__init__(n)

    def _init_stream(self):
        self._win = deque(maxlen=self.n)
        self._sum = 0.0

    @property
    def warmup(self):
        return self.n

    def _compute_raw(self, ctx):
        return {self.tag: ctx.get("close").rolling(self.n).mean()}

    def _update_raw(self, bar):
        c = float(bar["close"])
        if len(self._win) == self.n:
            self._sum -= self._win[0]
        self._win.append(c)
        self._sum += c
        return {self.tag: self._sum / len(self._win)}


@FeatureRegistry.register("ema")
class EMA(BaseFeature):
    """指数移动平均 EMA(span=n)。"""
    required = ("close",)

    def __init__(self, n: int):
        self.n = int(n)
        self.alpha = 2.0 / (n + 1)
        super().__init__(n)

    def _init_stream(self):
        self._prev = None

    @property
    def warmup(self):
        return self.n

    def _compute_raw(self, ctx):
        return {self.tag: ctx.get("close").ewm(span=self.n, adjust=False).mean()}

    def _update_raw(self, bar):
        c = float(bar["close"])
        self._prev = c if self._prev is None else self.alpha * c + (1 - self.alpha) * self._prev
        return {self.tag: self._prev}


@FeatureRegistry.register("macd")
class MACD(BaseFeature):
    """MACD(fast, slow, signal) → 三列：macd / signal / hist。"""
    required = ("close",)

    def __init__(self, fast: int, slow: int, signal: int):
        self.fast, self.slow, self.signal = int(fast), int(slow), int(signal)
        self.af, self.as_, self.asig = 2 / (fast + 1), 2 / (slow + 1), 2 / (signal + 1)
        super().__init__(fast, slow, signal)

    def _init_stream(self):
        self._ef = self._es = self._sig = None

    @property
    def warmup(self):
        return self.slow

    def columns(self):
        return [f"{self.tag}_macd", f"{self.tag}_signal", f"{self.tag}_hist"]

    def _compute_raw(self, ctx):
        c = ctx.get("close")
        ef = c.ewm(span=self.fast, adjust=False).mean()
        es = c.ewm(span=self.slow, adjust=False).mean()
        macd = ef - es
        sig = macd.ewm(span=self.signal, adjust=False).mean()
        return {f"{self.tag}_macd": macd, f"{self.tag}_signal": sig, f"{self.tag}_hist": macd - sig}

    def _update_raw(self, bar):
        c = float(bar["close"])
        self._ef = c if self._ef is None else self.af * c + (1 - self.af) * self._ef
        self._es = c if self._es is None else self.as_ * c + (1 - self.as_) * self._es
        macd = self._ef - self._es
        self._sig = macd if self._sig is None else self.asig * macd + (1 - self.asig) * self._sig
        return {f"{self.tag}_macd": macd, f"{self.tag}_signal": self._sig, f"{self.tag}_hist": macd - self._sig}


@FeatureRegistry.register("rsi")
class RSI(BaseFeature):
    """RSI(n)（Wilder/ewm(alpha=1/n) 平滑）。"""
    required = ("close",)

    def __init__(self, n: int):
        self.n = int(n)
        self.a = 1.0 / n
        super().__init__(n)

    def _init_stream(self):
        self._prev_close = None
        self._ag = self._al = None

    @property
    def warmup(self):
        return self.n

    def _compute_raw(self, ctx):
        c = ctx.get("close")
        d = c.diff()
        gain = d.clip(lower=0).ewm(alpha=self.a, adjust=False).mean()
        loss = (-d.clip(upper=0)).ewm(alpha=self.a, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return {self.tag: 100 - 100 / (1 + rs)}

    def _update_raw(self, bar):
        c = float(bar["close"])
        if self._prev_close is None:
            self._prev_close = c
            return {self.tag: 0.0}
        ch = c - self._prev_close
        g = ch if ch > 0 else 0.0
        l = -ch if ch < 0 else 0.0
        self._ag = g if self._ag is None else self._ag + self.a * (g - self._ag)
        self._al = l if self._al is None else self._al + self.a * (l - self._al)
        self._prev_close = c
        rs = self._ag / self._al if self._al and self._al > 0 else np.inf
        return {self.tag: (100.0 if rs == np.inf else 100 - 100 / (1 + rs))}


@FeatureRegistry.register("atr")
class ATR(BaseFeature):
    """ATR(n)（Wilder/ewm(alpha=1/n) 平滑 TR）。需 high/low/close。"""
    required = ("high", "low", "close")

    def __init__(self, n: int):
        self.n = int(n)
        self.a = 1.0 / n
        super().__init__(n)

    def _init_stream(self):
        self._prev_close = None
        self._atr = None

    @property
    def warmup(self):
        return self.n

    @staticmethod
    def _tr(h, l, pc):
        return max(h - l, abs(h - pc), abs(l - pc))

    def _compute_raw(self, ctx):
        h, l, c = ctx.get("high"), ctx.get("low"), ctx.get("close")
        pc = c.shift()
        tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return {self.tag: tr.ewm(alpha=self.a, adjust=False).mean()}

    def _update_raw(self, bar):
        h, l, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
        if self._prev_close is None:
            self._atr = h - l                       # 首点种子 = h−l（与批量 tr[0] 一致）
            self._prev_close = c
            return {self.tag: self._atr}
        tr = self._tr(h, l, self._prev_close)
        self._atr = self._atr + self.a * (tr - self._atr)
        self._prev_close = c
        return {self.tag: self._atr}


@FeatureRegistry.register("log_ret")
class LogReturn(BaseFeature):
    """对数收益率 ln(close).diff()。"""
    required = ("close",)
    warmup = 1

    def _init_stream(self):
        self._prev = None

    def _compute_raw(self, ctx):
        return {self.tag: np.log(ctx.get("close")).diff()}

    def _update_raw(self, bar):
        c = float(bar["close"])
        ret = np.log(c / self._prev) if self._prev and self._prev > 0 else 0.0
        self._prev = c
        return {self.tag: ret}


@FeatureRegistry.register("vol")
class Volatility(BaseFeature):
    """滚动波动率（log return 的 n 周期标准差）。"""
    required = ("close",)

    def __init__(self, n: int):
        self.n = int(n)
        super().__init__(n)

    @property
    def warmup(self):
        return self.n

    def _init_stream(self):
        self._buf = deque(maxlen=self.n)
        self._prev = None

    def _compute_raw(self, ctx):
        ret = np.log(ctx.get("close")).diff()
        return {self.tag: ret.rolling(self.n).std()}

    def _update_raw(self, bar):
        c = float(bar["close"])
        r = np.log(c / self._prev) if self._prev and self._prev > 0 else 0.0
        self._prev = c
        self._buf.append(r)
        v = float(np.std(list(self._buf), ddof=1)) if len(self._buf) >= 2 else 0.0
        return {self.tag: v}


@FeatureRegistry.register("kalman")
class KalmanFeature(BaseFeature):
    """卡尔曼滤波特征（多输出）。内部运行 AdaptiveKalmanFilter。

    输出列：{tag}_level, {tag}_velocity[, {tag}_acceleration],
            {tag}_predict_value, {tag}_innov, {tag}_S
    config 示例："kalman:50,3"（win=50, dim=3）。
    """
    required = ("close",)

    def __init__(self, win: int = 50, dim: int = 3):
        self.win = int(win)
        self.dim = int(dim)
        super().__init__(win, dim)

    @property
    def warmup(self):
        return 0   # Kalman 从首根输出（Q/R 自适应在内部 warmup 后生效）

    def columns(self):
        t = self.tag
        cols = [f"{t}_level", f"{t}_velocity"]
        if self.dim >= 3:
            cols.append(f"{t}_acceleration")
        cols += [f"{t}_predict_value", f"{t}_innov", f"{t}_S"]
        return cols

    def _init_stream(self):
        from scripts.filter import AdaptiveKalmanFilter
        self._kf = AdaptiveKalmanFilter(win=self.win, dim=self.dim)

    def _compute_raw(self, ctx):
        from scripts.filter import AdaptiveKalmanFilter
        kf = AdaptiveKalmanFilter(win=self.win, dim=self.dim)
        r = kf.fit(ctx.get("close"))
        t = self.tag
        out = {f"{t}_level": r["level"], f"{t}_velocity": r["velocity"],
               f"{t}_predict_value": r["predict_value"], f"{t}_innov": r["innov"],
               f"{t}_S": r["S"]}
        if self.dim >= 3:
            out[f"{t}_acceleration"] = r.get("acceleration")
        return out

    def _update_raw(self, bar):
        r = self._kf.update(float(bar["close"]))
        t = self.tag
        out = {f"{t}_level": r["level"], f"{t}_velocity": r["velocity"],
               f"{t}_predict_value": r["predict_value"], f"{t}_innov": r["innov"],
               f"{t}_S": r["S"]}
        if self.dim >= 3:
            out[f"{t}_acceleration"] = r.get("acceleration", 0.0)
        return out


# ════════════════════════════════════════════════════════════
# 收益率 / 量价 / 波动率 特征
# ════════════════════════════════════════════════════════════
@FeatureRegistry.register("log_ret_n")
class LogReturnN(BaseFeature):
    """N 日对数收益率 ln(close[t]/close[t-n])。"""
    required = ("close",)

    def __init__(self, n: int):
        self.n = int(n)
        super().__init__(n)

    @property
    def warmup(self):
        return self.n

    def _init_stream(self):
        self._buf = deque(maxlen=self.n + 1)

    def _compute_raw(self, ctx):
        return {self.tag: np.log(ctx.get("close")).diff(self.n)}

    def _update_raw(self, bar):
        self._buf.append(float(bar["close"]))
        if len(self._buf) <= self.n:
            return {self.tag: 0.0}
        return {self.tag: np.log(self._buf[-1] / self._buf[0])}


@FeatureRegistry.register("vol_log_ret")
class VolLogReturn(BaseFeature):
    """成交量对数收益率 ln(vol[t]/vol[t-1])。"""
    required = ("volume",)
    warmup = 1

    def _init_stream(self):
        self._prev = None

    def _compute_raw(self, ctx):
        v = ctx.get("volume")
        return {self.tag: np.log(v.replace(0, np.nan)).diff()}

    def _update_raw(self, bar):
        v = float(bar["volume"])
        ret = np.log(v / self._prev) if self._prev and self._prev > 0 and v > 0 else 0.0
        self._prev = v
        return {self.tag: ret}


@FeatureRegistry.register("vol_ratio")
class VolRatio(BaseFeature):
    """成交量相对均量比 = vol / ma(vol, n)。"""
    required = ("volume",)

    def __init__(self, n: int):
        self.n = int(n)
        super().__init__(n)

    @property
    def warmup(self):
        return self.n

    def _init_stream(self):
        self._buf = deque(maxlen=self.n)
        self._sum = 0.0

    def _compute_raw(self, ctx):
        v = ctx.get("volume")
        ma = v.rolling(self.n).mean()
        return {self.tag: v / ma.replace(0, np.nan)}

    def _update_raw(self, bar):
        v = float(bar["volume"])
        if len(self._buf) == self.n:
            self._sum -= self._buf[0]
        self._buf.append(v)
        self._sum += v
        ma = self._sum / len(self._buf) if self._buf else 1.0
        return {self.tag: v / ma if ma > 0 else 1.0}


@FeatureRegistry.register("vwap_dev")
class VWAPDeviation(BaseFeature):
    """(close − VWAP_n) / close。VWAP_n = Σ(close·vol)/Σ(vol) 滚动 n 期。"""
    required = ("close", "volume")

    def __init__(self, n: int):
        self.n = int(n)
        super().__init__(n)

    @property
    def warmup(self):
        return self.n

    def _init_stream(self):
        self._cv_buf = deque(maxlen=self.n)   # close*vol
        self._v_buf = deque(maxlen=self.n)    # vol
        self._cv_sum = 0.0
        self._v_sum = 0.0

    def _compute_raw(self, ctx):
        c, v = ctx.get("close"), ctx.get("volume")
        cv = c * v
        vwap = cv.rolling(self.n).sum() / v.rolling(self.n).sum().replace(0, np.nan)
        return {self.tag: (c - vwap) / c}

    def _update_raw(self, bar):
        c, v = float(bar["close"]), float(bar["volume"])
        cv = c * v
        if len(self._cv_buf) == self.n:
            self._cv_sum -= self._cv_buf[0]
            self._v_sum -= self._v_buf[0]
        self._cv_buf.append(cv)
        self._v_buf.append(v)
        self._cv_sum += cv
        self._v_sum += v
        vwap = self._cv_sum / self._v_sum if self._v_sum > 0 else c
        return {self.tag: (c - vwap) / c}


@FeatureRegistry.register("range_pct")
class RangePct(BaseFeature):
    """日振幅百分比 = (high − low) / close。"""
    required = ("high", "low", "close")
    warmup = 0

    def _compute_raw(self, ctx):
        h, l, c = ctx.get("high"), ctx.get("low"), ctx.get("close")
        return {self.tag: (h - l) / c}

    def _update_raw(self, bar):
        h, l, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
        return {self.tag: (h - l) / c if c > 0 else 0.0}


@FeatureRegistry.register("close_pos")
class ClosePosition(BaseFeature):
    """收盘在日内区间的位置 = (close − low) / (high − low)。0=收最低，1=收最高。"""
    required = ("high", "low", "close")
    warmup = 0

    def _compute_raw(self, ctx):
        h, l, c = ctx.get("high"), ctx.get("low"), ctx.get("close")
        rng = (h - l).replace(0, np.nan)
        return {self.tag: (c - l) / rng}

    def _update_raw(self, bar):
        h, l, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
        rng = h - l
        return {self.tag: (c - l) / rng if rng > 0 else 0.5}


# ════════════════════════════════════════════════════════════
# FeatureEngineer
# ════════════════════════════════════════════════════════════
class FeatureEngineer:
    """特征工程主入口。config 给特征规格列表，动态实例化并执行。

    用法：
      fe = FeatureEngineer(["ma:30", "macd:12,26,9", "rsi:14", "atr:14"])
      df = fe.fit(ctx)               # 批量：DataFrame(所有特征列)，fit 后状态已 warmstart
      fe.update(bar)                 # 流式：dict(各特征当步值)，可接在 fit 之后无缝续推
      fe.reset()                     # 重置（重新从 warmup 开始）
    """

    def __init__(self, config: list):
        self.config = list(config)
        self.features = [FeatureRegistry.build(s) for s in self.config]

    def fit(self, ctx: DataContext) -> pd.DataFrame:
        """批量：对 DataContext 跑每个特征 compute，合并为 DataFrame（index 对齐 close）。

        fit 后每个特征流式状态已 warmstart，可直接 update() 续推实盘。
        """
        cols: dict = {}
        for f in self.features:
            cols.update(f.compute(ctx))
        return pd.DataFrame(cols, index=ctx.close.index)

    def reset(self) -> None:
        for f in self.features:
            f.reset()

    def update(self, bar: dict) -> dict:
        """流式：传入最新一根 bar(dict)，返回各特征当步值 dict。"""
        out: dict = {}
        for f in self.features:
            out.update(f.update(bar))
        return out

    def columns(self) -> list:
        c: list = []
        for f in self.features:
            c += f.columns()
        return c


__all__ = ["DataContext", "BaseFeature", "FeatureRegistry", "FeatureEngineer"]
