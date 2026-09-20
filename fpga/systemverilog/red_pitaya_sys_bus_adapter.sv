`include "photon_qdriver_pkg.sv"

// P6.1 adapter for the Red Pitaya FPGA project's AXI-GP0 -> sys_bus path.
//
// The official Red Pitaya "logic" image converts the Zynq PS AXI-GP0 port to
// a flat system bus and decodes that bus into 256 KiB slots.  This module is
// intended for one such slot.  The first 0x5c bytes remain the immutable P6.0
// register map.  Observation-only P6.1 registers begin at 0x5c.
module red_pitaya_sys_bus_adapter #(
    parameter int CHANNELS = photon_qdriver_pkg::DEFAULT_CHANNELS,
    parameter int MAX_INSTRUCTIONS = 16,
    parameter int COUNT_WIDTH = 2,
    parameter int unsigned FPGA_CLOCK_HZ = 125_000_000,
    parameter int LOOPBACK_OUTPUT_CHANNEL = 0,
    parameter int LOOPBACK_INPUT_CHANNEL = 4
) (
    input  logic clk,
    input  logic reset_n,

    input  logic bus_write_enable,
    input  logic bus_read_enable,
    input  logic [31:0] bus_address,
    input  logic [31:0] bus_write_data,
    output logic [31:0] bus_read_data,
    output logic bus_acknowledge,
    output logic bus_error,

    input  logic [CHANNELS-1:0] detector_events,
    output logic [CHANNELS-1:0] pulse_active_mask
);

    localparam logic [7:0] REG_CONTROL                  = 8'h18;
    localparam logic [7:0] REG_PHYSICAL_PROTOCOL       = 8'h5c;
    localparam logic [7:0] REG_FPGA_CLOCK_HZ           = 8'h60;
    localparam logic [7:0] REG_OUTPUT_RISE_TICK         = 8'h64;
    localparam logic [7:0] REG_OUTPUT_FALL_TICK         = 8'h68;
    localparam logic [7:0] REG_INPUT_RISE_TICK          = 8'h6c;
    localparam logic [7:0] REG_INPUT_HIGH_CYCLES        = 8'h70;
    localparam logic [7:0] REG_LOOPBACK_FLAGS           = 8'h74;
    localparam logic [31:0] PHYSICAL_PROTOCOL_VERSION   = 32'h0001_0000;

    logic bus_request;
    logic address_aligned;
    logic address_in_aperture;
    logic address_valid;
    logic extension_read;
    logic extension_write;
    logic mmio_valid;
    logic mmio_write;
    logic [7:0] mmio_address;
    logic [31:0] mmio_read_data;
    logic mmio_ready;
    logic mmio_error;

    logic [31:0] device_tick;
    logic engine_busy;
    logic acquisition_active;
    logic previous_output;
    logic previous_input;
    logic output_rise_seen;
    logic output_fall_seen;
    logic input_rise_seen;
    logic [31:0] output_rise_tick;
    logic [31:0] output_fall_tick;
    logic [31:0] input_rise_tick;
    logic [31:0] input_high_cycles;
    logic measurement_clear;

    assign bus_request = bus_write_enable || bus_read_enable;
    assign address_aligned = bus_address[1:0] == 2'b00;
    assign address_in_aperture = bus_address[17:8] == 10'h000;
    assign address_valid = address_aligned && address_in_aperture;
    assign mmio_address = bus_address[7:0];
    assign extension_read = bus_read_enable && address_valid &&
                            mmio_address >= REG_PHYSICAL_PROTOCOL;
    assign extension_write = bus_write_enable && address_valid &&
                             mmio_address >= REG_PHYSICAL_PROTOCOL;
    assign mmio_valid = bus_request && address_valid && !extension_read &&
                        !extension_write;
    assign mmio_write = bus_write_enable;
    assign measurement_clear = mmio_valid && mmio_write &&
                               mmio_address == REG_CONTROL &&
                               bus_write_data[0];

    always_comb begin
        bus_read_data = mmio_read_data;
        if (extension_read) begin
            case (mmio_address)
                REG_PHYSICAL_PROTOCOL: bus_read_data = PHYSICAL_PROTOCOL_VERSION;
                REG_FPGA_CLOCK_HZ: bus_read_data = 32'(FPGA_CLOCK_HZ);
                REG_OUTPUT_RISE_TICK: bus_read_data = output_rise_tick;
                REG_OUTPUT_FALL_TICK: bus_read_data = output_fall_tick;
                REG_INPUT_RISE_TICK: bus_read_data = input_rise_tick;
                REG_INPUT_HIGH_CYCLES: bus_read_data = input_high_cycles;
                REG_LOOPBACK_FLAGS: begin
                    bus_read_data = {
                        29'h0000_0000,
                        input_rise_seen,
                        output_fall_seen,
                        output_rise_seen
                    };
                end
                default: bus_read_data = 32'h0000_0000;
            endcase
        end
    end

    assign bus_acknowledge = bus_request;
    assign bus_error = bus_request &&
                       (!address_valid || extension_write ||
                        (mmio_valid && mmio_ready && mmio_error));

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            previous_output <= 1'b0;
            previous_input <= 1'b0;
            output_rise_seen <= 1'b0;
            output_fall_seen <= 1'b0;
            input_rise_seen <= 1'b0;
            output_rise_tick <= '0;
            output_fall_tick <= '0;
            input_rise_tick <= '0;
            input_high_cycles <= '0;
        end else if (measurement_clear) begin
            previous_output <= pulse_active_mask[LOOPBACK_OUTPUT_CHANNEL];
            previous_input <= detector_events[LOOPBACK_INPUT_CHANNEL];
            output_rise_seen <= 1'b0;
            output_fall_seen <= 1'b0;
            input_rise_seen <= 1'b0;
            output_rise_tick <= '0;
            output_fall_tick <= '0;
            input_rise_tick <= '0;
            input_high_cycles <= '0;
        end else begin
            previous_output <= pulse_active_mask[LOOPBACK_OUTPUT_CHANNEL];
            previous_input <= detector_events[LOOPBACK_INPUT_CHANNEL];

            if (engine_busy && pulse_active_mask[LOOPBACK_OUTPUT_CHANNEL] &&
                !previous_output && !output_rise_seen) begin
                output_rise_seen <= 1'b1;
                output_rise_tick <= device_tick;
            end
            if (engine_busy && !pulse_active_mask[LOOPBACK_OUTPUT_CHANNEL] &&
                previous_output && !output_fall_seen) begin
                output_fall_seen <= 1'b1;
                output_fall_tick <= device_tick;
            end
            if (engine_busy && detector_events[LOOPBACK_INPUT_CHANNEL] &&
                !previous_input && !input_rise_seen) begin
                input_rise_seen <= 1'b1;
                input_rise_tick <= device_tick;
            end
            if (engine_busy && acquisition_active &&
                detector_events[LOOPBACK_INPUT_CHANNEL]) begin
                input_high_cycles <= input_high_cycles + 1'b1;
            end
        end
    end

    red_pitaya_control_bridge #(
        .CHANNELS(CHANNELS),
        .MAX_INSTRUCTIONS(MAX_INSTRUCTIONS),
        .COUNT_WIDTH(COUNT_WIDTH)
    ) bridge (
        .clk(clk),
        .reset_n(reset_n),
        .mmio_valid(mmio_valid),
        .mmio_write(mmio_write),
        .mmio_address(mmio_address),
        .mmio_write_data(bus_write_data),
        .mmio_ready(mmio_ready),
        .mmio_read_data(mmio_read_data),
        .mmio_error(mmio_error),
        .detector_events(detector_events),
        .pulse_active_mask(pulse_active_mask),
        .device_tick_observe(device_tick),
        .engine_busy_observe(engine_busy),
        .acquisition_active_observe(acquisition_active)
    );

endmodule
