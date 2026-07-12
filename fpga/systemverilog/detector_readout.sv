`include "photon_qdriver_pkg.sv"

module detector_readout #(
    parameter int DETECTORS = photon_qdriver_pkg::DEFAULT_DETECTORS,
    parameter int HOLDOFF_CYCLES = photon_qdriver_pkg::DEFAULT_HOLDOFF_CYCLES
) (
    input  logic                  clk,
    input  logic                  reset_n,
    input  logic [DETECTORS-1:0]  detector_in,
    output logic                  sample_valid,
    output logic [DETECTORS-1:0]  sample_bits,
    output logic                  readout_busy
);

    localparam int HOLDOFF_WIDTH = (HOLDOFF_CYCLES <= 1) ? 1 : $clog2(HOLDOFF_CYCLES + 1);
    localparam logic [HOLDOFF_WIDTH-1:0] HOLDOFF_VALUE = HOLDOFF_WIDTH'(HOLDOFF_CYCLES);

    logic [DETECTORS-1:0] detector_sync_0;
    logic [DETECTORS-1:0] detector_sync_1;
    logic [DETECTORS-1:0] detector_previous;
    logic [DETECTORS-1:0] detector_edges;
    logic [HOLDOFF_WIDTH-1:0] holdoff_remaining;

    assign detector_edges = detector_sync_1 & ~detector_previous;

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            detector_sync_0    <= '0;
            detector_sync_1    <= '0;
            detector_previous  <= '0;
            sample_valid       <= 1'b0;
            sample_bits        <= '0;
            readout_busy       <= 1'b0;
            holdoff_remaining  <= '0;
        end else begin
            detector_sync_0   <= detector_in;
            detector_sync_1   <= detector_sync_0;
            detector_previous <= detector_sync_1;
            sample_valid      <= 1'b0;
            sample_bits       <= '0;

            if (readout_busy) begin
                if (holdoff_remaining <= 1) begin
                    holdoff_remaining <= '0;
                    readout_busy      <= 1'b0;
                end else begin
                    holdoff_remaining <= holdoff_remaining - 1'b1;
                end
            end else if (|detector_edges) begin
                sample_valid      <= 1'b1;
                sample_bits       <= detector_edges;
                readout_busy      <= 1'b1;
                holdoff_remaining <= HOLDOFF_VALUE;
            end
        end
    end

endmodule
