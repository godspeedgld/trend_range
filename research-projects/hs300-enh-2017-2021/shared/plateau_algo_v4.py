"""平台突破 v4 —— v3 水平阻力/支撑带 + 双侧带生命周期（死亡机制）【修正版】。

v4.1（2026-09-04 修正）：初版 v4 丢失转折点 kind 导致高低点混灌阻力带——
现恢复 v3 语义：**H（转折高点）只进阻力带 r_bands，L（转折低点）只进支撑带 s_bands**；
突破事件（break_up）只从阻力带发。支撑带对称拥有生命周期与合并规则。

死亡机制（用户 2026-09-04 终版，双侧对称，收盘价双条件任一满足即死）：
  阻力带死：① 累计 ≥DEATH_CUM_DAYS(90) 日 close > line×(1+DEATH_ACC_PCT 0.10)
             ② 突破后某日 close > line×(1+DEATH_SPIKE_PCT 0.30)
  支撑带死：① 累计 ≥90 日 close < line×0.90；② 某日 close < line×0.70
  死带：不参与合并、不触发突破/跌破判定；可视化为灰色线段（终于死亡日）。
  ⚠ 演进史：DEATH_MULT=2.0(hi×2, +110%) 太苛 → 连续 60 日×+30%（V 型回调打断计数）→
  终版 = 累计 90 日×+10% + 单日收盘×+30% 冲高，两条件覆盖"长期越线"与"一次大突破"。

顺序（每 bar）：死亡检查（双侧）→ 转折点确认（带 kind）→ 各侧带维护 → 突破/跌破判定。
无未来：死亡/转折/突破全部用当日收盘与 ≤t 数据。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BAND_PCT = 0.05
BB_WINDOW, BB_K = 20, 1.0
DEATH_ACC_PCT = 0.10   # 累计条件阈值：收盘 > line×1.10（累计日数不计）
DEATH_CUM_DAYS = 90    # 累计 ≥90 日 close 越线 → 死
DEATH_SPIKE_PCT = 0.30 # 冲高条件：某日 close > line×1.30 → 立即死
# 初版演进：DEATH_MULT=2.0(hi×2→+110%) 太苛 → DEATH_PCT=0.30 连续60日 → 用户终版双条件


def _new_band(pts, band_pct, born_i, kind):
    """由点集构造带：line=均价，上下 band_pct。kind='R'（阻力/高点）| 'S'（支撑/低点）。"""
    line = float(np.mean([p for _, p in pts]))
    return {"pts": list(pts), "kind": kind, "line": line,
            "lo": line * (1 - band_pct), "hi": line * (1 + band_pct),
            "signaled": False, "born_i": born_i}


def _merge_recursive(bands, band_pct, born_i, kind):
    """同侧递归合并（闭区间相交）。被替换旧带弃置（本版不留 history）。"""
    changed = True
    while changed:
        changed = False
        n = len(bands)
        for a in range(n):
            for b in range(a + 1, n):
                A, B = bands[a], bands[b]
                if A["lo"] <= B["hi"] and B["lo"] <= A["hi"]:
                    merged = _new_band(A["pts"] + B["pts"], band_pct, born_i, kind)
                    bands = [x for k, x in enumerate(bands) if k not in (a, b)] + [merged]
                    changed = True
                    break
            if changed:
                break
    return bands


class BandBreakoutV4:
    """v4.1 状态机：v3 H/L 分流 + 双侧带生命周期。"""

    def __init__(self, band_pct=BAND_PCT, bb_window=BB_WINDOW, bb_k=BB_K,
                 death_acc_pct=DEATH_ACC_PCT, death_cum_days=DEATH_CUM_DAYS,
                 death_spike_pct=DEATH_SPIKE_PCT):
        self.band_pct = band_pct
        self.bb_window, self.bb_k = bb_window, bb_k
        self.death_acc_pct = death_acc_pct
        self.death_cum_days = death_cum_days
        self.death_spike_pct = death_spike_pct
        self.r_bands = []            # 活阻力带（只收高点）
        self.s_bands = []            # 活支撑带（只收低点）
        self.dead_bands = []         # 死带 [{..., dead_i}]（两侧共用，kind 区分）
        self.trend = 0
        self.hp_i, self.hp_p = -1, -1.0
        self.lp_i, self.lp_p = -1, -1.0
        self._started = False
        self.i = -1
        self._bars = []

    def _turning_step(self, high, low, ub, lb):
        """转折点确认，返回 (idx, price, kind) 或 None（与 v3 原版逐行同源）。"""
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
                    ev = (self.hp_i, self.hp_p, "H")     # 高点转折 → 阻力带
                self.trend, self.lp_i, self.lp_p = -1, self.i, low
        else:
            if low < self.lp_p:
                self.lp_i, self.lp_p = self.i, low
            elif high > ub:
                if self.lp_i >= 0:
                    ev = (self.lp_i, self.lp_p, "L")     # 低点转折 → 支撑带
                self.trend, self.hp_i, self.hp_p = 1, self.i, high
        return ev

    def feed(self, bar: dict) -> list:
        """逐 bar：死亡检查（双侧）→ 转折（kind 分流）→ 带维护 → 突破/跌破。"""
        self.i += 1
        c, h, l = float(bar["close"]), float(bar["high"]), float(bar["low"])
        if not self._started:
            self._started = True
            self._bars.append(c)
            return []
        self._bars.append(c)
        s = pd.Series(np.array(self._bars))
        ma, sd = s.rolling(self.bb_window).mean().iloc[-1], s.rolling(self.bb_window).std().iloc[-1]
        ub, lb = ma + self.bb_k * sd, ma - self.bb_k * sd

        # ═══ ⓪ 死亡检查（用户 2026-09-04 终版：收盘价双条件，任一满足即死）═══
        #   阻力带死：① 累计 ≥DEATH_CUM_DAYS 日 close > line×(1+DEATH_ACC_PCT)
        #             ② 突破后某日 close > line×(1+DEATH_SPIKE_PCT)
        #   支撑带死（对称）：① 累计 ≥DEATH_CUM_DAYS 日 close < line×(1−DEATH_ACC_PCT)
        #             ② 某日 close < line×(1−DEATH_SPIKE_PCT)
        for band in self.r_bands:
            if c > band["line"] * (1 + self.death_acc_pct):      # 累计条件（不打断）
                band["cum_cnt"] = band.get("cum_cnt", 0) + 1
            if (band.get("cum_cnt", 0) >= self.death_cum_days) or \
               (c > band["line"] * (1 + self.death_spike_pct)):  # 冲高条件
                band["dead_i"] = self.i
                self.dead_bands.append(band)
        for band in self.s_bands:
            if c < band["line"] * (1 - self.death_acc_pct):
                band["cum_cnt"] = band.get("cum_cnt", 0) + 1
            if (band.get("cum_cnt", 0) >= self.death_cum_days) or \
               (c < band["line"] * (1 - self.death_spike_pct)):
                band["dead_i"] = self.i
                self.dead_bands.append(band)
        self.r_bands = [b for b in self.r_bands if "dead_i" not in b]
        self.s_bands = [b for b in self.s_bands if "dead_i" not in b]

        # ═══ ⓪b 记录带"最后价格触及"（活带线段终点：最后一次 close 落 [lo,hi]）═══
        for band in self.r_bands + self.s_bands:
            if band["lo"] <= c <= band["hi"]:
                band["last_touch_i"] = self.i

        # ═══ ① 转折点 → 各侧带维护（kind 分流）═══
        tp = self._turning_step(h, l, ub, lb)
        if tp is not None:
            idx, price, kind = tp
            if kind == "H":
                self.r_bands.append(_new_band([(idx, price)], self.band_pct, self.i, "R"))
                self.r_bands = _merge_recursive(self.r_bands, self.band_pct, self.i, "R")
            else:
                self.s_bands.append(_new_band([(idx, price)], self.band_pct, self.i, "S"))
                self.s_bands = _merge_recursive(self.s_bands, self.band_pct, self.i, "S")
        # ═══ ② 突破/跌破判定（只对活带、本侧）═══
        events = []
        for band in self.r_bands:
            if not band["signaled"] and c > band["hi"]:
                band["signaled"] = True
                events.append({"type": "break_up", "date": bar.get("date"),
                               "line": band["line"], "hi": band["hi"], "lo": band["lo"],
                               "close": c, "degree": len(band["pts"])})
        for band in self.s_bands:
            if not band["signaled"] and c < band["lo"]:
                band["signaled"] = True
                events.append({"type": "break_down", "date": bar.get("date"),
                               "line": band["line"], "hi": band["hi"], "lo": band["lo"],
                               "close": c, "degree": len(band["pts"])})
        return events


def run_band_breakout_v4(df: pd.DataFrame, **kw):
    """df 需含 date/open/high/low/close（升序）。返回 (events, bands_all, bb)。

    events 含 break_up（阻力侧）与 break_down（支撑侧）。
    bands_all：活带 + 死带（kind R/S；死带含 dead_i → dead_date）。
    """
    bb = BandBreakoutV4(**kw)
    events = []
    dates = df["date"].reset_index(drop=True)
    n = len(df)
    for _, row in df.iterrows():
        for ev in bb.feed({"date": row["date"], "open": row["open"], "high": row["high"],
                           "low": row["low"], "close": row["close"]}):
            events.append(ev)
    bands_all = []
    for band in bb.r_bands + bb.s_bands + bb.dead_bands:
        rec = {"kind": band["kind"], "line": band["line"], "lo": band["lo"], "hi": band["hi"],
               "count": len(band["pts"]),
               "i0": min(i for i, _ in band["pts"]), "born_i": band["born_i"],
               "dead": "dead_i" in band, "dead_i": band.get("dead_i"),
               "last_touch_i": band.get("last_touch_i")}
        bands_all.append(rec)
    for b in bands_all:
        b["d0"] = dates.iloc[min(b["i0"], n - 1)]
        b["d_born"] = dates.iloc[min(b["born_i"], n - 1)]
        b["d_dead"] = dates.iloc[min(b["dead_i"], n - 1)] if b["dead_i"] is not None else None
        # 活带线段终点 = 最后一次收盘落 [lo,hi] 的日子（无触及则用 d_born 兜底）
        lt = b["last_touch_i"]
        b["d_last"] = (dates.iloc[min(lt, n - 1)] if lt is not None
                       else dates.iloc[min(b["born_i"], n - 1)])
    return events, bands_all, bb
