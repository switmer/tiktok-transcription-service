import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

Deno.serve(async (req) => {
  // Handle CORS preflight requests
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  try {
    // Parse request body
    const { task_id, update_data } = await req.json();
    
    if (!task_id) {
      return new Response(JSON.stringify({ error: 'task_id is required' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', ...corsHeaders }
      });
    }

    if (!update_data || typeof update_data !== 'object') {
      return new Response(JSON.stringify({ error: 'update_data is required and must be an object' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', ...corsHeaders }
      });
    }

    // Create Supabase client with service role key for function execution
    const supabaseClient = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    );

    console.log(`Updating transcription ${task_id} with data:`, JSON.stringify(update_data));

    // Use the PostgreSQL function to safely update the record
    // This bypasses the PostGREST ON CONFLICT issue
    // Explicitly cast task_id to UUID to avoid function overloading ambiguity
    const { data, error } = await supabaseClient.rpc('update_transcription', {
      p_task_id: task_id as string, // TypeScript knows it's a string
      p_update_data: update_data
    });

    if (error) {
      console.error('Error updating transcription:', error);
      return new Response(JSON.stringify({ 
        error: error.message,
        details: error.details,
        hint: error.hint,
        code: error.code
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json', ...corsHeaders }
      });
    }

    console.log(`Successfully updated transcription ${task_id}`);

    return new Response(JSON.stringify({ 
      success: true, 
      data: data,
      task_id: task_id
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json', ...corsHeaders }
    });

  } catch (error) {
    console.error('Unexpected error in update-transcription function:', error);
    
    return new Response(JSON.stringify({ 
      error: error.message || 'Internal server error',
      details: error.toString()
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', ...corsHeaders }
    });
  }
});