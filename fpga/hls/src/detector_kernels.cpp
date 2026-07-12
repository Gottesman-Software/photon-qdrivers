#include "photon_qdrivers/hls/detector_kernels.hpp"

namespace photon_qdrivers::hls {

namespace {

int bounded_detector_count(int detector_count) {
  if (detector_count < 0) {
    return 0;
  }
  if (detector_count > kMaxDetectors) {
    return kMaxDetectors;
  }
  return detector_count;
}

}  // namespace

int popcount_mask(detector_mask_t mask) {
  int count = 0;
  while (mask != 0) {
    count += static_cast<int>(mask & 1U);
    mask >>= 1U;
  }
  return count;
}

detector_mask_t threshold_sample(const sample_t* samples,
                                 const sample_t* thresholds,
                                 int detector_count) {
  detector_mask_t mask = 0;
  const int bounded_count = bounded_detector_count(detector_count);

  for (int detector = 0; detector < bounded_count; ++detector) {
#ifdef __SYNTHESIS__
#pragma HLS PIPELINE II=1
#endif
    if (samples[detector] >= thresholds[detector]) {
      mask |= static_cast<detector_mask_t>(1U) << detector;
    }
  }

  return mask;
}

void threshold_stream(const sample_t* samples,
                      const sample_t* thresholds,
                      detector_mask_t* masks,
                      int frame_count,
                      int detector_count) {
  const int bounded_count = bounded_detector_count(detector_count);

  for (int frame = 0; frame < frame_count; ++frame) {
#ifdef __SYNTHESIS__
#pragma HLS LOOP_TRIPCOUNT min=1 max=4096
#endif
    masks[frame] = threshold_sample(&samples[frame * bounded_count], thresholds, bounded_count);
  }
}

void histogram_masks(const detector_mask_t* masks,
                     count_t* histogram,
                     int frame_count,
                     int bin_count) {
  if (bin_count <= 0) {
    return;
  }

  const int bounded_bins = bin_count > kMaxHistogramBins ? kMaxHistogramBins : bin_count;

  for (int bin = 0; bin < bounded_bins; ++bin) {
#ifdef __SYNTHESIS__
#pragma HLS PIPELINE II=1
#endif
    histogram[bin] = 0;
  }

  for (int frame = 0; frame < frame_count; ++frame) {
#ifdef __SYNTHESIS__
#pragma HLS PIPELINE II=1
#endif
    const detector_mask_t mask = masks[frame];
    if (mask < static_cast<detector_mask_t>(bounded_bins)) {
      histogram[mask] += 1;
    }
  }
}

count_t count_coincidences(const detector_mask_t* masks,
                           int frame_count,
                           int minimum_hits) {
  count_t coincidences = 0;
  const int required_hits = minimum_hits < 1 ? 1 : minimum_hits;

  for (int frame = 0; frame < frame_count; ++frame) {
#ifdef __SYNTHESIS__
#pragma HLS PIPELINE II=1
#endif
    if (popcount_mask(masks[frame]) >= required_hits) {
      coincidences += 1;
    }
  }

  return coincidences;
}

}  // namespace photon_qdrivers::hls
