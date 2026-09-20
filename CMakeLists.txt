cmake_minimum_required(VERSION 3.16)

project(
  PhotonQDrivers
  VERSION 0.1.0
  DESCRIPTION "Universal photonic quantum hardware driver framework"
  LANGUAGES CXX
)

add_library(
  photon_qdrivers_runtime
  cpp/src/runtime.cpp
  cpp/src/hal.cpp
  cpp/src/device.cpp
  cpp/src/fpga_driver.cpp
  cpp/src/transport.cpp
  cpp/src/types.cpp
  cpp/src/control_protocol.cpp
  cpp/src/sha256.cpp
)

target_include_directories(
  photon_qdrivers_runtime
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/cpp/include>
)

target_compile_features(photon_qdrivers_runtime PUBLIC cxx_std_17)

set_target_properties(
  photon_qdrivers_runtime
  PROPERTIES
    OUTPUT_NAME photon_qdrivers_runtime
    CXX_EXTENSIONS OFF
    POSITION_INDEPENDENT_CODE ON
)

add_executable(photon_qdrivers_runtime_smoke cpp/tests/runtime_smoke.cpp)
target_link_libraries(photon_qdrivers_runtime_smoke PRIVATE photon_qdrivers_runtime)

add_library(photon_qdrivers_capi SHARED cpp/src/c_api.cpp)
target_include_directories(
  photon_qdrivers_capi
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/cpp/include>
)
target_link_libraries(photon_qdrivers_capi PRIVATE photon_qdrivers_runtime)
target_compile_features(photon_qdrivers_capi PUBLIC cxx_std_17)
target_compile_definitions(photon_qdrivers_capi PRIVATE PHOTON_QDRIVERS_CAPI_EXPORTS)
set_target_properties(
  photon_qdrivers_capi
  PROPERTIES
    OUTPUT_NAME photon_qdrivers_capi
    CXX_EXTENSIONS OFF
)

add_executable(photon_qdrivers_capi_smoke cpp/tests/c_api_smoke.cpp)
target_link_libraries(photon_qdrivers_capi_smoke PRIVATE photon_qdrivers_capi)

add_executable(photon_qdrivers_fpga_mailbox_smoke cpp/tests/fpga_mailbox_transport_smoke.cpp)
target_link_libraries(photon_qdrivers_fpga_mailbox_smoke PRIVATE photon_qdrivers_runtime)

add_executable(photon_qdrivers_red_pitaya_mailbox_smoke cpp/tests/red_pitaya_mailbox_smoke.cpp)
target_link_libraries(photon_qdrivers_red_pitaya_mailbox_smoke PRIVATE photon_qdrivers_capi)

add_library(photon_qdrivers_hls_kernels fpga/hls/src/detector_kernels.cpp)
target_include_directories(
  photon_qdrivers_hls_kernels
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/fpga/hls/include>
)
target_compile_features(photon_qdrivers_hls_kernels PUBLIC cxx_std_17)
set_target_properties(
  photon_qdrivers_hls_kernels
  PROPERTIES
    CXX_EXTENSIONS OFF
)

add_executable(photon_qdrivers_hls_detector_test fpga/hls/tests/detector_kernels_test.cpp)
target_link_libraries(photon_qdrivers_hls_detector_test PRIVATE photon_qdrivers_hls_kernels)

enable_testing()
add_test(NAME photon_qdrivers_runtime_smoke COMMAND photon_qdrivers_runtime_smoke)
add_test(NAME photon_qdrivers_capi_smoke COMMAND photon_qdrivers_capi_smoke)
add_test(NAME photon_qdrivers_fpga_mailbox_smoke COMMAND photon_qdrivers_fpga_mailbox_smoke)
add_test(
  NAME photon_qdrivers_red_pitaya_mailbox_smoke
  COMMAND photon_qdrivers_red_pitaya_mailbox_smoke
)
add_test(NAME photon_qdrivers_hls_detector_test COMMAND photon_qdrivers_hls_detector_test)

