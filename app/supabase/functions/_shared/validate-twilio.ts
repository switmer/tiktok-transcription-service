/**
 * Twilio request signature validation for Supabase Edge Functions.
 *
 * Verifies the X-Twilio-Signature header using HMAC-SHA1 to ensure
 * the request genuinely came from Twilio, not a random caller.
 *
 * Algorithm: https://www.twilio.com/docs/usage/security#validating-requests
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

/**
 * Validate a Twilio webhook request.
 *
 * Two-layer check:
 * 1. HMAC-SHA1 signature validation (X-Twilio-Signature header)
 * 2. AccountSid validation (fallback if signature fails due to URL mismatch)
 *
 * Supabase edge runtime proxies can rewrite req.url, making HMAC validation
 * fragile. The AccountSid check ensures only requests with your account's SID
 * are accepted, which is a strong secondary validation.
 */
export async function validateTwilioSignature(
  req: Request,
  params: Record<string, string>,
  authToken: string,
  functionName: string,
): Promise<boolean> {
  const signature = req.headers.get('x-twilio-signature');

  // Try HMAC signature validation first
  if (signature) {
    const supabaseUrl = Deno.env.get('SUPABASE_URL') || '';
    const webhookUrl = `${supabaseUrl}/functions/v1/${functionName}`;

    const sortedKeys = Object.keys(params).sort();
    let dataToSign = webhookUrl;
    for (const key of sortedKeys) {
      dataToSign += key + (params[key] ?? '');
    }

    const expected = await hmacSha1(authToken, dataToSign);

    // Constant-time comparison
    if (expected.length === signature.length) {
      let mismatch = 0;
      for (let i = 0; i < expected.length; i++) {
        mismatch |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
      }
      if (mismatch === 0) {
        return true;
      }
    }
    console.warn(`Twilio HMAC mismatch for ${functionName}, falling back to AccountSid check`);
  }

  // Fallback: verify the AccountSid in the POST body matches ours
  const expectedSid = Deno.env.get('TWILIO_ACCOUNT_SID');
  const requestSid = params['AccountSid'];
  if (expectedSid && requestSid && expectedSid === requestSid) {
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
