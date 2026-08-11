# External source no-copy contract

## Rule

KRCN Core integrates a project by keeping a logical source binding to its existing directory. It does not import the project tree into the KRCN user home.

## Allowed reads

The local discovery adapter may read directory metadata and permitted file bytes to produce redacted evidence, a file catalog, and a path-independent tree digest. It skips policy-blocked paths, symbolic links, oversized files, unstable files, and unreadable entries.

## Forbidden effects

- Creating project files under the KRCN user home.
- Copying or moving source files during onboarding, discovery, rescan, backup, restore, migration, or rebind.
- Writing an identity marker into the external project.
- Following a symbolic link outside the selected source root.
- Treating a source path as permission to modify project content.
- Including the physical locator in portable manifests or public summaries.

## Identity evidence

`krcn-discovery-tree-sha256-v1` is computed from sorted, relative file evidence produced by the approved read-only discovery policy. The identity contains a logical source ID, binding ID, tree digest, and file count. It contains neither the physical path nor file contents.

The digest is exact evidence, not a permanent repository identifier. A changed project requires a fresh reviewed discovery state. Rebind uses the last accepted evidence and stops on mismatch instead of guessing.

