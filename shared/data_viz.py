"""shared.data_viz — 数据可视化工具。

从 ``data_cache/returns.db`` 的各周期收益率表读取数据，画折线图，输出 HTML 到
``results/``。跨策略复用（趋势 / 震荡 / 综合）。

周期表名约定与 ``trend_following.check_trend_valid.return_tables`` 一致：
    mon → mon_return / 1d → 1d_return / 1h → 1h_return / 30m → 30m_return
"""

import re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

# 项目根（shared 的上一级），保证路径与 CWD 无关
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RETURNS_DB = PROJECT_ROOT / "data_cache" / "returns.db"
RESULTS_DIR = PROJECT_ROOT / "results"

# period → 收益率表名
_PERIOD_TABLE = {
    "mon": "mon_return",
    "1d": "1d_return",
    "1h": "1h_return",
    "30m": "30m_return",
}

# feature → 中文显示名
_FEATURE_LABEL = {
    "log_return": "对数收益率",
}

# 统计特征 → 中文显示名（return_stats 表）
_STAT_LABEL = {
    "count": "样本数", "mean": "均值", "std": "标准差",
    "min": "最小值", "q25": "25%分位", "q50": "中位数", "q75": "75%分位", "max": "最大值",
    "skew": "偏度", "kurt": "峰度(超额)",
}

# 柱状图参考线：特征 → 标准值（偏度/峰度/均值 以 0 为基准；标准差不画）
_REF_LINE = {"skew": 0.0, "kurt": 0.0, "mean": 0.0}

# 统计特征表名（与 trend_following.check_trend_valid.STATS_TABLE 一致）
STATS_TABLE = "return_stats"


