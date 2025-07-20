import { createClient } from 'npm:@supabase/supabase-js@2.39.3';

// Utility functions for phone-first auth system
function normalizePhoneNumber(phone: string): string {
// Remove all non-digit characters
const digits = phone.replace(/\D/g, '');
// Add +1 if it's a 10-digit US number
if (digits.length === 10) {
return `+1${digits}`;
}
// Add + if it doesn't start with +
if (digits.length === 11 && digits.startsWith('1')) {
return `+${digits}`;
}
return phone; // Return as-is if we can't normalize
}

function generateOTPCode(): string {
return Math.floor(100000 + Math.random() * 900000).toString();
}

function generateSessionToken(): string {
return crypto.randomUUID().replace(/-/g, '');
}

// Rate limiting function
async function checkRateLimit(phoneNumber: string, supabase: any): Promise<boolean> {
const normalizedPhone = normalizePhoneNumber(phoneNumber);
const oneMinuteAgo = new Date(Date.now() - 60000).toISOString();

try {
    // Check for recent commands from this phone number
    const { data: recentMessages, error } = await supabase
        .from('user_messages')
        .select('id')
        .eq('from_phone', normalizedPhone)
        .gte('created_at', oneMinuteAgo);

    if (error) {
        console.log('Rate limit check failed:', error);
        return true; // Allow on error
    }

    // Allow max 5 commands per minute
    return (recentMessages?.length || 0) < 5;
} catch (error) {
    console.log('Rate limit check error:', error);
    return true; // Allow on error
}
}

// Get or create SMS user
async function getOrCreateSMSUser(phoneNumber: string, supabase: any) {
const normalizedPhone = normalizePhoneNumber(phoneNumber);

// Try to find existing SMS user
let { data: smsUser, error } = await supabase
.from('sms_users')
.select('*')
.eq('phone_number', normalizedPhone)
.single();

if (!smsUser && error?.code === 'PGRST116') {
// SMS user doesn't exist, create both main user and SMS user
  
// Create SMS user without auth requirement (SMS-only users)
const { data: newSmsUser, error: createError } = await supabase
.from('sms_users')
.insert({
phone_number: normalizedPhone,
auth_user_id: null,  // SMS-only users don't need Supabase auth
last_active: new Date().toISOString()
})
.select('*')
.single();

if (createError) {
console.error('Error creating SMS user:', createError);
return null;
}
smsUser = newSmsUser;
} else if (error) {
console.error('Error fetching SMS user:', error);
return null;
}

// Update last active
await supabase
.from('sms_users')
.update({ last_active: new Date().toISOString() })
.eq('id', smsUser.id);

return smsUser;
}

// OTP functions
async function sendOTP(phoneNumber: string, supabase: any) {
const code = generateOTPCode();
const expires = new Date(Date.now() + 10 * 60 * 1000); // 10 minutes

const user = await getOrCreateSMSUser(phoneNumber, supabase);
if (!user) return false;

// Store OTP
const { error } = await supabase
.from('sms_users')
.update({
verification_code: code,
verification_expires: expires.toISOString()
})
.eq('id', user.id);

if (error) {
console.error('Error storing OTP:', error);
return false;
}

// Send SMS
await sendSMS(phoneNumber, `Your ScribeTok code: ${code}\n\nEnter: /verify ${code}`);
return true;
}

async function verifyOTP(phoneNumber: string, code: string, supabase: any) {
const normalizedPhone = normalizePhoneNumber(phoneNumber);

const { data: user, error } = await supabase
.from('sms_users')
.select('*')
.eq('phone_number', normalizedPhone)
.eq('verification_code', code)
.gt('verification_expires', new Date().toISOString())
.single();

if (!user || error) {
return { success: false };
}

// Generate session token
const sessionToken = generateSessionToken();
const sessionExpires = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000); // 30 days

await supabase
.from('sms_users')
.update({
phone_verified: true,
session_token: sessionToken,
session_expires: sessionExpires.toISOString(),
verification_code: null,
verification_expires: null
})
.eq('id', user.id);

return { success: true, sessionToken, userId: user.id };
}

// Background function to poll for completion and send SMS
async function pollForCompletion(taskId: string, phoneNumber: string, videoUrl: string) {
try {
const supabase = createClient(
Deno.env.get('SUPABASE_URL'),
Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')
);

// Poll for up to 10 minutes
for (let attempt = 0; attempt < 60; attempt++) {
await new Promise(resolve => setTimeout(resolve, 10000)); // Wait 10 seconds

const { data: task, error } = await supabase
.from('transcriptions')
.select('status, transcript, title')
.eq('task_id', taskId)
.single();

if (error) {
console.error('Error checking task status:', error);
continue;
}

if (task.status === 'completed' && task.transcript) {
// Send transcript via SMS
await sendTranscriptSMS(phoneNumber, task.title || 'Video', task.transcript, taskId);
break;
} else if (task.status === 'failed') {
await sendFailureSMS(phoneNumber);
break;
}
}
} catch (error) {
console.error('Error in polling:', error);
}
}

