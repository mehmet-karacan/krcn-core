# Release trust and integrity

## Trust model

Phase 3 accepts only local release directories. Remote discovery and download are outside the merge engine. Every release operation requires a canonical manifest SHA-256 digest obtained through an independent trusted channel and supplied explicitly by the caller.

The digest is a trust pin. The engine canonicalizes the strictly validated manifest, computes SHA-256, and compares it with the supplied pin using constant-time comparison. A digest printed from the same untrusted release directory is inspection information only and must not be treated as independent trust evidence.

## Payload binding

Every upsert entry binds a portable path, exact byte size, and SHA-256 digest. Every delete entry binds a portable path and the expected previous managed SHA-256 digest. The payload directory must contain exactly the declared upsert files and no other regular file or symbolic link.

All declared paths must resolve to `core` ownership. Release payloads cannot contain runtime, user-data, derived, secrets, or unmanaged targets.

## Safety scan

Before diff or apply, the payload passes the repository import policy. Secret patterns, machine-specific paths, blocked file types, invalid text encoding, and prohibited Unicode long-dash characters reject the release.

## Compatibility

The active installation version must be inside the manifest's inclusive compatibility range. The merge path cannot apply a lower core version. Rollback uses a verified local deployment backup and does not reinterpret an older release as a merge.

## Execution boundary

Manifest values are data. File names, migration identifiers, derived action identifiers, and payload contents are never executed as commands. Migration and derived behavior must resolve to trusted handlers already registered in KRCN Core code.

## Future signing

The trust-pin contract is the Phase 3 offline baseline. A future signature layer may add public-key authenticity without weakening digest pinning, payload evidence, ownership checks, or explicit caller trust.
