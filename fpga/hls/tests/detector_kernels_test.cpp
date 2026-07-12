#include "photon_qdrivers/hls/detector_kernels.hpp"

#include <array>
#include <cassert>
#include <iostream>

int main() {
  using namespace photon_qdrivers::hls;

  constexpr int detectors = 4;
  constexpr int frames = 5;
  constexpr int bins = 1 << detectors;

  const std::array<sample_t, detectors> thresholds{10, 20, 30, 40};
  const std::array<sample_t, frames * detectors> samples{
      10, 19, 31, 0,
      9,  20, 30, 41,
      0,  0,  0,  0,
      11, 21, 31, 41,
      100, 1,  1,  100,
  };

  std::array<detector_mask_t, frames> masks{};
  threshold_stream(samples.data(), thresholds.data(), masks.data(), frames, detectors);

  assert(masks[0] == 0b0101);
  assert(masks[1] == 0b1110);
  assert(masks[2] == 0b0000);
  assert(masks[3] == 0b1111);
  assert(masks[4] == 0b1001);

  std::array<count_t, bins> histogram{};
  histogram_masks(masks.data(), histogram.data(), frames, bins);

  assert(histogram[0b0101] == 1);
  assert(histogram[0b1110] == 1);
  assert(histogram[0b0000] == 1);
  assert(histogram[0b1111] == 1);
  assert(histogram[0b1001] == 1);

  assert(count_coincidences(masks.data(), frames, 2) == 4);
  assert(count_coincidences(masks.data(), frames, 4) == 1);
  assert(popcount_mask(0b101101) == 4);

  std::cout << "detector HLS kernels test passed\n";
  return 0;
}
