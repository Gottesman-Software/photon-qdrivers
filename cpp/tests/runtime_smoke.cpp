#include "photon_qdrivers/runtime.hpp"

#include <cassert>
#include <iostream>

int main() {
  photon_qdrivers::Runtime runtime;
  assert(!runtime.initialized());

  runtime.initialize();
  assert(runtime.initialized());

  const auto capabilities = runtime.capabilities();
  assert(capabilities.max_modes >= 4);
  assert(capabilities.max_shots >= 1000);

  photon_qdrivers::RuntimeJob job;
  job.job_id = "cpp-smoke-job";
  job.circuit_ir = "photonic-circuit-v1";
  job.modes = 4;
  job.shots = 1000;
  job.operations = {"BS", "PS", "photon_counting"};

  runtime.submit_job(job);
  const auto result = runtime.read_result(job.job_id);

  assert(result.job_id == job.job_id);
  assert(result.status == photon_qdrivers::JobStatus::Completed);
  assert(result.shots == job.shots);

  std::uint64_t total_counts = 0;
  for (const auto& entry : result.counts) {
    total_counts += entry.second;
  }
  assert(total_counts == job.shots);

  bool rejected = false;
  try {
    photon_qdrivers::RuntimeJob invalid_job = job;
    invalid_job.job_id = "invalid-job";
    invalid_job.operations = {"unsupported"};
    runtime.submit_job(invalid_job);
  } catch (const photon_qdrivers::ValidationError&) {
    rejected = true;
  }
  assert(rejected);

  runtime.shutdown();
  assert(!runtime.initialized());

  std::cout << "runtime smoke test passed\n";
  return 0;
}
