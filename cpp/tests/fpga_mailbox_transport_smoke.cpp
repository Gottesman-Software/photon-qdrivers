#include "photon_qdrivers/runtime.hpp"
#include "photon_qdrivers/transport.hpp"

#include <cassert>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

namespace {

std::string read_file(const std::string& path) {
  std::ifstream input(path);
  std::ostringstream buffer;
  buffer << input.rdbuf();
  return buffer.str();
}

bool contains(const std::string& value, const std::string& needle) {
  return value.find(needle) != std::string::npos;
}

}  // namespace

int main() {
  const std::string command_path = "fpga_mailbox_transport_smoke.commands";
  const std::string result_path = "fpga_mailbox_transport_smoke.results";
  std::remove(command_path.c_str());
  std::remove(result_path.c_str());

  auto transport = std::make_unique<photon_qdrivers::FPGAMailboxTransport>(
      command_path,
      result_path);
  photon_qdrivers::Runtime runtime(std::move(transport));

  runtime.initialize();
  const auto capabilities = runtime.capabilities();
  assert(capabilities.hardware_backed);
  assert(capabilities.realtime);
  assert(capabilities.device_id == "fpga-mailbox-device");

  photon_qdrivers::RuntimeJob job;
  job.job_id = "fpga-mailbox-job";
  job.circuit_ir = "{\"type\":\"photonic_circuit\",\"modes\":2}";
  job.modes = 2;
  job.shots = 12;
  job.operations = {"BS", "photon_counting"};

  runtime.submit_job(job);
  const std::string command_frame = read_file(command_path);
  assert(contains(command_frame, "PQDR_JOB_V1"));
  assert(contains(command_frame, "job_id=fpga-mailbox-job"));
  assert(contains(command_frame, "operations=BS,photon_counting"));

  {
    std::ofstream result_stream(result_path);
    result_stream << "PQDR_RESULT_V1\n";
    result_stream << "job_id=fpga-mailbox-job\n";
    result_stream << "status=completed\n";
    result_stream << "shots=12\n";
    result_stream << "message=completed by mailbox smoke\n";
    result_stream << "count=00:6\n";
    result_stream << "count=11:6\n";
    result_stream << "END\n";
  }

  const auto result = runtime.read_result(job.job_id);
  assert(result.job_id == job.job_id);
  assert(result.status == photon_qdrivers::JobStatus::Completed);
  assert(result.shots == 12);
  assert(result.counts.at("00") == 6);
  assert(result.counts.at("11") == 6);

  runtime.shutdown();
  std::remove(command_path.c_str());
  std::remove(result_path.c_str());
  return 0;
}
