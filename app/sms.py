import os
import re
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

# Conditional Twilio import with fallback
try:
    from twilio.rest import Client
    from twilio.twiml.messaging_response import MessagingResponse
    TWILIO_AVAILABLE = True
except ImportError:
    # Mock classes for when Twilio is not available
    class Client:
        def __init__(self, *args, **kwargs):
            pass
        @property
        def messages(self):
            return type('MockMessages', (), {
                'create': lambda **kwargs: type('MockMessage', (), {'sid': 'mock_sid'})()
            })()
    
    class MessagingResponse:
        def __init__(self):
            self._message = None
        def message(self, text):
            self._message = text
        def __str__(self):
            return f'<Response><Message>{self._message}</Message></Response>'
    
    TWILIO_AVAILABLE = False
    print("Warning: Twilio not available, using mock classes")

from fastapi import HTTPException
import asyncio

# Import your existing modules
try:
    from .database import supabase
except ImportError:
    import database
    from database import supabase

logger = logging.getLogger(__name__)

# Initialize Twilio client
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "MG1057ede7c24d65c977a1ccec2a62c2f8")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+17744727423")

twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_AVAILABLE:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        logger.info("Twilio client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Twilio client: {str(e)}")
else:
    logger.warning("Twilio credentials not found or Twilio not available. SMS functionality will be disabled.")

