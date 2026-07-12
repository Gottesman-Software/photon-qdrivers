#pragma once

#include <optional>
#include <string>
#include <vector>

#include "photon_qdrivers/types.hpp"

namespace photon_qdrivers {

class Transport {
public:
  virtual ~Transport() = default;

  virtual void open() = 0;
  virtual void close() = 0;
  virtual bool is_open() const = 0;
  virtual DeviceCapabilities capabilities() const = 0;
  virtual void submit(const RuntimeJob& job) = 0;
  virtual RuntimeResult read_result(const std::string& job_id) = 0;
};

class InMemoryTransport final : public Transport {
public:
  explicit InMemoryTransport(DeviceCapabilities capabilities = default_capabilities());

  void open() override;
  void close() override;
  bool is_open() const override;
  DeviceCapabilities capabilities() const override;
  void submit(const RuntimeJob& job) override;
  RuntimeResult read_result(const std::string& job_id) override;

  static DeviceCapabilities default_capabilities();

private:
  bool open_{false};
  DeviceCapabilities capabilities_;
  std::optional<RuntimeJob> last_job_;
};

class FPGAMailboxTransport final : public Transport {
public:
  FPGAMailboxTransport(std::string command_path,
                       std::string result_path,
                       DeviceCapabilities capabilities = default_capabilities());

  void open() override;
  void close() override;
  bool is_open() const override;
  DeviceCapabilities capabilities() const override;
  void submit(const RuntimeJob& job) override;
  RuntimeResult read_result(const std::string& job_id) override;

  const std::string& command_path() const;
  const std::string& result_path() const;

  static DeviceCapabilities default_capabilities();
  static DeviceCapabilities red_pitaya_stemlab_125_14_capabilities();

private:
  bool open_{false};
  std::string command_path_;
  std::string result_path_;
  DeviceCapabilities capabilities_;
};

}  // namespace photon_qdrivers
