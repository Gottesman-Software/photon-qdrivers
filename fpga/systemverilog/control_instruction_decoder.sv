`include "photon_qdriver_pkg.sv"

module control_instruction_decoder #(
    parameter int CHANNELS = photon_qdriver_pkg::DEFAULT_CHANNELS
) (
    input  logic [photon_qdriver_pkg::CONTROL_INSTRUCTION_WIDTH-1:0] instruction_word,
    output logic [3:0]  format_version,
    output logic [3:0]  opcode,
    output logic [7:0]  channel_index,
    output logic [31:0] start_tick,
    output logic [31:0] duration_ticks,
    output logic [31:0] argument_word,
    output logic [7:0]  acquisition_kind,
    output logic [7:0]  flags,
    output logic        instruction_valid,
    output logic [7:0]  error_code
);

    assign format_version = instruction_word[127:124];
    assign opcode = instruction_word[123:120];
    assign channel_index = instruction_word[119:112];
    assign start_tick = instruction_word[111:80];
    assign duration_ticks = instruction_word[79:48];
    assign argument_word = instruction_word[47:16];
    assign acquisition_kind = instruction_word[15:8];
    assign flags = instruction_word[7:0];

    always_comb begin
        instruction_valid = 1'b1;
        error_code = photon_qdriver_pkg::CONTROL_ERROR_NONE;

        if (format_version != photon_qdriver_pkg::CONTROL_FORMAT_VERSION) begin
            instruction_valid = 1'b0;
            error_code = photon_qdriver_pkg::CONTROL_ERROR_FORMAT_VERSION;
        end else if (opcode < photon_qdriver_pkg::CONTROL_OP_SOURCE_TRIGGER ||
                     opcode > photon_qdriver_pkg::CONTROL_OP_ACQUIRE) begin
            instruction_valid = 1'b0;
            error_code = photon_qdriver_pkg::CONTROL_ERROR_OPCODE;
        end else if (channel_index >= 8'(CHANNELS)) begin
            instruction_valid = 1'b0;
            error_code = photon_qdriver_pkg::CONTROL_ERROR_CHANNEL;
        end else if ((opcode == photon_qdriver_pkg::CONTROL_OP_SOURCE_TRIGGER ||
                      opcode == photon_qdriver_pkg::CONTROL_OP_MODULATOR_PULSE ||
                      opcode == photon_qdriver_pkg::CONTROL_OP_DELAY ||
                      opcode == photon_qdriver_pkg::CONTROL_OP_ACQUIRE) &&
                     duration_ticks == 0) begin
            instruction_valid = 1'b0;
            error_code = photon_qdriver_pkg::CONTROL_ERROR_DURATION;
        end else if (opcode == photon_qdriver_pkg::CONTROL_OP_ACQUIRE &&
                     acquisition_kind != 8'd3) begin
            instruction_valid = 1'b0;
            error_code = photon_qdriver_pkg::CONTROL_ERROR_ACQUISITION_KIND;
        end else if (opcode != photon_qdriver_pkg::CONTROL_OP_ACQUIRE &&
                     acquisition_kind != 0) begin
            instruction_valid = 1'b0;
            error_code = photon_qdriver_pkg::CONTROL_ERROR_ACQUISITION_KIND;
        end
    end

endmodule
