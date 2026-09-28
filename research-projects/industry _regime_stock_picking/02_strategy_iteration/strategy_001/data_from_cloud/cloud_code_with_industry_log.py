#%%
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from bigquant import bigtrader, dai

# ==================== 参数 ====================
# 行业层：变盘指数（沿用银河证券研报基准参数）
LOOKBACK_M     = 220      # 排名比较回望窗口 = 波动率窗口
SMOOTH_W       = 20       # 平滑窗口
MONTH_RET_DAYS = 20       # "月度收益率"对应交易日数
MOM_WINDOW     = 240      # T'<0 收敛期用长期动量
REV_WINDOW     = 60       # T'>0 发散期用短期反转（取负）

# 选股层
TOP_IND     = 3        # 每周选行业数
N_PER_IND   = 2           # 每行业选股数 → 共 6 只（原 3 只 → 优化1：提高选股门槛，减少稀释）
BUF_MULT    = 3.0         # 持仓缓冲：老持仓仍在行业内前 N*BUF_MULT 名则保留
MIN_AMOUNT  = 2e7         # 个股成交额门槛（元）

# 四因子（方向：-1 表示取负后越大越买；均为"短期反转 + 低关注度"方向）
FACTORS = {"turn_ratio": -1,   # 5日/60日换手比 —— 短期关注度降温
           "px_ma20":    -1,   # 收盘偏离 MA20 —— 超买回归
           "mom_20":     -1,   # 20日动量取负 —— 短期反转
           "liq_amount": -1}   # 20日均成交额取负 —— 低流动性溢价

# ---- 优化2：信号稳定性过滤 ----
# 本周所选 TOP_IND 个行业与上周完全一致（无任何轮换）才维持满仓，否则空仓一周
STABILITY_FULL_OVERLAP = True

# ---- 优化3：个股内部风险平价 ----
STOCK_VOL_WINDOW = 20      # 个股波动率窗口（交易日），用于组内反向波动率加权

# 回测
BT_START = "2015-01-06"

import os
trading_date = os.environ.get("TRADING_DATE") 
if trading_date:     
    BT_END = trading_date 
else:    
    BT_END = "2026-09-28"

DATA_START       = "2009-01-01"    # 变盘指数预热需约 480 根 bar
CAPITAL_BASE     = 500_000
BUY_COST, SELL_COST, MIN_COST = 0.0003, 0.0013, 5
SLIPPAGE         = 0.0             # 不计滑点

# ==================== ★ 因子对账导出（2026-09-28 加）====================
# 用途：把「调仓日 × 当周选中行业」的因子 panel 存成文件，下载后与本地 BigQuant
#       仓库算出的因子逐值比对，定位是哪个因子算得不一样。
# 背景：行业信号已证实 494/494 周与本地完全一致，差异只可能在因子值。
PANEL_START = "2026-01-01"      # 只导 2026（用户要求；数据量小、能立刻比对）
# END 取 2026-08-14：本地信号日到这天为止。原因是 build_stock_panel 的「次日可成交」
# 过滤需要**下一个交易日**，而 2026-08-21 正好是本地数据的最后一天 → 本地永远产不出
# 2026-08-21 这一期（属范围边界产物，不是数据缺口）。对齐到 08-14 两边才逐日可比。
PANEL_END   = "2026-08-14"
# ★ 叠加累积器：本函数被调用多次 / 本 cell 被重复运行时**追加**而不是覆盖
#   —— 否则文件里只会剩下最后一次那几天的数据。
_PANEL_ACCUM = []
# 注意：**云端没有配额限制**（配额只对本地 SDK 生效），所以取数与回测都照常跑全区间，
# 这里只把**导出**的部分限定在 2026（比对用，数据量小）。
# 另外云端 dai 没有 `get_data_quota()`（那是本地 SDK 才有的），别在云端调它。


