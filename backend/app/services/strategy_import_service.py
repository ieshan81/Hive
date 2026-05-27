"""Strategy import sandbox — manifest + AST validation, backtest-only lifecycle."""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from app.config import BACKEND_ROOT
from app.database import StrategyRegistry
from app.services.config_manager import ConfigManager

STRATEGY_IMPORT_SANDBOX = (BACKEND_ROOT / "data" / "strategy_import_sandbox").resolve()

FORBIDDEN_AST_NAMES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "alpaca",
        "shutil",
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "globals",
        "locals",
        "environ",
        "__class__",
        "__mro__",
        "__subclasses__",
        "__globals__",
        "__dict__",
    }
)

ALLOWED_IMPORT_ROOTS = frozenset({"typing", "dataclasses", "enum", "math", "statistics", "decimal"})


class StrategyImportService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def status(self) -> dict[str, Any]:
        imported = list(
            self.session.exec(
                select(StrategyRegistry).where(StrategyRegistry.current_stage == "imported")
            ).all()
        )
        validated = list(
            self.session.exec(
                select(StrategyRegistry).where(StrategyRegistry.current_stage == "validated_schema")
            ).all()
        )
        backtest_only = list(
            self.session.exec(
                select(StrategyRegistry).where(StrategyRegistry.current_stage == "backtest_only")
            ).all()
        )
        return {
            "status": "ok",
            "sandbox": True,
            "broker_access": False,
            "env_access": False,
            "subprocess": False,
            "file_writes": False,
            "network": False,
            "imported_count": len(imported),
            "validated_schema_count": len(validated),
            "backtest_only_count": len(backtest_only),
            "lifecycle_stages": [
                "imported",
                "validated_schema",
                "backtest_only",
                "rejected",
                "paper_candidate",
            ],
        }

    def list_imported(self) -> list[dict]:
        rows = self.session.exec(
            select(StrategyRegistry).where(
                StrategyRegistry.current_stage.in_(
                    ("imported", "validated_schema", "backtest_only", "rejected")
                )
            )
        ).all()
        return [self._row_dict(r) for r in rows]

    def import_manifest(self, manifest: dict, python_source: Optional[str] = None) -> dict[str, Any]:
        sid = str(manifest.get("strategy_id") or manifest.get("id") or "").strip()
        if not sid:
            return {"status": "error", "message": "strategy_id required"}
        name = str(manifest.get("name") or sid)
        errors = self._validate_manifest(manifest)
        if errors:
            return {"status": "error", "errors": errors}

        ast_result = {"status": "skipped", "message": "no python source"}
        if python_source:
            ast_result = self._validate_python_ast(python_source)
            if ast_result.get("status") != "ok":
                return {"status": "error", "ast": ast_result}

        existing = self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == sid)
        ).first()
        stage = "validated_schema" if ast_result.get("status") == "ok" else "imported"
        if existing:
            existing.name = name
            existing.current_stage = stage
            existing.symbols = manifest.get("symbols") or existing.symbols
            existing.active_parameters_json = {
                **(existing.active_parameters_json or {}),
                "import_manifest": manifest,
            }
            existing.updated_at = datetime.utcnow()
            self.session.add(existing)
        else:
            self.session.add(
                StrategyRegistry(
                    strategy_id=sid,
                    name=name,
                    family=str(manifest.get("family") or "imported"),
                    current_stage=stage,
                    symbols=manifest.get("symbols") or [],
                    author_type="imported_sandbox",
                    active_parameters_json={
                        "import_manifest": manifest,
                        "imported_at": datetime.utcnow().isoformat(),
                    },
                    can_trade_paper=False,
                    can_trade_live=False,
                    live_locked=True,
                )
            )
        self.session.flush()
        return {
            "status": "ok",
            "strategy_id": sid,
            "stage": stage,
            "ast": ast_result,
            "message": "Imported to sandbox — backtest_only required before paper",
        }

    def _resolve_sandbox_path(self, path: str) -> Path | None:
        """Only paths inside approved strategy import sandbox."""
        STRATEGY_IMPORT_SANDBOX.mkdir(parents=True, exist_ok=True)
        raw = Path(path)
        candidate = raw.resolve() if raw.is_absolute() else (STRATEGY_IMPORT_SANDBOX / raw).resolve()
        try:
            candidate.relative_to(STRATEGY_IMPORT_SANDBOX)
        except ValueError:
            return None
        return candidate if candidate.exists() and candidate.is_file() else None

    def import_file(self, path: str) -> dict[str, Any]:
        p = self._resolve_sandbox_path(path)
        if p is None:
            return {
                "status": "error",
                "message": "path not allowed — use sandbox directory or paste manifest JSON",
                "sandbox_root": str(STRATEGY_IMPORT_SANDBOX),
            }
        if p.suffix.lower() in (".json",):
            manifest = json.loads(p.read_text(encoding="utf-8"))
            return self.import_manifest(manifest)
        if p.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml

                manifest = yaml.safe_load(p.read_text(encoding="utf-8"))
            except Exception as exc:
                return {"status": "error", "message": f"yaml parse: {exc}"}
            return self.import_manifest(manifest)
        if p.suffix.lower() == ".py":
            source = p.read_text(encoding="utf-8")
            manifest = {"strategy_id": p.stem, "name": p.stem, "symbols": []}
            return self.import_manifest(manifest, python_source=source)
        return {"status": "error", "message": "unsupported file type"}

    def _validate_manifest(self, manifest: dict) -> list[str]:
        errors = []
        if not manifest.get("strategy_id") and not manifest.get("id"):
            errors.append("missing strategy_id")
        if not manifest.get("name"):
            errors.append("missing name")
        return errors

    def _validate_python_ast(self, source: str) -> dict[str, Any]:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return {"status": "error", "message": str(exc)}
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in ALLOWED_IMPORT_ROOTS:
                        violations.append(f"forbidden import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root not in ALLOWED_IMPORT_ROOTS:
                        violations.append(f"forbidden import from: {node.module}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_AST_NAMES:
                    violations.append(f"forbidden call: {node.func.id}")
                elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_AST_NAMES:
                    violations.append(f"forbidden call attribute: {node.func.attr}")
            elif isinstance(node, ast.Attribute):
                val = node.value
                if node.attr in FORBIDDEN_AST_NAMES:
                    violations.append(f"forbidden attribute: {node.attr}")
                if isinstance(val, ast.Name) and val.id in FORBIDDEN_AST_NAMES:
                    violations.append(f"forbidden attribute base: {val.id}")
        if violations:
            return {"status": "error", "violations": violations[:20]}
        return {"status": "ok", "message": "AST sandbox clean — backtest only"}

    def _row_dict(self, r: StrategyRegistry) -> dict:
        return {
            "strategy_id": r.strategy_id,
            "name": r.name,
            "current_stage": r.current_stage,
            "symbols": r.symbols,
            "author_type": r.author_type,
            "updated_at": r.updated_at.isoformat() + "Z" if r.updated_at else None,
        }
