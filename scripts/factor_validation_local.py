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

════════════════════════ 用法（★ 本库不含具体因子，换因子只改调用方的配置）════════════════════════
  推荐：写一个 driver 脚本（对标云端 notebook 的 cell[0] + 实例化 + render）：

      from factor_validation_local import run
      alpha_test = {
          "alpha_name": "turn_ratio",
          "alpha_name_chinese": "5日/60日换手率比",
          "alpha_py": "turn.rolling(5).mean() / (turn.rolling(60).mean() + 1e-8)",
          "group_num": 10, "instruments": "全市场", "benchmark": "中证500",
          "data_process": True, "start": "2017-05-01",
      }
      run(alpha_test, jobs=6, out_html="out.html")     # ← 一行

  命令行：python scripts/factor_validation_local.py --alpha-py '<表达式>' --pool 全市场 --out out.html

  ⚠ `jobs>1` 用多进程（Windows 是 spawn）：**driver 必须有 `if __name__ == "__main__":` 守卫**，
    且**不能**用 `python - <<'PY'`（stdin）/ 交互式跑 —— 子进程会去 import `<stdin>` 当 __main__ 而崩。
    真崩了会自动兜底串行（打印提示），结果不受影响。
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
    "alpha_name": "my_factor",       # 因子英文名（输出/文件名用）
    "alpha_name_chinese": "我的因子",
    "alpha_desc": "",
    # ★ 必填：Python 表达式（**对标云端的 alpha_sql**），在单标的 bars 上求值
    "alpha_py": None,
    "group_num": 10,             # 分几组（默认 10）
    "instruments": "中证500",     # 全市场 / 中证500 / 中证1000 / 沪深300
    "benchmark": "中证500",
    "data_process": True,        # 去极值→标准化→中性化
    "start": "2019-01-01",
    "end": None,                 # None = 库内最新
    # ★ 附加功能（2026-10-13）：分析频率。"daily"（默认，= 云端 AlphaMiner 行为，**完全不变**）
    #   | "weekly" = 先把 bars 重采样到「每周最后一个交易日」再走**同一条流水线**
    #     （用于检验 strategy_001 基线里那种**周频窗口**因子，如 5周/60周换手比）
    "freq": "daily",
}


# ═══════════════ 因子定义：Python 表达式（对标云端的 alpha_sql 字符串）═══════════════
class AlphaPyFactor:
    """把 **Python 表达式字符串**编译成可调用因子 —— 与云端 `alpha_sql` 同构：
    表达式在**单只标的的 bars** 上求值，可直接引用列名（turn / close / open / high / low /
    volume / amount / pre_close / adjust_factor）与 `np` / `pd`。

    例：
      "turn.rolling(5).mean() / (turn.rolling(60).mean() + 1e-8)"   # 换手比（日频口径）
      "close.pct_change(20)"                                        # 20 日动量
      "-(close / close.rolling(20).mean() - 1)"                     # 超买回归（取负）

    ★ 用**类实例**（可 pickle）→ 因子计算能进多进程。
    ★ **本库不含任何具体因子** —— 换因子只改**调用方的 alpha_test 配置**，不改本文件。
    """

    def __init__(self, expr: str):
        self.expr = expr.strip()
        self.code = compile(self.expr, "<alpha_py>", "eval")

    def __call__(self, bars: pd.DataFrame) -> pd.Series:
        env = {c: bars[c] for c in bars.columns}
        env["np"], env["pd"] = np, pd
        v = eval(self.code, {"__builtins__": {}}, env)
        return pd.Series(np.asarray(v, dtype=float), index=bars.index)

    def __repr__(self):
        return f"alpha_py({self.expr[:48]}…)"

    # ★ compiled code object 不可 pickle → 序列化时只带表达式，反序列化时重编译（否则多进程必 TypeError）
    def __getstate__(self):
        return {"expr": self.expr}

    def __setstate__(self, st):
        self.expr = st["expr"]
        self.code = compile(self.expr, "<alpha_py>", "eval")


