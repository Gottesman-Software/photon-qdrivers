#include "photon_qdrivers/c_api.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>

namespace {

void require(bool condition) {
  if (!condition) {
    std::exit(1);
  }
}

bool contains(const char* haystack, const char* needle) {
  return haystack != nullptr && std::strstr(haystack, needle) != nullptr;
}

bool contains(const std::string& haystack, const std::string& needle) {
  return haystack.find(needle) != std::string::npos;
}

std::string read_file(const std::string& path) {
  std::ifstream input(path);
  std::ostringstream buffer;
  buffer << input.rdbuf();
  return buffer.str();
}

}  // namespace

int main() {
  const std::string command_path = "red_pitaya_mailbox_smoke.commands";
  const std::string result_path = "red_pitaya_mailbox_smoke.results";
  std::remove(command_path.c_str());
  std::remove(result_path.c_str());

  pqdr_runtime* runtime = pqdr_runtime_create_red_pitaya(
      command_path.c_str(),
      result_path.c_str());
  require(runtime != nullptr);

  require(pqdr_runtime_initialize(runtime) == 0);

  const char* capabilities = pqdr_runtime_capabilities(runtime);
  require(contains(capabilities, "\"device_id\":\"red-pitaya-stemlab-125-14\""));
  require(contains(capabilities, "\"max_modes\":8"));
  require(contains(capabilities, "\"hardware_backed\":true"));
  require(contains(capabilities, "\"realtime\":true"));

  const char* circuit_ir =
      "{\"type\":\"photonic_circuit\",\"modes\":2,\"shots\":16,"
      "\"operations\":[{\"gate\":\"BS\",\"modes\":[0,1]},"
      "{\"measure\":\"photon_counting\",\"modes\":[0,1]}]}";
  require(
      pqdr_runtime_submit_job(
          runtime,
          "red-pitaya-smoke",
          circuit_ir,
          static_cast<std::uint32_t>(2),
          static_cast<std::uint64_t>(16),
          "BS,photon_counting") == 0);

  const std::string command_frame = read_file(command_path);
  require(contains(command_frame, "PQDR_JOB_V1"));
  require(contains(command_frame, "job_id=red-pitaya-smoke"));
  require(contains(command_frame, "operations=BS,photon_counting"));

  {
    std::ofstream result_stream(result_path);
    result_stream << "PQDR_RESULT_V1\n";
    result_stream << "job_id=red-pitaya-smoke\n";
    result_stream << "status=completed\n";
    result_stream << "shots=16\n";
    result_stream << "message=completed by Red Pitaya mailbox smoke\n";
    result_stream << "count=00:9\n";
    result_stream << "count=11:7\n";
    result_stream << "END\n";
  }

  const char* result = pqdr_runtime_read_result(runtime, "red-pitaya-smoke");
  require(contains(result, "\"job_id\":\"red-pitaya-smoke\""));
  require(contains(result, "\"status\":\"completed\""));
  require(contains(result, "\"shots\":16"));
  require(contains(result, "\"00\":9"));
  require(contains(result, "\"11\":7"));

  require(pqdr_runtime_shutdown(runtime) == 0);
  pqdr_runtime_destroy(runtime);
  std::remove(command_path.c_str());
  std::remove(result_path.c_str());
  return 0;
}
