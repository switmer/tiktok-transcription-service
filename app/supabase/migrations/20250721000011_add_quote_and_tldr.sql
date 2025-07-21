-- Add quote and TLDR columns to transcriptions table
ALTER TABLE public.transcriptions 
ADD COLUMN IF NOT EXISTS quote text NULL,
ADD COLUMN IF NOT EXISTS tldr jsonb NULL;

-- Add indexes for quote and TLDR searches
CREATE INDEX IF NOT EXISTS idx_transcriptions_quote ON public.transcriptions USING gin(to_tsvector('english', quote));
CREATE INDEX IF NOT EXISTS idx_transcriptions_tldr ON public.transcriptions USING gin(tldr);

-- Add comments for clarity
COMMENT ON COLUMN public.transcriptions.quote IS 'Most memorable, shareable quote from the video';
COMMENT ON COLUMN public.transcriptions.tldr IS 'Array of 2-3 key bullet points as JSON array';

-- Example TLDR format: ["Point 1", "Point 2", "Point 3"]