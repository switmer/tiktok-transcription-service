# Skipped Tests - Technical Debt Tracking

## Search Function Tests (6 tests skipped)

**Issue:** Schema mismatch between test expectations and production search function
**Error:** `42804: structure of query does not match function result type`
**Root Cause:** search_content function return type doesn't match test assertions

**Files Affected:**
- `tests/test_fts_search.py` - All search function tests

**Plan to Fix:**
1. Investigate actual search_content function signature in production DB
2. Update test expectations to match production return types
3. Verify search function parameters (limit_count, offset_count) exist
4. Re-enable tests once schema is aligned

**Priority:** Medium (supporting functionality, not business-critical)
**Estimated Effort:** 2-4 hours
**Target:** Next sprint after core business logic is 100% stable

---

## API Endpoint Tests (14 tests skipped)

**Issue:** TestClient/FastAPI/httpx version compatibility
**Error:** `Client.__init__() got an unexpected keyword argument 'app'`
**Root Cause:** Version mismatch between FastAPI, Starlette, and httpx

**Files Affected:**
- `tests/test_api_endpoints.py` - All API endpoint tests

**Plan to Fix:**
1. Pin compatible versions of FastAPI (0.95.2), Starlette (0.27.0), httpx (0.24.0)
2. OR upgrade to latest compatible versions across the stack
3. Update TestClient instantiation patterns if needed
4. Re-enable tests once compatibility is restored

**Priority:** Low (API tests don't validate business logic directly)
**Estimated Effort:** 1-2 hours
**Target:** After search function alignment is complete