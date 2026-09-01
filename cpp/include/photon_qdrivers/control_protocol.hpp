#pragma once

#include <cstdint>
#include <string>

#include "photon_qdrivers/types.hpp"

namespace photon_qdrivers {

inline constexpr const char* kControlProtocolVersion = "PQDR_CONTROL_V1";
inline constexpr const char* kControlResultProtocolVersion =
    "PQDR_CONTROL_RESULT_V1";

struct ControlRequest {
  std::string job_id;
  std::string program_id;
  std::string profile_id;
  std::string profile_digest;
  std::string program_digest;
  std::string envelope_digest;
  std::string compiled_payload;
  std::uint64_t shots{0};
  std::uint64_t repetition_ticks{0};
  std::uint64_t sweep_points{0};
  std::uint64_t event_count{0};
};

struct ControlReply {
  std::string protocol{kControlResultProtocolVersion};
  std::string job_id;
  std::string program_id;
  std::string profile_id;
  std::string profile_digest;
  std::string program_digest;
  std::string envelope_digest;
  std::string acquisition_digest;
  JobStatus status{JobStatus::Failed};
  std::uint64_t shots{0};
  std::uint64_t repetition_ticks{0};
  std::uint64_t sweep_points{0};
  std::uint64_t event_count{0};
  std::uint64_t acquisition_count{0};
  std::uint64_t total_device_ticks{0};
  std::uint64_t overflowed_acquisitions{0};
  std::uint64_t dropped_events{0};
  std::string acquisition_payload{"[]"};
  std::string message;
};

void validate_control_request(const ControlRequest& request);
void validate_control_reply(const ControlReply& reply);
std::string control_request_digest(const ControlRequest& request);
ControlReply complete_control_request(const ControlRequest& request,
                                      const std::string& message);

}  // namespace photon_qdrivers
