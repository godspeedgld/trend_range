"""特征工程框架：DataContext / BaseFeature / FeatureRegistry / FeatureEngineer。

设计：
  - DataContext（不可变 frozen dataclass）：持有 close/open/high/low/volume；特征按需取，生成过程中不可改。
  - BaseFeature（抽象基类）：每个特征一个子类，实现 compute(批量) 与 update(流式增量)。
  - FeatureRegistry：name → 特征类 的注册表；按配置字符串动态实例化（如 "ma:30"、"macd:12,26,9"）。
  - FeatureEngineer：根据 config 实例化一组特征；fit(ctx) 批量出 DataFrame；update(bar) 流式出 dict。

批量与流式：同一特征两套实现，数学一致（流式用增量递推；warmup 区可能与批量有微小差异，
warmup 后一致）。特征可单输出（MA/EMA/RSI/ATR）或多输出（MACD → macd/signal/hist）。

起步特征：MA / EMA / MACD / RSI / ATR。新增特征：继承 BaseFeature + @FeatureRegistry.register("name")。
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
        """按 spec 实例化特征。spec: "name:p1,p2,..." 或 {"name":..,"params":[..]}。"""
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
    """特征基类。子类实现 compute(批量) 与 update(流式)；@FeatureRegistry.register 注册。"""
    name: str = ""
    required: tuple = ("close",)

    def __init__(self, *params):
        self.params = params
        self.tag = self.name + ("_" + "_".join(str(p) for p in params) if params else "")
        self.reset()

    def reset(self) -> None:
        """重置流式状态（子类覆盖：super().reset() 后再加自己的状态）。"""
        self._n_seen = 0

    def compute(self, ctx: DataContext) -> dict:
        raise NotImplementedError

    def update(self, bar: dict) -> dict:
        raise NotImplementedError

    def columns(self) -> list[str]:
        return [self.tag]

    # —— 小工具 ——
    def _step(self):
        self._n_seen += 1


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

    def reset(self):
        super().reset()
        self._win = deque(maxlen=self.n)
        self._sum = 0.0

    def compute(self, ctx):
        return {self.tag: ctx.get("close").rolling(self.n).mean()}

    def update(self, bar):
        self._step()
        c = float(bar["close"])
        if len(self._win) == self.n:
            self._sum -= self._win[0]
        self._win.append(c)
        self._sum += c
        val = self._sum / len(self._win) if self._n_seen >= self.n else np.nan
        return {self.tag: val}


@FeatureRegistry.register("ema")
class EMA(BaseFeature):
    """指数移动平均 EMA(span=n)。"""
    required = ("close",)

    def __init__(self, n: int):
        self.n = int(n)
        self.alpha = 2.0 / (n + 1)
        super().__init__(n)

    def reset(self):
        super().reset()
        self._prev = None

    def compute(self, ctx):
        return {self.tag: ctx.get("close").ewm(span=self.n, adjust=False).mean()}

    def update(self, bar):
        self._step()
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

    def reset(self):
        super().reset()
        self._ef = self._es = self._sig = None

    def columns(self):
        return [f"{self.tag}_macd", f"{self.tag}_signal", f"{self.tag}_hist"]

    def compute(self, ctx):
        c = ctx.get("close")
        ef = c.ewm(span=self.fast, adjust=False).mean()
        es = c.ewm(span=self.slow, adjust=False).mean()
        macd = ef - es
        sig = macd.ewm(span=self.signal, adjust=False).mean()
        return {f"{self.tag}_macd": macd, f"{self.tag}_signal": sig, f"{self.tag}_hist": macd - sig}

    def update(self, bar):
        self._step()
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

    def reset(self):
        super().reset()
        self._prev_close = None
        self._ag = self._al = None   # avg gain / avg loss

    def compute(self, ctx):
        c = ctx.get("close")
        d = c.diff()
        gain = d.clip(lower=0).ewm(alpha=self.a, adjust=False).mean()
        loss = (-d.clip(upper=0)).ewm(alpha=self.a, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return {self.tag: 100 - 100 / (1 + rs)}

    def update(self, bar):
        self._step()
        c = float(bar["close"])
        if self._prev_close is None:
            self._prev_close = c
            return {self.tag: np.nan}
        ch = c - self._prev_close
        g = ch if ch > 0 else 0.0
        l = -ch if ch < 0 else 0.0
        self._ag = g if self._ag is None else self._ag + self.a * (g - self._ag)
        self._al = l if self._al is None else self._al + self.a * (l - self._al)
        self._prev_close = c
        rs = self._ag / self._al if self._al and self._al > 0 else np.inf
        rsi = 100.0 if rs == np.inf else 100 - 100 / (1 + rs)
        return {self.tag: rsi}


@FeatureRegistry.register("atr")
class ATR(BaseFeature):
    """ATR(n)（Wilder/ewm(alpha=1/n) 平滑 TR）。需 high/low/close。"""
    required = ("high", "low", "close")

    def __init__(self, n: int):
        self.n = int(n)
        self.a = 1.0 / n
        super().__init__(n)

    def reset(self):
        super().reset()
        self._prev_close = None
        self._atr = None

    @staticmethod
    def _tr(h, l, pc):
        return max(h - l, abs(h - pc), abs(l - pc))

    def compute(self, ctx):
        h, l, c = ctx.get("high"), ctx.get("low"), ctx.get("close")
        pc = c.shift()
        tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return {self.tag: tr.ewm(alpha=self.a, adjust=False).mean()}

    def update(self, bar):
        self._step()
        h, l, c = float(bar["high"]), float(bar["low"]), float(bar["close"])
        if self._prev_close is None:
            # 首点种子 = h−l（与批量 tr[0] 一致：max 跳过 NaN 前收盘）
            self._atr = h - l
            self._prev_close = c
            return {self.tag: self._atr}
        tr = self._tr(h, l, self._prev_close)
        self._atr = self._atr + self.a * (tr - self._atr)
        self._prev_close = c
        return {self.tag: self._atr}


# ════════════════════════════════════════════════════════════
# FeatureEngineer
# ════════════════════════════════════════════════════════════
class FeatureEngineer:
    """特征工程主入口。config 给特征规格列表，动态实例化并执行。

    用法：
      fe = FeatureEngineer(["ma:30", "macd:12,26,9", "rsi:14", "atr:14"])
      df = fe.fit(ctx)               # 批量：DataFrame(所有特征列)
      fe.reset(); fe.update(bar)     # 流式：dict(各特征当步值)
    """

    def __init__(self, config: list):
        self.config = list(config)
        self.features = [FeatureRegistry.build(s) for s in self.config]

    def fit(self, ctx: DataContext) -> pd.DataFrame:
        """批量：对 DataContext 跑每个特征 compute，合并为 DataFrame（index 对齐 close）。"""
        cols: dict = {}
        for f in self.features:
            cols.update(f.compute(ctx))
        return pd.DataFrame(cols, index=ctx.close.index)

    def reset(self) -> None:
        for f in self.features:
            f.reset()

    def update(self, bar: dict) -> dict:
        """流式：传入最新一根 bar(dict: close/high/low/open/volume)，返回各特征当步值 dict。"""
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
