# Examples

These examples are runnable scripts, not API reference snippets. From the
repository root:

```bash
python docs/examples/run_mock_device.py
python docs/examples/run_local_emulator.py
python docs/examples/simulate_with_schrosim.py
python docs/examples/decode_with_lidmas.py
python docs/examples/run_optional_sampling_adapters.py
python docs/examples/run_thewalrus_kernel.py
python docs/examples/run_qutip_dynamics.py
python docs/examples/run_dynamiqs_dynamics.py
python docs/examples/run_strawberryfields_legacy.py
python docs/examples/run_native_runtime.py
```

Use Python 3.12+ for modern emulator examples such as Dynamiqs. Use Python 3.10
for the legacy Strawberry Fields/Xanadu path.

The native runtime example requires the C++ library first:

```bash
cmake -S . -B build
cmake --build build
python docs/examples/run_native_runtime.py
```

