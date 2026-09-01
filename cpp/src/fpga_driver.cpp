#include "photon_qdrivers/fpga_driver.hpp"

#include <sstream>
#include <utility>

namespace photon_qdrivers {

FPGADriver::FPGADriver(std::unique_ptr<Transport> transport)
    : transport_(std::move(transport)) {
  if (transport_ == nullptr) {
    transport_ = std::make_unique<InMemoryTransport>();
  }
}

void FPGADriver::initialize() {
  transport_->open();
  initialized_ = true;
}

void FPGADriver::submit_job(const RuntimeJob& job) {
  if (!initialized_) {
    throw RuntimeError("FPGA driver is not initialized");
  }

  transport_->submit(job);
  last_job_id_ = job.job_id;
}

RuntimeResult FPGADriver::read_result(const std::string& job_id) {
  if (!initialized_) {
    throw RuntimeError("FPGA driver is not initialized");
  }

  return transport_->read_result(job_id);
}

void FPGADriver::submit_control(const ControlRequest& request) {
  if (!initialized_) {
    throw RuntimeError("FPGA driver is not initialized");
  }
  transport_->submit_control(request);
  last_job_id_ = request.job_id;
}

ControlReply FPGADriver::read_control_result(const std::string& job_id) {
  if (!initialized_) {
    throw RuntimeError("FPGA driver is not initialized");
  }
  return transport_->read_control_result(job_id);
}

void FPGADriver::shutdown() {
  transport_->close();
  initialized_ = false;
  last_job_id_.clear();
}

bool FPGADriver::initialized() const {
  return initialized_;
}

DeviceCapabilities FPGADriver::capabilities() const {
  return transport_->capabilities();
}

bool FPGADriver::submit_job(const std::string& job_payload) {
  RuntimeJob job;
  job.job_id = "compat-job";
  job.circuit_ir = job_payload;
  job.modes = 1;
  job.shots = 1024;
  job.operations = {"photon_counting"};
  submit_job(job);
  return true;
}

std::string FPGADriver::read_results() {
  if (last_job_id_.empty()) {
    return R"({"status":"idle","counts":{}})";
  }

  const RuntimeResult result = read_result(last_job_id_);
  std::ostringstream output;
  output << R"({"job_id":")" << result.job_id << R"(","status":")" << to_string(result.status)
         << R"(","shots":)" << result.shots << R"(,"counts":{)";

  bool first = true;
  for (const auto& entry : result.counts) {
    if (!first) {
      output << ",";
    }
    output << "\"" << entry.first << "\":" << entry.second;
    first = false;
  }

  output << R"(}})";
  return output.str();
}

}  // namespace photon_qdrivers
