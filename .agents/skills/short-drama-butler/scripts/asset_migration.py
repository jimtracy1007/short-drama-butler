#!/usr/bin/env python3
"""Create, execute, and roll back hash-verified short-drama asset migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AssetMigrationError(RuntimeError):
    """Raised when a migration cannot be completed safely."""


KINDS = {"characters", "scenes", "props"}


def _relative_path(value: str, field: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise AssetMigrationError(f"{field}必须是项目内的相对路径：{value}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _destination(specification: dict[str, str]) -> Path:
    kind = specification["kind"]
    if kind not in KINDS:
        raise AssetMigrationError(f"未知素材类别：{kind}")
    for field in ("asset_id", "slug", "variant", "scope"):
        if not specification.get(field):
            raise AssetMigrationError(f"缺少素材字段：{field}")

    filename = f"{specification['asset_id']}_{specification['slug']}/{specification['variant']}.png"
    scope = specification["scope"]
    if scope == "global":
        return Path("assets/global") / kind / filename
    if scope == "pending":
        return Path("assets/pending") / kind / filename
    if scope.startswith("season-"):
        return Path("assets/seasons") / scope / kind / filename
    if scope.startswith("episode-"):
        return Path("assets/episodes") / scope / kind / filename
    raise AssetMigrationError(f"未知素材范围：{scope}")


def build_plan(project_root: Path, specifications: list[dict[str, str]]) -> dict[str, Any]:
    """Build a preflight plan without changing any source files."""
    root = project_root.resolve()
    records: list[dict[str, str]] = []
    seen_sources: set[Path] = set()
    seen_destinations: set[Path] = set()

    for specification in specifications:
        source_rel = _relative_path(specification["source"], "source")
        source = root / source_rel
        if not source.is_file():
            raise AssetMigrationError(f"找不到源素材：{source_rel}")
        destination_rel = _destination(specification)
        destination = root / destination_rel
        if source_rel in seen_sources:
            raise AssetMigrationError(f"重复源素材：{source_rel}")
        if destination_rel in seen_destinations:
            raise AssetMigrationError(f"重复目标：{destination_rel}")
        if destination.exists():
            raise AssetMigrationError(f"目标已存在：{destination_rel}")
        seen_sources.add(source_rel)
        seen_destinations.add(destination_rel)
        records.append(
            {
                "source": source_rel.as_posix(),
                "destination": destination_rel.as_posix(),
                "asset_id": specification["asset_id"],
                "kind": specification["kind"],
                "scope": specification["scope"],
                "sha256": _sha256(source),
                "status": "planned",
            }
        )

    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }


def execute_plan(project_root: Path, plan: dict[str, Any]) -> Path:
    """Move every planned asset only after the whole plan passes verification."""
    root = project_root.resolve()
    records = plan.get("records", [])
    if not records:
        raise AssetMigrationError("迁移计划不含任何素材")

    for record in records:
        source = root / _relative_path(record["source"], "source")
        destination = root / _relative_path(record["destination"], "destination")
        if not source.is_file():
            raise AssetMigrationError(f"源素材已变化或不存在：{record['source']}")
        if destination.exists():
            raise AssetMigrationError(f"目标已存在：{record['destination']}")
        if _sha256(source) != record["sha256"]:
            raise AssetMigrationError(f"源素材哈希已变化：{record['source']}")

    for record in records:
        source = root / record["source"]
        destination = root / record["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        if _sha256(destination) != record["sha256"]:
            raise AssetMigrationError(f"移动后哈希不一致：{record['destination']}")
        record["status"] = "moved"

    ledger_path = root / "project-settings" / "migration-ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ledger_path


def rollback(project_root: Path, ledger_path: Path) -> None:
    """Restore all assets named in a ledger, in reverse move order."""
    root = project_root.resolve()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    records = ledger.get("records", [])
    for record in reversed(records):
        source = root / _relative_path(record["source"], "source")
        destination = root / _relative_path(record["destination"], "destination")
        if record.get("status") != "moved":
            continue
        if source.exists() or not destination.is_file():
            raise AssetMigrationError(f"无法安全回滚：{record['destination']}")
        if _sha256(destination) != record["sha256"]:
            raise AssetMigrationError(f"回滚前哈希不一致：{record['destination']}")
        source.parent.mkdir(parents=True, exist_ok=True)
        destination.replace(source)
        record["status"] = "rolled_back"
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "execute", "rollback"))
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--specifications", type=Path, help="JSON array of source-to-asset mappings")
    parser.add_argument("--plan", type=Path, help="JSON plan produced by preflight")
    parser.add_argument("--ledger", type=Path, help="migration-ledger.json to restore")
    args = parser.parse_args()

    if args.command == "preflight":
        if not args.specifications or not args.plan:
            parser.error("preflight需要 --specifications 和 --plan")
        specifications = json.loads(args.specifications.read_text(encoding="utf-8"))
        plan = build_plan(args.project_root, specifications)
        args.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    if args.command == "execute":
        if not args.plan:
            parser.error("execute需要 --plan")
        execute_plan(args.project_root, json.loads(args.plan.read_text(encoding="utf-8")))
        return
    if not args.ledger:
        parser.error("rollback需要 --ledger")
    rollback(args.project_root, args.ledger)


if __name__ == "__main__":
    main()
