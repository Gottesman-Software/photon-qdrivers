#include "photon_qdrivers/c_api.h"

#include <algorithm>
#include <cstdint>
#include <exception>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include "photon_qdrivers/runtime.hpp"
#include "photon_qdrivers/transport.hpp"
#include "photon_qdrivers/types.hpp"

struct pqdr_runtime {
  pqdr_runtime() : runtime(nullptr) {}
  explicit pqdr_runtime(std::unique_ptr<photon_qdrivers::Transport> transport)
      : runtime(std::move(transport)) {}

  photon_qdrivers::Runtime runtime;
  std::string last_error;
  std::string scratch;
};

namespace {

std::vector<std::string> split_operations(const char* operations_csv) {
  std::vector<std::string> operations;
  if (operations_csv == nullptr) {
    return operations;
  }

  std::string input(operations_csv);
  std::size_t start = 0;
  while (start <= input.size()) {
    const std::size_t comma = input.find(',', start);
    const std::size_t end = comma == std::string::npos ? input.size() : comma;
    std::string operation = input.substr(start, end - start);
    operation.erase(
        std::remove_if(operation.begin(), operation.end(), [](unsigned char value) {
          return value == ' ' || value == '\n' || value == '\r' || value == '\t';
        }),
        operation.end());
    if (!operation.empty()) {
      operations.push_back(operation);
    }
    if (comma == std::string::npos) {
      break;
    }
    start = comma + 1;
  }
  return operations;
}

std::string json_escape(const std::string& value) {
  std::ostringstream out;
  for (const char ch : value) {
    switch (ch) {
      case '"':
        out << "\\\"";
        break;
      case '\\':
        out << "\\\\";
        break;
      case '\b':
        out << "\\b";
        break;
      case '\f':
        out << "\\f";
        break;
      case '\n':
        out << "\\n";
        break;
      case '\r':
        out << "\\r";
        break;
      case '\t':
        out << "\\t";
        break;
      default:
        const auto byte = static_cast<unsigned char>(ch);
        if (byte < 0x20) {
          out << "\\u00";
          const char* digits = "0123456789abcdef";
          out << digits[(byte >> 4) & 0x0F] << digits[byte & 0x0F];
        } else {
          out << ch;
        }
        break;
    }
  }
  return out.str();
}

std::string result_to_json(const photon_qdrivers::RuntimeResult& result) {
  std::ostringstream out;
  out << "{\"job_id\":\"" << json_escape(result.job_id) << "\",";
  out << "\"status\":\"" << photon_qdrivers::to_string(result.status) << "\",";
  out << "\"shots\":" << result.shots << ",";
  out << "\"counts\":{";
  bool first = true;
  for (const auto& entry : result.counts) {
    if (!first) {
      out << ",";
    }
    first = false;
    out << "\"" << json_escape(entry.first) << "\":" << entry.second;
  }
  out << "},";
  out << "\"message\":\"" << json_escape(result.message) << "\"}";
  return out.str();
}

std::string capabilities_to_json(const photon_qdrivers::DeviceCapabilities& capabilities) {
  std::ostringstream out;
  out << "{\"device_id\":\"" << json_escape(capabilities.device_id) << "\",";
  out << "\"max_modes\":" << capabilities.max_modes << ",";
  out << "\"max_shots\":" << capabilities.max_shots << ",";
  out << "\"supported_operations\":[";
  for (std::size_t index = 0; index < capabilities.supported_operations.size(); ++index) {
    if (index != 0) {
      out << ",";
    }
    out << "\"" << json_escape(capabilities.supported_operations[index]) << "\"";
  }
  out << "],";
  out << "\"realtime\":" << (capabilities.realtime ? "true" : "false") << ",";
  out << "\"hardware_backed\":" << (capabilities.hardware_backed ? "true" : "false") << "}";
  return out.str();
}

void set_error(pqdr_runtime* handle, const std::string& message) {
  if (handle != nullptr) {
    handle->last_error = message;
  }
}

int failure(pqdr_runtime* handle, const std::string& message) {
  set_error(handle, message);
  return 1;
}

template <typename Fn>
int call_status(pqdr_runtime* handle, Fn&& fn) {
  if (handle == nullptr) {
    return 1;
  }

  try {
    fn();
    handle->last_error.clear();
    return 0;
  } catch (const std::exception& exc) {
    return failure(handle, exc.what());
  } catch (...) {
    return failure(handle, "unknown native runtime error");
  }
}

template <typename Fn>
const char* call_string(pqdr_runtime* handle, const char* fallback, Fn&& fn) {
  if (handle == nullptr) {
    return fallback;
  }

  try {
    handle->scratch = fn();
    handle->last_error.clear();
    return handle->scratch.c_str();
  } catch (const std::exception& exc) {
    set_error(handle, exc.what());
    handle->scratch = fallback;
    return handle->scratch.c_str();
  } catch (...) {
    set_error(handle, "unknown native runtime error");
    handle->scratch = fallback;
    return handle->scratch.c_str();
  }
}

}  // namespace

