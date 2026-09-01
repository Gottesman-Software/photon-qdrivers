#include "photon_qdrivers/runtime.hpp"

#include <utility>

namespace photon_qdrivers {

Runtime::Runtime(std::unique_ptr<Transport> transport)
    : hal_(std::move(transport)) {}

void Runtime::initialize() {
  hal_.initialize();
  initialized_ = true;
}

void Runtime::submit_job(const RuntimeJob& job) {
  if (!initialized_) {
    throw RuntimeError("runtime is not initialized");
  }

  hal_.submit_job(job);
  last_job_id_ = job.job_id;
}

RuntimeResult Runtime::read_result(const std::string& job_id) {
  if (!initialized_) {
    throw RuntimeError("runtime is not initialized");
  }

  return hal_.read_result(job_id);
}

void Runtime::submit_control(const ControlRequest& request) {
  if (!initialized_) {
    throw RuntimeError("runtime is not initialized");
  }
  hal_.submit_control(request);
  last_job_id_ = request.job_id;
}

ControlReply Runtime::read_control_result(const std::string& job_id) {
  if (!initialized_) {
    throw RuntimeError("runtime is not initialized");
  }
  return hal_.read_control_result(job_id);
}

void Runtime::shutdown() {
  hal_.shutdown();
  initialized_ = false;
  last_job_id_.clear();
}

bool Runtime::initialized() const {
  return initialized_;
}

DeviceCapabilities Runtime::capabilities() const {
  return hal_.capabilities();
}

bool Runtime::submit_job(const std::string& job_payload) {
  if (!initialized_) {
    return false;
  }

  hal_.submit_job(job_payload);
  last_job_id_ = "compat-job";
  return true;
}

std::string Runtime::read_results() {
  if (!initialized_) {
    return R"({"status":"not_initialized"})";
  }

  return hal_.read_results();
}

}  // namespace photon_qdrivers
