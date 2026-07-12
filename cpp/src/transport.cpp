#include "photon_qdrivers/transport.hpp"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <utility>

namespace photon_qdrivers {

namespace {

void ensure_open(bool open) {
  if (!open) {
    throw TransportError("transport is not open");
  }
}

std::map<std::string, std::uint64_t> deterministic_counts(std::uint32_t modes,
                                                          std::uint64_t shots) {
  const std::uint32_t bounded_modes = std::max<std::uint32_t>(1, std::min<std::uint32_t>(modes, 16));
  const std::uint64_t state_count = std::min<std::uint64_t>(4, 1ULL << bounded_modes);
  const std::uint64_t base = shots / state_count;
  const std::uint64_t remainder = shots % state_count;

  std::map<std::string, std::uint64_t> counts;
  for (std::uint64_t state = 0; state < state_count; ++state) {
    std::string key(bounded_modes, '0');
    for (std::uint32_t bit = 0; bit < bounded_modes; ++bit) {
      const bool set = ((state >> (bounded_modes - bit - 1)) & 1U) != 0;
      key[bit] = set ? '1' : '0';
    }
    counts[key] = base + (state < remainder ? 1 : 0);
  }
  return counts;
}

std::string join_operations(const std::vector<std::string>& operations) {
  std::ostringstream output;
  for (std::size_t index = 0; index < operations.size(); ++index) {
    if (index != 0) {
      output << ",";
    }
    output << operations[index];
  }
  return output.str();
}

std::string trim(const std::string& value) {
  const auto first = value.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return "";
  }
  const auto last = value.find_last_not_of(" \t\r\n");
  return value.substr(first, last - first + 1);
}

bool starts_with(const std::string& value, const std::string& prefix) {
  return value.size() >= prefix.size() && value.compare(0, prefix.size(), prefix) == 0;
}

JobStatus parse_status(const std::string& status) {
  const std::string normalized = trim(status);
  if (normalized == "completed" || normalized == "complete" || normalized == "success") {
    return JobStatus::Completed;
  }
  if (normalized == "submitted" || normalized == "queued" || normalized == "running") {
    return JobStatus::Submitted;
  }
  if (normalized == "created" || normalized == "open") {
    return JobStatus::Created;
  }
  return JobStatus::Failed;
}

RuntimeResult parse_result_frame(const std::vector<std::string>& lines) {
  RuntimeResult result;
  result.status = JobStatus::Failed;

  for (const auto& raw_line : lines) {
    const std::string line = trim(raw_line);
    if (starts_with(line, "job_id=")) {
      result.job_id = line.substr(7);
    } else if (starts_with(line, "status=")) {
      result.status = parse_status(line.substr(7));
    } else if (starts_with(line, "shots=")) {
      result.shots = static_cast<std::uint64_t>(std::stoull(line.substr(6)));
    } else if (starts_with(line, "message=")) {
      result.message = line.substr(8);
    } else if (starts_with(line, "count=")) {
      const std::string count_line = line.substr(6);
      const auto separator = count_line.find(':');
      if (separator == std::string::npos) {
        throw TransportError("malformed FPGA result count line");
      }
      const std::string state = count_line.substr(0, separator);
      const auto count = static_cast<std::uint64_t>(std::stoull(count_line.substr(separator + 1)));
      result.counts[state] = count;
    }
  }

  if (result.message.empty()) {
    result.message = "completed by FPGA mailbox transport";
  }
  return result;
}

RuntimeResult unavailable_result(const std::string& job_id, const std::string& message) {
  return RuntimeResult{
      job_id,
      JobStatus::Failed,
      0,
      {},
      message,
  };
}

}  // namespace

InMemoryTransport::InMemoryTransport(DeviceCapabilities capabilities)
    : capabilities_(std::move(capabilities)) {}

void InMemoryTransport::open() {
  open_ = true;
}

void InMemoryTransport::close() {
  open_ = false;
  last_job_.reset();
}

bool InMemoryTransport::is_open() const {
  return open_;
}

DeviceCapabilities InMemoryTransport::capabilities() const {
  return capabilities_;
}

void InMemoryTransport::submit(const RuntimeJob& job) {
  ensure_open(open_);
  last_job_ = job;
}

