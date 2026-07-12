#include "photon_qdrivers/types.hpp"

namespace photon_qdrivers {

const char* to_string(JobStatus status) {
  switch (status) {
    case JobStatus::Created:
      return "created";
    case JobStatus::Submitted:
      return "submitted";
    case JobStatus::Completed:
      return "completed";
    case JobStatus::Failed:
      return "failed";
  }

  return "unknown";
}

}  // namespace photon_qdrivers
