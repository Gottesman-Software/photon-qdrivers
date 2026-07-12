#include "photon_qdrivers/c_api.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>
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

}  // namespace

int main() {
  pqdr_runtime* runtime = pqdr_runtime_create();
  require(runtime != nullptr);

  require(pqdr_runtime_initialize(runtime) == 0);

  const char* capabilities = pqdr_runtime_capabilities(runtime);
  require(contains(capabilities, "\"device_id\":\"in-memory-fpga-device\""));
  require(contains(capabilities, "\"photon_counting\""));

  const char* circuit_ir =
      "{\"type\":\"photonic_circuit\",\"modes\":2,\"shots\":8,"
      "\"operations\":[{\"gate\":\"BS\",\"modes\":[0,1]},"
      "{\"measure\":\"photon_counting\",\"modes\":[0,1]}]}";
  require(
      pqdr_runtime_submit_job(
          runtime,
          "native-smoke",
          circuit_ir,
          static_cast<uint32_t>(2),
          static_cast<uint64_t>(8),
          "BS,photon_counting") == 0);

  const char* result = pqdr_runtime_read_result(runtime, "native-smoke");
  require(contains(result, "\"job_id\":\"native-smoke\""));
  require(contains(result, "\"status\":\"completed\""));
  require(contains(result, "\"shots\":8"));

  require(pqdr_runtime_shutdown(runtime) == 0);
  pqdr_runtime_destroy(runtime);
  return 0;
}
