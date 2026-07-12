# Hardware Adapter Foundation

Photon-QDrivers separates hardware execution into a shared cloud job contract and
thin vendor adapters.

## Shared Classes

- `CloudHardwareBackend`: reusable base class for hardware SDK adapters.
- `CloudJobClient`: protocol that wraps a vendor SDK client.
- `CloudJobSnapshot`: provider-neutral remote job snapshot.
- `CloudJobState`: normalized cloud job lifecycle state.

Vendor adapters should subclass `CloudHardwareBackend`, define identity and
capability limits, then implement `_create_client()` to return a
`CloudJobClient`.

## Client Contract

`CloudJobClient` exposes four methods:

- `submit_job(payload)`: submit a serialized Photon-QDrivers job.
- `get_job(provider_job_id)`: fetch the latest provider job snapshot.
- `cancel_job(provider_job_id)`: request provider-side cancellation.
- `close()`: release SDK/network resources.

`submit_job()` and `get_job()` may return either `CloudJobSnapshot` or a mapping
with common keys such as `job_id`, `status`, `counts`, `shots`, `metadata`, and
`error`.

## Lifecycle

Provider statuses are normalized into:

- `created`
- `queued`
- `running`
- `completed`
- `failed`
- `cancelled`

The backend base polls non-terminal jobs until completion, failure,
cancellation, or `BackendConfig.timeout_seconds`. On timeout it requests
provider cancellation and raises `JobTimeoutError`.

## Credentials And Config

Hardware credentials are read from `BackendConfig.credentials` or environment
variables:

```bash
PHOTON_QDRIVERS_QUANDELA_TOKEN=...
PHOTON_QDRIVERS_QUANDELA_API_KEY=...
PHOTON_QDRIVERS_XANADU_TOKEN=...
PHOTON_QDRIVERS_XANADU_API_KEY=...
PHOTON_QDRIVERS_XANADU_ACCESS_TOKEN=...
PHOTON_QDRIVERS_XANADU_CLIENT_ID=...
PHOTON_QDRIVERS_XANADU_CLIENT_SECRET=...
PHOTON_QDRIVERS_XANADU_REFRESH_TOKEN=...
```

Common non-secret selectors are also read:

```bash
PHOTON_QDRIVERS_QUANDELA_ENDPOINT=...
PHOTON_QDRIVERS_QUANDELA_DEVICE=qpu:belenos
PHOTON_QDRIVERS_QUANDELA_TIMEOUT_SECONDS=30
PHOTON_QDRIVERS_XANADU_ENDPOINT=...
PHOTON_QDRIVERS_XANADU_PROFILE=production
PHOTON_QDRIVERS_XANADU_TIMEOUT_SECONDS=30
PHOTON_QDRIVERS_XANADU_DEVICE=X8_01
PHOTON_QDRIVERS_XANADU_DEVICE_ID=...
PHOTON_QDRIVERS_XANADU_PROJECT_ID=...
PHOTON_QDRIVERS_XANADU_ORGANIZATION=...
PHOTON_QDRIVERS_XANADU_REGION=...
PHOTON_QDRIVERS_ORCA_TOKEN=...
PHOTON_QDRIVERS_ORCA_API_KEY=...
PHOTON_QDRIVERS_ORCA_ENDPOINT=...
PHOTON_QDRIVERS_ORCA_DEVICE=pt-2
PHOTON_QDRIVERS_ORCA_TIMEOUT_SECONDS=30
```

The prefix changes per backend, for example `PHOTON_QDRIVERS_QUANDELA_TOKEN`.

Secret values must not appear in job metadata, result metadata, exception text,
or logs. Use `BackendConfig.public_dict()` and
`redact_sensitive_mapping()` when returning configuration provenance.

## Quandela Adapter

`quandela` is the first implemented vendor SDK adapter. It uses the optional
`perceval-quandela` package and creates a Perceval `RemoteProcessor` for the
configured platform, for example `qpu:belenos`.

Install it with:

```bash
python -m pip install ".[quandela]"
```

Minimal configuration:

```bash
PHOTON_QDRIVERS_QUANDELA_TOKEN=...
PHOTON_QDRIVERS_QUANDELA_DEVICE=qpu:belenos
```

The adapter accepts the same `BS`, `PS`, and `photon_counting` circuit subset as
the local Perceval backend. Circuits must include `metadata.input_state`, because
Perceval hardware jobs require a concrete Fock input state. Execution uses
`Sampler.sample_count`, maps Perceval job status into `CloudJobState`, supports
provider cancellation when the SDK job exposes `cancel()`, and redacts provider
metadata before returning results.

Useful `BackendConfig.options`:

- `device`, `device_id`, `processor_name`, `qpu`, or `platform`: Perceval remote
  processor name.
- `min_detected_photons`: minimum detected photon filter.
- `max_shots_per_call`: Perceval sampler shot budget per call.
- `poll_interval_seconds`: Photon-QDrivers polling interval.

## Xanadu Legacy Adapter

`xanadu` is implemented as a legacy adapter through Strawberry Fields
`RemoteEngine` and `xanadu-cloud-client`. Xanadu Quantum Cloud is no longer a
public service, so this path is intended for private deployments, archived
environments, or lab endpoints that still expose an XCC-compatible API.

Install it in a compatible legacy Python environment with:

```bash
python -m pip install ".[xanadu]"
```

Minimal configuration:

```bash
PHOTON_QDRIVERS_XANADU_API_KEY=...
PHOTON_QDRIVERS_XANADU_DEVICE=X8_01
```

The adapter creates an `xcc.Connection`, builds a Strawberry Fields `Program`
from the Photon-QDrivers IR, then submits it with `RemoteEngine.run_async`.
Statuses such as `open`, `queued`, `complete`, `failed`, `cancel_pending`, and
`cancelled` are mapped into `CloudJobState`. Result payloads with `output`,
`samples`, or `counts` are normalized into `PhotonicResult.counts`.

