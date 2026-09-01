`include "photon_qdriver_pkg.sv"

module red_pitaya_control_bridge #(
    parameter int CHANNELS = photon_qdriver_pkg::DEFAULT_CHANNELS,
    parameter int MAX_INSTRUCTIONS = 64,
    parameter int COUNT_WIDTH = photon_qdriver_pkg::DEFAULT_COUNT_WIDTH
) (
    input  logic clk,
    input  logic reset_n,

    input  logic mmio_valid,
    input  logic mmio_write,
    input  logic [7:0] mmio_address,
    input  logic [31:0] mmio_write_data,
    output logic mmio_ready,
    output logic [31:0] mmio_read_data,
    output logic mmio_error,

    input  logic [CHANNELS-1:0] detector_events,
    output logic [CHANNELS-1:0] pulse_active_mask
);

    localparam logic [7:0] REG_IDENTITY               = 8'h00;
    localparam logic [7:0] REG_PROTOCOL_VERSION       = 8'h04;
    localparam logic [7:0] REG_INSTRUCTION_WIDTH      = 8'h08;
    localparam logic [7:0] REG_MAX_INSTRUCTIONS       = 8'h0c;
    localparam logic [7:0] REG_CHANNEL_COUNT          = 8'h10;
    localparam logic [7:0] REG_COUNT_WIDTH            = 8'h14;
    localparam logic [7:0] REG_CONTROL                = 8'h18;
    localparam logic [7:0] REG_STATUS                 = 8'h1c;
    localparam logic [7:0] REG_ERROR_CODE             = 8'h20;
    localparam logic [7:0] REG_REPETITION_TICKS       = 8'h24;
    localparam logic [7:0] REG_INSTRUCTION_COUNT      = 8'h28;
    localparam logic [7:0] REG_DEVICE_TICK            = 8'h2c;
    localparam logic [7:0] REG_ACQUISITION_COUNT      = 8'h30;
    localparam logic [7:0] REG_DROPPED_EVENTS         = 8'h34;
    localparam logic [7:0] REG_RESULT_FLAGS           = 8'h38;
    localparam logic [7:0] REG_PULSE_ACTIVE_MASK      = 8'h3c;
    localparam logic [7:0] REG_INSTRUCTION_WORD_3     = 8'h40;
    localparam logic [7:0] REG_INSTRUCTION_WORD_2     = 8'h44;
    localparam logic [7:0] REG_INSTRUCTION_WORD_1     = 8'h48;
    localparam logic [7:0] REG_INSTRUCTION_WORD_0     = 8'h4c;
    localparam logic [7:0] REG_ACQUISITION_START_TICK = 8'h50;
    localparam logic [7:0] REG_ACQUISITION_END_TICK   = 8'h54;
    localparam logic [7:0] REG_ACQUISITION_CHANNEL    = 8'h58;

    localparam logic [31:0] BOARD_IDENTITY = 32'h50514452;
    localparam logic [31:0] BOARD_PROTOCOL_VERSION = 32'h00010000;
    localparam logic [7:0] MMIO_ERROR_CODE = 8'h80;

    logic [31:0] repetition_ticks;
    logic [31:0] instruction_word_3;
    logic [31:0] instruction_word_2;
    logic [31:0] instruction_word_1;
    logic [31:0] instruction_word_0;
    logic [127:0] instruction_word;

    logic program_clear;
    logic instruction_valid;
    logic instruction_last;
    logic instruction_ready;
    logic program_loaded;
    logic [$clog2(MAX_INSTRUCTIONS+1)-1:0] instruction_count;
    logic run_start;
    logic engine_busy;
    logic engine_done;
    logic engine_error;
    logic [7:0] engine_error_code;
    logic [31:0] device_tick;
    logic acquisition_active;
    logic acquisition_done;
    logic [7:0] acquisition_channel;
    logic [31:0] acquisition_start_tick;
    logic [31:0] acquisition_end_tick;
    logic [COUNT_WIDTH-1:0] acquisition_count;
    logic acquisition_overflow;
    logic [31:0] dropped_event_count;
    logic done_latched;
    logic acquisition_done_latched;
    logic mmio_error_latched;

    assign instruction_word = {
        instruction_word_3,
        instruction_word_2,
        instruction_word_1,
        instruction_word_0
    };
    assign mmio_ready = mmio_valid;
    assign mmio_error = mmio_error_latched;

    always_comb begin
        mmio_read_data = 32'h00000000;
        case (mmio_address)
            REG_IDENTITY: mmio_read_data = BOARD_IDENTITY;
            REG_PROTOCOL_VERSION: mmio_read_data = BOARD_PROTOCOL_VERSION;
            REG_INSTRUCTION_WIDTH: mmio_read_data = 32'(128);
            REG_MAX_INSTRUCTIONS: mmio_read_data = 32'(MAX_INSTRUCTIONS);
            REG_CHANNEL_COUNT: mmio_read_data = 32'(CHANNELS);
            REG_COUNT_WIDTH: mmio_read_data = 32'(COUNT_WIDTH);
            REG_CONTROL: mmio_read_data = 32'h00000000;
            REG_STATUS: begin
                mmio_read_data[0] = program_loaded;
                mmio_read_data[1] = instruction_ready;
                mmio_read_data[2] = engine_busy;
                mmio_read_data[3] = done_latched;
                mmio_read_data[4] = engine_error || mmio_error_latched;
                mmio_read_data[5] = acquisition_active;
                mmio_read_data[6] = acquisition_done_latched;
            end
            REG_ERROR_CODE: begin
                if (mmio_error_latched) begin
                    mmio_read_data = {24'h000000, MMIO_ERROR_CODE};
                end else begin
                    mmio_read_data = {24'h000000, engine_error_code};
                end
            end
            REG_REPETITION_TICKS: mmio_read_data = repetition_ticks;
            REG_INSTRUCTION_COUNT: mmio_read_data = 32'(instruction_count);
            REG_DEVICE_TICK: mmio_read_data = device_tick;
            REG_ACQUISITION_COUNT: mmio_read_data = 32'(acquisition_count);
            REG_DROPPED_EVENTS: mmio_read_data = dropped_event_count;
            REG_RESULT_FLAGS: mmio_read_data = {31'h00000000, acquisition_overflow};
            REG_PULSE_ACTIVE_MASK: mmio_read_data = 32'(pulse_active_mask);
            REG_INSTRUCTION_WORD_3: mmio_read_data = instruction_word_3;
            REG_INSTRUCTION_WORD_2: mmio_read_data = instruction_word_2;
            REG_INSTRUCTION_WORD_1: mmio_read_data = instruction_word_1;
            REG_INSTRUCTION_WORD_0: mmio_read_data = instruction_word_0;
            REG_ACQUISITION_START_TICK: mmio_read_data = acquisition_start_tick;
            REG_ACQUISITION_END_TICK: mmio_read_data = acquisition_end_tick;
            REG_ACQUISITION_CHANNEL: begin
                mmio_read_data = {24'h000000, acquisition_channel};
            end
            default: mmio_read_data = 32'h00000000;
        endcase
    end

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            repetition_ticks <= '0;
            instruction_word_3 <= '0;
            instruction_word_2 <= '0;
            instruction_word_1 <= '0;
            instruction_word_0 <= '0;
            program_clear <= 1'b0;
            instruction_valid <= 1'b0;
            instruction_last <= 1'b0;
            run_start <= 1'b0;
            done_latched <= 1'b0;
            acquisition_done_latched <= 1'b0;
            mmio_error_latched <= 1'b0;
        end else begin
            program_clear <= 1'b0;
            instruction_valid <= 1'b0;
            instruction_last <= 1'b0;
            run_start <= 1'b0;

            if (engine_done) begin
                done_latched <= 1'b1;
            end
            if (acquisition_done) begin
                acquisition_done_latched <= 1'b1;
            end

            if (mmio_valid && mmio_write) begin
                case (mmio_address)
                    REG_REPETITION_TICKS: repetition_ticks <= mmio_write_data;
                    REG_INSTRUCTION_WORD_3: instruction_word_3 <= mmio_write_data;
                    REG_INSTRUCTION_WORD_2: instruction_word_2 <= mmio_write_data;
                    REG_INSTRUCTION_WORD_1: instruction_word_1 <= mmio_write_data;
                    REG_INSTRUCTION_WORD_0: instruction_word_0 <= mmio_write_data;
                    REG_CONTROL: begin
                        if (mmio_write_data[0]) begin
                            program_clear <= 1'b1;
                            done_latched <= 1'b0;
                            acquisition_done_latched <= 1'b0;
                            mmio_error_latched <= 1'b0;
                        end
                        if (mmio_write_data[1]) begin
                            if (instruction_ready) begin
                                instruction_valid <= 1'b1;
                                instruction_last <= mmio_write_data[2];
                            end else begin
                                mmio_error_latched <= 1'b1;
                            end
                        end
                        if (mmio_write_data[3]) begin
                            run_start <= 1'b1;
                            done_latched <= 1'b0;
                            acquisition_done_latched <= 1'b0;
                        end
                    end
                    default: mmio_error_latched <= 1'b1;
                endcase
            end
        end
    end

    control_schedule_engine #(
        .CHANNELS(CHANNELS),
        .MAX_INSTRUCTIONS(MAX_INSTRUCTIONS),
        .COUNT_WIDTH(COUNT_WIDTH)
    ) engine (
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
        .error_code(engine_error_code),
        .device_tick(device_tick),
        .observation_valid(),
        .observation_opcode(),
        .observation_channel(),
        .observation_start_tick(),
        .observation_duration_ticks(),
        .observation_argument(),
        .observation_acquisition_kind(),
        .observation_flags(),
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

endmodule
