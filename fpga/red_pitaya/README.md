# P6.1 Red Pitaya Hardware Target

This target maps the immutable P6.0 register contract through the official Red
Pitaya Zynq PS AXI-GP0 path and adds observation-only registers for a measured
digital-loopback bench.  It targets one board configuration only:

- Red Pitaya STEMlab 125-14, Zynq-7010 (`MODEL=Z10`);
- 125 MHz FPGA fabric clock, so one device tick is 8 ns;
- official `RedPitaya-FPGA` project `logic`, pinned to commit
  `728a4f37e9c0a9b5ba1d9b7a0d44c38bbd2dc674`;
- system-bus slot 13 at physical address `0x40340000`;
- output channel 0 on `DIO_N0`, returned to detector channel 4 on `DIO_P4`.

The two pins must be connected with a short jumper and a common ground.  Check
the exact E1 connector pinout for the board revision before powering the board.
Do not connect either pin to an analog or externally driven signal.

## Prepare and build

The current official build requires Linux and Vivado 2025.1.  From a Linux
host with that toolchain:

```bash
git clone https://github.com/RedPitaya/RedPitaya-FPGA.git
git -C RedPitaya-FPGA checkout 728a4f37e9c0a9b5ba1d9b7a0d44c38bbd2dc674

python fpga/red_pitaya/prepare_official_project.py \
  /absolute/path/to/RedPitaya-FPGA

source /path/to/Xilinx/Vivado/2025.1/settings64.sh
make -C /absolute/path/to/RedPitaya-FPGA PRJ=qdriverlab MODEL=Z10
```

The official flow writes the bitstream, binary image, device-tree output, and
Vivado reports under `prj/qdriverlab/out/`.  Preserve the complete directory;
the bitstream digest and timing/utilization reports are part of P6.1 evidence.

## Deploy

For Red Pitaya OS 2.00 or newer, copy the generated binary image to the board
and load it with the Linux FPGA Manager.  The exact command depends on the OS
release; current releases support `fpgautil -b <image>`, while OS 2.07-43 and
newer also provide the board-aware `overlay.sh` flow.  Do not use the legacy
`/dev/xdevcfg` method on current images.

After loading, verify the live capability registers before connecting the
loopback jumper:

```bash
python -m photon_qdrivers.control.red_pitaya_daemon --help
```

Then run one mailbox request through the board-side command:

```bash
qdriver-red-pitaya \
  --command /root/p61/control_request.frame \
  --result /root/p61/control_result.frame \
  --evidence /root/p61/physical_evidence.json \
  --channel-map /root/photon-qdrivers/fpga/red_pitaya/channel_map.json \
  --bitstream /root/red_pitaya.bin
```

The process needs narrowly scoped access to `/dev/mem`.  The result is not
physical evidence unless it contains the live identity/capability reads, the
deployed bitstream SHA-256, output and input edge ticks, count saturation, and
host round-trip timing.  Synthesis reports establish tool output only; they do
not establish successful deployment or pin-level behavior.