extern "C" {

pqdr_runtime* pqdr_runtime_create(void) {
  try {
    return new pqdr_runtime{};
  } catch (...) {
    return nullptr;
  }
}

pqdr_runtime* pqdr_runtime_create_fpga_mailbox(
    const char* command_path,
    const char* result_path) {
  if (command_path == nullptr || result_path == nullptr) {
    return nullptr;
  }

  try {
    auto transport = std::make_unique<photon_qdrivers::FPGAMailboxTransport>(
        command_path,
        result_path);
    return new pqdr_runtime(std::move(transport));
  } catch (...) {
    return nullptr;
  }
}

pqdr_runtime* pqdr_runtime_create_red_pitaya(
    const char* command_path,
    const char* result_path) {
  if (command_path == nullptr || result_path == nullptr) {
    return nullptr;
  }

  try {
    auto transport = std::make_unique<photon_qdrivers::FPGAMailboxTransport>(
        command_path,
        result_path,
        photon_qdrivers::FPGAMailboxTransport::red_pitaya_stemlab_125_14_capabilities());
    return new pqdr_runtime(std::move(transport));
  } catch (...) {
    return nullptr;
  }
}

void pqdr_runtime_destroy(pqdr_runtime* handle) {
  delete handle;
}

int pqdr_runtime_initialize(pqdr_runtime* handle) {
  return call_status(handle, [&]() {
    handle->runtime.initialize();
  });
}

int pqdr_runtime_shutdown(pqdr_runtime* handle) {
  return call_status(handle, [&]() {
    handle->runtime.shutdown();
  });
}

int pqdr_runtime_submit_job(
    pqdr_runtime* handle,
    const char* job_id,
    const char* circuit_ir,
    uint32_t modes,
    uint64_t shots,
    const char* operations_csv) {
  if (job_id == nullptr || circuit_ir == nullptr) {
    return failure(handle, "job_id and circuit_ir are required");
  }

  return call_status(handle, [&]() {
    photon_qdrivers::RuntimeJob job{
        job_id,
        circuit_ir,
        modes,
        shots,
        split_operations(operations_csv),
    };
    handle->runtime.submit_job(job);
  });
}

const char* pqdr_runtime_read_result(pqdr_runtime* handle, const char* job_id) {
  if (job_id == nullptr) {
    set_error(handle, "job_id is required");
    return "{\"status\":\"failed\",\"message\":\"job_id is required\"}";
  }

  return call_string(handle, "{\"status\":\"failed\"}", [&]() {
    return result_to_json(handle->runtime.read_result(job_id));
  });
}

const char* pqdr_runtime_capabilities(pqdr_runtime* handle) {
  return call_string(handle, "{}", [&]() {
    return capabilities_to_json(handle->runtime.capabilities());
  });
}

const char* pqdr_runtime_last_error(pqdr_runtime* handle) {
  if (handle == nullptr || handle->last_error.empty()) {
    return "";
  }
  return handle->last_error.c_str();
}

const char* pqdr_runtime_version(void) {
  return "0.1.0";
}

}  // extern "C"
