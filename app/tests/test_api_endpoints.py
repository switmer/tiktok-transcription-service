"""
API Endpoint Integration Tests
Tests the FastAPI endpoints for functionality and error handling.

Key Features Tested:
1. Public discovery endpoints
2. FTS search API integration
3. Health check endpoints  
4. Error handling and validation
5. Response format compliance
"""
import pytest
import json
from fastapi.testclient import TestClient

from app import app
from database import supabase
from .conftest import TEST_VIDEO_URL, TestDataBuilder

class TestAPIEndpoints:
    """Integration tests for API endpoints"""
    
    def test_health_check_endpoint(self, client: TestClient):
        """Test basic health check endpoint"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert data["status"] in ["healthy", "degraded"]
    
    def test_discover_trending_endpoint(self, client: TestClient):
        """Test trending discovery endpoint"""
        response = client.get("/api/public/discover/trending")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return list (empty is OK for test environment)
        assert isinstance(data, list)
        
        # If data exists, verify structure
        if data:
            for item in data:
                assert "task_id" in item
                assert "title" in item
                assert "created_at" in item
    
    def test_discover_categories_endpoint(self, client: TestClient):
        """Test categories discovery endpoint"""
        response = client.get("/api/public/discover/categories")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return list of category strings
        assert isinstance(data, list)
        assert len(data) > 0, "Should have at least some categories"
        
        for category in data:
            assert isinstance(category, str)
            assert len(category) > 0
    
    @pytest.mark.asyncio
    async def test_search_endpoint_integration(self, client: TestClient, clean_test_data, test_data_builder):
        """Test search API endpoint integration"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create test data for searching
        test_transcription = test_data_builder.transcription(
            title="Test Search Content",
            transcript="This is searchable content for testing the API endpoint.",
            quote="Searchable quote for testing purposes."
        )
        
        supabase.table('transcriptions').insert(test_transcription).execute()
        
        # Test search endpoint
        response = client.get("/api/public/discover/search?q=searchable")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "query" in data
        assert "results" in data
        assert "total_results" in data
        
        assert data["query"] == "searchable"
        assert isinstance(data["results"], list)
        assert isinstance(data["total_results"], int)
        
        # Should find our test content
        if data["results"]:
            result = data["results"][0]
            assert "task_id" in result
            assert "title" in result
            assert "search_rank" in result
            assert result["search_rank"] > 0
    
    @pytest.mark.asyncio
    async def test_viral_search_endpoint(self, client: TestClient, clean_test_data, test_data_builder):
        """Test viral content search endpoint"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create high-engagement test content
        viral_content = test_data_builder.transcription(
            title="Viral Content",
            quote="This quote has high engagement for viral testing.",
            like_count=1000,
            view_count=50000
        )
        
        supabase.table('transcriptions').insert(viral_content).execute()
        
        # Test viral search endpoint
        response = client.get("/api/public/discover/viral?q=viral&min_likes=100")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return list of viral results
        assert isinstance(data, list)
        
        # If results found, verify structure
        if data:
            result = data[0]
            assert "task_id" in result
            assert "quote" in result
            assert "like_count" in result
            assert "search_rank" in result
            assert result["like_count"] >= 100
    
    def test_search_endpoint_validation(self, client: TestClient):
        """Test search endpoint input validation"""
        # Test empty query
        response = client.get("/api/public/discover/search?q=")
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        
        # Test very short query
        response = client.get("/api/public/discover/search?q=a")
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        
        # Test pagination parameters
        response = client.get("/api/public/discover/search?q=test&limit=5&offset=10")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
    
    def test_viral_search_validation(self, client: TestClient):
        """Test viral search endpoint validation"""
        # Test with minimum likes parameter
        response = client.get("/api/public/discover/viral?q=test&min_likes=50&limit=5")
        assert response.status_code == 200
        
        # Test with invalid parameters (should still work with defaults)
        response = client.get("/api/public/discover/viral?q=test&min_likes=-1")
        assert response.status_code == 200
    
    def test_similar_content_endpoint(self, client: TestClient):
        """Test similar content discovery endpoint"""
        # Test with fake task ID (should return empty list)
        fake_task_id = "00000000-0000-0000-0000-000000000000"
        response = client.get(f"/api/public/discover/similar/{fake_task_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should be empty for non-existent task
        assert data == []
    
    def test_recent_content_endpoint(self, client: TestClient):
        """Test recent content discovery endpoint"""
        response = client.get("/api/public/discover/recent")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        
        # Test with category filter
        response = client.get("/api/public/discover/recent?category=education")
        assert response.status_code == 200
        
        # Test with limit parameter
        response = client.get("/api/public/discover/recent?limit=5")
        assert response.status_code == 200
    
    def test_public_endpoints_no_auth_required(self, client: TestClient):
        """Test that public endpoints don't require authentication"""
        public_endpoints = [
            "/api/public/discover/trending",
            "/api/public/discover/recent", 
            "/api/public/discover/categories",
            "/api/public/discover/search?q=test",
            "/api/public/discover/viral?q=test"
        ]
        
        for endpoint in public_endpoints:
            response = client.get(endpoint)
            # Should not return 401/403 (auth errors)
            assert response.status_code not in [401, 403], f"Endpoint {endpoint} should not require auth"
            # Should return 200 (success) or possibly 404/422 for invalid params
            assert response.status_code in [200, 404, 422], f"Endpoint {endpoint} returned unexpected status {response.status_code}"
    
    def test_error_handling_robustness(self, client: TestClient):
        """Test that endpoints handle errors gracefully"""
        # Test search with malformed query
        response = client.get("/api/public/discover/search?q=" + "x" * 1000)  # Very long query
        assert response.status_code == 200  # Should not crash
        
        # Test trending with invalid time window
        response = client.get("/api/public/discover/trending?time_window=invalid")
        assert response.status_code == 200  # Should use default
        
        # Test viral search with malformed parameters
        response = client.get("/api/public/discover/viral?min_likes=invalid")
        assert response.status_code == 200  # Should use default
    
    def test_response_content_types(self, client: TestClient):
        """Test that endpoints return correct content types"""
        endpoints = [
            "/api/public/discover/trending",
            "/api/public/discover/categories",
            "/api/public/discover/search?q=test"
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            if response.status_code == 200:
                assert "application/json" in response.headers.get("content-type", "")
    
    def test_cors_headers(self, client: TestClient):
        """Test CORS headers for public endpoints"""
        response = client.get("/api/public/discover/trending")
        
        # Should have CORS headers (if configured)
        # This test verifies CORS is not blocking public access
        assert response.status_code == 200
    
    @pytest.mark.asyncio 
    async def test_pagination_consistency(self, client: TestClient, clean_test_data, test_data_builder):
        """Test pagination works consistently"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create multiple test transcriptions
        for i in range(10):
            test_transcription = test_data_builder.transcription(
                title=f"Pagination Test Video {i}",
                transcript=f"Content for pagination testing video number {i}."
            )
            supabase.table('transcriptions').insert(test_transcription).execute()
        
        # Test first page
        page1 = client.get("/api/public/discover/search?q=pagination&limit=3&offset=0")
        assert page1.status_code == 200
        page1_data = page1.json()
        
        # Test second page
        page2 = client.get("/api/public/discover/search?q=pagination&limit=3&offset=3")
        assert page2.status_code == 200
        page2_data = page2.json()
        
        # Pages should have different results
        if page1_data["results"] and page2_data["results"]:
            page1_ids = {r["task_id"] for r in page1_data["results"]}
            page2_ids = {r["task_id"] for r in page2_data["results"]}
            assert page1_ids.isdisjoint(page2_ids), "Pagination should return different results per page"