Useful `BackendConfig.options`:

- `target`, `device`, `device_id`, or `processor_name`: Strawberry Fields remote
  target, defaulting to `X8_01`.
- `host`, `port`, `tls`, or `BackendConfig.endpoint`: XCC-compatible endpoint.
- `compile_options`: forwarded to `Program.compile()` through
  `RemoteEngine.run_async`.
- `recompile`: whether Strawberry Fields should recompile the program.
- `backend_options`: forwarded to `RemoteEngine`.
- `poll_interval_seconds`: Photon-QDrivers polling interval.

## ORCA Adapter

`orca` is implemented for ORCA-compatible PT-series deployments through two
integration paths:

- a private Python SDK module, selected with
  `BackendConfig.options["sdk_module"]`; or
- a JSON HTTPS endpoint, selected with `BackendConfig.endpoint` or
  `PHOTON_QDRIVERS_ORCA_ENDPOINT`.

Minimal REST-style configuration:

```bash
PHOTON_QDRIVERS_ORCA_TOKEN=...
PHOTON_QDRIVERS_ORCA_ENDPOINT=https://orca.example/api
PHOTON_QDRIVERS_ORCA_DEVICE=pt-2
```

Equivalent Python configuration:

```python
from photonic_driver import BackendConfig, Driver

driver = Driver.load(
    "orca",
    config=BackendConfig(
        backend_name="orca",
        endpoint="https://orca.example/api",
        credentials={"token": "..."},
        options={"device": "pt-2"},
    ),
)
```

For private SDK deployments, configure the SDK module and optional client class:

```python
driver = Driver.load(
    "orca",
    config=BackendConfig(
        backend_name="orca",
        credentials={"token": "..."},
        options={
            "sdk_module": "orca_quantum",
            "client_class": "Client",
            "device": "pt-2",
        },
    ),
)
```

The adapter serializes the Photon-QDrivers circuit IR into a provider payload,
maps provider states into `CloudJobState`, supports timeout/cancellation through
the shared hardware base, and normalizes provider `counts`, `histogram`,
`samples`, or nested `result.counts` payloads into `PhotonicResult.counts`.

Useful `BackendConfig.options`:

- `device`, `device_id`, `target`, `processor_name`, `qpu`, or `platform`: ORCA
  device selector.
- `sdk_module`: private SDK module name. If omitted, Photon-QDrivers attempts
  conservative module names such as `orca_quantum`, `orca_computing`, and
  `orca_sdk`.
- `client_class`: private SDK client class or factory name.
- `submit_method`, `get_method`, `cancel_method`: private SDK method names when
  they differ from common defaults.
- `submit_path`, `job_path_template`, `cancel_path_template`: REST endpoint
  paths, defaulting to `/jobs`, `/jobs/{job_id}`, and `/jobs/{job_id}/cancel`.
- `auth_scheme`, `auth_header`, `auth_prefix`, `api_key_header`: REST
  authentication header controls.
- `http_timeout_seconds`: per-request REST timeout.
- `poll_interval_seconds`: Photon-QDrivers polling interval.

## PsiQuantum Construct / PsiQDK Adapter

`psiquantum` is implemented as a PsiQuantum Construct / PsiQDK software adapter
for fault-tolerant quantum computing workflows. It is not a live PsiQuantum QPU
execution adapter.

Install it with:

```bash
python -m pip install ".[psiquantum]"
```

`psiqdk` is kept as a dedicated optional extra because it may be distributed
through a private or restricted package source. The public `.[hardware]` extra
does not install it.

Minimal resource-estimation job:

```python
from photonic_driver import Driver

driver = Driver.load("psiquantum")

job = driver.compile({
    "type": "photonic_circuit",
    "modes": 2,
    "operations": [
        {"gate": "H", "mode": 0},
        {"gate": "CNOT", "modes": [0, 1]},
        {"measure": "logical_measure", "modes": [0, 1]},
    ],
    "shots": 1,
    "metadata": {
        "model": "resource_estimate",
        "logical_qubits": 2,
    },
})

result = driver.run(job)
print(result.metadata["provider_metadata"]["resources"])
```

The adapter builds a Workbench `QPU`, optionally maps supported logical
operations when Workbench exposes matching methods, and calls
`psiqdk.workbench.qre.resource_estimator(qpu).resources()`. Resource estimates
are returned in `PhotonicResult.metadata["provider_metadata"]["resources"]`.

Supported `metadata.model` values:

- `resource_estimate`: run PsiQDK resource estimation.
- `simulate`: run a Workbench simulation method when exposed by the installed
  SDK.
- `workbench_program`: reserved for custom Workbench-program workflows and
  currently follows the resource-estimation path.

Useful `BackendConfig.options`:

- `sdk_module`: SDK package name, defaulting to `psiqdk`.
- `workbench_module`: Workbench module name, defaulting to
  `psiqdk.workbench`.
- `qre_module`: resource-estimation module name, defaulting to
  `psiqdk.workbench.qre`.
- `logical_qubits`: default logical-qubit count when not set in circuit
  metadata.
- `qpu_options`: mapping forwarded to the Workbench `QPU` constructor.

## Current Hardware Targets

`quandela` now has an optional Perceval-based hardware SDK adapter.

`xanadu` now has an optional legacy Strawberry Fields/XCC adapter for
non-public compatible endpoints.

`orca` now has private SDK and configurable REST endpoint integration paths.

`psiquantum` now has a PsiQDK / Construct software adapter for local FTQC
resource estimation and simulation. Live PsiQuantum QPU execution is still a
future integration point.