def plot_feature(symbol, start_date=None, end_date=None, feature="log_return", period="1d"):
    """读取 symbol 在指定 period 表里的 feature，画折线，输出 HTML 到 results/。

    Args:
        symbol:     品种代码，如 "rb"
        start_date: 开始日期 "YYYY-MM-DD"（含），可选
        end_date:   结束日期 "YYYY-MM-DD"（含），可选
        feature:    要画的列，目前表里只有 "log_return"
        period:     "mon" / "1d" / "1h" / "30m" → 对应表

    Returns:
        生成的 HTML 文件路径；无数据返回 None。
    """
    if period not in _PERIOD_TABLE:
        raise ValueError(f"period 仅支持 {list(_PERIOD_TABLE)}，收到 {period!r}")
    # feature 作为列名拼进 SQL，做安全标识符校验防注入
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(feature)):
        raise ValueError(f"feature 不是合法列名: {feature!r}")

    table = _PERIOD_TABLE[period]

    if not RETURNS_DB.exists():
        print(f"[data_viz] 收益率库不存在: {RETURNS_DB}，请先运行 calc_log_return")
        return None

    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        sql = f'SELECT datetime, "{feature}" FROM "{table}" WHERE symbol = ?'
        params = [symbol]
        if start_date:
            sql += " AND datetime >= ?"
            params.append(f"{start_date} 00:00:00")
        if end_date:
            sql += " AND datetime <= ?"
            params.append(f"{end_date} 23:59:59")
        sql += " ORDER BY datetime"
        df = pd.read_sql(sql, conn, params=params)
    except sqlite3.OperationalError as e:
        print(f"[data_viz] 读取失败（表/列可能不存在）: {e}")
        return None
    finally:
        conn.close()

    if df.empty:
        print(f"[data_viz] {symbol} {period} {feature} 无数据，请先 calc_log_result")
        return None

    df["datetime"] = pd.to_datetime(df["datetime"])
    label = _FEATURE_LABEL.get(feature, feature)
    title = f"{symbol} · {period} · {label}"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["datetime"], y=df[feature], mode="lines", name=label))
    fig.update_layout(
        title=title,
        xaxis_title="时间",
        yaxis_title=label,
        template="plotly_white",
        hovermode="x unified",
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{symbol}_{period}_{feature}.html"
    fig.write_html(str(out))
    print(f"[data_viz] 已输出: {out}  ({len(df)} 点, {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]})")
    return out


def plot_stats_table(period="1d"):
    """读取 return_stats，输出可点击表头排序的统计特征表格 HTML。

    点击任意列标题即可按该列升降序切换（数值列按数值，文本列按字典序）。

    Args:
        period: "1d" / "week" / "mon"

    Returns:
        生成的 HTML 文件路径；无数据返回 None。
    """
    if not RETURNS_DB.exists():
        print(f"[data_viz] 收益率库不存在: {RETURNS_DB}")
        return None
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        df = pd.read_sql(f'SELECT * FROM "{STATS_TABLE}" WHERE period = ?', conn, params=(period,))
    finally:
        conn.close()
    if df.empty:
        print(f"[data_viz] {STATS_TABLE} 无 {period} 数据，请先 calc_return_stats")
        return None

    df = df.sort_values("symbol").reset_index(drop=True)
    text_cols = ["symbol", "category", "start_date", "end_date"]
    stat_cols = ["count", "mean", "std", "min", "q25", "q50", "q75", "max", "skew", "kurt"]
    cols = text_cols + stat_cols
    labels = {
        "symbol": "symbol", "category": "板块", "start_date": "起", "end_date": "止",
        **_STAT_LABEL,
    }

    def fmt(v, c):
        if pd.isna(v):
            return ""
        if c == "count":
            return str(int(v))
        if c in ("skew", "kurt"):
            return f"{v:.4f}"
        if c in stat_cols:
            return f"{v:.6f}"
        return str(v)

    # 表头
    thead = "".join(
        f'<th onclick="sortTable({i})" title="点击排序">{labels[c]}</th>'
        for i, c in enumerate(cols)
    )
    # 表体（数值列 data-val 存原始数值，供排序用）
    tbody = ""
    for _, row in df.iterrows():
        tds = []
        for c in cols:
            raw = row[c]
            disp = fmt(raw, c)
            if c in stat_cols and not pd.isna(raw):
                tds.append(f'<td data-val="{raw}">{disp}</td>')
            else:
                tds.append(f'<td data-val="{disp}">{disp}</td>')
        tbody += "<tr>" + "".join(tds) + "</tr>\n"

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{period} 收益率统计特征</title>
<style>
  body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 20px; }}
  h2 {{ color: #333; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid #ccc; padding: 5px 8px; text-align: center; white-space: nowrap; }}
  th {{ background: #afeeee; cursor: pointer; user-select: none; position: sticky; top: 0; }}
  th:hover {{ background: #8deeee; }}
  tr:nth-child(even) {{ background: #f7fafa; }}
  .arrow::after {{ content: ""; }}
</style></head>
<body>
<h2>{period} 收益率统计特征（共 {len(df)} 个品种，点击表头排序）</h2>
<table id="statTable">
<thead><tr>{thead}</tr></thead>
<tbody>{tbody}</tbody>
</table>
<script>
let lastCol = -1, asc = true;
function sortTable(col) {{
  const tbl = document.getElementById("statTable");
  const rows = Array.from(tbl.tBodies[0].rows);
  asc = (col === lastCol) ? !asc : true;
  lastCol = col;
  rows.sort((a, b) => {{
    const x = a.cells[col].getAttribute("data-val");
    const y = b.cells[col].getAttribute("data-val");
    const xn = parseFloat(x), yn = parseFloat(y);
    let cmp;
    if (!isNaN(xn) && !isNaN(yn)) cmp = xn - yn;
    else cmp = String(x).localeCompare(String(y), "zh");
    return asc ? cmp : -cmp;
  }});
  rows.forEach(r => tbl.tBodies[0].appendChild(r));
}}
</script>
</body></html>"""

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"stats_table_{period}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[data_viz] 已输出: {out}  ({len(df)} 个品种，表头可点击排序)")
    return out


def plot_stats_bar(period="1d", feature="std"):
    """读取 return_stats，画某统计特征的柱状图（横轴=品种，纵轴=特征值），输出 HTML。

    偏度 / 峰度 / 均值 会在 y=0 处画红色虚线参考；标准差不画参考线。

    Args:
        period:  "1d" / "week" / "mon"
        feature: "std" / "skew" / "kurt" / "mean" / ...

    Returns:
        生成的 HTML 文件路径；无数据返回 None。
    """
    if not RETURNS_DB.exists():
        print(f"[data_viz] 收益率库不存在: {RETURNS_DB}")
        return None
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(feature)):
        raise ValueError(f"feature 不是合法列名: {feature!r}")

    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        df = pd.read_sql(f'SELECT symbol, "{feature}" FROM "{STATS_TABLE}" WHERE period = ?',
                         conn, params=(period,))
    except sqlite3.OperationalError as e:
        print(f"[data_viz] 读取失败: {e}")
        return None
    finally:
        conn.close()
    if df.empty:
        print(f"[data_viz] {STATS_TABLE} 无 {period} 数据，请先 calc_return_stats")
        return None

    df = df.sort_values(feature, ascending=False).reset_index(drop=True)
    label = _STAT_LABEL.get(feature, feature)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["symbol"], y=df[feature], name=label,
                         marker_color="steelblue"))
    if feature in _REF_LINE:
        fig.add_hline(y=_REF_LINE[feature], line_dash="dash", line_color="red",
                      annotation_text=f"参考线 y={_REF_LINE[feature]}",
                      annotation_position="top left")
    fig.update_layout(
        title=f"{period} · {label}",
        xaxis_title="品种", yaxis_title=label,
        template="plotly_white",
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"stats_{period}_{feature}.html"
    fig.write_html(str(out))
    print(f"[data_viz] 已输出: {out}  ({len(df)} 个品种)")
    return out


def plot_stats_box(period="1d", feature="kurt"):
    """读取 return_stats，按板块分组画箱线图（横轴=板块，纵轴=特征值），输出 HTML。

    每个板块一个箱体，展示该板块内各品种该特征的中位数 / 25%-75% 分位 / min-max
    须线及离群点。偏度/峰度/均值 会在 y=0 画红色虚线参考。

    Args:
        period:  "1d" / "week" / "mon"
        feature: "std"(波动率) / "skew"(偏度) / "kurt"(峰度) / "mean" / ...

    Returns:
        生成的 HTML 文件路径；无数据返回 None。
    """
    if not RETURNS_DB.exists():
        print(f"[data_viz] 收益率库不存在: {RETURNS_DB}")
        return None
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(feature)):
        raise ValueError(f"feature 不是合法列名: {feature!r}")

    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        df = pd.read_sql(f'SELECT category, symbol, "{feature}" FROM "{STATS_TABLE}" WHERE period = ?',
                         conn, params=(period,))
    except sqlite3.OperationalError as e:
        print(f"[data_viz] 读取失败: {e}")
        return None
    finally:
        conn.close()
    if df.empty:
        print(f"[data_viz] {STATS_TABLE} 无 {period} 数据，请先 calc_return_stats")
        return None

    df = df.dropna(subset=[feature])
    # 按板块中位数排序（中位数大的在右），便于横向比较
    order = (df.groupby("category")[feature].median()
             .sort_values(ascending=False).index.tolist())
    label = _STAT_LABEL.get(feature, feature)

    fig = go.Figure()
    for cat in order:
        g = df[df["category"] == cat][feature]
        fig.add_trace(go.Box(
            y=g, name=f"{cat}({len(g)})",
            boxpoints="outliers",  # 显示离群点
            boxmean=False,
            marker_color="steelblue", line_color="navy",
            width=0.6,            # 箱体加宽（默认 ~0.3）
            jitter=0.3, pointpos=0,
        ))
    if feature in _REF_LINE:
        fig.add_hline(y=_REF_LINE[feature], line_dash="dash", line_color="red",
                      annotation_text=f"参考线 y={_REF_LINE[feature]}",
                      annotation_position="top left")
    fig.update_layout(
        title=f"{period} · {label}（按板块）",
        xaxis_title="板块(品种数)", yaxis_title=label,
        template="plotly_white", showlegend=False,
        boxmode="group",        # 单 trace/类别，避免偏移；boxgap 控制类间距
        boxgroupgap=0.1, boxgap=0.25,
        xaxis=dict(tickangle=0),  # 类别标签水平，和箱体一一正对
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"stats_{period}_{feature}_box.html"
    fig.write_html(str(out))
    print(f"[data_viz] 已输出: {out}  ({len(order)} 个板块)")
    return out


def plot_tsmom_tstat(period="1d", minh=1, maxh=60, steph=1):
    """扫描 h，画 TSMOM 面板回归的 t 统计量柱状图，输出 HTML。

    对 h = minh, minh+steph, ..., maxh 逐个调用
    ``trend_following.check_trend_valid.tsmom_regression(period, h)``，收集返回的
    t 统计量，画柱状图（横轴=h，纵轴=t），并标 ±2 显著性参考线。

    Args:
        period: "1d" / "week" / "mon"
        minh:   起始 h（含）
        maxh:   结束 h（含）
        steph:  步长

    Returns:
        生成的 HTML 文件路径。
    """
    from trend_following.check_trend_valid import tsmom_regression

    hs = list(range(minh, maxh + 1, steph))
    ts = []
    import contextlib, io
    for h in hs:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):       # 屏蔽逐行打印
            t = tsmom_regression(period=period, h=h)
        ts.append(float(t) if t is not None and not pd.isna(t) else None)

    # 画图（NaN 画为 0 高度但保留位置）
    y = [0 if v is None else v for v in ts]
    colors = ["crimson" if v < 0 else "steelblue" for v in y]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=hs, y=y, marker_color=colors,
                         name="t 统计量", showlegend=False))
    fig.add_hline(y=2, line_dash="dash", line_color="gray",
                  annotation_text="+2 (5%显著)", annotation_position="top left")
    fig.add_hline(y=-2, line_dash="dash", line_color="gray",
                  annotation_text="-2", annotation_position="bottom left")
    fig.add_hline(y=0, line_color="black", line_width=1)
    fig.update_layout(
        title=f"{period} · TSMOM 回归 t 统计量 vs h（{minh}~{maxh} 步{steph}）",
        xaxis_title="滞后阶数 h", yaxis_title="β 的 t 统计量",
        template="plotly_white",
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"tsmom_tstat_{period}_h{minh}-{maxh}.html"
    fig.write_html(str(out))
    valid = sum(1 for v in ts if v is not None)
    print(f"[data_viz] 已输出: {out}  (h {minh}~{maxh} 步{steph}, 有效 {valid}/{len(hs)})")
    return out


if __name__ == "__main__":
    # 自测：统计特征表格 + 柱状图（std/skew/kurt）
    plot_stats_table(period="1d")
    for feat in ("std", "skew", "kurt"):
        plot_stats_bar(period="1d", feature=feat)
