# Public source and private test provenance

The public branch preserves the original GPL donor history at
`e2aca2ca89650a68df3184918f93e37fce933f2e`, then imports the reviewed safe kernel
development tree. The current tree intentionally excludes donor installers,
desktop agents, VM/USB-IP helpers, backups, and host reports. Those historical
files remain in their already-public upstream ancestry; no donor tool is run
as part of this project. Copyright, SPDX attribution, and the GPL license are
preserved.

Local development and hardware tests preceded publication. Original local commit
IDs in the dated evidence, including the four-byte fix `f79493e` and physical
success record `2edfd7f`, are traceability identifiers, not public commit links.
The full local development history is retained privately; only the separately
sanitized public branch is intended for publication. This avoids publishing
personal checkout paths and private commit metadata from intermediate revisions.
Do not push private branches, all tags, or a mirror of the local repository.

The successful kernel code is unchanged by publication. Shell wrappers resolve
their artifact paths from their own reviewed checkout with quoted arguments;
their exact hashes, descriptor checks, USB selectors, review tokens, and fault
guards remain intact. They are historical one-session tests, not installers or
portable loading commands. Path-resolution tests use a synthetic directory with
spaces and execute only the pure prologue, never a privileged or USB operation.

Personal home prefixes are normalized to `$REPO` in command transcripts. Device
paths/numbers, kernel versions, timings, protocol bytes, and artifact hashes are
retained because they establish the actual test boundary; none is a stable device
identity. Monitor serials, hostnames, credentials, raw USB/kernel logs, screenshots,
downloaded packages/captures, and compiled artifacts are excluded from new public
commits. Ignored local artifacts retain the detailed private evidence and working
binary; a public checkout must build and validate its own matching artifact.

The public report distinguishes firmware/capture agreement, compiler/policy
checks, successful transport, and user-confirmed physical output. It makes no
claim that the package is permanently installed or that future roadmap items
are implemented. A release must repeat the tree and commit-metadata audit before
publishing new files, binaries, logs, or additional refs.
