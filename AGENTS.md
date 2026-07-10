# 编码智能体工作区说明

## 仓库用途
这是一个基于 Python 的编码智能体，灵感来源于 Claude Code / Aider，具有以下特性：
- ReAct 推理循环（思考 → 行动 → 观察 → 重新思考）
- 基于 Rich 的流式输出，支持实时 Markdown/代码块渲染
- 工具系统（文件读写、精确编辑、Bash 执行、代码搜索）
- 多 LLM 支持（OpenAI / Anthropic / 智谱 / LiteLLM 统一接口）
- 沙箱执行（本地子进程 / Docker / E2B 云沙箱）
- 权限控制（操作前确认，防止误删）
- 上下文管理（自动压缩历史记录，token 计数）

## 主要目录
```
coding-agent/
├── src/coding_agent/
│   ├── cli.py              # CLI 入口点
│   ├── config.py           # 配置管理
│   ├── core/               # Agent 核心
│   │   ├── agent.py        # Agent 主类
│   │   ├── loop.py         # ReAct 循环
│   │   ├── memory.py       # 上下文管理
│   │   └── session.py      # 会话状态
│   ├── llm/                # LLM 抽象层
│   ├── tools/              # 工具系统
│   ├── sandbox/            # 执行沙箱
│   ├── ui/                 # 终端 UI
│   ├── storage/            # 持久化存储
│   ├── permissions/        # 权限控制
│   ├── codebase/           # 代码库理解
│   └── utils/              # 工具函数
├── tests/                  # 测试文件
├── .env.example            # 环境变量模板
└── pyproject.toml          # 项目依赖和配置
```

## 构建、类型检查、格式化和测试命令
- **安装依赖**：`make dev` 或 `uv sync --extra dev`
- **运行智能体**：`make run` 或 `uv run coding-agent`
- **运行测试**：`make test` 或 `uv run pytest`
- **代码检查**：`make lint` 或 `uv run ruff check src tests`
- **格式化代码**：`make format` 或 `uv run ruff format src tests`
- **类型检查**：`make typecheck` 或 `uv run mypy src`
- **清理**：`make clean`

## 架构边界和层级规则
1. **LLM 层**（`src/coding_agent/llm/`）：必须为不同的 LLM 提供商（OpenAI、Anthropic、智谱、LiteLLM）保持抽象。不要在各自文件之外嵌入特定提供者的逻辑。
2. **工具系统**（`src/coding_agent/tools/`）：工具应尽可能保持无状态和幂等。所有文件操作必须通过权限控制层。
3. **沙箱层**（`src/coding_agent/sandbox/`）：沙箱实现（本地、docker、e2b）必须实现 `sandbox/base.py` 中定义的基础沙箱接口。
4. **权限控制**（`src/coding_agent/permissions/`）：所有文件修改和 bash 执行都必须通过权限策略层。

## 编码规范
- **语言**：Python 3.11+
- **格式化**：使用 `ruff format`（双引号，行长度 100）
- **代码检查**：使用 `ruff check` 和规则：E, F, I, N, W, UP, B, C4, SIM
- **类型检查**：使用启用了严格模式的 `mypy`
- **测试**：使用支持 asyncio 的 `pytest`
- **日志记录**：所有日志操作使用 `loguru`

## 环境配置
- 环境变量通过 `.env` 文件管理（从 `.env.example` 复制）
- 关键配置选项：
  - `CODING_AGENT_MODEL`：默认 LLM 模型（例如，`openai:gpt-4o`，`anthropic:claude-3-5-sonnet`）
  - `CODING_AGENT_PERMISSION`：权限模式（`ask`，`auto`，`readonly`）
  - `CODING_AGENT_SANDBOX`：沙箱类型（`local`，`docker`）
  - `CODING_AGENT_LOG_LEVEL`：日志级别（`INFO`，`DEBUG` 等）

## 已知注意事项
1. **权限模式**：当 `CODING_AGENT_PERMISSION=ask` 时，智能体在文件修改或 bash 执行前会提示确认。使用 `readonly` 进行安全探索。
2. **沙箱执行**：本地沙箱使用 subprocess，而 Docker 沙箱需要 Docker 守护进程正在运行。
3. **LLM 路由**：`src/coding_agent/llm/router.py` 中的 LLM 路由器根据模型字符串前缀处理模型选择（例如，`openai:`，`anthropic:`，`zhipu:`）。

## 在更改敏感区域之前需要阅读的文档
- 修改 LLM 集成前：阅读 `src/coding_agent/llm/base.py` 和 `src/coding_agent/llm/router.py`
- 更改权限逻辑前：阅读 `src/coding_agent/permissions/policy.py`
- 修改沙箱执行前：阅读 `src/coding_agent/sandbox/base.py` 及具体的实现文件
