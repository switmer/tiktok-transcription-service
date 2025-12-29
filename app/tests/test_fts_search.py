"""
Integration Tests for Full-Text Search System
Tests the enterprise FTS implementation for lightning-fast content discovery.

Key Features Tested:
1. GIN index search performance
2. Weighted relevance ranking
3. JSONB TLDR search support
4. Viral content discovery
5. Auto-updating search vectors
6. Search health monitoring
"""
import pytest
import uuid
import json
from datetime import datetime

from database import supabase
from .conftest import TEST_USER_PHONE, TestDataBuilder

class TestFullTextSearch:
    """Integration tests for the FTS system"""
    
    @pytest.mark.asyncio
    async def test_basic_search_functionality(
        self, 
        clean_test_data,
        database_health_check,
        test_data_builder
    ):
        """Test basic search across transcript/quote/tldr"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create test transcriptions with searchable content
        test_transcriptions = [
            test_data_builder.transcription(
                title="Motivation and Success Tips",
                transcript="This video talks about motivation, success mindset, and achieving your goals through hard work.",
                quote="Success is not final, failure is not fatal, it's the courage to continue that counts.",
                tldr=["Stay motivated daily", "Success requires consistency", "Never give up on dreams"]
            ),
            test_data_builder.transcription(
                title="Cooking Pasta Tutorial",
                transcript="Learn how to cook perfect pasta every time with these simple techniques.",
                quote="The secret to great pasta is proper timing and quality ingredients.",
                tldr=["Use plenty of salted water", "Don't overcook the pasta", "Save pasta water for sauce"]
            ),
            test_data_builder.transcription(
                title="Entrepreneurship Advice",
                transcript="Starting a business requires courage, planning, and perseverance through challenges.",
                quote="Every successful entrepreneur started with a single courageous step.",
                tldr=["Validate your idea first", "Start small and iterate", "Focus on customer needs"]
            )
        ]
        
        # Insert test data
        for transcription in test_transcriptions:
            response = supabase.table('transcriptions').insert(transcription).execute()
            assert response.data, "Failed to insert test transcription"
        
        # Test search for "motivation success"
        search_result = supabase.rpc('search_content', {
            'search_query': 'motivation success',
            'limit_count': 10,
            'offset_count': 0
        }).execute()
        
        assert search_result.data, "Search should return results"
        results = search_result.data
        
        # Should find the motivation video
        motivation_results = [r for r in results if 'motivation' in r['title'].lower()]
        assert len(motivation_results) > 0, "Should find motivation-related content"
        
        # Results should have search_rank > 0
        for result in results:
            assert result['search_rank'] > 0, "All results should have positive search rank"
        
        # Results should be ordered by search_rank (descending)
        ranks = [r['search_rank'] for r in results]
        assert ranks == sorted(ranks, reverse=True), "Results should be ordered by relevance"
    
    @pytest.mark.asyncio
    async def test_viral_content_search(
        self, 
        clean_test_data,
        database_health_check,
        test_data_builder
    ):
        """Test viral content discovery with engagement filtering"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create transcriptions with varying engagement levels
        high_engagement = test_data_builder.transcription(
            title="Viral Success Story",
            quote="This quote went viral because it's so inspiring and motivational.",
            like_count=5000,
            view_count=100000
        )
        
        low_engagement = test_data_builder.transcription(
            title="Another Success Story",
            quote="This is also about success but didn't get as many likes.",
            like_count=5,
            view_count=100
        )
        
        # Insert test data
        supabase.table('transcriptions').insert(high_engagement).execute()
        supabase.table('transcriptions').insert(low_engagement).execute()
        
        # Search for viral content with minimum likes
        viral_result = supabase.rpc('search_viral_quotes', {
            'search_query': 'success',
            'min_likes': 100,
            'limit_count': 10
        }).execute()
        
        assert viral_result.data, "Viral search should return results"
        viral_results = viral_result.data
        
        # Should only return high-engagement content
        for result in viral_results:
            assert result['like_count'] >= 100, "All viral results should meet minimum like threshold"
        
        # High engagement video should be in results
        high_engagement_found = any(r['task_id'] == high_engagement['task_id'] for r in viral_results)
        assert high_engagement_found, "High engagement content should be found"
        
        # Low engagement video should NOT be in results (below threshold)
        low_engagement_found = any(r['task_id'] == low_engagement['task_id'] for r in viral_results)
        assert not low_engagement_found, "Low engagement content should be filtered out"
    
    @pytest.mark.asyncio
    async def test_jsonb_tldr_search(
        self, 
        clean_test_data,
        database_health_check,
        test_data_builder
    ):
        """Test search within JSONB TLDR arrays"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create transcription with specific TLDR content
        transcription_with_tldr = test_data_builder.transcription(
            title="Productivity Hacks",
            transcript="General productivity content here.",
            quote="Standard productivity quote.",
            tldr=[
                "Use the Pomodoro Technique for focus",
                "Eliminate distractions from your workspace", 
                "Time blocking is essential for deep work"
            ]
        )
        
        supabase.table('transcriptions').insert(transcription_with_tldr).execute()
        
        # Search for content within TLDR
        tldr_search = supabase.rpc('search_content', {
            'search_query': 'Pomodoro Technique',
            'limit_count': 10,
            'offset_count': 0
        }).execute()
        
        assert tldr_search.data, "TLDR search should return results"
        
        # Should find the transcription based on TLDR content
        found_transcription = next(
            (r for r in tldr_search.data if r['task_id'] == transcription_with_tldr['task_id']), 
            None
        )
        assert found_transcription, "Should find transcription based on TLDR content"
        assert found_transcription['search_rank'] > 0, "TLDR match should have positive rank"
    
    @pytest.mark.asyncio
    async def test_weighted_search_ranking(
        self, 
        clean_test_data,
        database_health_check,
        test_data_builder
    ):
        """Test that title/quote matches rank higher than transcript matches"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create transcriptions where search term appears in different fields
        title_match = test_data_builder.transcription(
            title="Entrepreneurship Guide",  # Search term in title (highest weight)
            transcript="This video covers various business topics and strategies.",
            quote="Building a business requires dedication and planning."
        )
        
        quote_match = test_data_builder.transcription(
            title="Business Strategy Video",
            transcript="This video covers various business topics and strategies.",
            quote="Every entrepreneur needs to understand market dynamics."  # Search term in quote (highest weight)
        )
        
        transcript_match = test_data_builder.transcription(
            title="Business Strategy Video",
            transcript="This video talks about entrepreneurship and starting new ventures.",  # Search term in transcript (medium weight)
            quote="Building a business requires dedication and planning."
        )
        
        # Insert test data
        supabase.table('transcriptions').insert(title_match).execute()
        supabase.table('transcriptions').insert(quote_match).execute()
        supabase.table('transcriptions').insert(transcript_match).execute()
        
        # Search for "entrepreneurship"
        weighted_search = supabase.rpc('search_content', {
            'search_query': 'entrepreneurship',
            'limit_count': 10,
            'offset_count': 0
        }).execute()
        
        assert weighted_search.data, "Weighted search should return results"
        results = weighted_search.data
        
        # Find each result
        title_result = next((r for r in results if r['task_id'] == title_match['task_id']), None)
        quote_result = next((r for r in results if r['task_id'] == quote_match['task_id']), None)
        transcript_result = next((r for r in results if r['task_id'] == transcript_match['task_id']), None)
        
        assert title_result, "Title match should be found"
        assert quote_result, "Quote match should be found"
        assert transcript_result, "Transcript match should be found"
        
        # Title and quote matches should rank higher than transcript match
        assert title_result['search_rank'] >= transcript_result['search_rank'], "Title match should rank higher than transcript"
        assert quote_result['search_rank'] >= transcript_result['search_rank'], "Quote match should rank higher than transcript"
    
    @pytest.mark.asyncio
    async def test_auto_updating_search_vectors(
        self, 
        clean_test_data,
        database_health_check,
        test_data_builder
    ):
        """Test that FTS vectors are automatically updated when content changes"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create initial transcription
        original_transcription = test_data_builder.transcription(
            title="Original Title",
            transcript="Original transcript content.",
            quote="Original quote content."
        )
        
        response = supabase.table('transcriptions').insert(original_transcription).execute()
        task_id = response.data[0]['task_id']
        
        # Search for original content
        original_search = supabase.rpc('search_content', {
            'search_query': 'original',
            'limit_count': 10,
            'offset_count': 0
        }).execute()
        
        original_found = any(r['task_id'] == task_id for r in original_search.data)
        assert original_found, "Should find original content"
        
        # Update the transcription content
        supabase.table('transcriptions').update({
            'title': 'Updated Title with Innovation',
            'transcript': 'Updated transcript with innovation content.',
            'quote': 'Updated quote about innovation and creativity.'
        }).eq('task_id', task_id).execute()
        
        # Search for new content (should find due to auto-updated FTS vectors)
        updated_search = supabase.rpc('search_content', {
            'search_query': 'innovation',
            'limit_count': 10,
            'offset_count': 0
        }).execute()
        
        innovation_found = any(r['task_id'] == task_id for r in updated_search.data)
        assert innovation_found, "Should find updated content with new search terms"
        
        # Search for original content (should no longer find it)
        old_search = supabase.rpc('search_content', {
            'search_query': 'original',
            'limit_count': 10,
            'offset_count': 0
        }).execute()
        
        old_found = any(r['task_id'] == task_id for r in old_search.data)
        assert not old_found, "Should not find old content after update"
    
    @pytest.mark.asyncio
    async def test_search_health_monitoring(
        self, 
        clean_test_data,
        database_health_check,
        test_data_builder
    ):
        """Test FTS health check and monitoring functions"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create some test transcriptions
        for i in range(3):
            test_transcription = test_data_builder.transcription(
                title=f"Test Video {i}",
                transcript=f"Test transcript content for video {i}."
            )
            supabase.table('transcriptions').insert(test_transcription).execute()
        
        # Run FTS health check
        health_check = supabase.rpc('fts_health_check').execute()
        
        assert health_check.data, "Health check should return data"
        health_metrics = {metric['metric']: metric for metric in health_check.data}
        
        # Verify expected metrics are present
        expected_metrics = [
            'total_transcriptions',
            'fts_indexed_records', 
            'fts_coverage_percent',
            'fts_index_size',
            'search_ready'
        ]
        
        for metric in expected_metrics:
            assert metric in health_metrics, f"Health check should include {metric}"
        
        # Verify metrics make sense
        total_transcriptions = int(health_metrics['total_transcriptions']['value'])
        fts_indexed = int(health_metrics['fts_indexed_records']['value'])
        
        assert total_transcriptions >= 3, "Should have at least 3 test transcriptions"
        assert fts_indexed >= 3, "Should have at least 3 FTS indexed records"
        
        # Coverage should be 100% or close for fresh data
        coverage_percent = float(health_metrics['fts_coverage_percent']['value'].replace('%', ''))
        assert coverage_percent >= 95, "FTS coverage should be high for fresh data"
        
        # Search should be ready
        search_ready = health_metrics['search_ready']['value']
        assert search_ready == 'YES', "Search system should be ready"
    
    @pytest.mark.asyncio
    async def test_search_pagination(
        self, 
        clean_test_data,
        database_health_check,
        test_data_builder
    ):
        """Test search pagination with limit and offset"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create multiple transcriptions with same search term
        for i in range(10):
            test_transcription = test_data_builder.transcription(
                title=f"Business Strategy Video {i}",
                transcript=f"This business video {i} covers important strategies.",
                quote=f"Business insight number {i} for entrepreneurs."
            )
            supabase.table('transcriptions').insert(test_transcription).execute()
        
        # Test first page
        page1 = supabase.rpc('search_content', {
            'search_query': 'business',
            'limit_count': 3,
            'offset_count': 0
        }).execute()
        
        # Test second page
        page2 = supabase.rpc('search_content', {
            'search_query': 'business',
            'limit_count': 3,
            'offset_count': 3
        }).execute()
        
        assert len(page1.data) <= 3, "First page should have at most 3 results"
        assert len(page2.data) <= 3, "Second page should have at most 3 results"
        
        # Pages should have different results
        page1_ids = {r['task_id'] for r in page1.data}
        page2_ids = {r['task_id'] for r in page2.data}
        
        assert page1_ids.isdisjoint(page2_ids), "Different pages should have different results"
    
    @pytest.mark.asyncio
    async def test_empty_search_handling(
        self, 
        clean_test_data,
        database_health_check
    ):
        """Test handling of empty search queries and no results"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Test search for non-existent content
        no_results = supabase.rpc('search_content', {
            'search_query': 'xyznonexistentterm123',
            'limit_count': 10,
            'offset_count': 0
        }).execute()
        
        # Should return empty results, not error
        assert no_results.data == [], "Should return empty array for no matches"
        
        # Test viral search with no results
        no_viral = supabase.rpc('search_viral_quotes', {
            'search_query': 'xyznonexistentterm123',
            'min_likes': 1,
            'limit_count': 10
        }).execute()
        
        assert no_viral.data == [], "Should return empty array for no viral matches"