"""平台突破 v3 —— 水平阻力带/支撑带系统（用户 2026-08-28 指定，analysis_006）。

承接链：v1 plateau_algo.py（冻结）→ v2.x plateau_algo_v2.py（**v2.7 锁死，冻结**）→ 本文件 v3。
范式变化：v2.x 是斜趋势线（OLS 拟合），v3 回到**水平带**（转折点价格聚类，HSAR 思想的带状版）：

  1. 转折点识别：与 v2.7 完全一致（布林带状态机 BB(N=20, K=1.0)，逐 bar 增量）
  2. 阻力带规则（用户 3.2）：
     · 初始化：一个转折高点构成一条阻力线（价格 = 高点价），线上下 5% 为阻力带
     · 合并：新转折高点构成的带与其他阻力带重叠 → 合并
     · 合并规则：带内**所有转折高点的均值**为新阻力线，上下 5% 为新带；旧带剔除
     · 递归合并：合并后的带再与其他带重叠则继续合并，直到无重叠
     · 计数 = 该带合并的转折高点个数；带记录全部高点
  3. 支撑带规则（用户 3.3）：转折低点对称
  4. 突破（用户 3.4）：**K线收盘价** > 阻力带上边界 → 突破；突破程度 = 被突破带计数
  5. 跌破（用户 3.5）：收盘价 < 支撑带下边界 → 跌破；跌破程度 = 带计数

实现口径（用户未明确处的决定，全部无未来数据）：
  · 每带只发一次信号（signaled）；带被合并后旧带剔除、新带为未发信号状态（可再发）
  · 带的建立/合并发生在转折点**确认日**（≤t 信息）；当日即可参与突破判定
    （顺序同 v2.7：先转折点→带维护，后突破判定）
  · 重叠 = 闭区间相交（[l×0.95, l×1.05] 与 [l2×0.95, l2×1.05] 有交集）
  · 同日多带被突破：每带各发一个事件（各自 degree）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── 参数 ──
BAND_PCT = 0.05          # 带宽：线上下 5%
BB_WINDOW, BB_K = 20, 1.0  # 转折点（同 v2.7）


def _new_band(pts, band_pct, born_i, kind):
    """由点集构造带：line=均价，上下 band_pct。"""
    line = float(np.mean([p for _, p in pts]))
    return {"pts": list(pts), "kind": kind, "line": line,
            "lo": line * (1 - band_pct), "hi": line * (1 + band_pct),
            "signaled": False, "born_i": born_i}


def _merge_recursive(bands, band_pct, born_i, closed_out):
    """递归合并重叠带（闭区间相交）。被替换的旧带记入 closed_out（可视化用）。"""
    changed = True
    while changed:
        changed = False
        n = len(bands)
        for a in range(n):
            for b in range(a + 1, n):
                A, B = bands[a], bands[b]
                if A["lo"] <= B["hi"] and B["lo"] <= A["hi"]:
                    closed_out.append(A)
                    closed_out.append(B)
                    merged = _new_band(A["pts"] + B["pts"], band_pct, born_i, A["kind"])
                    bands = [x for k, x in enumerate(bands) if k not in (a, b)] + [merged]
                    changed = True
                    break
            if changed:
                break
    return bands


class BandBreakout:
    """v3 水平带状态机：逐日 feed(bar) → 事件列表。

    状态：
      r_bands / s_bands：活跃阻力/支撑带（水平，含全部转折点）
      band_history：被合并剔除的旧带（可视化）
    事件：
      break_up   {date, line, hi, lo, count, close, degree}
      break_down {date, line, hi, lo, count, close, degree}
    铁律：无未来数据（转折点确认 ≤t；带的建立/合并在确认日；突破判定用当日收盘）。
    """

    def __init__(self, band_pct=BAND_PCT, bb_window=BB_WINDOW, bb_k=BB_K):
        self.band_pct = band_pct
        self.bb_window, self.bb_k = bb_window, bb_k
        self.r_bands = []
        self.s_bands = []
        self.band_history = []        # 被合并剔除的旧带
        # 转折点状态机（同 v2.7）
        self.trend = 0
        self.hp_i, self.hp_p = -1, -1.0
        self.lp_i, self.lp_p = -1, -1.0
        self._started = False
        self.i = -1
        self._bars = []

    # ── 转折点增量推进（逻辑同 v2.7 _turning_step）──
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

    def feed(self, bar: dict) -> list:
        """逐 bar 推进。返回事件列表（可为空）。"""
        self.i += 1
        date = bar.get("date")
        c, h, l = float(bar["close"]), float(bar["high"]), float(bar["low"])
        if not self._started:
            self._started = True
            self._bars.append(c)
            return []
        self._bars.append(c)
        s = pd.Series(np.array(self._bars))
        ma, sd = s.rolling(self.bb_window).mean().iloc[-1], s.rolling(self.bb_window).std().iloc[-1]
        ub, lb = ma + self.bb_k * sd, ma - self.bb_k * sd

        # ═══ ① 转折点确认 → 带维护（初始化 + 递归合并）═══
        tp = self._turning_step(h, l, ub, lb)
        if tp is not None:
            idx, price, kind = tp
            if kind == "H":
                self.r_bands.append(_new_band([(idx, price)], self.band_pct, self.i, "R"))
                self.r_bands = _merge_recursive(self.r_bands, self.band_pct,
                                                self.i, self.band_history)
            else:
                self.s_bands.append(_new_band([(idx, price)], self.band_pct, self.i, "S"))
                self.s_bands = _merge_recursive(self.s_bands, self.band_pct,
                                                self.i, self.band_history)

        # ═══ ② 突破/跌破判定（收盘价 vs 带边界，每带一次）═══
        events = []
        for band in self.r_bands:
            if not band["signaled"] and c > band["hi"]:
                band["signaled"] = True
                events.append({"type": "break_up", "date": date,
                               "line": band["line"], "hi": band["hi"], "lo": band["lo"],
                               "count": len(band["pts"]), "close": c,
                               "degree": len(band["pts"])})
        for band in self.s_bands:
            if not band["signaled"] and c < band["lo"]:
                band["signaled"] = True
                events.append({"type": "break_down", "date": date,
                               "line": band["line"], "hi": band["hi"], "lo": band["lo"],
                               "count": len(band["pts"]), "close": c,
                               "degree": len(band["pts"])})
        return events


# ═══════════════════════════════════════════════════════════
# 便捷封装
# ═══════════════════════════════════════════════════════════

def run_band_breakout(df: pd.DataFrame, **kw):
    """df 需含 date/open/high/low/close（升序）。

    返回 (events, bands, bb)：
      events：break_up / break_down（含 degree）
      bands：全部带段（含活跃）[{kind R/S, line, lo, hi, count, i0(最早点), i1(结束/当前), active}]
    """
    bb = BandBreakout(**kw)
    events = []
    dates = df["date"].reset_index(drop=True)
    n = len(df)
    for _, row in df.iterrows():
        for ev in bb.feed({"date": row["date"], "open": row["open"], "high": row["high"],
                           "low": row["low"], "close": row["close"]}):
            events.append(ev)

    bands = []
    for band in bb.band_history:
        bands.append({"kind": band["kind"], "line": band["line"], "lo": band["lo"],
                      "hi": band["hi"], "count": len(band["pts"]),
                      "i0": min(i for i, _ in band["pts"]),
                      "i1": band["born_i"], "active": False})
    for kind, lst in (("R", bb.r_bands), ("S", bb.s_bands)):
        for band in lst:
            bands.append({"kind": kind, "line": band["line"], "lo": band["lo"], "hi": band["hi"],
                          "count": len(band["pts"]),
                          "i0": min(i for i, _ in band["pts"]),
                          "i1": bb.i, "active": True})
    for b in bands:
        b["d0"] = dates.iloc[min(b["i0"], n - 1)]
        b["d1"] = dates.iloc[min(b["i1"], n - 1)]
    return events, bands, bb
