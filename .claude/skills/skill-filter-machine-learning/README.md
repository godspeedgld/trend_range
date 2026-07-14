# skill-filter-machine-learning

骨架。功能待定（滤波 / 机器学习方法）。目录结构对齐 `skill-time-series-model`。

## 目录
```
skill-filter-machine-learning/
├── SKILL.md            # 骨架
├── README.md
├── pyproject.toml      # uv 依赖
├── .gitignore
├── scripts/            # 实现代码（待加）
├── references/         # workflow / api / interpretation / report-format（骨架）
├── agents/             # cursor / openai / portable（骨架）
└── reports/            # 输出（gitignore，保留 README）
```

## Python 与依赖
- 依赖用 **uv** 管理。
- 解释器：`C:\Anaconda\envs\quant_env_311\python.exe`（Python 3.11.15）。
- 建环境：`uv venv --python "C:\Anaconda\envs\quant_env_311\python.exe"`，再 `uv sync`。
- 加包：`uv add <package>`。

License: GPL-3.0-only.
