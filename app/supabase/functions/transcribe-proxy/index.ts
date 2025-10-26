import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

serve(async (req) => {
  // Handle CORS preflight requests
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  try {
    // Get API key from secrets
    const API_KEY = Deno.env.get('API_KEY')
    if (!API_KEY) {
      throw new Error('API_KEY not configured in Edge Function secrets')
    }

    const API_BASE_URL = (Deno.env.get('API_BASE_URL') || 'https://tiktok-transcription-service.onrender.com').replace(/\/$/, '')
    
    // Parse request body
    const body = await req.json()
    const { url, action = 'transcribe', taskId } = body

    let apiUrl: string
    let method = 'POST'
    let requestBody = null

    // Route different actions
    switch (action) {
      case 'transcribe':
        apiUrl = `${API_BASE_URL}/api/public/transcribe`
        requestBody = { url }
        break
      case 'status':
        apiUrl = `${API_BASE_URL}/api/public/tasks/${taskId}`
        method = 'GET'
        break
      case 'transcript':
        apiUrl = `${API_BASE_URL}/api/public/transcript/${taskId}`
        method = 'GET'
        break
      case 'tasks':
        apiUrl = `${API_BASE_URL}/api/public/tasks`
        method = 'GET'
        break
      default:
        throw new Error(`Unknown action: ${action}`)
    }

    // Make request to FastAPI backend with API key
    const headers = {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY,
    }

    const fetchOptions: RequestInit = {
      method,
      headers,
    }

    if (requestBody) {
      fetchOptions.body = JSON.stringify(requestBody)
    }

    console.log(`Making ${method} request to ${apiUrl}`)
    const response = await fetch(apiUrl, fetchOptions)
    
    if (!response.ok) {
      const errorText = await response.text()
      console.error(`API Error: ${response.status} - ${errorText}`)
      throw new Error(`API Error: ${response.status} - ${errorText}`)
    }

    const data = await response.json()
    
    return new Response(
      JSON.stringify(data),
      { 
        headers: { 
          ...corsHeaders, 
          'Content-Type': 'application/json' 
        } 
      }
    )

  } catch (error) {
    console.error('Edge Function Error:', error)
    return new Response(
      JSON.stringify({ 
        error: error.message || 'Internal server error',
        details: error.toString()
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