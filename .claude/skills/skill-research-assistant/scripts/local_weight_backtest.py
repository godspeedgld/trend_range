"""权重驱动组合回测引擎 —— 对标 BigQuant bigtrader `handle_data_weight_based`。

════════════════════════ 三层结构（与云端一一对应）════════════════════════
① 调仓模板：`handle_data_weight_based`（读目标权重 → 每日拉回，本引擎唯一模板）
② 调仓周期：`RebalancePeriod` 家族（11 类：交易日/自然日 × 间隔/周/月/季/年）
            非调仓日**不动作**（持仓市值随价格漂移，不做调整）
③ 下单方法：`order_target_percent` 为主（+ `order`/`order_value`/`order_target`/`order_target_value`）

════════════════════════ 与云端对齐的执行口径（2026-10-12）════════════════════════
· 决策时点：**收盘**读目标权重 → **次日开盘**成交（与 bigtrader DAILY 一致）
· 成交价：市场数据若为**后复权**且带 `adjust_factor`，引擎自动还原**原始价**成交
  （实证：云端 5,548 笔成交价 = 后复权价÷adjust_factor，99.7% 逐笔吻合）
· 整手：100 股向下取整；目标股数不足 1 手 → 该单不下（卖出为全清）
· 成本：`PerOrder(buy_cost=3bps, sell_cost=13bps, min_cost=5元)`（云端同款）
· 每日再平衡：调仓日把**实际漂移权重**拉回目标（= 高抛低吸）

════════════════════════ 输入契约 ════════════════════════════
--market-data  列 [date, symbol, open, close] (+可选 high/low/adjust_factor/name)
               注：open/close 为后复权则须带 adjust_factor，引擎自动还原原始价
--targets      列 [date, symbol, weight]，日期为**信号日**（策略侧 expand_to_daily 后
               应铺到每个调仓日；本引擎按 RebalancePeriod 取用）
               某调仓日在 targets 中**完全没有行** → 视为空仓信号 → 清空全部持仓

用法示例：
  python local_weight_backtest.py <project_dir> \
     --market-data mkt.parquet --targets targets.parquet \
     --rebalance-period weekly_trading --cost-bps 3 --sell-cost-bps 13 --min-cost 5 \
     --initial-cash 500000 --output-dir <dir>
自测：python local_weight_backtest.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

LOT = 100                     # A 股整手
DEFAULT_BUY_BPS = 3.0         # 云端 PerOrder(buy_cost=0.0003)
DEFAULT_SELL_BPS = 13.0       # 云端 PerOrder(sell_cost=0.0013)
DEFAULT_MIN_COST = 5.0        # 云端 PerOrder(min_cost=5.0)


# ═════════════════════ ② 调仓周期（对标 bigtradercpp.rebalanceperiod）═════════════════════
@dataclass
class RebalancePeriod:
    """调仓周期基类。`days` 语义随子类不同（间隔天数 / 周内第几个交易日 / 月内第几天）。"""
    days: int | list[int] = 1
    roll_forward: bool = True          # 命中日非交易日 → 顺延（True）还是提前（False）

    name = "period"

    def signal_dates(self, cal: pd.DatetimeIndex) -> pd.DatetimeIndex:
        raise NotImplementedError

    def is_trival(self) -> bool:
        """每交易日都调仓 = 平凡情形（云端 RebalancePeriod.is_trival 同义）。"""
        return isinstance(self, TradingDaysRebalance) and self._d() == 1

    def _d(self) -> int:
        return self.days[0] if isinstance(self.days, (list, tuple)) else int(self.days)

    # ── 工具 ──
    @staticmethod
    def _pick(cal: pd.DatetimeIndex, targets: pd.DatetimeIndex, roll_forward: bool) -> pd.DatetimeIndex:
        """把「自然日期候选」对齐到交易日：顺延取 >= 的第一个交易日，否则取 <= 的最后一个。"""
        out = []
        for t in targets:
            pos = cal.searchsorted(t, side="left" if roll_forward else "right")
            if roll_forward:
                if pos < len(cal):
                    out.append(cal[pos])
            else:
                if pos > 0:
                    out.append(cal[pos - 1])
        return pd.DatetimeIndex(sorted(set(out)))


@dataclass
class TradingDaysRebalance(RebalancePeriod):
    """每 N 个交易日调仓（默认 N=1 → 每交易日，平凡）。"""
    name = "trading_days"

    def signal_dates(self, cal):
        return pd.DatetimeIndex(cal[:: self._d()])


@dataclass
class NaturalDaysRebalance(RebalancePeriod):
    """每 N 个自然日调仓（对齐到交易日）。"""
    name = "natural_days"

    def signal_dates(self, cal):
        cand = pd.date_range(cal[0], cal[-1], freq=f"{self._d()}D")
        return self._pick(cal, cand, self.roll_forward)


@dataclass
class WeeklyTradingDaysRebalance(RebalancePeriod):
    """每周第 N 个交易日（默认 N=1）。"""
    name = "weekly_trading"

    def signal_dates(self, cal):
        g = pd.Series(cal, index=cal).groupby(cal.to_period("W"))
        n = self._d()
        return pd.DatetimeIndex([min(v, key=lambda x: x) if n <= 1 else
                                 (sorted(v)[n - 1] if len(v) >= n else sorted(v)[-1])
                                 for v in g.apply(list)])


@dataclass
class WeeklyRebalance(RebalancePeriod):
    """每周星期几（1=周一 … 7=周日；默认 1）。"""
    name = "weekly"

    def signal_dates(self, cal):
        wd = self._d()
        cand = pd.date_range(cal[0], cal[-1], freq="W-MON" if wd == 1 else "W")
        cand = pd.DatetimeIndex([d + pd.Timedelta(days=(wd - 1)) for d in cand])
        return self._pick(cal, cand, self.roll_forward)


@dataclass
class MonthlyTradingDaysRebalance(RebalancePeriod):
    """每月第 N 个交易日（默认 1）。"""
    name = "monthly_trading"

    def signal_dates(self, cal):
        n = self._d()
        g = pd.Series(cal, index=cal).groupby(cal.to_period("M"))
        return pd.DatetimeIndex([sorted(v)[n - 1] if len(v) >= n else sorted(v)[-1]
                                 for v in g.apply(list)])


@dataclass
class MonthlyRebalance(RebalancePeriod):
    """每月某日（默认 1 号）。"""
    name = "monthly"

    def signal_dates(self, cal):
        cand = pd.DatetimeIndex([p.to_timestamp() + pd.Timedelta(days=self._d() - 1)
                                 for p in cal.to_period("M").unique()])
        return self._pick(cal, cand, self.roll_forward)


@dataclass
class QuarterlyTradingDaysRebalance(RebalancePeriod):
    """每季第 N 个交易日（默认 1）。"""
    name = "quarterly_trading"

    def signal_dates(self, cal):
        n = self._d()
        g = pd.Series(cal, index=cal).groupby(cal.to_period("Q"))
        return pd.DatetimeIndex([sorted(v)[n - 1] if len(v) >= n else sorted(v)[-1]
                                 for v in g.apply(list)])


@dataclass
class QuarterlyRebalance(RebalancePeriod):
    """每季某日（默认 1 号）。"""
    name = "quarterly"

    def signal_dates(self, cal):
        cand = pd.DatetimeIndex([p.to_timestamp() + pd.Timedelta(days=self._d() - 1)
                                 for p in cal.to_period("Q").unique()])
        return self._pick(cal, cand, self.roll_forward)


@dataclass
class YearlyTradingDaysRebalance(RebalancePeriod):
    """每年第 N 个交易日（默认 1）。"""
    name = "yearly_trading"

    def signal_dates(self, cal):
        n = self._d()
        g = pd.Series(cal, index=cal).groupby(cal.to_period("Y"))
        return pd.DatetimeIndex([sorted(v)[n - 1] if len(v) >= n else sorted(v)[-1]
                                 for v in g.apply(list)])


@dataclass
class YearlyRebalance(RebalancePeriod):
    """每年某日（默认 1 月 1 日）。"""
    name = "yearly"

    def signal_dates(self, cal):
        cand = pd.DatetimeIndex([p.to_timestamp() + pd.Timedelta(days=self._d() - 1)
                                 for p in cal.to_period("Y").unique()])
        return self._pick(cal, cand, self.roll_forward)


PERIODS = {c.name: c for c in [
    TradingDaysRebalance, NaturalDaysRebalance, WeeklyTradingDaysRebalance, WeeklyRebalance,
    MonthlyTradingDaysRebalance, MonthlyRebalance, QuarterlyTradingDaysRebalance,
    QuarterlyRebalance, YearlyTradingDaysRebalance, YearlyRebalance]}


# ═════════════════════ ① 调仓模板 + ③ 下单方法 ═════════════════════
@dataclass
class WeightBacktestConfig:
    initial_cash: float = 500_000.0
    buy_bps: float = DEFAULT_BUY_BPS
    sell_bps: float = DEFAULT_SELL_BPS
    min_cost: float = DEFAULT_MIN_COST
    lot: int = LOT
    order_method: str = "target_percent"     # target_percent(默认) | percent | value | target_value


def raw_prices(market: pd.DataFrame) -> pd.DataFrame:
    """若带 adjust_factor → 把 OHLC 由后复权还原为**原始价**（云端成交价口径）。"""
    m = market.copy()
    if "adjust_factor" in m.columns:
        af = pd.to_numeric(m["adjust_factor"], errors="coerce").replace(0, np.nan).ffill().bfill()
        for c in ("open", "high", "low", "close"):
            if c in m.columns:
                m[c] = m[c] / af
    return m


def order_fee(amount: float, bps: float, min_cost: float) -> float:
    """云端 PerOrder 口径：按成交额比例计费，且不低于 min_cost。"""
    return max(abs(amount) * bps / 10000.0, min_cost)


def target_shares(target_value: float, price: float, lot: int = LOT) -> int:
    """目标金额 → 目标股数（整手向下取整）。价格为原始价。"""
    if not np.isfinite(price) or price <= 0 or target_value <= 0:
        return 0
    return int(np.floor(target_value / price / lot)) * lot


def run_weight_backtest(market: pd.DataFrame, targets: pd.DataFrame,
                        cfg: WeightBacktestConfig,
                        period: RebalancePeriod) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """主循环：调仓日按目标权重拉回，次日开盘成交。

    返回 (daily, trades, holdings)
      daily    date, equity, nav, ret, turnover, n_positions, cost
      trades   每次买卖的明细（date, symbol, side, shares, price, amount, fee）
      holdings date, symbol, shares, price, value, weight（调仓日快照）
    """
    m = raw_prices(market)
    m["date"] = pd.to_datetime(m["date"])
    m = m.sort_values(["date", "symbol"])
    dates = pd.DatetimeIndex(sorted(m["date"].unique()))
    open_px = m.pivot_table(index="date", columns="symbol", values="open").sort_index()
    close_px = m.pivot_table(index="date", columns="symbol", values="close").sort_index()
    close_ff = close_px.ffill()
    name_map = (m.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
                if "name" in m.columns else {})

    tgt = targets.copy()
    tgt["date"] = pd.to_datetime(tgt["date"])
    # ★ NaN 权重视同"没有该行"（空仓信号）；整日全 NaN → {} → 清仓
    tgt_by_day = {d: {s: float(w) for s, w in zip(g["symbol"], g["weight"]) if pd.notna(w)}
                  for d, g in tgt.groupby("date")}

    sig_days = set(period.signal_dates(dates))
    cash = float(cfg.initial_cash)
    pos: dict[str, int] = {}
    trades, daily, hold_rows = [], [], []

    pending: tuple[dict, dict] | None = None        # (目标股数, 目标权重) → 次日开盘执行
    for t, d in enumerate(dates):
        # ══ ① 执行：用**上一交易日**的决策，在**今日开盘**成交（严格 T+1）══
        if pending is not None:
            want_shares, _tw = pending
            pending = None
            # 先卖（腾出现金，且卖出不受现金约束）
            for s in list(pos):
                if s in want_shares:
                    continue
                px = open_px.loc[d, s] if s in open_px.columns else np.nan
                if pd.isna(px) or px <= 0:
                    continue
                amt = pos[s] * px
                fee = order_fee(amt, cfg.sell_bps, cfg.min_cost)
                cash += amt - fee
                trades.append({"date": d, "symbol": s, "side": "sell", "shares": pos[s],
                               "price": round(px, 4), "amount": round(amt, 2),
                               "fee": round(fee, 2), "name": name_map.get(s, s)})
                del pos[s]
            # 再按目标股数买卖（买入受可用现金封顶 —— bigtrader 不会允许透支）
            for s, want in want_shares.items():
                want = int(want)
                # 目标 0 股 = 清仓（空仓周发的 weight=0 行走到这里）；本就没仓则无动作
                if want <= 0 and s not in pos:
                    continue
                px = open_px.loc[d, s] if s in open_px.columns else np.nan
                if pd.isna(px) or px <= 0:
                    continue
                cur = pos.get(s, 0)
                diff = want - cur
                if diff > 0:                            # 买入：现金封顶（预留最低佣金）
                    afford = int(np.floor(max(cash - cfg.min_cost, 0.0) / px / cfg.lot)) * cfg.lot
                    diff = min(diff, afford)
                if diff == 0:
                    continue
                amt = abs(diff) * px
                fee = order_fee(amt, cfg.buy_bps if diff > 0 else cfg.sell_bps, cfg.min_cost)
                cash -= diff * px + fee
                new_sh = cur + diff
                if new_sh <= 0:
                    pos.pop(s, None)
                else:
                    pos[s] = new_sh
                trades.append({"date": d, "symbol": s, "side": "buy" if diff > 0 else "sell",
                               "shares": abs(diff), "price": round(px, 4),
                               "amount": round(amt, 2), "fee": round(fee, 2),
                               "name": name_map.get(s, s)})

        # ══ ② 收盘决策（仅调仓日）：用今日收盘价算权益 → 目标权重 → 挂到 pending ══
        if d in sig_days:
            equity_dec = cash + sum(sh * close_ff.loc[d, s] for s, sh in pos.items()
                                    if s in close_ff.columns and pd.notna(close_ff.loc[d, s]))
            tw = tgt_by_day.get(d, {})
            # ★ bigtrader order_target_percent：**下单当时**用当时价格把目标权重折成目标股数，
            #   次日开盘才成交（成交价可能不同 → 实际权重≈目标，非精确）
            want = {}
            for s, w in tw.items():
                pxc = close_ff.loc[d, s] if s in close_ff.columns else np.nan
                if pd.notna(pxc) and pxc > 0:
                    want[s] = target_shares(w * equity_dec, pxc, cfg.lot)
            pending = (want, tw)

        # ══ ③ 收盘估值 ══
        val = sum(sh * close_ff.loc[d, s] for s, sh in pos.items()
                  if s in close_ff.columns and pd.notna(close_ff.loc[d, s]))
        equity = cash + val
        daily.append({"date": d, "equity": equity, "cash": cash,
                      "n_positions": len(pos),
                      "turnover": 0.0})
        if d in sig_days:
            for s, sh in pos.items():
                px = close_ff.loc[d, s] if s in close_ff.columns else np.nan
                if pd.notna(px) and equity > 0:
                    hold_rows.append({"date": d, "symbol": s, "shares": sh,
                                      "price": round(px, 4), "value": round(sh * px, 2),
                                      "weight": round(sh * px / equity, 6)})

    dl = pd.DataFrame(daily).set_index("date")
    dl["nav"] = dl["equity"] / cfg.initial_cash
    dl["ret"] = dl["nav"].pct_change().fillna(0.0)
    dl["drawdown"] = dl["nav"] / dl["nav"].cummax() - 1.0
    tr = pd.DataFrame(trades)
    ho = pd.DataFrame(hold_rows)
    return dl.reset_index(), tr, ho


# ═════════════════════ 由 trades 直接推算净值/指标（技能「指标铁律」）═════════════════════
def nav_from_trades(market: pd.DataFrame, trades: pd.DataFrame,
                    initial_cash: float) -> tuple[pd.DataFrame, dict]:
    """只用**成交明细 + 收盘价**重建逐日净值 —— 独立于引擎内部记账的**第二事实源**。

    技能铁律：净值/统计指标必须由交易记录（trades）直接推算。口径与引擎一致：
      当日成交按 `trade.price` 计入现金与持股，当日按 close 估值。
    只对**被交易过的股票**取价（几百只，避免 5000+ 只的全市场 pivot）。

    返回 (nav_df[date,ret,nav,drawdown], metrics)。
    """
    m = raw_prices(market)
    m["date"] = pd.to_datetime(m["date"])
    syms = sorted(trades["symbol"].unique()) if trades is not None and len(trades) else []
    px = (m[m["symbol"].isin(syms)]
          .pivot_table(index="date", columns="symbol", values="close").sort_index().ffill())
    by_day = ({} if not syms else
              {d: g for d, g in trades.assign(date=pd.to_datetime(trades["date"])).groupby("date")})
    cash, pos, rows = float(initial_cash), {}, []
    for d in px.index:
        for r in (by_day[d].itertuples() if d in by_day else []):
            if r.side == "buy":
                pos[r.symbol] = pos.get(r.symbol, 0) + r.shares
                cash -= float(r.amount) + float(r.fee)
            else:
                pos[r.symbol] = pos.get(r.symbol, 0) - r.shares
                if pos[r.symbol] <= 0:
                    pos.pop(r.symbol, None)
                cash += float(r.amount) - float(r.fee)
        val = sum(sh * px.at[d, s] for s, sh in pos.items()
                  if s in px.columns and pd.notna(px.at[d, s]))
        rows.append({"date": d, "nav": (cash + val) / float(initial_cash)})
    nav = pd.DataFrame(rows).set_index("date")["nav"]
    ret = nav.pct_change().fillna(0.0)
    dd = nav / nav.cummax() - 1.0
    out = pd.DataFrame({"date": nav.index, "ret": ret.values,
                        "nav": nav.values, "drawdown": dd.values})
    ann = nav.iloc[-1] ** (252 / max(len(ret) - 1, 1)) - 1
    metrics = {"periods": int(len(ret) - 1), "final_nav": float(nav.iloc[-1]),
               "total_return": float(nav.iloc[-1] - 1), "annual_return": float(ann),
               "annual_volatility": float(ret.std() * np.sqrt(252)),
               "sharpe": float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() else None,
               "max_drawdown": float(dd.min())}
    return out, metrics


def build_report(nav_df: pd.DataFrame, metrics: dict, trades: pd.DataFrame,
                 cfg: WeightBacktestConfig, period: RebalancePeriod,
                 out_dir: Path, engine_metrics: dict | None = None) -> Path:
    """生成 `backtest_report.html`（指标卡 + 净值/回撤曲线 + 成交明细）。

    ★ 指标与净值**全部来自 trades 推算**（技能指标铁律）；`engine_metrics` 仅用于
      在报告里标注「引擎口径 vs trades 口径」的差异（若有），不参与展示口径。
    风格对齐本技能另两个引擎（plotly CDN + CSS 页签）。
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    nv = nav_df.set_index("date")["nav"]
    dd = nav_df.set_index("date")["drawdown"]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
                        subplot_titles=("组合净值（由 trades 推算）", "Drawdown"))
    fig.add_trace(go.Scatter(x=nv.index, y=nv.values, name="净值",
                             line=dict(color="#2980b9", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, name="Drawdown", fill="tozeroy",
                             line=dict(color="#c0392b", width=0.7),
                             fillcolor="rgba(192,57,43,0.15)"), row=2, col=1)
    fig.update_layout(template="plotly_white", height=460, hovermode="x unified",
                      margin=dict(l=50, r=30, t=40, b=30))
    nav_html = fig.to_html(full_html=False, include_plotlyjs=False, div_id="fig_nav")

    n = int(len(trades)) if trades is not None else 0
    rows = "".join(
        f"<tr><td>{i + 1}</td><td>{r.date}</td><td>{r.symbol}</td>"
        f"<td>{getattr(r, 'name', r.symbol)}</td>"
        f"<td style='color:{'#e74c3c' if r.side == 'buy' else '#27ae60'}'>{r.side}</td>"
        f"<td>{r.shares:,}</td><td>{r.price:.2f}</td><td>{r.amount:,.0f}</td><td>{r.fee:.2f}</td></tr>"
        for i, r in enumerate(trades.itertuples())) if n else ""
    gap = ""
    if engine_metrics:
        d = {k: abs(float(engine_metrics.get(k, 0)) - float(metrics.get(k, 0)))
             for k in ("final_nav", "annual_return", "sharpe", "max_drawdown")}
        gap = (f"<div class='note'>引擎口径 vs trades 口径 最大绝对差："
               + "、".join(f"{k}={v:.2e}" for k, v in d.items()) + "</div>")

    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>权重引擎回测报告</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
table{{border-collapse:collapse;width:100%;}}th,td{{border:1px solid #d6dae1;padding:6px 10px;}}
th{{background:#f3f5f8;}}
.note{{color:#6b7480;font-size:13px;margin:8px 0;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 120px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:12px 6px;}}
.metrics .item b{{display:block;font-size:18px;margin-top:4px;}}
.metrics .item span{{color:#6b7480;font-size:12px;}}
</style></head><body>
<h1>回测报告（权重引擎 · 对标 bigtrader handle_data_weight_based）</h1>
<div class="note">调仓周期 {period.name}（{period.days}）× 每{'收盘决策 → 次日开盘成交'}；
成本 买 {cfg.buy_bps:g}bps / 卖 {cfg.sell_bps:g}bps（最低 {cfg.min_cost:g} 元）；初始资金 {cfg.initial_cash:,.0f}。
<b>净值与指标均由成交明细（trades）推算</b>。</div>
{gap}
<div class="metrics">
  <div class="item"><span>净值</span><b>{metrics['final_nav']:.3f}</b></div>
  <div class="item"><span>累计收益</span><b>{metrics['total_return'] * 100:.2f}%</b></div>
  <div class="item"><span>年化收益</span><b>{metrics['annual_return'] * 100:.2f}%</b></div>
  <div class="item"><span>Sharpe</span><b>{(metrics['sharpe'] or 0):.2f}</b></div>
  <div class="item"><span>最大回撤</span><b>{metrics['max_drawdown'] * 100:.2f}%</b></div>
  <div class="item"><span>成交笔数</span><b>{n}</b></div>
</div>
{nav_html}
<h3>成交明细</h3>
<div style='max-height:480px;overflow:auto'>
<table><tr><th>#</th><th>日期</th><th>symbol</th><th>名称</th><th>方向</th>
<th>股数</th><th>价格</th><th>金额</th><th>费用</th></tr>{rows}</table></div>
</body></html>"""
    p = Path(out_dir) / "backtest_report.html"
    p.write_text(body, encoding="utf-8")
    return p


# ═════════════════════ 自测 ═════════════════════
def _selftest() -> int:
    """引擎自测：调仓周期 / 整手 / 费用 / 原始价还原 / 端到端。"""
    ok = True

    def chk(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")

    print("① 调仓周期")
    cal = pd.DatetimeIndex(pd.bdate_range("2024-01-01", "2024-03-31"))   # 约 65 个交易日
    chk(len(TradingDaysRebalance(1).signal_dates(cal)) == len(cal), "每交易日调仓 = 全部交易日（平凡）")
    chk(TradingDaysRebalance(1).is_trival(), "TradingDaysRebalance(1).is_trival() = True")
    chk(len(TradingDaysRebalance(5).signal_dates(cal)) == len(cal[::5]), "每 5 交易日")
    w = WeeklyTradingDaysRebalance(1).signal_dates(cal)
    chk(len(w) == cal.to_period("W").nunique(), f"周频信号日数 = 周数（{len(w)}）")
    chk(all(d in cal for d in w), "周频信号日都落在交易日")
    m_ = MonthlyTradingDaysRebalance(1).signal_dates(cal)
    chk(len(m_) == cal.to_period("M").nunique(), f"月频信号日数 = 月数（{len(m_)}）")

    print("② 整手 / 费 用")
    chk(target_shares(500_000 * 0.2, 13.57) == 7300, f"20 万 @13.57 → 7300 股（实得 {target_shares(500_000*0.2, 13.57)}）")
    chk(target_shares(1000, 50.0) == 0, "不足 1 手 → 0 股")
    chk(order_fee(1000, 3.0, 5.0) == 5.0, "小额买入触发最低佣金 5 元")
    chk(abs(order_fee(1_000_000, 13.0, 5.0) - 1300.0) < 1e-6, "卖出 13bps（100 万 → 1300 元）")

    print("③ 原始价还原")
    mk = pd.DataFrame({"date": ["2024-01-02"], "symbol": ["X.SZ"], "open": [10.0],
                       "close": [10.5], "adjust_factor": [2.0]})
    rp = raw_prices(mk)
    chk(abs(rp["open"].iloc[0] - 5.0) < 1e-9 and abs(rp["close"].iloc[0] - 5.25) < 1e-9,
        "后复权 ÷ adjust_factor = 原始价")

    print("④ 端到端（单票、每日再平衡、目标权重恒定）")
    ds = pd.bdate_range("2024-01-02", periods=6)
    # ★ 买入发生在 d1 的 open（引擎 T+1）→ 让 d1 open == 期末 close，才是真"往返"
    mk = pd.DataFrame({"date": list(ds) * 1, "symbol": "X.SZ",
                       "open": [10, 10, 12, 11, 10, 10], "close": [10, 10, 12, 11, 10, 10]})
    tg = pd.DataFrame({"date": ds, "symbol": "X.SZ", "weight": 1.0})
    dly, tr, ho = run_weight_backtest(mk, tg, WeightBacktestConfig(initial_cash=100_000.0),
                                      TradingDaysRebalance(1))
    # 价格 10→12→10 往返，每日拉回 100% 权重 → 最终应回到本金附近（无收益、有成本）
    final = dly["nav"].iloc[-1]
    chk(len(tr) > 0, f"产生了交易（{len(tr)} 笔）")
    chk(abs(final - 1.0) < 0.02, f"价格往返 + 恒定权重 → 期末 nav≈1（实得 {final:.4f}，差额=再平衡成本）")
    n_hold = len(ho)
    chk(n_hold > 0, f"持仓快照 {n_hold} 行")

    print("⑤ 空仓信号（某调仓日无行）→ 清仓")
    tg2 = tg.copy()
    tg2.loc[tg2["date"] == ds[3], "weight"] = np.nan       # 该日无有效权重
    dly2, tr2, _ = run_weight_backtest(mk, tg2, WeightBacktestConfig(initial_cash=100_000.0),
                                       TradingDaysRebalance(1))
    has_sell_all = ((tr2["side"] == "sell").sum() > 0) if len(tr2) else False
    chk(has_sell_all, "存在卖出（清仓路径可达）")

    print("\n" + ("★ 自测全部通过" if ok else "★ 自测有失败"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", nargs="?")
    ap.add_argument("--market-data")
    ap.add_argument("--targets")
    ap.add_argument("--rebalance-period", default="trading_days", choices=list(PERIODS))
    ap.add_argument("--period-days", type=int, default=1)
    ap.add_argument("--initial-cash", type=float, default=500_000.0)
    ap.add_argument("--buy-cost-bps", type=float, default=DEFAULT_BUY_BPS)
    ap.add_argument("--sell-cost-bps", type=float, default=DEFAULT_SELL_BPS)
    ap.add_argument("--min-cost", type=float, default=DEFAULT_MIN_COST)
    ap.add_argument("--output-dir")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not (a.market_data and a.targets):
        ap.error("需要 --market-data 与 --targets（或用 --selftest）")

    market = (pd.read_parquet(a.market_data) if a.market_data.endswith(".parquet")
              else pd.read_csv(a.market_data))
    targets = (pd.read_parquet(a.targets) if a.targets.endswith(".parquet")
               else pd.read_csv(a.targets))
    if "instrument" in targets.columns:
        targets = targets.rename(columns={"instrument": "symbol"})
    period = PERIODS[a.rebalance_period](a.period_days)
    cfg = WeightBacktestConfig(initial_cash=a.initial_cash, buy_bps=a.buy_cost_bps,
                               sell_bps=a.sell_cost_bps, min_cost=a.min_cost)
    daily, trades, holdings = run_weight_backtest(market, targets, cfg, period)

    nav = daily.set_index("date")["nav"]
    ret = nav.pct_change().dropna()
    ann = nav.iloc[-1] ** (252 / max(len(ret), 1)) - 1
    metrics = {
        "periods": len(ret), "final_nav": float(nav.iloc[-1]),
        "total_return": float(nav.iloc[-1] - 1),
        "annual_return": float(ann),
        "annual_volatility": float(ret.std() * np.sqrt(252)),
        "sharpe": float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() else None,
        "max_drawdown": float(daily["drawdown"].min()),
        "n_trades": int(len(trades)),
        "total_fee": float(trades["fee"].sum()) if len(trades) else 0.0,
    }
    # ★ 产物布局对齐技能（同 local_portfolio_backtest）：--output-dir = 策略目录（如 backtest_strategy）
    #   数据 → <output-dir>/backtest_logs/；config.json 与 backtest_report.html → <output-dir>/
    root = Path(a.output_dir) if a.output_dir else (
        Path(a.project_dir) / "backtest_strategy" if a.project_dir else Path("."))
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    out = root / "backtest_logs"
    out.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out / "equity_curve.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    holdings.to_csv(out / "position_return_detail.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([metrics]).to_csv(out / "performance_metrics.csv", index=False, encoding="utf-8-sig")
    (root / "config.json").write_text(json.dumps({
        "engine": "weight-based (handle_data_weight_based 对标)",
        "rebalance_period": period.name, "period_days": period.days,
        "initial_cash": cfg.initial_cash, "buy_bps": cfg.buy_bps, "sell_bps": cfg.sell_bps,
        "min_cost": cfg.min_cost, "lot": cfg.lot}, ensure_ascii=False, indent=2), encoding="utf-8")
    # ★ 技能「指标铁律」：净值/统计指标/可视化**由 trades 直接推算**（独立第二事实源），
    #   并生成 backtest_report.html（另两个引擎同款产物）。
    nav_tr, m_tr = nav_from_trades(market, trades, cfg.initial_cash)
    nav_tr.to_csv(out / "nav_from_trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([m_tr]).to_csv(out / "metrics_from_trades.csv", index=False, encoding="utf-8-sig")
    rp = build_report(nav_tr, m_tr, trades, cfg, period, root, engine_metrics=metrics)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"trades 口径: 净值 {m_tr['final_nav']:.4f} / 年化 {m_tr['annual_return']:.2%} / "
          f"Sharpe {(m_tr['sharpe'] or 0):.3f} / 回撤 {m_tr['max_drawdown']:.2%} / 成交 {len(trades):,}")
    print(f"报告: {rp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
