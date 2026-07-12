`include "photon_qdriver_pkg.sv"

module coincidence_counter #(
    parameter int DETECTORS = photon_qdriver_pkg::DEFAULT_DETECTORS,
    parameter int COUNT_WIDTH = photon_qdriver_pkg::DEFAULT_COUNT_WIDTH,
    parameter int WINDOW_CYCLES = photon_qdriver_pkg::DEFAULT_COINCIDENCE_WINDOW_CYCLES
) (
    input  logic                    clk,
    input  logic                    reset_n,
    input  logic                    clear,
    input  logic                    sample_valid,
    input  logic [DETECTORS-1:0]    sample_bits,
    output logic [COUNT_WIDTH-1:0]  coincidence_count,
    output logic                    coincidence_valid,
    output logic [DETECTORS-1:0]    coincidence_bits
);

    localparam int WINDOW_WIDTH = (WINDOW_CYCLES <= 1) ? 1 : $clog2(WINDOW_CYCLES + 1);
    localparam logic [WINDOW_WIDTH-1:0] WINDOW_VALUE = WINDOW_WIDTH'(WINDOW_CYCLES);
    localparam int ACTIVE_WIDTH = $clog2(DETECTORS + 1);

    logic [ACTIVE_WIDTH-1:0] active_detectors;
    logic [DETECTORS-1:0] window_bits;
    logic [WINDOW_WIDTH-1:0] window_remaining;
    logic window_active;

    always_comb begin
        active_detectors = '0;
        for (int index = 0; index < DETECTORS; index++) begin
            active_detectors = active_detectors + ACTIVE_WIDTH'(window_bits[index]);
        end
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            coincidence_count <= '0;
            coincidence_valid <= 1'b0;
            coincidence_bits  <= '0;
            window_bits       <= '0;
            window_remaining  <= '0;
            window_active     <= 1'b0;
        end else begin
            coincidence_valid <= 1'b0;

            if (clear) begin
                coincidence_count <= '0;
                coincidence_bits  <= '0;
                window_bits       <= '0;
                window_remaining  <= '0;
                window_active     <= 1'b0;
            end else begin
                if (sample_valid) begin
                    window_bits      <= window_bits | sample_bits;
                    window_active    <= 1'b1;
                    window_remaining <= WINDOW_VALUE;
                end else if (window_active) begin
                    if (window_remaining <= 1) begin
                        if (active_detectors > 1) begin
                            coincidence_count <= coincidence_count + 1'b1;
                            coincidence_valid <= 1'b1;
                            coincidence_bits  <= window_bits;
                        end
                        window_bits      <= '0;
                        window_remaining <= '0;
                        window_active    <= 1'b0;
                    end else begin
                        window_remaining <= window_remaining - 1'b1;
                    end
                end
            end
        end
    end

endmodule
