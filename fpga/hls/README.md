# HLS Kernels

This directory contains portable C++ kernels for future high-level synthesis
work. The current kernels are written so they can run as normal host-side C++
tests today and later be adapted to Vitis HLS or another HLS flow.

## Current Kernels

- `threshold_sample`: converts one detector sample frame into a detector bitmask.
- `threshold_stream`: thresholds a stream of detector frames.
- `histogram_masks`: builds a histogram of detector bitmasks.
- `count_coincidences`: counts frames whose detector bitmask has at least a
  configured number of active detectors.

These kernels are useful for detector preprocessing, fast histogramming,
coincidence analysis, and reference-model parity with the SystemVerilog path.

## Layout

- `include/photon_qdrivers/hls/detector_kernels.hpp`: public kernel API.
- `src/detector_kernels.cpp`: portable implementation with optional HLS pragmas.
- `tests/detector_kernels_test.cpp`: host-side correctness test.

## Run

```bash
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

## HLS Direction

The real-time control path remains in SystemVerilog. HLS is intended for
streaming preprocessing and analysis kernels that benefit from hardware
acceleration but do not need hand-authored cycle-level control.

Potential future kernels:

- Timestamp binning.
- Detector dead-time correction.
- Calibration feedback reductions.
- Decoder preprocessing.
- Streaming correlation utilities.
