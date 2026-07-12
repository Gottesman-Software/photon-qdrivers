# Plugin System

Photon-QDrivers uses a lightweight plugin registry so optional capabilities can
be attached without making the core package depend on every simulator, decoder,
vendor SDK, or lab-specific hardware stack.

## Current Registry

The Python API exposes:

- `register_plugin(plugin)`
- `list_plugins()`
- `driver.plugins.get(name)`
- `driver.plugins.describe()`

A plugin must expose a non-empty string `name`. It may also expose `role` and
`description` metadata.

## SchroSIM

`SchroSIMPlugin` is a placeholder for a future photonic simulator adapter. It
should eventually translate Photon-QDrivers symbolic circuits or intermediate
representations into SchroSIM inputs, invoke the simulator, and normalize
results back into the standard result schema.

The placeholder intentionally raises `NotImplementedError` when compile logic is
called. This keeps the extension point visible without importing an unavailable
external package.

## LiDMaS+

`LiDMaSPlugin` is a placeholder for a future decoder adapter. It should
eventually accept detector outputs or measurement records and return decoded
logical information, diagnostics, and confidence metadata.

The placeholder intentionally raises `NotImplementedError` when decode logic is
called.

## Vendor Backends

Vendor backends should be implemented as backend classes, not as hard imports in
the core driver. The initial tree includes placeholder modules for:

- Xanadu
- Quandela
- ORCA Computing

Future backends should declare capabilities clearly and fail early when required
SDKs, credentials, devices, or transport layers are unavailable.

Backends are distinct from plugins: a backend executes jobs, while a plugin may
provide a simulator bridge, decoder, compiler pass, calibration utility, or
vendor-specific helper.
