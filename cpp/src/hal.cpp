#include "photon_qdrivers/hal.hpp"

#include <algorithm>
#include <utility>

namespace photon_qdrivers {

namespace {

bool contains(const std::vector<std::string>& values, const std::string& value) {
  return std::find(values.begin(), values.end(), value) != values.end();
}

void validate_job_against_capabilities(const RuntimeJob& job, const DeviceCapabilities& caps) {
  if (job.job_id.empty()) {
    throw ValidationError("job_id must be non-empty");
  }
  if (job.modes == 0) {
    throw ValidationError("modes must be greater than zero");
  }
  if (job.shots == 0) {
    throw ValidationError("shots must be greater than zero");
  }
  if (caps.max_modes != 0 && job.modes > caps.max_modes) {
    throw ValidationError("job exceeds device mode limit");
  }
  if (caps.max_shots != 0 && job.shots > caps.max_shots) {
    throw ValidationError("job exceeds device shot limit");
  }
  for (const auto& operation : job.operations) {
    if (!contains(caps.supported_operations, operation)) {
      throw ValidationError("job contains unsupported operation: " + operation);
    }
  }
}

}  // namespace

HAL::HAL(std::unique_ptr<Transport> transport)
    : device_("in-memory-fpga-device", std::move(transport)) {}

void HAL::initialize() {
  device_.initialize();
}

void HAL::submit_job(const RuntimeJob& job) {
  validate_job_against_capabilities(job, capabilities());
  device_.submit_job(job);
}

RuntimeResult HAL::read_result(const std::string& job_id) {
  if (job_id.empty()) {
    throw ValidationError("job_id must be non-empty");
  }
  return device_.read_result(job_id);
}

void HAL::submit_control(const ControlRequest& request) {
  validate_control_request(request);
  const auto caps = capabilities();
  if (caps.max_shots != 0 && request.shots > caps.max_shots) {
    throw ValidationError("control request exceeds device shot limit");
  }
  device_.submit_control(request);
}

ControlReply HAL::read_control_result(const std::string& job_id) {
  if (job_id.empty()) {
    throw ValidationError("control job_id must be non-empty");
  }
  return device_.read_control_result(job_id);
}

void HAL::shutdown() {
  device_.shutdown();
}

const Device& HAL::device() const {
  return device_;
}

DeviceCapabilities HAL::capabilities() const {
  return device_.capabilities();
}

bool HAL::submit_job(const std::string& job_payload) {
  return device_.submit_job(job_payload);
}

std::string HAL::read_results() {
  return device_.read_results();
}

}  // namespace photon_qdrivers