// Send transcript via SMS using Twilio
async function sendTranscriptSMS(phoneNumber: string, title: string, transcript: string, taskId: string) {
try {
// Get first 50 words of transcript for SMS
const words = transcript.split(' ').slice(0, 50);
const shortTranscript = words.join(' ') + (transcript.split(' ').length > 50 ? '...' : '');

const message = `🎬 Transcript ready: "${title}"

${shortTranscript}

📖 Full transcript: https://scribetok.com/v/${taskId}

🚀 Share this link with friends!`;

await sendSMS(phoneNumber, message);
console.log('Transcript SMS sent successfully to:', phoneNumber);
} catch (error) {
console.error('Error sending transcript SMS:', error);
}
}

// Send failure notification
async function sendFailureSMS(phoneNumber: string) {
try {
const message = '❌ Sorry, we couldn\'t transcribe your video. Please try again with a different link.';
await sendSMS(phoneNumber, message);
} catch (error) {
console.error('Error sending failure SMS:', error);
}
}

// Generic SMS sending function
async function sendSMS(phoneNumber: string, message: string) {
const twilioAccountSid = Deno.env.get('TWILIO_ACCOUNT_SID');
const twilioAuthToken = Deno.env.get('TWILIO_AUTH_TOKEN');
const twilioPhoneNumber = Deno.env.get('TWILIO_PHONE_NUMBER') || '+17744727423';

if (!twilioAccountSid || !twilioAuthToken) {
console.error('Twilio credentials not configured');
return;
}

const url = `https://api.twilio.com/2010-04-01/Accounts/${twilioAccountSid}/Messages.json`;
const auth = btoa(`${twilioAccountSid}:${twilioAuthToken}`);

const response = await fetch(url, {
method: 'POST',
headers: {
'Authorization': `Basic ${auth}`,
'Content-Type': 'application/x-www-form-urlencoded',
},
body: new URLSearchParams({
To: phoneNumber,
From: twilioPhoneNumber,
Body: message,
}),
});

if (!response.ok) {
console.error('Twilio API error:', await response.text());
}
}

// --- YouTube helpers ---
function isYouTubeUrl(url) {
  return /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)/i.test(url);
}
function extractYouTubeVideoId(url) {
  // Handles watch?v=, youtu.be/, shorts/
  const match = url.match(/(?:v=|youtu\.be\/|shorts\/)([\w-]{11})/);
  return match ? match[1] : null;
}
async function fetchYouTubeTranscript(youtubeUrl, videoId, lang = "en") {
  const apiUrl = "https://youtube-transcribe-fastest-youtube-transcriber.p.rapidapi.com/transcript";
  const headers = {
    "x-rapidapi-key": Deno.env.get("RAPIDAPI_KEY"),
    "x-rapidapi-host": "youtube-transcribe-fastest-youtube-transcriber.p.rapidapi.com"
  };
  const params = new URLSearchParams({
    lang,
    url: youtubeUrl,
    video_id: videoId
  });
  const response = await fetch(`${apiUrl}?${params.toString()}`, { headers });
  if (!response.ok) throw new Error(await response.text());
  return await response.json();
}