class SMSHandler:
    """Handles SMS operations for ScribeTok"""
    
    @staticmethod
    def is_video_url(text: str) -> bool:
        """Check if text contains a TikTok or YouTube URL"""
        video_patterns = [
            r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+',
            r'https?://(?:vm\.)?tiktok\.com/\w+',
            r'https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+',
            r'https?://youtu\.be/[\w-]+',
            r'https?://(?:www\.)?youtube\.com/shorts/[\w-]+',
        ]
        
        for pattern in video_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    
    @staticmethod
    def extract_video_url(text: str) -> Optional[str]:
        """Extract the first video URL from text"""
        video_patterns = [
            r'(https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+)',
            r'(https?://(?:vm\.)?tiktok\.com/\w+)',
            r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+)',
            r'(https?://youtu\.be/[\w-]+)',
            r'(https?://(?:www\.)?youtube\.com/shorts/[\w-]+)',
        ]
        
        for pattern in video_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    
    @staticmethod
    async def get_user_transcripts(phone_number: str, limit: int = 5) -> list:
        """Get recent transcripts for a user"""
        if not supabase:
            return []
        
        try:
            # Query transcript_jobs with linked transcriptions
            response = await asyncio.to_thread(
                supabase.table('transcript_jobs')
                        .select("id, video_url, status, created_at, transcriptions!transcript_jobs_transcript_id_fkey(title, transcript)")
                        .eq('from_phone', phone_number)
                        .eq('status', 'completed')
                        .order('created_at', desc=True)
                        .limit(limit)
                        .execute
            )
            
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching user transcripts: {str(e)}")
            return []
    
    @staticmethod
    async def send_sms(to: str, body: str, status_callback: Optional[str] = None) -> bool:
        """Send an SMS message"""
        if not twilio_client:
            logger.error("Cannot send SMS: Twilio client not initialized")
            return False
        
        try:
            message_data = {
                'to': to,
                'body': body,
                'messaging_service_sid': TWILIO_MESSAGING_SERVICE_SID
            }
            
            if status_callback:
                message_data['status_callback'] = status_callback
            
            message = twilio_client.messages.create(**message_data)
            
            logger.info(f"SMS sent successfully to {to}, SID: {message.sid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send SMS to {to}: {str(e)}")
            return False
    
    @staticmethod
    def create_twiml_response(message: str) -> str:
        """Create a TwiML response for webhook"""
        response = MessagingResponse()
        response.message(message)
        return str(response)
    
    @staticmethod
    async def handle_help_command(phone_number: str) -> str:
        """Handle /help command"""
        return """👋 Welcome to ScribeTok!

📱 Text a TikTok or YouTube link to get an instant transcript.

🗂️ Commands:
• /vault - View your recent transcripts
• /summary - Get a summary of your last transcript
• /upgrade - Buy more credits ($5 for 10 credits)
• /referral - Share with friends (both get 5 bonus credits!)
• /help - Show this message

Just paste any video link and we'll transcribe it for you! 🎥✨"""
    
    @staticmethod
    async def handle_upgrade_command(phone_number: str) -> str:
        """Handle /upgrade command for purchasing credits"""
        try:
            # Check current credit balance
            result = supabase.table("sms_users").select("credits_remaining, free_credits_used").eq("phone_number", phone_number).execute()
            
            current_credits = 0
            free_used = 0
            if result.data:
                current_credits = result.data[0].get("credits_remaining", 0)
                free_used = result.data[0].get("free_credits_used", 0)
            
            # Calculate free credits remaining
            free_remaining = max(0, 5 - free_used)
            
            # Get the Stripe payment link from environment
            stripe_payment_link = os.getenv("STRIPE_PAYMENT_LINK", "https://buy.stripe.com/test_your_payment_link_here")
            
            status_text = f"💳 Current Credits: {current_credits}"
            if free_remaining > 0:
                status_text += f" ({free_remaining} free remaining)"
            
            return (
                f"{status_text}\n\n"
                f"🎯 Buy 10 SMS Credits for $5:\n"
                f"{stripe_payment_link}\n\n"
                f"✨ Credits are instantly added to your phone after purchase!\n"
                f"💬 No account required - credits never expire.\n\n"
                f"Questions? Reply HELP"
            )
            
        except Exception as e:
            logger.error(f"Error in upgrade command: {str(e)}")
            return "💳 Sorry, couldn't load upgrade info right now. Please try again later!"
    
    @staticmethod
    async def handle_referral_command(phone_number: str) -> str:
        """Handle /referral command for sharing referral links"""
        try:
            # Get user's referral code
            result = supabase.table("sms_users").select("referral_code, referrals_count, credits_remaining").eq("phone_number", phone_number).execute()
            
            if not result.data:
                # Create user if doesn't exist
                referral_code = await SMSHandler._generate_referral_code(phone_number)
                supabase.table("sms_users").insert({
                    "phone_number": phone_number,
                    "credits_remaining": 5,
                    "referral_code": referral_code
                }).execute()
                referrals_count = 0
                credits = 5
            else:
                user_data = result.data[0]
                referral_code = user_data.get("referral_code")
                referrals_count = user_data.get("referrals_count", 0)
                credits = user_data.get("credits_remaining", 0)
                
                # Generate referral code if missing
                if not referral_code:
                    referral_code = await SMSHandler._generate_referral_code(phone_number)
                    supabase.table("sms_users").update({"referral_code": referral_code}).eq("phone_number", phone_number).execute()
            
            # Create referral link
            base_url = os.getenv('BASE_URL', 'https://scribetok.com')
            referral_link = f"{base_url}/?ref={referral_code}"
            
            return (
                f"🎁 Share ScribeTok and both get 5 bonus credits!\n\n"
                f"Your link: {referral_link}\n\n"
                f"📊 You've referred {referrals_count} friends\n"
                f"💳 Current credits: {credits}\n\n"
                f"Send this link to friends - when they use ScribeTok, you both get 5 credits!"
            )
            
        except Exception as e:
            logger.error(f"Error in referral command: {str(e)}")
            return "🎁 Sorry, couldn't load referral info right now. Please try again later!"
    
    @staticmethod
    async def _generate_referral_code(phone_number: str) -> str:
        """Generate a unique referral code for a user"""
        import hashlib
        # Create a hash-based code from phone number (privacy-friendly)
        hash_input = f"{phone_number}scribetok_salt"
        code = hashlib.md5(hash_input.encode()).hexdigest()[:6].upper()
        
        # Check if code exists, add random suffix if needed
        result = supabase.table("sms_users").select("id").eq("referral_code", code).execute()
        if result.data:
            import random
            code += str(random.randint(10, 99))
        
        return code
    
    @staticmethod
    async def use_credit_and_get_message(phone_number: str, video_title: str = "Video") -> tuple:
        """
        Use a credit and return success status with appropriate message.
        Returns (success: bool, message: str, credits_remaining: int)
        """
        try:
            # Call the database function to use a credit
            result = supabase.rpc('use_credit', {'user_phone': phone_number}).execute()
            
            if not result.data:
                return False, "❌ Error processing credit usage. Please try again.", 0
            
            credit_result = result.data[0]
            success = credit_result.get('success', False)
            remaining = credit_result.get('credits_remaining', 0)
            is_free = credit_result.get('is_free_credit', False)
            
            if not success:
                # User is out of credits
                message = credit_result.get('message', 'No credits remaining')
                if 'No credits remaining' in message:
                    return False, await SMSHandler._get_out_of_credits_message(phone_number), 0
                return False, f"❌ {message}", 0
            
            # Create success message with credit countdown
            if is_free and remaining > 0:
                # Show remaining free credits in a motivating way
                if remaining == 4:
                    credit_msg = f"✅ Transcript ready for '{video_title}'!\n\n🎯 You have {remaining} of 5 free credits remaining.\n\n💡 Share with a friend and both get 5 bonus credits! Text /referral for your link."
                elif remaining == 3:
                    credit_msg = f"✅ Transcript ready for '{video_title}'!\n\n📊 You have {remaining} of 5 free credits remaining.\n\n🎁 Want more? Text /referral to share with friends!"
                elif remaining == 2:
                    credit_msg = f"✅ Transcript ready for '{video_title}'!\n\n⚠️ You have {remaining} of 5 free credits remaining.\n\n💰 Almost out! Text /upgrade to buy more or /referral to earn bonus credits."
                elif remaining == 1:
                    credit_msg = f"✅ Transcript ready for '{video_title}'!\n\n🚨 LAST FREE CREDIT! Only {remaining} remaining.\n\n💳 Text /upgrade to buy more or /referral to get 5 bonus credits with a friend!"
                else:
                    credit_msg = f"✅ Transcript ready for '{video_title}'!\n\n🎉 You have {remaining} free credits remaining!"
            elif is_free and remaining == 0:
                # Just used the last free credit
                credit_msg = f"✅ Transcript ready for '{video_title}'!\n\n🎊 That was your last free credit!\n\n💰 Buy 10 more for $5: Text /upgrade\n🎁 Or invite a friend for 5 bonus credits: Text /referral"
            else:
                # Used a purchased credit
                credit_msg = f"✅ Transcript ready for '{video_title}'!\n\n💳 {remaining} credits remaining."
            
            return True, credit_msg, remaining
            
        except Exception as e:
            logger.error(f"Error using credit for {phone_number}: {str(e)}")
            return False, "❌ Error processing your request. Please try again.", 0
    
    @staticmethod
    async def _get_out_of_credits_message(phone_number: str) -> str:
        """Get message when user is out of credits"""
        try:
            # Check if user has made any referrals
            result = supabase.table("sms_users").select("referrals_count").eq("phone_number", phone_number).execute()
            
            referrals_count = 0
            if result.data:
                referrals_count = result.data[0].get("referrals_count", 0)
            
            if referrals_count == 0:
                # First time out of credits - emphasize referrals
                return (
                    "💸 You're out of credits!\n\n"
                    "🎁 FREE OPTION: Invite a friend and both get 5 credits!\n"
                    "Text /referral for your sharing link.\n\n"
                    "💰 OR buy 10 credits for $5: Text /upgrade"
                )
            else:
                # Has referred before - emphasize purchase
                return (
                    "💸 You're out of credits!\n\n"
                    "💰 Buy 10 more credits for $5: Text /upgrade\n\n"
                    "🎁 Or invite another friend for 5 bonus credits: Text /referral"
                )
        except:
            return "💸 You're out of credits! Text /upgrade to buy more or /referral to earn bonus credits."
    
    @staticmethod
    async def process_new_user_referral(phone_number: str, referral_code: str = None) -> tuple:
        """
        Process referral for a new user. Returns (success, message)
        """
        if not referral_code:
            return False, ""
        
        try:
            # Call the database function to process referral
            result = supabase.rpc('process_referral', {
                'referrer_code': referral_code,
                'new_user_phone': phone_number
            }).execute()
            
            if not result.data:
                return False, ""
            
            referral_result = result.data[0]
            success = referral_result.get('success', False)
            referrer_phone = referral_result.get('referrer_phone')
            credits_awarded = referral_result.get('credits_awarded', 0)
            
            if success and referrer_phone:
                # Send notification to referrer
                referrer_message = f"🎉 Great news! Your friend just joined ScribeTok.\n\nYou both got {credits_awarded} bonus credits! Keep sharing: Text /referral"
                await send_sms(referrer_phone, referrer_message)
                
                # Return success message for new user
                return True, f"\n\n🎁 Bonus! You and your friend both got {credits_awarded} extra credits for the referral!"
            
            return False, ""
            
        except Exception as e:
            logger.error(f"Error processing referral for {phone_number}: {str(e)}")
            return False, ""
    
    @staticmethod
    async def _check_and_process_pending_referral(phone_number: str) -> str:
        """Check for pending referrals for new users and process them"""
        try:
            # Check if this user already exists
            user_result = supabase.table("sms_users").select("id").eq("phone_number", phone_number).execute()
            
            if user_result.data:
                # User already exists, no need to check for referrals
                return ""
            
            # New user - check for pending referrals
            referral_result = supabase.rpc('use_pending_referral', {'user_phone': phone_number}).execute()
            
            if referral_result.data and referral_result.data[0]:
                referral_code = referral_result.data[0]
                logger.info(f"Found pending referral {referral_code} for new user {phone_number}")
                
                # The referral will be processed when the transcript completes
                # Store the referral code temporarily (this is a simple approach)
                # In production, you might want a more sophisticated system
                return referral_code
            
            return ""
            
        except Exception as e:
            logger.error(f"Error checking pending referrals for {phone_number}: {str(e)}")
            return ""
    
    @staticmethod
    async def handle_vault_command(phone_number: str) -> str:
        """Handle /vault command with enhanced public links"""
        try:
            # Get completed transcript jobs with links
            if not supabase:
                return "🗂️ Vault temporarily unavailable. Please try again later!"
            
            response = await asyncio.to_thread(
                supabase.table('transcript_jobs')
                        .select("""
                            id, 
                            video_url, 
                            status, 
                            created_at,
                            public_link,
                            transcriptions!transcript_jobs_transcript_id_fkey(title, task_id)
                        """)
                        .eq('from_phone', phone_number)
                        .eq('status', 'completed')
                        .order('created_at', desc=True)
                        .limit(5)
                        .execute
            )
            
            transcripts = response.data if response.data else []
            
            if not transcripts:
                return "🗂️ Your vault is empty! Send a video link to create your first transcript."
            
            vault_text = "🗂️ Your Recent Transcripts:\n\n"
            
            for i, transcript in enumerate(transcripts, 1):
                # Get transcript details
                transcription_data = transcript.get('transcriptions')
                title = transcription_data.get('title', 'Untitled') if transcription_data else 'Untitled'
                task_id = transcription_data.get('task_id') if transcription_data else None
                
                # Format date
                created_date = datetime.fromisoformat(transcript['created_at'].replace('Z', '+00:00'))
                date_str = created_date.strftime('%b %d')
                
                # Create public link
                base_url = os.getenv('BASE_URL', 'https://scribetok.com')
                public_link = transcript.get('public_link') or f"{base_url}/v/{task_id}" if task_id else None
                
                # Format title (keep it short for SMS)
                display_title = title[:25] + '...' if len(title) > 25 else title
                
                vault_text += f"{i}. {display_title} ({date_str})\n"
                if public_link:
                    vault_text += f"   🔗 {public_link}\n"
                vault_text += "\n"
            
            vault_text += f"💬 Reply with a number (1-{len(transcripts)}) for details, /summary for AI analysis, or send a new link!"
            return vault_text
            
        except Exception as e:
            logger.error(f"Error in vault command: {str(e)}")
            return "🗂️ Sorry, couldn't load your vault right now. Please try again later!"
    
    @staticmethod
    async def handle_summary_command(phone_number: str) -> str:
        """Handle /summary command with Claude AI"""
        transcripts = await SMSHandler.get_user_transcripts(phone_number, 1)
        
        if not transcripts:
            return "📝 No transcripts found to summarize. Send a video link first!"
        
        transcript_data = transcripts[0]
        transcript_text = transcript_data.get('transcriptions', {}).get('transcript', '') if transcript_data.get('transcriptions') else ''
        
        if not transcript_text:
            return "📝 Transcript not ready yet or no content found. Try again in a moment!"
        
        try:
            # Generate summary using Claude prompt
            summary = await SMSHandler.generate_summary(transcript_text)
            title = transcript_data.get('transcriptions', {}).get('title', 'Video') if transcript_data.get('transcriptions') else 'Video'
            
            return f"📝 Summary of '{title}':\n\n{summary}"
            
        except Exception as e:
            logger.error(f"Error generating summary: {str(e)}")
            return "📝 Sorry, couldn't generate summary right now. Try again later!"
    
    @staticmethod
    async def generate_summary(transcript_text: str) -> str:
        """Generate summary using Claude API (preferred) with OpenAI fallback"""
        try:
            # Try Claude first (Anthropic API)
            anthropic_key = os.getenv("ANTHROPIC_API_KEY")
            if anthropic_key:
                return await SMSHandler._generate_claude_summary(transcript_text, anthropic_key)
            
            # Fallback to OpenAI
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                return await SMSHandler._generate_openai_summary(transcript_text, openai_key)
            
            # Final fallback to simple truncation
            logger.warning("No AI API keys found, using simple summary")
            words = transcript_text.split()[:30]
            return f"Summary: {' '.join(words)}{'...' if len(transcript_text.split()) > 30 else ''}"
            
        except Exception as e:
            logger.error(f"Error generating summary: {str(e)}")
            words = transcript_text.split()[:30]
            return f"Summary: {' '.join(words)}{'...' if len(transcript_text.split()) > 30 else ''}"
    
    @staticmethod
    async def _generate_claude_summary(transcript_text: str, api_key: str) -> str:
        """Generate summary using Claude API"""
        try:
            import httpx
            
            # Claude API endpoint
            url = "https://api.anthropic.com/v1/messages"
            
            headers = {
                "x-api-key": api_key,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01"
            }
            
            # ScribeTok Claude prompt optimized for viral content
            prompt = f"""You are ScribeTok, a smart AI assistant that summarizes short-form video transcripts for creators, writers, and busy professionals.

Given this transcript of a TikTok or YouTube video, your job is to:

1. Write a short, bold summary of the main idea in 1-2 sentences.
2. Extract one or two punchy, tweet-worthy quotes or lines from the transcript.
3. Be concise, specific, and energetic—sound like a great curator, not a dry robot.
4. Avoid referencing "TikTok" or "YouTube" directly; focus on the content/message.

Format your response exactly like this:

Summary: <your summary here>

Quote: "<memorable quote or phrase from transcript>"

Transcript:
\"\"\"
{transcript_text[:1500]}
\"\"\""""

            data = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                
                result = response.json()
                return result["content"][0]["text"].strip()
                
        except Exception as e:
            logger.error(f"Claude API error: {str(e)}")
            raise e
    
    @staticmethod
    async def _generate_openai_summary(transcript_text: str, api_key: str) -> str:
        """Generate summary using OpenAI API"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            
            prompt = f"""You are ScribeTok, a smart summarizer for short-form video transcripts.

