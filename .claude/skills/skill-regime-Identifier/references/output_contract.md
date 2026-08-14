# 输出契约（output_contract.md）

## 输出根

优先级：`REPLICATION_ROOT`（.env）> 云环境 `/home/coder/project/regime-replication` > `~/regime-replication`。可用 `--root` 覆盖。

## 目录布局

```
{project_dir}/
  01_translation/
    full_translation.md          # Step 2 产出（中文研报可跳过）
  02_approach/
    main_approach.md             # Step 3 产出（头条）
  03_regime_analysis/
    regime_methods.md            # Step 4a 产出（方法描述）
    regime_impl.py               # Step 4a 产出（可执行代码）
    data_params.json             # Step 4a 产出（数据参数）
    regime_segments.md           # Step 4b 产出（表格化时间段划分）
    regime_stats.json            # Step 4b 产出（统计）
    regime_view.html             # Step 4b 产出（可视化）
  04_delivery/
    final_report.md              # Step 6 产出
  manifest.json                  # 全局元数据
  failure_report.md              # 可选（有阻塞时）
```

## 产物验收清单（quality_gate_check.py 强制）

| 产物 | 必需 | 来源步骤 |
|------|------|---------|
| `02_approach/main_approach.md` | ✅ | Step 3 |
| `03_regime_analysis/regime_methods.md` | ✅ | Step 4a |
| `03_regime_analysis/regime_impl.py` | ✅ | Step 4a |
| `03_regime_analysis/data_params.json` | ✅ | Step 4a |
| `03_regime_analysis/regime_segments.md` | ✅ | Step 4b |
| `03_regime_analysis/regime_stats.json` | ✅ | Step 4b |
| `03_regime_analysis/regime_view.html` | ✅ | Step 4b |
| `04_delivery/final_report.md` | ✅ | Step 5 |
| `manifest.json` | ✅ | Step 1 |

> `01_translation/full_translation.md` 对中文研报可跳过。

## manifest.json 字段

```json
{
  "report_id": "slug",
  "title": "标题",
  "source": "PDF路径/URL",
  "created_at": "ISO时间",
  "regime_engine": {"name": "regime-view-generator", "status": "ran/available"},
  "data_sources": [{"provider": "...", "path": "...", "instrument": "...", "interval": "..."}],
  "methods": ["方法1", "方法2"],
  "run_history": [],
  "status": "initialized/complete/inconclusive"
}
```

## 语言要求

- 用户可见产出全程中文。
- 图内文字仅英文 ASCII。
- 不得伪造产物；数据不足标 `inconclusive`。
