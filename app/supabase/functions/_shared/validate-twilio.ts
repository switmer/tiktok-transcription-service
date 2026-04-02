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
 * Validate a Twilio webhook request signature.
 *
 * @param req     - The incoming Request object
 * @param params  - The parsed form data as a plain object (key-value pairs)
 * @param authToken - Your Twilio Auth Token
 * @returns true if the signature is valid
 */
export async function validateTwilioSignature(
  req: Request,
  params: Record<string, string>,
  authToken: string,
): Promise<boolean> {
  const signature = req.headers.get('x-twilio-signature');
  if (!signature) {
    return false;
  }

  // Twilio signs against the full URL that it POSTs to.
  // Use the URL from the request; Supabase edge runtime preserves it.
  const url = req.url;

  // Sort param keys alphabetically, append key+value to URL
  const sortedKeys = Object.keys(params).sort();
  let dataToSign = url;
  for (const key of sortedKeys) {
    dataToSign += key + (params[key] ?? '');
  }

  const expected = await hmacSha1(authToken, dataToSign);

  // Constant-time comparison to prevent timing attacks
  if (expected.length !== signature.length) return false;
  let mismatch = 0;
  for (let i = 0; i < expected.length; i++) {
    mismatch |= expected.charCodeAt(i) ^ signature.charCodeAt(i);
  }
  return mismatch === 0;
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
