import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

interface TwilioErrorPayload {
  AccountSid: string
  Sid: string
  ParentAccountSid?: string
  Timestamp: string
  Level: 'Error' | 'Warning'
  PayloadType: string
  Payload: any
}

serve(async (req) => {
  // Handle CORS preflight requests
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  try {
    // Initialize Supabase client
    const supabaseUrl = Deno.env.get('SUPABASE_URL')!
    const supabaseServiceKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    const supabase = createClient(supabaseUrl, supabaseServiceKey)

    // Parse the Twilio error webhook payload (sent as form data, not JSON)
    const formData = await req.formData()
    
    // Parse Payload field (might be JSON string)
    let payloadData: any = {}
    try {
      const payloadStr = formData.get('Payload') as string
      if (payloadStr) {
        payloadData = JSON.parse(payloadStr)
      }
    } catch (e) {
      console.warn('Failed to parse Payload field as JSON:', e)
      payloadData = { raw: formData.get('Payload') }
    }
    
    const payload: TwilioErrorPayload = {
      AccountSid: formData.get('AccountSid') as string,
      Sid: formData.get('Sid') as string,
      ParentAccountSid: formData.get('ParentAccountSid') as string || undefined,
      Timestamp: formData.get('Timestamp') as string,
      Level: formData.get('Level') as 'Error' | 'Warning',
      PayloadType: formData.get('PayloadType') as string,
      Payload: payloadData
    }
    
    console.log(`Twilio ${payload.Level} received:`, {
      sid: payload.Sid,
      accountSid: payload.AccountSid,
      timestamp: payload.Timestamp,
      payload: payload.Payload
    })

    // Log the error to Supabase for monitoring
    const { error: logError } = await supabase
      .from('twilio_error_logs')
      .insert({
        twilio_sid: payload.Sid,
        account_sid: payload.AccountSid,
        parent_account_sid: payload.ParentAccountSid,
        timestamp: payload.Timestamp,
        level: payload.Level.toLowerCase(),
        payload_type: payload.PayloadType,
        payload_data: payload.Payload,
        created_at: new Date().toISOString()
      })

    if (logError) {
      console.error('Failed to log Twilio error to database:', logError)
    }

    // Handle specific error types
    if (payload.Level === 'Error') {
      await handleTwilioError(supabase, payload)
    } else if (payload.Level === 'Warning') {
      await handleTwilioWarning(supabase, payload)
    }

    return new Response(
      JSON.stringify({ success: true, message: 'Webhook processed successfully' }),
      { 
        headers: { 
          ...corsHeaders, 
          'Content-Type': 'application/json' 
        } 
      }
    )

  } catch (error) {
    console.error('Twilio Error Webhook Error:', error)
    
    return new Response(
      JSON.stringify({ 
        error: 'Internal server error',
        message: error.message 
      }),
      { 
        status: 500, 
        headers: { 
          ...corsHeaders, 
          'Content-Type': 'application/json' 
        } 
      }
    )
  }
})

async function handleTwilioError(supabase: any, payload: TwilioErrorPayload) {
  // Extract relevant information from the error payload
  const errorInfo = payload.Payload
  
  // Common error handling based on error codes
  if (errorInfo.error_code) {
    switch (errorInfo.error_code) {
      case '21211': // Invalid 'To' phone number
      case '21612': // The 'To' phone number is not currently reachable
        console.warn(`Phone number issue: ${errorInfo.error_code} - ${errorInfo.more_info}`)
        await markPhoneAsInvalid(supabase, errorInfo.to)
        break
        
      case '21408': // Permission to send an SMS has not been enabled
      case '21610': // Attempt to send to unsubscribed recipient
        console.warn(`SMS permission issue: ${errorInfo.error_code} - ${errorInfo.more_info}`)
        await handleUnsubscribe(supabase, errorInfo.to)
        break
        
      case '30001': // Queue overflow
      case '30002': // Account suspended
      case '30003': // Unreachable destination handset
        console.error(`Service issue: ${errorInfo.error_code} - ${errorInfo.more_info}`)
        // These require immediate attention
        break
        
      default:
        console.log(`Unhandled Twilio error: ${errorInfo.error_code} - ${errorInfo.more_info}`)
    }
  }
}

async function handleTwilioWarning(supabase: any, payload: TwilioErrorPayload) {
  // Log warnings for monitoring but don't take action
  console.warn('Twilio Warning:', payload.Payload)
}

async function markPhoneAsInvalid(supabase: any, phoneNumber: string) {
  if (!phoneNumber) return
  
  const { error } = await supabase
    .from('sms_users')
    .update({ 
      is_active: false,
      last_error: 'Invalid phone number',
      updated_at: new Date().toISOString()
    })
    .eq('phone', phoneNumber)
    
  if (error) {
    console.error('Failed to mark phone as invalid:', error)
  } else {
    console.log(`Marked phone ${phoneNumber} as invalid`)
  }
}

async function handleUnsubscribe(supabase: any, phoneNumber: string) {
  if (!phoneNumber) return
  
  const { error } = await supabase
    .from('sms_users')
    .update({ 
      is_active: false,
      unsubscribed_at: new Date().toISOString(),
      last_error: 'Unsubscribed or permission denied',
      updated_at: new Date().toISOString()
    })
    .eq('phone', phoneNumber)
    
  if (error) {
    console.error('Failed to handle unsubscribe:', error)
  } else {
    console.log(`Handled unsubscribe for phone ${phoneNumber}`)
  }
}