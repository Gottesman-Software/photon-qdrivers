#pragma once

#include <memory>
#include <string>

#include "photon_qdrivers/transport.hpp"
#include "photon_qdrivers/types.hpp"

namespace photon_qdrivers {

class FPGADriver {
public:
  explicit FPGADriver(std::unique_ptr<Transport> transport = nullptr);

  void initialize();
  void submit_job(const RuntimeJob& job);
  RuntimeResult read_result(const std::string& job_id);
  void shutdown();

  bool initialized() const;
  DeviceCapabilities capabilities() const;

  bool submit_job(const std::string& job_payload);
  std::string read_results();

private:
  bool initialized_{false};
  std::unique_ptr<Transport> transport_;
  std::string last_job_id_;
};

}  // namespace photon_qdrivers
