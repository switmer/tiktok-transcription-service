# 🧪 Test Suite for TikTok/YouTube Transcription Service

## Overview

This comprehensive test suite ensures bulletproof reliability for our enterprise-grade transcription system. The tests cover everything from E2E SMS flows to atomic credit transactions and lightning-fast FTS performance.

## Test Categories

### 🔄 **End-to-End Tests** (`test_e2e_sms_flow.py`)
- Complete SMS user journey from inbound message to completion
- Credit deduction and atomic transactions
- FK integrity throughout the entire flow
- Error handling and edge cases
- Concurrent transaction safety

### ⚡ **Unit Tests** (`test_atomic_credits.py`)
- Atomic credit transaction system
- Insufficient credit prevention
- Race condition handling
- Transaction type validation
- Zero-balance edge cases

### 🔍 **FTS Integration Tests** (`test_fts_search.py`)
- Full-text search functionality
- Weighted relevance ranking
- JSONB TLDR search support
- Viral content discovery
- Auto-updating search vectors
- Performance monitoring

### 🔐 **Data Integrity Tests** (`test_data_integrity.py`)
- FK constraint enforcement
- CASCADE/SET NULL/RESTRICT policies
- Orphan prevention and cleanup
- Bulk operation integrity
- Phone number normalization

### 🌐 **API Integration Tests** (`test_api_endpoints.py`)
- Public discovery endpoints
- Search API functionality
- Error handling and validation
- Response format compliance
- CORS and pagination

## Quick Start

### Install Test Dependencies
```bash
pip install -r requirements-test.txt
```

### Run All Tests
```bash
python run_tests.py
```

### Run Specific Test Categories
```bash
# Unit tests only
python run_tests.py --unit

# Integration tests only  
python run_tests.py --integration

# E2E tests only
python run_tests.py --e2e

# FTS tests only
python run_tests.py --fts

# Credit system tests only
python run_tests.py --credits

# SMS flow tests only
python run_tests.py --sms
```

### Run with Coverage
```bash
python run_tests.py --coverage
```

### Run Tests in Parallel
```bash
python run_tests.py --parallel
```

### Debug Mode
```bash
python run_tests.py --debug --pdb
```

## Test Configuration

### Environment Setup
Tests automatically configure the environment:
- `TESTING=true`
- `LOG_LEVEL=INFO`
- Loads `.env` file if present
- Mocks external API keys if not set

### Database Requirements
- Tests require access to Supabase database
- Database should have all migrations applied
- Tests use `clean_test_data` fixture for isolation
- Specific test phone number: `+15559876543`

### Test Markers
Use pytest markers to categorize tests:
```python
@pytest.mark.unit
@pytest.mark.integration  
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.database
@pytest.mark.fts
@pytest.mark.credits
@pytest.mark.sms
```

## Test Data Management

### Fixtures
- `clean_test_data`: Cleans up test data before/after tests
- `database_health_check`: Verifies database connectivity
- `test_data_builder`: Creates test data with sensible defaults
- `mock_supabase`: Mock Supabase client for unit tests
- `mock_twilio_client`: Mock Twilio for SMS testing

### Test Data Builder
```python
# Create test SMS user
user = test_data_builder.sms_user(phone="+15551234567", credits=5)

# Create test transcription
transcription = test_data_builder.transcription(
    user_phone="+15551234567",
    status="completed"
)

# Create test message
message = test_data_builder.user_message(
    from_phone="+15551234567",
    message_body="https://tiktok.com/@test/video/123"
)
```

## Critical Test Scenarios

### 💳 **Credit System Safety**
- ✅ Atomic transactions prevent double-charging
- ✅ Insufficient credit handling 
- ✅ Race condition prevention
- ✅ Purchase integration
- ✅ Zero-balance edge cases

### 📱 **SMS Flow Integrity**
- ✅ Complete E2E user journey
- ✅ Message deduplication (webhook retries)
- ✅ Phone number normalization
- ✅ Command parsing and routing
- ✅ Follow-up SMS delivery

### 🔍 **Search Performance**
- ✅ Lightning-fast GIN index performance
- ✅ Weighted relevance ranking
- ✅ JSONB array/object support
- ✅ Auto-updating search vectors
- ✅ Viral content discovery

### 🔐 **Data Integrity**
- ✅ FK constraint enforcement
- ✅ CASCADE delete policies
- ✅ SET NULL preservation policies  
- ✅ RESTRICT financial protection
- ✅ Orphan prevention

## Performance Testing

### Benchmarks
```bash
python run_tests.py --benchmark
```

### Load Testing
For load testing, use the parallel execution:
```bash
python run_tests.py --parallel --fast
```

## Continuous Integration

### GitHub Actions Integration
Add to `.github/workflows/test.yml`:
```yaml
- name: Run Test Suite
  run: |
    pip install -r requirements-test.txt
    python run_tests.py --coverage --parallel
```

### Test Reports
- **Coverage**: `htmlcov/index.html`
- **HTML Report**: `reports/report.html`
- **XML Coverage**: `coverage.xml`

## Debugging Failed Tests

### Common Issues

1. **Database Connection**
   ```bash
   # Check Supabase connection
   python -c "from database import supabase; print('OK' if supabase else 'FAILED')"
   ```

2. **Missing Migrations**
   ```bash
   # Apply latest migrations
   supabase db push
   ```

3. **Test Data Conflicts**
   ```bash
   # Run with clean data
   python run_tests.py --verbose
   ```

### Debug Mode
```bash
# Drop into debugger on failures
python run_tests.py --pdb

# Extra verbose logging
python run_tests.py --debug --verbose
```

## Test Coverage Goals

- **Unit Tests**: 90%+ coverage
- **Integration Tests**: All critical flows
- **E2E Tests**: Complete user journeys
- **Performance Tests**: Sub-100ms search
- **Error Handling**: All edge cases

## Contributing to Tests

### Adding New Tests
1. Follow existing test patterns
2. Use appropriate markers (`@pytest.mark.unit`)
3. Include docstrings explaining what's tested
4. Use `test_data_builder` for consistent test data
5. Clean up test data with `clean_test_data` fixture

### Test Naming
- `test_` prefix for all test functions
- Descriptive names: `test_atomic_credit_deduction_success`
- Group related tests in classes: `TestAtomicCreditSystem`

### Best Practices
- Test one thing per test function
- Use descriptive assertion messages
- Mock external dependencies
- Test both success and failure cases
- Include edge cases and boundary conditions

---

## 🚀 Ready to Ship with Confidence!

This test suite ensures your transcription service is bulletproof and ready for viral scale. Run the tests before every deploy to catch regressions and ship with confidence! 

```bash
python run_tests.py --coverage --parallel
```

**All green? You're ready to change the world! 🌟**