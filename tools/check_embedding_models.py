#!/usr/bin/env python3
"""Probe an explicit local embedding integration with synthetic text only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from krcn_core.embedding_adapter import (  # noqa: E402
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingAdapter,
    create_embedding_provider_request,
)
from krcn_core.embedding_models import (  # noqa: E402
    load_embedding_model_catalog,
    parse_embedding_integration,
)
from krcn_core.integrations import parse_integration_metadata  # noqa: E402
from krcn_core.information_records import canonical_json  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.provider_gate import (  # noqa: E402
    ProviderApproval,
    load_provider_gate_policy,
)
from krcn_core.secret_provider import OpenCodeSecretProvider  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check approved embedding model access without project data",
    )
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--integration-id", required=True)
    parser.add_argument("--opencode-config", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan")
    parser.add_argument("--approval-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo.resolve()
    store = LocalWorkspaceStore(
        args.data_root.resolve(),
        OwnershipResolver.from_repository(repo_root),
    )
    stored = store.read("integrations", args.integration_id)
    if stored is None:
        print("ERROR: embedding integration is unavailable", file=sys.stderr)
        return 2
    catalog = load_embedding_model_catalog(repo_root)
    integration = parse_embedding_integration(
        parse_integration_metadata(dict(stored.payload)),
        catalog,
    )
    requests = []
    for profile_id in integration.model_profile_ids:
        profile = catalog.profile(profile_id)
        request = create_embedding_provider_request(
            profile,
            integration,
            data_category="synthetic-test",
            session_id=args.session_id,
        )
        requests.append((profile, request))
    plan_identity = {
        "operation": "embedding.synthetic-access-check",
        "integration_id": integration.integration_id,
        "selection_id": catalog.selection_id,
        "request_ids": [request.request_id for _, request in requests],
        "synthetic_input_sha256": hashlib.sha256(
            b"KRCN synthetic embedding access check."
        ).hexdigest(),
    }
    plan_id = hashlib.sha256(canonical_json(plan_identity)).hexdigest()
    plan_summary = {
        "plan_id": plan_id,
        "integration": integration.public_summary(),
        "synthetic_input_only": True,
        "provider_requests": [request.public_summary() for _, request in requests],
        "network_effects": len(requests),
        "applied": False,
    }
    if not args.apply:
        print(json.dumps(plan_summary, ensure_ascii=False, indent=2))
        return 0
    if args.expected_plan != plan_id:
        print("ERROR: apply requires the exact plan id", file=sys.stderr)
        return 2
    if not isinstance(args.approval_id, str) or not args.approval_id.strip():
        print("ERROR: apply requires an approval id", file=sys.stderr)
        return 2
    adapter = OpenAICompatibleEmbeddingAdapter(
        catalog,
        integration,
        OpenCodeSecretProvider(args.opencode_config.resolve()),
        load_provider_gate_policy(repo_root),
    )
    results = []
    for profile, request in requests:
        approval = ProviderApproval(
            request.request_id,
            request.session_id,
            args.approval_id,
            True,
        )
        try:
            batch = adapter.embed(
                profile.profile_id,
                ["KRCN synthetic embedding access check."],
                request,
                approval=approval,
            )
            results.append({**batch.public_summary(), "accessible": True})
        except EmbeddingProviderError:
            results.append(
                {
                    "profile_id": profile.profile_id,
                    "provider_id": profile.provider_id,
                    "model_id": profile.model_id,
                    "accessible": False,
                    "error_disclosed": False,
                }
            )
    print(
        json.dumps(
            {
                "plan_id": plan_id,
                "schema_version": 1,
                "integration": integration.public_summary(),
                "synthetic_input_only": True,
                "results": results,
                "applied": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if results and all(item["accessible"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
