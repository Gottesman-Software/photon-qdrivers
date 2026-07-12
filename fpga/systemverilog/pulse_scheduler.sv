`include "photon_qdriver_pkg.sv"

module pulse_scheduler #(
    parameter int CHANNELS = photon_qdriver_pkg::DEFAULT_CHANNELS,
    parameter int PULSE_WIDTH_CYCLES = photon_qdriver_pkg::DEFAULT_PULSE_WIDTH_CYCLES
) (
    input  logic                  clk,
    input  logic                  reset_n,
    input  logic                  command_valid,
    input  logic [CHANNELS-1:0]   command_mask,
    output logic                  command_ready,
    output logic                  pulse_valid,
    output logic [CHANNELS-1:0]   pulse_mask,
    output logic                  scheduler_busy,
    output logic                  command_error
);

    localparam int COUNTER_WIDTH = (PULSE_WIDTH_CYCLES <= 1) ? 1 : $clog2(PULSE_WIDTH_CYCLES + 1);
    localparam logic [COUNTER_WIDTH-1:0] PULSE_WIDTH_VALUE = COUNTER_WIDTH'(PULSE_WIDTH_CYCLES);

    logic [COUNTER_WIDTH-1:0] remaining_cycles;

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            command_ready     <= 1'b1;
            pulse_valid       <= 1'b0;
            pulse_mask        <= '0;
            scheduler_busy    <= 1'b0;
            command_error     <= 1'b0;
            remaining_cycles  <= '0;
        end else begin
            command_error <= 1'b0;

            if (scheduler_busy) begin
                command_ready <= 1'b0;
                pulse_valid   <= 1'b1;

                if (command_valid) begin
                    command_error <= 1'b1;
                end

                if (remaining_cycles <= 1) begin
                    scheduler_busy   <= 1'b0;
                    command_ready    <= 1'b1;
                    pulse_valid      <= 1'b0;
                    pulse_mask       <= '0;
                    remaining_cycles <= '0;
                end else begin
                    remaining_cycles <= remaining_cycles - 1'b1;
                end
            end else begin
                command_ready <= 1'b1;
                pulse_valid   <= 1'b0;
                pulse_mask    <= '0;

                if (command_valid) begin
                    if (command_mask == '0) begin
                        command_error <= 1'b1;
                    end else begin
                        scheduler_busy   <= 1'b1;
                        command_ready    <= 1'b0;
                        pulse_valid      <= 1'b1;
                        pulse_mask       <= command_mask;
                        remaining_cycles <= PULSE_WIDTH_VALUE;
                    end
                end
            end
        end
    end

endmodule
