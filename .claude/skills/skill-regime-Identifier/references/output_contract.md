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

## 诚实报告要求（可视化出错时）

严格按研报/论文复现时，若 regime 输出结果**过于碎片化**导致可视化输出错误或无意义（如 HMM 单变量观测状态频繁跳变、时间段划分表上千行每段 1-2 天），**必须在 `04_delivery/final_report.md` 的「复现问题与局限」一节如实说明**，不得回避或掩盖。

说明需覆盖：现象（量化表现）、根因（数据限制/观测变量选择/方法固有特性）、已尝试的解决路径及结果、结论（方法局限 vs 复现条件不足）。

> 反复尝试后，若数据限制或研报方法本身导致可视化出错，如实写进 final_report 是诚实复现的一部分，而非失败。