def _factor_worker(args):
    """多进程 worker：算一只标的的因子。"""
    name, sub, fn = args
    return pd.DataFrame({"date": sub["date"].values, "instrument": name,
                         "factor": np.asarray(fn(sub), dtype=float)})


# ══════════════════════════ 平台函数的 Python 实现 ══════════════════════════
def clip_3sigma(v: np.ndarray) -> np.ndarray:
    """平台 `clip(f, c_avg(f)-3*c_std(f), c_avg(f)+3*c_std(f))`（逐日截面，ddof=1）。"""
    with np.errstate(invalid="ignore", divide="ignore"):
        mu, sd = np.nanmean(v), np.nanstd(v, ddof=1)
        return np.clip(v, mu - 3 * sd, mu + 3 * sd)      # sd=0 时全体变 mu —— 与平台 clip 同


def c_normalize(v: np.ndarray) -> np.ndarray:
    """平台 `c_normalize(f) = (f-μ)/σ`（逐日截面，ddof=1）。★ 无 sd==0 守卫（平台没有）。"""
    with np.errstate(invalid="ignore", divide="ignore"):
        return (v - np.nanmean(v)) / np.nanstd(v, ddof=1)


def process_factor(v: np.ndarray) -> np.ndarray:
    """官方 c_neutralize 内部的 `process_factor`：MAD 去极值(median±3*1.4826*MAD) → z-score(ddof=1)。"""
    med = np.nanmedian(v)
    mad = np.nanmedian(np.abs(v - med)) * 3 * 1.4826
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.clip(v, med - mad, med + mad)
        return (v - np.nanmean(v)) / np.nanstd(v, ddof=1)


