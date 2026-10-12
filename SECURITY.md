# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| latest release (`v*`) | ✅ |
| older releases | ❌ — please upgrade |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Use GitHub's private reporting instead:
**https://github.com/Huntz-Group/VxDesk/security/advisories/new**

We aim to acknowledge reports within 3 business days and will coordinate disclosure
with you after a fix is available.

## Scope notes

VxDesk is a **local automation tool that controls your mouse and keyboard** — that power
is the point. The threat model we care most about:

- **Remote services** (off by default): agent-token authentication, TLS configuration,
  and bind-address exposure are the sensitive surface. See `docs/remote-services.md`.
- **Secrets on disk**: the AI-assistant API key is stored locally and is never returned
  by any endpoint or written to logs. Report any path where it could leak.
- **Workflow files** are plain JSON and can contain what you type — including, if you
  ignore the warning, credentials recorded by the recorder. Treat them as sensitive.

Bugs that let a *workflow you downloaded* or a *remote client* escape the documented
trust boundaries (e.g. bypassing dry-run, token checks, or the bind address) are
in scope and taken seriously.
