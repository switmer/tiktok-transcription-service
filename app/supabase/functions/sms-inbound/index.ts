import { createClient } from 'npm:@supabase/supabase-js@2.39.3';
// Utility functions for phone-first auth system
function normalizePhoneNumber(phone) {
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
function generateOTPCode() {
  return Math.floor(100000 + Math.random() * 900000).toString();
}
function generateSessionToken() {
  return crypto.randomUUID().replace(/-/g, '');
}
// Rate limiting function
async function checkRateLimit(phoneNumber, supabase) {
  const normalizedPhone = normalizePhoneNumber(phoneNumber);
  const oneMinuteAgo = new Date(Date.now() - 60000).toISOString();
  try {
    // Check for recent commands from this phone number
    const { data: recentMessages, error } = await supabase.from('user_messages').select('id').eq('from_phone', normalizedPhone).gte('created_at', oneMinuteAgo);
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
async function getOrCreateSMSUser(phoneNumber, supabase) {
  const normalizedPhone = normalizePhoneNumber(phoneNumber);
  // Try to find existing SMS user
  let { data: smsUsers, error } = await supabase.from('sms_users').select('*').eq('phone_number', normalizedPhone);
  let smsUser = smsUsers && smsUsers.length > 0 ? smsUsers[0] : null;
  if (!smsUser) {
    // SMS user doesn't exist, create both main user and SMS user
    // Create SMS user without auth requirement (SMS-only users) with 3 free credits
    const { data: newSmsUser, error: createError } = await supabase.from('sms_users').insert({
      phone_number: normalizedPhone,
      auth_user_id: null,
      last_active: new Date().toISOString(),
      credits_remaining: 3  // Start with 3 free credits
    }).select('*').single();
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
  {
    const { error: updateError } = await supabase.from('sms_users').update({
      last_active: new Date().toISOString()
    }).eq('id', smsUser.id);
    if (updateError) {
      console.error('Error updating last_active for SMS user:', updateError);
    }
  }
  return smsUser;
}
// OTP functions
async function sendOTP(phoneNumber, supabase) {
  const code = generateOTPCode();
  const expires = new Date(Date.now() + 10 * 60 * 1000); // 10 minutes
  const user = await getOrCreateSMSUser(phoneNumber, supabase);
  if (!user) return false;
  // Store OTP
  const { error } = await supabase.from('sms_users').update({
    verification_code: code,
    verification_expires: expires.toISOString()
  }).eq('id', user.id);
  if (error) {
    console.error('Error storing OTP:', error);
    return false;
  }
  // Send SMS
  await sendSMS(phoneNumber, `Your ScribeTok code: ${code}\n\nEnter: /verify ${code}`);
  return true;
}
async function verifyOTP(phoneNumber, code, supabase) {
  const normalizedPhone = normalizePhoneNumber(phoneNumber);
  const { data: user, error } = await supabase.from('sms_users').select('*').eq('phone_number', normalizedPhone).eq('verification_code', code).gt('verification_expires', new Date().toISOString()).single();
  if (!user || error) {
    return {
      success: false
    };
  }
  // Generate session token
  const sessionToken = generateSessionToken();
  const sessionExpires = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000); // 30 days
  {
    const { error: updateError } = await supabase.from('sms_users').update({
    phone_verified: true,
    session_token: sessionToken,
    session_expires: sessionExpires.toISOString(),
    verification_code: null,
    verification_expires: null
  }).eq('id', user.id);
    if (updateError) {
      console.error('Error updating SMS user after OTP verification:', updateError);
    }
  }
  return {
    success: true,
    sessionToken,
    userId: user.id
  };
}
// Background polling that respects 409 Not Ready from backend and avoids double sends
async function pollForCompletion(taskId: string, phoneNumber: string) {
  const baseUrl = (Deno.env.get('RENDER_SERVICE_URL') || '').replace(/\/$/, '');
  const apiKey = Deno.env.get('RENDER_API_KEY') || '';
  const headers: Record<string, string> = {
    'User-Agent': 'Supabase-Edge-Function',
  };
  // Public transcript endpoint should not require API key; include if set just in case env expects it
  if (apiKey) headers['X-API-Key'] = apiKey;

  let delayMs = 2000; // start with 2s
  const maxDelayMs = 15000; // cap backoff
  const deadline = Date.now() + 10 * 60 * 1000; // 10 minutes

  while (Date.now() < deadline) {
    try {
      await new Promise((r) => setTimeout(r, delayMs));
      const resp = await fetch(`${baseUrl}/api/public/transcript/${taskId}`, { method: 'GET', headers });
      if (resp.status === 200) {
        // Success: backend will send completion SMS; do not double-send
        console.log(`Task ${taskId} ready; letting backend SMS stand.`);
        return;
      }
      if (resp.status === 409) {
        // Not ready; respect retry_after_ms if present
        let retryAfterMs = delayMs;
        try {
          const body = await resp.json();
          if (typeof body?.retry_after_ms === 'number' && body.retry_after_ms > 0) {
            retryAfterMs = body.retry_after_ms;
          }
          console.log(`Task ${taskId} not ready: ${body?.status || 'pending'}; retry in ${retryAfterMs}ms`);
        } catch {
          // fallback to exponential backoff
          retryAfterMs = Math.min(maxDelayMs, delayMs * 1.5);
        }
        delayMs = Math.min(maxDelayMs, retryAfterMs);
        continue;
      }
      if (resp.status === 404) {
        // Task not found; stop
        console.warn(`Task ${taskId} not found while polling.`);
        return;
      }
      // Other errors: try task status to see if failed
      const statusResp = await fetch(`${baseUrl}/api/public/tasks/${taskId}`, { headers });
      if (statusResp.ok) {
        const t = await statusResp.json();
        if (t?.status === 'failed') {
          await sendFailureSMS(phoneNumber);
          return;
        }
      }
      // brief backoff before next loop
      delayMs = Math.min(maxDelayMs, delayMs * 1.5);
    } catch (e) {
      console.error('Polling error:', e);
      delayMs = Math.min(maxDelayMs, delayMs * 1.5);
    }
  }
  console.warn(`Polling timed out for task ${taskId}`);
}
// Send transcript via SMS using Twilio
async function sendTranscriptSMS(phoneNumber, title, transcript, taskId) {
  try {
    const supabase = createClient(Deno.env.get('SUPABASE_URL'), Deno.env.get('SUPABASE_SERVICE_ROLE_KEY'));
    
    // Get user's current credits
    const { data: smsUser } = await supabase.from('sms_users').select('credits_remaining').eq('phone_number', normalizePhoneNumber(phoneNumber)).single();
    const creditsRemaining = smsUser?.credits_remaining || 0;
    
    // Get first 50 words of transcript for SMS
    const words = transcript.split(' ').slice(0, 50);
    const shortTranscript = words.join(' ') + (transcript.split(' ').length > 50 ? '...' : '');
    
    let message = `🎬 Transcript ready: "${title}"

${shortTranscript}

📖 Full transcript: https://share.scribetok.com/v/${taskId}
💳 Credits remaining: ${creditsRemaining}`;

    // Add upsell messages based on credits remaining - optimized conversion flow
    // Note: creditsRemaining is the CURRENT amount (after this transcription was deducted)
    if (creditsRemaining === 0) {
      message += `

💳 You've used all 3 free transcripts!
Get 5 more for just $1.99 - cheaper than 1 jukebox song!
🚀 Buy now: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01

🎁 Or invite friends: /referral`;
    } else if (creditsRemaining === 1) {
      message += `

⚠️ Last free transcript! Get 5 more for $1.99: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01
🎁 Or invite friends: /referral`;
    } else if (creditsRemaining === 2) {
      message += `

💡 Only 2 free transcripts left! 
🚀 Get 5 more for $1.99: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01`;
    }

    message += `

💬 Share with friends who'd love this!
📱 Send link: https://share.scribetok.com/v/${taskId}
🎁 Want free credits? Text /referral for your sharing link!`;

    await sendSMS(phoneNumber, message);
    console.log('Transcript SMS sent successfully to:', phoneNumber);
  } catch (error) {
    console.error('Error sending transcript SMS:', error);
  }
}
// Send failure notification
async function sendFailureSMS(phoneNumber) {
  try {
    const message = '❌ Sorry, we couldn\'t transcribe your video. Please try again with a different link.';
    await sendSMS(phoneNumber, message);
  } catch (error) {
    console.error('Error sending failure SMS:', error);
  }
}
// Generic SMS sending function
async function sendSMS(phoneNumber, message) {
  const twilioAccountSid = Deno.env.get('TWILIO_ACCOUNT_SID');
  const twilioAuthToken = Deno.env.get('TWILIO_AUTH_TOKEN');
  const twilioPhoneNumber = Deno.env.get('TWILIO_PHONE_NUMBER') || '+17744727423';
  
  if (!twilioAccountSid || !twilioAuthToken) {
    console.error('Twilio credentials not configured');
    return null;
  }

  const url = `https://api.twilio.com/2010-04-01/Accounts/${twilioAccountSid}/Messages.json`;
  const auth = btoa(`${twilioAccountSid}:${twilioAuthToken}`);
  
  // Status callback URL
  const statusCallbackUrl = `${Deno.env.get('SUPABASE_URL')}/functions/v1/sms-status-callback`;
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Basic ${auth}`,
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: new URLSearchParams({
      To: phoneNumber,
      From: twilioPhoneNumber,
      Body: message,
      StatusCallback: statusCallbackUrl
    })
  });

  if (response.ok) {
    const result = await response.json();
    
    try {
      // Log the outgoing message to user_messages table
      const supabase = createClient(
        Deno.env.get('SUPABASE_URL'), 
        Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')
      );
      
      await supabase.from('user_messages').upsert({
        id: crypto.randomUUID(), // Generate unique ID
        from_phone: twilioPhoneNumber,
        to_phone: normalizePhoneNumber(phoneNumber),
        message_body: message,
        direction: 'outbound',
        message_sid: result.sid,
        delivery_status: result.status || 'queued'
      }, { 
        onConflict: 'id' 
      });
      
      console.log(`SMS sent and logged: ${result.sid} to ${phoneNumber}`);
    } catch (dbError) {
      console.error('Error logging outbound SMS:', dbError);
    }
    
    return result.sid;
  } else {
    console.error('Twilio API error:', await response.text());
    return null;
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
  const response = await fetch(`${apiUrl}?${params.toString()}`, {
    headers
  });
  if (!response.ok) throw new Error(await response.text());
  return await response.json();
}
Deno.serve(async (req)=>{
  // Immediate response function to avoid Twilio timeout
  const sendTwilioResponse = (message)=>new Response(`<Response><Message>${message}</Message></Response>`, {
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
    ({ From, Body } = await req.json().catch(()=>({})));
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
  const supabase = createClient(Deno.env.get('SUPABASE_URL'), Deno.env.get('SUPABASE_SERVICE_ROLE_KEY'));
  
  // Log all incoming messages to user_messages table
  try {
    const command = Body.trim().startsWith('/') ? Body.trim().split(' ')[0].toLowerCase() : null;
    await supabase.from('user_messages').upsert({
      id: crypto.randomUUID(), // Generate unique ID
      from_phone: normalizePhoneNumber(From),
      message_body: Body,
      command: command
    }, { 
      onConflict: 'id' 
    });
  } catch (logError) {
    console.error('Error logging message to user_messages:', logError);
    // Continue processing even if logging fails
  }
  
  // Check rate limiting (max 5 commands per minute)
  const rateLimitOk = await checkRateLimit(From, supabase);
  if (!rateLimitOk) {
    console.log(`Rate limit exceeded for ${From}`);
    return sendTwilioResponse('⚠️ Too many commands. Please wait a minute before trying again.');
  }
  // Handle commands
  if (Body.trim().toLowerCase() === '/help') {
    return sendTwilioResponse(`🤖 ScribeTok Help:

📱 Commands:
/register - Create account & link your history
/login - Get verification code
/verify 123456 - Verify with code
/profile - View your stats & credits
/vault - View transcripts
/tldr - AI summary of your latest transcript
/quote - Get the best quote from latest video
/full - See full transcript of latest video
/referral - Get your referral link for free credits
/feedback [message] - Send feedback to improve ScribeTok

💳 Credits:
• New users get 3 free transcripts
• 5 more for just $1.99: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01
• Unlimited for $6.75/month: https://buy.stripe.com/6oUeVcgEIfib3x84WG6Vq02
• Refer friends: Both get 3 bonus credits!

Just text any TikTok/YouTube link to save the good stuff!`);
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
    const { data: transcripts } = await supabase.from('transcriptions').select('task_id').eq('user_phone', normalizePhoneNumber(From));
    const totalCount = transcripts?.length || 0;
    const verifiedStatus = user.phone_verified ? '✅ Verified' : '❌ Not verified';
    const creditsRemaining = user.credits_remaining || 0;
    return sendTwilioResponse(`📱 Your ScribeTok Profile:

📊 Total transcripts: ${totalCount}
💳 Credits remaining: ${creditsRemaining}
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
      const baseUrl = Deno.env.get('RENDER_SERVICE_URL') || '';
      const renderApiUrl = `${baseUrl.replace(/\/$/, '')}/api/link-sms-account`;
      const linkResponse = await fetch(renderApiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Supabase-Edge-Function',
          'X-API-Key': Deno.env.get('RENDER_API_KEY') || 'f8a9b1e2-c5d4-4e5f-8d7b-1c2d3e4f5a6b'
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
      const { data: transcripts, error } = await supabase.from('transcriptions').select('task_id, title, status, created_at').eq('user_phone', normalizePhoneNumber(From)).order('created_at', {
        ascending: false
      }).limit(5);
      if (error || !transcripts || transcripts.length === 0) {
        return sendTwilioResponse('📱 Your vault is empty! Send a video link to create your first transcript.');
      }
      let vaultMessage = '📱 Your Recent Transcripts:\n\n';
      transcripts.forEach((transcript, i)=>{
        const title = transcript.title?.replace(`SMS from ${From}`, 'Video') || 'Video';
        const date = new Date(transcript.created_at).toLocaleDateString('en-US', {
          month: 'short',
          day: 'numeric'
        });
        const status = transcript.status === 'completed' ? '✅' : transcript.status === 'processing' ? '⏳' : '❌';
        vaultMessage += `${i + 1}. ${status} ${title.substring(0, 30)}... (${date})\n`;
        if (transcript.status === 'completed') {
          vaultMessage += `   🔗 https://share.scribetok.com/v/${transcript.task_id}\n`;
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

  // Referral command
  if (Body.trim().toLowerCase() === '/referral') {
    try {
      const user = await getOrCreateSMSUser(From, supabase);
      if (!user) {
        return sendTwilioResponse('❌ Error loading your account. Try again later.');
      }

      // Get or generate referral code
      let referralCode = user.referral_code;
      if (!referralCode) {
        // Generate a simple referral code based on phone number
        const phoneDigits = From.replace(/\D/g, '');
        referralCode = `REF${phoneDigits.slice(-6)}`;
        
        const { error: referralUpdateError } = await supabase.from('sms_users').update({
          referral_code: referralCode
        }).eq('id', user.id);
        if (referralUpdateError) {
          console.error('Error updating referral_code for SMS user:', referralUpdateError);
        }
      }

      const referralsCount = user.referrals_count || 0;
      const creditsRemaining = user.credits_remaining || 0;
      const referralLink = `https://scribetok.com/?ref=${referralCode}`;

      return sendTwilioResponse(`🎁 Get 3 bonus credits for each friend you invite!

📱 Your sharing link: ${referralLink}

💡 Easy ways to share:
• "Found this cool TikTok transcriber! Try it: ${referralLink}"
• Post in group chats, Discord, Slack
• Share on social: "Transcribe any video instantly!"

📊 Friends you've helped: ${referralsCount}
💳 Your credits: ${creditsRemaining}

💡 TIP: When friends use your link, you both get 3 free credits!

💰 Or buy credits: 5 for $1.99: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01
🚀 Go unlimited: $6.75/month: https://buy.stripe.com/6oUeVcgEIfib3x84WG6Vq02`);
    } catch (error) {
      console.error('Referral error:', error);
      return sendTwilioResponse('❌ Error loading referral info. Try again later.');
    }
  }

  // Feedback command
  if (Body.trim().toLowerCase().startsWith('/feedback ')) {
    try {
      const feedbackText = Body.trim().substring(10); // Remove '/feedback '
      
      if (feedbackText.length < 10) {
        return sendTwilioResponse('💬 Please provide more detailed feedback!\n\nExample: /feedback The app is great but could use faster transcriptions');
      }

      const user = await getOrCreateSMSUser(From, supabase);
      if (!user) {
        return sendTwilioResponse('❌ Error saving feedback. Try again later.');
      }

      // Store feedback in user_messages table using command field
      const { error } = await supabase.from('user_messages').upsert({
        id: crypto.randomUUID(), // Generate unique ID
        from_phone: normalizePhoneNumber(From),
        message_body: feedbackText,
        command: 'feedback'
      }, { 
        onConflict: 'id' 
      });

      if (error) {
        console.error('Error storing feedback:', error);
        // Fallback: log to console and send success message anyway
        console.log(`FEEDBACK from ${From}: ${feedbackText}`);
      }

      return sendTwilioResponse(`💬 Thank you for your feedback! We read every message.

"${feedbackText.substring(0, 100)}${feedbackText.length > 100 ? '...' : ''}"

🎁 As a thanks, here's your referral link for free credits: https://scribetok.com/?ref=FEEDBACK

Reply /help for more commands!`);
    } catch (error) {
      console.error('Feedback error:', error);
      return sendTwilioResponse('❌ Error saving feedback. Please try again later.');
    }
  }

  // TLDR command (formerly /summary)
  if (Body.trim().toLowerCase() === '/tldr' || Body.trim().toLowerCase() === '/summary') {
    try {
      // Call the Python backend's summary endpoint
      const baseUrl = Deno.env.get('RENDER_SERVICE_URL') || '';
      const renderApiUrl = `${baseUrl.replace(/\/$/, '')}/api/sms/summary`;
      const summaryResponse = await fetch(renderApiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Supabase-Edge-Function',
          'X-API-Key': Deno.env.get('RENDER_API_KEY') || 'f8a9b1e2-c5d4-4e5f-8d7b-1c2d3e4f5a6b'
        },
        body: JSON.stringify({
          phone: normalizePhoneNumber(From)
        })
      });

      if (summaryResponse.ok) {
        const result = await summaryResponse.json();
        return sendTwilioResponse(result.summary);
      } else {
        console.error('TLDR API failed:', summaryResponse.status, await summaryResponse.text());
        return sendTwilioResponse('🧠 Too long, didn\'t watch? We got you covered - but our TLDR feature is temporarily unavailable. Try again later!');
      }
    } catch (error) {
      console.error('TLDR error:', error);
      return sendTwilioResponse('🧠 Too long, didn\'t watch? We got you covered - but our TLDR feature is temporarily unavailable. Try again later!');
    }
  }

  // Full transcript command
  if (Body.trim().toLowerCase() === '/full') {
    try {
      const { data: transcripts, error } = await supabase.from('transcriptions').select('task_id, title, transcript, status').eq('user_phone', normalizePhoneNumber(From)).order('created_at', { ascending: false }).limit(1);
      
      if (error || !transcripts || transcripts.length === 0) {
        await sendSMS(From, '📄 No transcripts found. Send a video link first!');
        return sendTwilioResponse('');
      }

      const latest = transcripts[0];
      if (latest.status !== 'completed' || !latest.transcript) {
        await sendSMS(From, '📄 Latest transcript not ready yet. Try again in a moment!');
        return sendTwilioResponse('');
      }

      const title = latest.title || 'Video';
      const transcript = latest.transcript;
      const words = transcript.split(' ');
      
      // SMS has character limits, so we need to chunk long transcripts
      let message;
      if (words.length > 100) {
        const chunk = words.slice(0, 100).join(' ') + '...';
        message = `📄 Full transcript: "${title}"

${chunk}

💡 This is a preview. Full version: https://share.scribetok.com/v/${latest.task_id}`;
      } else {
        message = `📄 Full transcript: "${title}"

${transcript}

🔗 Share: https://share.scribetok.com/v/${latest.task_id}`;
      }
      
      await sendSMS(From, message);
      return sendTwilioResponse('');
    } catch (error) {
      console.error('Full transcript error:', error);
      await sendSMS(From, '📄 Error loading transcript. Try again later!');
      return sendTwilioResponse('');
    }
  }

  // Quote command - get the best quote from latest video
  if (Body.trim().toLowerCase() === '/quote') {
    try {
      const { data: transcripts, error } = await supabase.from('transcriptions').select('quote, title, task_id, status').eq('user_phone', normalizePhoneNumber(From)).order('created_at', { ascending: false }).limit(1);
      
      if (error || !transcripts || transcripts.length === 0) {
        await sendSMS(From, '🧠 No transcripts found. Send a video link first!');
        return sendTwilioResponse('');
      }

      const latest = transcripts[0];
      if (latest.status !== 'completed') {
        await sendSMS(From, '🧠 Latest video not ready yet. Try again in a moment!');
        return sendTwilioResponse('');
      }

      if (!latest.quote) {
        await sendSMS(From, '🧠 No quote found for this video. Try /tldr instead!');
        return sendTwilioResponse('');
      }

      const title = latest.title || 'Video';
      const message = `🧠 Quote from "${title}":

"${latest.quote}"

🔗 Share: https://share.scribetok.com/v/${latest.task_id}
💡 Want the TLDR? Reply /tldr`;

      await sendSMS(From, message);
      return sendTwilioResponse('');
    } catch (error) {
      console.error('Quote command error:', error);
      await sendSMS(From, '🧠 Error loading quote. Try again later!');
      return sendTwilioResponse('');
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
    // Get or create SMS user and check credits
    const smsUser = await getOrCreateSMSUser(From, supabase);
    if (!smsUser) {
      return sendTwilioResponse('❌ Error creating user account. Try again later.');
    }

    // Check if user has credits remaining
    const creditsRemaining = smsUser.credits_remaining || 0;
    if (creditsRemaining <= 0) {
      return sendTwilioResponse(`💳 You've used all your free transcripts!

Get 5 more for just $1.99 - cheaper than 1 jukebox song!
🚀 Buy now: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01

🎁 Or invite friends for 3 free credits each: /referral
💻 Go unlimited for $6.75/month: https://buy.stripe.com/6oUeVcgEIfib3x84WG6Vq02`);
    }

    // Deduct one credit for this transcription
    {
      // Defensive coercion: PostgREST can return bigints as strings, which would turn `+ 1`
      // into string concatenation and cause 400 "invalid input syntax for type integer".
      // NOTE: Production schema uses `total_videos_transcribed` (not `total_transcriptions`).
      // Attempting to update non-existent columns causes PostgREST 400s.
      const nextTotalVideos = Number(smsUser.total_videos_transcribed ?? 0) + 1;
      const nextCredits = Number(creditsRemaining) - 1;

      const { error: deductError } = await supabase.from('sms_users').update({
        credits_remaining: nextCredits,
        total_videos_transcribed: nextTotalVideos
      }).eq('id', smsUser.id);

      if (deductError) {
        console.error('Error deducting credit / incrementing counters for SMS user:', {
          deductError,
          smsUserId: smsUser.id,
          creditsRemaining,
          nextCredits,
          nextTotalVideos
        });
      }
    }

    const newCreditsRemaining = creditsRemaining - 1;
    if (isYouTubeUrl(url)) {
      const videoId = extractYouTubeVideoId(url);
      try {
        const transcriptData = await fetchYouTubeTranscript(url, videoId);
        const transcript = transcriptData.transcript || '';
        // Store in Supabase as completed
        const { data: insertedTask, error } = await supabase.from('transcriptions').insert({
          url: url,
          status: 'completed',
          tags: [
            'sms-inbound',
            'youtube'
          ],
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
        
        let message = `🎬 YouTube Transcript ready: "${transcriptData.title || 'Video'}"

${shortTranscript}

📖 Full transcript: https://share.scribetok.com/v/${insertedTask.task_id}
💳 Credits remaining: ${newCreditsRemaining}`;

        // Add upsell messages based on credits remaining - optimized conversion flow
        if (newCreditsRemaining === 0) {
          message += `

💳 You've used all 3 free transcripts!
Get 5 more for just $1.99 - cheaper than 1 jukebox song!
🚀 Buy now: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01

🎁 Or invite friends: /referral`;
        } else if (newCreditsRemaining === 1) {
          message += `

⚠️ Last free transcript! Get 5 more for $1.99: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01
🎁 Or invite friends: /referral`;
        } else if (newCreditsRemaining === 2) {
          message += `

💡 Only 2 free transcripts left! 
🚀 Get 5 more for $1.99: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01`;
        }

        message += `

💬 Share with friends who'd love this!
📱 Send link: https://share.scribetok.com/v/${insertedTask.task_id}
🎁 Want free credits? Text /referral for your sharing link!`;

        await sendSMS(From, message);
        return sendTwilioResponse('✅ YouTube transcript complete! Check your texts for details.');
      } catch (err) {
        console.error('YouTube RapidAPI error:', err);
        return sendTwilioResponse('❌ Failed to transcribe YouTube video. Try again later.');
      }
    }
    // Don't create a database record here - let the main API handle it
    // The main API will create the proper task record with background processing
    // Just send simple Twilio acknowledgment - let backend handle SMS notifications
    const initialResponse = sendTwilioResponse('👍 Got it! Processing your video...');
    // Call Render service to start processing (async, don't wait)
    setTimeout(async ()=>{
      try {
        const baseUrl = Deno.env.get('RENDER_SERVICE_URL') || '';
        const renderApiUrl = `${baseUrl.replace(/\/$/, '')}/api/public/transcribe`;
        console.log('Calling Render API:', renderApiUrl);
        const transcribeResponse = await fetch(renderApiUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'User-Agent': 'Supabase-Edge-Function',
            'X-API-Key': Deno.env.get('RENDER_API_KEY') || 'f8a9b1e2-c5d4-4e5f-8d7b-1c2d3e4f5a6b'
          },
          body: JSON.stringify({
            url: url,
            user_phone: normalizePhoneNumber(From) // Pass phone number for SMS notification
          })
        });
        const responseText = await transcribeResponse.text();
        console.log('Render API response:', transcribeResponse.status, responseText);
        if (!transcribeResponse.ok) {
          console.error('Render API failed:', transcribeResponse.status, responseText);
        } else {
          // Try to extract task_id and start polling (non-blocking, no double-send)
          try {
            const parsed = JSON.parse(responseText);
            const taskId = parsed?.task_id;
            if (taskId) {
              pollForCompletion(taskId, From);
            }
          } catch (e) {
            console.warn('Could not parse transcribe response JSON:', e);
          }
        }
      } catch (apiError) {
        console.error('Failed to call Render API:', apiError);
      }
    }, 0);
    // Backend will handle SMS notification when transcription completes
    console.log(`Transcription queued for phone ${From}`);
    return initialResponse;
  } catch (err) {
    console.error('Unexpected error:', err);
    return sendTwilioResponse('🚨 An unexpected error occurred. Please try again.');
  }
});
