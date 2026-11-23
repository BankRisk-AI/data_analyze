"""The architecture rules as a test: modules are independent, layers only look inward, core and shared know no module."""
import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[3] / "app"
MODULES = sorted(p.name for p in (APP / "modules").iterdir() if p.is_dir() and not p.name.startswith("_"))
LAYERS = ("domain", "application", "infrastructure", "presentation")
# what each layer may import from its own module (module.py and __main__.py compose the module: no rule)
ALLOWED = {"domain": {"domain"}, "infrastructure": {"domain", "infrastructure"}, "application": {"domain", "infrastructure", "application"},
           "presentation": {"domain", "application", "presentation"}}
FRAMEWORKS = {"fastapi", "starlette", "pydantic", "psycopg2", "uvicorn"}


def imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append(node.module)
    return out


def files(root: Path):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize("module", MODULES)
def test_a_module_imports_no_other_module(module):
    for p in files(APP / "modules" / module):
        for name in imports_of(p):
            if name.startswith("app.modules."):
                assert name.split(".")[2] == module, f"{p.relative_to(APP)} imports {name}"
            assert name != "app.modules", f"{p.relative_to(APP)} imports the module registry"


@pytest.mark.parametrize("module", MODULES)
def test_layers_only_look_inward(module):
    for layer in LAYERS:
        for p in files(APP / "modules" / module / layer):
            for name in imports_of(p):
                parts = name.split(".")
                if name.startswith(f"app.modules.{module}.") and len(parts) > 3 and parts[3] in LAYERS:
                    assert parts[3] in ALLOWED[layer], f"{p.relative_to(APP)} ({layer}) imports {name}"


@pytest.mark.parametrize("module", MODULES)
def test_the_domain_is_free_of_frameworks(module):
    for p in files(APP / "modules" / module / "domain"):
        for name in imports_of(p):
            assert name.split(".")[0] not in FRAMEWORKS, f"{p.relative_to(APP)} imports {name}"


def test_core_and_shared_know_no_module():
    for root in (APP / "core", APP / "shared"):
        for p in files(root):
            for name in imports_of(p):
                assert not name.startswith("app.modules"), f"{p.relative_to(APP)} imports {name}"


def test_every_module_has_a_spec_in_the_registry():
    from app.modules import MODULES as REGISTERED

    assert sorted(m.name for m in REGISTERED) == MODULES