# ==================== 1. 行业层：变盘指数 → 每周前 3 个行业 ====================
def load_industry_close():
    """申万一级行业指数日收盘价，返回 date x industry 宽表。"""
    sql = """
    SELECT date,
           sw_level_index_code AS ind,
           sw_level1_name      AS name,
           sw_level1_close     AS close
    FROM cn_stock_prefactors
    WHERE sw_level1_close IS NOT NULL
    GROUP BY 1, 2, 3, 4
    """
    df = dai.query(sql, filters={"date": [DATA_START, BT_END]}).df()
    name_map = df.drop_duplicates("ind").set_index("ind")["name"].to_dict()
    close = df.pivot_table(index="date", columns="ind", values="close").sort_index()
    return close, name_map


def pick_industries(close):
    """
    变盘指数四步 + 动量/反转切换 → 每个周频信号日的前 TOP_IND 个行业。

    T 是二阶量：先算行业排名的迁移幅度（一阶），再算迁移幅度的滚动波动（二阶），
    最后平滑。T' = T.diff() 只做风格开关，不参与横截面排序。
    """
    # step 1-2: 各行业"月度收益率"横截面排名，与 M 日前比较后取绝对迁移幅度，横截面平均
    month_ret = close / close.shift(MONTH_RET_DAYS) - 1.0
    rank_now = month_ret.rank(axis=1, method="average")
    rank_change = (rank_now - rank_now.shift(LOOKBACK_M)).abs().mean(axis=1)
    # step 3-4: 迁移强度的滚动波动率 → 平滑 → 变盘指数 T
    T = (rank_change.rolling(LOOKBACK_M, min_periods=LOOKBACK_M).std()
         .rolling(SMOOTH_W, min_periods=SMOOTH_W).mean())
    Td = T.diff()

    f_mom = close / close.shift(MOM_WINDOW) - 1.0        # 动量
    f_rev = -(close / close.shift(REV_WINDOW) - 1.0)     # 反转取负，统一为越大越买

    use_mom, use_rev = (Td < 0).fillna(False), (Td > 0).fillna(False)
    factor = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    factor[use_mom] = f_mom[use_mom]
    factor[use_rev] = f_rev[use_rev]
    regime = pd.Series(np.where(use_mom, "momentum",
                                np.where(use_rev, "reversal", "none")),
                       index=close.index)

    # 周频信号日 = 每周最后一个交易日
    s = pd.Series(close.index, index=close.index)
    weekly = pd.DatetimeIndex(s.groupby(close.index.to_period("W")).last().values)
    weekly = pd.DatetimeIndex([d for d in weekly
                               if d <= pd.Timestamp(BT_END)
                               and factor.loc[d].notna().sum() >= TOP_IND])
    # 保留 BT_START 之前最后一个信号日，使回测首日即满仓（否则第一周空仓）
    prior = weekly[weekly < pd.Timestamp(BT_START)]
    lo = prior[-1] if len(prior) else pd.Timestamp(BT_START)
    weekly = weekly[weekly >= lo]

    rows = []
    for d in weekly:
        for c in factor.loc[d].dropna().nlargest(TOP_IND).index:
            rows.append({"date": d, "ind_code": c, "regime": regime[d]})
    return pd.DataFrame(rows), weekly


def compute_stability_exposure(ind_sig, weekly):
    """
    优化2：信号稳定性过滤。

    本周所选 TOP_IND 个行业集合与上周完全相同（无任何轮换）→ exposure=1（满仓）；
    只要发生一个行业的轮换 → exposure=0（空仓一周，等信号稳定后再入场）。
    首个信号周默认满仓（无上周可比）。
    """
    picks_by_date = {d: set(ind_sig.loc[ind_sig["date"] == d, "ind_code"])
                      for d in weekly}
    exposure = {}
    prev = None
    for d in weekly:
        cur = picks_by_date[d]
        exposure[d] = 1.0 if (prev is None or cur == prev) else 0.0
        prev = cur
    return pd.Series(exposure)


