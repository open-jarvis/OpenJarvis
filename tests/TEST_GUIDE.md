# NORA AI Testing & Validation Suite

## Unit Tests

### Identity System Tests
```bash
pytest tests/identity/test_manager.py -v
pytest tests/identity/test_personality.py -v
pytest tests/identity/test_branding.py -v
pytest tests/identity/test_modes.py -v
pytest tests/identity/test_router.py -v
pytest tests/identity/test_resource_monitor.py -v
```

### Device System Tests
```bash
pytest tests/devices/test_types.py -v
pytest tests/devices/test_manager.py -v
pytest tests/devices/test_pairing.py -v
```

### Permission System Tests
```bash
pytest tests/permissions/test_system.py -v
pytest tests/permissions/test_levels.py -v
```

### Tool Tests
```bash
pytest tests/tools/test_blender.py -v
pytest tests/tools/test_software_manager.py -v
pytest tests/tools/test_file_system.py -v
pytest tests/tools/test_terminal.py -v
```

### Network Tests
```bash
pytest tests/network/test_device_protocol.py -v
pytest tests/network/test_device_server.py -v
```

## Integration Tests

### Full Workflow Test
```bash
pytest tests/integration/test_complete_workflow.py -v
```

Tests:
1. Initialize NORA
2. Register device
3. Switch operating modes
4. Use model router
5. Execute specialized tools
6. Send commands
7. Verify responses

### Device Communication Test
```bash
pytest tests/integration/test_device_communication.py -v
```

Tests:
1. Start device server
2. Pair devices
3. Send signed messages
4. Verify signatures
5. Test replay prevention
6. Broadcast messages

### Cross-Device Test
```bash
pytest tests/integration/test_cross_device.py -v
```

Tests:
1. PC device initialization
2. Android device pairing
3. Command routing
4. File transfer
5. Notification delivery

## Performance Tests

### Benchmarks
```bash
pytest tests/performance/test_identity_perf.py -v
pytest tests/performance/test_model_router_perf.py -v
pytest tests/performance/test_message_perf.py -v
```

Metrics:
- Identity initialization time
- Model selection latency
- Message signing/verification time
- Device discovery time

## Security Tests

### Message Security
```bash
pytest tests/security/test_signatures.py -v
pytest tests/security/test_replay_attack.py -v
pytest tests/security/test_pairing_protocol.py -v
```

Tests:
1. Valid message signature verification
2. Invalid signature rejection
3. Replay attack prevention
4. Timestamp validation
5. Pairing token generation
6. Shared key security

### Permission Security
```bash
pytest tests/security/test_permission_system.py -v
```

Tests:
1. L1 permissions auto-grant
2. L2 permissions require confirmation
3. L3 permissions denied by default
4. Dangerous commands blocked
5. Protected paths rejected

## Running All Tests

```bash
# Run all tests
pytest tests/ -v --cov=src/openjarvis --cov-report=html

# Run with markers
pytest tests/ -m "unit" -v
pytest tests/ -m "integration" -v
pytest tests/ -m "performance" -v
pytest tests/ -m "security" -v

# Run specific test class
pytest tests/identity/test_manager.py::TestIdentityManager -v

# Run specific test method
pytest tests/identity/test_manager.py::TestIdentityManager::test_initialization -v
```

## Test Configuration

**pytest.ini:**
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    unit: Unit tests
    integration: Integration tests
    performance: Performance benchmarks
    security: Security tests
addopts = -v --tb=short --strict-markers
```

## Coverage Requirements

- **Minimum overall:** 80%
- **Critical modules:** 95%
  - Identity manager
  - Device manager
  - Permission system
  - Network protocol

## Continuous Integration

All tests run on:
- Python 3.9+
- Linux (Ubuntu latest)
- macOS (latest)
- Windows (latest)

With coverage reports automatically uploaded to codecov.io
