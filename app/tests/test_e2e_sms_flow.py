"""
End-to-End SMS Flow Tests
Tests the complete SMS user journey from inbound message to transcription completion.

Critical Flows Tested:
1. SMS Inbound → Credit Check → Transcription → Follow-up SMS
2. Credit deduction and atomic transactions
3. FK integrity throughout the flow
4. Error handling and edge cases
"""
import pytest
import asyncio
import uuid
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta

from database import supabase
from .conftest import (
    TEST_USER_PHONE, TEST_PHONE_NUMBER, TEST_VIDEO_URL, 
    TestDataBuilder, cleanup_test_phone_numbers
)

class TestE2ESMSFlow:
    """End-to-end SMS flow testing"""
    
    @pytest.mark.asyncio
    async def test_complete_sms_transcription_flow(
        self, 
        clean_test_data, 
        database_health_check,
        mock_twilio_client,
        mock_openai_client,
        test_data_builder
    ):
        """
        Test the complete SMS flow:
        1. User sends video URL via SMS
        2. System creates SMS user (if needed)
        3. Credits are checked and decremented
        4. Transcription is created and processed
        5. User receives completion SMS
        6. All FK relationships are maintained
        """
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Step 1: Create test SMS user with credits
        test_user = test_data_builder.sms_user(
            phone=TEST_USER_PHONE,
            credits=3,
            free_credits_used=2
        )
        
        user_response = supabase.table('sms_users').upsert(test_user, on_conflict='phone_number').execute()
        assert user_response.data, "Failed to create test SMS user"
        created_user = user_response.data[0]
        
        # Step 2: Simulate inbound SMS message
        test_message = test_data_builder.user_message(
            from_phone=TEST_USER_PHONE,
            message_body=TEST_VIDEO_URL
        )
        
        message_response = supabase.table('user_messages').upsert(test_message, on_conflict='id').execute()
        assert message_response.data, "Failed to log inbound SMS message"
        
        # Step 3: Create transcription task (simulating SMS processing)
        task_id = str(uuid.uuid4())
        test_transcription = test_data_builder.transcription(
            task_id=task_id,
            user_phone=TEST_USER_PHONE,
            status="pending"
        )
        
        transcription_response = supabase.table('transcriptions').upsert(test_transcription, on_conflict='task_id').execute()
        assert transcription_response.data, "Failed to create transcription task"
        
        # Step 4: Test atomic credit deduction
        credit_result = supabase.rpc('atomic_credit_transaction', {
            'user_phone_param': TEST_USER_PHONE,
            'credit_change': -1,
            'transaction_type': 'transcription',
            'description': f'Video transcription for task {task_id}'
        }).execute()
        
        assert credit_result.data, "Credit transaction failed"
        assert credit_result.data[0]['success'] is True, "Credit deduction should succeed"
        assert credit_result.data[0]['new_balance'] == 2, "Credits should be decremented from 3 to 2"
        
        # Step 5: Verify user credits were updated
        user_check = supabase.table('sms_users').select('credits_remaining').eq('phone_number', TEST_USER_PHONE).single().execute()
        assert user_check.data['credits_remaining'] == 2, "User credits not properly decremented"
        
        # Step 6: Simulate transcription completion
        completed_transcription = test_data_builder.transcription(
            task_id=task_id,
            user_phone=TEST_USER_PHONE,
            status="completed",
            transcript="This is a completed test transcript.",
            quote="Most shareable quote from the video",
            tldr=["Key insight 1", "Key insight 2", "Key insight 3"]
        )
        
        # Update transcription to completed (this should trigger completion notification)
        update_response = supabase.table('transcriptions').update({
            'status': 'completed',
            'transcript': completed_transcription['transcript'],
            'quote': completed_transcription['quote'],
            'tldr': completed_transcription['tldr']
        }).eq('task_id', task_id).execute()
        
        assert update_response.data, "Failed to update transcription to completed"
        
        # Step 7: Verify completion updated user stats
        final_user_check = supabase.table('sms_users').select('*').eq('phone_number', TEST_USER_PHONE).single().execute()
        final_user = final_user_check.data
        
        # User stats should be updated by completion trigger
        assert final_user['total_videos_transcribed'] >= 1, "Video count should be incremented"
        
        # Step 8: Verify FK integrity throughout flow
        integrity_check = supabase.rpc('check_fk_integrity').execute()
        assert integrity_check.data, "FK integrity check failed"
        
        # All tables should show 100% integrity
        for table_check in integrity_check.data:
            if table_check['orphan_count'] is not None:
                assert table_check['orphan_count'] == 0, f"Orphaned records found in {table_check['table_name']}"
        
        # Step 9: Test message deduplication (simulate webhook retry)
        duplicate_message = test_data_builder.user_message(
            from_phone=TEST_USER_PHONE,
            message_body=TEST_VIDEO_URL,
            message_sid=test_message['message_sid']  # Same SID = duplicate
        )
        
        # This should be prevented by unique constraint on message_sid
        with pytest.raises(Exception):  # Should fail due to unique constraint
            supabase.table('user_messages').upsert(duplicate_message, on_conflict='id').execute()
    
    @pytest.mark.asyncio
    async def test_insufficient_credits_flow(
        self, 
        clean_test_data, 
        database_health_check,
        test_data_builder
    ):
        """Test SMS flow when user has insufficient credits"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create user with 0 credits
        test_user = test_data_builder.sms_user(
            phone=TEST_USER_PHONE,
            credits=0,
            free_credits_used=3  # Used all free credits
        )
        
        user_response = supabase.table('sms_users').upsert(test_user, on_conflict='phone_number').execute()
        assert user_response.data, "Failed to create test SMS user"
        
        # Test atomic credit transaction with insufficient credits
        credit_result = supabase.rpc('atomic_credit_transaction', {
            'user_phone_param': TEST_USER_PHONE,
            'credit_change': -1,
            'transaction_type': 'transcription',
            'description': 'Should fail - insufficient credits'
        }).execute()
        
        assert credit_result.data, "Credit transaction should return result"
        assert credit_result.data[0]['success'] is False, "Credit deduction should fail"
        assert credit_result.data[0]['new_balance'] == 0, "Balance should remain unchanged"
        
        # Verify user credits unchanged
        user_check = supabase.table('sms_users').select('credits_remaining').eq('phone_number', TEST_USER_PHONE).single().execute()
        assert user_check.data['credits_remaining'] == 0, "Credits should remain at 0"
    
    @pytest.mark.asyncio
    async def test_sms_redundancy_detection(
        self, 
        clean_test_data,
        database_health_check, 
        test_data_builder
    ):
        """Test SMS redundancy detection function"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create clean test user
        test_user = test_data_builder.sms_user(phone=TEST_USER_PHONE)
        supabase.table('sms_users').upsert(test_user, on_conflict='phone_number').execute()
        
        # Create some test data
        test_message = test_data_builder.user_message(from_phone=TEST_USER_PHONE)
        supabase.table('user_messages').upsert(test_message, on_conflict='id').execute()
        
        test_transcription = test_data_builder.transcription(user_phone=TEST_USER_PHONE)
        supabase.table('transcriptions').upsert(test_transcription, on_conflict='task_id').execute()
        
        # Run redundancy detection
        redundancy_check = supabase.rpc('detect_sms_redundancies').execute()
        assert redundancy_check.data is not None, "Redundancy check should return data"
        
        # Should find no redundancies with clean test data
        for issue in redundancy_check.data:
            if issue['count'] is not None:
                assert issue['count'] == 0, f"Found {issue['issue_type']}: {issue['count']} issues"
    
    @pytest.mark.asyncio
    async def test_phone_number_normalization(
        self, 
        clean_test_data,
        database_health_check,
        test_data_builder
    ):
        """Test phone number normalization function"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Test various phone number formats
        test_cases = [
            ("5551234567", "+15551234567"),           # 10 digits
            ("15551234567", "+15551234567"),          # 11 digits with 1
            ("+15551234567", "+15551234567"),         # Already normalized
            ("(555) 123-4567", "+15551234567"),      # Formatted
            ("555-123-4567", "+15551234567"),        # Dashed
            ("555.123.4567", "+15551234567"),        # Dotted
        ]
        
        for input_phone, expected in test_cases:
            result = supabase.rpc('normalize_phone_number', {'phone_input': input_phone}).execute()
            assert result.data == expected, f"Failed to normalize {input_phone} to {expected}, got {result.data}"
    
    @pytest.mark.asyncio
    async def test_cascade_delete_policies(
        self, 
        clean_test_data,
        database_health_check, 
        test_data_builder
    ):
        """Test FK CASCADE policies work correctly"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create test user with related data
        test_user = test_data_builder.sms_user(phone=TEST_USER_PHONE)
        user_response = supabase.table('sms_users').upsert(test_user, on_conflict='phone_number').execute()
        user_id = user_response.data[0]['id']
        
        # Create related records
        test_message = test_data_builder.user_message(from_phone=TEST_USER_PHONE)
        message_response = supabase.table('user_messages').upsert(test_message, on_conflict='id').execute()
        
        test_transcription = test_data_builder.transcription(user_phone=TEST_USER_PHONE)
        transcription_response = supabase.table('transcriptions').upsert(test_transcription, on_conflict='task_id').execute()
        
        # Verify records exist
        messages_before = supabase.table('user_messages').select('id').eq('from_phone', TEST_USER_PHONE).execute()
        transcriptions_before = supabase.table('transcriptions').select('task_id').eq('user_phone', TEST_USER_PHONE).execute()
        
        assert len(messages_before.data) > 0, "Should have user messages"
        assert len(transcriptions_before.data) > 0, "Should have transcriptions"
        
        # Delete the SMS user (should trigger CASCADE and SET NULL policies)
        supabase.table('sms_users').delete().eq('phone_number', TEST_USER_PHONE).execute()
        
        # Check CASCADE: user_messages should be deleted
        messages_after = supabase.table('user_messages').select('id').eq('from_phone', TEST_USER_PHONE).execute()
        assert len(messages_after.data) == 0, "User messages should be deleted via CASCADE"
        
        # Check SET NULL: transcriptions should have user_phone set to NULL
        transcriptions_after = supabase.table('transcriptions').select('user_phone').eq('task_id', test_transcription['task_id']).execute()
        assert transcriptions_after.data[0]['user_phone'] is None, "Transcription user_phone should be NULL via SET NULL"
    
    @pytest.mark.asyncio
    async def test_concurrent_credit_transactions(
        self, 
        clean_test_data,
        database_health_check, 
        test_data_builder
    ):
        """Test atomic credit transactions prevent race conditions"""
        if supabase is None:
            pytest.skip("Supabase client not available")
        
        # Create user with credits
        test_user = test_data_builder.sms_user(phone=TEST_USER_PHONE, credits=1)
        supabase.table('sms_users').upsert(test_user, on_conflict='phone_number').execute()
        
        # Simulate concurrent credit deductions
        async def deduct_credit(transaction_id: str):
            return supabase.rpc('atomic_credit_transaction', {
                'user_phone_param': TEST_USER_PHONE,
                'credit_change': -1,
                'transaction_type': 'transcription',
                'description': f'Concurrent test {transaction_id}'
            }).execute()
        
        # Run two concurrent transactions (both trying to deduct the last credit)
        results = await asyncio.gather(
            asyncio.to_thread(deduct_credit, "txn1"),
            asyncio.to_thread(deduct_credit, "txn2"),
            return_exceptions=True
        )
        
        # Only one should succeed due to atomic locking
        successes = [r for r in results if not isinstance(r, Exception) and r.data[0]['success']]
        failures = [r for r in results if not isinstance(r, Exception) and not r.data[0]['success']]
        
        assert len(successes) == 1, "Exactly one transaction should succeed"
        assert len(failures) == 1, "Exactly one transaction should fail"
        
        # Final balance should be 0
        final_user = supabase.table('sms_users').select('credits_remaining').eq('phone_number', TEST_USER_PHONE).single().execute()
        assert final_user.data['credits_remaining'] == 0, "Final balance should be 0"