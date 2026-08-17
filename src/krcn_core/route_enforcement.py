"""Measured, adjacent-only adaptive route enforcement rollout."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .foundation import load_json
from .json_documents import canonical_json_bytes


STAGES = ("shadow", "advisory", "project-opt-in", "read-only", "mutating", "default")


class RouteEnforcementError(ValueError): pass


@dataclass(frozen=True)
class RouteEnforcementDecision:
    payload: Mapping[str, object]
    def as_dict(self) -> dict[str, object]: return json.loads(json.dumps(self.payload))


def load_route_enforcement_policy(repo_root: Path) -> dict[str, object]:
    value = load_json(repo_root / "config" / "route-enforcement.json")
    required = {"schema_ref", "schema_version", "stages", "maximum_mismatch_rate_ppm", "minimum_observation_count", "project_opt_in_from_stage", "mutation_from_stage", "rollback_required", "authority_granted"}
    if set(value) != required or tuple(value["stages"]) != STAGES or value["rollback_required"] is not True or value["authority_granted"] is not False:
        raise RouteEnforcementError("route enforcement policy is invalid")
    return value


def decide_route_enforcement(policy: Mapping[str, object], *, current_stage: str, requested_stage: str, observation_count: int, mismatch_count: int, project_opt_in: bool) -> RouteEnforcementDecision:
    if current_stage not in STAGES or requested_stage not in STAGES or not isinstance(observation_count, int) or not isinstance(mismatch_count, int) or observation_count < 0 or mismatch_count < 0 or mismatch_count > observation_count or not isinstance(project_opt_in, bool):
        raise RouteEnforcementError("route enforcement inputs are invalid")
    current = STAGES.index(current_stage); requested = STAGES.index(requested_stage)
    distance = requested - current
    reasons: list[str] = []
    direction = "hold" if distance == 0 else ("promote" if distance > 0 else "rollback")
    if abs(distance) > 1: reasons.append("adjacent-stage-required")
    rate = 0 if observation_count == 0 else (mismatch_count * 1_000_000) // observation_count
    if direction == "promote" and observation_count < int(policy["minimum_observation_count"]): reasons.append("insufficient-observations")
    if direction == "promote" and rate > int(policy["maximum_mismatch_rate_ppm"]): reasons.append("mismatch-threshold")
    if requested >= STAGES.index(str(policy["project_opt_in_from_stage"])) and not project_opt_in: reasons.append("project-opt-in-required")
    allowed = not reasons
    identity = {"current_stage": current_stage, "requested_stage": requested_stage, "direction": direction, "observation_count": observation_count, "mismatch_count": mismatch_count, "mismatch_rate_ppm": rate, "project_opt_in": project_opt_in, "allowed": allowed, "reason_codes": sorted(reasons), "rollback_available": True, "mutation_allowed": allowed and requested >= STAGES.index(str(policy["mutation_from_stage"])), "authority_granted": False}
    digest = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return RouteEnforcementDecision({"schema_ref": "schemas/route-enforcement-decision.schema.json", "schema_version": 1, "decision_id": digest, **identity, "decision_digest": digest})
