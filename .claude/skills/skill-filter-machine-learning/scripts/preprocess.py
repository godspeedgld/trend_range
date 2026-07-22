"""金融时序数据预处理（独立类）。

Preprocessor：
  排序 → 重复日期处理 → 缺失值检查与填充/删除 → 预处理报告。
  策略可配（close_fill / ffill / drop），默认：close 缺失删行、OHLV 缺失用 close 填、volume 前向填。
"""

from __future__ import annotations

import pandas as pd


class Preprocessor:
    """金融时序数据预处理：排序 + 缺失值 + 重复。

    Args:
        ohlcv_strategy: OHLV 缺失处理。'close_fill'(用close填) | 'ffill'(前值填) | 'drop'(删行)。
        volume_strategy: volume 缺失处理。'ffill' | 'zero'(填0) | 'drop'。
        drop_close_nan: close 为 NaN 的行直接删除（close 是必需字段）。
        dedup: 重复日期处理。'last'(保留最后一条) | 'first' | None(不处理)。
    """

    def __init__(
        self,
        ohlcv_strategy: str = "close_fill",
        volume_strategy: str = "ffill",
        drop_close_nan: bool = True,
        dedup: str = "last",
    ):
        self.ohlcv_strategy = ohlcv_strategy
        self.volume_strategy = volume_strategy
        self.drop_close_nan = drop_close_nan
        self.dedup = dedup
        self._report: dict = {}

    def preprocess(self, data: pd.DataFrame) -> pd.DataFrame:
        """主入口：排序 → 去重 → 缺失值预处理 → 返回干净的 DataFrame。"""
        df = data.copy()
        n_in = len(df)
        stats = {"input_rows": n_in}

        # 1. 按时间排序
        if not df.index.is_monotonic_increasing:
            df = df.sort_index()
        stats["sorted"] = not data.index.is_monotonic_increasing

        # 2. 重复日期
        dup_mask = df.index.duplicated(keep="first")   # True = 后面重复的
        n_dup = int(dup_mask.sum())
        if n_dup and self.dedup:
            df = df[~df.index.duplicated(keep=self.dedup)]
        stats["dropped_duplicates"] = n_dup

        # 3. close NaN → 删除（close 必需）
        n_close_drop = 0
        if self.drop_close_nan and "close" in df.columns:
            mask = df["close"].isna()
            n_close_drop = int(mask.sum())
            df = df[~mask]
        stats["dropped_close_nan"] = n_close_drop

        # 4. OHLV 缺失 → 按策略
        ohl_cols = [c for c in ("open", "high", "low") if c in df.columns]
        n_ohl = 0
        for col in ohl_cols:
            mask = df[col].isna()
            cnt = int(mask.sum())
            if cnt == 0:
                continue
            n_ohl += cnt
            if self.ohlcv_strategy == "close_fill":
                df.loc[mask, col] = df.loc[mask, "close"]
            elif self.ohlcv_strategy == "ffill":
                df[col] = df[col].ffill()
            elif self.ohlcv_strategy == "drop":
                df = df[~mask]
        stats["filled_ohlcv"] = n_ohl

        # 5. volume 缺失 → 按策略
        vol_col = next((c for c in ("vol", "volume") if c in df.columns), None)
        n_vol = 0
        if vol_col:
            mask = df[vol_col].isna()
            n_vol = int(mask.sum())
            if n_vol:
                if self.volume_strategy == "ffill":
                    df[vol_col] = df[vol_col].ffill().fillna(0)
                elif self.volume_strategy == "zero":
                    df[vol_col] = df[vol_col].fillna(0)
                elif self.volume_strategy == "drop":
                    df = df[~mask]
        stats["filled_volume"] = n_vol

        # 6. 汇总
        stats["output_rows"] = len(df)
        stats["remaining_nan"] = int(df.isna().sum().sum())
        self._report = stats
        return df

    @property
    def report(self) -> dict:
        """返回上次 process() 的处理统计。"""
        return self._report

    def check(self, data: pd.DataFrame) -> dict:
        """只检查不修改：缺失统计 + 重复 + 排序。"""
        return {
            "total_rows": len(data),
            "nan_per_col": {c: int(data[c].isna().sum()) for c in data.columns},
            "duplicated_dates": int(data.index.duplicated().sum()),
            "is_sorted": bool(data.index.is_monotonic_increasing),
            "close_nan": int(data["close"].isna().sum()) if "close" in data.columns else None,
        }


__all__ = ["Preprocessor"]
