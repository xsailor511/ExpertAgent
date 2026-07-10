from __future__ import annotations

from pathlib import Path

from coding_agent.codebase.indexer import Indexer, _extract_fallback
from coding_agent.codebase.search import CodeSearch


class TestExtractFallback:
    def test_python_class_and_function(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text(
            "class MyClass:\n"
            "    def my_method(self):\n"
            "        pass\n"
            "\n"
            "def top_func():\n"
            "    pass\n"
        )
        symbols = _extract_fallback(f, f.read_text("utf-8"))
        names = [s["name"] for s in symbols]
        assert "MyClass" in names
        assert "top_func" in names

    def test_js_function(self, tmp_path: Path):
        f = tmp_path / "test.js"
        f.write_text("function hello() {}\nconst x = 1;\n")
        symbols = _extract_fallback(f, f.read_text("utf-8"))
        names = [s["name"] for s in symbols]
        assert "hello" in names

    def test_unsupported_ext(self, tmp_path: Path):
        f = tmp_path / "test.xyz"
        f.write_text("whatever")
        assert _extract_fallback(f, f.read_text("utf-8")) == []


class TestIndexer:
    def test_index_single_file(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "mod.py").write_text("def foo(): pass\nclass Bar: pass\n")
        idx = Indexer(tmp_path / "src")
        idx.index()
        names = [s["name"] for s in idx.symbols]
        assert "foo" in names
        assert "Bar" in names

    def test_index_multiple_files(self, tmp_path: Path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "a.py").write_text("def a(): pass\n")
        (tmp_path / "pkg" / "b.py").write_text("def b(): pass\n")
        idx = Indexer(tmp_path / "pkg")
        idx.index()
        assert len(idx.symbols) == 2

    def test_index_empty_dir(self, tmp_path: Path):
        idx = Indexer(tmp_path / "empty")
        (tmp_path / "empty").mkdir()
        idx.index()
        assert idx.symbols == []

    def test_search_by_name(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "mod.py").write_text("def hello_world(): pass\n")
        idx = Indexer(tmp_path / "src")
        idx.index()
        results = idx.search("hello")
        assert len(results) >= 1
        assert results[0]["name"] == "hello_world"

    def test_search_with_scope(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "mod.py").write_text("def shared(): pass\n")
        idx = Indexer(tmp_path / "src")
        idx.index()
        results = idx.search("shared", scope="src")
        assert len(results) >= 1
        results2 = idx.search("shared", scope="nonexistent")
        assert results2 == []


class TestCodeSearch:
    def test_find_symbol_exact(self, tmp_path: Path):
        (tmp_path / "mod.py").write_text("def exact_match(): pass\n")
        cs = CodeSearch(tmp_path)
        cs.ensure_indexed()
        results = cs.find_symbol("exact_match")
        assert len(results) == 1

    def test_file_symbols(self, tmp_path: Path):
        f = tmp_path / "mod.py"
        f.write_text("def a(): pass\ndef b(): pass\n")
        cs = CodeSearch(tmp_path)
        cs.ensure_indexed()
        syms = cs.file_symbols(f)
        assert len(syms) == 2

    def test_stats(self, tmp_path: Path):
        (tmp_path / "mod.py").write_text("def func(): pass\n")
        cs = CodeSearch(tmp_path)
        cs.ensure_indexed()
        stats = cs.stats()
        assert stats["total_symbols"] >= 1
        assert stats["total_files"] >= 1

    def test_search_substring(self, tmp_path: Path):
        (tmp_path / "mod.py").write_text("def find_this(): pass\n")
        cs = CodeSearch(tmp_path)
        cs.ensure_indexed()
        results = cs.search("find")
        assert len(results) >= 1
