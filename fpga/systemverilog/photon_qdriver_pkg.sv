`ifndef PHOTON_QDRIVER_PKG_SV
`define PHOTON_QDRIVER_PKG_SV

package photon_qdriver_pkg;

    parameter int DEFAULT_CHANNELS = 8;
    parameter int DEFAULT_DETECTORS = 8;
    parameter int DEFAULT_COUNT_WIDTH = 32;
    parameter int DEFAULT_PULSE_WIDTH_CYCLES = 4;
    parameter int DEFAULT_HOLDOFF_CYCLES = 8;
    parameter int DEFAULT_COINCIDENCE_WINDOW_CYCLES = 8;

    typedef enum logic [1:0] {
        STATUS_IDLE  = 2'b00,
        STATUS_BUSY  = 2'b01,
        STATUS_DONE  = 2'b10,
        STATUS_ERROR = 2'b11
    } qdrv_status_t;

endpackage

`endif