find_program(VERILATOR_EXECUTABLE verilator)
if(VERILATOR_EXECUTABLE)
  add_test(
    NAME fpga_verilator_lint
    COMMAND
      ${VERILATOR_EXECUTABLE}
      --lint-only
      -sv
      --top-module
      top_photon_qdriver
      -I${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog
      -f
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/filelist.f
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  )
  add_test(
    NAME fpga_control_verilator_lint
    COMMAND
      ${VERILATOR_EXECUTABLE}
      --lint-only
      -sv
      --top-module
      control_schedule_engine
      -I${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog
      -f
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/filelist.f
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  )
  add_test(
    NAME fpga_red_pitaya_bridge_verilator_lint
    COMMAND
      ${VERILATOR_EXECUTABLE}
      --lint-only
      -sv
      --top-module
      red_pitaya_control_bridge
      -I${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog
      -f
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/filelist.f
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  )
  add_test(
    NAME fpga_red_pitaya_sys_bus_adapter_verilator_lint
    COMMAND
      ${VERILATOR_EXECUTABLE}
      --lint-only
      -sv
      --top-module
      red_pitaya_sys_bus_adapter
      -I${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog
      -f
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/filelist.f
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  )
endif()

find_program(IVERILOG_EXECUTABLE iverilog)
find_program(VVP_EXECUTABLE vvp)
if(IVERILOG_EXECUTABLE AND VVP_EXECUTABLE)
  set(FPGA_TESTBENCH_OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/fpga/tb_top_photon_qdriver.vvp)
  set(
    FPGA_CONTROL_TESTBENCH_OUTPUT
    ${CMAKE_CURRENT_BINARY_DIR}/fpga/tb_control_schedule_engine.vvp
  )
  set(
    FPGA_RED_PITAYA_TESTBENCH_OUTPUT
    ${CMAKE_CURRENT_BINARY_DIR}/fpga/tb_red_pitaya_control_bridge.vvp
  )
  set(
    FPGA_RED_PITAYA_SYS_BUS_TESTBENCH_OUTPUT
    ${CMAKE_CURRENT_BINARY_DIR}/fpga/tb_red_pitaya_sys_bus_adapter.vvp
  )

  add_custom_command(
    OUTPUT ${FPGA_TESTBENCH_OUTPUT}
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/fpga
    COMMAND
      ${IVERILOG_EXECUTABLE}
      -g2012
      -I
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog
      -o
      ${FPGA_TESTBENCH_OUTPUT}
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/tb_top_photon_qdriver.sv
    DEPENDS
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/tb_top_photon_qdriver.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/photon_qdriver_pkg.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/pulse_scheduler.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/detector_readout.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/coincidence_counter.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/top_photon_qdriver.sv
    VERBATIM
  )

  add_custom_target(fpga_tb_top_photon_qdriver ALL DEPENDS ${FPGA_TESTBENCH_OUTPUT})
  add_test(NAME fpga_tb_top_photon_qdriver COMMAND ${VVP_EXECUTABLE} ${FPGA_TESTBENCH_OUTPUT})

  add_custom_command(
    OUTPUT ${FPGA_CONTROL_TESTBENCH_OUTPUT}
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/fpga
    COMMAND
      ${IVERILOG_EXECUTABLE}
      -g2012
      -I
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog
      -o
      ${FPGA_CONTROL_TESTBENCH_OUTPUT}
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/tb_control_schedule_engine.sv
    DEPENDS
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/tb_control_schedule_engine.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/fixtures/p5_control_program.hex
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/photon_qdriver_pkg.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/control_instruction_decoder.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/control_schedule_engine.sv
    VERBATIM
  )

  add_custom_target(
    fpga_tb_control_schedule_engine ALL
    DEPENDS ${FPGA_CONTROL_TESTBENCH_OUTPUT}
  )
  add_test(
    NAME fpga_tb_control_schedule_engine
    COMMAND
      ${VVP_EXECUTABLE}
      ${FPGA_CONTROL_TESTBENCH_OUTPUT}
      +PROGRAM=${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/fixtures/p5_control_program.hex
  )

  add_custom_command(
    OUTPUT ${FPGA_RED_PITAYA_TESTBENCH_OUTPUT}
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/fpga
    COMMAND
      ${IVERILOG_EXECUTABLE}
      -g2012
      -I
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog
      -o
      ${FPGA_RED_PITAYA_TESTBENCH_OUTPUT}
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/tb_red_pitaya_control_bridge.sv
    DEPENDS
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/tb_red_pitaya_control_bridge.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/fixtures/p5_control_program.hex
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/photon_qdriver_pkg.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/control_instruction_decoder.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/control_schedule_engine.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/red_pitaya_control_bridge.sv
    VERBATIM
  )

  add_custom_target(
    fpga_tb_red_pitaya_control_bridge ALL
    DEPENDS ${FPGA_RED_PITAYA_TESTBENCH_OUTPUT}
  )
  add_test(
    NAME fpga_tb_red_pitaya_control_bridge
    COMMAND
      ${VVP_EXECUTABLE}
      ${FPGA_RED_PITAYA_TESTBENCH_OUTPUT}
      +PROGRAM=${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/fixtures/p5_control_program.hex
  )

  add_custom_command(
    OUTPUT ${FPGA_RED_PITAYA_SYS_BUS_TESTBENCH_OUTPUT}
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/fpga
    COMMAND
      ${IVERILOG_EXECUTABLE}
      -g2012
      -I
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog
      -o
      ${FPGA_RED_PITAYA_SYS_BUS_TESTBENCH_OUTPUT}
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/tb_red_pitaya_sys_bus_adapter.sv
    DEPENDS
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/tb_red_pitaya_sys_bus_adapter.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/fixtures/p61_physical_loopback_program.hex
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/photon_qdriver_pkg.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/control_instruction_decoder.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/control_schedule_engine.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/red_pitaya_control_bridge.sv
      ${CMAKE_CURRENT_SOURCE_DIR}/fpga/systemverilog/red_pitaya_sys_bus_adapter.sv
    VERBATIM
  )

  add_custom_target(
    fpga_tb_red_pitaya_sys_bus_adapter ALL
    DEPENDS ${FPGA_RED_PITAYA_SYS_BUS_TESTBENCH_OUTPUT}
  )
  add_test(
    NAME fpga_tb_red_pitaya_sys_bus_adapter
    COMMAND
      ${VVP_EXECUTABLE}
      ${FPGA_RED_PITAYA_SYS_BUS_TESTBENCH_OUTPUT}
      +PROGRAM=${CMAKE_CURRENT_SOURCE_DIR}/fpga/testbench/fixtures/p61_physical_loopback_program.hex
  )
endif()
