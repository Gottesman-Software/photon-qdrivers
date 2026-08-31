#pragma once

#include <memory>
#include <string>

#include "photon_qdrivers/hal.hpp"
#include "photon_qdrivers/types.hpp"

namespace photon_qdrivers {

class Runtime {
public:
  explicit Runtime(std::unique_ptr<Transport> transport = nullptr);

  void initialize();
  void submit_job(const RuntimeJob& job);
  RuntimeResult read_result(const std::string& job_id);
  void submit_control(const ControlRequest& request);
  ControlReply read_control_result(const std::string& job_id);
  void shutdown();

  bool initialized() const;
  DeviceCapabilities capabilities() const;

  bool submit_job(const std::string& job_payload);
  std::string read_results();

private:
  bool initialized_{false};
  HAL hal_;
  std::string last_job_id_;
};

}  // namespace photon_qdrivers
