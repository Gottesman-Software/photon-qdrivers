#pragma once

#include <memory>
#include <string>

#include "photon_qdrivers/fpga_driver.hpp"
#include "photon_qdrivers/types.hpp"

namespace photon_qdrivers {

class Device {
public:
  explicit Device(std::string id = "in-memory-fpga-device",
                  std::unique_ptr<Transport> transport = nullptr);

  void initialize();
  void submit_job(const RuntimeJob& job);
  RuntimeResult read_result(const std::string& job_id);
  void shutdown();

  const std::string& id() const;
  bool initialized() const;
  DeviceCapabilities capabilities() const;

  bool submit_job(const std::string& job_payload);
  std::string read_results();

private:
  std::string id_;
  FPGADriver fpga_driver_;
};

}  // namespace photon_qdrivers
