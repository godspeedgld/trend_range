"""建指标目录 `factor_catalog` —— cs-trend-train「指标辅助」功能的唯一指标注册表。

一个指标 = 一行。前端弹窗（筛选/搜索/多选/名称公式解释用途）与后端取数（当前值/横截面排名）
都只认这张表；二期加复合指标/行业指标时**只往表里加行**，前后端零改动。

字段：
  id          唯一标识（日频基础 d_*；周频因子 = v_factor_1w 列名；占位 c_*/i_*）
  name        名称（弹窗主标题）
  formula     公式
  explain     解释（值是什么意思）
  purpose     用途（怎么用——按 base 手写，不用库里的模板套话）
  category    分类（基础/趋势/动量/突破/反转/通道/量能/量价/排序/分布/流动性/复合/行业）
  freq        频率（日 | 周）
  type        类型（个股 | 行业 | 复合）
  status      ok | 待建（占位行灰显）
  kind        取数方式：daily（stock_bar1d 现算 expr）/ factor（v_factor_1w|1d 的列）
  table       kind=factor 时读哪张宽表（v_factor_1w 周频 / v_factor_1d 日频）；否则空
  expr        kind=daily 时的 SQL 表达式（窗口函数按 instrument 分区）
  column      kind=weekly 时的列名
  lookback    daily 窗口表达式的回看天数（保证窗口满）
  threshold   阈值说明（可空；有则前端提示）
  dis_em      ★显示倍率 display_em（默认 1；**纯显示**，不改存储值/因子值）。用户 2026-10-14 指定：
              形态四件套（dual_ema_gap_10w_compress / range_ratio_10w_rank /
              breakout_10w_confirm_volume / volume_ratio_5w_rank）×100 —— 值域太小读起来全是小数点后两三位，
              ×100 后分别读作「乖离百分点 / 分位百分点 / 突破×量能放大 / 量比分位百分点」

用法：python build_factor_catalog.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILLS = REPO / ".claude/skills"
LIBS = {
    "dir": SKILLS / "skill-quant-factor-directional-alpha-main",
    "volstat": SKILLS / "skill-quant-factor-volume-stat-alpha-main",
}
OUT = HERE / "factor_catalog.parquet"

# ── 21 个 base 的 解释 / 用途（手写，不抄库里的 rationale 模板套话）──
BASE_TXT = {
    "return":         ("最近 N 周的累计收益率", "动量/趋势度量：高=近期涨得多；反转框架取低值"),
    "skip_return":    ("跳过近 N 周的累计收益率", "中期动量，剔除最近 N 周的短期反转影响"),
    "reversal":       ("N 周收益率的负值", "超跌度量：值越大=近期跌得越深 —— 反转框架的核心排序量"),
    "sma_gap":        ("收盘价相对 N 周均线的偏离幅度", "价格乖离：正=站在均线上方；绝对值大=偏离趋势远"),
    "ema_gap":        ("收盘价相对 N 周 EMA 的偏离", "更灵敏的乖离度量（EMA 对近期价格权重高）"),
    "dual_ema_gap":   ("快慢 EMA 之差占价格比例", "趋势方向经典度量（MACD 思想）：正且增大=多头趋势强化"),
    "sma_slope":      ("N 周均线的归一化斜率", "趋势方向与陡峭度：正=上升趋势且在加陡"),
    "range_position": ("收盘价在 N 周高低区间中的位置（−0.5~0.5）", "通道位置：+0.5=贴区间顶 / −0.5=贴区间底"),
    "breakout":       ("收盘价超过前 N 周最高价的幅度", "创新高强度：正=已突破前高 —— 突破框架核心"),
    "breakdown":      ("收盘价跌破前 N 周最低价的深度", "创新低强度：正=已破位 —— 超卖反弹框架核心"),
    "trend_strength": ("N 周净涨跌幅 ÷ 同期波动", "单位风险的净趋势（类信息比率）：高=涨得稳"),
    "efficiency":     ("净位移 ÷ 路径总长（0~1）", "趋势效率：接近 1=单边流畅，接近 0=来回震荡"),
    "volume_ratio":   ("当前成交量 ÷ N 周均量 − 1", "量能放大/萎缩：正=放量；巨量区（RV 高位）失败率高（analysis_014）"),
    "volume_z":       ("成交量的时序 z-score", "量能异常度：|z| 大=量偏离自身常态远"),
    "dollar_volume":  ("成交额相对 N 周均额 − 1", "金额口径的活跃度变化（含价格权重）"),
    "price_volume_corr": ("收益率与量变化率的 N 周滚动相关", "量价配合度：正=量价同向（配合），负=背离"),
    "obv_slope":      ("OBV（能量潮）的 N 周斜率 ÷ 均量", "资金流向净趋势：正=资金持续流入"),
    "ts_rank_close":  ("收盘价在自身 N 周历史中的分位", "价格冷热：高=创阶段新高，低=阶段新低"),
    "ts_rank_volume": ("成交量在自身 N 周历史中的分位", "量能冷热：高=近期量处于自身历史高位"),
    "ret_skew":       ("N 周收益分布的偏度", "尾部分向：负=左尾（暴跌多），正=右尾（暴涨多）"),
    "ret_kurt":       ("N 周收益分布的峰度", "极端收益频率：高=肥尾（彩票型标的）"),
}
# 变换后缀（拼进 解释）
TR_TXT = {
    "z": "；按自身 20 周历史标准化（看偏离常态多远）",
    "delta": "；取相对前期的变化量（看边际变化）",
    "smooth": "；3 周指数平滑去噪（看趋势不看毛刺）",
    "rank": "；转为自身历史分位（0~1，看冷热）",
    "vol_scaled": "；按收益波动归一（同波动下比较）",
    "stability": "；除以信号自身波动（越稳越可信）",
    "confirm_volume": "；乘量比做量能确认（放量放大 / 缩量压低）",
    "compress": "；tanh 压缩到 (−1,1)（压制极端值）",
}
CAT_MAP = {"Momentum": "动量", "Reversal": "反转", "Trend": "趋势",
           "Breakout": "突破", "Channel": "通道"}

# ── 日频基础指标（stock_bar1d 现算；kind=daily）──
DAILY = [
    dict(id="d_turn", name="换手率(当日)", formula="turn", category="基础",
         explain="当日换手率（成交股数÷流通股本）",
         purpose="关注度与流动性：高=交易拥挤；本工程多次验证其为负向因子（低换手占优）",
         expr="turn", lookback=5),
    dict(id="d_amount", name="成交额(亿元)", formula="amount / 1e8", category="基础",
         explain="当日成交金额", purpose="绝对活跃度；低成交额有流动性溢价但容量受限",
         expr="amount/1e8", lookback=5),
    dict(id="d_amp", name="日振幅%", formula="(high − low) / pre_close × 100", category="基础",
         explain="当日高低价差占昨收比例", purpose="日内波动强度：大振幅=分歧大",
         expr="(high-low)/nullif(pre_close,0)*100", lookback=5),
    dict(id="d_turn_ma5", name="5日平均换手率%", formula="avg(turn, 5日)", category="基础",
         explain="近 5 个交易日换手率均值", purpose="短期关注度水平（比当日更稳）",
         expr="avg(turn) over (partition by instrument order by date "
              "rows between 4 preceding and current row)", lookback=15),
    dict(id="d_turn_ratio", name="换手比(5日/60日)", formula="avg(turn,5) / avg(turn,60)",
         category="基础", explain="短期换手相对长期水平的倍数",
         purpose="关注度升温/降温：>1 升温、<1 降温（strategy 基线四因子之一）",
         expr="avg(turn) over (partition by instrument order by date "
              "rows between 4 preceding and current row) / "
              "(avg(turn) over (partition by instrument order by date "
              "rows between 59 preceding and current row) + 1e-8)", lookback=120),
]
# ── ★ 扩展因子（2026-10-14）：库 factor.py 实现了 33 个 base，512 个 SPEC 只用了 21 个；
#    剩下 12 个代码在、没因子 —— SPEC 由 build_factor_ext_specs.py 生成，专为**形态分析**补的。──
EXT_SPECS = HERE / "factor_specs_ext.json"
EXT_CAT = {"upper_wick": "形态", "lower_wick": "形态", "intraday": "形态", "gap_sum": "形态",
           "range_ratio": "形态", "atr_ratio": "波动", "realized_vol": "波动",
           "downside_vol": "波动", "rsi": "超买超卖", "rsi_reversal": "超买超卖",
           "stoch": "超买超卖", "drawdown": "通道"}
EXT_TXT = {
    "upper_wick":  ("近 N 期平均「上影 ÷ 全幅」",
                    "★假突破指纹：突破日冲高回落 → 上影长。配合 breakout 看 —— 突破强但上影也长 = 大概率假突破"),
    "lower_wick":  ("近 N 期平均「下影 ÷ 全幅」",
                    "★破底翻指纹：砸下去被拉回 → 下影长。配合 breakdown 看 —— 破位但下影长 = 可能是破底翻"),
    "intraday":    ("近 N 期平均（收/开 − 1）",
                    "日内强弱：突破日**收在高位**（正值大）才健康；收在低位=冲高回落"),
    "gap_sum":     ("近 N 期跳空（开/昨收 − 1）累计",
                    "跳空突破的**持续性**：连续跳空/跳空不补 = 强；跳空当天就补 = 弱"),
    "range_ratio": ("近 N 期平均（高−低)/收",
                    "**收敛程度**：越小越像三角形/平台整理 —— 突破前的地基"),
    "atr_ratio":   ("ATR(N) / 收",
                    "波动率水平：定止损距离（ATR 倍数止损的输入）；波动骤降=变盘前夜"),
    "realized_vol": ("近 N 期收益标准差",
                     "波动率水平（同上，更常规的口径）"),
    "downside_vol": ("只算跌日的收益标准差",
                     "**下行风险**：破位时若下行波动激增 = 真跌；平缓 = 可能是洗盘"),
    "rsi":          ("N 期 RSI − 0.5",
                     "超买超卖：突破时 RSI 已很高 = 追高衰竭；破底时 RSI 极低 = 超卖"),
    "rsi_reversal": ("0.5 − N 期 RSI（反向）",
                     "同上取反（买入方向：值大=超卖）"),
    "stoch":        ("收盘在 N 期高低区间的位置 − 0.5",
                     "KD 的 K：+0.5=贴区间顶 / −0.5=贴底"),
    "drawdown":     ("收 / N 期最高 − 1",
                     "距区间高点多远：**破底翻**要看它是否已从深坑里爬起来"),
}

# ── ★ 打分复因子（2026-10-14 定稿）：`factor_score_1d` —— 4 分项 + 总分 ──
#    由 build_factor_score.py 生成。目录只登记 total（副图画这一条）；4 个分项留在表里。
#    ★曾有 quality = foundation.where(s_break>0) 一版 —— 已按用户裁决删除：
#      把库的「突破」定义（今收>前10日最高）强加给使用者 = 用未来/口径信息构造因子。
#      突破日由使用者自己判断，表只提供分数。
SCORE_TXT = {
    "total": ("总分 = 均线粘合(0~2) + 振幅收敛(0~2) + 突破×量能(0~2) + 非巨量(0~2) 四项直接加总。"
              "读法：高 = 平静收敛 + 有突破 + 不巨量。⚠ 四项与未来收益方向**不一致**（突破项 IC 为负、"
              "地基项为正），相加互相抵消 ⇒ 当**多空观察索引**用，别当因子信号；要拆开看用表里的 "
              "s_glue/s_converge/s_break/s_volume 四列"),
}

# ── 二期占位（弹窗可见、灰显「待建」）──
PLACEHOLDER = [
    dict(id="c_baseline4", name="基线四因子复合分", type="复合", freq="周", category="复合",
         formula="mean(rank_pct(−turn_ratio, −px_ma20, −mom_20, −liq_amount))",
         explain="strategy_002 基线选股打分（行业内百分位等权平均）",
         purpose="买弱框架的复合排序；二期建独立表 factor_composite_1w"),
    dict(id="i_bp", name="变盘指数 T′", type="行业", freq="日", category="行业",
         formula="行业排名迁移幅度的滚动波动（银河口径，二阶量）",
         explain="T′<0 动量期 / T′>0 反转期", purpose="行业轮动 regime 开关；二期建表"),
]


def main() -> int:
    rows = []
    for d in DAILY:
        rows.append({**d, "freq": "日", "type": "个股", "status": "ok", "kind": "daily",
                     "column": None, "threshold": None, "table": None})
    # ★ 同一批 512 个因子出**两套**：周频（v_factor_1w，窗口=周）与日频（v_factor_1d，窗口=交易日）。
    #   列名/结构完全相同（都是 <base>_<W>w_<transform>），差别只在喂给库的行集 ⇒ 频率不同。
    #   id 加频率后缀保证唯一；name 也带后缀，否则已选 chips 里两个同名看不出谁是谁。
    for lib, root in LIBS.items():
        idx = json.loads((root / "factor_index.json").read_text(encoding="utf-8"))
        for f in idx:
            w = int(f["params"]["window"])
            col = f"{f['base']}_{w}w_{f['transform']}"
            base_exp, purpose = BASE_TXT[f["base"]]
            cat = CAT_MAP.get(f.get("category_en", ""), None) or f.get("category_cn", "其他")
            if lib == "volstat":
                cat = f.get("category_cn", "量能")
            for tag, tbl, zh in (("", "v_factor_1w", "周"), ("__1d", "v_factor_1d", "日")):
                rows.append({
                    "id": col + tag, "name": f"{f['name_cn']}（{zh}）",
                    "formula": f["formula_cn"] + ("  [窗口按周]" if zh == "周" else "  [窗口按交易日]"),
                    "explain": base_exp + TR_TXT.get(f["transform"], ""),
                    "purpose": purpose, "category": cat, "freq": zh, "type": "个股",
                    "status": "ok", "kind": "factor", "column": col, "expr": None,
                    "lookback": None, "threshold": None, "table": tbl,
                })
    # ★ 扩展因子：12 个未出厂 base，SPEC 来自 build_factor_ext_specs.py（周/日各一套）
    ext = json.loads(EXT_SPECS.read_text(encoding="utf-8"))["specs"]
    for f in ext:
        w = int(f["params"]["window"])
        col = f"{f['base']}_{w}w_{f['transform']}"
        exp, purpose = EXT_TXT[f["base"]]
        for tag, tbl, zh in (("", "factor_ext_1w", "周"), ("__1d", "factor_ext_1d", "日")):
            rows.append({
                "id": col + tag, "name": f"{f['name_cn']}（{zh}）",
                "formula": f["formula_cn"] + ("  [窗口按周]" if zh == "周" else "  [窗口按交易日]"),
                "explain": exp, "purpose": purpose, "category": EXT_CAT[f["base"]],
                "freq": zh, "type": "个股", "status": "ok", "kind": "factor",
                "column": col, "expr": None, "lookback": None, "threshold": None,
                "table": tbl,
            })

    # ★ 打分复因子：只登记 total（副图画这一条；分项在表里）
    for col, txt in SCORE_TXT.items():
        rows.append({
            "id": f"score_{col}",
            "name": "形态辅助总分 0~8",
            "formula": "s_glue + s_converge + s_break + s_volume（各 0~2）",
            "explain": txt, "purpose": "形态分析的多空观察索引（副图画这一条）",
            "category": "复合", "freq": "日", "type": "复合", "status": "ok",
            "kind": "factor", "column": col, "expr": None, "lookback": None,
            "threshold": None, "table": "factor_score_1d",
        })

    for p in PLACEHOLDER:
        rows.append({**p, "status": "待建", "kind": None, "column": None,
                     "expr": None, "lookback": None, "threshold": None, "table": None})
    # ★★ 显示倍率 dis_em：统一后处理（默认 1）—— 放在 DataFrame 之前，保证每行都有该列，
    #    避免某个 append 块漏带 → NaN（NaN 不会被子进程/服务端兜底成 1，会把显示值全变 NaN）
    DIS100 = {"dual_ema_gap_5w_compress", "dual_ema_gap_7w_compress", "dual_ema_gap_10w_compress",
              "range_ratio_10w_rank", "breakout_10w_confirm_volume", "volume_ratio_5w_rank"}
    # ★ 副图截尾 disp_clip（纯显示，仅作用于副图序列；当前值/排名不截）：compress 家族日常 ±3
    #   但全历史可达 ±13（2015 股灾等），Y 轴被极端日撑开 → 日常波动被压扁、0 不居中（轴不对称）。
    #   钳到 ±5（P99=4.1）→ 轴对称、0 居中；极端日照常可见（顶到边界）
    DISCLIP = {"dual_ema_gap_5w_compress", "dual_ema_gap_7w_compress", "dual_ema_gap_10w_compress"}
    for row in rows:
        row["dis_em"] = 100 if row.get("column") in DIS100 else 1
        row["disp_clip"] = 5 if row.get("column") in DISCLIP else 0   # ★ 0=不截（数值列，勿用 None ——
        #   parquet 读回 None 会变 NaN，而 `float(nan) if nan else None` 不会兜底 → c=nan 毒化全部值）
        if row["dis_em"] != 1:
            row["formula"] += "  [显示×100]"
        if row.get("disp_clip"):
            row["formula"] += f"  [副图±{row['disp_clip']}截尾]"

    df = pd.DataFrame(rows)
    dup = df["id"].duplicated().sum()
    assert dup == 0, f"id 重复 {dup}"
    df.to_parquet(OUT, index=False)
    con = duckdb.connect(str(HERE / "bigquant_warehouse.duckdb"))
    con.execute(f"CREATE OR REPLACE VIEW factor_catalog AS SELECT * FROM read_parquet("
                f"'{OUT.resolve().as_posix()}')")
    n = con.execute("SELECT count(*) FROM factor_catalog").fetchone()[0]
    con.close()
    print(f"factor_catalog：{n} 行（日频基础 {len(DAILY)} + 因子库 "
          f"{n - len(DAILY) - len(PLACEHOLDER)}（周/日各半）+ 占位 {len(PLACEHOLDER)}）")
    print(df.groupby(["type", "freq", "status"]).size().to_string())
    print("\n样例：")
    print(df[df.id.isin(["d_turn", "breakdown_5w_smooth", "c_baseline4"])][
        ["id", "name", "category", "freq", "type", "status"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
