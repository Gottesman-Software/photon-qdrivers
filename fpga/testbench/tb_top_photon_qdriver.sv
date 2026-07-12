`timescale 1ns/1ps
`include "../systemverilog/photon_qdriver_pkg.sv"
`include "../systemverilog/pulse_scheduler.sv"
`include "../systemverilog/detector_readout.sv"
`include "../systemverilog/coincidence_counter.sv"
`include "../systemverilog/top_photon_qdriver.sv"

module tb_top_photon_qdriver;

    localparam int CHANNELS = 4;
    localparam int DETECTORS = 4;
    localparam int COUNT_WIDTH = 16;

    logic clk = 1'b0;
    logic reset_n = 1'b0;
    logic command_valid = 1'b0;
    logic [CHANNELS-1:0] command_mask = '0;
    logic clear_counters = 1'b0;
    logic [DETECTORS-1:0] detector_in = '0;
    logic command_ready;
    logic pulse_valid;
    logic [CHANNELS-1:0] pulse_mask;
    logic [COUNT_WIDTH-1:0] coincidence_count;
    logic coincidence_valid;
    logic [DETECTORS-1:0] coincidence_bits;
    logic error_flag;
    photon_qdriver_pkg::qdrv_status_t status;

    always #5 clk = ~clk;

    top_photon_qdriver #(
        .CHANNELS(CHANNELS),
        .DETECTORS(DETECTORS),
        .COUNT_WIDTH(COUNT_WIDTH),
        .PULSE_WIDTH_CYCLES(3),
        .HOLDOFF_CYCLES(2),
        .COINCIDENCE_WINDOW_CYCLES(4)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .command_valid(command_valid),
        .command_mask(command_mask),
        .clear_counters(clear_counters),
        .detector_in(detector_in),
        .command_ready(command_ready),
        .pulse_valid(pulse_valid),
        .pulse_mask(pulse_mask),
        .coincidence_count(coincidence_count),
        .coincidence_valid(coincidence_valid),
        .coincidence_bits(coincidence_bits),
        .error_flag(error_flag),
        .status(status)
    );

    task automatic send_command(input logic [CHANNELS-1:0] mask);
        begin
            @(posedge clk);
            command_mask <= mask;
            command_valid <= 1'b1;
            @(posedge clk);
            command_valid <= 1'b0;
            command_mask <= '0;
        end
    endtask

    task automatic detector_pulse(input logic [DETECTORS-1:0] bits);
        begin
            @(posedge clk);
            detector_in <= bits;
            @(posedge clk);
            detector_in <= '0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        reset_n <= 1'b1;
        repeat (2) @(posedge clk);

        if (!command_ready) $fatal(1, "command_ready should be asserted after reset");
        send_command(4'b0011);
        repeat (1) @(posedge clk);
        if (!pulse_valid) $fatal(1, "pulse_valid should assert after command");
        if (pulse_mask != 4'b0011) $fatal(1, "pulse_mask mismatch");

        repeat (6) @(posedge clk);
        detector_pulse(4'b0001);
        repeat (2) @(posedge clk);
        detector_pulse(4'b0010);
        repeat (8) @(posedge clk);

        if (coincidence_count != 1) $fatal(1, "expected one coincidence event");
        if (coincidence_bits[1:0] != 2'b11) $fatal(1, "coincidence bits mismatch");

        clear_counters <= 1'b1;
        @(posedge clk);
        clear_counters <= 1'b0;
        @(posedge clk);
        if (coincidence_count != 0) $fatal(1, "clear_counters failed");

        send_command('0);
        @(posedge clk);
        if (!error_flag) $fatal(1, "zero command mask should raise error_flag");

        $display("tb_top_photon_qdriver passed");
        $finish;
    end

endmodule
