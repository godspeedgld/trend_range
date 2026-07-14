---
name: filter-machine-learning
description: 滤波与机器学习方法的 skill 骨架，具体功能待定。
quantSkills:
  project_type: skill
  collection: quant-research-tools
  license: GPL-3.0
  category: tooling
  tags: [filter, kalman, machine-learning]
  language: zh-en
  status: draft
  validation_level: skeleton
  maintainer_type: community
  requires: []
---

# filter-machine-learning

> 骨架（skeleton）。具体功能、Core Workflow、API 待规划后补全。

## 待定
- 滤波方法（卡尔曼等）与机器学习方法的具体范围
- 输入 / 输出契约
- 与其它 skill（time-series-model / trend-prediction）的分工

## Python 与依赖
- 依赖用 **uv** 管理；解释器 `C:\Anaconda\envs\quant_env_311\python.exe`（Python 3.11）。
- 建环境：`uv venv --python "C:\Anaconda\envs\quant_env_311\python.exe"` → `uv sync`。
