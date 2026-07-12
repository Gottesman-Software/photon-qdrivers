#pragma once

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace photon_qdrivers {

enum class JobStatus {
  Created,
  Submitted,
  Completed,
  Failed,
};

struct RuntimeJob {
  std::string job_id;
  std::string circuit_ir;
  std::uint32_t modes{0};
  std::uint64_t shots{0};
  std::vector<std::string> operations;
};

struct RuntimeResult {
  std::string job_id;
  JobStatus status{JobStatus::Created};
  std::uint64_t shots{0};
  std::map<std::string, std::uint64_t> counts;
  std::string message;
};

struct DeviceCapabilities {
  std::string device_id;
  std::uint32_t max_modes{0};
  std::uint64_t max_shots{0};
  std::vector<std::string> supported_operations;
  bool realtime{false};
  bool hardware_backed{false};
};

class RuntimeError : public std::runtime_error {
public:
  explicit RuntimeError(const std::string& message) : std::runtime_error(message) {}
};

class ValidationError : public RuntimeError {
public:
  explicit ValidationError(const std::string& message) : RuntimeError(message) {}
};

class TransportError : public RuntimeError {
public:
  explicit TransportError(const std::string& message) : RuntimeError(message) {}
};

const char* to_string(JobStatus status);

}  // namespace photon_qdrivers
