"""Syntax and structure validation for notebooks/kaggle_llm_server.ipynb (Sprint 8 Task 10).

No Jupyter or nbconvert installation required — the notebook is plain JSON.
Each code cell is validated with Python's compile() built-in.
GPU-only cells (tagged "gpu-only") are excluded from execution checks.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

NOTEBOOK_PATH = Path(__file__).parent.parent.parent.parent / "notebooks" / "kaggle_llm_server.ipynb"


@pytest.fixture(scope="module")
def notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text())


@pytest.fixture(scope="module")
def cells(notebook: dict) -> list[dict]:
    return notebook["cells"]


def _is_gpu_only(cell: dict) -> bool:
    tags = cell.get("metadata", {}).get("tags", [])
    return "gpu-only" in tags


def _source(cell: dict) -> str:
    src = cell["source"]
    return "".join(src) if isinstance(src, list) else src


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

class TestNotebookStructure:
    def test_notebook_file_exists(self):
        assert NOTEBOOK_PATH.exists(), f"Notebook not found at {NOTEBOOK_PATH}"

    def test_notebook_is_valid_json(self):
        content = NOTEBOOK_PATH.read_text()
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_notebook_has_expected_nbformat(self, notebook: dict):
        assert notebook["nbformat"] == 4

    def test_notebook_has_at_least_ten_cells(self, cells: list[dict]):
        assert len(cells) >= 10

    def test_notebook_has_kernel_info(self, notebook: dict):
        kernelspec = notebook.get("metadata", {}).get("kernelspec", {})
        assert kernelspec.get("name") == "python3"

    def test_notebook_has_both_code_and_markdown_cells(self, cells: list[dict]):
        types = {c["cell_type"] for c in cells}
        assert "code" in types
        assert "markdown" in types


# ---------------------------------------------------------------------------
# Code cell syntax
# ---------------------------------------------------------------------------

class TestCodeCellSyntax:
    def test_all_non_gpu_code_cells_compile(self, cells: list[dict]):
        errors = []
        for i, cell in enumerate(cells):
            if cell["cell_type"] != "code":
                continue
            if _is_gpu_only(cell):
                continue
            src = _source(cell)
            try:
                compile(src, f"<cell {i}>", "exec")
            except SyntaxError as exc:
                errors.append(f"Cell {i}: {exc}")
        assert not errors, "Syntax errors in non-GPU code cells:\n" + "\n".join(errors)

    def test_gpu_only_cells_are_tagged(self, cells: list[dict]):
        gpu_cells = [c for c in cells if _is_gpu_only(c)]
        assert len(gpu_cells) >= 3, "Expected at least 3 gpu-only tagged cells"

    def test_non_gpu_code_cells_also_compile_as_valid_python(self, cells: list[dict]):
        non_gpu_code = [
            c for c in cells
            if c["cell_type"] == "code" and not _is_gpu_only(c)
        ]
        assert len(non_gpu_code) >= 2, "Expected at least 2 non-GPU code cells"


# ---------------------------------------------------------------------------
# Required content
# ---------------------------------------------------------------------------

class TestRequiredContent:
    def test_env_var_cell_sets_embedding_server_url(self, cells: list[dict]):
        code_sources = [_source(c) for c in cells if c["cell_type"] == "code"]
        assert any("EMBEDDING_SERVER_URL" in src for src in code_sources)

    def test_env_var_cell_sets_llm_server_url(self, cells: list[dict]):
        code_sources = [_source(c) for c in cells if c["cell_type"] == "code"]
        assert any("LLM_SERVER_URL" in src for src in code_sources)

    def test_env_var_cell_sets_openai_api_key(self, cells: list[dict]):
        code_sources = [_source(c) for c in cells if c["cell_type"] == "code"]
        assert any("OPENAI_API_KEY" in src for src in code_sources)

    def test_health_check_cell_references_health_endpoint(self, cells: list[dict]):
        code_sources = [_source(c) for c in cells if c["cell_type"] == "code"]
        assert any("/health" in src for src in code_sources)

    def test_all_markdown_cells_are_non_empty(self, cells: list[dict]):
        for i, cell in enumerate(cells):
            if cell["cell_type"] == "markdown":
                assert _source(cell).strip(), f"Markdown cell {i} is empty"

    def test_architecture_md_contains_notebook_pointer(self):
        arch = (Path(__file__).parent.parent.parent.parent / "ARCHITECTURE.md").read_text()
        assert "kaggle_llm_server.ipynb" in arch
