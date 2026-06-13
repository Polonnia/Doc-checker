# 文档规范检查系统

- 规则识别 Agent：从规范 PDF 提取规则并构建规则执行 DAG
- 检查执行 Agent：基于 DAG 对 XML 技术文档执行分层并行检查

LLM 使用 DeepSeek API。

## 1. 安装

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -e .
```

## 2. 配置

编辑根目录 `config.yaml`，其中统一配置：

- 规则 PDF 路径
- 待检查 XML 文件夹路径
- 输出目录
- DeepSeek API URL、模型、API Key

## 3. 运行

### 仅构建规则与 DAG

```bash
doc-checker build-rules --config config.yaml
```

### 仅执行检查（使用已有 DAG）

```bash
doc-checker run-check --config config.yaml --dag output/rule_dag.json
```

### 全流程

```bash
doc-checker full-run --config config.yaml
```

## 4. 输出

默认输出到 `output/`：

- `rules.json`：结构化规则
- `rule_dag.json`：规则执行图
- `check_report.json`：机器可读检查结果
- `check_report.md`：人工审阅报告
