#pragma once

#include <stdint.h>

#ifdef _WIN32
#  ifdef PHOTON_QDRIVERS_CAPI_EXPORTS
#    define PHOTON_QDRIVERS_CAPI_API __declspec(dllexport)
#  else
#    define PHOTON_QDRIVERS_CAPI_API __declspec(dllimport)
#  endif
#else
#  define PHOTON_QDRIVERS_CAPI_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct pqdr_runtime pqdr_runtime;

PHOTON_QDRIVERS_CAPI_API pqdr_runtime* pqdr_runtime_create(void);
PHOTON_QDRIVERS_CAPI_API pqdr_runtime* pqdr_runtime_create_fpga_mailbox(
    const char* command_path,
    const char* result_path);
PHOTON_QDRIVERS_CAPI_API pqdr_runtime* pqdr_runtime_create_red_pitaya(
    const char* command_path,
    const char* result_path);
PHOTON_QDRIVERS_CAPI_API void pqdr_runtime_destroy(pqdr_runtime* handle);

PHOTON_QDRIVERS_CAPI_API int pqdr_runtime_initialize(pqdr_runtime* handle);
PHOTON_QDRIVERS_CAPI_API int pqdr_runtime_shutdown(pqdr_runtime* handle);
PHOTON_QDRIVERS_CAPI_API int pqdr_runtime_submit_job(
    pqdr_runtime* handle,
    const char* job_id,
    const char* circuit_ir,
    uint32_t modes,
    uint64_t shots,
    const char* operations_csv);
PHOTON_QDRIVERS_CAPI_API int pqdr_runtime_submit_control(
    pqdr_runtime* handle,
    const char* job_id,
    const char* program_id,
    const char* profile_id,
    const char* profile_digest,
    const char* program_digest,
    const char* envelope_digest,
    const char* compiled_payload,
    uint64_t shots,
    uint64_t repetition_ticks,
    uint64_t sweep_points,
    uint64_t event_count);

PHOTON_QDRIVERS_CAPI_API const char* pqdr_runtime_read_result(
    pqdr_runtime* handle,
    const char* job_id);
PHOTON_QDRIVERS_CAPI_API const char* pqdr_runtime_read_control_result(
    pqdr_runtime* handle,
    const char* job_id);
PHOTON_QDRIVERS_CAPI_API const char* pqdr_runtime_capabilities(pqdr_runtime* handle);
PHOTON_QDRIVERS_CAPI_API const char* pqdr_runtime_last_error(pqdr_runtime* handle);
PHOTON_QDRIVERS_CAPI_API const char* pqdr_runtime_version(void);

#ifdef __cplusplus
}
#endif