# ==================== 2. 选股层：行业内四因子复合排名 ====================
def load_stock_panel(sig_dates, ind_sig):
    """只在信号日取数，并裁剪到当周多头行业，避免全区间个股面板过大。

    ★ 2026-09-28 改（供本地因子对账）：取数与截断逻辑**一字未改**，
      只在最后把生成的 panel 里 2026 的部分**叠加导出**成文件
      （`_PANEL_ACCUM` 累积 → 重复运行只追加不覆盖，否则只剩最后一次的日期）。
    """
    dl = ",".join(f"'{pd.Timestamp(d).strftime('%Y-%m-%d')}'" for d in sig_dates)
    # 两个阈值内联为字面量（值与 MIN_AMOUNT / STOCK_VOL_WINDOW 相同）。
    # 不用 $占位符 + params：省得再踩「excess parameters」/「can't be prepared」。
    sql = f"""
    WITH ts AS (
        SELECT date, instrument, sw_level_index_code AS ind_code,
            m_avg(turn, 5) / (m_avg(turn, 60) + 1e-8)  AS turn_ratio,
            close / (m_avg(close, 20) + 1e-8) - 1       AS px_ma20,
            close / m_lag(close, 20) - 1                AS mom_20,
            m_avg(amount, 20)                           AS liq_amount,
            m_nanstd(close / m_lag(close, 1) - 1, {STOCK_VOL_WINDOW}) AS vol_stock
        FROM cn_stock_prefactors
        WHERE st_status = 0 AND suspended = 0 AND list_days > 252
          AND amount > {int(MIN_AMOUNT)} AND sw_level_index_code IS NOT NULL
    )
    SELECT * FROM ts WHERE date IN ({dl})
    """
    # 缓冲 1 年供 m_avg(turn, 60) 等窗口函数预热
    buf = (pd.Timestamp(BT_START) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    df = dai.query(sql, filters={"date": [buf, BT_END]}).df()
    df["date"] = pd.to_datetime(df["date"])
    key = set(zip(ind_sig["date"], ind_sig["ind_code"]))
    out = df[[(d, c) in key for d, c in zip(df["date"], df["ind_code"])]].copy()

    # ── ★ 叠加写出（对账用）──
    _sub = out[(out["date"] >= pd.Timestamp(PANEL_START))
               & (out["date"] <= pd.Timestamp(PANEL_END))]
    if len(_sub):
        _PANEL_ACCUM.append(_sub)
        _acc = (pd.concat(_PANEL_ACCUM, ignore_index=True)
                  .drop_duplicates(subset=["date", "instrument"], keep="last")
                  .sort_values(["date", "instrument"]).reset_index(drop=True))
        try:
            _acc.to_parquet("panel_2026.parquet", index=False)
            _path = "panel_2026.parquet"
        except Exception as _e:
            _path = "panel_2026.csv.gz"
            _acc.to_csv(_path, index=False, compression="gzip", encoding="utf-8")
            print(f"  （parquet 不可用: {type(_e).__name__} → 退 gzip CSV）")
        print(f"★ 因子panel已**叠加**写出: {len(_acc):,} 行 × {_acc.shape[1]} 列 / "
              f"{_acc['date'].nunique()} 个信号日 / {_acc['instrument'].nunique()} 只")
        print(f"  列: {list(_acc.columns)}")
        print(f"  绝对路径: {os.path.abspath(_path)}")
    return out


def build_holdings(panel, exposure):
    """
    行业内复合因子取前 N_PER_IND 只 + 持仓缓冲；行业间等权，行业内按 20 日波动率倒数
    分配权重（优化3：个股风险平价，降低高波动个股对组合波动的贡献），再乘以信号稳定性
    过滤给出的仓位敞口 exposure（优化2：非稳定信号周直接空仓）。

    缓冲逻辑：老持仓只要还在行业内前 N_PER_IND*BUF_MULT 名就保留，
    只有掉出该范围才被替换。周均换手由 0.64 降至 0.48，年化提升约 9 个百分点。
    """
    sc = panel[["date", "instrument", "ind_code", "vol_stock"]].copy()
    sc["_s"] = pd.concat(
        [(panel[f] * sgn).groupby([panel["date"], panel["ind_code"]]).rank(pct=True)
         for f, sgn in FACTORS.items()], axis=1).mean(axis=1)
    sc = sc.dropna(subset=["_s"])

    # 复合分存在大量并列（约 1/3 的行业-周有并列），必须用 instrument 做显式
    # 二级排序键。否则并列的名次由 DAI 返回的行顺序决定，同一份数据重跑
    # 结果会漂移（实测年化可差 0.5 个百分点）。
    keep_n = int(round(N_PER_IND * BUF_MULT))
    sc = sc.sort_values(["date", "ind_code", "_s", "instrument"],
                        ascending=[True, True, False, True])
    sc["rk"] = sc.groupby(["date", "ind_code"]).cumcount() + 1
    vol_map = dict(zip(zip(sc["date"], sc["instrument"]), sc["vol_stock"]))

    out, held = [], {}          # held: ind_code -> 当前持仓列表
    for d, day in sc.groupby("date", sort=True):
        for ind, g in day.groupby("ind_code", sort=False):
            rank_of = dict(zip(g["instrument"], g["rk"]))
            stay = [x for x in held.get(ind, [])
                    if rank_of.get(x, 10 ** 9) <= keep_n][:N_PER_IND]
            need = N_PER_IND - len(stay)
            if need > 0:
                stay += [x for x in g["instrument"].tolist() if x not in stay][:need]
            held[ind] = stay
            out += [(d, ind, x) for x in stay]
        for ind in list(held):                      # 行业轮出则清空
            if ind not in set(day["ind_code"]):
                held.pop(ind)

    picks = pd.DataFrame(out, columns=["date", "ind_code", "instrument"])
    picks["vol_stock"] = [vol_map.get((d, i), np.nan)
                          for d, i in zip(picks["date"], picks["instrument"])]
    # 波动率缺失（极少数新股/数据不足）用当日行业内中位数兜底
    picks["vol_stock"] = picks["vol_stock"].fillna(
        picks.groupby(["date", "ind_code"])["vol_stock"].transform("median"))
    inv_vol = 1.0 / picks["vol_stock"].clip(lower=1e-4)
    w_in_ind = inv_vol / inv_vol.groupby([picks["date"], picks["ind_code"]]).transform("sum")

    n_ind = picks.groupby("date")["ind_code"].transform("nunique")
    picks["exposure"] = picks["date"].map(exposure).fillna(1.0)
    weight = w_in_ind / n_ind * picks["exposure"]
    return picks.assign(weight=weight)[
        ["date", "instrument", "weight"]].reset_index(drop=True)


def expand_to_daily(hold, cal):
    """
    信号日权重前推到每个交易日。

    handle_data_weight_based 会卖出当天 context.data 里没有的持仓：
    只在信号日给权重会导致次日全部清仓、实际持有期仅 1 天。
    """
    sig = sorted(hold["date"].unique())
    frames = []
    for k, d0 in enumerate(sig):
        d1 = sig[k + 1] if k + 1 < len(sig) else cal[-1]
        w = hold.loc[hold["date"] == d0, ["instrument", "weight"]]
        for dt in cal[(cal >= d0) & (cal <= d1)]:
            f = w.copy()
            f["date"] = dt
            frames.append(f)
    out = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["date", "instrument"], keep="last")   # 边界日保留新信号
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out[["date", "instrument", "weight"]].sort_values(
        ["date", "instrument"]).reset_index(drop=True)


