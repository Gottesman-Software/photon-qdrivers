#pragma once

#include <memory>
#include <string>

#include "photon_qdrivers/device.hpp"
#include "photon_qdrivers/types.hpp"

namespace photon_qdrivers {

class HAL {
public:
  explicit HAL(std::unique_ptr<Transport> transport = nullptr);

  void initialize();
  void submit_job(const RuntimeJob& job);
  RuntimeResult read_result(const std::string& job_id);
  void submit_control(const ControlRequest& request);
  ControlReply read_control_result(const std::string& job_id);
  void shutdown();

  const Device& device() const;
  DeviceCapabilities capabilities() const;

  bool submit_job(const std::string& job_payload);
  std::string read_results();

private:
  Device device_;
};

}  // namespace photon_qdrivers
