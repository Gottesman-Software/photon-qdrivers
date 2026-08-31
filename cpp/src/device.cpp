#include "photon_qdrivers/device.hpp"

#include <utility>

namespace photon_qdrivers {

Device::Device(std::string id, std::unique_ptr<Transport> transport)
    : id_(std::move(id)), fpga_driver_(std::move(transport)) {}

void Device::initialize() {
  fpga_driver_.initialize();
}

void Device::submit_job(const RuntimeJob& job) {
  fpga_driver_.submit_job(job);
}

RuntimeResult Device::read_result(const std::string& job_id) {
  return fpga_driver_.read_result(job_id);
}

void Device::submit_control(const ControlRequest& request) {
  fpga_driver_.submit_control(request);
}

ControlReply Device::read_control_result(const std::string& job_id) {
  return fpga_driver_.read_control_result(job_id);
}

void Device::shutdown() {
  fpga_driver_.shutdown();
}

const std::string& Device::id() const {
  return id_;
}

bool Device::initialized() const {
  return fpga_driver_.initialized();
}

DeviceCapabilities Device::capabilities() const {
  DeviceCapabilities caps = fpga_driver_.capabilities();
  if (!id_.empty() && id_ != "in-memory-fpga-device") {
    caps.device_id = id_;
  }
  return caps;
}

bool Device::submit_job(const std::string& job_payload) {
  return fpga_driver_.submit_job(job_payload);
}

std::string Device::read_results() {
  return fpga_driver_.read_results();
}

}  // namespace photon_qdrivers
