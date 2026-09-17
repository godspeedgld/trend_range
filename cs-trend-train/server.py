"""cs-trend-train — 手动趋势画线交易训练工具 · 后端

标准库 http.server（零第三方依赖），职责：
  ① 静态托管 index.html / trades.html（含本地化的 klinecharts、plotly，零 CDN）
  ② K 线 JSON API（读本地 DuckDB warehouse stock_bar1d，后复权 + 原始价 + ATR14）
  ③ 画线 / 交易记录 / 全局设置的读写（data/lines.json, data/trades.json, data/settings.json）
  ④ 交易出场判定：**只认用户提交的止损价 / 止盈价**，从开仓日当根起逐日判定，
     先止损后止盈（同日双触按止损计）；跳空越过触发价时按**当日开盘价**成交
  ⑤ 按「等额止损」反算股数：止损额度 ÷ 每股风险，向下取整到 1 手（100 股）

启动：python cs-trend-train/server.py   →  http://127.0.0.1:8710
"""
from __future__ import annotations

import json
import math
import os
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
DATA = HERE / "data"
LINES_F = DATA / "lines.json"
TRADES_F = DATA / "trades.json"
SETTINGS_F = DATA / "settings.json"
LOT = 100                                     # A 股 1 手 = 100 股
DEFAULT_SETTINGS = {"risk_amount": 5000, "show_lines": True, "show_trades": False}
FAT_TAIL_PCT = 30.0                           # 肥尾线：收益率 ≥ +30%（与 analysis_012/014 同口径）
# 静态托管白名单 —— 用**显式枚举**而非路径拼接，从根上免掉目录穿越
STATIC = {"index.html": "text/html; charset=utf-8",
          "trades.html": "text/html; charset=utf-8",
          "klinecharts.min.js": "application/javascript; charset=utf-8",
          "plotly.min.js": "application/javascript; charset=utf-8"}
PORT = int(os.environ.get("PORT", "8710"))


# ── JSON 存取（原子写）──
def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def get_settings() -> dict:
    s = {**DEFAULT_SETTINGS, **_load(SETTINGS_F)}
    if not isinstance(s.get("risk_amount"), (int, float)) or s["risk_amount"] <= 0:
        s["risk_amount"] = DEFAULT_SETTINGS["risk_amount"]
    return s


def _num(v):
    """前端空串 / null / 非数字 → None（空串必须当"没填"而不是 0）"""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


