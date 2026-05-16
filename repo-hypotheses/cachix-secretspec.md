# Triage Graph: cachix/secretspec

## Repo Profile
- Stars: 443
- Default branch: main
- Language: Rust (workspace: secretspec, secretspec-derive, examples/derive)
- Solo maintainer: domenkozar (Domen Kozar, cachix founder)
- No CONTRIBUTING.md
- Active: PRs merging from external contributors regularly
- Open PRs: 2 (PR #58 SOPS provider, PR #24 Bitwarden — both stale)

## MAINTAINER PREFERENCES
- Prefers explicit over implicit (rejected PR #75 for implicit profile fallback)
- Happy to merge external providers (protonpass, vault, awssm all merged from contributors)
- Bug fixes get fast merges
- Uses Claude for development (mentioned in commit history)
- Responsive to issues and PRs

## Issue Scan (2026-05-11)

### Actionable
| # | Title | Label | Score | Status |
|---|-------|-------|-------|--------|
| - | test_generate_command_empty_output fails on macOS | (unfiled) | 10 | TRIAGED — branch fix/portable-empty-command-test |

### Blocked/Deferred
| # | Title | Reason |
|---|-------|--------|
| 73 | Escape characters in secrets | Blocked on upstream dotenvy#113 |
| 79 | Configuring providers in secretspec.toml | Design discussion, maintainer undecided |

### Feature Requests (not actionable for first contrib)
| # | Title | Label |
|---|-------|-------|
| 84 | Cloudflare secret support | provider |
| 65 | NixOS integration | enhancement |
| 64 | Out-of-tree providers via gRPC | provider |
| 49 | Incomplete GH action example | enhancement |
| 42 | Mention fnox | documentation |
| 41 | systemd-credentials provider | provider |
| 29 | SDK typed secret names | enhancement |
| 17 | Support Infisical | provider |
| 14 | Azure Key Vault | provider |
| 13 | Support Cerby | provider |
| 11 | Secret lifetimes | enhancement |
| 5 | Support SOPS | provider (PR #58 open) |
| 4 | Support Age | provider |

## Competing PRs
- PR #58: SOPS provider (read-only) — linked to issue #5, maintainer aware
- PR #24: Bitwarden — stale (10 months), BWS already in main

## Kill List
(none)
