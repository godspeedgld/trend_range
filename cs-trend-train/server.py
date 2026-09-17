"""cs-trend-train — 手动趋势画线交易训练工具 · 后端

标准库 http.server（零第三方依赖），职责：
  ① 静态托管 index.html
  ② K 线 JSON API（读本地 DuckDB warehouse stock_bar1d，后复权 + 原始价 + ATR14）
  ③ 画线 / 交易记录的读写（data/lines.json, data/trades.json）
  ④ 交易自动平仓判定：止损 / 止盈 / 吊灯（最高价 − 3×ATR14(前一日)，收盘触发）

启动：python cs-trend-train/server.py   →  http://127.0.0.1:8710
"""
from __future__ import annotations

import json
import os
import re
import uuid
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
ATR_N, CHANDRIER_MULT = 14, 3.0
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
    df["atr14"] = tr.ewm(alpha=1.0 / ATR_N, adjust=False, min_periods=ATR_N).mean()
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


# ── 自动平仓判定（5.2）──
def auto_exit(symbol: str, rec: dict) -> dict:
    """从信号日次日起逐日判定：止损 / 止盈 / 吊灯（close < 最高价−3×ATR14(前一日)）。"""
    kl = load_klines(symbol, rec["signal_date"], "2099-01-01")
    idx = next((i for i, b in enumerate(kl) if b["date"] > rec["signal_date"]), None)
    if idx is None:
        rec.update(exit_date=None, exit_price=None, exit_reason="pending")
        return rec
    peak = rec["buy_price"]
    for b in kl[idx:]:
        peak = max(peak, b["high"])
        if rec.get("stop_price") and b["low"] <= rec["stop_price"]:
            rec.update(exit_date=b["date"], exit_price=rec["stop_price"], exit_reason="止损")
            break
        if rec.get("tp_price") and b["high"] >= rec["tp_price"]:
            rec.update(exit_date=b["date"], exit_price=rec["tp_price"], exit_reason="止盈")
            break
        a_prev = kl[kl.index(b) - 1]["atr14"] if kl.index(b) > 0 else None
        if a_prev and b["close"] < peak - CHANDRIER_MULT * a_prev:
            rec.update(exit_date=b["date"], exit_price=b["close"], exit_reason="吊灯")
            break
    else:
        rec.update(exit_date=None, exit_price=None, exit_reason="pending")
    return rec


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
        if u.path == "/":
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if u.path == "/klinecharts.min.js":        # 本地化的图表库（CDN 不可达时免疫）
            self._send(200, (HERE / "klinecharts.min.js").read_bytes(),
                       "application/javascript; charset=utf-8")
            return
        if u.path == "/favicon.ico":
            self._send(200, b"", "image/x-icon")
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
            self._send(200, _load(TRADES_F).get(q.get("symbol", ""), []))
        else:
            self._send(404, {"err": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        symbol = body.get("symbol", "")
        if not symbol:
            return self._send(400, {"err": "symbol required"})
        if urlparse(self.path).path == "/api/lines":
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
        elif urlparse(self.path).path == "/api/trades":
            db = _load(TRADES_F)
            rec = body["trade"]
            rec.setdefault("id", uuid.uuid4().hex[:8])
            if body.get("auto") and not rec.get("exit_price"):
                rec = auto_exit(symbol, rec)
            db.setdefault(symbol, []).append(rec)
            _save(TRADES_F, db)
            self._send(200, rec)
        else:
            self._send(404, {"err": "not found"})

    def do_DELETE(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        symbol, rid = q.get("symbol", ""), q.get("id", "")
        if u.path == "/api/lines":
            db = _load(LINES_F)
            db[symbol] = [r for r in db.get(symbol, []) if r["id"] != rid]
            _save(LINES_F, db)
            self._send(200, {"ok": True})
        elif u.path == "/api/trades":
            db = _load(TRADES_F)
            db[symbol] = [r for r in db.get(symbol, []) if r["id"] != rid]
            _save(TRADES_F, db)
            self._send(200, {"ok": True})
        else:
            self._send(404, {"err": "not found"})


if __name__ == "__main__":
    print(f"cs-trend-train → http://127.0.0.1:{PORT}  （Ctrl+C 退出）")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
