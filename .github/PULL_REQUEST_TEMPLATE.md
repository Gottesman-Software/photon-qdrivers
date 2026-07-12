## Summary

Describe the change and why it is needed.

## Type

- [ ] Python API
- [ ] Emulator adapter
- [ ] Hardware adapter
- [ ] C++ runtime / HAL
- [ ] FPGA RTL / HLS
- [ ] Documentation
- [ ] Tests / CI

## Verification

Commands run:

```bash
pytest
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

## Checklist

- [ ] Tests or examples were added/updated where needed.
- [ ] Documentation was updated for public behavior changes.
- [ ] New dependencies are optional or justified.
- [ ] Hardware/emulator claims are sourced or reproducible.
- [ ] No credentials, private endpoints, or lab secrets are included.
