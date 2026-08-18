# Local Observation Reconciliation

KRCN may observe an already registered project source read-only and reconcile its own bounded local state without asking the user to approve the same refresh twice. The caller still expresses mutation intent with `apply`; planning remains read-only when `apply` is false.

The exemption is limited to reversible create or update effects for discovery-managed project metadata, source state, integration state, fixed project knowledge records, and rebuildable local indexes under `KRCN_HOME`. It never deletes or moves user data. A source deletion is represented by an updated observed inventory and rebuilt contentless index; KRCN does not delete the source file.

Project identity, name, description, status, source bindings, and policies are preserved from the existing record. Source observation does not infer Work Graph completion or change task status. Work Graph changes require an explicit work operation, and destructive work-data changes retain their normal gate.

New registration, source-tree writes, policy or ownership changes, external providers, databases, Git operations, secrets, cross-project effects, destructive user-data operations, and any target outside the reconciliation allowlist keep the existing exact-plan and explicit-approval boundary.
