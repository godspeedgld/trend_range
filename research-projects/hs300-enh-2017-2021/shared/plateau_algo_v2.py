"""平台突破 v2.6 —— 趋势线系统（OLS 拟合支撑/阻力线 + 通道带 + 线速率断线，见 analysis_002 records）。

v2.5 完全替代 v2.0~v2.4 的"平台"范式（用户指定，5.1 放弃平台/待定突破概念）：

  1. 转折点识别不变（布林带状态机，同 v1）
  2. 阻力线 = 高点 OLS 拟合直线（≥2 个转折高点）
     · 阻力距 = 所有拟合高点到线的最大价格距离（OLS 残差绝对值）
     · 新高点距离线 > 2×阻力距 → 原阻力线结束，新高点开启新线（v2.6：与速率条件 OR 独立）
     · 初始化（2 高点）：两点连线即线；残差为 0，以**两点价差半幅**作初始带宽种子
       （避免 2×0=0 导致第三点必重开）
  3. 支撑线对称（低点 OLS，支撑距）
  4. 突破/跌破（盘中价 vs 当日线值 ± 距离带，固定 3%）：
     · high > (阻力线(t) + 阻力距) × 1.03 → 突破信号
     · low  < (支撑线(t) − 支撑距) × 0.97 → 跌破信号（用户 4.2 原文"阻力线"系笔误，按对称实现）
     · 每条线只发一次信号（首破；假突破与线划分无关——线只由转折点距离规则驱动）
  5. 无平台、无 pending/回退——纯"线"概念

v2.6（线速率断线）：线速率 rate =（终点−起点）/（起点×bar 数）。
  断线两条件**独立评估、满足其一即断线**（用户规则 4/5：速率无条件独立）：
    ① 距离断线：新点距线 > 2×dist（line_end_k=2.0）
    ② 速率断线：加入新点重新拟合，拟合线速率 阻力 > +1%/bar、支撑 < −1%/bar（涨/跌太快）
  事件 reason 字段标注触发来源：dist_break / rate_break / both。

v2.7（单点待成线 → 收盘+速率提前成线）：解决爆发式拉升/下杀期间单点 pending 长期不成线
  （如 2021-04~08 阻力线空窗 3 个月）。当 pend_highs/pend_lows 只有 1 点时，不再只等第二个转折点：
    · 阻力线：某根 K 线 close > 前高×(1+3%) 且 (close−前高)/(前高×bar数) > 1%/bar
      → 该 K 线 close 与前高构成阻力线（formed="close_rate"）
    · 支撑线：某根 K 线 close < 前低×(1−3%) 且 (close−前低)/(前低×bar数) < −1%/bar
      → 该 K 线 close 与前低构成支撑线（formed="close_rate"）
  否则（后续最高点一直低于前高 / 最低点一直高于前低）仍按原规则等下一个转折点。
  formed 字段标记成线来源：close_rate=本规则提前成线；缺省=None=两转折点成线。

实现注记：
  · 距离用**价格垂直距离** |p − line(t)|（OLS 残差；(bar 索引, 价格) 平面的欧氏距离被价格量纲
    主导，无实际意义——如需真欧氏距离需先归一化，暂不采用）
  · 拟合点用高点**发生位置** (hp_i, hp_p)，非确认日
  · 铁律：无未来数据（当日判定用截至昨日的线；转折点确认 ≤t）
  · 不影响 v1（plateau_algo.py 冻结）与 ssquant HP 版
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── 参数 ──
BREAK_PCT = 0.03         # 突破阈值：(线+距)×1.03 / (线−距)×0.97
LINE_END_K = 2.0         # 新点距离 > k×距离 → 线结束
RATE_MAX = 0.01          # v2.6 速率断线阈值：阻力线速率 > 1%/bar → 阻力线结束
RATE_MIN = -0.01         # 支撑线速率 < -1%/bar → 支撑线结束
BB_WINDOW, BB_K, P_CLEAR = 20, 1.0, 4    # 转折点（同 v1）


def line_rate(ln) -> float:
    """线速率 =（终点值 − 起点值）/（起点值 × bar 数），带符号（%/1 归一为小数）。

    即每 bar 增长百分比（小数形式，如 +0.018 = +1.8%/bar）。"""
    bars = max(ln["i1"] - ln["i0"], 1)
    y0 = ln["a"] + ln["b"] * ln["i0"]
    y1 = ln["a"] + ln["b"] * ln["i1"]
    if abs(y0) < 1e-12:
        return 0.0
    return (y1 - y0) / (y0 * bars)


def _ols_line(points):
    """points = [(i, price), ...] → (a, b)：y = a + b·i（最小二乘）。"""
    arr = np.array(points, dtype=float)
    i_s, p_s = arr[:, 0], arr[:, 1]
    if len(points) == 2:
        di = i_s[1] - i_s[0]
        if abs(di) < 1e-12:
            return float(p_s.mean()), 0.0
        b = (p_s[1] - p_s[0]) / di
        return float(p_s[0] - b * i_s[0]), float(b)
    b, a = np.polyfit(i_s, p_s, 1)
    return float(a), float(b)


class TrendlineBreakout:
    """v2.5 趋势线状态机：逐日 feed(bar) → 事件流。

    状态：
      resist / support：None 或
        {"pts": [(i,p)...], "a","b": 线参数, "dist": 带宽, "start_i", "signaled": bool}
      pend_highs / pend_lows：未成线的累积点（1 个时等待第 2 个）
    事件：
      resist_start / resist_end {date, a, b, dist, i0, i1}
      break_up / break_down {date, line_val, dist, price}
    """

    def __init__(self, break_pct=BREAK_PCT, line_end_k=LINE_END_K,
                 rate_max=RATE_MAX, rate_min=RATE_MIN):
        self.break_pct = break_pct
        self.line_end_k = line_end_k
        self.rate_max = rate_max    # 阻力线速率上限（>此值涨太快，断线）
        self.rate_min = rate_min    # 支撑线速率下限（<此值跌太快，断线）
        self.resist = None
        self.support = None
        self.pend_highs = []
        self.pend_lows = []
        self.finished_lines = []     # 已结束线（可视化）：{"kind":"R"/"S", i0,i1,a,b,dist}
        # 转折点状态机（布林带，同 v1）
        self.trend = 0
        self.hp_i, self.hp_p = -1, -1.0
        self.lp_i, self.lp_p = -1, -1.0
        self._started = False
        self.i = -1
        self._bars = []

    # ── 转折点增量推进 ──
    def _turning_step(self, high, low, ub, lb):
        if np.isnan(ub) or np.isnan(lb):
            return None
        ev = None
        if self.trend == 0:
            if high > ub:
                self.trend, self.hp_i, self.hp_p = 1, self.i, high
            elif low < lb:
                self.trend, self.lp_i, self.lp_p = -1, self.i, low
        elif self.trend == 1:
            if high > self.hp_p:
                self.hp_i, self.hp_p = self.i, high
            elif low < lb:
                if self.hp_i >= 0:
                    ev = (self.hp_i, self.hp_p, "H")
                self.trend, self.lp_i, self.lp_p = -1, self.i, low
        else:
            if low < self.lp_p:
                self.lp_i, self.lp_p = self.i, low
            elif high > ub:
                if self.lp_i >= 0:
                    ev = (self.lp_i, self.lp_p, "L")
                self.trend, self.hp_i, self.hp_p = 1, self.i, high
        return ev

    def _line_val(self, ln, i):
        return ln["a"] + ln["b"] * i

    def _form_from_pending(self, c: float):
        """v2.7：单点待成线时，用"收盘价超阈值 + 速率超限"提前成线（不等第二个转折点）。

        · 阻力线：pend_highs 只有 1 个高点时，若某根 K 线 close > 前高×(1+break_pct)
          且上涨速率 (close−前高)/(前高×bar数) > 1%/bar → 该 K 线 close 与前高构成阻力线。
        · 支撑线对称：close < 前低×(1−break_pct) 且下跌速率 (close−前低)/(前低×bar数) < −1%/bar
          → 该 K 线 close 与前低构成支撑线。
        不满足（后续最高点一直低于前高 / 最低点一直高于前低）则保持等待，由原规则接续。
        """
        if self.resist is None and len(self.pend_highs) == 1:
            hi_i, hi_p = self.pend_highs[0]
            bars = max(self.i - hi_i, 1)
            if c > hi_p * (1 + self.break_pct):
                rate = (c - hi_p) / (hi_p * bars)
                if rate > self.rate_max:
                    a, b = _ols_line([(hi_i, hi_p), (self.i, c)])
                    self.resist = {"pts": [(hi_i, hi_p), (self.i, c)], "a": a, "b": b,
                                   "dist": abs(hi_p - c) / 2.0, "start_i": hi_i,
                                   "signaled": False, "formed": "close_rate"}
                    self.pend_highs = []
        if self.support is None and len(self.pend_lows) == 1:
            lo_i, lo_p = self.pend_lows[0]
            bars = max(self.i - lo_i, 1)
            if c < lo_p * (1 - self.break_pct):
                rate = (c - lo_p) / (lo_p * bars)
                if rate < self.rate_min:
                    a, b = _ols_line([(lo_i, lo_p), (self.i, c)])
                    self.support = {"pts": [(lo_i, lo_p), (self.i, c)], "a": a, "b": b,
                                    "dist": abs(lo_p - c) / 2.0, "start_i": lo_i,
                                    "signaled": False, "formed": "close_rate"}
                    self.pend_lows = []

    def feed(self, bar: dict):
        self.i += 1
        date = bar.get("date")
        c, h, l = float(bar["close"]), float(bar["high"]), float(bar["low"])
        if not self._started:
            self._started = True
            self._bars.append(c)
            return None
        self._bars.append(c)
        s = pd.Series(np.array(self._bars))
        ma, sd = s.rolling(BB_WINDOW).mean().iloc[-1], s.rolling(BB_WINDOW).std().iloc[-1]
        ub, lb = ma + BB_K * sd, ma - BB_K * sd

        ev_out = None

        # ═══ ① 转折点确认 → 阻力线/支撑线维护 ═══
        tp = self._turning_step(h, l, ub, lb)
        if tp is not None:
            idx, price, kind = tp
            if kind == "H":
                ev_out = self._on_point(idx, price, is_high=True)
            else:
                ev_out = self._on_point(idx, price, is_high=False)

        # ═══ ② 每日突破/跌破判定（盘中价 vs 当日线值±带，首破一次）═══
        if self.resist is not None and not self.resist["signaled"]:
            band = self._line_val(self.resist, self.i) + self.resist["dist"]
            if h > band * (1 + self.break_pct):
                ev2 = {"type": "break_up", "date": date,
                       "line_val": self._line_val(self.resist, self.i),
                       "dist": self.resist["dist"], "price": h}
                self.resist["signaled"] = True
                ev_out = ev_out or ev2
        if self.support is not None and not self.support["signaled"]:
            band = self._line_val(self.support, self.i) - self.support["dist"]
            if l < band * (1 - self.break_pct):
                ev2 = {"type": "break_down", "date": date,
                       "line_val": self._line_val(self.support, self.i),
                       "dist": self.support["dist"], "price": l}
                self.support["signaled"] = True
                ev_out = ev_out or ev2

        # ═══ ③ v2.7 单点待成线 → 收盘超阈值 + 速率超限 提前成线 ═══
        self._form_from_pending(c)
        return ev_out

    def _on_point(self, idx, price, is_high: bool):
        """转折点进入：成线/并线/断线。返回线结束事件（或 None）。"""
        date_key = idx
        if is_high:
            if self.resist is None:
                self.pend_highs.append((idx, price))
                if len(self.pend_highs) >= 2:
                    a, b = _ols_line(self.pend_highs[:2])
                    dist = abs(self.pend_highs[0][1] - self.pend_highs[1][1]) / 2.0   # 价差半幅作带宽种子
                    self.resist = {"pts": list(self.pend_highs[:2]), "a": a, "b": b,
                                   "dist": dist, "start_i": self.pend_highs[0][0],
                                   "signaled": False}
                    self.pend_highs = []
                return None
            y = self._line_val(self.resist, idx)
            resid = abs(price - y)
            # v2.6 断线两条件独立评估、满足其一即断（用户规则：速率无条件独立）：
            #   ① 距离断线：新点距线 > 2×dist；② 速率断线：加入新点重新拟合，拟合线速率 > 1%/bar（涨太快）
            dist_break = resid > self.line_end_k * self.resist["dist"]
            tmp_pts = self.resist["pts"] + [(idx, price)]
            a2, b2 = _ols_line(tmp_pts)
            rate2 = line_rate({"a": a2, "b": b2, "i0": self.resist["start_i"], "i1": idx})
            rate_break = rate2 > self.rate_max
            if dist_break or rate_break:
                reason = ("both" if (dist_break and rate_break)
                          else ("rate_break" if rate_break else "dist_break"))
                ev = {"type": "resist_end", "kind": "R", "i0": self.resist["start_i"],
                      "i1": self.i, "a": self.resist["a"], "b": self.resist["b"],
                      "dist": self.resist["dist"],
                      "rate": line_rate({**self.resist, "i0": self.resist["start_i"],
                                         "i1": self.i}), "reason": reason}
                self.finished_lines.append({"kind": "R", "i0": self.resist["start_i"],
                                            "i1": self.i, "a": self.resist["a"],
                                            "b": self.resist["b"], "dist": self.resist["dist"],
                                            "formed": self.resist.get("formed")})
                self.resist = None
                self.pend_highs = [(idx, price)]     # 新点开启新累积
                return ev
            # 并线：重新 OLS + 更新带宽
            self.resist["pts"].append((idx, price))
            a, b = _ols_line(self.resist["pts"])
            self.resist["a"], self.resist["b"] = a, b
            resids = [abs(p - (a + b * i)) for i, p in self.resist["pts"]]
            self.resist["dist"] = max(resids)
            return None
        # ── 低点对称 ──
        if self.support is None:
            self.pend_lows.append((idx, price))
            if len(self.pend_lows) >= 2:
                a, b = _ols_line(self.pend_lows[:2])
                dist = abs(self.pend_lows[0][1] - self.pend_lows[1][1]) / 2.0
                self.support = {"pts": list(self.pend_lows[:2]), "a": a, "b": b,
                                "dist": dist, "start_i": self.pend_lows[0][0],
                                "signaled": False}
                self.pend_lows = []
            return None
        y = self._line_val(self.support, idx)
        resid = abs(price - y)
        # v2.6 断线两条件独立评估、满足其一即断（用户规则：速率无条件独立）：
        #   ① 距离断线：新点距线 > 2×dist；② 速率断线：加入新点重新拟合，拟合线速率 < -1%/bar（跌太快）
        dist_break = resid > self.line_end_k * self.support["dist"]
        tmp_pts = self.support["pts"] + [(idx, price)]
        a2, b2 = _ols_line(tmp_pts)
        rate2 = line_rate({"a": a2, "b": b2, "i0": self.support["start_i"], "i1": idx})
        rate_break = rate2 < self.rate_min
        if dist_break or rate_break:
            reason = ("both" if (dist_break and rate_break)
                      else ("rate_break" if rate_break else "dist_break"))
            ev = {"type": "support_end", "kind": "S", "i0": self.support["start_i"],
                  "i1": self.i, "a": self.support["a"], "b": self.support["b"],
                  "dist": self.support["dist"],
                  "rate": line_rate({**self.support, "i0": self.support["start_i"],
                                     "i1": self.i}), "reason": reason}
            self.finished_lines.append({"kind": "S", "i0": self.support["start_i"],
                                        "i1": self.i, "a": self.support["a"],
                                        "b": self.support["b"], "dist": self.support["dist"],
                                        "formed": self.support.get("formed")})
            self.support = None
            self.pend_lows = [(idx, price)]
            return ev
        self.support["pts"].append((idx, price))
        a, b = _ols_line(self.support["pts"])
        self.support["a"], self.support["b"] = a, b
        resids = [abs(p - (a + b * i)) for i, p in self.support["pts"]]
        self.support["dist"] = max(resids)
        return None


# ═══════════════════════════════════════════════════════════
# 便捷封装
# ═══════════════════════════════════════════════════════════

def run_trendline_breakout(df: pd.DataFrame, **kw):
    """df 需含 date/open/high/low/close（升序）。

    返回 (events, lines, tb)：
      events：break_up / break_down / resist_end / support_end
      lines：全部线段（含当前活跃）[{kind R/S, i0, i1, a, b, dist, active}] 供可视化
    """
    tb = TrendlineBreakout(**kw)
    events = []
    dates = df["date"].reset_index(drop=True)
    n = len(df)
    for _, row in df.iterrows():
        ev = tb.feed({"date": row["date"], "open": row["open"], "high": row["high"],
                      "low": row["low"], "close": row["close"]})
        if ev is not None:
            ev["date"] = row["date"]
            events.append(ev)
    lines = [dict(l, active=False) for l in tb.finished_lines]
    if tb.resist is not None:
        lines.append({"kind": "R", "i0": tb.resist["start_i"], "i1": tb.i,
                      "a": tb.resist["a"], "b": tb.resist["b"],
                      "dist": tb.resist["dist"], "active": True,
                      "formed": tb.resist.get("formed")})
    if tb.support is not None:
        lines.append({"kind": "S", "i0": tb.support["start_i"], "i1": tb.i,
                      "a": tb.support["a"], "b": tb.support["b"],
                      "dist": tb.support["dist"], "active": True,
                      "formed": tb.support.get("formed")})
    for l in lines:      # 附日期 + 速率（可视化用）
        l["d0"] = dates.iloc[min(l["i0"], n - 1)]
        l["d1"] = dates.iloc[min(l["i1"], n - 1)]
        l["rate"] = line_rate(l)
    return events, lines, tb
