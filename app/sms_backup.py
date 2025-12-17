import os
import re
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    # Mock class for when Twilio is not available
    class Client:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

        @property
        def messages(self):
            return type(
                "MockMessages",
                (),
                {"create": lambda **kwargs: type("MockMessage", (), {"sid": "mock_sid"})()},
            )()

    TWILIO_AVAILABLE = False
    logging.warning("Twilio not available, using mock classes")

try:
    from twilio.twiml.messaging_response import MessagingResponse
except ImportError:
    # Mock class for when Twilio is not available
    class MessagingResponse:  # type: ignore
        def __init__(self):
            self._message = None

        def message(self, text):
            self._message = text

        def __str__(self):
            return f"<Response><Message>{self._message}</Message></Response>"
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
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        logger.info("Twilio client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Twilio client: {str(e)}")
else:
    logger.warning("Twilio credentials not found. SMS functionality will be disabled.")

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
                        .execute()
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
• /help - Show this message

Just paste any video link and we'll transcribe it for you! 🎥✨"""
    
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
                        .execute()
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
        
        # Check for video URLs
        elif SMSHandler.is_video_url(body):
            video_url = SMSHandler.extract_video_url(body)
            if video_url:
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

async def notify_transcript_complete(phone_number: str, task_id: str, title: str, transcript_preview: str = "") -> bool:
    """Send SMS notification when transcript is complete"""
    try:
        # Truncate transcript for SMS
        preview = transcript_preview[:200] + "..." if len(transcript_preview) > 200 else transcript_preview
        
        message = f"✅ Transcript ready!\n\n📄 {title}\n\n{preview}\n\n💬 Reply /vault to see all your transcripts!"
        
        return await SMSHandler.send_sms(
            to=phone_number,
            body=message,
            status_callback=f"{os.getenv('BASE_URL', '')}/api/sms/status"
        )
    except Exception as e:
        logger.error(f"Failed to send completion notification: {str(e)}")
        return False