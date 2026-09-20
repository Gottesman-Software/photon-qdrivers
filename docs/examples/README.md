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
python docs/examples/run_red_pitaya_control_loopback.py
python docs/examples/create_red_pitaya_physical_loopback_request.py \
  /tmp/control_request.frame
```

Use Python 3.12+ for modern emulator examples such as Dynamiqs. Use Python 3.10
for the legacy Strawberry Fields/Xanadu path.

The native runtime example requires the C++ library first:

```bash
cmake -S . -B build
cmake --build build
python docs/examples/run_native_runtime.py
python docs/examples/run_red_pitaya_control_loopback.py
```

The Red Pitaya control example uses temporary mailbox files and the deterministic
software bridge. It demonstrates the public framing and normalization path; it
does not communicate with a physical board.

The request-creation example emits the versioned 125 MHz P6.1 program that
drives `DIO_N0` during the `DIO_P4` acquisition window. It creates a request
only; synthesis, image deployment, safe jumper installation, and the
board-side `qdriver-red-pitaya` command are documented in
`fpga/red_pitaya/README.md`.
