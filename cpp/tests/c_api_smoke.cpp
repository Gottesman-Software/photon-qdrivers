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

  const char* empty_object_digest =
      "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a";
  const char* tampered_digest =
      "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945";
  const char* envelope_digest =
      "02f9e40f65952b718b375b243ce4ff1e44fc260f94570d10fd94b3a700e409cd";
  const char* tampered_envelope_digest =
      "ef57ed56be501a1f4a723bbb36b9643f4a3800ca7f16523d6b752af8fdbea701";
  require(
      pqdr_runtime_submit_control(
          runtime,
          "native-control-smoke",
          "control-program-smoke",
          "control-profile-smoke",
          empty_object_digest,
          empty_object_digest,
          envelope_digest,
          "{}",
          static_cast<uint64_t>(3),
          static_cast<uint64_t>(20),
          static_cast<uint64_t>(2),
          static_cast<uint64_t>(1)) == 0);

  const char* control_result =
      pqdr_runtime_read_control_result(runtime, "native-control-smoke");
  require(contains(control_result, "\"protocol\":\"PQDR_CONTROL_RESULT_V1\""));
  require(contains(control_result, "\"program_id\":\"control-program-smoke\""));
  require(contains(control_result, envelope_digest));
  require(contains(control_result, "\"total_device_ticks\":120"));
  require(contains(control_result, "\"acquisition_payload\":\"[]\""));

  require(
      pqdr_runtime_submit_control(
          runtime,
          "tampered-control-smoke",
          "control-program-smoke",
          "control-profile-smoke",
          empty_object_digest,
          tampered_digest,
          tampered_envelope_digest,
          "{}",
          static_cast<uint64_t>(1),
          static_cast<uint64_t>(20),
          static_cast<uint64_t>(1),
          static_cast<uint64_t>(1)) != 0);
  require(contains(pqdr_runtime_last_error(runtime), "compiled_payload SHA-256 mismatch"));

  require(
      pqdr_runtime_submit_control(
          runtime,
          "envelope-tamper-smoke",
          "control-program-smoke",
          "control-profile-smoke",
          empty_object_digest,
          empty_object_digest,
          "0000000000000000000000000000000000000000000000000000000000000000",
          "{}",
          static_cast<uint64_t>(1),
          static_cast<uint64_t>(20),
          static_cast<uint64_t>(1),
          static_cast<uint64_t>(1)) != 0);
  require(contains(pqdr_runtime_last_error(runtime), "envelope SHA-256 mismatch"));

  require(pqdr_runtime_shutdown(runtime) == 0);
  pqdr_runtime_destroy(runtime);
  return 0;
}