Deno.serve(async (req) => {
// Immediate response function to avoid Twilio timeout
const sendTwilioResponse = (message) =>
new Response(`<Response><Message>${message}</Message></Response>`, {
status: 200,
headers: {
'Content-Type': 'text/xml'
}
});

if (req.method !== 'POST') {
return new Response('Method Not Allowed', {
status: 405
});
}

// Parse Twilio's x-www-form-urlencoded or JSON
let From, Body;
const contentType = req.headers.get('content-type') || '';

if (contentType.includes('application/json')) {
({ From, Body } = await req.json().catch(() => ({})));
} else {
const form = await req.formData();
From = form.get('From');
Body = form.get('Body');
}

// Robust logging for debugging
console.log('Received Body:', JSON.stringify(Body));
console.log('Received From:', JSON.stringify(From));

if (!From || !Body) {
return sendTwilioResponse('Missing From or Body.');
}

// Initialize Supabase client for all commands
const supabase = createClient(
Deno.env.get('SUPABASE_URL'),
Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')
);

// Check rate limiting (max 5 commands per minute)
const rateLimitOk = await checkRateLimit(From, supabase);
if (!rateLimitOk) {
    console.log(`Rate limit exceeded for ${From}`);
    return sendTwilioResponse('⚠️ Too many commands. Please wait a minute before trying again.');
}

// Handle commands
if (Body.trim().toLowerCase() === '/help') {
return sendTwilioResponse('🤖 ScribeTok Help:\n\n📱 Commands:\n/register - Create account & link your history\n/login - Get verification code\n/verify 123456 - Verify with code\n/profile - View your stats\n/vault - View transcripts\n\nJust text any TikTok/YouTube link to transcribe!');
}

// Login command - send OTP
if (Body.trim().toLowerCase() === '/login') {
const success = await sendOTP(From, supabase);
if (success) {
return sendTwilioResponse('📱 Check your texts! Enter the 6-digit code like this:\n\n/verify 123456');
} else {
return sendTwilioResponse('❌ Error sending verification code. Try again later.');
}
}

// Verify OTP command
if (Body.trim().toLowerCase().startsWith('/verify ')) {
const code = Body.trim().split(' ')[1];
if (!code || code.length !== 6) {
return sendTwilioResponse('❌ Please enter a 6-digit code like:\n\n/verify 123456');
}

const result = await verifyOTP(From, code, supabase);
if (result.success) {
return sendTwilioResponse('✅ Verified! You can now:\n\n💻 Access web: https://scribetok.com/login\n📱 Use /profile to see your stats\n🎥 Text video links for transcripts');
} else {
return sendTwilioResponse('❌ Invalid or expired code. Try /login to get a new one.');
}
}

// Profile command
if (Body.trim().toLowerCase() === '/profile') {
const user = await getOrCreateSMSUser(From, supabase);
if (!user) {
return sendTwilioResponse('❌ Error loading profile. Try again later.');
}

// Get user's transcript count
const { data: transcripts } = await supabase
.from('transcriptions')
.select('task_id')
.eq('user_phone', normalizePhoneNumber(From));

const totalCount = transcripts?.length || 0;
const verifiedStatus = user.phone_verified ? '✅ Verified' : '❌ Not verified';

return sendTwilioResponse(`📱 Your ScribeTok Profile:

📊 Total transcripts: ${totalCount}
${verifiedStatus}
📅 Joined: ${new Date(user.created_at).toLocaleDateString()}

💻 Web access: https://scribetok.com/login
💡 Text /login to verify your account`);
}

// Register command - create phone-based account and link history
if (Body.trim().toLowerCase() === '/register') {
try {
// Get user stats before linking
const { data: stats } = await supabase.rpc('get_sms_user_stats', {
p_phone_number: From
});

const transcriptionCount = stats?.[0]?.total_transcriptions || 0;

if (transcriptionCount === 0) {
return sendTwilioResponse('📱 No transcription history found. Send a video link first, then register!');
}

// Check if already has auth account
const user = await getOrCreateSMSUser(From, supabase);
if (user && user.auth_user_id) {
return sendTwilioResponse('✅ You already have an account!\n\n💻 Access web: https://scribetok.com/login\n📱 Use your phone number to sign in');
}

// Call backend to create phone-based account and link transcriptions
const renderApiUrl = `${Deno.env.get('RENDER_SERVICE_URL')}/api/link-sms-account`;
const linkResponse = await fetch(renderApiUrl, {
method: 'POST',
headers: { 
'Content-Type': 'application/json',
'User-Agent': 'Supabase-Edge-Function'
},
body: JSON.stringify({
phone: From
})
});

const result = await linkResponse.json();

if (linkResponse.ok && result.success) {
return sendTwilioResponse(`✅ Account created successfully!\n\n📱 Phone: ${From}\n🔗 Linked ${result.linked_transcriptions} transcriptions\n\n💻 Web access: https://scribetok.com/login\n🔑 Use your phone number to sign in`);
} else {
const errorMsg = result.error || 'Unknown error';
if (errorMsg.includes('already registered')) {
return sendTwilioResponse('✅ You already have an account!\n\n💻 Access web: https://scribetok.com/login');
}
return sendTwilioResponse(`❌ Registration failed: ${errorMsg}\n\nTry again later or contact support.`);
}
} catch (error) {
console.error('Registration error:', error);
return sendTwilioResponse('❌ Registration failed. Please try again later.');
}
}

// Vault command
if (Body.trim().toLowerCase() === '/vault') {
try {
const { data: transcripts, error } = await supabase
.from('transcriptions')
.select('task_id, title, status, created_at')
.eq('user_phone', normalizePhoneNumber(From))
.order('created_at', { ascending: false })
.limit(5);

if (error || !transcripts || transcripts.length === 0) {
return sendTwilioResponse('📱 Your vault is empty! Send a video link to create your first transcript.');
}

let vaultMessage = '📱 Your Recent Transcripts:\n\n';
transcripts.forEach((transcript, i) => {
const title = transcript.title?.replace(`SMS from ${From}`, 'Video') || 'Video';
const date = new Date(transcript.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
const status = transcript.status === 'completed' ? '✅' : transcript.status === 'processing' ? '⏳' : '❌';

vaultMessage += `${i + 1}. ${status} ${title.substring(0, 30)}... (${date})\n`;
if (transcript.status === 'completed') {
vaultMessage += `   🔗 https://scribetok.com/v/${transcript.task_id}\n`;
}
vaultMessage += '\n';
});

vaultMessage += '💡 Reply with a number (1-5) for details, or send a new video link!';
return sendTwilioResponse(vaultMessage);
} catch (error) {
console.error('Vault error:', error);
return sendTwilioResponse('📱 Error loading your vault. Try again later!');
}
}

// More robust URL detection using regex
const urlRegex = /(https?:\/\/[^\s]+)/i;
const match = Body.trim().match(urlRegex);

if (!match) {
return sendTwilioResponse('👀 That doesn\'t look like a link. Try again or type /help.');
}

// Use the first matched URL
const url = match[0];

try {
// Get or create SMS user and link to transcription
const smsUser = await getOrCreateSMSUser(From, supabase);

if (smsUser) {
// Update user's transcription count
await supabase
.from('sms_users')
.update({
total_transcriptions: (smsUser.total_transcriptions || 0) + 1,
monthly_transcriptions: (smsUser.monthly_transcriptions || 0) + 1
})
.eq('id', smsUser.id);
}

if (isYouTubeUrl(url)) {
  const videoId = extractYouTubeVideoId(url);
  try {
    const transcriptData = await fetchYouTubeTranscript(url, videoId);
    const transcript = transcriptData.transcript || '';
    // Store in Supabase as completed
    const { data: insertedTask, error } = await supabase.from('transcriptions').insert({
      url: url,
      status: 'completed',
      tags: ['sms-inbound', 'youtube'],
      category: 'youtube-transcription',
      title: transcriptData.title || null,
      user_phone: From,
      user_id: null,
      transcript: transcript
    }).select('task_id').single();
    if (error) {
      console.error('Supabase insert error:', error);
      return sendTwilioResponse('⚠️ Error saving your YouTube transcript. Try again.');
    }
    // Send SMS with transcript preview
    const words = transcript.split(' ').slice(0, 50);
    const shortTranscript = words.join(' ') + (transcript.split(' ').length > 50 ? '...' : '');
    const message = `🎬 YouTube Transcript ready: "${transcriptData.title || 'Video'}"
\n${shortTranscript}
\n📖 Full transcript: https://scribetok.com/v/${insertedTask.task_id}`;
    await sendSMS(From, message);
    return sendTwilioResponse('✅ YouTube transcript complete! Check your texts for details.');
  } catch (err) {
    console.error('YouTube RapidAPI error:', err);
    return sendTwilioResponse('❌ Failed to transcribe YouTube video. Try again later.');
  }
}

// Perform database insert before responding
const { data: insertedTask, error } = await supabase
.from('transcriptions')
.insert({
url: url,
status: 'pending',
tags: ['sms-inbound'],
category: 'sms-transcription',
title: null,  // Let backend set the actual video title during processing
user_phone: From,
user_id: null,  // SMS users don't need user_id, just user_phone
})
.select('task_id')
.single();

if (error) {
console.error('Supabase insert error:', error);
return sendTwilioResponse('⚠️ Error logging your request. Try again.');
}

console.log('Database record created with task_id:', insertedTask?.task_id);

// Send immediate response to user FIRST
const initialResponse = sendTwilioResponse('🎥 Got your link! We\'re transcribing now. You\'ll get your transcript shortly.');

// Call Render service to start processing (async, don't wait)
setTimeout(async () => {
  try {
    const renderApiUrl = `${Deno.env.get('RENDER_SERVICE_URL')}/api/public/transcribe`;
    console.log('Calling Render API:', renderApiUrl);

    const transcribeResponse = await fetch(renderApiUrl, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'User-Agent': 'Supabase-Edge-Function'
      },
      body: JSON.stringify({
        url: url,
        user_phone: normalizePhoneNumber(From)  // Pass phone number for SMS notification
      })
    });

    const responseText = await transcribeResponse.text();
    console.log('Render API response:', transcribeResponse.status, responseText);

    if (!transcribeResponse.ok) {
      console.error('Render API failed:', transcribeResponse.status, responseText);
    }
  } catch (apiError) {
    console.error('Failed to call Render API:', apiError);
  }
}, 0);

// Backend will handle SMS notification when transcription completes
console.log(`Task ${insertedTask.task_id} queued for phone ${From}`);

return initialResponse;

} catch (err) {
console.error('Unexpected error:', err);
return sendTwilioResponse('🚨 An unexpected error occurred. Please try again.');
}
});