Here is a transcript of a TikTok/YouTube video. Your job is to:
1. Summarize the key point in 1-2 short sentences (max 100 words)
2. Highlight any punchy quotes or phrases that would make a great tweet
3. Keep it conversational and engaging

Transcript:
\"\"\"
{transcript_text[:2000]}
\"\"\"

Respond in this format:
Summary: [your summary]
Quote: "[best quote from the video]" """

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise e
    
    @staticmethod
    async def process_inbound_sms(from_number: str, body: str) -> str:
        """Process incoming SMS and return TwiML response"""
        body = body.strip()
        
        logger.info(f"Processing SMS from {from_number}: {body[:50]}...")
        
        # Handle commands
        if body.lower() == '/help':
            return SMSHandler.create_twiml_response(await SMSHandler.handle_help_command(from_number))
        
        elif body.lower() == '/vault':
            return SMSHandler.create_twiml_response(await SMSHandler.handle_vault_command(from_number))
        
        elif body.lower() == '/summary':
            return SMSHandler.create_twiml_response(await SMSHandler.handle_summary_command(from_number))
        
        elif body.lower() == '/upgrade':
            return SMSHandler.create_twiml_response(await SMSHandler.handle_upgrade_command(from_number))
        
        elif body.lower() == '/referral':
            return SMSHandler.create_twiml_response(await SMSHandler.handle_referral_command(from_number))
        
        # Check for video URLs
        elif SMSHandler.is_video_url(body):
            video_url = SMSHandler.extract_video_url(body)
            if video_url:
                # Check if this is a new user and if there are any pending referrals
                await SMSHandler._check_and_process_pending_referral(from_number)
                
                # Queue the transcription (this will be handled by your existing backend)
                response_msg = "🎥 Got your link! We're transcribing now.\nYou'll get your transcript shortly. ⏱️"
                return SMSHandler.create_twiml_response(response_msg)
            else:
                return SMSHandler.create_twiml_response("🤔 I found a video link but couldn't process it. Try copying the full URL!")
        
        # Handle vault item selection (numbers 1-5)
        elif body.isdigit() and 1 <= int(body) <= 5:
            transcripts = await SMSHandler.get_user_transcripts(from_number, 5)
            try:
                index = int(body) - 1
                if 0 <= index < len(transcripts):
                    transcript = transcripts[index]
                    title = transcript.get('title', 'Untitled')
                    # Return a link to the transcript or abbreviated version
                    return SMSHandler.create_twiml_response(
                        f"📄 {title}\n\n[Transcript content will be sent as a follow-up message or link]"
                    )
                else:
                    return SMSHandler.create_twiml_response(f"❌ Please choose a number between 1 and {len(transcripts)}")
            except:
                return SMSHandler.create_twiml_response("❌ Invalid selection. Type /vault to see your transcripts again.")
        
        # Default response for unrecognized input
        else:
            return SMSHandler.create_twiml_response(
                "🤖 Hi there! Send me a TikTok or YouTube link to get a transcript.\n\nType /help for more options! 📱"
            )

async def send_sms(phone_number: str, message: str) -> bool:
    """Send an SMS message to a phone number"""
    try:
        if not twilio_client:
            logger.warning(f"Twilio not available, cannot send SMS to {phone_number}")
            return False
            
        # Use messaging service if available, otherwise use phone number
        if TWILIO_MESSAGING_SERVICE_SID:
            message = twilio_client.messages.create(
                body=message,
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=phone_number
            )
        else:
            message = twilio_client.messages.create(
                body=message,
                from_=TWILIO_PHONE_NUMBER,
                to=phone_number
            )
        
        logger.info(f"SMS sent successfully to {phone_number}: {message.sid}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send SMS to {phone_number}: {str(e)}")
        return False

async def notify_transcript_complete(phone_number: str, task_id: str, title: str, transcript_preview: str = "", referral_code: str = None) -> bool:
    """Send SMS notification when transcript is complete with credit countdown"""
    try:
        # Use a credit and get the appropriate message
        success, credit_message, remaining = await SMSHandler.use_credit_and_get_message(phone_number, title)
        
        if not success:
            # User is out of credits - send the out of credits message
            return await send_sms(phone_number, credit_message)
        
        # Process referral if this is a new user
        referral_bonus_msg = ""
        if referral_code:
            ref_success, ref_msg = await SMSHandler.process_new_user_referral(phone_number, referral_code)
            if ref_success:
                referral_bonus_msg = ref_msg
        
        # Create the complete message with transcript preview
        if transcript_preview:
            preview = transcript_preview[:150] + "..." if len(transcript_preview) > 150 else transcript_preview
            full_message = f"{credit_message}\n\n📄 Preview:\n{preview}{referral_bonus_msg}\n\n💬 Reply /vault to see all your transcripts!"
        else:
            full_message = f"{credit_message}{referral_bonus_msg}\n\n💬 Reply /vault to see all your transcripts!"
        
        return await send_sms(phone_number, full_message)
        
    except Exception as e:
        logger.error(f"Failed to send completion notification: {str(e)}")
        # Fallback message
        fallback_msg = f"✅ Transcript ready for '{title}'! Reply /vault to see it."
        return await send_sms(phone_number, fallback_msg)