# ==================== 3. 组装信号 ====================
close_ind, NAME = load_industry_close()
ind_sig, weekly = pick_industries(close_ind)
print(f"行业指数: {close_ind.shape[1]} 个行业, "
      f"{close_ind.index.min().date()} ~ {close_ind.index.max().date()}")
print(f"周频信号日: {len(weekly)}  {weekly[0].date()} ~ {weekly[-1].date()}")

exposure = compute_stability_exposure(ind_sig, weekly)

# ==================== ★ 调仓行业日志（2026-09-28 加，供本地逐周对比）====================
# 直接**写文件**（不靠 print 手动复制，避免抄错）：云端工作目录下生成 industry_log.csv，
# 下载后放到 data_from_cloud/ 再跑 compare_industry_log.py 即可逐周比对。
# 输出字段：signal_date / regime / exposure(1=满仓 0=空仓) / top3(三个行业中文名，| 分隔)
_rows = []
for _d in weekly:
    _sub = ind_sig.loc[ind_sig["date"] == _d]
    _rows.append({
        "signal_date": str(_d.date()),
        "regime": (_sub["regime"].unique()[0] if len(_sub) else "none"),
        "exposure": float(exposure.loc[_d]),
        "top3": "|".join(sorted(NAME.get(c, c) for c in _sub["ind_code"].tolist())),
    })
