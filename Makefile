.PHONY: install dev test lint format typecheck clean run

# 安装依赖
install:
	uv sync

# 开发环境设置
dev:
	uv sync --extra dev

# 运行智能体
run:
	uv run coding-agent

# 运行测试
test:
	uv run pytest

# 代码检查
lint:
	uv run ruff check src tests

# 格式化代码
format:
	uv run ruff format src tests

# 类型检查
typecheck:
	uv run mypy src

# 清理临时文件
clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
