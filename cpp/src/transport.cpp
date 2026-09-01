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

std::uint64_t parse_uint64_field(const std::string& value, const char* field) {
  try {
    std::size_t consumed = 0;
    const auto parsed = static_cast<std::uint64_t>(std::stoull(value, &consumed));
    if (consumed != value.size()) {
      throw TransportError(std::string("malformed control-result field: ") + field);
    }
    return parsed;
  } catch (const TransportError&) {
    throw;
  } catch (const std::exception&) {
    throw TransportError(std::string("malformed control-result field: ") + field);
  }
}

ControlReply unavailable_control_result(const std::string& job_id,
                                        const std::string& message) {
  ControlReply reply;
  reply.job_id = job_id;
  reply.message = message;
  return reply;
}

ControlReply parse_control_result_frame(const std::vector<std::string>& lines) {
  ControlReply result;
  std::size_t acquisition_payload_length = 0;
  bool saw_payload_length = false;

  for (const auto& raw_line : lines) {
    const std::string line = trim(raw_line);
    if (starts_with(line, "protocol=")) {
      result.protocol = line.substr(9);
    } else if (starts_with(line, "job_id=")) {
      result.job_id = line.substr(7);
    } else if (starts_with(line, "program_id=")) {
      result.program_id = line.substr(11);
    } else if (starts_with(line, "profile_id=")) {
      result.profile_id = line.substr(11);
    } else if (starts_with(line, "profile_digest=")) {
      result.profile_digest = line.substr(15);
    } else if (starts_with(line, "program_digest=")) {
      result.program_digest = line.substr(15);
    } else if (starts_with(line, "envelope_digest=")) {
      result.envelope_digest = line.substr(16);
    } else if (starts_with(line, "acquisition_digest=")) {
      result.acquisition_digest = line.substr(19);
    } else if (starts_with(line, "status=")) {
      result.status = parse_status(line.substr(7));
    } else if (starts_with(line, "shots=")) {
      result.shots = parse_uint64_field(line.substr(6), "shots");
    } else if (starts_with(line, "repetition_ticks=")) {
      result.repetition_ticks =
          parse_uint64_field(line.substr(17), "repetition_ticks");
    } else if (starts_with(line, "sweep_points=")) {
      result.sweep_points = parse_uint64_field(line.substr(13), "sweep_points");
    } else if (starts_with(line, "event_count=")) {
      result.event_count = parse_uint64_field(line.substr(12), "event_count");
    } else if (starts_with(line, "acquisition_count=")) {
      result.acquisition_count =
          parse_uint64_field(line.substr(18), "acquisition_count");
    } else if (starts_with(line, "total_device_ticks=")) {
      result.total_device_ticks =
          parse_uint64_field(line.substr(19), "total_device_ticks");
    } else if (starts_with(line, "overflowed_acquisitions=")) {
      result.overflowed_acquisitions =
          parse_uint64_field(line.substr(24), "overflowed_acquisitions");
    } else if (starts_with(line, "dropped_events=")) {
      result.dropped_events =
          parse_uint64_field(line.substr(15), "dropped_events");
    } else if (starts_with(line, "acquisition_payload_length=")) {
      acquisition_payload_length = static_cast<std::size_t>(
          parse_uint64_field(line.substr(27), "acquisition_payload_length"));
      saw_payload_length = true;
    } else if (starts_with(line, "acquisition_payload=")) {
      result.acquisition_payload = raw_line.substr(20);
    } else if (starts_with(line, "message=")) {
      result.message = line.substr(8);
    }
  }

  if (!saw_payload_length ||
      result.acquisition_payload.size() != acquisition_payload_length) {
    throw TransportError("control-result acquisition_payload length mismatch");
  }
  validate_control_reply(result);
  return result;
}

void validate_control_correlation(const ControlRequest& request,
                                  const ControlReply& reply) {
  if (reply.job_id != request.job_id || reply.program_id != request.program_id ||
      reply.profile_id != request.profile_id ||
      reply.profile_digest != request.profile_digest ||
      reply.program_digest != request.program_digest ||
      reply.envelope_digest != request.envelope_digest ||
      reply.shots != request.shots ||
      reply.repetition_ticks != request.repetition_ticks ||
      reply.sweep_points != request.sweep_points ||
      reply.event_count != request.event_count) {
    throw TransportError("control-result does not correlate with submitted request");
  }
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
  last_control_request_.reset();
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

void InMemoryTransport::submit_control(const ControlRequest& request) {
  ensure_open(open_);
  validate_control_request(request);
  last_control_request_ = request;
}

ControlReply InMemoryTransport::read_control_result(const std::string& job_id) {
  ensure_open(open_);
  if (!last_control_request_.has_value() || last_control_request_->job_id != job_id) {
    return unavailable_control_result(job_id, "control result is not available");
  }
  return complete_control_request(
      *last_control_request_, "completed by in-memory control transport");
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
  last_control_request_.reset();
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

void FPGAMailboxTransport::submit_control(const ControlRequest& request) {
  ensure_open(open_);
  validate_control_request(request);

  std::ofstream command_stream(command_path_, std::ios::app);
  if (!command_stream) {
    throw TransportError("failed to write FPGA command mailbox: " + command_path_);
  }

  command_stream << kControlProtocolVersion << "\n";
  command_stream << "job_id=" << request.job_id << "\n";
  command_stream << "program_id=" << request.program_id << "\n";
  command_stream << "profile_id=" << request.profile_id << "\n";
  command_stream << "profile_digest=" << request.profile_digest << "\n";
  command_stream << "program_digest=" << request.program_digest << "\n";
  command_stream << "envelope_digest=" << request.envelope_digest << "\n";
  command_stream << "shots=" << request.shots << "\n";
  command_stream << "repetition_ticks=" << request.repetition_ticks << "\n";
  command_stream << "sweep_points=" << request.sweep_points << "\n";
  command_stream << "event_count=" << request.event_count << "\n";
  command_stream << "compiled_payload_length=" << request.compiled_payload.size() << "\n";
  command_stream << "compiled_payload=" << request.compiled_payload << "\n";
  command_stream << "END\n";
  last_control_request_ = request;
}

ControlReply FPGAMailboxTransport::read_control_result(const std::string& job_id) {
  ensure_open(open_);

  std::ifstream result_stream(result_path_);
  if (!result_stream) {
    return unavailable_control_result(
        job_id, "FPGA control-result mailbox is not available: " + result_path_);
  }

  std::string line;
  bool in_frame = false;
  std::vector<std::string> frame_lines;
  ControlReply latest_match =
      unavailable_control_result(job_id, "control result is not available");

  while (std::getline(result_stream, line)) {
    const std::string trimmed = trim(line);
    if (trimmed == kControlResultProtocolVersion) {
      in_frame = true;
      frame_lines.clear();
      frame_lines.push_back(std::string("protocol=") + kControlResultProtocolVersion);
      continue;
    }
    if (!in_frame) {
      continue;
    }
    if (trimmed == "END") {
      ControlReply result = parse_control_result_frame(frame_lines);
      if (result.job_id == job_id) {
        if (!last_control_request_.has_value() ||
            last_control_request_->job_id != job_id) {
          throw TransportError("control-result has no matching submitted request");
        }
        validate_control_correlation(*last_control_request_, result);
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
