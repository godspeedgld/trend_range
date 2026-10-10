"""本地因子检验 —— 对齐 BigQuant `AlphaMiner` 口径（dai/bigcharts → duckdb/numpy）。

对标文件：平台版 `AlphaMiner(params)`（读 `alpha_test` 配置字典）。
本地的三处替换：
  dai.query(sql, filters)      → duckdb.connect(WAREHOUSE).execute(sql)   [同一仓库，SQL 语法基本兼容]
  c_clip/c_normalize/c_neutralize 截面算子 → 本地 SQL + numpy 实现（见 preprocess()）
  bigcharts/empyrical          → plotly（图表）/ 本地 _perf()（指标）

════════════════════════════════════════════════════════════════════════
【口径对齐表】（平台 → 本地）

项              平台                                    本地
取数表          cn_stock_prefactors / cn_stock_factors_base   v_prefactors + stock_valuation + stock_industry_component_daily + stock_prefactors_attr
池标志          is_hs300/is_zz500/is_zz1000 = 1         index_component 逐日成分
去极值          clip(f, c_avg-3*c_std, c_avg+3*c_std)   daily_preprocess() 同式（截面，按日）
标准化          c_normalize(f) = (f-μ)/σ               同式
中性化          c_neutralize(f, sector, log(mcap))     逐日 OLS: f ~ 行业哑变量 + log(市值) 取残差
未来收益        m_lead(open,2)/m_lead(open,1)-1        同式（lead 窗口函数）—— t 日因子 → t+1 开盘买、t+2 开盘卖
年化            sum()*242/天数                          同式（线性，非复利）
Sharpe          empyrical.sharpe_ratio(s, 0.035/242)   同式（自实现）
IC              Spearman(daily_ret, factor)             同式
IR              IC均值/IC标准差（日频）                 同式

★ 本地已知缺口（务必在读结果时扣减）：
  1) stock_valuation 仅 3,475 只（中证300/500/1000 并集 100%，全市场约 61%）
     → 池=全市场 时市值中性化覆盖不足；池=中证500/1000 时 100% 覆盖 【推荐】
  2) stock_industry_component_daily(sw2021) 5,033 只，缺 773 只 → 缺的记「未知」行业
  3) 平台 cn_stock_factors_base.trading_days 本地无 → 用 stock_prefactors_attr.list_days 代替
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

# ── 默认配置（结构与平台版 alpha_test 一致）─────────────────────────────
PARAMS = {
    "alpha_class": "test",                       # 平台内部归类（本地不用）
    "alpha_name": "turn_60",                     # 因子英文名（输出用）
    "alpha_name_chinese": "60日换手率均值",        # 因子中文名（报告用）
    "alpha_desc": "个股 60 个交易日换手率均值",
    # ★ 只写【因子表达式】——外层 SELECT date, instrument, ... FROM ... 由本模块生成
    "alpha_factor_sql": (
        "avg(turn) OVER (PARTITION BY instrument ORDER BY date "
        "ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)"
    ),
    "group_num": 10,                             # 分组数
    "instruments": "中证500",                     # 全市场 / 中证500 / 中证1000 / 沪深300
    "benchmark": "中证500",                       # 基准
    "data_process": True,                        # 是否做 去极值→标准化→中性化
    "start": "2019-01-01",                       # 本地分钟/日线仓库起点决定（平台硬编码 2018-04-25）
    "end": None,                                 # None = 库内最新
}

POOLS = {"沪深300": "000300.SH", "中证500": "000905.SH", "中证1000": "000852.SH"}
BENCH = {"沪深300": "000300.SH", "中证500": "000905.SH", "中证1000": "000852.SH"}


class AlphaMiner:
    """本地版因子检验。用法：m = AlphaMiner(PARAMS); m.report()"""

    def __init__(self, params: dict | None = None):
        self.p = {**PARAMS, **(params or {})}
        t0 = time.time()
        self.factor = self._get_factor()                       # ① 因子面板（含池过滤）
        print(f"① 因子面板 {len(self.factor):,} 行 / {self.factor['instrument'].nunique():,} 只 "
              f"/ {self.factor['date'].min()}~{self.factor['date'].max()} "
              f"({time.time()-t0:.0f}s)")
        if self.p["data_process"]:
            self.factor = self.preprocess(self.factor)          # ② 去极值→标准化→中性化
            print("② 预处理完成（外置 mean±3σ clip + z-score → c_neutralize[MAD 去极值 + z-score + 行业/市值 OLS 残差]）")
        self.ret = self._get_forward_return()                   # ③ 个股未来收益
        self.grp = self._group()                                # ④ 逐日截面分组
        print(f"③ 分组完成：{self.grp['date'].nunique()} 个交易日 × {self.p['group_num']} 组")
        self.group_ret, self.group_cum = self._group_returns()  # ⑤ 分组收益
        self.ic = self._ic_series()                             # ⑥ IC 序列
        print(f"④ 指标计算完成（{time.time()-t0:.0f}s）")

    # ─────────────────────── ① 取因子（含池过滤）───────────────────────
    def _get_factor(self) -> pd.DataFrame:
        p = self.p
        con = duckdb.connect(str(WAREHOUSE), read_only=True)
        end = p["end"] or str(con.execute("SELECT max(date) FROM stock_bar1d").fetchone()[0])[:10]
        pool_sql = "1=1" if p["instruments"] == "全市场" else f"""
            EXISTS (SELECT 1 FROM index_component ic
                    WHERE ic.instrument='{POOLS[p["instruments"]]}'
                      AND ic.member_code=b.instrument AND ic.date=b.date)"""
        sql = f"""
        WITH f AS (
          SELECT date, instrument, ({p['alpha_factor_sql']}) AS factor
          FROM v_prefactors WHERE date BETWEEN TIMESTAMP '{p['start']}' AND TIMESTAMP '{end}'
        )
        SELECT f.date, f.instrument, f.factor
        FROM f JOIN stock_bar1d b USING (date, instrument)
        LEFT JOIN stock_prefactors_attr a USING (date, instrument)
        WHERE 1=1
          AND {pool_sql}                          -- 股票池
          AND b.amount > 0                        -- 有成交
          AND COALESCE(a.st_status, 0) = 0        -- 非 ST
          AND COALESCE(a.list_days, 9999) > 252   -- 上市满 252 天
          AND (f.instrument LIKE '%SH' OR f.instrument LIKE '%SZ')   -- 剔北交所
          AND f.factor IS NOT NULL
          AND isfinite(f.factor)
        ORDER BY f.date, f.instrument"""
        df = con.execute(sql).df()
        con.close()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df

    # ─────────────── ② 预处理：去极值 → 标准化 → 中性化 ────────────────
    def preprocess(self, df: pd.DataFrame, outer: bool = True) -> pd.DataFrame:
        """逐日截面预处理 —— 严格按官方 `c_neutralize` 算法实现。

        官方源码（`.claude/skills/.../references/bigquant/bq_dai_sql_fqa.md` §行业市值中性化）：
            def process_factor(factor):
                median = np.median(factor); mad = np.median(abs(factor-median)) * 3*1.4826
                clipped = factor.clip(median-mad, median+mad)      # MAD 去极值
                return (clipped - clipped.mean()) / clipped.std(ddof=1)
            X = get_dummies(industry_level1_code); X['log_marketcap']=log(total_market_cap)
            X = sm.add_constant(X);  resid = OLS(process_factor(y), X).resid

        ★ outer=True 复刻平台 AlphaMiner SQL 的**外层两步**（mean±3σ clip → z-score）。
          注意：c_neutralize 内部会重做一遍 MAD clip+z-score，**外层这两步对最终残差几乎无影响**
          （OLS 残差对 y 的仿射变换不变，仅 MAD 截断是非线性、有微小作用）→ 可用 outer=False 对比。
        ★ 实现差异（本地）：行业缺失填「未知」；市值缺失（stock_valuation 全市场仅 ~61%）该股当日
          不进回归、残差记 NaN —— 平台是全量（cn_stock_factors_base 自带 total_market_cap）。
        """
        con = duckdb.connect(str(WAREHOUSE), read_only=True)
        dates = sorted(df["date"].unique())
        din = ",".join(f"TIMESTAMP '{d}'" for d in dates)
        mcap = con.execute(f"""SELECT strftime(date,'%Y-%m-%d') d, instrument, total_market_cap mcap
            FROM stock_valuation WHERE date IN ({din})""").df()
        ind = con.execute(f"""SELECT strftime(date,'%Y-%m-%d') d, instrument, industry_level1_name ind
            FROM stock_industry_component_daily WHERE date IN ({din}) AND industry='sw2021'""").df()
        con.close()
        mc_i = mcap.set_index(["d", "instrument"])["mcap"]
        ind_i = ind.set_index(["d", "instrument"])["ind"]

        def process_factor(v: np.ndarray) -> np.ndarray:
            """官方 process_factor：MAD 去极值 → z-score(ddof=1)。"""
            med = np.nanmedian(v)
            mad = np.nanmedian(np.abs(v - med)) * 3 * 1.4826
            v = np.clip(v, med - mad, med + mad)
            return (v - np.nanmean(v)) / np.nanstd(v, ddof=1)

        out = []
        for d, g in df.groupby("date", sort=True):
            g = g.copy()
            v = g["factor"].values.astype(float)
            # 外层（平台 SQL 明文，可关）
            if outer:
                mu, sd = np.nanmean(v), np.nanstd(v, ddof=1)
                v = np.clip(v, mu - 3 * sd, mu + 3 * sd)
                v = (v - np.nanmean(v)) / np.nanstd(v, ddof=1)
            # 中性化（c_neutralize：内部先 process_factor(y)，再对 X 回归取残差）
            key = pd.MultiIndex.from_arrays([[d] * len(g), g["instrument"].values])
            mcap_v = mc_i.reindex(key).values.astype(float)
            ind_v = pd.Series(ind_i.reindex(key).values, index=g.index).fillna("未知")
            ok = np.isfinite(v) & np.isfinite(mcap_v)
            if ok.sum() > 30:
                y = process_factor(v[ok])                      # ★ 官方内部预处理
                X = pd.get_dummies(pd.DataFrame({"mcap": np.log(mcap_v[ok]),
                                                 "ind": ind_v[ok].values}),
                                   columns=["ind"], drop_first=True).astype(float)
                X.insert(0, "const", 1.0)                      # sm.add_constant
                beta, *_ = np.linalg.lstsq(X.values, y, rcond=None)   # method='pinv'
                resid = np.full(len(g), np.nan)
                resid[ok] = y - X.values @ beta
                v = resid
            g["factor"] = v
            g["mcap_used"] = np.isfinite(mcap_v)
            out.append(g)
        res = pd.concat(out, ignore_index=True)
        cov = res.groupby("date")["mcap_used"].mean().mean()
        print(f"   市值中性化覆盖率 {cov:.1%}"
              + ("  ⚠ 不足——池=全市场时 stock_valuation 仅覆盖约 61%" if cov < 0.9 else "  ✓"))
        return res.drop(columns=["mcap_used"])

    # ─────────────── ③ 个股未来收益（平台同式，防前视）────────────────
    def _get_forward_return(self) -> pd.DataFrame:
        con = duckdb.connect(str(WAREHOUSE), read_only=True)
        d0 = self.factor["date"].min(); d1 = self.factor["date"].max()
        df = con.execute(f"""
            WITH b AS (
              SELECT date, instrument, open,
                     lead(open, 1) OVER w AS o1,
                     lead(open, 2) OVER w AS o2
              FROM stock_bar1d
              WHERE date BETWEEN TIMESTAMP '{d0}'::TIMESTAMP - INTERVAL 10 DAY AND TIMESTAMP '{d1}'::TIMESTAMP + INTERVAL 10 DAY
              WINDOW w AS (PARTITION BY instrument ORDER BY date)
            )
            SELECT strftime(date,'%Y-%m-%d') AS date, instrument, (o2 / o1 - 1) AS daily_ret
            FROM b WHERE o1 IS NOT NULL AND o2 IS NOT NULL
        """).df()
        con.close()
        return df

    # ─────────────── ④ 逐日截面分组 ────────────────────────────────
    def _group(self) -> pd.DataFrame:
        d = self.factor.merge(self.ret, on=["date", "instrument"], how="left")
        d = d[np.isfinite(d["factor"])]

        def cut(g):
            # ★ 平台版有 drop_duplicates('factor')（会丢掉因子值相同的标的）——本地按标的去重，更正确
            g = g.dropna(subset=["factor", "daily_ret"])
            if len(g) < self.p["group_num"] * 5:
                return g.iloc[0:0]
            g = g.copy()
            g["group"] = pd.qcut(g["factor"], q=self.p["group_num"], labels=False,
                                 duplicates="drop").astype(int).astype(str)   # 统一成字符串
            return g.dropna(subset=["group"])
        # ★ include_groups=False 会丢掉分组列 date → 按原索引补回
        res = d.groupby("date", group_keys=False).apply(cut, include_groups=False)
        res["date"] = d.loc[res.index, "date"]
        return res

    # ─────────────── ⑤ 分组收益 / 多空 / 基准 ──────────────────────────
    def _group_returns(self):
        bn = BENCH[self.p["benchmark"]]
        con = duckdb.connect(str(WAREHOUSE), read_only=True)
        bm = con.execute(f"""SELECT strftime(date,'%Y-%m-%d') d,
                close/lag(close) OVER (ORDER BY date) - 1 AS bm_ret
            FROM index_bar1d WHERE instrument='{bn}'
              AND date BETWEEN TIMESTAMP '{self.factor['date'].min()}' AND TIMESTAMP '{self.factor['date'].max()}'
            ORDER BY date""").df().set_index("d")["bm_ret"]
        con.close()
        g = self.grp.groupby(["date", "group"])["daily_ret"].mean().unstack("group")
        g.columns = [str(c) for c in g.columns]
        top, bot = str(self.p["group_num"] - 1), "0"
        g["ls"] = g[top] - g[bot]            # 多空 = 最大因子组 − 最小因子组
        g["bm"] = bm.reindex(g.index)
        return g, g.cumsum()                  # 平台同款：简单加总累计

    # ─────────────── ⑥ IC（Rank IC，Spearman）────────────────────────
    def _ic_series(self) -> pd.Series:
        gr = self.grp.dropna(subset=["factor", "daily_ret"])
        ic = gr.groupby("date").apply(
            lambda x: x["daily_ret"].corr(x["factor"], method="spearman")
            if len(x) > 10 else np.nan, include_groups=False).dropna()
        return ic

    # ─────────────── ⑦ 指标（平台同口径）───────────────────────────
    def _perf(self, s: pd.Series, bm: pd.Series) -> dict:
        s = s.fillna(0); n = len(s)
        vol = s.std() * np.sqrt(242)
        return {
            "区间收益": s.sum(),
            "年化收益": s.sum() * 242 / n,
            "超额收益": (s - bm.reindex(s.index).fillna(0)).sum(),
            "年化超额": (s - bm.reindex(s.index).fillna(0)).sum() * 242 / n,
            "Sharpe": (s.mean() - 0.035 / 242) / s.std() * np.sqrt(242) if s.std() else np.nan,
            "波动率": vol,
            "IR(日频)": s.mean() / s.std() if s.std() else np.nan,
            "最大回撤": ((1 + s).cumprod() / (1 + s).cumprod().cummax() - 1).min(),
            "胜率": (s > 0).mean(),
            "交易日数": n,
        }

    def summary(self) -> pd.DataFrame:
        top, bot = str(self.p["group_num"] - 1), "0"
        rows = []
        for name, col in [("多头(因子最大组)", top), ("空头(因子最小组)", bot), ("多空", "ls")]:
            r = self._perf(self.group_ret[col], self.group_ret["bm"])
            r["portfolio"] = name
            rows.append(r)
        df = pd.DataFrame(rows).set_index("portfolio")
        ic = self.ic
        df["IC(全截面)"] = np.nan
        df["ICIR(全截面)"] = np.nan
        df.loc["多头(因子最大组)", ["IC(全截面)", "ICIR(全截面)"]] = [ic.mean(), ic.mean() / ic.std()]
        # ★ 平台版特有：分组合内 IC（get_ic 的 long/short/long_short 三种）
        gr = self.grp.dropna(subset=["factor", "daily_ret"])
        top, bot = str(self.p["group_num"] - 1), "0"
        def _ic_of(sub):
            if len(sub) == 0:
                return (np.nan, np.nan)
            s = sub.groupby("date").apply(
                lambda x: x["daily_ret"].corr(x["factor"], method="spearman") if len(x) > 5 else np.nan,
                include_groups=False)
            s = pd.Series(np.asarray(s, dtype=float).ravel(),
                          index=s.index if s.ndim == 1 else None).dropna()
            if len(s) < 2:
                return (np.nan, np.nan)
            return (float(s.mean()), float(s.mean() / s.std()))
        for label, sub in [("多头(因子最大组)", gr[gr["group"] == top]),
                           ("空头(因子最小组)", gr[gr["group"] == bot]),
                           ("多空", gr[gr["group"].isin([top, bot])])]:
            m, r = _ic_of(sub)
            df.loc[label, ["IC(组内)", "ICIR(组内)"]] = [m, r]
        return df.round(4)

    def report(self, out_html: str | None = None):
        df = self.summary()
        print(f"\n{'='*78}\n因子：{self.p['alpha_name_chinese']}（{self.p['alpha_name']}）"
              f" | 池={self.p['instruments']} | 基准={self.p['benchmark']}"
              f" | 分组={self.p['group_num']} | 预处理={'开' if self.p['data_process'] else '关'}")
        print(f"IC 均值 {self.ic.mean():+.4f} | ICIR {self.ic.mean()/self.ic.std():+.3f} "
              f"| |IC|≥0.02 占比 {(self.ic.abs()>=0.02).mean():.1%} | IC 日数 {len(self.ic)}")
        print("="*78)
        print(df.to_string())
        if out_html:
            try:
                import plotly.graph_objects as go
                fig = go.Figure()
                for c in [x for x in self.group_cum.columns if x not in ("bm",)]:
                    fig.add_scatter(x=self.group_cum.index, y=self.group_cum[c], name=f"G{c}")
                fig.add_scatter(x=self.group_cum.index, y=self.group_cum["bm"], name="基准",
                                line=dict(dash="dot", color="gray"))
                fig.write_html(out_html)
                print(f"\n图表已写 {out_html}")
            except Exception as e:
                print(f"（图表跳过：{e}）")
        return df


if __name__ == "__main__":
    AlphaMiner(PARAMS).report()
