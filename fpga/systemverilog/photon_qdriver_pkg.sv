`ifndef PHOTON_QDRIVER_PKG_SV
`define PHOTON_QDRIVER_PKG_SV

package photon_qdriver_pkg;

    parameter int DEFAULT_CHANNELS = 8;
    parameter int DEFAULT_DETECTORS = 8;
    parameter int DEFAULT_COUNT_WIDTH = 32;
    parameter int DEFAULT_PULSE_WIDTH_CYCLES = 4;
    parameter int DEFAULT_HOLDOFF_CYCLES = 8;
    parameter int DEFAULT_COINCIDENCE_WINDOW_CYCLES = 8;
    parameter int CONTROL_INSTRUCTION_WIDTH = 128;
    parameter logic [3:0] CONTROL_FORMAT_VERSION = 4'h1;

    typedef enum logic [3:0] {
        CONTROL_OP_SOURCE_TRIGGER  = 4'h1,
        CONTROL_OP_MODULATOR_PULSE = 4'h2,
        CONTROL_OP_PHASE_UPDATE    = 4'h3,
        CONTROL_OP_SYNC            = 4'h4,
        CONTROL_OP_DELAY           = 4'h5,
        CONTROL_OP_ACQUIRE         = 4'h6
    } control_opcode_t;

    typedef enum logic [7:0] {
        CONTROL_ERROR_NONE             = 8'h00,
        CONTROL_ERROR_FORMAT_VERSION   = 8'h01,
        CONTROL_ERROR_OPCODE           = 8'h02,
        CONTROL_ERROR_CHANNEL          = 8'h03,
        CONTROL_ERROR_DURATION         = 8'h04,
        CONTROL_ERROR_ACQUISITION_KIND = 8'h05,
        CONTROL_ERROR_UNSORTED         = 8'h06,
        CONTROL_ERROR_MEMORY_FULL      = 8'h07,
        CONTROL_ERROR_NOT_LOADED       = 8'h08,
        CONTROL_ERROR_REPETITION       = 8'h09,
        CONTROL_ERROR_SCHEDULE_BOUNDS  = 8'h0a,
        CONTROL_ERROR_ACQUISITION_BUSY = 8'h0b
    } control_error_t;

    typedef enum logic [1:0] {
        STATUS_IDLE  = 2'b00,
        STATUS_BUSY  = 2'b01,
        STATUS_DONE  = 2'b10,
        STATUS_ERROR = 2'b11
    } qdrv_status_t;

endpackage

`endif
