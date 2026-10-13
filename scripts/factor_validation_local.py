"""本地版 AlphaMiner —— 对齐云端 `scripts/factor_val_cloud.ipynb`（BigQuant 平台因子分析工具）。

════════════════════════ 与云端的三处替换 ════════════════════════
  云端                                  本地
  ────────────────────────────────────────────────────────────────
  dai.query(SQL 里算因子+过滤+预处理)     duckdb **只读原始列**；因子/过滤/预处理**全在 Python**
  平台 SQL 标量函数 c_*                   Python 实现（见 preprocess_factor / c_normalize / c_neutralize）
  bigcharts.Chart(...)                    plotly（单 HTML，零 CDN；7 张图对齐云端 render）

⚠ 设计原则（用户 2026-10-13 指定）：**读表用 duckdb，计算全用 Python**
  —— 目的：① 便于多进程/多线程加速（`--jobs`）② 与策略侧（周频/候选池）共用同一套 Python 算子。

════════════════════════ 平台函数的本地实现（逐字对齐）════════════════════════
  平台 SQL 原文：
      clip(factor, c_avg(factor) - 3 * c_std(factor), c_avg(factor) + 3 * c_std(factor)) AS clipped_factor,
      c_normalize(clipped_factor)                                              AS normalized_factor,
      c_neutralize(normalized_factor, sw2021_level1, LOG(total_market_cap))     AS neutralized_factor
  本地实现：
      clipped      = 逐日截面  clip(f, mean(f) - 3*sd(f), mean(f) + 3*sd(f))          [sd=样本std, ddof=1]
      normalized   = 逐日截面  (clipped - mean) / sd
      neutralized  = 逐日截面  OLS( process_factor(f) ~ 行业哑变量 + log(市值) + 常数 ) 的**残差**
                     其中 process_factor(f) = MAD 去极值(median±3*1.4826*MAD) → z-score(ddof=1)
                     （官方 c_neutralize 内部**会重做一遍** MAD+z-score；OLS 残差对仿射变换不变，
                       故外层那两步对最终残差几乎无影响——保留是为了**逐字对齐平台 SQL**）

════════════════════════ 用法 ════════════════════════
  python scripts/factor_validation_local.py                      # 跑内置示例因子
  python scripts/factor_validation_local.py --jobs 8             # 预处理多进程
  python scripts/factor_validation_local.py --out out.html
  # 代码里自定义因子：AlphaMiner(params, factor_fn=my_fn).render()
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

POOLS = {"沪深300": "000300.SH", "中证500": "000905.SH", "中证1000": "000852.SH"}
BENCH = POOLS

PARAMS = {
    "alpha_name": "turn_60",
    "alpha_name_chinese": "60日换手率均值",
    "alpha_desc": "个股 60 个交易日换手率均值（示例）",
    "group_num": 10,
    "instruments": "中证500",     # 全市场 / 中证500 / 中证1000 / 沪深300
    "benchmark": "中证500",
    "data_process": True,        # 去极值→标准化→中性化
    "start": "2019-01-01",
    "end": None,                 # None = 库内最新
}


# ══════════════════════════ 因子库（纯 Python，可直接替换）══════════════════════════
class RollingFactor:
    """内置因子：某列的 N 日滚动 agg（mean/std/max/min/sum）。
    ★ 用**类实例**而非闭包 —— 可 pickle，才能在多进程里并行算因子。"""

    def __init__(self, agg: str = "mean", col: str = "turn", win: int = 60,
                 min_periods: int | None = None):
        self.agg, self.col, self.win = agg, col, win
        self.min_periods = min_periods or win

    def __call__(self, bars: pd.DataFrame) -> pd.Series:
        return getattr(bars[self.col].rolling(self.win, min_periods=self.min_periods), self.agg)()

    def __repr__(self):
        return f"{self.col}_{self.win}_{self.agg}"


def make_rolling(agg: str = "mean", col: str = "turn", win: int = 60, min_periods: int | None = None):
    """内置因子工厂。"""
    return RollingFactor(agg, col, win, min_periods)


def _factor_worker(args):
    """多进程 worker：算一只标的的因子。"""
    name, sub, fn = args
    return pd.DataFrame({"date": sub["date"].values, "instrument": name,
                         "factor": np.asarray(fn(sub), dtype=float)})


def make_pctrank_combo(spec: list[tuple[str, float]]):
    """截面百分位组合（对齐云端 alpha_test 示例：0.8*pct_rank(total_market_cap)+0.2*pct_rank(turn)）。
    ★ 注意：pct_rank 是**截面**算子 → 这里按 (symbol, date) 值返回，截面排名在 __init__ 里做。

    spec = [("total_market_cap", 0.8), ("turn", 0.2)]；权重不归一，与云端写法一致。
    """
    def _f(bars: pd.DataFrame) -> pd.Series:
        return pd.Series(np.nan, index=bars.index)      # 占位：真正的截面排名见 _cross_rank
    _f.__name__ = "pctrank_combo_" + "_".join(c for c, _ in spec)
    _f.cross_rank = spec                                # 标记：需要截面排名
    return _f


FACTOR_LIB = {
    "turn_60": make_rolling("mean", "turn", 60),
    "turn_20": make_rolling("mean", "turn", 20),
    "ret_20": None,   # 占位（示例，实际用 alpha_factor_fn 传）
}


# ══════════════════════════ 平台函数的 Python 实现 ══════════════════════════
def clip_3sigma(v: np.ndarray) -> np.ndarray:
    """平台 `clip(f, c_avg(f)-3*c_std(f), c_avg(f)+3*c_std(f))`（逐日截面，ddof=1）。"""
    mu, sd = np.nanmean(v), np.nanstd(v, ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return v
    return np.clip(v, mu - 3 * sd, mu + 3 * sd)


def c_normalize(v: np.ndarray) -> np.ndarray:
    """平台 `c_normalize(f) = (f-μ)/σ`（逐日截面，ddof=1）。"""
    mu, sd = np.nanmean(v), np.nanstd(v, ddof=1)
    return (v - mu) / sd if np.isfinite(sd) and sd != 0 else v


def process_factor(v: np.ndarray) -> np.ndarray:
    """官方 c_neutralize 内部的 `process_factor`：MAD 去极值(median±3*1.4826*MAD) → z-score(ddof=1)。"""
    med = np.nanmedian(v)
    mad = np.nanmedian(np.abs(v - med)) * 3 * 1.4826
    if np.isfinite(mad) and mad > 0:
        v = np.clip(v, med - mad, med + mad)
    sd = np.nanstd(v, ddof=1)
    return (v - np.nanmean(v)) / sd if np.isfinite(sd) and sd != 0 else v - np.nanmean(v)


def c_neutralize(f: np.ndarray, ind: np.ndarray, log_mcap: np.ndarray) -> np.ndarray:
    """平台 `c_neutralize(f, sw2021_level1, LOG(total_market_cap))`：
    process_factor(f) 后对 [行业哑变量 + log市值 + 常数] 做 OLS，取残差。"""
    y = process_factor(f)
    ok = np.isfinite(y) & np.isfinite(log_mcap)
    if ok.sum() < 30:
        return np.full_like(y, np.nan)
    ind_ok = pd.Series(ind[ok]).fillna("未知")
    X = pd.get_dummies(pd.DataFrame({"mcap": log_mcap[ok], "ind": ind_ok.values}),
                       columns=["ind"], drop_first=True).astype(float)
    X.insert(0, "const", 1.0)
    beta, *_ = np.linalg.lstsq(X.values, y[ok], rcond=None)     # method='pinv'
    resid = np.full_like(y, np.nan)
    resid[ok] = y[ok] - X.values @ beta
    return resid


def preprocess_frame(g: pd.DataFrame) -> pd.DataFrame:
    """单日截面的完整预处理（= 平台 SQL 的那三行）。可在子进程里调用。"""
    v = g["factor"].to_numpy(dtype=float)
    if v.size:
        v = clip_3sigma(v)           # clipped_factor
        v = c_normalize(v)           # normalized_factor
        v = c_neutralize(v, g["industry"].to_numpy(), g["log_mcap"].to_numpy())   # neutralized_factor
    g = g.copy()
    g["factor"] = v
    return g


# ══════════════════════════ 主类 ══════════════════════════
class AlphaMiner:
    """本地因子分析。用法：AlphaMiner(params, factor_fn).render()"""

    def __init__(self, params: dict | None = None, factor_fn=None, jobs: int = 1):
        self.p = {**PARAMS, **(params or {})}
        self.factor_fn = factor_fn or FACTOR_LIB.get(self.p["alpha_name"]) or make_rolling("mean", "turn", 60)
        self.jobs = max(1, int(jobs))
        t0 = time.time()

        # ① 读原始列（duckdb 只做「读」，不做计算）
        self.bars, self.univ = self._read_raw()
        print(f"① 原始数据 {len(self.bars):,} 行 / {self.bars['instrument'].nunique():,} 只 / "
              f"{self.bars['date'].min().date()}~{self.bars['date'].max().date()} ({time.time()-t0:.0f}s)")

        # ② 因子（纯 Python；逐标的滚动）
        self.raw_factor = self._compute_factor()
        print(f"② 因子计算完成（{getattr(self.factor_fn, '__name__', None) or repr(self.factor_fn)}）")

        # ③ 预处理：clip → normalize → neutralize（纯 Python，可多进程）
        self.factor = self._preprocess()
        print(f"③ 预处理完成（{'开' if self.p['data_process'] else '关'}；jobs={self.jobs}）")

        # ④ 未来收益（纯 Python shift/lead）
        self.ret = self._forward_return()

        # ⑤ 分组
        self.grp = self._group()
        print(f"④ 分组完成：{self.grp['date'].nunique()} 个交易日 × {self.p['group_num']} 组")

        # ⑥ 分组收益 / 累计 / 基准；⑦ IC
        self.group_ret, self.group_cum = self._group_returns()
        self.ic = self._ic_series()
        self.yearly = self._yearly_perf()
        print(f"⑤ 指标计算完成（总 {time.time()-t0:.0f}s）")

    # ───────── ① 读原始列（唯一用 duckdb 的地方；只 SELECT + JOIN，无窗口/无 c_* 函数）─────────
    def _read_raw(self):
        p = self.p
        con = duckdb.connect(str(WAREHOUSE), read_only=True)
        end = p["end"] or str(con.execute("SELECT max(date) FROM stock_bar1d").fetchone()[0])[:10]
        # 需要的原始列：价格/量/换手（stock_bar1d）+ 市值（stock_valuation）+ 行业（component）
        bars = con.execute(f"""
            SELECT date, instrument, open, close, volume, amount, turn, adjust_factor
            FROM stock_bar1d
            WHERE date BETWEEN TIMESTAMP '{p['start']}' AND TIMESTAMP '{end}'
              AND (instrument LIKE '%SH' OR instrument LIKE '%SZ')
        """).df()
        mc = con.execute(f"""
            SELECT date, instrument, total_market_cap
            FROM stock_valuation
            WHERE date BETWEEN TIMESTAMP '{p['start']}' AND TIMESTAMP '{end}'
        """).df()
        ind = con.execute(f"""
            SELECT date, instrument, industry_level1_name AS industry
            FROM stock_industry_component_daily
            WHERE industry='sw2021' AND date BETWEEN TIMESTAMP '{p['start']}' AND TIMESTAMP '{end}'
        """).df()
        att = con.execute(f"""
            SELECT date, instrument, st_status, suspended, list_days
            FROM stock_prefactors_attr
            WHERE date BETWEEN TIMESTAMP '{p['start']}' AND TIMESTAMP '{end}'
        """).df()
        bm = con.execute(f"""
            SELECT date, close FROM index_bar1d WHERE instrument='{BENCH[p['benchmark']]}'
              AND date BETWEEN TIMESTAMP '{p['start']}' AND TIMESTAMP '{end}' ORDER BY date
        """).df()
        pool = None
        if p["instruments"] != "全市场":
            pool = con.execute(f"""
                SELECT DISTINCT date, member_code AS instrument FROM index_component
                WHERE instrument='{POOLS[p['instruments']]}'
                  AND date BETWEEN TIMESTAMP '{p['start']}' AND TIMESTAMP '{end}'
            """).df()
        con.close()
        for d in (bars, mc, ind, att, bm, pool):
            if d is not None and len(d):
                d["date"] = pd.to_datetime(d["date"])
        self._bm = bm.set_index("date")["close"]
        return bars.sort_values(["instrument", "date"]).reset_index(drop=True), dict(mc=mc, ind=ind, att=att, pool=pool)

    # ───────── ② 因子：逐标的纯 Python（支持 cross_rank 截面型因子）─────────
    def _compute_factor(self):
        fn = self.factor_fn
        bars = self.bars
        if getattr(fn, "cross_rank", None):       # 截面型（pct_rank 组合）：先按日排名
            spec = fn.cross_rank
            wide = bars[["date", "instrument"]].copy()
            score = pd.Series(0.0, index=bars.index)
            for col, w in spec:
                score = score + w * bars.groupby("date")[col].rank(pct=True)
            wide["factor"] = score
            return wide
        jobs = [(name, b) for name, b in bars.groupby("instrument", sort=False)]
        if self.jobs > 1 and len(jobs) > 200:
            try:                       # fn 必须可 pickle（闭包/lambda 不行 → 退回串行）
                with ProcessPoolExecutor(max_workers=self.jobs) as ex:
                    parts = list(ex.map(_factor_worker, [(n, b, fn) for n, b in jobs], chunksize=64))
                return pd.concat(parts, ignore_index=True)
            except Exception as e:
                print(f"   （因子多进程不可用，退回串行：{type(e).__name__}）")
        parts = [_factor_worker((n, b, fn)) for n, b in jobs]
        return pd.concat(parts, ignore_index=True)

    # ───────── ③ 预处理（纯 Python；--jobs 多进程）─────────
    def _preprocess(self):
        if not self.p["data_process"]:
            return self.raw_factor
        d = self.raw_factor.merge(self.univ["ind"], on=["date", "instrument"], how="left")
        d = d.merge(self.univ["mc"], on=["date", "instrument"], how="left")
        d = d[np.isfinite(d["factor"])]
        d["log_mcap"] = np.log(d["total_market_cap"].where(d["total_market_cap"] > 0))
        d = d.drop(columns=["total_market_cap"])
        cov = d["log_mcap"].notna().mean()
        print(f"   市值中性化覆盖率 {cov:.1%}" + ("  ⚠ 池=全市场时 stock_valuation 覆盖不足" if cov < 0.9 else "  ✓"))
        parts = [g for _, g in d.groupby("date", sort=True)]
        if self.jobs > 1 and len(parts) > 20:
            with ProcessPoolExecutor(max_workers=self.jobs) as ex:
                parts = list(ex.map(preprocess_frame, parts, chunksize=8))
        else:
            parts = [preprocess_frame(g) for g in parts]
        return pd.concat(parts, ignore_index=True)

    # ───────── ④ 未来收益：t 日因子 → t+1 开盘买 / t+2 开盘卖（纯 Python lead）─────────
    def _forward_return(self):
        b = self.bars[["date", "instrument", "open"]].copy()
        g = b.groupby("instrument", sort=False)["open"]
        b["o1"] = g.shift(-1)
        b["o2"] = g.shift(-2)
        b["daily_ret"] = b["o2"] / b["o1"] - 1
        return b[["date", "instrument", "daily_ret"]].dropna()

    # ───────── ⑤ 逐日截面分组（纯 Python qcut）─────────
    def _group(self):
        d = self.factor.merge(self.ret, on=["date", "instrument"], how="inner")
        d = d[np.isfinite(d["factor"])].dropna(subset=["daily_ret"])
        d = d.merge(self.univ["att"], on=["date", "instrument"], how="left")     # 过滤字段
        d = d.merge(self.bars[["date", "instrument", "amount"]], on=["date", "instrument"], how="left")
        if self.univ["pool"] is not None:
            d = d.merge(self.univ["pool"].assign(_in=1), on=["date", "instrument"], how="inner")
        n0 = len(d)
        d = d[(d["amount"] > 0)
              & (d["st_status"].fillna(0) == 0)
              & (d["suspended"].fillna(0) == 0)
              & (d["list_days"].fillna(9999) > 252)]
        print(f"   池过滤：{n0:,} → {len(d):,} 行（池={self.p['instruments']}，剔停牌/ST/上市<252天/无成交）")
        gn = self.p["group_num"]

        def cut(g):
            if len(g) < gn * 5 * 2:
                return g.iloc[0:0]
            g = g.copy()
            g["group"] = pd.qcut(g["factor"], q=gn, labels=False, duplicates="drop").astype(int).astype(str)
            return g.dropna(subset=["group"])
        res = d.groupby("date", group_keys=False).apply(cut, include_groups=False)
        res = res.copy()
        res["date"] = d.loc[res.index, "date"]
        return res

    # ───────── ⑥ 分组收益 / 多空 / 基准 / 累计 ─────────
    def _group_returns(self):
        g = self.grp.groupby(["date", "group"])["daily_ret"].mean().unstack("group")
        g.columns = [str(c) for c in g.columns]
        top, bot = str(self.p["group_num"] - 1), "0"
        g["ls"] = g[top] - g[bot]
        bm = (self._bm / self._bm.shift(1) - 1).rename("bm")
        g["bm"] = bm.reindex(g.index)
        return g, g.cumsum()

    # ───────── ⑦ IC（Rank IC = Spearman，逐日截面）─────────
    def _ic_series(self) -> pd.Series:
        gr = self.grp
        ic = gr.groupby("date").apply(
            lambda x: x["daily_ret"].corr(x["factor"], method="spearman") if len(x) > 10 else np.nan,
            include_groups=False).dropna()
        return ic

    # ───────── ⑧ 绩效（平台同口径）─────────
    @staticmethod
    def _perf(s: pd.Series, bm: pd.Series) -> dict:
        s = s.fillna(0); n = len(s); bmv = bm.reindex(s.index).fillna(0)
        sd = s.std()
        return {
            "区间收益": s.sum(), "年化收益": s.sum() * 242 / n,
            "超额收益": (s - bmv).sum(), "年化超额": (s - bmv).sum() * 242 / n,
            "Sharpe": (s.mean() - 0.035 / 242) / sd * np.sqrt(242) if sd else np.nan,
            "波动率": sd * np.sqrt(242), "IR(日频)": s.mean() / sd if sd else np.nan,
            "最大回撤": ((1 + s).cumprod() / (1 + s).cumprod().cummax() - 1).min(),
            "胜率": (s > 0).mean(), "交易日数": n,
        }

    def summary(self) -> pd.DataFrame:
        top, bot = str(self.p["group_num"] - 1), "0"
        rows = []
        for name, col in [("多头(因子最大组)", top), ("空头(因子最小组)", bot), ("多空(高-低)", "ls")]:
            r = self._perf(self.group_ret[col], self.group_ret["bm"]); r["portfolio"] = name
            rows.append(r)
        df = pd.DataFrame(rows).set_index("portfolio")
        df["IC"] = np.nan; df["IR"] = np.nan
        df.loc["多头(因子最大组)", ["IC", "IR"]] = [self.ic.mean(), self.ic.mean() / self.ic.std()]
        df["|IC|≥0.02 占比"] = np.nan
        df.loc["多头(因子最大组)", "|IC|≥0.02 占比"] = (self.ic.abs() >= 0.02).mean()
        return df.round(4)

    def _yearly_perf(self) -> pd.DataFrame:
        top = str(self.p["group_num"] - 1)
        rows = []
        for y, g in self.group_ret.groupby(self.group_ret.index.year):
            r = self._perf(g[top], g["bm"]); r["year"] = str(y); rows.append(r)
        return pd.DataFrame(rows).set_index("year")

    # ───────── ⑨ 图表（plotly 本地；对齐云端 render 的 7 张）─────────
    def render(self, out_html: str | None = None, local_plot: bool = False):
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        title = (f"因子分析 — {self.p['alpha_name_chinese']}（{self.p['alpha_name']}）"
                 f" | 池={self.p['instruments']} | 基准={self.p['benchmark']} | {self.p['group_num']} 组")
        top = str(self.p["group_num"] - 1)

        # 1) 分组累计收益 + IC 曲线 + IC 累计
        fig1 = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45],
                             subplot_titles=("分组累计收益（简单加总，同平台）", "IC 曲线（日 IC / 22 日均值 / 累计）"))
        for c in [x for x in self.group_cum.columns if x != "bm"]:
            fig1.add_trace(go.Scatter(x=self.group_cum.index, y=self.group_cum[c], name=f"G{c}",
                                      line=dict(width=1)), row=1, col=1)
        fig1.add_trace(go.Scatter(x=self.group_cum.index, y=self.group_cum["bm"], name="基准",
                                  line=dict(dash="dot", color="gray")), row=1, col=1)
        ic = self.ic
        fig1.add_trace(go.Bar(x=ic.index, y=ic.values, name="日 IC", marker_color="#95a5a6", opacity=.5),
                       row=2, col=1)
        fig1.add_trace(go.Scatter(x=ic.index, y=ic.rolling(22).mean(), name="IC 22 日均值",
                                  line=dict(color="#2980b9", width=1.4)), row=2, col=1)
        fig1.add_trace(go.Scatter(x=ic.index, y=ic.cumsum(), name="IC 累计",
                                  line=dict(color="#e67e22", width=1.4), yaxis="y3"), row=2, col=1)
        fig1.update_layout(template="plotly_white", height=760, hovermode="x unified",
                           margin=dict(l=60, r=60, t=60, b=40),
                           yaxis3=dict(overlaying="y2", side="right", showgrid=False, title="IC 累计"))

        # 2) 整体绩效 / 年度绩效（表）
        s = self.summary().reset_index()
        fig2 = go.Figure(go.Table(
            header=dict(values=list(s.columns), fill_color="#f3f5f8", align="left"),
            cells=dict(values=[s[c] for c in s.columns], align="left", height=26)))
        fig2.update_layout(title="整体绩效（多头 / 空头 / 多空）", height=200 + 28 * len(s))

        y = self.yearly.reset_index()
        fig3 = go.Figure(go.Table(
            header=dict(values=list(y.columns), fill_color="#f3f5f8", align="left"),
            cells=dict(values=[y[c].round(4) if y[c].dtype.kind == "f" else y[c] for c in y.columns],
                       align="left", height=26)))
        fig3.update_layout(title="年度绩效（多头组合）", height=200 + 28 * len(y))

        # 3) 因子值最大/最小的 5 只（最后一天）
        last = self.factor["date"].max()
        topdf = self.factor[self.factor["date"] == last].sort_values("factor", ascending=False)
        def _tbl(d, t):
            d = d.copy(); d["date"] = d["date"].dt.strftime("%Y-%m-%d")
            d = d[["date", "instrument", "factor"]].round(4)
            f = go.Figure(go.Table(header=dict(values=list(d.columns), fill_color="#f3f5f8", align="left"),
                                   cells=dict(values=[d[c] for c in d.columns], align="left", height=24)))
            f.update_layout(title=f"{t}（{last.date()}）", height=190)
            return f
        fig4 = _tbl(topdf.head(5), "因子值最大的 5 只")
        fig5 = _tbl(topdf.tail(5), "因子值最小的 5 只")

        figs = [("整体绩效", fig2), ("年度绩效", fig3), ("净值与 IC", fig1),
                ("头部 5 只", fig4), ("尾部 5 只", fig5)]
        p = Path(out_html or (REPO / "scripts" / f"factor_report_{self.p['alpha_name']}.html"))
        parts = [f"<h2>{title}</h2>"]
        for name, f in figs:
            parts.append(f"<h3>{name}</h3>" + f.to_html(full_html=False, include_plotlyjs="cdn"))
        p.write_text('<html><head><meta charset="utf-8"></head>'
                     '<body style="font-family:Arial,\'Microsoft YaHei\',sans-serif;margin:24px">'
                     + "".join(parts) + "</body></html>", encoding="utf-8")
        print(f"\n图表已写 {p}（{len(figs)} 张）")
        if local_plot:
            try:
                from IPython.display import display
                for _, f in figs:
                    display(f)
            except Exception:
                pass
        return str(p)


# ══════════════════════════ CLI ══════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--factor", default="turn_60", help=f"内置因子 {list(FACTOR_LIB)}")
    ap.add_argument("--pool", default=PARAMS["instruments"], choices=list(POOLS) + ["全市场"])
    ap.add_argument("--benchmark", default=PARAMS["benchmark"], choices=list(BENCH))
    ap.add_argument("--group-num", type=int, default=10)
    ap.add_argument("--start", default=PARAMS["start"])
    ap.add_argument("--no-process", action="store_true", help="关闭预处理（不对齐平台 data_process=True）")
    ap.add_argument("--jobs", type=int, default=1, help="预处理多进程数")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    m = AlphaMiner({"alpha_name": a.factor, "instruments": a.pool, "benchmark": a.benchmark,
                    "group_num": a.group_num, "start": a.start, "data_process": not a.no_process},
                   jobs=a.jobs)
    print("\n" + "=" * 78)
    print(f"IC 均值 {m.ic.mean():+.4f} | ICIR {m.ic.mean()/m.ic.std():+.3f} | "
          f"|IC|≥0.02 占比 {(m.ic.abs()>=0.02).mean():.1%} | IC 日数 {len(m.ic)}")
    print("=" * 78)
    print(m.summary().to_string())
    m.render(out_html=a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
