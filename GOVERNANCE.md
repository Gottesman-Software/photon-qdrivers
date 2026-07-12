# Governance

Photon-QDrivers currently uses maintainer-led governance.

## Maintainers

Maintainers are responsible for:

- Protecting the public API direction.
- Reviewing code, documentation, tests, and benchmark claims.
- Keeping hardware-facing changes conservative and auditable.
- Deciding whether dependencies belong in core or optional adapters.
- Enforcing the code of conduct.

## Decision Process

Small technical changes can be accepted through normal pull request review.
Larger changes should start as an issue or design note, especially when they
affect:

- Public Python APIs.
- Backend contracts.
- C++ runtime or HAL interfaces.
- FPGA register maps, command streams, or timing behavior.
- Vendor adapter architecture.
- Benchmark methodology.

## Vendor And Emulator Neutrality

Photon-QDrivers should not privilege one vendor or emulator by hard-coding it
into the core path. Vendor SDKs and simulator integrations should remain optional
adapters unless there is a clear reason to promote a dependency.
