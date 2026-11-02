# Security policy

## Reporting
Please report vulnerabilities **privately** via GitHub Security Advisories on this repository (Security → Report a vulnerability), or email SECURITY_CONTACT@example.com
<!-- TODO(maintainer): replace the contact address above before publishing -->. Do not open public issues for exploitable bugs. We aim to acknowledge within 7 days.

## Scope
Sandbox escapes, permission bypasses, privacy-mode bypasses (data sent remotely when it should be blocked), secret leakage to logs/prompts/frontend,
unauthenticated access to the local API, plugin manifest abuse.

## Out of scope / known limits
See "Residual risks" in docs/PRIVACY_AND_SECURITY.md (e.g. approved commands run with user rights; no OS sandbox).

## Supported versions
Only the latest release (pre-1.0).
