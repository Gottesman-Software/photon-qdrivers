`timescale 1ns/1ps
`include "../systemverilog/photon_qdriver_pkg.sv"
`include "../systemverilog/control_instruction_decoder.sv"
`include "../systemverilog/control_schedule_engine.sv"
`include "../systemverilog/red_pitaya_control_bridge.sv"

module tb_red_pitaya_control_bridge;

    localparam int CHANNELS = 8;
    localparam int MAX_INSTRUCTIONS = 16;
    localparam int COUNT_WIDTH = 2;
    localparam int FIXTURE_COUNT = 6;

    logic clk = 1'b0;
    logic reset_n = 1'b0;
    logic mmio_valid = 1'b0;
    logic mmio_write = 1'b0;
    logic [7:0] mmio_address = '0;
    logic [31:0] mmio_write_data = '0;
    logic mmio_ready;
    logic [31:0] mmio_read_data;
    logic mmio_error;
    logic [CHANNELS-1:0] detector_events = '0;
    logic [CHANNELS-1:0] pulse_active_mask;
    logic [127:0] fixture_words [0:FIXTURE_COUNT-1];
    logic [31:0] read_value;
    string fixture_path;

    always #5 clk = ~clk;

    red_pitaya_control_bridge #(
        .CHANNELS(CHANNELS),
        .MAX_INSTRUCTIONS(MAX_INSTRUCTIONS),
        .COUNT_WIDTH(COUNT_WIDTH)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .mmio_valid(mmio_valid),
        .mmio_write(mmio_write),
        .mmio_address(mmio_address),
        .mmio_write_data(mmio_write_data),
        .mmio_ready(mmio_ready),
        .mmio_read_data(mmio_read_data),
        .mmio_error(mmio_error),
        .detector_events(detector_events),
        .pulse_active_mask(pulse_active_mask)
    );

    task automatic write_register(
        input logic [7:0] address,
        input logic [31:0] value
    );
        begin
            @(negedge clk);
            mmio_valid = 1'b1;
            mmio_write = 1'b1;
            mmio_address = address;
            mmio_write_data = value;
            @(negedge clk);
            if (!mmio_ready) $fatal(1, "MMIO write was not acknowledged");
            mmio_valid = 1'b0;
            mmio_write = 1'b0;
            mmio_address = '0;
            mmio_write_data = '0;
        end
    endtask

    task automatic read_register(
        input logic [7:0] address,
        output logic [31:0] value
    );
        begin
            @(negedge clk);
            mmio_valid = 1'b1;
            mmio_write = 1'b0;
            mmio_address = address;
            #1 value = mmio_read_data;
            if (!mmio_ready) $fatal(1, "MMIO read was not acknowledged");
            @(negedge clk);
            mmio_valid = 1'b0;
            mmio_address = '0;
        end
    endtask

    task automatic load_instruction(
        input logic [127:0] word,
        input logic is_last
    );
        begin
            write_register(8'h40, word[127:96]);
            write_register(8'h44, word[95:64]);
            write_register(8'h48, word[63:32]);
            write_register(8'h4c, word[31:0]);
            write_register(8'h18, 32'(2 | (is_last ? 4 : 0)));
            repeat (2) @(negedge clk);
        end
    endtask

    always @(negedge clk) begin
        detector_events = '0;
        if (dut.acquisition_active) begin
            detector_events[4] = 1'b1;
        end
    end

    initial begin
        if (!$value$plusargs("PROGRAM=%s", fixture_path)) begin
            fixture_path = "fpga/testbench/fixtures/p5_control_program.hex";
        end
        $readmemh(fixture_path, fixture_words);

        repeat (3) @(negedge clk);
        reset_n = 1'b1;
        repeat (2) @(negedge clk);

        read_register(8'h00, read_value);
        if (read_value != 32'h50514452) $fatal(1, "board identity mismatch");
        read_register(8'h04, read_value);
        if (read_value != 32'h00010000) $fatal(1, "protocol version mismatch");
        read_register(8'h08, read_value);
        if (read_value != 128) $fatal(1, "instruction width mismatch");
        read_register(8'h0c, read_value);
        if (read_value != MAX_INSTRUCTIONS) $fatal(1, "instruction limit mismatch");
        read_register(8'h10, read_value);
        if (read_value != CHANNELS) $fatal(1, "channel count mismatch");
        read_register(8'h14, read_value);
        if (read_value != COUNT_WIDTH) $fatal(1, "count width mismatch");
        $display("P6_CAPS 128 %0d %0d %0d", MAX_INSTRUCTIONS, CHANNELS, COUNT_WIDTH);

        write_register(8'h18, 32'h00000001);
        repeat (2) @(negedge clk);
        write_register(8'h24, 32'd12);
        for (int index = 0; index < FIXTURE_COUNT; index++) begin
            load_instruction(fixture_words[index], index == FIXTURE_COUNT - 1);
        end

        read_register(8'h28, read_value);
        if (read_value != FIXTURE_COUNT) $fatal(1, "instruction count mismatch");
        read_register(8'h1c, read_value);
        if (!read_value[0] || read_value[4]) $fatal(1, "program load status mismatch");

        write_register(8'h18, 32'h00000008);
        wait (dut.done_latched || dut.engine_error);
        repeat (2) @(negedge clk);

        read_register(8'h1c, read_value);
        if (!read_value[3] || read_value[4] || !read_value[6]) begin
            $fatal(1, "completion status mismatch");
        end
        read_register(8'h2c, read_value);
        if (read_value != 11) $fatal(1, "final device tick mismatch");
        read_register(8'h30, read_value);
        if (read_value != 3) $fatal(1, "acquisition count mismatch");
        read_register(8'h34, read_value);
        if (read_value != 1) $fatal(1, "dropped event mismatch");
        read_register(8'h38, read_value);
        if (!read_value[0]) $fatal(1, "overflow flag mismatch");
        read_register(8'h50, read_value);
        if (read_value != 7) $fatal(1, "acquisition start mismatch");
        read_register(8'h54, read_value);
        if (read_value != 11) $fatal(1, "acquisition end mismatch");
        read_register(8'h58, read_value);
        if (read_value != 4) $fatal(1, "acquisition channel mismatch");
        $display("P6_RESULT 11 6 4 7 11 3 1 1");

        write_register(8'h00, 32'h00000000);
        if (!mmio_error) $fatal(1, "read-only MMIO write was not rejected");
        read_register(8'h20, read_value);
        if (read_value != 8'h80) $fatal(1, "MMIO error code mismatch");
        $display("P6_FAULT read_only_write 128");

        $display("P6_PASS");
        $finish;
    end

endmodule
