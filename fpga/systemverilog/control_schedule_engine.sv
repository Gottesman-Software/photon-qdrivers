`include "photon_qdriver_pkg.sv"

module control_schedule_engine #(
    parameter int CHANNELS = photon_qdriver_pkg::DEFAULT_CHANNELS,
    parameter int MAX_INSTRUCTIONS = 64,
    parameter int COUNT_WIDTH = photon_qdriver_pkg::DEFAULT_COUNT_WIDTH
) (
    input  logic clk,
    input  logic reset_n,

    input  logic program_clear,
    input  logic instruction_valid,
    input  logic [photon_qdriver_pkg::CONTROL_INSTRUCTION_WIDTH-1:0] instruction_word,
    input  logic instruction_last,
    output logic instruction_ready,
    output logic program_loaded,
    output logic [$clog2(MAX_INSTRUCTIONS+1)-1:0] instruction_count,

    input  logic run_start,
    input  logic [31:0] repetition_ticks,
    input  logic [CHANNELS-1:0] detector_events,

    output logic engine_busy,
    output logic engine_done,
    output logic engine_error,
    output logic [7:0] error_code,
    output logic [31:0] device_tick,

    output logic observation_valid,
    output logic [3:0] observation_opcode,
    output logic [7:0] observation_channel,
    output logic [31:0] observation_start_tick,
    output logic [31:0] observation_duration_ticks,
    output logic [31:0] observation_argument,
    output logic [7:0] observation_acquisition_kind,
    output logic [7:0] observation_flags,

    output logic [CHANNELS-1:0] pulse_active_mask,
    output logic acquisition_active,
    output logic acquisition_done,
    output logic [7:0] acquisition_channel,
    output logic [31:0] acquisition_start_tick,
    output logic [31:0] acquisition_end_tick,
    output logic [COUNT_WIDTH-1:0] acquisition_count,
    output logic acquisition_overflow,
    output logic [31:0] dropped_event_count
);

    localparam int INDEX_WIDTH = (MAX_INSTRUCTIONS <= 1) ? 1 : $clog2(MAX_INSTRUCTIONS);
    localparam int INSTRUCTION_COUNT_WIDTH = $clog2(MAX_INSTRUCTIONS + 1);
    localparam int CHANNEL_INDEX_WIDTH = (CHANNELS <= 1) ? 1 : $clog2(CHANNELS);
    localparam logic [COUNT_WIDTH-1:0] COUNT_MAX = {COUNT_WIDTH{1'b1}};

    logic [127:0] instruction_memory [0:MAX_INSTRUCTIONS-1];
    logic [INSTRUCTION_COUNT_WIDTH-1:0] current_index;
    logic [31:0] last_loaded_start_tick;
    logic [31:0] pulse_end_tick [0:CHANNELS-1];

    logic [31:0] load_start_tick;
    logic load_word_valid;
    logic [7:0] load_error_code;

    logic [127:0] current_word;
    logic [3:0] execute_opcode;
    logic [7:0] execute_channel;
    logic [31:0] execute_start_tick;
    logic [31:0] execute_duration_ticks;
    logic [31:0] execute_argument;
    logic [7:0] execute_acquisition_kind;
    logic [7:0] execute_flags;
    logic execute_word_valid;
    logic [7:0] execute_error_code;
    logic [32:0] execute_end_tick;

    assign instruction_ready = !program_loaded && !engine_busy && !engine_error &&
                               instruction_count <
                                   INSTRUCTION_COUNT_WIDTH'(MAX_INSTRUCTIONS);
    assign current_word = instruction_memory[current_index[INDEX_WIDTH-1:0]];
    assign execute_end_tick = {1'b0, execute_start_tick} +
                              {1'b0, execute_duration_ticks};

    control_instruction_decoder #(.CHANNELS(CHANNELS)) load_decoder (
        .instruction_word(instruction_word),
        .format_version(),
        .opcode(),
        .channel_index(),
        .start_tick(load_start_tick),
        .duration_ticks(),
        .argument_word(),
        .acquisition_kind(),
        .flags(),
        .instruction_valid(load_word_valid),
        .error_code(load_error_code)
    );

    control_instruction_decoder #(.CHANNELS(CHANNELS)) execute_decoder (
        .instruction_word(current_word),
        .format_version(),
        .opcode(execute_opcode),
        .channel_index(execute_channel),
        .start_tick(execute_start_tick),
        .duration_ticks(execute_duration_ticks),
        .argument_word(execute_argument),
        .acquisition_kind(execute_acquisition_kind),
        .flags(execute_flags),
        .instruction_valid(execute_word_valid),
        .error_code(execute_error_code)
    );

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            program_loaded <= 1'b0;
            instruction_count <= '0;
            current_index <= '0;
            last_loaded_start_tick <= '0;
            engine_busy <= 1'b0;
            engine_done <= 1'b0;
            engine_error <= 1'b0;
            error_code <= photon_qdriver_pkg::CONTROL_ERROR_NONE;
            device_tick <= '0;
            observation_valid <= 1'b0;
            observation_opcode <= '0;
            observation_channel <= '0;
            observation_start_tick <= '0;
            observation_duration_ticks <= '0;
            observation_argument <= '0;
            observation_acquisition_kind <= '0;
            observation_flags <= '0;
            pulse_active_mask <= '0;
            acquisition_active <= 1'b0;
            acquisition_done <= 1'b0;
            acquisition_channel <= '0;
            acquisition_start_tick <= '0;
            acquisition_end_tick <= '0;
            acquisition_count <= '0;
            acquisition_overflow <= 1'b0;
            dropped_event_count <= '0;
            for (int channel = 0; channel < CHANNELS; channel++) begin
                pulse_end_tick[channel] <= '0;
            end
        end else begin
            engine_done <= 1'b0;
            observation_valid <= 1'b0;
            acquisition_done <= 1'b0;

            if (program_clear) begin
                program_loaded <= 1'b0;
                instruction_count <= '0;
                current_index <= '0;
                last_loaded_start_tick <= '0;
                engine_busy <= 1'b0;
                engine_error <= 1'b0;
                error_code <= photon_qdriver_pkg::CONTROL_ERROR_NONE;
                device_tick <= '0;
                pulse_active_mask <= '0;
                acquisition_active <= 1'b0;
                acquisition_count <= '0;
                acquisition_overflow <= 1'b0;
                dropped_event_count <= '0;
                for (int channel = 0; channel < CHANNELS; channel++) begin
                    pulse_end_tick[channel] <= '0;
                end
            end else if (instruction_valid && instruction_ready) begin
                if (!load_word_valid) begin
                    engine_error <= 1'b1;
                    error_code <= load_error_code;
                end else if (instruction_count != 0 &&
                             load_start_tick < last_loaded_start_tick) begin
                    engine_error <= 1'b1;
                    error_code <= photon_qdriver_pkg::CONTROL_ERROR_UNSORTED;
                end else if (instruction_count ==
                                 INSTRUCTION_COUNT_WIDTH'(MAX_INSTRUCTIONS - 1) &&
                             !instruction_last) begin
                    engine_error <= 1'b1;
                    error_code <= photon_qdriver_pkg::CONTROL_ERROR_MEMORY_FULL;
                end else begin
                    instruction_memory[instruction_count[INDEX_WIDTH-1:0]] <=
                        instruction_word;
                    instruction_count <= instruction_count + 1'b1;
                    last_loaded_start_tick <= load_start_tick;
                    if (instruction_last) begin
                        program_loaded <= 1'b1;
                    end
                end
            end else if (run_start && !engine_busy) begin
                if (!program_loaded || instruction_count == 0) begin
                    engine_error <= 1'b1;
                    error_code <= photon_qdriver_pkg::CONTROL_ERROR_NOT_LOADED;
                end else if (repetition_ticks == 0) begin
                    engine_error <= 1'b1;
                    error_code <= photon_qdriver_pkg::CONTROL_ERROR_REPETITION;
                end else begin
                    current_index <= '0;
                    device_tick <= '0;
                    engine_busy <= 1'b1;
                    engine_error <= 1'b0;
                    error_code <= photon_qdriver_pkg::CONTROL_ERROR_NONE;
                    pulse_active_mask <= '0;
                    acquisition_active <= 1'b0;
                    acquisition_count <= '0;
                    acquisition_overflow <= 1'b0;
                    dropped_event_count <= '0;
                end
            end else if (engine_busy) begin
                if (current_index < instruction_count &&
                    execute_start_tick == device_tick) begin
                    if (!execute_word_valid) begin
                        engine_busy <= 1'b0;
                        engine_error <= 1'b1;
                        error_code <= execute_error_code;
                    end else if (execute_start_tick >= repetition_ticks ||
                                 execute_end_tick > {1'b0, repetition_ticks}) begin
                        engine_busy <= 1'b0;
                        engine_error <= 1'b1;
                        error_code <= photon_qdriver_pkg::CONTROL_ERROR_SCHEDULE_BOUNDS;
                    end else if (execute_opcode == photon_qdriver_pkg::CONTROL_OP_ACQUIRE &&
                                 acquisition_active) begin
                        engine_busy <= 1'b0;
                        engine_error <= 1'b1;
                        error_code <= photon_qdriver_pkg::CONTROL_ERROR_ACQUISITION_BUSY;
                    end else begin
                        observation_valid <= 1'b1;
                        observation_opcode <= execute_opcode;
                        observation_channel <= execute_channel;
                        observation_start_tick <= execute_start_tick;
                        observation_duration_ticks <= execute_duration_ticks;
                        observation_argument <= execute_argument;
                        observation_acquisition_kind <= execute_acquisition_kind;
                        observation_flags <= execute_flags;
                        current_index <= current_index + 1'b1;

                        if (execute_opcode == photon_qdriver_pkg::CONTROL_OP_SOURCE_TRIGGER ||
                            execute_opcode == photon_qdriver_pkg::CONTROL_OP_MODULATOR_PULSE) begin
                            pulse_active_mask[
                                execute_channel[CHANNEL_INDEX_WIDTH-1:0]
                            ] <= 1'b1;
                            pulse_end_tick[
                                execute_channel[CHANNEL_INDEX_WIDTH-1:0]
                            ] <= execute_end_tick[31:0];
                        end
                        if (execute_opcode == photon_qdriver_pkg::CONTROL_OP_ACQUIRE) begin
                            acquisition_active <= 1'b1;
                            acquisition_channel <= execute_channel;
                            acquisition_start_tick <= execute_start_tick;
                            acquisition_end_tick <= execute_end_tick[31:0];
                            acquisition_count <= '0;
                            acquisition_overflow <= 1'b0;
                            dropped_event_count <= '0;
                        end
                    end
                end else begin
                    if (acquisition_active &&
                        device_tick < acquisition_end_tick &&
                        detector_events[
                            acquisition_channel[CHANNEL_INDEX_WIDTH-1:0]
                        ]) begin
                        if (acquisition_count == COUNT_MAX) begin
                            acquisition_overflow <= 1'b1;
                            dropped_event_count <= dropped_event_count + 1'b1;
                        end else begin
                            acquisition_count <= acquisition_count + 1'b1;
                        end
                    end

                    for (int channel = 0; channel < CHANNELS; channel++) begin
                        if (pulse_active_mask[channel] &&
                            device_tick + 1'b1 >= pulse_end_tick[channel]) begin
                            pulse_active_mask[channel] <= 1'b0;
                        end
                    end

                    if (acquisition_active &&
                        device_tick + 1'b1 >= acquisition_end_tick) begin
                        acquisition_active <= 1'b0;
                        acquisition_done <= 1'b1;
                    end

                    if (device_tick + 1'b1 >= repetition_ticks) begin
                        engine_busy <= 1'b0;
                        if (current_index < instruction_count) begin
                            engine_error <= 1'b1;
                            error_code <= photon_qdriver_pkg::CONTROL_ERROR_SCHEDULE_BOUNDS;
                        end else begin
                            engine_done <= 1'b1;
                        end
                    end else begin
                        device_tick <= device_tick + 1'b1;
                    end
                end
            end
        end
    end

endmodule