def c_neutralize(f: np.ndarray, ind: np.ndarray, log_mcap: np.ndarray) -> np.ndarray:
    """平台 `c_neutralize(f, sw2021_level1, LOG(total_market_cap))`：
    `process_factor(f)` 后对 [行业哑变量 + log市值 + 常数] 做 OLS（pinv），取残差。
    ★ **无最小样本量守卫**（官方源码没有；秩亏由 lstsq/pinv 自然处理）。"""
    y = process_factor(f)
    X = pd.get_dummies(pd.DataFrame({"mcap": np.asarray(log_mcap, dtype=float), "ind": ind}),
                       columns=["ind"], drop_first=True).astype(float)
    X.insert(0, "const", 1.0)
    try:
        beta, *_ = np.linalg.lstsq(X.values, y, rcond=None)      # 官方 fit(method='pinv')
        return y - X.values @ beta
    except Exception:
        return np.full_like(y, np.nan)     # 官方语义：y / X 含 NaN 时残差整体 NaN


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
        self.factor_fn = factor_fn or (AlphaPyFactor(self.p["alpha_py"]) if self.p.get("alpha_py") else None)
        if self.factor_fn is None:
            raise ValueError("必须给因子：params['alpha_py']（Python 表达式字符串）或 factor_fn（可调用）")
        self.jobs = max(1, int(jobs))
        t0 = time.time()

        # ① 读原始列（duckdb 只做「读」，不做计算）
        self.bars, self.univ = self._read_raw()
        print(f"① 原始数据 {len(self.bars):,} 行 / {self.bars['instrument'].nunique():,} 只 / "
              f"{self.bars['date'].min().date()}~{self.bars['date'].max().date()} ({time.time()-t0:.0f}s)")

        # ★ freq（**附加**开关；daily = 云端行为，一行不动）
        self.freq = self.p.get("freq", "daily")
        self.ANN = 242 if self.freq == "daily" else 52          # 线性年化：日 242（平台口径）/ 周 52
        self.ANN_EMP = 252 if self.freq == "daily" else 52      # empyrical 年化（云端用其默认 252）
        if self.freq == "weekly":
            self.bars = self._to_weekly(self.bars)
            wd = pd.DatetimeIndex(sorted(self.bars["date"].unique()))
            self._bm = self._bm.reindex(wd).dropna()      # 基准也重采样到同一批周频日 → 周收益
            print(f"   ★ freq=weekly：重采样到 {len(wd)} 个周频信号日（年化因子 {self.ANN}）")

        # ② 因子（纯 Python；逐标的滚动）
        self.raw_factor = self._compute_factor()
        print(f"② 因子计算完成（{getattr(self.factor_fn, '__name__', None) or repr(self.factor_fn)}）")

        # ③ 面板：**先按云端 SQL 的 WHERE 过滤**（顺序不能反 —— 截面算子必须作用在过滤后的行集上）
        self.panel = self._panel()
        print(f"③ 面板 {len(self.panel):,} 行（池={self.p['instruments']}）")

        # ④ 预处理：clip → normalize → neutralize（纯 Python；在③的行集上做，与云端 SQL 同序）
        self.factor = self._preprocess()
        print(f"④ 预处理完成（{'开' if self.p['data_process'] else '关'}；jobs={self.jobs}）")

        # ⑤ 未来收益（纯 Python shift/lead，云端同式）
        self.ret = self._forward_return()

        # ⑥ 分组（left merge + drop_duplicates('factor')，云端同式）
        self.grp = self._group()
        print(f"⑤ 分组完成：{self.grp['date'].nunique()} 个交易日 × {self.p['group_num']} 组")

        # ⑦ 分组收益（★ 整体 shift(1)）/ 累计 / 基准；IC
        self.group_ret, self.group_cum = self._group_returns()
        self.ic = self._ic_series()
        self.yearly = self._yearly_perf()
        print(f"⑥ 指标计算完成（总 {time.time()-t0:.0f}s）")

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

    # ─────── 附加：日线 → 周频（每周最后一个交易日）───────
    @staticmethod
    def _to_weekly(bars: pd.DataFrame) -> pd.DataFrame:
        """每个自然周取**最后一个交易日**那一行（与策略侧 `groupby(date.to_period('W')).last()` 同款）。
        ★ 只有 freq=weekly 才走这里；daily 路径不碰本函数。"""
        b = bars.copy()
        b["_w"] = b["date"].dt.to_period("W")
        b = (b.sort_values(["instrument", "_w", "date"])
              .drop_duplicates(["instrument", "_w"], keep="last"))
        return b.drop(columns=["_w"]).sort_values(["instrument", "date"]).reset_index(drop=True)

    # ───────── ② 因子：逐标的纯 Python（支持 cross_rank 截面型因子）─────────
    def _compute_factor(self):
        fn = self.factor_fn
        bars = self.bars
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

    # ───────── ③ 面板：拼原始列 + 施加云端 SQL 的 WHERE（**必须在预处理之前**）─────────
    def _panel(self) -> pd.DataFrame:
        """复刻云端 `data_alpha_origin` + `data_alpha_process` 的**行集**：
             QUALIFY COLUMNS(*) IS NOT NULL  ∧ factor 非 Inf
             ∧ {pool}  ∧ amount > 0 ∧ st_status = 0 ∧ trading_days > 252 ∧ (SH|SZ)
        ★ 云端**没有** `suspended` 这一条 —— 别自己加。
        ★ `trading_days` 本地用 `stock_prefactors_attr.list_days` 代替（平台字段本地无）。"""
        d = self.raw_factor.merge(self.univ["att"], on=["date", "instrument"], how="left")
        d = d.merge(self.univ["ind"], on=["date", "instrument"], how="left")
        d = d.merge(self.univ["mc"], on=["date", "instrument"], how="left")
        d = d.merge(self.bars[["date", "instrument", "amount"]], on=["date", "instrument"], how="left")
        if self.univ["pool"] is not None:
            d = d.merge(self.univ["pool"].drop_duplicates().assign(_in=1),
                        on=["date", "instrument"], how="inner")
        n0 = len(d)
        d = d[np.isfinite(d["factor"]) & (d["amount"] > 0)
              & (d["st_status"].fillna(0) == 0) & (d["list_days"].fillna(0) > 252)].copy()
        d["log_mcap"] = np.log(d["total_market_cap"].where(d["total_market_cap"] > 0))
        # QUALIFY COLUMNS(*) IS NOT NULL：市值/行业缺的行云端整行丢弃（中性化要用它们）
        n1 = len(d)
        d = d[d["log_mcap"].notna() & d["industry"].notna()].copy()
        print(f"   WHERE 过滤：{n0:,} → {n1:,}（池/amount/st/trading_days/SH-SZ）→ {len(d):,}"
              f"（再按云端 QUALIFY 剔「市值或行业缺失」的行）")
        return d.drop(columns=["total_market_cap"]).reset_index(drop=True)

    # ───────── ④ 预处理（纯 Python；--jobs 多进程；作用在③的行集上）─────────
    def _preprocess(self):
        if not self.p["data_process"]:
            return self.panel[["date", "instrument", "factor"]].copy()
        d = self.panel
        parts = [g for _, g in d.groupby("date", sort=True)]
        if self.jobs > 1 and len(parts) > 20:
            try:
                with ProcessPoolExecutor(max_workers=self.jobs) as ex:
                    parts = list(ex.map(preprocess_frame, parts, chunksize=8))
            except Exception as e:   # Windows spawn 需 __main__ 守卫；被 import/交互式调用时兜底串行
                print(f"   （预处理多进程不可用，退回串行：{type(e).__name__}）")
                parts = [preprocess_frame(g) for g in parts]
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

    # ───────── ⑤ 逐日截面分组（**逐字对齐云端 cut()**）─────────
    def _group(self):
        # 云端：merge_data = pd.merge(factor_data, daily_ret_data, on=[...], how='left')
        d = self.factor.merge(self.ret, on=["date", "instrument"], how="left")
        gn = self.p["group_num"]

        def cut(g):
            """云端 cut()：`drop_duplicates('factor')` → `qcut(duplicates='drop')` → 组号转 str。
            ★ **无最小样本量守卫**（本地曾自加 `len(g) >= gn*10`，已删——那是自创的）。"""
            g = g.drop_duplicates("factor").copy()
            g["group"] = pd.qcut(g["factor"], q=gn, labels=False, duplicates="drop")
            g = g.dropna(subset=["group"])
            g["group"] = g["group"].astype(int).astype(str)
            return g
        res = d.groupby("date", group_keys=False).apply(cut, include_groups=False)
        res = res.copy()
        res["date"] = d.loc[res.index, "date"]
        return res

    # ───────── ⑥ 分组收益 / 多空 / 基准 / 累计（含云端整体 shift(1)）─────────
    def _group_returns(self):
        g = self.grp.groupby(["date", "group"])["daily_ret"].mean().unstack("group")   # 云端用 np.nanmean
        g.columns = [str(c) for c in g.columns]
        top, bot = str(self.p["group_num"] - 1), "0"
        g["ls"] = g[top] - g[bot]
        bm = (self._bm / self._bm.shift(1) - 1).rename("bm")
        g["bm"] = bm.reindex(g.index)
        g = g.shift(1)          # ★★ 云端 get_group_cumret 对**整表 shift(1)** 后才 cumsum / 算绩效
        return g, g.cumsum()

    # ───────── ⑦ IC（Rank IC，逐日截面 Spearman；**无样本量守卫**）─────────
    def _ic_series(self) -> pd.Series:
        ic = self.grp.groupby("date").apply(
            lambda x: x["daily_ret"].corr(x["factor"], method="spearman"),
            include_groups=False).dropna()
        return ic

    # ───────── ⑧ 绩效（平台同口径）─────────
    # ───────── ⑧ 绩效：**字段名与口径逐列对齐云端 AlphaMiner** ─────────
    @staticmethod
    def _ic_stats(gr: pd.DataFrame) -> dict:
        """云端 get_ic：按日截面 Spearman IC → ic / ir + ic_3|10|21|63|126|252（尾部均值）。"""
        keys = ["ic", "ir"] + [f"ic_{k}" for k in (3, 10, 21, 63, 126, 252)]
        s = gr.groupby("date").apply(
            lambda x: x["daily_ret"].corr(x["factor"], method="spearman"),
            include_groups=False).dropna()
        if len(s) < 2:
            return {k: np.nan for k in keys}
        d = {"ic": s.mean(), "ir": s.mean() / s.std()}
        d.update({f"ic_{k}": s.tail(k).mean() for k in (3, 10, 21, 63, 126, 252)})
        return d

    @staticmethod
    def _turnover(gr: pd.DataFrame) -> float:
        """云端 get_turnover：1 − |今日∩昨日| / |今日|，逐日取均值。"""
        per_day = gr.groupby("date")["instrument"].apply(set).sort_index()
        prev = per_day.shift(1)
        # 云端 count_repeat：`if dfs.name > 0` ⇒ **首日按 0 次重复**算 → turnover = 1（不是 NaN）
        vals = [(1 - len(a & b) / len(a)) if isinstance(b, set) and len(a) else 1.0
                for a, b in zip(per_day, prev)]
        return float(np.nanmean(vals)) if len(vals) else np.nan

    def _perf(self, s: pd.Series, bm: pd.Series) -> dict:
        """云端 get_basic_perf：empyrical 算 sharpe/vol/mdd（**daily 原样：annualization=252、线性 242**），
        收益/超额用线性年化（非复利）。freq=weekly 时年化因子换成 **52**（附加分支，daily 不受影响）。"""
        ann, ann_emp = self.ANN, self.ANN_EMP
        s = s.fillna(0)
        bmv = bm.reindex(s.index).fillna(0)
        n = len(s)
        ex = s - bmv
        try:
            import empyrical as emp                        # 与云端同一实现，口径必然一致
            sharpe = (emp.sharpe_ratio(s, 0.035 / ann, annualization=ann_emp) if self.freq == "weekly"
                      else emp.sharpe_ratio(s, 0.035 / ann))                    # daily：云端的默认 252
            vol = (emp.annual_volatility(s, annualization=ann_emp) if self.freq == "weekly"
                   else emp.annual_volatility(s))
            mdd = emp.max_drawdown(s)
        except Exception:                                   # 兜底自实现（ddof=1）
            sd = s.std(ddof=1)
            sharpe = (s.mean() - 0.035 / ann) / sd * np.sqrt(ann_emp) if sd else np.nan
            vol = sd * np.sqrt(ann_emp)
            nav = (1 + s).cumprod(); mdd = (nav / nav.cummax() - 1).min()
        d = {"return_ratio": s.sum(), "annual_return_ratio": s.sum() * ann / n,
             "ex_return_ratio": ex.sum(), "ex_annual_return_ratio": ex.sum() * ann / n,
             "sharp_ratio": sharpe, "return_volatility": vol,
             "information_ratio": s.mean() / s.std() if s.std() else np.nan,
             "max_drawdown": mdd, "win_percent": (s > 0).mean(), "trading_days": n}
        d.update({f"ret_{k}": s.tail(k).sum() for k in (3, 10, 21, 63, 126, 252)})
        return d

    # 云端 render 里「整体绩效」显示的列（顺序一致）
    WHOLE_COLS = ["portfolio", "ic", "ir", "turnover", "return_ratio", "annual_return_ratio",
                  "ex_return_ratio", "ex_annual_return_ratio", "sharp_ratio", "return_volatility",
                  "information_ratio", "max_drawdown", "win_percent", "ic_252", "ret_252"]
    YEARLY_COLS = ["year", "ic", "return_ratio", "annual_return_ratio", "ex_return_ratio",
                   "ex_annual_return_ratio", "sharp_ratio", "return_volatility", "max_drawdown",
                   "win_percent", "trading_days"]

    def summary(self) -> pd.DataFrame:
        """整体绩效 —— 3 个组合 × 云端**全部字段**（含 ic / ir / turnover / ic_k / ret_k）。"""
        top, bot = str(self.p["group_num"] - 1), "0"
        gr = self.grp.dropna(subset=["factor", "daily_ret"])
        gl = gr[gr["group"] == top]
        gs = gr[gr["group"] == bot]
        rows = []
        for name, col, sel in [("long", top, gl), ("short", bot, gs),
                               ("long_short", "ls", gr[gr["group"].isin([top, bot])])]:
            d = {**self._ic_stats(sel), **self._perf(self.group_ret[col], self.group_ret["bm"])}
            # 云端：多空的 turnover = 多头 + 空头（各自算再相加）
            d["turnover"] = (self._turnover(gl) + self._turnover(gs)
                             if name == "long_short" else self._turnover(sel))
            d["portfolio"] = name
            rows.append(d)
        df = pd.DataFrame(rows).set_index("portfolio")
        return df[self.WHOLE_COLS[1:]].round(4)

    def _yearly_perf(self) -> pd.DataFrame:
        """年度绩效（多头组合）—— 云端同列（含年度 ic）。"""
        top = str(self.p["group_num"] - 1)
        gr = self.grp.dropna(subset=["factor", "daily_ret"])
        gl = gr[gr["group"] == top]
        rows = []
        for y, g in self.group_ret.groupby(self.group_ret.index.year):
            d = self._perf(g[top], g["bm"])
            sub = gl[gl["date"].dt.year == y]
            s = sub.groupby("date").apply(
                lambda x: x["daily_ret"].corr(x["factor"], method="spearman"),
                include_groups=False).dropna()
            d["ic"] = s.mean() if len(s) else np.nan
            d["year"] = str(y)
            rows.append(d)
        return pd.DataFrame(rows)[self.YEARLY_COLS].set_index("year").round(4)

    def ic_stats(self) -> pd.DataFrame:
        """云端 c4「IC 分析指标」：IC / |IC|>0.02 占比 / IR（基于**全部组**的日频 IC 序列）。"""
        ic = self.ic
        return pd.DataFrame({"IC": [round(float(ic.mean()), 4)],
                             "|IC|>0.02": [round(float((ic.abs() >= 0.02).mean()), 4)],
                             "IR": [round(float(ic.mean() / ic.std()), 4)]})

    # ───────── ⑨ 总结：分层效果 / 多空 / 年度稳定性（用户 2026-10-13 要求）─────────
    def conclude(self) -> pd.DataFrame:
        """★ 总结四项（每项给数值 + 判定）：
            ① 分层效果 —— 分组累计收益对「组号」的**单调性** ρ（|ρ|≥0.9 强单调）
            ② 多空组    —— 年化 / Sharpe / 回撤 / IR（|Sharpe|≥1 强）
            ③ 年度 Sharpe 稳定性 —— 逐年 Sharpe 的离散度 + 正向年占比（标准差<1 且正向≥70% 判"稳定"）
            ④ 收益波动率稳定性 —— 逐年波动率的变异系数 CV（<0.3 稳定）
           ★ ③④ 默认统计**多头组**（因子最大组）；分组数不足 2 年时自动退化。"""
        gn = self.p["group_num"]
        cols = [str(i) for i in range(gn) if str(i) in self.group_ret.columns]
        tot = self.group_ret[cols].sum()                       # 各组区间累计收益（简单加总，同平台）
        x = pd.Series(range(len(tot)), dtype=float)
        rho = float(x.rank().corr(tot.reset_index(drop=True).rank()))   # Pearson on ranks = Spearman

        ls = self._perf(self.group_ret["ls"], self.group_ret["bm"])
        top = str(gn - 1)

        def _yearly(col):
            rows = []
            for y, g in self.group_ret.groupby(self.group_ret.index.year):
                s = g[col].fillna(0); sd = s.std()
                rows.append({"year": y, "ret": s.sum(),
                             "sharpe": (s.mean() - .035 / self.ANN) / sd * np.sqrt(self.ANN_EMP) if sd else np.nan,
                             "vol": sd * np.sqrt(self.ANN_EMP)})
            return pd.DataFrame(rows).set_index("year")

        yt = _yearly(top)
        sh, vol = yt["sharpe"].dropna(), yt["vol"].dropna()
        sh_pos = (sh > 0).mean()
        cv = abs(vol.std() / vol.mean()) if len(vol) and vol.mean() else np.nan
        j_rho = "强单调" if abs(rho) >= .9 else ("中等" if abs(rho) >= .6 else "弱/无")
        j_sh = "强" if abs(ls["sharp_ratio"]) >= 1 else ("中" if abs(ls["sharp_ratio"]) >= .5 else "弱")
        j_stab = "稳定" if (sh.std() < 1 and sh_pos >= .7) else ("偏不稳定" if sh.std() >= 1.5 else "中等")
        j_vol = "稳定" if cv < .3 else ("中等" if cv < .5 else "不稳定")

        rows = [
            ("① 分层效果", f"单调性 ρ(组号,累计收益)={rho:+.2f}；顶组−底组 累计收益差={tot.iloc[-1]-tot.iloc[0]:+.2f}", j_rho),
            ("② 多空组", f"年化 {ls['annual_return_ratio']:+.2%} / Sharpe {ls['sharp_ratio']:+.2f} / 回撤 {ls['max_drawdown']:+.1%} / IR {ls['information_ratio']:+.3f}", j_sh),
            ("③ 年度 Sharpe 稳定性(多头)", f"均值 {sh.mean():+.2f}（中位 {sh.median():+.2f}）最小 {sh.min():+.2f} 最大 {sh.max():+.2f}；"
                                    f"标准差 {sh.std():.2f}；正向年 {int((sh>0).sum())}/{len(sh)}", j_stab),
            ("④ 收益波动率稳定性(多头)", f"均值 {vol.mean():+.2%}（中位 {vol.median():+.2%}）最小 {vol.min():+.2%} 最大 {vol.max():+.2%}；CV {cv:.2f}", j_vol),
        ]
        return pd.DataFrame(rows, columns=["项", "数值", "判定"])

    # ───────── ⑩ 图表（plotly 本地；对齐云端 render 的 7 张）─────────
    def render(self, out_html: str | None = None, local_plot: bool = False):
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        title = (f"因子分析 — {self.p['alpha_name_chinese']}（{self.p['alpha_name']}）"
                 f" | 池={self.p['instruments']} | 基准={self.p['benchmark']} | {self.p['group_num']} 组"
                 f" | 频率={self.freq}")
        top = str(self.p["group_num"] - 1)

        # 1) 分组累计收益 + IC 曲线 + IC 累计
        fig1 = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45],
                             subplot_titles=("分组累计收益（简单加总，同平台）", "IC 曲线（日 IC / 22 日均值 / 累计）"))
        for c in [x for x in self.group_cum.columns if x != "bm"]:
            fig1.add_trace(go.Scatter(x=self.group_cum.index, y=self.group_cum[c], name=f"G{c}",
                                      line=dict(width=1)), row=1, col=1)
        fig1.add_trace(go.Scatter(x=self.group_cum.index, y=self.group_cum["bm"], name="基准",
                                  line=dict(dash="dot", color="gray")), row=1, col=1)
        # ★ 云端 get_all_ic 先把 IC 序列 `.shift(1)` 再画曲线/累计 —— 逐字对齐
        ic = self.ic.shift(1).dropna()
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

        # 2b) IC 分析指标（云端 c4：IC / |IC|>0.02 占比 / IR）
        icd = self.ic_stats()
        fig_ic = go.Figure(go.Table(
            header=dict(values=list(icd.columns), fill_color="#f3f5f8", align="left"),
            cells=dict(values=[icd[c] for c in icd.columns], align="left", height=30)))
        fig_ic.update_layout(title="IC 分析指标", height=230)

        # 3) 因子值最大/最小的 5 只（最后一天）
        last = self.factor["date"].max()
        topdf = self.factor[self.factor["date"] == last].sort_values("factor", ascending=False)
        def _tbl(d, t):
            d = d.copy(); d["date"] = d["date"].dt.strftime("%Y-%m-%d")
            d = d[["date", "instrument", "factor"]].round(4)
            f = go.Figure(go.Table(header=dict(values=list(d.columns), fill_color="#f3f5f8", align="left"),
                                   cells=dict(values=[d[c] for c in d.columns], align="left", height=24)))
            f.update_layout(title=f"{t}（{last.date()}）", height=340)
            return f
        fig4 = _tbl(topdf.head(5), "因子值最大的 5 只")
        fig5 = _tbl(topdf.tail(5), "因子值最小的 5 只")

        # 0) ★ 总结（分层效果 / 多空 / 年度稳定性）
        c = self.conclude()
        fig0 = go.Figure(go.Table(
            header=dict(values=list(c.columns), fill_color="#eaf2f8", align="left"),
            cells=dict(values=[c[x] for x in c.columns], align="left", height=34)))
        fig0.update_layout(title="★ 总结", height=540)

        figs = [("★ 总结", fig0), ("整体绩效指标", fig2), ("年度绩效指标(多头组合)", fig3),
                ("IC 分析指标", fig_ic), ("分组累计收益 / IC 曲线", fig1),
                ("因子值最大的 5 只标的", fig4), ("因子值最小的 5 只标的", fig5)]
        p = Path(out_html or (REPO / "scripts" / f"factor_report_{self.p['alpha_name']}.html"))
        parts = [f"<h2>{title}</h2>"]
        for k, (name, f) in enumerate(figs):
            # ★ 自包含：**只有第一张内联 plotly.js**（后面复用），零 CDN ——
            #   IDE 内置预览 / 离线环境会拦外部 script，CDN 版会整页空白。
            parts.append(f"<h3>{name}</h3>"
                         + f.to_html(full_html=False, include_plotlyjs=(True if k == 0 else False)))
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


