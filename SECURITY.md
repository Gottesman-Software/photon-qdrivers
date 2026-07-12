# Security Policy

Photon-QDrivers is early infrastructure for emulator and hardware driver paths.
Security reports are welcome, especially around credentials, hardware access,
transport protocols, unsafe defaults, dependency risks, and denial-of-service
conditions in parsers or backends.

## Supported Versions

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Published releases | Best effort |

## Reporting A Vulnerability

Do not open a public issue for vulnerabilities involving credentials, private
hardware endpoints, unsafe hardware control, or exploitable crashes.

Report privately to the project owner, or use GitHub private vulnerability
reporting if it is enabled for the repository. Include:

- Affected commit, release, or package version.
- Reproduction steps.
- Expected and actual behavior.
- Impact assessment.
- Suggested fix, if known.

## Hardware Safety

Hardware adapters must default to conservative behavior:

- No pulse, detector, FPGA, or transport operation should run without explicit
  initialization and capability checks.
- Backends must validate mode counts, shot counts, operation names, timing
  windows, and device limits before submission.
- Real device endpoints and credentials must be loaded from secure local
  configuration, not committed to the repository.

## Disclosure

Maintainers will acknowledge reports as soon as practical, coordinate fixes, and
credit reporters when requested and appropriate.
