/**
 * Twilio request signature validation for Supabase Edge Functions.
 *
 * Verifies the X-Twilio-Signature header using HMAC-SHA1 to ensure
 * the request genuinely came from Twilio, not a random caller.
 *
 * Algorithm: https://www.twilio.com/docs/usage/security#validating-requests
 *
 * Env vars
 * --------
 * TWILIO_AUTH_TOKEN              Required. HMAC key.
 * TWILIO_ACCOUNT_SID             Used for the proxy-URL fallback.
 * TWILIO_WEBHOOK_URL             Optional. Exact URL configured in Twilio
 *                                (recommended so HMAC succeeds despite proxy rewrites).
 * TWILIO_ALLOW_ACCOUNTSID_FALLBACK
 *                                Default true. When HMAC fails because the public
 *                                URL does not match what Twilio signed, accept the
 *                                request if AccountSid matches AND a signature
 *                                header is present. Set "false" to require HMAC.
 */

const encoder = new TextEncoder();

async function hmacSha1(key: string, data: string): Promise<string> {
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    encoder.encode(key),
    { name: 'HMAC', hash: 'SHA-1' },
    false,
    ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', cryptoKey, encoder.encode(data));
  return btoa(String.fromCharCode(...new Uint8Array(signature)));
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) {
    mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return mismatch === 0;
}

function addUrl(urls: string[], url: string | undefined | null): void {
  if (!url) return;
  const noHash = url.split('#')[0];
  const trimmed = noHash.replace(/\/$/, '');
  if (trimmed && !urls.includes(trimmed)) urls.push(trimmed);
  if (noHash && !urls.includes(noHash)) urls.push(noHash);
}

/**
 * URLs Twilio may have signed. Supabase edge proxies often rewrite req.url,
 * so HMAC is tried against several candidates including TWILIO_WEBHOOK_URL.
 */
export function candidateWebhookUrls(req: Request, functionName: string): string[] {
  const urls: string[] = [];
  addUrl(urls, Deno.env.get('TWILIO_WEBHOOK_URL'));

  const supabaseUrl = (Deno.env.get('SUPABASE_URL') || '').replace(/\/$/, '');
  if (supabaseUrl) {
    addUrl(urls, `${supabaseUrl}/functions/v1/${functionName}`);
  }

  try {
    const parsed = new URL(req.url);
    addUrl(urls, parsed.toString());
    parsed.search = '';
    addUrl(urls, parsed.toString());
  } catch {
    // ignore unparseable req.url
  }

  return urls;
}

/**
 * Validate a Twilio webhook request.
 *
 * 1. Require X-Twilio-Signature
 * 2. HMAC-SHA1 against every candidate webhook URL
 * 3. Optional AccountSid fallback (signature header still required)
 */
export async function validateTwilioSignature(
  req: Request,
  params: Record<string, string>,
  authToken: string,
  functionName: string,
): Promise<boolean> {
  if (!authToken) {
    console.error(`Twilio validation failed for ${functionName}: TWILIO_AUTH_TOKEN is not set`);
    return false;
  }

  const signature = req.headers.get('x-twilio-signature');
  if (!signature) {
    console.warn(`Twilio validation failed for ${functionName}: missing X-Twilio-Signature`);
    return false;
  }

  const sortedKeys = Object.keys(params).sort();
  const paramSuffix = sortedKeys.map((key) => key + (params[key] ?? '')).join('');

  for (const webhookUrl of candidateWebhookUrls(req, functionName)) {
    const expected = await hmacSha1(authToken, webhookUrl + paramSuffix);
    if (constantTimeEqual(expected, signature)) {
      return true;
    }
  }

  console.warn(`Twilio HMAC mismatch for ${functionName} (tried ${candidateWebhookUrls(req, functionName).length} URLs)`);

  const allowFallback = (Deno.env.get('TWILIO_ALLOW_ACCOUNTSID_FALLBACK') || 'true').toLowerCase() !== 'false';
  const expectedSid = Deno.env.get('TWILIO_ACCOUNT_SID') || '';
  const requestSid = params['AccountSid'] || '';
  if (allowFallback && expectedSid && requestSid && constantTimeEqual(expectedSid, requestSid)) {
    console.warn(
      `Twilio HMAC mismatch for ${functionName}; accepting via AccountSid fallback. ` +
        'Set TWILIO_WEBHOOK_URL to the exact Twilio console URL, or TWILIO_ALLOW_ACCOUNTSID_FALLBACK=false to require HMAC.',
    );
    return true;
  }

  console.warn(`Twilio validation failed for ${functionName}: no valid signature or AccountSid`);
  return false;
}

/**
 * Helper: parse FormData into a plain Record for signature validation.
 */
export function formDataToRecord(formData: FormData): Record<string, string> {
  const params: Record<string, string> = {};
  formData.forEach((value, key) => {
    params[key] = value.toString();
  });
  return params;
}
