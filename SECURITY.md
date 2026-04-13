# Security policy

The maintainers of [NU-Tonic/nutonic](https://github.com/NU-Tonic/nutonic) take security reports seriously. This document describes how to report vulnerabilities and what to expect.

## Supported versions

Security fixes are applied to the **default branch** (`main`) of this repository. Release branches or store builds may lag; ask in your report if you need a specific backport.

## Reporting a vulnerability

**Please do not** file a public GitHub issue for undisclosed security problems (including suspected secret leaks or authentication bypasses).

Instead, use **private reporting**:

1. Open **[GitHub → Security → Report a vulnerability](https://github.com/NU-Tonic/nutonic/security/advisories/new)** for this repository (recommended), or  
2. Use the repository **Security** tab and follow GitHub’s guided flow.

If GitHub private reporting is unavailable (e.g. fork without Security enabled), contact the maintainers through an **organization-approved private channel** only—do not paste exploit details in public issues, discussions, or pull requests.

### What to include

- A short description of the issue and its **impact** (confidentiality / integrity / availability).
- **Affected component** (e.g. `nutonic/` client, `inference/`, CI workflow, dependency) and how you believe it can be triggered.
- **Reproduction steps** or a proof-of-concept where safe to share.
- Your **preferred attribution** (name/handle or anonymous).

### Scope (in scope for this repo)

Examples include, but are not limited to:

- Authentication, session handling, or authorization flaws in **this** codebase or documented reference APIs.
- Insecure handling of user data, tokens, or **secrets** in repo-owned code or configs.
- CI/CD or automation that could leak credentials or allow unauthorized repository access.
- Dependency vulnerabilities **when exploitation goes through code paths we ship or run** in this repository (still report upstream when appropriate).

**Out of scope or report elsewhere:** vulnerabilities in third-party services should be reported to those vendors. Generic dependency alerts are welcome as advisories if they affect shipped artifacts; for routine bumps, a normal PR may suffice after coordinated disclosure.

## Our response

- We aim to **acknowledge** valid reports within a **few business days** (not a legal SLA).
- We will work on a **fix** and coordinated disclosure where applicable, and may request follow-up information.
- **Credit:** We are happy to credit reporters in release notes or advisories unless you prefer to remain anonymous.

## Hardening and automation in this repository

- **CodeQL** and **Gitleaks** run in CI (see [`.github/workflows/security-codeql-and-secrets.yml`](.github/workflows/security-codeql-and-secrets.yml)).
- Optional local **secret scanning** before commit: [`.pre-commit-config.yaml`](.pre-commit-config.yaml) (see [`CONTRIBUTING.md`](CONTRIBUTING.md)).

These checks **do not replace** responsible disclosure of new issues.

## Secrets and sensitive data

- Do not commit API keys, tokens, `.env` files, or personal `local.properties` values. Follow [`.gitignore`](.gitignore) and [`CONTRIBUTING.md`](CONTRIBUTING.md).
- If you **accidentally pushed a secret**, rotate the credential immediately, remove it from history if required by your process, and still report via private channels if the exposure could harm users or infrastructure.

Thank you for helping keep NU:TONIC and its users safe.
