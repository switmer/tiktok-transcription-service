import { createClient } from 'npm:@supabase/supabase-js@2.39.3';

// XML escape function for TwiML responses - prevents XML parsing errors from & and < characters
function escapeXml(str: string): string {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

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
  // Strict: reject anything we can't safely normalize (prevents fragmented identities)
  return null;
}
function generateOTPCode() {
  // Legacy fallback; primary OTP is issued by DB RPC `request_otp`.
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  const n = (buf[0] % 900000) + 100000;
  return String(n).padStart(6, '0');
}
function generateSessionToken() {
  return crypto.randomUUID().replace(/-/g, '');
}
// Rate limiting function
async function checkRateLimit(phoneNumber, supabase) {
  const normalizedPhone = normalizePhoneNumber(phoneNumber);
  if (!normalizedPhone) return false; // fail closed for abuse protection
  const oneMinuteAgo = new Date(Date.now() - 60000).toISOString();
  try {
    // Check for recent commands from this phone number
    const { data: recentMessages, error } = await supabase.from('user_messages').select('id').eq('from_phone', normalizedPhone).gte('created_at', oneMinuteAgo);
    if (error) {
      console.log('Rate limit check failed:', error);
      return false; // Fail closed on error
    }
    // Allow max 5 commands per minute
    return (recentMessages?.length || 0) < 5;
  } catch (error) {
    console.log('Rate limit check error:', error);
    return false; // Fail closed on error
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
  const user = await getOrCreateSMSUser(phoneNumber, supabase);
  if (!user) return { success: false, error: 'otp_failed' };

  const normalized = normalizePhoneNumber(phoneNumber);
  if (!normalized) return { success: false, error: 'otp_failed' };

  const { data, error } = await supabase.rpc('request_otp', { p_phone_e164: normalized });
  if (error) {
    const message = error?.message || '';
    const code = error?.code || '';
    if (code === 'P0001' || code === '42501' || /OTP not configured/i.test(message)) {
      console.error('OTP service unavailable:', error);
      return { success: false, error: 'otp_unavailable' };
    }
    console.error('request_otp RPC failed:', error);
    return { success: false, error: 'otp_failed' };
  }
  const row = Array.isArray(data) ? data[0] : data;
  if (!row?.success || !row?.code) {
    console.warn('request_otp returned failure:', row);
    return { success: false, error: 'otp_failed' };
  }

  await sendSMS(normalized, `Your ScribeTok code: ${row.code}\n\nEnter: /verify ${row.code}`);
  return { success: true };
}
async function verifyOTP(phoneNumber, code, supabase) {
  const normalizedPhone = normalizePhoneNumber(phoneNumber);
  if (!normalizedPhone) return { success: false };

  const { data, error } = await supabase.rpc('verify_otp', {
    p_phone_e164: normalizedPhone,
    p_code: code
  });
  if (error) {
    const message = error?.message || '';
    const errorCode = error?.code || '';
    if (errorCode === 'P0001' || errorCode === '42501' || /OTP not configured/i.test(message)) {
      console.error('OTP service unavailable:', error);
      return { success: false, error: 'otp_unavailable' };
    }
    console.error('verify_otp RPC failed:', error);
    return { success: false };
  }
  const ok = Boolean(data?.success);
  if (!ok) return { success: false };

  // Fetch user id for existing API shape
  const { data: user } = await supabase.from('sms_users').select('id').eq('phone_number', normalizedPhone).single();
  return {
    success: true,
    sessionToken: data.session_token,
    userId: user?.id
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

    // Truncate title to prevent bloat
    const shortTitle = truncateTitle(title, 50);
    const shareUrl = `https://share.scribetok.com/v/${taskId}`;

    // Build a compact message that stays under SMS limits
    // Target: ~500 chars to avoid error 30019 (carrier limit exceeded)
    const header = `Ready: "${shortTitle}"\n\n`;
    const footer = `\n\n${shareUrl}\n/full for more | /tldr to regenerate\n${creditsRemaining} credits left`;

    // Calculate available space for transcript preview
    const availableChars = SMS_SAFE_CHARS - header.length - footer.length;
    const shortTranscript = truncateForSMS(transcript, Math.max(availableChars, 150));

    let message = `${header}${shortTranscript}${footer}`;

    // Only add upsell for 0 credits (keep it short!)
    if (creditsRemaining === 0) {
      message += `\n\nOut of credits! 5 for $1.99: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01`;
    }

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
// SMS length helper - prevents error 30019 (content size exceeds carrier limit)
// UCS-2 encoding (emojis present) = 70 chars/segment, GSM = 160 chars/segment
// Most carriers limit concatenated SMS to ~10 segments
const SMS_MAX_CHARS = 1400;  // Safe limit for ~10 segments with UCS-2
const SMS_SAFE_CHARS = 600;   // Ideal for 8-9 segments with UCS-2
const SMS_GSM_8_SEGMENTS = 1200;  // 8 segments with GSM encoding (no emojis): 160 × 8 = 1280, with buffer

function truncateForSMS(text: string, maxChars: number = SMS_SAFE_CHARS): string {
  if (!text || text.length <= maxChars) return text;
  // Find a good break point (space, newline) near the limit
  let truncateAt = text.lastIndexOf(' ', maxChars - 3);
  if (truncateAt < maxChars * 0.5) truncateAt = maxChars - 3; // fallback if no space
  return text.substring(0, truncateAt) + '...';
}

function truncateTitle(title: string, maxLen: number = 60): string {
  if (!title || title.length <= maxLen) return title;
  return title.substring(0, maxLen - 3) + '...';
}

// Remove emojis for long messages to use GSM encoding (160 chars/segment vs 70)
function stripEmojisForLength(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]|[\u{1F600}-\u{1F64F}]|[\u{1F680}-\u{1F6FF}]|[\u{1F1E0}-\u{1F1FF}]/gu, '');
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
function isTikTokUrl(url) {
  return /(?:tiktok\.com\/@[^/]+\/video\/|tiktok\.com\/t\/|vm\.tiktok\.com\/)/i.test(url);
}
function isInstagramUrl(url) {
  return /(?:instagram\.com\/(?:reel|p|tv)\/)/i.test(url);
}
function isFacebookUrl(url) {
  return /(?:facebook\.com\/.*\/videos\/|facebook\.com\/reel\/|fb\.watch\/)/i.test(url);
}
function extractYouTubeVideoId(url) {
  // Handles watch?v=, youtu.be/, shorts/
  const match = url.match(/(?:v=|youtu\.be\/|shorts\/)([\w-]{11})/);
  return match ? match[1] : null;
}
// Create unique Stripe checkout session with phone number in metadata (one-time payment)
async function createStripeCheckoutUrl(phoneNumber: string, priceId: string, credits: number): Promise<string | null> {
  const stripeSecretKey = Deno.env.get('STRIPE_SECRET_KEY');
  if (!stripeSecretKey || !priceId) {
    console.log('Stripe not configured, cannot create checkout session');
    return null;
  }

  try {
    const frontendUrl = Deno.env.get('FRONTEND_URL') || 'https://scribetok.com';

    const params = new URLSearchParams();
    params.append('payment_method_types[]', 'card');
    params.append('line_items[0][price]', priceId);
    params.append('line_items[0][quantity]', '1');
    params.append('mode', 'payment');
    params.append('success_url', `${frontendUrl}/sms-payment-success?session_id={CHECKOUT_SESSION_ID}`);
    params.append('cancel_url', `${frontendUrl}/sms-payment-canceled`);
    params.append('metadata[phone_number]', phoneNumber);
    params.append('metadata[credits]', String(credits));
    params.append('metadata[source]', 'sms_out_of_credits');

    const response = await fetch('https://api.stripe.com/v1/checkout/sessions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${stripeSecretKey}`,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: params.toString(),
    });

    if (!response.ok) {
      const error = await response.text();
      console.error('Stripe checkout creation failed:', error);
      return null;
    }

    const session = await response.json();
    console.log(`Created Stripe checkout session ${session.id} for phone ${phoneNumber}`);
    return session.url;
  } catch (error) {
    console.error('Error creating Stripe checkout:', error);
    return null;
  }
}

// Create unique Stripe checkout session for subscription (unlimited plan)
async function createStripeSubscriptionUrl(phoneNumber: string, priceId: string): Promise<string | null> {
  const stripeSecretKey = Deno.env.get('STRIPE_SECRET_KEY');
  if (!stripeSecretKey || !priceId) {
    console.log('Stripe not configured, cannot create subscription checkout');
    return null;
  }

  try {
    const frontendUrl = Deno.env.get('FRONTEND_URL') || 'https://scribetok.com';

    const params = new URLSearchParams();
    params.append('payment_method_types[]', 'card');
    params.append('line_items[0][price]', priceId);
    params.append('line_items[0][quantity]', '1');
    params.append('mode', 'subscription');
    params.append('success_url', `${frontendUrl}/sms-subscription-success?session_id={CHECKOUT_SESSION_ID}`);
    params.append('cancel_url', `${frontendUrl}/sms-payment-canceled`);
    params.append('metadata[phone_number]', phoneNumber);
    params.append('metadata[plan]', 'unlimited');
    params.append('metadata[source]', 'sms_out_of_credits');

    const response = await fetch('https://api.stripe.com/v1/checkout/sessions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${stripeSecretKey}`,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: params.toString(),
    });

    if (!response.ok) {
      const error = await response.text();
      console.error('Stripe subscription checkout creation failed:', error);
      return null;
    }

    const session = await response.json();
    console.log(`Created Stripe subscription checkout ${session.id} for phone ${phoneNumber}`);
    return session.url;
  } catch (error) {
    console.error('Error creating Stripe subscription checkout:', error);
    return null;
  }
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
  // Note: escapeXml disabled temporarily for debugging - re-enable after testing
  const sendTwilioResponse = (message)=>new Response(`<Response><Message>${message || ''}</Message></Response>`, {
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
  let From, Body, MessageSid, To;
  const contentType = req.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    ({ From, Body, MessageSid, To } = await req.json().catch(()=>({})));
  } else {
    const form = await req.formData();
    From = form.get('From');
    Body = form.get('Body');
    MessageSid = form.get('MessageSid');
    To = form.get('To');
  }
  // Robust logging for debugging
  console.log('Received Body:', JSON.stringify(Body));
  console.log('Received From:', JSON.stringify(From));
  if (!From || !Body) {
    return sendTwilioResponse('Missing From or Body.');
  }
  const normalizedFrom = normalizePhoneNumber(String(From));
  if (!normalizedFrom) {
    return sendTwilioResponse('📱 Please send from a valid US phone number.');
  }

  // Initialize Supabase client for all commands
  const supabase = createClient(Deno.env.get('SUPABASE_URL'), Deno.env.get('SUPABASE_SERVICE_ROLE_KEY'));
  
  // Log all incoming messages to user_messages table
  try {
    const command = Body.trim().startsWith('/') ? Body.trim().split(' ')[0].toLowerCase() : null;
    const messageSid = MessageSid ? String(MessageSid) : null;

    // If Twilio retries the webhook, MessageSid will be the same. Short-circuit to avoid
    // duplicate charges and duplicate backend enqueues.
    if (messageSid) {
      const { data: existing } = await supabase
        .from('user_messages')
        .select('id')
        .eq('message_sid', messageSid)
        .limit(1);
      if (existing && existing.length > 0) {
        return sendTwilioResponse('✅ Already received — still working on it.');
      }
    }

    // Use DB-side helper to log idempotently based on MessageSid.
    await supabase.rpc('safe_message_log', {
      from_phone_param: normalizedFrom,
      to_phone_param: To ? String(To) : null,
      message_body_param: String(Body),
      direction_param: 'inbound',
      message_sid_param: messageSid,
      command_param: command
    });
  } catch (logError) {
    console.error('Error logging message to user_messages:', logError);
    // Continue processing even if logging fails
  }
  
  // Check rate limiting (max 5 commands per minute)
  const trimmed = String(Body).trim();
  const isCommand = trimmed.startsWith('/');
  const isUrl = /(https?:\/\/[^\s]+)/i.test(trimmed);
  const rateLimitOk = (isCommand || isUrl) ? await checkRateLimit(normalizedFrom, supabase) : true;
  if (!rateLimitOk) {
    console.log(`Rate limit exceeded for ${From}`);
    return sendTwilioResponse('⚠️ Too many commands. Please wait a minute before trying again.');
  }

  // Secret code for free credits (customer support / promos)
  const secretCode = Deno.env.get('FREE_CREDITS_SECRET_CODE') || '';
  if (secretCode && Body.trim().toUpperCase() === secretCode.toUpperCase()) {
    try {
      // Check if user exists, create if not
      const { data: existingUser } = await supabase
        .from('sms_users')
        .select('credits_remaining')
        .eq('phone_number', From)
        .single();

      if (existingUser) {
        // Add 10 credits to existing user
        const newCredits = (existingUser.credits_remaining || 0) + 10;
        await supabase
          .from('sms_users')
          .update({ credits_remaining: newCredits })
          .eq('phone_number', From);

        console.log(`Secret code used: Added 10 credits to ${From}, new balance: ${newCredits}`);
        return sendTwilioResponse(`🎉 Boom! 10 credits added to your account!\n\n💳 New balance: ${newCredits} credits\n\nEnjoy! 🚀`);
      } else {
        // Create new user with 10 credits
        await supabase
          .from('sms_users')
          .insert({
            phone_number: From,
            credits_remaining: 10,
            created_at: new Date().toISOString()
          });

        console.log(`Secret code used: Created new user ${From} with 10 credits`);
        return sendTwilioResponse(`🎉 Welcome! 10 credits added to your new account!\n\n💳 Balance: 10 credits\n\nText any TikTok/YouTube link to get started! 🚀`);
      }
    } catch (error) {
      console.error('Error applying secret code:', error);
      return sendTwilioResponse('❌ Something went wrong. Please try again or contact support.');
    }
  }

  // Handle commands
  if (Body.trim().toLowerCase() === '/help') {
    return sendTwilioResponse(`🤖 ScribeTok Help:

📱 Commands:
/link @handle - Connect your TikTok
/stats - View your creator dashboard
/vault - View transcripts
/chat [question] - Ask about your latest transcript
/tldr - AI summary of your latest transcript
/quote - Get the best quote from latest video
/full - See full transcript of latest video
/referral - Get your referral link for free credits
/upgrade - Buy more credits
/profile - View account info
/feedback [message] - Send feedback

💳 Credits:
• New users get 3 free transcripts
• Refer friends: Both get 3 bonus credits!

Just text any TikTok/YouTube/Instagram/Facebook link!`);
  }

  // Upgrade command - generate unique payment links
  if (Body.trim().toLowerCase() === '/upgrade') {
    // Get user's current credits
    let currentCredits = 0;
    try {
      const { data: userData } = await supabase
        .from('sms_users')
        .select('credits_remaining')
        .eq('phone_number', From)
        .single();
      currentCredits = userData?.credits_remaining || 0;
    } catch (e) {
      console.log('Could not fetch user credits for upgrade command');
    }

    // Generate unique checkout URLs with phone number in metadata
    const fiveCreditsPrice = Deno.env.get('STRIPE_5_CREDITS_PRICE_ID') || '';
    const tenCreditsPrice = Deno.env.get('STRIPE_SMS_CREDITS_PRICE_ID') || '';
    const unlimitedPrice = Deno.env.get('STRIPE_UNLIMITED_PRICE_ID') || '';

    const fiveCreditsUrl = await createStripeCheckoutUrl(From, fiveCreditsPrice, 5);
    const tenCreditsUrl = await createStripeCheckoutUrl(From, tenCreditsPrice, 10);
    const unlimitedUrl = await createStripeSubscriptionUrl(From, unlimitedPrice);

    // Build message with available options
    let message = `💳 Current Credits: ${currentCredits}\n\n🎯 Buy More Credits:\n`;

    if (fiveCreditsUrl) {
      message += `• 5 credits for $1.99: ${fiveCreditsUrl}\n`;
    }
    if (tenCreditsUrl) {
      message += `• 10 credits for $4.75: ${tenCreditsUrl}\n`;
    }
    if (unlimitedUrl) {
      message += `• Unlimited for $6.75/mo: ${unlimitedUrl}\n`;
    }

    // Fallback if no Stripe configured
    if (!fiveCreditsUrl && !tenCreditsUrl && !unlimitedUrl) {
      message = `💳 Current Credits: ${currentCredits}\n\n⚠️ Payment links temporarily unavailable. Please try again later or contact support.`;
    } else {
      message += `\n✨ Credits are instantly added after purchase!\n🎁 Or text /referral to earn free credits!`;
    }

    return sendTwilioResponse(message);
  }

  // Login command - send OTP
  if (Body.trim().toLowerCase() === '/login') {
    const result = await sendOTP(From, supabase);
    if (result?.success) {
      return sendTwilioResponse('📱 Check your texts! Enter the 6-digit code like this:\n\n/verify 123456');
    }
    if (result?.error === 'otp_unavailable') {
      return sendTwilioResponse('⚠️ SMS login is temporarily unavailable. Please try again later.');
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
    }
    if (result.error === 'otp_unavailable') {
      return sendTwilioResponse('⚠️ SMS login is temporarily unavailable. Please try again later.');
    } else {
      return sendTwilioResponse('❌ Invalid or expired code. Try /login to get a new one.');
    }
  }
  // Chat command - ask a question about the latest transcript
  if (Body.trim().toLowerCase().startsWith('/chat')) {
    const question = Body.trim().substring(5).trim();
    if (!question) {
      return sendTwilioResponse('💬 Ask a question like:\n\n/chat What is the main point?');
    }
    try {
      const baseUrl = Deno.env.get('RENDER_SERVICE_URL') || '';
      const renderApiUrl = `${baseUrl.replace(/\/$/, '')}/api/sms/chat`;
      const chatResponse = await fetch(renderApiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Supabase-Edge-Function',
          'X-API-Key': Deno.env.get('RENDER_API_KEY') || 'f8a9b1e2-c5d4-4e5f-8d7b-1c2d3e4f5a6b'
        },
        body: JSON.stringify({
          phone: normalizePhoneNumber(From),
          message: question
        })
      });

      if (chatResponse.ok) {
        const result = await chatResponse.json();
        return sendTwilioResponse(result.answer || 'I\'m not sure how to answer that.');
      }
      if (chatResponse.status === 404) {
        return sendTwilioResponse('📄 No completed transcripts found yet. Send a video link first!');
      }
      if (chatResponse.status === 409) {
        return sendTwilioResponse('⏳ Your latest transcript is still processing. Try again in a moment.');
      }

      console.error('Chat API failed:', chatResponse.status, await chatResponse.text());
      return sendTwilioResponse('❌ Couldn\'t answer that right now. Try again later.');
    } catch (error) {
      console.error('Chat command error:', error);
      return sendTwilioResponse('❌ Couldn\'t answer that right now. Try again later.');
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

  // Admin Stats command (admin only)
  if (Body.trim().toLowerCase() === '/adminstats' || Body.trim().toLowerCase() === '/admin') {
    // Admin phone numbers
    const ADMIN_PHONES = ['+16103244250'];
    if (!ADMIN_PHONES.includes(normalizedFrom)) {
      return sendTwilioResponse('Unknown command. Text /help for options.');
    }

    try {
      // Call Python backend for admin stats
      const baseUrl = Deno.env.get('RENDER_SERVICE_URL') || '';
      const apiKey = Deno.env.get('RENDER_API_KEY') || '';
      const statsResponse = await fetch(`${baseUrl.replace(/\/$/, '')}/api/admin/stats?period=month`, {
        method: 'GET',
        headers: {
          'X-API-Key': apiKey,
          'User-Agent': 'Supabase-Edge-Function'
        }
      });

      if (!statsResponse.ok) {
        console.error('Admin stats API failed:', statsResponse.status);
        return sendTwilioResponse('Error fetching admin stats. Try again later.');
      }

      const stats = await statsResponse.json();
      const f = stats.financials || {};
      const u = stats.users || {};
      const usage = stats.usage || {};

      const revenue = (f.revenue_cents || 0) / 100;
      const costs = (f.costs_cents || 0) / 100;
      const profit = (f.profit_cents || 0) / 100;
      const margin = f.margin_percent || 0;

      const message = `ADMIN STATS (Month)
====================
FINANCIALS
Revenue: $${revenue.toFixed(2)}
Costs: $${costs.toFixed(2)}
Profit: $${profit.toFixed(2)} (${margin}%)

USERS
Total: ${u.total || 0}
Active: ${u.active || 0}
New: ${u.new || 0}
Paid: ${u.paid || 0} (${u.conversion_rate || 0}%)

USAGE
Transcriptions: ${usage.transcriptions || 0}
Success: ${usage.success_rate || 0}%`;

      return sendTwilioResponse(message);
    } catch (error) {
      console.error('Admin stats error:', error);
      return sendTwilioResponse('Error fetching admin stats. Try again later.');
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

  // Link TikTok account command
  if (Body.trim().toLowerCase().startsWith('/link')) {
    try {
      const input = Body.trim().substring(5).trim(); // Remove '/link '

      if (!input) {
        return sendTwilioResponse(`🔗 Link your TikTok account:

/link @yourhandle
or
/link https://tiktok.com/@yourhandle

Once linked, use /stats to see your creator dashboard!`);
      }

      // Call the database function to link the TikTok profile
      const { data, error } = await supabase.rpc('link_tiktok_profile', {
        p_user_phone: normalizedFrom,
        p_handle_or_url: input
      });

      if (error) {
        console.error('Error linking TikTok profile:', error);
        if (error.message?.includes('Invalid')) {
          return sendTwilioResponse(`❌ Invalid TikTok handle or URL.

Try:
/link @yourhandle
/link https://tiktok.com/@yourhandle`);
        }
        return sendTwilioResponse('❌ Error linking account. Try again later.');
      }

      const linkedHandle = data?.tiktok_handle || input.replace(/^@/, '');

      return sendTwilioResponse(`🔗 Success! Your TikTok account @${linkedHandle} has been linked to ScribeTok.

You can now use /stats to see your creator dashboard!`);
    } catch (error) {
      console.error('Link command error:', error);
      return sendTwilioResponse('❌ Error linking account. Try again later.');
    }
  }

  // Stats command - creator dashboard
  if (Body.trim().toLowerCase() === '/stats') {
    try {
      // Call the database function to get creator stats
      const { data: stats, error } = await supabase.rpc('get_user_creator_stats', {
        p_user_phone: normalizedFrom
      });

      if (error) {
        console.error('Error fetching creator stats:', error);
        return sendTwilioResponse('❌ Error loading stats. Try again later.');
      }

      if (!stats) {
        return sendTwilioResponse('📊 No stats yet! Send a video link to get started.');
      }

      // Format the stats into a readable SMS message
      const totalTranscribed = stats.total_transcribed || 0;
      const creditsRemaining = stats.credits_remaining || 0;
      const freeCreditsUsed = stats.free_credits_used || 0;
      const freeRemaining = Math.max(0, 3 - freeCreditsUsed);
      const totalReferrals = stats.total_referrals || 0;
      const referralCredits = stats.total_referral_credits || 0;
      const tiktokHandle = stats.tiktok_handle;
      const joinedDate = stats.joined_date ? new Date(stats.joined_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : 'Unknown';

      let message = `📊 Your ScribeTok Creator Stats

🎥 ${totalTranscribed} videos transcribed
💳 ${creditsRemaining} credits (${freeRemaining} free remaining)`;

      if (totalReferrals > 0) {
        message += `\n🎁 ${totalReferrals} friends referred (+${referralCredits} bonus credits)`;
      }

      if (tiktokHandle) {
        message += `\n🔗 Linked: @${tiktokHandle}`;
      } else {
        message += `\n🔗 No TikTok linked - use /link @handle`;
      }

      message += `\n📅 Member since: ${joinedDate}`;

      // Add most popular video if available
      if (stats.most_popular_video?.title) {
        const views = stats.most_popular_video.views;
        const viewsFormatted = views >= 1000000
          ? `${(views / 1000000).toFixed(1)}M`
          : views >= 1000
            ? `${(views / 1000).toFixed(0)}K`
            : views;
        message += `\n🏆 Top video: "${truncateTitle(stats.most_popular_video.title, 30)}" (${viewsFormatted} views)`;
      }

      message += `\n\nText /referral for free credits!`;

      return sendTwilioResponse(message);
    } catch (error) {
      console.error('Stats command error:', error);
      return sendTwilioResponse('❌ Error loading stats. Try again later.');
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
      // Fetch the most recent *completed* transcript for this phone.
      // The latest row can be pending/processing (no transcript yet), which made /full feel broken.
      const normalized = normalizePhoneNumber(From);
      const { data: transcripts, error } = await supabase
        .from('transcriptions')
        .select('task_id, title, transcript, status, created_at')
        .eq('user_phone', normalized)
        .eq('status', 'completed')
        .not('transcript', 'is', null)
        .order('created_at', { ascending: false })
        .limit(1);
      
      if (error || !transcripts || transcripts.length === 0) {
        // If they have an in-flight job, let them know rather than claiming nothing exists.
        const { data: inFlight } = await supabase
          .from('transcriptions')
          .select('task_id,status,created_at')
          .eq('user_phone', normalized)
          .in('status', ['pending', 'processing'])
          .order('created_at', { ascending: false })
          .limit(1);
        if (inFlight && inFlight.length > 0) {
          await sendSMS(From, `📄 Your latest transcript is still processing.\n\n🔗 https://share.scribetok.com/v/${inFlight[0].task_id}`);
          return sendTwilioResponse('');
        }

        await sendSMS(From, '📄 No completed transcripts found yet. Send a video link first!');
        return sendTwilioResponse('');
      }

      const latest = transcripts[0];

      // Truncate title to avoid bloating the message
      const title = truncateTitle(latest.title || 'Video', 50);
      const shareUrl = `https://share.scribetok.com/v/${latest.task_id}`;

      // For /full we strip emojis to use GSM encoding (160 chars/segment vs 70)
      // This lets us fit ~1200 chars in 8 segments instead of ~560
      const cleanTranscript = stripEmojisForLength(latest.transcript || '');
      const cleanTitle = stripEmojisForLength(title);

      const baseMessage = `Full transcript: "${cleanTitle}"\n\n`;
      const footer = `\n\nFull version: ${shareUrl}`;
      const availableChars = SMS_GSM_8_SEGMENTS - baseMessage.length - footer.length;

      // Truncate transcript content to fit (~1100 chars of actual content)
      const truncatedTranscript = truncateForSMS(cleanTranscript, Math.max(availableChars, 200));

      const message = `${baseMessage}${truncatedTranscript}${footer}`;
      
      await sendSMS(From, message);
      return sendTwilioResponse('');
    } catch (error) {
      console.error('Full transcript error:', error);
      await sendSMS(From, '📄 Error loading transcript. Try again later!');
      return sendTwilioResponse('');
    }
  }

  // Reset chat command
  if (Body.trim().toLowerCase() === '/reset') {
    try {
      const baseUrl = Deno.env.get('RENDER_SERVICE_URL') || '';
      const renderApiUrl = `${baseUrl.replace(/\/$/, '')}/api/sms/chat/reset`;
      const resetResponse = await fetch(renderApiUrl, {
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

      if (resetResponse.ok) {
        return sendTwilioResponse('✅ Chat reset. Ask a new question whenever you\'re ready.');
      }
      console.error('Chat reset failed:', resetResponse.status, await resetResponse.text());
      return sendTwilioResponse('❌ Couldn\'t reset chat right now. Try again later.');
    } catch (error) {
      console.error('Chat reset error:', error);
      return sendTwilioResponse('❌ Couldn\'t reset chat right now. Try again later.');
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
    try {
      const baseUrl = Deno.env.get('RENDER_SERVICE_URL') || '';
      const renderApiUrl = `${baseUrl.replace(/\/$/, '')}/api/sms/chat`;
      const chatResponse = await fetch(renderApiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Supabase-Edge-Function',
          'X-API-Key': Deno.env.get('RENDER_API_KEY') || 'f8a9b1e2-c5d4-4e5f-8d7b-1c2d3e4f5a6b'
        },
        body: JSON.stringify({
          phone: normalizePhoneNumber(From),
          message: Body.trim()
        })
      });

      if (chatResponse.ok) {
        const result = await chatResponse.json();
        return sendTwilioResponse(result.answer || 'I\'m not sure how to answer that.');
      }

      if (chatResponse.status === 404) {
        return sendTwilioResponse('📄 No completed transcripts found yet. Send a video link first!');
      }
      if (chatResponse.status === 409) {
        return sendTwilioResponse('⏳ Your latest transcript is still processing. Try again in a moment.');
      }

      console.error('Chat API failed:', chatResponse.status, await chatResponse.text());
      return sendTwilioResponse('👀 That doesn\'t look like a link. Try again or type /help.');
    } catch (error) {
      console.error('Chat error:', error);
      return sendTwilioResponse('👀 That doesn\'t look like a link. Try again or type /help.');
    }
  }
  // Use the first matched URL
  const url = match[0];
  if (!isYouTubeUrl(url) && !isTikTokUrl(url) && !isInstagramUrl(url) && !isFacebookUrl(url)) {
    return sendTwilioResponse(
      "⚠️ We currently support TikTok, YouTube, Instagram, and Facebook links. Send one of those and I’ll transcribe it!"
    );
  }
  try {
    // Get or create SMS user and check credits
    const smsUser = await getOrCreateSMSUser(normalizedFrom, supabase);
    if (!smsUser) {
      return sendTwilioResponse('❌ Error creating user account. Try again later.');
    }

    // Dedupe: if this phone already sent this exact URL before, don't charge twice.
    // Note: This is an exact-string match. TikTok shortlinks can vary; a stronger
    // dedupe could normalize by video_id once we resolve it.
    // normalizedFrom was already computed and validated above
    let isFreeRetry = false; // Track if this is a free retry of a failed task
    try {
      const { data: existingTasks, error: existingError } = await supabase
        .from('transcriptions')
        .select('task_id,status,title,created_at')
        .eq('user_phone', normalizedFrom)
        .eq('url', url)
        .order('created_at', { ascending: false })
        .limit(1);

      if (existingError) {
        console.warn('Dedupe lookup failed; proceeding with normal flow:', existingError);
      } else if (existingTasks && existingTasks.length > 0) {
        const existing = existingTasks[0];
        const existingTitle = existing.title || 'that video';

        if (existing.status === 'completed') {
          return sendTwilioResponse(
            `✅ Already transcribed ${existingTitle}.\n\n` +
              `🔗 https://share.scribetok.com/v/${existing.task_id}\n` +
              `💳 Credits remaining: ${smsUser.credits_remaining ?? 0}`
          );
        }

        // If it's already in-flight, don't create a new task or charge again.
        if (existing.status === 'pending' || existing.status === 'processing') {
          return sendTwilioResponse(
            `⏳ That link is already being processed.\n\n` +
              `I'll text you when it's ready.\n` +
              `💳 Credits remaining: ${smsUser.credits_remaining ?? 0}`
          );
        }

        // If the previous attempt failed, allow a free retry
        if (existing.status === 'failed' || existing.status === 'error') {
          console.log(`Free retry for previously failed task ${existing.task_id} (status: ${existing.status})`);
          isFreeRetry = true;
          // Continue to normal processing flow - don't return, just flag for free retry
        }
      }
    } catch (dedupeErr) {
      console.warn('Dedupe check error; proceeding with normal flow:', dedupeErr);
    }

    // Check if user has credits remaining (pre-check for UX; actual deduction happens after enqueue)
    // Skip credit check for free retries of failed tasks
    const creditsRemaining = smsUser.credits_remaining || 0;
    if (creditsRemaining <= 0 && !isFreeRetry) {
      // Generate unique checkout URLs with phone number in metadata
      const fiveCreditsPrice = Deno.env.get('STRIPE_5_CREDITS_PRICE_ID') || '';
      const unlimitedPrice = Deno.env.get('STRIPE_UNLIMITED_PRICE_ID') || '';

      // Create unique checkout links for this user
      const fiveCreditsUrl = await createStripeCheckoutUrl(From, fiveCreditsPrice, 5);
      const unlimitedUrl = await createStripeSubscriptionUrl(From, unlimitedPrice);

      // Fallback to static links if Stripe checkout creation fails
      const buyLink = fiveCreditsUrl || 'https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01';
      const unlimitedLink = unlimitedUrl || 'https://buy.stripe.com/6oUeVcgEIfib3x84WG6Vq02';

      return sendTwilioResponse(`💳 You've used all your free transcripts!

Get 5 more for just $1.99 - cheaper than 1 jukebox song!
🚀 Buy now: ${buyLink}

🎁 Or invite friends for 3 free credits each: /referral
💻 Go unlimited for $6.75/month: ${unlimitedLink}`);
    }

    // We only deduct credits AFTER the backend successfully queues the job.
    // This avoids charging if the downstream call fails.
    let newCreditsRemaining = creditsRemaining;
    if (isYouTubeUrl(url)) {
      const videoId = extractYouTubeVideoId(url);
      try {
        const transcriptData = await fetchYouTubeTranscript(url, videoId);
        const transcript = transcriptData?.transcript || '';
        const title = transcriptData?.title || '';
        const description = transcriptData?.description || '';

        // Validate we got meaningful data back
        // Priority: transcript > substantial description > fail
        const hasTranscript = transcript && transcript.trim().length > 0;
        const hasTitle = title && title.trim().length > 0;
        // Consider description "substantial" if it's at least 100 chars (not just "Check out my links!")
        const hasSubstantialDescription = description && description.trim().length >= 100;

        // Determine what content to use
        let finalTranscript = transcript;
        let contentSource = 'transcript';

        if (!hasTranscript) {
          if (hasSubstantialDescription) {
            // Use description as the content - video may have no audio but good description
            console.log('No transcript but has substantial description, using that:', videoId);
            finalTranscript = `[Video Description]\n\n${description.trim()}`;
            contentSource = 'description';
          } else if (!hasTitle) {
            // Got nothing - complete API failure
            console.error('YouTube API returned no data for video:', videoId, transcriptData);
            throw new Error('Failed to fetch video data - API returned empty response');
          } else {
            // Has title but no transcript and no substantial description
            console.error('YouTube video has no usable content:', videoId);
            throw new Error('No transcript or description available for this video');
          }
        }

        // Store in Supabase as completed
        const tags = ['sms-inbound', 'youtube'];
        if (contentSource === 'description') {
          tags.push('from-description'); // Flag that content came from description, not audio
        }

        const { data: insertedTask, error } = await supabase.from('transcriptions').insert({
          url: url,
          status: 'completed',
          tags: tags,
          category: 'youtube-transcription',
          title: title || null,
          description: description || null,
          user_phone: From,
          user_id: null,
          transcript: finalTranscript
        }).select('task_id').single();
        if (error) {
          console.error('Supabase insert error:', error);
          return sendTwilioResponse('⚠️ Error saving your YouTube transcript. Try again.');
        }
        // Send SMS with transcript preview - keep compact to avoid error 30019
        const shortTitle = truncateTitle(title || 'Video', 50);
        const shareUrl = `https://share.scribetok.com/v/${insertedTask.task_id}`;

        const contentLabel = contentSource === 'description' ? 'Description' : 'YouTube ready';
        const header = `${contentLabel}: "${shortTitle}"\n\n`;
        const footer = `\n\n${shareUrl}\n/full for more | /tldr to regenerate\n${newCreditsRemaining} credits left`;

        const availableChars = SMS_SAFE_CHARS - header.length - footer.length;
        const shortTranscript = truncateForSMS(finalTranscript, Math.max(availableChars, 150));

        let message = `${header}${shortTranscript}${footer}`;

        // Only add upsell for 0 credits
        if (newCreditsRemaining === 0) {
          message += `\n\nOut of credits! 5 for $1.99: https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01`;
        }

        await sendSMS(From, message);
        return sendTwilioResponse('✅ YouTube transcript complete! Check your texts for details.');
      } catch (err) {
        console.error('YouTube RapidAPI error:', err);
        return sendTwilioResponse('❌ Failed to transcribe YouTube video. Try again later.');
      }
    }
    // Call Render service to start processing (synchronously, with timeout).
    // Runtimes may freeze after response; setTimeout fire-and-forget is risky.
    try {
      const baseUrl = Deno.env.get('RENDER_SERVICE_URL') || '';
      const renderApiUrl = `${baseUrl.replace(/\/$/, '')}/api/public/transcribe`;
      console.log('Calling Render API:', renderApiUrl);

      const apiKey = Deno.env.get('RENDER_API_KEY') || '';
      if (!apiKey) {
        console.error('Missing RENDER_API_KEY; refusing to enqueue transcription');
        return sendTwilioResponse('⚠️ Service misconfigured. Please try again later.');
      }

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);

      const transcribeResponse = await fetch(renderApiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Supabase-Edge-Function',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({
          url,
          user_phone: normalizedFrom,
        }),
        signal: controller.signal,
      }).finally(() => clearTimeout(timeout));

      const responseText = await transcribeResponse.text();
      console.log('Render API response:', transcribeResponse.status, responseText);

      if (!transcribeResponse.ok) {
        return sendTwilioResponse('⚠️ Couldn’t start processing. Try again in a minute.');
      }

      // Charge one credit now that the job is successfully queued.
      // Skip credit deduction for free retries of failed tasks
      if (!isFreeRetry) {
        try {
          const { data: creditResult, error: creditError } = await supabase.rpc('atomic_credit_transaction', {
            user_phone_param: normalizedFrom,
            credit_change: -1,
            transaction_type: 'transcription',
            description: 'SMS transcription',
            metadata: { url, message_sid: MessageSid ? String(MessageSid) : null },
          });
          if (creditError) {
            console.error('Credit deduction RPC failed:', creditError);
          } else if (creditResult?.success === false) {
            console.warn('Insufficient credits at deduction time:', creditResult);
            // We already queued the job; do not block delivery, but tell user their balance is low.
          } else if (typeof creditResult?.new_balance === 'number') {
            newCreditsRemaining = creditResult.new_balance;
          }
        } catch (e) {
          console.error('Credit deduction exception:', e);
        }
      } else {
        console.log(`Free retry - skipping credit deduction for ${normalizedFrom}`);
      }

      console.log(`Transcription queued for phone ${normalizedFrom}${isFreeRetry ? ' (free retry)' : ''}`);
      if (isFreeRetry) {
        return sendTwilioResponse(`🔄 Retrying (free)! Last attempt failed.\n💳 ${creditsRemaining} credits`);
      }
      return sendTwilioResponse(`👍 Got it! Processing your video...\n💳 ${newCreditsRemaining} left`);
    } catch (apiError) {
      console.error('Failed to call Render API:', apiError);
      return sendTwilioResponse('⚠️ Couldn’t start processing. Try again in a minute.');
    }
  } catch (err) {
    console.error('Unexpected error:', err);
    return sendTwilioResponse('🚨 An unexpected error occurred. Please try again.');
  }
});
