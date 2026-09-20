`timescale 1ns/1ps
`include "../systemverilog/photon_qdriver_pkg.sv"
`include "../systemverilog/control_instruction_decoder.sv"
`include "../systemverilog/control_schedule_engine.sv"
`include "../systemverilog/red_pitaya_control_bridge.sv"
`include "../systemverilog/red_pitaya_sys_bus_adapter.sv"

module tb_red_pitaya_sys_bus_adapter;

    localparam int CHANNELS = 8;
    localparam int MAX_INSTRUCTIONS = 16;
    localparam int COUNT_WIDTH = 2;
    localparam int FIXTURE_COUNT = 6;

    logic clk = 1'b0;
    logic reset_n = 1'b0;
    logic bus_write_enable = 1'b0;
    logic bus_read_enable = 1'b0;
    logic [31:0] bus_address = '0;
    logic [31:0] bus_write_data = '0;
    logic [31:0] bus_read_data;
    logic bus_acknowledge;
    logic bus_error;
    logic [CHANNELS-1:0] detector_events;
    logic [CHANNELS-1:0] pulse_active_mask;
    logic [127:0] fixture_words [0:FIXTURE_COUNT-1];
    logic [31:0] read_value;
    string fixture_path;

    // The board fabric runs at 125 MHz.
    always #4 clk = ~clk;

    // Physical P6.1 wiring: expansion output DIO_N0 -> input DIO_P4.
    always_comb begin
        detector_events = '0;
        detector_events[4] = pulse_active_mask[0];
    end

    red_pitaya_sys_bus_adapter #(
        .CHANNELS(CHANNELS),
        .MAX_INSTRUCTIONS(MAX_INSTRUCTIONS),
        .COUNT_WIDTH(COUNT_WIDTH),
        .FPGA_CLOCK_HZ(125_000_000),
        .LOOPBACK_OUTPUT_CHANNEL(0),
        .LOOPBACK_INPUT_CHANNEL(4)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .bus_write_enable(bus_write_enable),
        .bus_read_enable(bus_read_enable),
        .bus_address(bus_address),
        .bus_write_data(bus_write_data),
        .bus_read_data(bus_read_data),
        .bus_acknowledge(bus_acknowledge),
        .bus_error(bus_error),
        .detector_events(detector_events),
        .pulse_active_mask(pulse_active_mask)
    );

    task automatic write_register(
        input logic [31:0] address,
        input logic [31:0] value
    );
        begin
            @(negedge clk);
            bus_write_enable = 1'b1;
            bus_address = address;
            bus_write_data = value;
            #1;
            if (!bus_acknowledge) $fatal(1, "system-bus write not acknowledged");
            if (bus_error) $fatal(1, "system-bus write returned an error");
            @(negedge clk);
            bus_write_enable = 1'b0;
            bus_address = '0;
            bus_write_data = '0;
        end
    endtask

    task automatic read_register(
        input logic [31:0] address,
        output logic [31:0] value
    );
        begin
            @(negedge clk);
            bus_read_enable = 1'b1;
            bus_address = address;
            #1;
            value = bus_read_data;
            if (!bus_acknowledge) $fatal(1, "system-bus read not acknowledged");
            if (bus_error) $fatal(1, "system-bus read returned an error");
            @(negedge clk);
            bus_read_enable = 1'b0;
            bus_address = '0;
        end
    endtask

    task automatic load_instruction(
        input logic [127:0] word,
        input logic is_last
    );
        begin
            write_register(32'h0000_0040, word[127:96]);
            write_register(32'h0000_0044, word[95:64]);
            write_register(32'h0000_0048, word[63:32]);
            write_register(32'h0000_004c, word[31:0]);
            write_register(32'h0000_0018, 32'(2 | (is_last ? 4 : 0)));
            repeat (2) @(negedge clk);
        end
    endtask

    initial begin
        if (!$value$plusargs("PROGRAM=%s", fixture_path)) begin
            fixture_path = "fpga/testbench/fixtures/p61_physical_loopback_program.hex";
        end
        $readmemh(fixture_path, fixture_words);

        repeat (3) @(negedge clk);
        reset_n = 1'b1;
        repeat (2) @(negedge clk);

        read_register(32'h0000_0000, read_value);
        if (read_value != 32'h50514452) $fatal(1, "board identity mismatch");
        read_register(32'h0000_000c, read_value);
        if (read_value != MAX_INSTRUCTIONS) $fatal(1, "instruction limit mismatch");
        read_register(32'h0000_0014, read_value);
        if (read_value != COUNT_WIDTH) $fatal(1, "count width mismatch");
        read_register(32'h0000_005c, read_value);
        if (read_value != 32'h00010000) $fatal(1, "physical protocol mismatch");
        read_register(32'h0000_0060, read_value);
        if (read_value != 125_000_000) $fatal(1, "fabric clock mismatch");

        write_register(32'h0000_0018, 32'h0000_0001);
        repeat (2) @(negedge clk);
        write_register(32'h0000_0024, 32'd12);
        for (int index = 0; index < FIXTURE_COUNT; index++) begin
            load_instruction(fixture_words[index], index == FIXTURE_COUNT - 1);
        end

        write_register(32'h0000_0018, 32'h0000_0008);
        wait (dut.bridge.done_latched || dut.bridge.engine_error);
        repeat (3) @(negedge clk);

        read_register(32'h0000_001c, read_value);
        if (!read_value[3] || read_value[4] || !read_value[6]) begin
            $fatal(1, "completion status mismatch");
        end
        read_register(32'h0000_002c, read_value);
        if (read_value != 11) $fatal(1, "final device tick mismatch");
        read_register(32'h0000_0030, read_value);
        if (read_value != 3) $fatal(1, "loopback count mismatch");
        read_register(32'h0000_0034, read_value);
        if (read_value != 1) $fatal(1, "loopback dropped-event mismatch");
        read_register(32'h0000_0038, read_value);
        if (!read_value[0]) $fatal(1, "loopback overflow mismatch");

        read_register(32'h0000_0064, read_value);
        if (read_value != 7) $fatal(1, "output rise tick mismatch");
        read_register(32'h0000_0068, read_value);
        if (read_value != 11) $fatal(1, "output fall tick mismatch");
        read_register(32'h0000_006c, read_value);
        if (read_value != 7) $fatal(1, "input rise tick mismatch");
        read_register(32'h0000_0070, read_value);
        if (read_value != 4) $fatal(1, "input high-cycle count mismatch");
        read_register(32'h0000_0074, read_value);
        if (read_value[2:0] != 3'b111) $fatal(1, "loopback flags mismatch");

        $display("P61_LOOPBACK 125000000 7 11 7 4 3 1 1");
        $display("P61_PASS");
        $finish;
    end

endmodule
