`timescale 1ns/1ps
`include "../systemverilog/photon_qdriver_pkg.sv"
`include "../systemverilog/control_instruction_decoder.sv"
`include "../systemverilog/control_schedule_engine.sv"

module tb_control_schedule_engine;

    localparam int CHANNELS = 8;
    localparam int MAX_INSTRUCTIONS = 16;
    localparam int COUNT_WIDTH = 2;
    localparam int FIXTURE_COUNT = 6;

    logic clk = 1'b0;
    logic reset_n = 1'b0;
    logic program_clear = 1'b0;
    logic instruction_valid = 1'b0;
    logic [127:0] instruction_word = '0;
    logic instruction_last = 1'b0;
    logic instruction_ready;
    logic program_loaded;
    logic [$clog2(MAX_INSTRUCTIONS+1)-1:0] instruction_count;
    logic run_start = 1'b0;
    logic [31:0] repetition_ticks = 32'd12;
    logic [CHANNELS-1:0] detector_events = '0;
    logic engine_busy;
    logic engine_done;
    logic engine_error;
    logic [7:0] error_code;
    logic [31:0] device_tick;
    logic observation_valid;
    logic [3:0] observation_opcode;
    logic [7:0] observation_channel;
    logic [31:0] observation_start_tick;
    logic [31:0] observation_duration_ticks;
    logic [31:0] observation_argument;
    logic [7:0] observation_acquisition_kind;
    logic [7:0] observation_flags;
    logic [CHANNELS-1:0] pulse_active_mask;
    logic acquisition_active;
    logic acquisition_done;
    logic [7:0] acquisition_channel;
    logic [31:0] acquisition_start_tick;
    logic [31:0] acquisition_end_tick;
    logic [COUNT_WIDTH-1:0] acquisition_count;
    logic acquisition_overflow;
    logic [31:0] dropped_event_count;

    logic [127:0] fixture_words [0:FIXTURE_COUNT-1];
    integer observation_index = 0;
    string fixture_path;

    logic [3:0] expected_opcode [0:FIXTURE_COUNT-1];
    logic [7:0] expected_channel [0:FIXTURE_COUNT-1];
    logic [31:0] expected_start [0:FIXTURE_COUNT-1];
    logic [31:0] expected_duration [0:FIXTURE_COUNT-1];
    logic [31:0] expected_argument [0:FIXTURE_COUNT-1];
    logic [7:0] expected_acquisition [0:FIXTURE_COUNT-1];
    logic [CHANNELS-1:0] expected_pulse_mask [0:FIXTURE_COUNT-1];

    always #5 clk = ~clk;

    control_schedule_engine #(
        .CHANNELS(CHANNELS),
        .MAX_INSTRUCTIONS(MAX_INSTRUCTIONS),
        .COUNT_WIDTH(COUNT_WIDTH)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .program_clear(program_clear),
        .instruction_valid(instruction_valid),
        .instruction_word(instruction_word),
        .instruction_last(instruction_last),
        .instruction_ready(instruction_ready),
        .program_loaded(program_loaded),
        .instruction_count(instruction_count),
        .run_start(run_start),
        .repetition_ticks(repetition_ticks),
        .detector_events(detector_events),
        .engine_busy(engine_busy),
        .engine_done(engine_done),
        .engine_error(engine_error),
        .error_code(error_code),
        .device_tick(device_tick),
        .observation_valid(observation_valid),
        .observation_opcode(observation_opcode),
        .observation_channel(observation_channel),
        .observation_start_tick(observation_start_tick),
        .observation_duration_ticks(observation_duration_ticks),
        .observation_argument(observation_argument),
        .observation_acquisition_kind(observation_acquisition_kind),
        .observation_flags(observation_flags),
        .pulse_active_mask(pulse_active_mask),
        .acquisition_active(acquisition_active),
        .acquisition_done(acquisition_done),
        .acquisition_channel(acquisition_channel),
        .acquisition_start_tick(acquisition_start_tick),
        .acquisition_end_tick(acquisition_end_tick),
        .acquisition_count(acquisition_count),
        .acquisition_overflow(acquisition_overflow),
        .dropped_event_count(dropped_event_count)
    );

    task automatic clear_program_state;
        begin
            @(negedge clk);
            program_clear = 1'b1;
            @(negedge clk);
            program_clear = 1'b0;
        end
    endtask

    task automatic send_instruction(
        input logic [127:0] word,
        input logic is_last
    );
        begin
            while (!instruction_ready) @(negedge clk);
            instruction_word = word;
            instruction_last = is_last;
            instruction_valid = 1'b1;
            @(negedge clk);
            instruction_valid = 1'b0;
            instruction_last = 1'b0;
            instruction_word = '0;
        end
    endtask

    task automatic start_run;
        begin
            @(negedge clk);
            run_start = 1'b1;
            @(negedge clk);
            run_start = 1'b0;
        end
    endtask

    always @(negedge clk) begin
        detector_events = '0;
        if (acquisition_active) begin
            detector_events[4] = 1'b1;
        end

        if (observation_valid) begin
            if (observation_index >= FIXTURE_COUNT) begin
                $fatal(1, "received too many RTL observations");
            end
            if (observation_opcode != expected_opcode[observation_index] ||
                observation_channel != expected_channel[observation_index] ||
                observation_start_tick != expected_start[observation_index] ||
                observation_duration_ticks != expected_duration[observation_index] ||
                observation_argument != expected_argument[observation_index] ||
                observation_acquisition_kind !=
                    expected_acquisition[observation_index] ||
                observation_flags != 0 ||
                pulse_active_mask != expected_pulse_mask[observation_index]) begin
                $fatal(1, "RTL observation mismatch at index %0d", observation_index);
            end
            $display(
                "P5_OBS %0d %0d %0d %0d %0d %08x %0d",
                observation_index,
                observation_start_tick,
                observation_opcode,
                observation_channel,
                observation_duration_ticks,
                observation_argument,
                observation_acquisition_kind
            );
            observation_index = observation_index + 1;
        end
    end

    initial begin
        expected_opcode[0] = 1; expected_channel[0] = 0;
        expected_start[0] = 1; expected_duration[0] = 2;
        expected_argument[0] = 32'hffffffff; expected_acquisition[0] = 0;
        expected_pulse_mask[0] = 8'b00000001;
        expected_opcode[1] = 2; expected_channel[1] = 1;
        expected_start[1] = 2; expected_duration[1] = 3;
        expected_argument[1] = 32'h80000000; expected_acquisition[1] = 0;
        expected_pulse_mask[1] = 8'b00000011;
        expected_opcode[2] = 3; expected_channel[2] = 2;
        expected_start[2] = 2; expected_duration[2] = 0;
        expected_argument[2] = 32'h80000000; expected_acquisition[2] = 0;
        expected_pulse_mask[2] = 8'b00000011;
        expected_opcode[3] = 4; expected_channel[3] = 3;
        expected_start[3] = 4; expected_duration[3] = 0;
        expected_argument[3] = 0; expected_acquisition[3] = 0;
        expected_pulse_mask[3] = 8'b00000010;
        expected_opcode[4] = 5; expected_channel[4] = 3;
        expected_start[4] = 5; expected_duration[4] = 1;
        expected_argument[4] = 0; expected_acquisition[4] = 0;
        expected_pulse_mask[4] = 8'b00000000;
        expected_opcode[5] = 6; expected_channel[5] = 4;
        expected_start[5] = 7; expected_duration[5] = 4;
        expected_argument[5] = 0; expected_acquisition[5] = 3;
        expected_pulse_mask[5] = 8'b00000000;

        if (!$value$plusargs("PROGRAM=%s", fixture_path)) begin
            fixture_path = "fpga/testbench/fixtures/p5_control_program.hex";
        end
        $readmemh(fixture_path, fixture_words);

        repeat (3) @(negedge clk);
        reset_n = 1'b1;
        repeat (2) @(negedge clk);

        for (int index = 0; index < FIXTURE_COUNT; index++) begin
            send_instruction(fixture_words[index], index == FIXTURE_COUNT - 1);
        end
        if (!program_loaded || instruction_count != FIXTURE_COUNT) begin
            $fatal(1, "RTL fixture did not load completely");
        end

        start_run();
        wait (engine_done || engine_error);
        @(negedge clk);
        if (engine_error) $fatal(1, "RTL engine failed with code %0d", error_code);
        if (observation_index != FIXTURE_COUNT) $fatal(1, "missing RTL observations");
        if (device_tick != 11) $fatal(1, "unexpected final device tick %0d", device_tick);
        if (acquisition_count != 3 || !acquisition_overflow ||
            dropped_event_count != 1) begin
            $fatal(1, "acquisition saturation mismatch");
        end
        if (acquisition_start_tick != 7 || acquisition_end_tick != 11) begin
            $fatal(1, "acquisition window mismatch");
        end
        $display("P5_RESULT 11 3 1 1");

        clear_program_state();
        send_instruction(
            {4'h2, fixture_words[0][123:0]},
            1'b1
        );
        if (!engine_error ||
            error_code != photon_qdriver_pkg::CONTROL_ERROR_FORMAT_VERSION) begin
            $fatal(1, "invalid format version was not rejected");
        end
        $display("P5_FAULT format_version %0d", error_code);

        clear_program_state();
        send_instruction(fixture_words[1], 1'b0);
        send_instruction(fixture_words[0], 1'b1);
        if (!engine_error ||
            error_code != photon_qdriver_pkg::CONTROL_ERROR_UNSORTED) begin
            $fatal(1, "unsorted instructions were not rejected");
        end
        $display("P5_FAULT unsorted %0d", error_code);

        clear_program_state();
        send_instruction(
            {fixture_words[5][127:16], 8'd2, fixture_words[5][7:0]},
            1'b1
        );
        if (!engine_error ||
            error_code != photon_qdriver_pkg::CONTROL_ERROR_ACQUISITION_KIND) begin
            $fatal(1, "unsupported acquisition kind was not rejected");
        end
        $display("P5_FAULT acquisition_kind %0d", error_code);

        $display("P5_PASS");
        $finish;
    end

endmodule
