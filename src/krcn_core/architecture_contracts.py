"""Resolve the V1 immutable architecture contracts against real repository evidence.

A frozen contract is only durable while something fails when it is broken. Each
contract in `config/v1-architecture-contracts.json` therefore names the module
symbols, policy values, and specification statements that carry it. Resolving a
contract imports nothing beyond the product package and reads no user data.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .foundation import load_json


CONTRACTS_REF = "config/v1-architecture-contracts.json"
EVIDENCE_KINDS = ("module-symbol", "policy-flag", "policy-members", "document-phrase")


class ArchitectureContractError(ValueError):
    """Raised when the contract record itself cannot be read."""


@dataclass(frozen=True)
class ContractResolution:
    """Resolution state for one frozen contract."""

    contract_id: str
    statement: str
    evidence_count: int
    errors: tuple[str, ...]

    @property
    def satisfied(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "statement": self.statement,
            "evidence_count": self.evidence_count,
            "satisfied": self.satisfied,
            "errors": list(self.errors),
        }


def validate_architecture_contracts(payload: object) -> list[str]:
    """Validate the contract record shape without touching the repository."""

    if not isinstance(payload, dict):
        return ["architecture contract record must be an object"]
    errors: list[str] = []
    if payload.get("schema_ref") != "schemas/v1-architecture-contracts.schema.json":
        errors.append("architecture contract schema reference is invalid")
    if payload.get("schema_version") != 1:
        errors.append("architecture contract schema version is invalid")
    if not isinstance(payload.get("decision_ref"), str) or not payload["decision_ref"]:
        errors.append("architecture contract decision reference is invalid")
    contracts = payload.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        errors.append("architecture contract list is empty")
        return errors

    seen: set[str] = set()
    for index, contract in enumerate(contracts):
        label = f"contracts[{index}]"
        if not isinstance(contract, dict):
            errors.append(f"{label} must be an object")
            continue
        contract_id = contract.get("id")
        if not isinstance(contract_id, str) or not contract_id:
            errors.append(f"{label} id is invalid")
        elif contract_id in seen:
            errors.append(f"{label} id is duplicated: {contract_id}")
        else:
            seen.add(contract_id)
        if not isinstance(contract.get("statement"), str) or not contract["statement"]:
            errors.append(f"{label} statement is invalid")
        evidence = contract.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{label} evidence is empty")
            continue
        for position, item in enumerate(evidence):
            if not isinstance(item, dict):
                errors.append(f"{label}.evidence[{position}] must be an object")
            elif item.get("kind") not in EVIDENCE_KINDS:
                errors.append(f"{label}.evidence[{position}] kind is unsupported")
    return errors


def _module_symbol_errors(evidence: Mapping[str, object], label: str) -> list[str]:
    module_name = evidence.get("module")
    symbols = evidence.get("symbols")
    if not isinstance(module_name, str) or not isinstance(symbols, list):
        return [f"{label} module evidence is invalid"]
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        return [f"{label} module is unavailable: {module_name} ({exc})"]
    return [
        f"{label} missing symbol: {module_name}.{symbol}"
        for symbol in symbols
        if not hasattr(module, symbol)
    ]


def _policy_flag_errors(
    repo_root: Path, evidence: Mapping[str, object], label: str
) -> list[str]:
    policy_ref = evidence.get("policy")
    key = evidence.get("key")
    if not isinstance(policy_ref, str) or not isinstance(key, str):
        return [f"{label} policy evidence is invalid"]
    try:
        policy = load_json(repo_root / Path(policy_ref))
    except ValueError as exc:
        return [f"{label} {exc}"]
    if key not in policy:
        return [f"{label} missing policy key: {policy_ref}#{key}"]
    if "expected" in evidence and policy[key] != evidence["expected"]:
        return [
            f"{label} policy value changed: {policy_ref}#{key} "
            f"is {policy[key]!r}, expected {evidence['expected']!r}"
        ]
    return []


def _policy_members_errors(
    repo_root: Path, evidence: Mapping[str, object], label: str
) -> list[str]:
    policy_ref = evidence.get("policy")
    collection = evidence.get("collection")
    member_key = evidence.get("member_key")
    required = evidence.get("required")
    if (
        not isinstance(policy_ref, str)
        or not isinstance(collection, str)
        or not isinstance(member_key, str)
        or not isinstance(required, list)
    ):
        return [f"{label} policy member evidence is invalid"]
    try:
        policy = load_json(repo_root / Path(policy_ref))
    except ValueError as exc:
        return [f"{label} {exc}"]
    members = policy.get(collection)
    if not isinstance(members, list):
        return [f"{label} missing policy collection: {policy_ref}#{collection}"]
    present = {
        member.get(member_key)
        for member in members
        if isinstance(member, Mapping)
    }
    return [
        f"{label} missing policy member: {policy_ref}#{collection}.{value}"
        for value in required
        if value not in present
    ]


def _document_phrase_errors(
    repo_root: Path, evidence: Mapping[str, object], label: str
) -> list[str]:
    document_ref = evidence.get("document")
    phrase = evidence.get("phrase")
    if not isinstance(document_ref, str) or not isinstance(phrase, str):
        return [f"{label} document evidence is invalid"]
    document = repo_root / Path(document_ref)
    if not document.is_file():
        return [f"{label} missing document: {document_ref}"]
    if phrase not in document.read_text(encoding="utf-8"):
        return [f"{label} missing statement in {document_ref}: {phrase}"]
    return []


def resolve_architecture_contracts(repo_root: Path) -> list[ContractResolution]:
    """Resolve every frozen contract against current repository evidence."""

    root = repo_root.resolve()
    try:
        payload = load_json(root / Path(CONTRACTS_REF))
    except ValueError as exc:
        raise ArchitectureContractError(str(exc)) from exc
    shape_errors = validate_architecture_contracts(payload)
    if shape_errors:
        raise ArchitectureContractError("; ".join(shape_errors))

    resolutions: list[ContractResolution] = []
    for contract in payload["contracts"]:
        contract_id = contract["id"]
        errors: list[str] = []
        for position, evidence in enumerate(contract["evidence"]):
            label = f"{contract_id}.evidence[{position}]"
            kind = evidence["kind"]
            if kind == "module-symbol":
                errors.extend(_module_symbol_errors(evidence, label))
            elif kind == "policy-flag":
                errors.extend(_policy_flag_errors(root, evidence, label))
            elif kind == "policy-members":
                errors.extend(_policy_members_errors(root, evidence, label))
            else:
                errors.extend(_document_phrase_errors(root, evidence, label))
        resolutions.append(
            ContractResolution(
                contract_id=contract_id,
                statement=contract["statement"],
                evidence_count=len(contract["evidence"]),
                errors=tuple(errors),
            )
        )
    return resolutions


def validate_architecture_contracts_repository(repo_root: Path) -> list[str]:
    """Return every unmet contract evidence error for doctor and verification."""

    try:
        resolutions = resolve_architecture_contracts(repo_root)
    except ArchitectureContractError as exc:
        return [str(exc)]
    errors: list[str] = []
    for resolution in resolutions:
        errors.extend(resolution.errors)
    decision = load_json(repo_root.resolve() / Path(CONTRACTS_REF))["decision_ref"]
    if not (repo_root.resolve() / Path(decision)).is_file():
        errors.append(f"missing architecture decision record: {decision}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve the V1 immutable architecture contracts"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root",
    )
    parser.add_argument("--format", choices=("json", "text"), default="text")
    return parser


def _render_text(resolutions: Sequence[ContractResolution]) -> str:
    lines = ["V1 architecture contracts:"]
    for resolution in resolutions:
        state = "ok" if resolution.satisfied else "unmet"
        lines.append(
            f"- {resolution.contract_id}: {state} "
            f"({resolution.evidence_count} evidence)"
        )
        lines.extend(f"    {error}" for error in resolution.errors)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        resolutions = resolve_architecture_contracts(args.repo)
    except ArchitectureContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(
            json.dumps(
                {"contracts": [item.as_dict() for item in resolutions]},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_render_text(resolutions))

    unmet = [item for item in resolutions if not item.satisfied]
    if unmet:
        for item in unmet:
            print(f"ERROR: unmet contract: {item.contract_id}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
