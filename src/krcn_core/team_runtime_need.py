"""Evidence-only gate for the optional multi-machine team runtime."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from .foundation import load_json
from .json_documents import canonical_json_bytes

class TeamRuntimeNeedError(ValueError): pass

@dataclass(frozen=True)
class TeamRuntimeAssessment:
    payload: Mapping[str, object]
    def as_dict(self) -> dict[str, object]: return json.loads(json.dumps(self.payload))

def load_team_runtime_need_policy(repo_root: Path) -> dict[str, object]:
    value = load_json(repo_root / "config" / "team-runtime-need-gate.json")
    if value.get("schema_ref") != "schemas/team-runtime-need-policy.schema.json" or value.get("schema_version") != 1 or value.get("authority_granted") is not False:
        raise TeamRuntimeNeedError("team runtime need policy is invalid")
    return value

def assess_team_runtime_need(policy: Mapping[str, object], *, machine_count: int, concurrent_worker_count: int, cross_machine_claim_required: bool, enterprise_needs: Sequence[str], migration_owner_assigned: bool, rollback_owner_assigned: bool, operating_budget_approved: bool) -> TeamRuntimeAssessment:
    booleans = (cross_machine_claim_required, migration_owner_assigned, rollback_owner_assigned, operating_budget_approved)
    if isinstance(machine_count, bool) or not isinstance(machine_count, int) or machine_count < 1 or isinstance(concurrent_worker_count, bool) or not isinstance(concurrent_worker_count, int) or concurrent_worker_count < 1 or any(not isinstance(value, bool) for value in booleans):
        raise TeamRuntimeNeedError("team runtime evidence is invalid")
    needs = sorted(set(enterprise_needs))
    allowed_needs = set(policy["qualifying_enterprise_needs"])
    if any(not isinstance(item, str) or item not in allowed_needs for item in needs):
        raise TeamRuntimeNeedError("enterprise need is not recognized")
    reasons: list[str] = []
    if machine_count < int(policy["minimum_machine_count"]): reasons.append("single-machine-sufficient")
    if not cross_machine_claim_required: reasons.append("no-cross-machine-claim")
    if not needs: reasons.append("no-enterprise-runtime-need")
    if not migration_owner_assigned: reasons.append("migration-owner-missing")
    if not rollback_owner_assigned: reasons.append("rollback-owner-missing")
    if not operating_budget_approved: reasons.append("operating-budget-missing")
    eligible = not reasons
    identity = {"machine_count": machine_count, "concurrent_worker_count": concurrent_worker_count, "cross_machine_claim_required": cross_machine_claim_required, "enterprise_needs": needs, "migration_owner_assigned": migration_owner_assigned, "rollback_owner_assigned": rollback_owner_assigned, "operating_budget_approved": operating_budget_approved, "decision": "eligible-for-separate-plan" if eligible else "deferred", "reason_codes": reasons or ["need-gate-satisfied"], "postgresql_required": eligible, "migration_allowed": False, "provider_calls": 0, "authority_granted": False}
    digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return TeamRuntimeAssessment({"schema_ref": "schemas/team-runtime-assessment.schema.json", "schema_version": 1, "assessment_id": digest, **identity, "assessment_digest": digest})
