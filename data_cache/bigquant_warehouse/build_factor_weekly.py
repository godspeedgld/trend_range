"""按【指定频率】计算 QuantSkills 两个因子库 → 本地宽表 + 合并视图（BigQuant 仓库）。

产物（Parquet + DuckDB 视图，与既有表同构；`--freq` 决定后缀 1w / 1d）：
  factor_dir_1w|1d/year=YYYY/part-*.parquet        directional 296 因子（宽表）
  factor_volstat_1w|1d/year=YYYY/part-*.parquet    volume-stat  216 因子（宽表）
  v_factor_1w|1d                                   合并视图：两表按 (date, instrument) join → 512 列
列 = date, instrument, <base>_<w>w_<transform> …（**列名/结构两频率完全一致**，只有频率不同）

★ 两个频率的**唯一差别**是喂给库的行集（库按**行数**滚窗口）：
    --freq 1w（默认）：只保留**全局周频信号日**的行（云端 `date IN (信号日)` 下推的效果）
                       ⇒ 窗口 5/7/10 = 5/7/10 **周**
    --freq 1d        ：全部**日线**行（同样只剔停牌）⇒ 窗口 5/7/10 = 5/7/10 **个交易日**

════════════════════ 口径（关键，已与用户确认，别改）════════════════════
① 周频 = **全局**「每周最后一个交易日」的截面快照（`signal_dates(cal)`），**不是把一周的价量聚合**、
   也**不是**逐股取每周最后一行。做法 = 日线先用「日期 ∈ 全局信号日」筛选（复刻云端
   `date IN (信号日)` 被 DAI 下推进 CTE 的效果），再做逐股滚动。
   理由：strategy_001 云端对齐口径实测如此（见 memory: bigquant-handler-pitfalls ⑩）；
   `signal_dates` 逐字复刻 `research-projects/.../shared/build_stock_panel.py::signal_dates`。
   库的窗口按**行数**滚 → 周频行 ⇒ 5/7/10 自动变 5/7/10 **周**。
   ★ 停牌股在信号日没有行（窗口顺延），与策略侧 `df[df["date"].isin(set(sd))]` 一致。
② 价格 = **后复权**：直接用 `stock_bar1d.close`（它**本身已是后复权**，见 memory ②），
   **不**除 `adjust_factor`。与 strategy_001 的 px_ma20/mom_20 口径一致；volume 用原始股数。
   （代价：`dollar_volume` 在窗口内含除权日时有微小扰动——归一化里的常数倍会抵消，只跨除权日的阶跃不抵消。）
③ 落盘 = **原始因子值**（不做去极值/标准化/行业市值中性化；那是下游的事，见 factor_validation_local.py）。
④ 池 = 全市场 .SH/.SZ（含退市股），**不过滤** ST/停牌/上市天数。

════════════════════ 实现要点 ════════════════════
★ 512 个 `factor.py` 的**代码体完全相同**（只有开头 SPEC 不同，已用 md5 断言）⇒ 加载**一个**模块 +
  按 SPEC patch `base`/`transform`/`params` 即可精确复现整个库。**不改动任何库代码。**
★ 同 (base, window, params) 的 base 信号只算一次 → 再套 8 个 transform（分组显式排序，不靠相邻假设）。
★ 流式落盘：每 ~400 只股 flush 一次（避免 2.9M×296 float64 全驻内存）；float32 + zstd。

用法：
  python build_factor_weekly.py --lib both --jobs 6          # 全量（推荐）
  python build_factor_weekly.py --lib dir --symbols 200      # 冒烟
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
# ★ 只“静音”库代码里 Series.pct_change 的 FutureWarning —— **不改变任何计算行为**
#   （pandas 仍按其默认 fill_method='pad' 执行）。不静音的话每次调用都往 stderr 刷一行，拖慢数倍。
warnings.filterwarnings("ignore", category=FutureWarning)
ROOT = Path(__file__).resolve().parent            # data_cache/bigquant_warehouse
REPO = ROOT.parents[1]
DB = ROOT / "bigquant_warehouse.duckdb"
SKILLS = REPO / ".claude/skills"
LIBS = {
    "dir": SKILLS / "skill-quant-factor-directional-alpha-main/factors",
    "volstat": SKILLS / "skill-quant-factor-volume-stat-alpha-main/factors",
}
FREQ = "1w"                                   # 由 --freq 设置：1w（周频快照）| 1d（日频）


def _tbl(lib: str) -> str:
    return f"factor_{lib}_{FREQ}"


def _view() -> str:
    return f"v_factor_{FREQ}"
EXPECT = {"dir": 296, "volstat": 216}
START = "2015-01-01"
END = None                    # None = 库内最新
FLUSH = 400                   # 每 N 只股落一次盘
BARS_COLS = ["open", "high", "low", "close", "volume"]


# ═══════════════════ Step 0：前置断言（"一个模块打天下"的前提）═══════════════════
def assert_single_code_body() -> None:
    """断言 512 个 factor.py 的代码体（SPEC 之后的部分）md5 唯一；否则中止。"""
    bodies: dict[str, list[str]] = {}
    n = 0
    for lib, root in LIBS.items():
        for d in sorted(root.glob("R*")):
            fp = d / "scripts" / "factor.py"
            if not fp.exists():
                continue
            n += 1
            txt = fp.read_text(encoding="utf-8")
            h = hashlib.md5(txt[txt.index("FACTOR_COLUMN"):].encode()).hexdigest()
            bodies.setdefault(h, []).append(f"{lib}/{d.name}")
    if len(bodies) != 1:
        raise SystemExit(f"✗ {n} 个 factor.py 代码体不唯一（{len(bodies)} 种）"
                         "——『一个模块打天下』前提不成立，中止")
    h = next(iter(bodies))
    print(f"✓ Step0 代码体唯一 {h[:12]}…（{n} 个文件）")


def lib_module_path() -> str:
    """库计算模块路径（两库代码同一份，取 dir 的第一个即可）。"""
    return str(next(LIBS["dir"].glob("R*/scripts/factor.py")))


def _load_module(path: str):
    spec = importlib.util.spec_from_file_location("qs_factor_lib", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # 只定义函数 + 读 SPEC，无副作用
    return mod


# ═══════════════════ ① 库 SPEC ═══════════════════
def load_specs(lib: str) -> list[dict]:
    """读该库每个因子目录的 SPEC（base/transform/params）——只读元数据，不跑计算。"""
    specs = []
    for d in sorted(LIBS[lib].glob("R*")):
        fp = d / "scripts" / "factor.py"
        if not fp.exists():
            continue
        mod = _load_module(str(fp))
        s = dict(mod.SPEC)
        s["_dir"] = d.name
        specs.append(s)
    if len(specs) != EXPECT[lib]:
        raise SystemExit(f"✗ {lib} 因子数 {len(specs)} ≠ 预期 {EXPECT[lib]}")
    return specs


def build_combos(specs: list[dict]) -> list[dict]:
    """SPEC → 去重后的计算清单；按 (base, window, params, transform) 排序 → 同组 base 只算一次。"""
    combos, seen = [], set()
    for s in specs:
        p = dict(s["params"])
        w = int(p.get("window", 20))
        key = (s["base"], w, json.dumps(p, sort_keys=True), s["transform"])
        if key in seen:
            continue
        seen.add(key)
        combos.append({"base": s["base"], "window": w, "params": p,
                       "transform": s["transform"], "col": f"{s['base']}_{w}w_{s['transform']}"})
    cols = [c["col"] for c in combos]
    if len(set(cols)) != len(cols):
        raise SystemExit("✗ 列名有重复 —— 命名规则不成立")
    combos.sort(key=lambda c: (c["base"], c["window"],
                               json.dumps(c["params"], sort_keys=True), c["transform"]))
    return combos


# ═══════════════════ ② 日线 → 周频 bar ═══════════════════
def load_calendar() -> pd.Series:
    """真实交易日历（= stock_bar1d 的实际出现日期，见 memory bigquant-handler-pitfalls ①）。
    ★ 不带任何过滤 —— 与 `build_stock_panel_weekly.load_bars` 里 `cal` 的算法一致。"""
    con = duckdb.connect(str(DB), read_only=True)
    d = con.execute("SELECT DISTINCT date FROM stock_bar1d "
                    "WHERE (instrument LIKE '%.SH' OR instrument LIKE '%.SZ') ORDER BY 1").df()["date"]
    con.close()
    return pd.Series(pd.to_datetime(d))


def signal_dates(cal: pd.Series) -> list:
    """每周最后一个交易日（**全局**，非逐股）—— 逐字复刻
    `research-projects/.../shared/build_stock_panel.py::signal_dates`（云端周频口径的来源）。"""
    d = pd.DatetimeIndex(sorted(cal.unique()))
    key = pd.Series(d, index=d).groupby([d.isocalendar().year.values, d.isocalendar().week.values])
    return sorted(pd.DatetimeIndex(key.max().values))


def load_bars(symbols: list[str] | None = None) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    end = END or str(con.execute("SELECT max(date) FROM stock_bar1d").fetchone()[0])[:10]
    where = [f"date >= TIMESTAMP '{START}'", f"date <= TIMESTAMP '{end}'",
             "(instrument LIKE '%.SH' OR instrument LIKE '%.SZ')",
             # ★ 剔停牌行：stock_bar1d 里停牌日 close/amount 为 NULL（volume=0），
             #   与策略侧 build_stock_panel_weekly.py 的 `close.notna() & amount.notna()`
             #   （= 云端 suspended=0）同口径 ⇒ 周频 bar = 当周最后一个**有成交**日
             '"close" IS NOT NULL AND amount IS NOT NULL']
    pushdown = bool(symbols) and len(symbols) <= 2000        # 小样本直接下推，省得读完再筛
    if pushdown:
        lst = ",".join("'" + s.replace("'", "''") + "'" for s in symbols)
        where.append(f"instrument IN ({lst})")
    # ★ 后复权口径：close 原样（stock_bar1d.close 已是后复权），不除 adjust_factor
    df = con.execute("SELECT date, instrument, open, high, low, close, volume FROM stock_bar1d "
                     "WHERE " + " AND ".join(where)).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    if symbols and not pushdown:
        df = df[df["instrument"].isin(symbols)]
    return df.sort_values(["instrument", "date"]).reset_index(drop=True)


def to_freq(bars: pd.DataFrame, sd: list) -> pd.DataFrame:
    """按 FREQ 采样：1d = 原样全部日线行；1w = 只保留全局周频信号日（见 to_weekly）。"""
    if FREQ == "1d":
        return bars.sort_values(["instrument", "date"]).reset_index(drop=True)
    return to_weekly(bars, sd)


def to_weekly(bars: pd.DataFrame, sd: list) -> pd.DataFrame:
    """周频采样：**只保留「日期 ∈ 全局周频信号日」的行**（= 云端 `date IN (信号日)` 的下推效果）。

    ★ 注意不是「逐股取每周最后一行」：逐股取最后一行会让「在信号日停牌的个股」用本周更早的
      交易日顶替（本地实测会多出 300+ 个非信号日日期）；而策略/云端口径是——
      `build_stock_panel_weekly.main`：`p = attach_industry(df[df["date"].isin(set(sd))])`
      ⇒ 停牌股那一周**直接没有行**（窗口顺延到它有行的下一个信号日）。这里照此办理。
    """
    b = bars[bars["date"].isin(set(sd))]
    return b.sort_values(["instrument", "date"]).reset_index(drop=True)


# ═══════════════════ ③ 计算（多进程；子进程一次性初始化模块 + combos）═══════════════════
_G: dict = {}


def _init(libpath: str, combos: list[dict]) -> None:
    """子进程初始化：加载库模块 + 存 combos（只 pickle 一次，不随每只股重复传）。"""
    warnings.filterwarnings("ignore", category=FutureWarning)      # 子进程也要静音
    _G["mod"] = _load_module(libpath)
    _G["combos"] = combos


def _worker(arg):
    """算**一只标的**的全部因子（该 lib 的 combos）。"""
    sym, g = arg
    mod, combos = _G["mod"], _G["combos"]
    g = g.reset_index(drop=True)
    out = {"date": g["date"].to_numpy(), "instrument": np.full(len(g), sym)}
    i, n = 0, len(combos)
    while i < n:
        head = combos[i]
        pj = json.dumps(head["params"], sort_keys=True)
        mod.SPEC["base"] = head["base"]
        mod.SPEC["params"] = head["params"]
        base_sig = mod._base(g)                       # ★ 同 (base,window,params) 只算一次
        j = i
        while (j < n and combos[j]["base"] == head["base"] and combos[j]["window"] == head["window"]
               and json.dumps(combos[j]["params"], sort_keys=True) == pj):
            mod.SPEC["transform"] = combos[j]["transform"]
            out[combos[j]["col"]] = np.asarray(mod._transform(base_sig, g), dtype=float)
            j += 1
        i = j
    return pd.DataFrame(out)


def compute_and_ingest(weekly: pd.DataFrame, specs: list[dict], lib: str, jobs: int) -> dict:
    """逐标的算 → 流式落盘（float32+zstd，按年分区）→ 建基础视图。返回登记信息。"""
    combos = build_combos(specs)
    table = _tbl(lib)
    tdir = ROOT / table
    if tdir.exists():
        if tdir.parent != ROOT:
            raise SystemExit("✗ 拒绝删除仓库外的目录")
        shutil.rmtree(tdir)                            # 清旧分区，避免残留
    print(f"[{lib}] 因子 {len(specs)} → 宽表 {len(combos)} 列 | 表 {table}")

    work = [(sym, g) for sym, g in weekly.groupby("instrument", sort=True)]
    t0, done = time.time(), 0

    def flush(buf: list[pd.DataFrame], idx: int) -> None:
        df = pd.concat(buf, ignore_index=True)
        fcols = [c for c in df.columns if c not in ("date", "instrument")]
        df[fcols] = df[fcols].astype("float32")
        yr = pd.to_datetime(df["date"]).dt.year
        for y, g in df.groupby(yr):
            out = tdir / f"year={int(y)}" / f"part-{idx:05d}.parquet"
            out.parent.mkdir(parents=True, exist_ok=True)
            g.to_parquet(out, index=False, compression="zstd")

    buf, idx = [], 0
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs, initializer=_init,
                                 initargs=(lib_module_path(), combos)) as ex:
            it = ex.map(_worker, work, chunksize=16)
            for k, df in enumerate(it):
                buf.append(df); done += 1
                if len(buf) >= FLUSH:
                    flush(buf, idx); idx += 1; buf = []
                if done % 500 == 0:
                    print(f"    {done:,}/{len(work):,} 只 … {time.time()-t0:.0f}s", flush=True)
    else:
        _init(lib_module_path(), combos)
        for k, w in enumerate(work):
            buf.append(_worker(w)); done += 1
            if len(buf) >= FLUSH:
                flush(buf, idx); idx += 1; buf = []
            if done % 500 == 0:
                print(f"    {done:,}/{len(work):,} 只 … {time.time()-t0:.0f}s", flush=True)
    if buf:
        flush(buf, idx)

    con = duckdb.connect(str(DB))
    con.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_parquet("
                f"'{tdir.resolve().as_posix()}/**/*.parquet', hive_partitioning=true)")
    n = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    con.close()
    print(f"  → {table}: {n:,} 行 × {len(combos)+2} 列（{time.time()-t0:.0f}s）")
    return {"table": table, "rows": n, "factors": len(combos)}


# ═══════════════════ ④ 合并视图 ═══════════════════
def create_combined_view() -> None:
    """v_factor_{FREQ} = dir ⋈ volstat（按 date, instrument）——「一次访问全部 512 个因子」。
    ★ 显式 EXCLUDE 掉 read_parquet 带出的 year 列，避免 join 后重名。"""
    view, td, tv = _view(), _tbl("dir"), _tbl("volstat")
    con = duckdb.connect(str(DB))
    con.execute(f"""
        CREATE OR REPLACE VIEW {view} AS
        SELECT d.* EXCLUDE(year), v.* EXCLUDE(date, instrument, year)
        FROM {td} d JOIN {tv} v USING (date, instrument)
    """)
    r = con.execute(f"SELECT count(*) FROM {view}").fetchone()
    ncol = len(con.execute(f"DESCRIBE {view}").fetchall())
    con.close()
    print(f"  → {view}: {r[0]:,} 行 × {ncol} 列（= 512 因子 + date/instrument）")


# ═══════════════════ ⑤ _meta.json 登记 ═══════════════════
def update_meta(infos: list[dict]) -> None:
    mp = ROOT / "_meta.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m.setdefault("tables", {})
    now = pd.Timestamp.now().isoformat()
    cal = ("周频=全局每周最后交易日快照；窗口 5/7/10 = 周" if FREQ == "1w"
           else "日频=全部日线（仅剔停牌）；窗口 5/7/10 = 交易日")
    for it in infos:
        m["tables"][it["table"]] = {
            "source": "QuantSkills 因子库（directional 296 / volume-stat 216）",
            "kind": f"factor_wide_{FREQ}",
            "primary_key": ["date", "instrument"],
            "rows": it["rows"], "factors": it["factors"],
            "date_column": "date", "partition_keys": ["year"],
            "storage": "parquet/year=YYYY/part-*.parquet (float32, zstd)",
            "caliber": f"{cal}；价格=后复权 stock_bar1d.close；值=原始因子值；池=全市场 .SH/.SZ",
            "built_by": "build_factor_weekly.py --freq " + FREQ, "last_refresh_at": now,
        }
    if {_tbl("dir"), _tbl("volstat")} <= set(m["tables"]):
        m["tables"][_view()] = {
            "kind": "view_combined",
            "source": f"{_tbl('dir')} ⋈ {_tbl('volstat')} USING(date, instrument)",
            "columns": 514, "note": "512 因子一次访问", "last_refresh_at": now,
        }
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  → _meta.json 已登记 {[i['table'] for i in infos]}")


# ═══════════════════ main ═══════════════════
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default="both", choices=["dir", "volstat", "both"])
    ap.add_argument("--freq", default="1w", choices=["1w", "1d"],
                    help="1w=周频快照（默认，原行为）；1d=日频（全部日线行）")
    ap.add_argument("--symbols", type=int, default=0, help="只取前 N 只（冒烟用）")
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    global FREQ
    FREQ = a.freq
    libs = ["dir", "volstat"] if a.lib == "both" else [a.lib]

    t0 = time.time()
    assert_single_code_body()

    syms = None
    if a.symbols:
        con = duckdb.connect(str(DB), read_only=True)
        syms = [r[0] for r in con.execute(
            "SELECT DISTINCT instrument FROM stock_bar1d "
            "WHERE instrument LIKE '%.SH' OR instrument LIKE '%.SZ' "
            f"ORDER BY instrument LIMIT {a.symbols}").fetchall()]
        con.close()
    bars = load_bars(syms)
    sd = signal_dates(load_calendar()) if FREQ == "1w" else []
    framed = to_freq(bars, sd)
    if FREQ == "1w":
        print(f"日线 {len(bars):,} 行 / {bars['instrument'].nunique():,} 只 → 周频 {len(framed):,} 行 / "
              f"{framed['date'].nunique()} 个信号日 (全局信号日 {len(sd)} 个，"
              f"{sd[0].date()}~{sd[-1].date()})")
    else:
        print(f"日线 {len(bars):,} 行 / {bars['instrument'].nunique():,} 只 → **日频** {len(framed):,} 行 / "
              f"{framed['date'].nunique()} 个交易日 ({framed['date'].min().date()}~{framed['date'].max().date()})")

    infos = []
    for lib in libs:
        infos.append(compute_and_ingest(framed, load_specs(lib), lib, max(1, a.jobs)))

    if a.lib == "both":
        create_combined_view()
    if not a.symbols:
        update_meta(infos)
    else:
        print("（冒烟模式：跳过 _meta.json 登记）")
    print(f"完成，总 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