# ══════════════════════════ CLI（可选入口；推荐写 driver 脚本传参）══════════════════════════
def run(alpha_test: dict, factor_fn=None, jobs: int = 1, out_html: str | None = None):
    """★ 一行式入口：`run(alpha_test_dict)` —— 对标云端
    `alpha_miner = AlphaMiner(params=alpha_test); alpha_miner.render(local_plot=True)`。
    `alpha_test` 就是云端那套参数（alpha_name / alpha_py / group_num / instruments / benchmark …）。"""
    m = AlphaMiner(alpha_test, factor_fn=factor_fn, jobs=jobs)
    print("\n" + "=" * 78)
    print(f"IC 均值 {m.ic.mean():+.4f} | ICIR {m.ic.mean()/m.ic.std():+.3f} | "
          f"|IC|≥0.02 占比 {(m.ic.abs()>=0.02).mean():.1%} | IC 日数 {len(m.ic)}")
    print("=" * 78)
    print(m.summary().to_string())
    print("\n年度绩效指标(多头组合):")
    print(m._yearly_perf().to_string())
    print("\nIC 分析指标（全部组）:")
    print(m.ic_stats().to_string(index=False))
    print("\n" + "=" * 78)
    print("总结")
    print("=" * 78)
    print(m.conclude().to_string(index=False))
    m.render(out_html=out_html)
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description="AlphaMiner 本地版 —— 命令行入口（因子用 --alpha-py 给）")
    ap.add_argument("--alpha-py", required=True, help="因子 Python 表达式（对标云端 alpha_sql）")
    ap.add_argument("--name", default="my_factor")
    ap.add_argument("--pool", default=PARAMS["instruments"], choices=list(POOLS) + ["全市场"])
    ap.add_argument("--benchmark", default=PARAMS["benchmark"], choices=list(BENCH))
    ap.add_argument("--group-num", type=int, default=10)
    ap.add_argument("--start", default=PARAMS["start"])
    ap.add_argument("--freq", default="daily", choices=["daily", "weekly"],
                    help="分析频率：daily=云端 AlphaMiner 行为 / weekly=附加（重采样到每周最后一个交易日）")
    ap.add_argument("--no-process", action="store_true", help="关闭预处理（不对齐平台 data_process=True）")
    ap.add_argument("--jobs", type=int, default=1, help="多进程数（因子计算 + 预处理）")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    run({"alpha_name": a.name, "alpha_py": a.alpha_py, "instruments": a.pool,
         "benchmark": a.benchmark, "group_num": a.group_num, "start": a.start,
         "data_process": not a.no_process, "freq": a.freq}, jobs=a.jobs, out_html=a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
