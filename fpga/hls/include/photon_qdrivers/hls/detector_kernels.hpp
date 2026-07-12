#pragma once

#include <cstdint>

namespace photon_qdrivers::hls {

constexpr int kMaxDetectors = 32;
constexpr int kMaxHistogramBins = 1 << 16;

using sample_t = std::uint16_t;
using detector_mask_t = std::uint32_t;
using count_t = std::uint32_t;

struct DetectorThresholdConfig {
  sample_t threshold{0};
  int detector_count{0};
};

struct CoincidenceConfig {
  int detector_count{0};
  int minimum_hits{2};
};

detector_mask_t threshold_sample(const sample_t* samples,
                                 const sample_t* thresholds,
                                 int detector_count);

void threshold_stream(const sample_t* samples,
                      const sample_t* thresholds,
                      detector_mask_t* masks,
                      int frame_count,
                      int detector_count);

void histogram_masks(const detector_mask_t* masks,
                     count_t* histogram,
                     int frame_count,
                     int bin_count);

count_t count_coincidences(const detector_mask_t* masks,
                           int frame_count,
                           int minimum_hits);

int popcount_mask(detector_mask_t mask);

}  // namespace photon_qdrivers::hls