# ── 行情读取 + ATR14 ──
def load_klines(symbol: str, start: str, end: str) -> list[dict]:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    # XD/除权日的名称会变（如"XD中国平"），按主键取最长序列，再按名称众数过滤脏行
    df = con.execute(
        "SELECT date, open, high, low, close, volume, amount, change_ratio, adjust_factor "
        "FROM stock_bar1d WHERE instrument=? AND date>=? AND date<=? ORDER BY date",
        [symbol, start, end]).df()
    con.close()
    if df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"])
    # 停牌占位行（OHLC 为 NaN）直接丢弃 —— K 线图只画交易日，缺行无害；
    # adjust_factor 阶梯不变 → ffill 后再算原始价；volume 缺失置 0
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    df["adjust_factor"] = df["adjust_factor"].ffill().bfill()
    df["volume"] = df["volume"].fillna(0)
    # Wilder ATR14（与 hs300 工程 shared/atr14_precompute.py 同式）
    pc = df["close"].shift(1)
    tr = pd.Series(np.maximum.reduce([df["high"] - df["low"],
                                      (df["high"] - pc).abs(),
                                      (df["low"] - pc).abs()]))
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    df["atr14"] = tr.ewm(alpha=1.0 / 14, adjust=False, min_periods=14).mean()
    df["raw"] = df["close"] / df["adjust_factor"]          # 原始价（参考字段）
    # turnover / change 是 klinecharts KLineData 的**标准字段**，塞进去后
    # tooltip 模板里的 {turnover} / {change} 就能直接插值，无需自绘
    return [{"timestamp": int(t.value // 10**6), "open": r.open, "high": r.high,
             "low": r.low, "close": r.close, "volume": float(r.volume),
             "turnover": (None if pd.isna(r.amount) else round(r.amount / 1e8, 2)),  # 成交额(亿)
             "change": (None if pd.isna(r.change_ratio) else round(r.change_ratio * 100, 2)),
             "amount": (None if pd.isna(r.amount) else round(r.amount / 1e8, 2)),
             "atr14": (None if pd.isna(r.atr14) else round(r.atr14, 4)),
             "raw_close": round(r.raw, 3), "date": r.date.strftime("%Y-%m-%d")}
            for r, t in zip(df.itertuples(), df["date"])]


def search_symbols(q: str) -> list[dict]:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    rows = con.execute(
        "SELECT instrument, any_value(name) nm, count(*) n FROM stock_bar1d "
        "WHERE instrument LIKE ? OR name LIKE ? GROUP BY instrument "
        "ORDER BY n DESC LIMIT 20", [f"%{q}%", f"%{q}%"]).fetchall()
    con.close()
    return [{"symbol": r[0], "name": r[1], "bars": r[2]} for r in rows]


def symbol_names(syms: list[str]) -> dict:
    if not syms:
        return {}
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    ph = ",".join("?" * len(syms))
    rows = con.execute(
        f"SELECT instrument, any_value(name) FROM stock_bar1d WHERE instrument IN ({ph}) "
        "GROUP BY instrument", syms).fetchall()
    con.close()
    return {r[0]: r[1] for r in rows}


# ── 出场判定（只认用户提交的止损/止盈价）──
def auto_exit(symbol: str, rec: dict) -> dict:
    """从**开仓日当根**起逐日判定出场（开盘已成交，当天盘中就可能打到止损）。

    规则（用户 2026-09-17 指定）：
      · 出场**只由提交的止损价/止盈价决定**，不用吊灯等自适应规则
      · 同日既触止损又触止盈 → 按**止损**计（日内路径不可知，取保守假设）
      · 跳空越过触发价 → 按**当日开盘价**成交（止损取 min(止损价, 开盘)、止盈取 max)，
        否则会系统性高估收益（现实中跳空从来成交不到理论价）
    """
    kl = load_klines(symbol, rec["entry_date"], "2099-01-01")
    i0 = next((i for i, b in enumerate(kl) if b["date"] == rec["entry_date"]), None)
    if i0 is None:                                   # 开仓日无行情（理论上已被 build_trade 拦掉）
        rec.update(exit_date=None, exit_price=None, exit_reason="pending", holding_days=None)
        return rec
    stop, tp = rec["stop_price"], rec["tp_price"]
    for i in range(i0, len(kl)):
        b = kl[i]
        if b["low"] <= stop:
            rec.update(exit_date=b["date"], exit_price=min(stop, b["open"]),
                       exit_reason="止损", holding_days=i - i0 + 1)
            return rec
        if b["high"] >= tp:
            rec.update(exit_date=b["date"], exit_price=max(tp, b["open"]),
                       exit_reason="止盈", holding_days=i - i0 + 1)
            return rec
    # 两根线都没打到 → 一直持仓（统计里单列，不计入胜率/盈亏比）
    rec.update(exit_date=None, exit_price=None, exit_reason="pending", holding_days=None)
    return rec


def build_trade(symbol: str, body: dict, settings: dict):
    """构造一条交易记录 → (rec, None) 或 (None, 错误 dict)。空串一律当"没填"。"""
    t = body.get("trade") or {}
    entry_date = str(t.get("entry_date") or "").strip()
    if not entry_date:
        return None, {"err": "开仓时间必填"}
    stop, tp = _num(t.get("stop_price")), _num(t.get("tp_price"))
    if stop is None:
        return None, {"err": "止损价必填（出场只认你提交的止损/止盈价）"}
    if tp is None:
        return None, {"err": "止盈价必填（出场只认你提交的止损/止盈价）"}
    bars = load_klines(symbol, entry_date, entry_date)
    if not bars:
        return None, {"err": f"{entry_date} 无行情（非交易日 / 停牌 / 超出库内范围）"}
    bar = bars[0]
    buy = _num(t.get("buy_price"))
    source = "manual" if buy is not None else "bar_open"
    if buy is None:
        buy = bar["open"]                     # 留空 = 用开仓时间那根的开盘价
    if buy <= stop:
        return None, {"err": f"止损价须低于开仓价（开仓 {buy:.2f} / 止损 {stop:.2f}）"}
    if tp <= buy:
        return None, {"err": f"止盈价须高于开仓价（开仓 {buy:.2f} / 止盈 {tp:.2f}）"}
    risk = _num(body.get("risk_amount")) or settings["risk_amount"]
    rps = buy - stop                          # 每股风险
    shares = int(math.floor(risk / rps / LOT) * LOT)   # 向下取整到整手（不向上，否则放大风险）
    if shares <= 0:
        return None, {"err": f"按 {risk:g} 元止损额度买不满 1 手："
                             f"每股风险 {rps:.2f} 元 → 1 手需 {rps * LOT:,.0f} 元"}
    rec = {"id": t.get("id") or uuid.uuid4().hex[:8],
           "entry_date": entry_date, "entry_source": source,
           "buy_price": round(buy, 4), "stop_price": round(stop, 4), "tp_price": round(tp, 4),
           "risk_amount": risk, "shares": shares,
           "adj": "hfq",                                   # 备注口径（见 README 已知限制）
           "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    return auto_exit(symbol, rec), None


def decorate(rec: dict) -> dict:
    """读时补齐派生量（**不改库**）。全部容忍 None：老记录（上一版 schema，无 entry_date /
    shares / risk_amount）也能算—— 因为 R 是价格层量，不需要股数：

        R = (平仓价 − 开仓价) / (开仓价 − 止损价)

    """
    out = dict(rec)
    buy, stop, ex = rec.get("buy_price"), rec.get("stop_price"), rec.get("exit_price")
    if not out.get("entry_date"):                 # 老记录：开仓日退回信号日
        out["entry_date"] = rec.get("signal_date")
        out["legacy"] = True
    rps = (buy - stop) if (buy is not None and stop is not None) else None
    shares = rec.get("shares")
    out.update(risk_per_share=rps, risk_pct=(rps / buy if rps and buy else None),
               notional=(buy * shares if buy and shares else None),
               ret_pct=None, R=None, pnl=None, is_fat_tail=False)
    if ex is not None and buy is not None:
        out["ret_pct"] = (ex / buy - 1) * 100
        out["R"] = (ex - buy) / rps if rps else None
        out["is_fat_tail"] = out["ret_pct"] >= FAT_TAIL_PCT
        # 老记录没有 shares → pnl 留 None（反填止损额度会凭空造出从未发生过的仓位）
        if shares:
            out["pnl"] = (ex - buy) * shares
        out["status"] = "win" if ex > buy else ("loss" if ex < buy else "flat")
    else:
        out["status"] = "pending"                 # 持仓中：不计入统计
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):        # 静默访问日志
        pass

    def _send(self, code: int, body, ctype="application/json"):
        if isinstance(body, (list, dict)):
            # 保险丝：再有漏网 NaN 当场报 500，而不是输出非法 JSON 让浏览器莫名失败
            body = json.loads(json.dumps(body, ensure_ascii=False, allow_nan=False))
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")   # 页面不缓存，改完刷新即生效
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        name = "index.html" if u.path == "/" else u.path.lstrip("/")
        if name in STATIC:                                  # 白名单枚举，无路径拼接
            self._send(200, (HERE / name).read_bytes(), STATIC[name])
            return
        if u.path == "/favicon.ico":
            self._send(200, b"", "image/x-icon")
            return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/api/symbols":
            # curl/浏览器默认 UTF-8；parse_qs 在 py3.13- 已按 latin-1 解 bytes，
            # 中文会变乱码 → 手动重解码
            raw = u.query.split("q=", 1)[-1].split("&")[0] if "q=" in u.query else ""
            if raw and (not q.get("q") or q["q"].count("�")):
                try:
                    from urllib.parse import unquote
                    q["q"] = unquote(raw, encoding="utf-8", errors="strict")
                except UnicodeDecodeError:
                    pass
            self._send(200, search_symbols(q.get("q", "")))
        elif u.path == "/api/coverage":
            con = duckdb.connect(str(WAREHOUSE), read_only=True)
            row = con.execute("SELECT min(date), max(date) FROM stock_bar1d WHERE instrument=?",
                              [q.get("symbol", "")]).fetchone()
            total = con.execute("SELECT count(DISTINCT instrument) FROM stock_bar1d").fetchone()[0]
            con.close()
            self._send(200, {"in_db": row[0] is not None,
                             "first": str(row[0])[:10] if row[0] else None,
                             "last": str(row[1])[:10] if row[1] else None,
                             "total": total})
        elif u.path == "/api/klines":
            self._send(200, load_klines(q.get("symbol", ""), q.get("start", "2015-01-01"),
                                        q.get("end", "2099-01-01")))
        elif u.path == "/api/lines":
            self._send(200, _load(LINES_F).get(q.get("symbol", ""), []))
        elif u.path == "/api/trades":
            db = _load(TRADES_F)
            if q.get("all"):                    # 统计页：一次拿全部标的
                self._send(200, {"trades": {s: [decorate(r) for r in rs]
                                            for s, rs in db.items() if rs},
                                 "names": symbol_names([s for s, rs in db.items() if rs])})
            else:
                self._send(200, [decorate(r) for r in db.get(q.get("symbol", ""), [])])
        elif u.path == "/api/settings":
            self._send(200, get_settings())
        else:
            self._send(404, {"err": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        path = urlparse(self.path).path
        if path == "/api/settings":
            s = get_settings()
            for k, v in (body or {}).items():
                if k in DEFAULT_SETTINGS and v is not None:
                    s[k] = v
            try:                                   # 前端可能传来字符串
                s["risk_amount"] = float(s["risk_amount"])
            except (TypeError, ValueError):
                s["risk_amount"] = DEFAULT_SETTINGS["risk_amount"]
            if s["risk_amount"] <= 0:
                s["risk_amount"] = DEFAULT_SETTINGS["risk_amount"]
            _save(SETTINGS_F, s)
            return self._send(200, s)
        symbol = body.get("symbol", "")
        if not symbol:
            return self._send(400, {"err": "symbol required"})
        if path == "/api/lines":
            db = _load(LINES_F)
            rec = body["line"]
            lst = db.setdefault(symbol, [])
            # 按 id upsert：命中 → 原地更新（拖动整体/端点），未命中 → 新建（画线）
            if not rec.get("id"):
                # 客户端本应总带 id（闭包捕获）。走到这里说明有 bug —— 出声报警，
                # 否则会静默追加重复线，肉眼很难发现
                print(f"⚠ /api/lines 收到无 id 的记录，按新建处理（疑似客户端 bug）：{rec}")
                rec["id"] = uuid.uuid4().hex[:8]
            # 4.1 归一化：拖动可能交换端点 → start>end。强制 start≤end（交换日期+价格对），
            #     保证记录规范、过滤逻辑只看 end 即可覆盖"整条线在未来"的情形
            if rec["start_date"] > rec["end_date"]:
                rec["start_date"], rec["end_date"] = rec["end_date"], rec["start_date"]
                rec["start_price"], rec["end_price"] = rec["end_price"], rec["start_price"]
            hit = next((r for r in lst if r["id"] == rec["id"]), None)
            if hit is not None:
                lst[lst.index(hit)] = rec
                action = "update"
            else:
                lst.append(rec)
                action = "create"
            _save(LINES_F, db)
            self._send(200, {**rec, "_action": action})
        elif path == "/api/trades":
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            dry = q.get("dry_run") in ("1", "true")
            db = _load(TRADES_F)
            lst = db.setdefault(symbol, [])
            rec, err = build_trade(symbol, body, get_settings())
            if err:
                return self._send(400, err)
            # 唯一键 = 标的 + 开仓时间：同 id 命中 = 修改自己；同开仓日命中 = 撞车
            i_same = next((i for i, r in enumerate(lst) if r.get("id") == rec["id"]), None)
            i_day = next((i for i, r in enumerate(lst)
                          if (r.get("entry_date") or r.get("signal_date")) == rec["entry_date"]), None)
            dup = decorate(lst[i_day]) if (i_day is not None and i_same != i_day) else None
            if dry:                                   # 实时预览：不落库，把撞车情况一并回传
                return self._send(200, {**decorate(rec), "_dry_run": True, "_duplicate": dup})
            if dup and not body.get("overwrite"):
                return self._send(409, {"err": "duplicate",
                                        "msg": f"{rec['entry_date']} 已有开仓记录",
                                        "existing": dup})
            if i_same is not None and i_day is not None and i_same != i_day:
                # 修改时把开仓日改到了**另一条**记录的日子：吞掉两条，只留一条（沿用被覆盖那条的 id）
                rec["id"] = lst[i_day]["id"]
                lst = [r for j, r in enumerate(lst) if j not in (i_same, i_day)]
                lst.append(rec)
                action = "update"
            elif i_day is not None and i_same != i_day:
                rec["id"] = lst[i_day]["id"]     # 覆盖同日记录，沿用它的 id
                lst[i_day] = rec
                action = "update"
            elif i_same is not None:
                lst[i_same] = rec
                action = "update"
            else:
                lst.append(rec)
                action = "create"
            db[symbol] = lst
            _save(TRADES_F, db)
            self._send(200, {**decorate(rec), "_action": action})
        else:
            self._send(404, {"err": "not found"})

    def do_DELETE(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        symbol, rid = q.get("symbol", ""), q.get("id", "")
        if u.path == "/api/trades" and q.get("all"):
            # 清除整个标的 —— **独立分支**，不复用下面 `id != rid` 的逻辑：
            # 那条在 rid 为空时是 no-op（安全），一旦改成"空 id 即清空"，
            # 前端任何一次 id 丢失的 DELETE 都会静默清掉整个标的
            db = _load(TRADES_F)
            n = len(db.get(symbol, []))
            db[symbol] = []
            _save(TRADES_F, db)
            return self._send(200, {"ok": True, "removed": n})
        if u.path in ("/api/lines", "/api/trades"):
            path = LINES_F if u.path == "/api/lines" else TRADES_F
            db = _load(path)
            db[symbol] = [r for r in db.get(symbol, []) if r["id"] != rid]
            _save(path, db)
            self._send(200, {"ok": True})
        else:
            self._send(404, {"err": "not found"})


if __name__ == "__main__":
    print(f"cs-trend-train → http://127.0.0.1:{PORT}  （Ctrl+C 退出）")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
