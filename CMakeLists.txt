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
endif()
