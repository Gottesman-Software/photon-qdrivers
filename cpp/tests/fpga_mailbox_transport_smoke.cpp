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

  const std::string object_digest =
      "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a";
  const std::string array_digest =
      "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945";
  const std::string envelope_digest =
      "3a4780c0d3c9566ca2bbf6e7927a0491e9c5675af3f38dc5af46879d58f8b2c7";
  photon_qdrivers::ControlRequest control_request{
      "fpga-control-job",
      "fpga-control-program",
      "fpga-control-profile",
      object_digest,
      object_digest,
      envelope_digest,
      "{}",
      4,
      20,
      2,
      1,
  };
  runtime.submit_control(control_request);
  const std::string control_command_frame = read_file(command_path);
  assert(contains(control_command_frame, "PQDR_CONTROL_V1"));
  assert(contains(control_command_frame, "job_id=fpga-control-job"));
  assert(contains(control_command_frame, "compiled_payload_length=2"));
  assert(contains(control_command_frame, "envelope_digest=" + envelope_digest));

  {
    std::ofstream result_stream(result_path);
    result_stream << "PQDR_CONTROL_RESULT_V1\n";
    result_stream << "job_id=fpga-control-job\n";
    result_stream << "program_id=fpga-control-program\n";
    result_stream << "profile_id=fpga-control-profile\n";
    result_stream << "profile_digest=" << object_digest << "\n";
    result_stream << "program_digest=" << object_digest << "\n";
    result_stream << "envelope_digest=" << envelope_digest << "\n";
    result_stream << "acquisition_digest=" << array_digest << "\n";
    result_stream << "status=completed\n";
    result_stream << "shots=4\n";
    result_stream << "repetition_ticks=20\n";
    result_stream << "sweep_points=2\n";
    result_stream << "event_count=1\n";
    result_stream << "acquisition_count=0\n";
    result_stream << "total_device_ticks=160\n";
    result_stream << "overflowed_acquisitions=0\n";
    result_stream << "dropped_events=0\n";
    result_stream << "acquisition_payload_length=2\n";
    result_stream << "acquisition_payload=[]\n";
    result_stream << "message=completed by control mailbox smoke\n";
    result_stream << "END\n";
  }

  const auto control_result = runtime.read_control_result(control_request.job_id);
  assert(control_result.status == photon_qdrivers::JobStatus::Completed);
  assert(control_result.program_digest == object_digest);
  assert(control_result.total_device_ticks == 160);
  assert(control_result.acquisition_payload == "[]");

  runtime.shutdown();
  std::remove(command_path.c_str());
  std::remove(result_path.c_str());
  return 0;
}
