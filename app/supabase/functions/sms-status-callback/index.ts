import { createClient } from 'npm:@supabase/supabase-js@2.39.3';
import { validateTwilioSignature, formDataToRecord } from '../_shared/validate-twilio.ts';

Deno.serve(async (req) => {
  if (req.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 });
  }

  try {
    const twilioAuthToken = Deno.env.get('TWILIO_AUTH_TOKEN');

    // Parse Twilio's callback data (form-encoded)
    const form = await req.formData();

    // Validate Twilio signature if auth token is configured
    if (twilioAuthToken) {
      const params = formDataToRecord(form);
      const valid = await validateTwilioSignature(req, params, twilioAuthToken);
      if (!valid) {
        console.warn('Invalid Twilio signature on sms-status-callback');
        return new Response('Forbidden', { status: 403 });
      }
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );
    const messageSid = form.get('MessageSid')?.toString();
    const messageStatus = form.get('MessageStatus')?.toString();
    const errorCode = form.get('ErrorCode')?.toString();
    const to = form.get('To')?.toString();
    const from = form.get('From')?.toString();
    
    console.log(`SMS Status Callback: ${messageSid} -> ${messageStatus}`);
    console.log(`To: ${to}, From: ${from}, ErrorCode: ${errorCode}`);
    
    if (!messageSid || !messageStatus) {
      console.error('Missing required fields:', { messageSid, messageStatus });
      return new Response('Missing required fields', { status: 400 });
    }

    // Update the user_messages table with delivery status
    const updateData: any = {
      delivery_status: messageStatus,
      error_code: errorCode || null,
    };

    // Set timestamp fields based on status
    if (messageStatus === 'delivered') {
      updateData.delivered_at = new Date().toISOString();
    } else if (['failed', 'undelivered'].includes(messageStatus)) {
      updateData.failed_at = new Date().toISOString();
    }

    const { error } = await supabase
      .from('user_messages')
      .update(updateData)
      .eq('message_sid', messageSid);

    if (error) {
      console.error('Database update error:', error);
      // Still return 200 to Twilio to prevent retries
      return new Response('OK', { status: 200 });
    }

    console.log(`Successfully updated message ${messageSid} status to ${messageStatus}`);
    return new Response('OK', { status: 200 });

  } catch (error) {
    console.error('Status callback error:', error);
    // Always return 200 to Twilio to prevent retries
    return new Response('OK', { status: 200 });
  }
});