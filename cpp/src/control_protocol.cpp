#include "photon_qdrivers/control_protocol.hpp"

#include <limits>

#include "photon_qdrivers/sha256.hpp"

namespace photon_qdrivers {

namespace {

bool is_lowercase_sha256(const std::string& value) {
  if (value.size() != 64) {
    return false;
  }
  for (const char character : value) {
    if (!((character >= '0' && character <= '9') ||
          (character >= 'a' && character <= 'f'))) {
      return false;
    }
  }
  return true;
}

void require_identifier(const std::string& value, const char* label) {
  if (value.empty()) {
    throw ValidationError(std::string(label) + " must be non-empty");
  }
  if (value.find('\n') != std::string::npos ||
      value.find('\r') != std::string::npos) {
    throw ValidationError(std::string(label) + " must not contain line breaks");
  }
}

void require_line_payload(const std::string& value, const char* label) {
  if (value.empty()) {
    throw ValidationError(std::string(label) + " must be non-empty");
  }
  if (value.find('\n') != std::string::npos ||
      value.find('\r') != std::string::npos) {
    throw ValidationError(std::string(label) + " must be canonical single-line JSON");
  }
}

std::uint64_t checked_total_ticks(std::uint64_t repetition_ticks,
                                  std::uint64_t shots,
                                  std::uint64_t sweep_points) {
  const auto maximum = std::numeric_limits<std::uint64_t>::max();
  if (shots > maximum / sweep_points) {
    throw ValidationError("control execution iteration count overflows uint64");
  }
  const std::uint64_t iterations = shots * sweep_points;
  if (repetition_ticks > maximum / iterations) {
    throw ValidationError("control total_device_ticks overflows uint64");
  }
  return repetition_ticks * iterations;
}

}  // namespace

std::string control_request_digest(const ControlRequest& request) {
  std::string preimage;
  preimage.reserve(request.compiled_payload.size() + 512U);
  preimage += kControlProtocolVersion;
  preimage += "\njob_id=" + request.job_id;
  preimage += "\nprogram_id=" + request.program_id;
  preimage += "\nprofile_id=" + request.profile_id;
  preimage += "\nprofile_digest=" + request.profile_digest;
  preimage += "\nprogram_digest=" + request.program_digest;
  preimage += "\nshots=" + std::to_string(request.shots);
  preimage += "\nrepetition_ticks=" + std::to_string(request.repetition_ticks);
  preimage += "\nsweep_points=" + std::to_string(request.sweep_points);
  preimage += "\nevent_count=" + std::to_string(request.event_count);
  preimage +=
      "\ncompiled_payload_length=" + std::to_string(request.compiled_payload.size());
  preimage += "\ncompiled_payload=" + request.compiled_payload;
  preimage += "\nEND\n";
  return sha256_hex(preimage);
}

void validate_control_request(const ControlRequest& request) {
  require_identifier(request.job_id, "control job_id");
  require_identifier(request.program_id, "control program_id");
  require_identifier(request.profile_id, "control profile_id");
  if (!is_lowercase_sha256(request.profile_digest)) {
    throw ValidationError("control profile_digest must be a lowercase SHA-256 digest");
  }
  if (!is_lowercase_sha256(request.program_digest)) {
    throw ValidationError("control program_digest must be a lowercase SHA-256 digest");
  }
  if (!is_lowercase_sha256(request.envelope_digest)) {
    throw ValidationError("control envelope_digest must be a lowercase SHA-256 digest");
  }
  require_line_payload(request.compiled_payload, "control compiled_payload");
  if (sha256_hex(request.compiled_payload) != request.program_digest) {
    throw ValidationError("control compiled_payload SHA-256 mismatch");
  }
  if (control_request_digest(request) != request.envelope_digest) {
    throw ValidationError("control envelope SHA-256 mismatch");
  }
  if (request.shots == 0) {
    throw ValidationError("control shots must be greater than zero");
  }
  if (request.repetition_ticks == 0) {
    throw ValidationError("control repetition_ticks must be greater than zero");
  }
  if (request.sweep_points == 0) {
    throw ValidationError("control sweep_points must be greater than zero");
  }
  if (request.event_count == 0) {
    throw ValidationError("control event_count must be greater than zero");
  }
  (void)checked_total_ticks(
      request.repetition_ticks, request.shots, request.sweep_points);
}

void validate_control_reply(const ControlReply& reply) {
  if (reply.protocol != kControlResultProtocolVersion) {
    throw TransportError("unsupported control-result protocol: " + reply.protocol);
  }
  require_identifier(reply.job_id, "control-result job_id");
  require_identifier(reply.program_id, "control-result program_id");
  require_identifier(reply.profile_id, "control-result profile_id");
  if (!is_lowercase_sha256(reply.profile_digest) ||
      !is_lowercase_sha256(reply.program_digest) ||
      !is_lowercase_sha256(reply.envelope_digest) ||
      !is_lowercase_sha256(reply.acquisition_digest)) {
    throw TransportError("control-result contains an invalid SHA-256 digest");
  }
  require_line_payload(reply.acquisition_payload, "control-result acquisition_payload");
  if (sha256_hex(reply.acquisition_payload) != reply.acquisition_digest) {
    throw TransportError("control-result acquisition_payload SHA-256 mismatch");
  }
  if (reply.shots == 0 || reply.repetition_ticks == 0 || reply.sweep_points == 0 ||
      reply.event_count == 0) {
    throw TransportError("control-result contains zero execution dimensions");
  }
  if (reply.overflowed_acquisitions > reply.acquisition_count) {
    throw TransportError(
        "control-result overflowed_acquisitions exceeds acquisition_count");
  }
  const auto expected = checked_total_ticks(
      reply.repetition_ticks, reply.shots, reply.sweep_points);
  if (reply.total_device_ticks != expected) {
    throw TransportError("control-result total_device_ticks is inconsistent");
  }
}

ControlReply complete_control_request(const ControlRequest& request,
                                      const std::string& message) {
  validate_control_request(request);
  ControlReply reply;
  reply.job_id = request.job_id;
  reply.program_id = request.program_id;
  reply.profile_id = request.profile_id;
  reply.profile_digest = request.profile_digest;
  reply.program_digest = request.program_digest;
  reply.envelope_digest = request.envelope_digest;
  reply.acquisition_digest = sha256_hex("[]");
  reply.status = JobStatus::Completed;
  reply.shots = request.shots;
  reply.repetition_ticks = request.repetition_ticks;
  reply.sweep_points = request.sweep_points;
  reply.event_count = request.event_count;
  reply.acquisition_count = 0;
  reply.total_device_ticks = checked_total_ticks(
      request.repetition_ticks, request.shots, request.sweep_points);
  reply.overflowed_acquisitions = 0;
  reply.dropped_events = 0;
  reply.acquisition_payload = "[]";
  reply.message = message;
  return reply;
}

}  // namespace photon_qdrivers