RuntimeResult InMemoryTransport::read_result(const std::string& job_id) {
  ensure_open(open_);
  if (!last_job_.has_value() || last_job_->job_id != job_id) {
    return RuntimeResult{
        job_id,
        JobStatus::Failed,
        0,
        {},
        "job result is not available",
    };
  }

  return RuntimeResult{
      last_job_->job_id,
      JobStatus::Completed,
      last_job_->shots,
      deterministic_counts(last_job_->modes, last_job_->shots),
      "completed by in-memory transport",
  };
}

DeviceCapabilities InMemoryTransport::default_capabilities() {
  return DeviceCapabilities{
      "in-memory-fpga-device",
      32,
      10'000'000,
      {"BS", "PS", "photon_counting"},
      false,
      false,
  };
}

FPGAMailboxTransport::FPGAMailboxTransport(std::string command_path,
                                           std::string result_path,
                                           DeviceCapabilities capabilities)
    : command_path_(std::move(command_path)),
      result_path_(std::move(result_path)),
      capabilities_(std::move(capabilities)) {}

void FPGAMailboxTransport::open() {
  if (command_path_.empty()) {
    throw TransportError("FPGA command mailbox path is empty");
  }
  if (result_path_.empty()) {
    throw TransportError("FPGA result mailbox path is empty");
  }

  std::ofstream command_stream(command_path_, std::ios::app);
  if (!command_stream) {
    throw TransportError("failed to open FPGA command mailbox: " + command_path_);
  }
  open_ = true;
}

void FPGAMailboxTransport::close() {
  open_ = false;
}

bool FPGAMailboxTransport::is_open() const {
  return open_;
}

DeviceCapabilities FPGAMailboxTransport::capabilities() const {
  return capabilities_;
}

void FPGAMailboxTransport::submit(const RuntimeJob& job) {
  ensure_open(open_);

  std::ofstream command_stream(command_path_, std::ios::app);
  if (!command_stream) {
    throw TransportError("failed to write FPGA command mailbox: " + command_path_);
  }

  command_stream << "PQDR_JOB_V1\n";
  command_stream << "job_id=" << job.job_id << "\n";
  command_stream << "modes=" << job.modes << "\n";
  command_stream << "shots=" << job.shots << "\n";
  command_stream << "operations=" << join_operations(job.operations) << "\n";
  command_stream << "circuit_ir=" << job.circuit_ir << "\n";
  command_stream << "END\n";
}

RuntimeResult FPGAMailboxTransport::read_result(const std::string& job_id) {
  ensure_open(open_);

  std::ifstream result_stream(result_path_);
  if (!result_stream) {
    return unavailable_result(job_id, "FPGA result mailbox is not available: " + result_path_);
  }

  std::string line;
  bool in_frame = false;
  std::vector<std::string> frame_lines;
  RuntimeResult latest_match = unavailable_result(job_id, "job result is not available");

  while (std::getline(result_stream, line)) {
    const std::string trimmed = trim(line);
    if (trimmed == "PQDR_RESULT_V1") {
      in_frame = true;
      frame_lines.clear();
      continue;
    }

    if (!in_frame) {
      continue;
    }

    if (trimmed == "END") {
      RuntimeResult result = parse_result_frame(frame_lines);
      if (result.job_id == job_id) {
        latest_match = std::move(result);
      }
      in_frame = false;
      frame_lines.clear();
      continue;
    }

    frame_lines.push_back(line);
  }

  return latest_match;
}

const std::string& FPGAMailboxTransport::command_path() const {
  return command_path_;
}

const std::string& FPGAMailboxTransport::result_path() const {
  return result_path_;
}

DeviceCapabilities FPGAMailboxTransport::default_capabilities() {
  return DeviceCapabilities{
      "fpga-mailbox-device",
      32,
      10'000'000,
      {"BS", "PS", "photon_counting"},
      true,
      true,
  };
}

DeviceCapabilities FPGAMailboxTransport::red_pitaya_stemlab_125_14_capabilities() {
  return DeviceCapabilities{
      "red-pitaya-stemlab-125-14",
      8,
      1'000'000,
      {"BS", "PS", "photon_counting"},
      true,
      true,
  };
}

}  // namespace photon_qdrivers
