`include "photon_qdriver_pkg.sv"

module top_photon_qdriver #(
    parameter int CHANNELS = photon_qdriver_pkg::DEFAULT_CHANNELS,
    parameter int DETECTORS = photon_qdriver_pkg::DEFAULT_DETECTORS,
    parameter int COUNT_WIDTH = photon_qdriver_pkg::DEFAULT_COUNT_WIDTH,
    parameter int PULSE_WIDTH_CYCLES = photon_qdriver_pkg::DEFAULT_PULSE_WIDTH_CYCLES,
    parameter int HOLDOFF_CYCLES = photon_qdriver_pkg::DEFAULT_HOLDOFF_CYCLES,
    parameter int COINCIDENCE_WINDOW_CYCLES = photon_qdriver_pkg::DEFAULT_COINCIDENCE_WINDOW_CYCLES
) (
    input  logic                    clk,
    input  logic                    reset_n,
    input  logic                    command_valid,
    input  logic [CHANNELS-1:0]     command_mask,
    input  logic                    clear_counters,
    input  logic [DETECTORS-1:0]    detector_in,
    output logic                    command_ready,
    output logic                    pulse_valid,
    output logic [CHANNELS-1:0]     pulse_mask,
    output logic [COUNT_WIDTH-1:0]  coincidence_count,
    output logic                    coincidence_valid,
    output logic [DETECTORS-1:0]    coincidence_bits,
    output logic                    error_flag,
    output photon_qdriver_pkg::qdrv_status_t status
);

    logic sample_valid;
    logic [DETECTORS-1:0] sample_bits;
    logic scheduler_busy;
    logic command_error;
    logic readout_busy;

    always_comb begin
        error_flag = command_error;
        if (command_error) begin
            status = photon_qdriver_pkg::STATUS_ERROR;
        end else if (scheduler_busy || readout_busy) begin
            status = photon_qdriver_pkg::STATUS_BUSY;
        end else if (coincidence_valid) begin
            status = photon_qdriver_pkg::STATUS_DONE;
        end else begin
            status = photon_qdriver_pkg::STATUS_IDLE;
        end
    end

    pulse_scheduler #(
        .CHANNELS(CHANNELS),
        .PULSE_WIDTH_CYCLES(PULSE_WIDTH_CYCLES)
    ) scheduler (
        .clk(clk),
        .reset_n(reset_n),
        .command_valid(command_valid),
        .command_mask(command_mask),
        .command_ready(command_ready),
        .pulse_valid(pulse_valid),
        .pulse_mask(pulse_mask),
        .scheduler_busy(scheduler_busy),
        .command_error(command_error)
    );

    detector_readout #(
        .DETECTORS(DETECTORS),
        .HOLDOFF_CYCLES(HOLDOFF_CYCLES)
    ) readout (
        .clk(clk),
        .reset_n(reset_n),
        .detector_in(detector_in),
        .sample_valid(sample_valid),
        .sample_bits(sample_bits),
        .readout_busy(readout_busy)
    );

    coincidence_counter #(
        .DETECTORS(DETECTORS),
        .COUNT_WIDTH(COUNT_WIDTH),
        .WINDOW_CYCLES(COINCIDENCE_WINDOW_CYCLES)
    ) counter (
        .clk(clk),
        .reset_n(reset_n),
        .clear(clear_counters),
        .sample_valid(sample_valid),
        .sample_bits(sample_bits),
        .coincidence_count(coincidence_count),
        .coincidence_valid(coincidence_valid),
        .coincidence_bits(coincidence_bits)
    );

endmodule