_log = pd.DataFrame(_rows)
_log.to_csv("industry_log.csv", index=False, encoding="utf-8-sig")
print(f"★ 调仓行业日志已写出: industry_log.csv（{len(_log)} 周）")
print(f"  绝对路径: {os.path.abspath('industry_log.csv')}")

cash_weeks = int((exposure < 1.0).sum())
print(f"信号稳定性过滤: 空仓周数 {cash_weeks}/{len(exposure)} "
      f"({cash_weeks / len(exposure):.1%})")

panel = load_stock_panel(weekly, ind_sig)
holdings = build_holdings(panel, exposure)

CAL = close_ind.index[(close_ind.index >= pd.Timestamp(BT_START)) &
                      (close_ind.index <= pd.Timestamp(BT_END))]
holdings_daily = expand_to_daily(holdings, CAL)

_w = holdings.pivot_table(index="date", columns="instrument",
                          values="weight").fillna(0)
turnover = (_w - _w.shift(1)).abs().sum(axis=1).mul(0.5).dropna().mean()
print(f"每期持仓: {int(holdings[holdings['weight'] > 0].groupby('date').size().median())} 只   "
      f"周均换手: {turnover:.3f} → 单边年化 {turnover * 52:.1f} 倍")

last = holdings["date"].max()
last_exposure = exposure.loc[last]
print(f"\n最新信号日 {last.date()}（"
      f"{'动量' if ind_sig.loc[ind_sig['date'] == last, 'regime'].iloc[0] == 'momentum' else '反转'}）"
      f"，仓位敞口 {last_exposure:.0f}，次日开盘建仓：")
if last_exposure > 0:
    for _, r in holdings[(holdings["date"] == last) & (holdings["weight"] > 0)].iterrows():
        ind = panel.loc[(panel["date"] == last) &
                        (panel["instrument"] == r["instrument"]), "ind_code"]
        tag = NAME.get(ind.iloc[0], "") if len(ind) else ""
        print(f"  {tag:6s} {r['instrument']}  权重 {r['weight']:.4f}")
else:
    print("  行业信号本周发生轮换，空仓等待信号稳定")


# ==================== 4. 回测 ====================
def initialize(context: bigtrader.IContext):
    context.set_commission(bigtrader.PerOrder(
        buy_cost=BUY_COST, sell_cost=SELL_COST, min_cost=MIN_COST))
    if SLIPPAGE > 0:
        context.set_slippage_value(slippage_type=2, slippage_value=SLIPPAGE)
    context.data = holdings_daily


performance = bigtrader.run(
    market=bigtrader.Market.CN_STOCK,
    frequency=bigtrader.Frequency.DAILY,
    start_date=BT_START,
    end_date=BT_END,
    capital_base=CAPITAL_BASE,
    initialize=initialize,
    handle_data=bigtrader.HandleDataLib.handle_data_weight_based,
    benchmark="000300.SH",
)

print("\n" + "=" * 56)
print(f"绩效（含手续费{'' if SLIPPAGE > 0 else '、不计滑点'}）")
print("=" * 56)
for k, v in performance.get_stats().items():
    print(f"  {k:24s} = {v}")
