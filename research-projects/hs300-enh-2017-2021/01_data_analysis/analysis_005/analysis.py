"""analysis_005 — 特征驱动的 v2.7 突破信号过滤（长江 26 价量特征 + 决策树分类）。

目的：找**能提高 v2.7 成功率的因素**——用长江证券《平台突破》表4 的 26 个价量特征
训练决策树（分类树，非长江的线性逐步回归），对 v2.7 突破信号做 a/b/c 三分类过滤。

标签（与 analysis_004 更新一规则一致，成功拆两类；基准=突破次日开盘，窗口20交易日）：
  a（无效）：窗口内最低 < 基准×0.95 或 第20日收益 < 0
  c（强势有效）：未破 -5% 且 窗口内最高 > 基准×1.10
  b（温和有效）：未破 -5% 且 第20日收益 > 0（其余归 a）

26 特征（表4，六类；面板列 turn/amount/close/total_market_cap 可全算）：
  换手率7：Turn, TurnMean{5,20,45}d, TurnVol{5,20,45}d
  成交额6：AmtMean{5,20,45}d, AmtRatio{5,20,45}d（当日/N日均值）
  动量3：Ret{5,20,45}d　波动率3：Vol{5,20,45}d（日收益std）
  市值4：LnCap, CapVol{5,20,45}d　均线偏离3：PriceMA{5,20,45}Dev

更新一（LightGBM + 2年训练窗 + 去市值特征）：诊断确认单棵树"高偏差为主"
（最优容量下 test macroF1 顶格 0.51、准确率不敌多数类基线）→ 换 boosting 降偏差。
模型 = LGBMClassifier；train 窗 1 年 → **2 年**（[H-30月, H-6月)）；特征 **22 个**
（剔除市值类 LnCap/CapVol{5,20,45}d）。特征大表 feature_panel.parquet 复用（仍全算，
仅模型输入剔除）。滚动/标签/过滤/输出结构不变。

更新二（回朴素：4 个逻辑特征 + OLS 线性）：机器学习过滤提升有限（+2.3pp 未达显著），
用户改走"一点一点加"的朴素路线——**4 个加工特征 + OLS**：
  TurnDecay   换手率衰减 = (TurnMean5d − TurnMean20d)/TurnMean20d×100（逻辑：突破点换手衰减好）
  AmtDecay    成交额变化 = (AmtMean5d − AmtMean20d)/AmtMean20d×100（逻辑：突破点成交额增加好）
  VolDecay    波动率变化 = (Vol5d − Vol20d)/Vol20d×100
  PricePctile60 价格分位数 = 收盘价在过去 60 日收盘中的分位（逻辑：低位突破好）
模型 = sklearn LinearRegression（OLS，含截距）；**y = ret_20（20 日前瞻收益%）**；
训练 = 生效半年 H 前推 **1 年**（[H−12月, H)，OLS 无超参故无验证窗）；
test 期信号 score = 预测收益，**score>0 → 有效（b/c 语义），≤0 → 无效**。
滚动窗口/成分过滤/输出结构与前版一致（test 仍为 2018H2~2026H2，可与更新一对比）。

滚动训练（用户 5.2/6.x）：模型有效期半年、连滚无缺口：
  对每个生效半年 H（2018H2 ~ 2026H2 共 17 个）：
    train = [H-30月, H-6月)（2年，更新一），val = [H-6月, H)（半年），test = H（半年）
  网格 max_depth×min_samples_leaf×class_weight 按 val macro-F1 选优；
  test 期信号 → 预测 a=无效（丢弃），b/c=有效（记录，格式同 analysis_004）。
  边界日旧模型照常使用、新模型次日起生效（按信号日落入的 H 归属模型，天然连续）。

数据：`_market_hs300_panel.parquet`（668 只历史成分 2015~2026-08）；
信号：复用 `analysis_004/breakout_detail.parquet`（8429 次 v2.7 向上突破）；
成分：信号须属 members_asof(当日) 沪深300 成分（plateau_algo）。

输出（本目录）：
  feature_panel.parquet       特征+前向统计大表（一次预计算，全 symbol×date）
  model_metrics.csv           每模型 train/val/test 指标 + 特征重要度
  filtered_detail.parquet/csv 过滤后明细（true_label/pred/valid，同 004 格式+预测列）
  summary_by_halfyear.csv / summary_by_year.csv / summary_by_symbol.csv
  result_view.html            可视化
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))

from plateau_algo import members_asof   # noqa: E402  当日沪深300成分

FAIL_PCT, WIN_PCT, WINDOW = 0.05, 0.10, 20
# 更新一：剔除市值类（LnCap/CapVol*），26 → 22 特征（保留供特征大表全算）
FEATS = (["Turn"] + [f"TurnMean{n}d" for n in (5, 20, 45)] + [f"TurnVol{n}d" for n in (5, 20, 45)]
         + [f"AmtMean{n}d" for n in (5, 20, 45)] + [f"AmtRatio{n}d" for n in (5, 20, 45)]
         + [f"Ret{n}d" for n in (5, 20, 45)] + [f"Vol{n}d" for n in (5, 20, 45)]
         + [f"PriceMA{n}Dev" for n in (5, 20, 45)])
# 更新二：4 个逻辑加工特征（模型输入）
FEATS4 = ["TurnDecay", "AmtDecay", "VolDecay", "PricePctile60"]


# ══════════════════ ① 特征 + 前向统计大表 ══════════════════

def _fwd_extreme(s: pd.Series, window: int, fn) -> pd.Series:
    """t 行 = s[t+1..t+window] 的 min/max（反转滚动技巧）。不足 window 为 NaN。"""
    r = fn(s.iloc[::-1].rolling(window, min_periods=window))
    return r.iloc[::-1].shift(-1)


def build_feature_panel() -> pd.DataFrame:
    fp = HERE / "feature_panel.parquet"
    if fp.exists():
        print("特征大表已缓存，跳过计算")
        return pd.read_parquet(fp)
    market = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
    market["date"] = pd.to_datetime(market["date"])
    out = []
    for k, (sym, g) in enumerate(market.groupby("symbol"), 1):
        g = g.sort_values("date").copy()
        turn, amt, close = g["turn"].astype(float), g["amount"].astype(float), g["close"].astype(float)
        cap = g["total_market_cap"].astype(float)
        ret1 = close.pct_change()
        d = {"symbol": sym, "date": g["date"], "Turn": turn}
        for n in (5, 20, 45):
            d[f"TurnMean{n}d"] = turn.rolling(n).mean()
            d[f"TurnVol{n}d"] = turn.rolling(n).std()
            d[f"AmtMean{n}d"] = amt.rolling(n).mean()
            d[f"AmtRatio{n}d"] = amt / amt.rolling(n).mean()
            d[f"Ret{n}d"] = close.pct_change(n)
            d[f"Vol{n}d"] = ret1.rolling(n).std()
            d[f"CapVol{n}d"] = cap.rolling(n).std()
            d[f"PriceMA{n}Dev"] = close / close.rolling(n).mean() - 1
        d["LnCap"] = np.log(cap)
        # 更新二：4 个逻辑加工特征
        d["TurnDecay"] = (turn.rolling(5).mean() - turn.rolling(20).mean()) / turn.rolling(20).mean() * 100
        d["AmtDecay"] = (amt.rolling(5).mean() - amt.rolling(20).mean()) / amt.rolling(20).mean() * 100
        d["VolDecay"] = (ret1.rolling(5).std() - ret1.rolling(20).std()) / ret1.rolling(20).std() * 100
        d["PricePctile60"] = close.rolling(60).rank(pct=True) * 100
        # 前向统计（t+1..t+20；基准=t+1 开盘）
        base = g["open"].shift(-1).astype(float)
        d["base"] = base
        d["min_low_20"] = _fwd_extreme(g["low"].astype(float), WINDOW, lambda r: r.min())
        d["max_high_20"] = _fwd_extreme(g["high"].astype(float), WINDOW, lambda r: r.max())
        d["close_20"] = close.shift(-WINDOW)
        d["ret_20"] = d["close_20"] / base - 1
        out.append(pd.DataFrame(d))
        if k % 100 == 0:
            print(f"  特征 … {k}/668")
    panel = pd.concat(out, ignore_index=True)
    for c in FEATS + FEATS4:
        panel[c] = panel[c].astype("float32")
    panel.to_parquet(fp, index=False)
    print(f"特征大表：{len(panel)} 行 × {len(panel.columns)} 列 → {fp}")
    return panel


def label_abc(row) -> str:
    """a=失败规则；c=未破且冲+10%；b=未破且收益>0；其余（恰0未冲）归 a。NaN 前向→NaN。"""
    if pd.isna(row["ret_20"]) or pd.isna(row["min_low_20"]):
        return np.nan
    if row["min_low_20"] < row["base"] * (1 - FAIL_PCT) or row["ret_20"] < 0:
        return "a"
    if row["max_high_20"] > row["base"] * (1 + WIN_PCT):
        return "c"
    if row["ret_20"] > 0:
        return "b"
    return "a"


# ══════════════════ ② 信号表（join 特征 + 标签 + 成分过滤）══════════════════

def load_signals(panel: pd.DataFrame) -> pd.DataFrame:
    det = pd.read_parquet(PROJ / "01_data_analysis" / "analysis_004" / "breakout_detail.parquet")
    det["date"] = pd.to_datetime(det["date"])
    sig = det.merge(panel, on=["symbol", "date"], how="left", suffixes=("", "_fp"))
    sig["true_label"] = sig.apply(label_abc, axis=1)
    # 当日成分股过滤（用户 5.0：当年沪深300成分）
    sig["is_member"] = [s in members_asof(d) for s, d in zip(sig["symbol"], sig["date"])]
    n0, n1 = len(sig), int(sig["is_member"].sum())
    print(f"信号 {n0} → 成分内 {n1}（剔除非当日成分 {n0 - n1}）")
    return sig[sig["is_member"]].reset_index(drop=True)


# ══════════════════ ③ 滚动模型（train 1年 / val 半年 / test 半年）══════════════════

def halfyear_starts():
    return list(pd.date_range("2018-07-01", "2026-07-01", freq="6MS"))


def rolling_models(sig: pd.DataFrame):
    """更新二：4 特征 OLS（y=20日前瞻收益%），score>0=有效；训 1 年 / 测半年滚动，无验证窗。"""
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import confusion_matrix

    lab = sig.dropna(subset=["true_label", "ret_20"] + FEATS4).copy()
    lab["y"] = lab["ret_20"].astype(float) * 100      # 回归目标：20 日收益%
    lab["true_valid"] = lab["true_label"].isin(["b", "c"])
    X_all, y_all = lab[FEATS4].values, lab["y"].values
    tv_all = lab["true_valid"].values
    dser = lab["date"].reset_index(drop=True)

    metrics, preds = [], []
    for mid, h0 in enumerate(halfyear_starts(), 1):
        h1 = h0 + pd.DateOffset(months=6)
        tr0 = h0 - pd.DateOffset(months=12)            # 更新二：1 年训练窗，紧贴生效期
        m_tr = ((dser >= tr0) & (dser < h0)).values
        m_te = ((dser >= h0) & (dser < h1)).values
        if m_tr.sum() < 50 or m_te.sum() == 0:
            continue
        ols = LinearRegression().fit(X_all[m_tr], y_all[m_tr])
        score_te = ols.predict(X_all[m_te])
        pred_valid = score_te > 0
        acc = float((pred_valid == tv_all[m_te]).mean())
        corr = float(np.corrcoef(score_te, y_all[m_te])[0, 1]) if m_te.sum() > 2 else np.nan
        coefs = dict(zip(FEATS4, [float(c) for c in ols.coef_]))
        coef_str = " | ".join(f"{k}={v:+.4f}" for k, v in coefs.items())
        metrics.append({
            "model": f"M{mid}", "test期": f"{h0.date()}~{min(h1, pd.Timestamp('2026-08-21')).date()}",
            "train": f"{tr0.date()}~{h0.date()}",
            "params": f"OLS intercept={ols.intercept_:+.3f}; {coef_str}",
            "n_train": int(m_tr.sum()), "n_test": int(m_te.sum()),
            "train_R2": round(float(ols.score(X_all[m_tr], y_all[m_tr])), 4),
            "test_acc_sign": round(acc, 3),
            "test_corr_ret20": round(corr, 3) if not np.isnan(corr) else np.nan,
            "keep_rate": round(float(pred_valid.mean()), 3),
            "_coefs": coefs,
            "_cm": confusion_matrix(tv_all[m_te].astype(int), pred_valid.astype(int), labels=[0, 1]),
        })
        te_idx = lab.index[m_te]
        for i, s in zip(te_idx, score_te):
            preds.append({"idx": i, "model": f"M{mid}", "score": float(s)})
        print(f"  M{mid} test {h0.date()}~{h1.date()}: acc={acc:.3f} keep={pred_valid.mean():.2f} "
              f"corr={corr:.3f} n={int(m_te.sum())}")
    return pd.DataFrame(metrics), pd.DataFrame(preds)


# ══════════════════ ④ 汇总 + 可视化 ══════════════════

def main():
    panel = build_feature_panel()
    sig = load_signals(panel)
    mdf, preds = rolling_models(sig)
    mdf.drop(columns=["_coefs", "_cm"]).to_csv(HERE / "model_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"\n模型指标落盘 model_metrics.csv（{len(mdf)} 个模型）")

    lab = sig.dropna(subset=["true_label"]).copy()
    pred_by_idx = preds.set_index("idx")
    lab["model"] = pred_by_idx["model"].reindex(lab.index).values
    lab["score"] = pred_by_idx["score"].reindex(lab.index).values
    tested = lab.dropna(subset=["score"]).copy()
    tested["valid"] = tested["score"] > 0                     # 更新二：OLS 预测收益 > 0 = 有效
    tested["true_valid"] = tested["true_label"].isin(["b", "c"])
    cols = ["date", "symbol", "name", "break_price", "line_val", "dist", "base",
            "min_low_20", "max_high_20", "close_20", "ret_20", "true_label", "score",
            "valid", "model"]
    tested[cols].to_parquet(HERE / "filtered_detail.parquet", index=False)
    tested[cols].to_csv(HERE / "filtered_detail.csv", index=False, encoding="utf-8-sig")

    tested["halfyear"] = tested["date"].dt.year.astype(str) + np.where(tested["date"].dt.month <= 6, "H1", "H2")
    tested["year"] = tested["date"].dt.year

    def agg(df, key):
        g = df.groupby(key).apply(lambda x: pd.Series({
            "信号数": len(x), "保留数": int(x["valid"].sum()),
            "保留率%": round(x["valid"].mean() * 100, 1),
            "保留后成功率%": round(x.loc[x["valid"], "true_valid"].mean() * 100, 1) if x["valid"].any() else np.nan,
            "全量成功率%": round(x["true_valid"].mean() * 100, 1),
            "提升pp": round((x.loc[x["valid"], "true_valid"].mean() - x["true_valid"].mean()) * 100, 1) if x["valid"].any() else np.nan,
        }), include_groups=False).reset_index()
        return g

    sh, sy = agg(tested, "halfyear"), agg(tested, "year")
    ss = agg(tested, ["symbol", "name"]).sort_values("信号数", ascending=False)
    sh.to_csv(HERE / "summary_by_halfyear.csv", index=False, encoding="utf-8-sig")
    sy.to_csv(HERE / "summary_by_year.csv", index=False, encoding="utf-8-sig")
    ss.to_csv(HERE / "summary_by_symbol.csv", index=False, encoding="utf-8-sig")

    kv = int(tested["valid"].sum())
    print(f"\n=== 过滤总效果（{len(mdf)} 模型，{tested['date'].min().date()}~{tested['date'].max().date()}）===")
    print(f"测试期信号 {len(tested)} | 模型保留 {kv}（{kv/len(tested)*100:.1f}%）| "
          f"保留后成功率 {tested.loc[tested['valid'],'true_valid'].mean()*100:.1f}% vs 全量 {tested['true_valid'].mean()*100:.1f}% "
          f"（+{(tested.loc[tested['valid'],'true_valid'].mean()-tested['true_valid'].mean())*100:.1f}pp）")
    print("\n=== 半年度 ===")
    print(sh.to_string(index=False))
    _viz(mdf, sh, ss)


def _viz(mdf, sh, ss):
    sys.path.insert(0, str(PROJ.parents[2] / ".claude" / "skills" / "skill-research-assistant" / "scripts"))
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    figs = {}
    f1 = go.Figure()
    f1.add_trace(go.Scatter(x=mdf["model"], y=mdf["test_acc_sign"] * 100, name="符号准确率%",
                            mode="lines+markers"))
    f1.add_trace(go.Scatter(x=mdf["model"], y=mdf["test_corr_ret20"], name="score与实际20日收益相关",
                            mode="lines+markers"))
    f1.update_layout(title="各模型指标（OLS，半年一滚 2018H2~2026H2；符号准确率=socre>0 与真实有效的吻合度）",
                     height=420)
    figs["metrics"] = f1

    f2 = make_subplots(specs=[[{"secondary_y": True}]])
    f2.add_trace(go.Bar(x=sh["halfyear"], y=sh["保留数"], name="保留信号", marker_color="#27ae60"), 1, 1)
    f2.add_trace(go.Bar(x=sh["halfyear"], y=sh["信号数"] - sh["保留数"], name="过滤掉", marker_color="#e74c3c"), 1, 1)
    f2.add_trace(go.Scatter(x=sh["halfyear"], y=sh["保留后成功率%"], name="保留后成功率%", mode="lines+markers",
                            line=dict(color="#8e44ad", width=2.5)), secondary_y=True)
    f2.add_trace(go.Scatter(x=sh["halfyear"], y=sh["全量成功率%"], name="全量成功率%", mode="lines",
                            line=dict(color="#7f8c8d", dash="dot", width=2)), secondary_y=True)
    f2.update_layout(barmode="stack", title="过滤效果：保留/过滤信号量 + 成功率（紫=保留后，灰虚=不过滤）", height=460)
    f2.update_yaxes(title_text="信号数", secondary_y=False)
    f2.update_yaxes(title_text="成功率%", secondary_y=True, range=[0, 100])
    figs["filter"] = f2

    # 更新二：4 特征系数随时间变化（符号稳定性 = 逻辑是否成立的核心读数）
    f3 = go.Figure()
    for feat in FEATS4:
        f3.add_trace(go.Scatter(x=mdf["model"], y=[r["_coefs"][feat] for _, r in mdf.iterrows()],
                                name=feat, mode="lines+markers"))
    f3.add_hline(y=0, line_dash="dot", line_color="#7f8c8d")
    f3.update_layout(title="OLS 系数逐模型变化（符号稳定性：TurnDecay 预期负=换手衰减好；"
                           "AmtDecay 预期正=量增好；PricePctile60 预期负=低位突破好）", height=460)
    figs["coefs"] = f3

    cm = mdf["_cm"].sum(axis=0)
    f4 = go.Figure(go.Heatmap(z=cm, x=["预测无效", "预测有效"], y=["实际无效(a)", "实际有效(b/c)"],
                              colorscale="Blues", text=cm, texttemplate="%{text}"))
    f4.update_layout(title="混叠矩阵（全部模型 test 期合计，score>0=预测有效）", height=380)
    figs["cm"] = f4

    parts = [f.to_html(full_html=False, include_plotlyjs=(i == 0), div_id=f"fig_{k}")
             for i, (k, f) in enumerate(figs.items())]
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_005 — 特征过滤 v2.7 突破</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}</style>
</head><body>
<h1>analysis_005 — 更新二：4 逻辑特征 OLS 过滤 v2.7 突破信号</h1>
<p>OLS 线性回归：y=20日前瞻收益%；特征=换手率衰减/成交额变化/波动率变化/价格60日分位（4个）；
滚动：训1年/测半年，模型有效期半年（2018H2~2026H2）。预测收益 score &gt; 0 判有效保留，否则丢弃。</p>
{''.join(parts)}
</body></html>"""
    (HERE / "result_view.html").write_text(body, encoding="utf-8")
    print(f"Saved: {HERE / 'result_view.html'}")


if __name__ == "__main__":
    main()
