# Coding Agent

一个用 Python 实现的 Coding Agent，灵感来自 Claude Code / Aider。

## 特性

- **ReAct 推理循环** — 思考 → 行动 → 观察 → 再思考
- **流式输出** — 基于 Rich 的实时 Markdown / 代码块渲染
- **工具系统** — 文件读写、精确编辑、Bash 执行、代码搜索
- **多 LLM 支持** — OpenAI / Anthropic / 智谱 / LiteLLM 统一接口
- **沙箱执行** — 本地 subprocess / Docker / E2B 云沙箱
- **权限控制** — 操作前确认，防止误删
- **上下文管理** — 自动压缩历史，token 计数

## 快速开始

```bash
# 1. 安装依赖 (推荐 uv)
make dev

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 3. 运行
make run
# 或
uv run coding-agent
```

## 使用示例

```bash
# 交互模式
coding-agent

# 单次执行
coding-agent -m "帮我看看 src/ 目录结构"

# 指定模型
coding-agent --model anthropic:claude-3-5-sonnet

# 只读模式
coding-agent --permission readonly
```

## 项目结构

```
coding-agent/
├── src/coding_agent/
│   ├── cli.py              # CLI 入口
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
│   ├── storage/            # 持久化
│   ├── permissions/        # 权限控制
│   └── utils/              # 工具函数
└── tests/
```

## License

MIT
