# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in Voxtra, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please report vulnerabilities by emailing:

**security@rexploreresearchlabs.com**

Or use [GitHub's private vulnerability reporting](https://github.com/rexplore-ai/voxtra/security/advisories/new).

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix and disclosure**: Coordinated with reporter

### Scope

The following are in scope:

- Voxtra core framework (`src/voxtra/`)
- AI provider integrations (credential handling, API key exposure)
- Telephony adapter security (ARI authentication, SIP credentials)
- Media transport security (WebSocket connections)
- Configuration file handling (environment variable injection)

### Out of scope

- Vulnerabilities in third-party dependencies (report upstream, but let us know)
- Asterisk/FreeSWITCH/LiveKit server configuration issues
- Denial of service via expected high call volume

## Security Best Practices for Voxtra Users

- **Never hardcode API keys** in source code. Use environment variables or a secrets manager.
- **Use TLS** for all ARI and WebSocket connections in production.
- **Restrict ARI access** to localhost or trusted networks.
- **Rotate credentials** regularly for AI provider APIs and telephony systems.
- **Keep Voxtra updated** to the latest version for security patches.
