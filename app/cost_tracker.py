"""
Cost Tracking Module for ScribeTok

Tracks API costs for:
- OpenAI Whisper (transcription)
- OpenAI GPT (summaries, quotes)
- Anthropic Claude (chat, summaries)
- RapidAPI (TikTok, YouTube, Instagram, Facebook)
- Twilio SMS (inbound/outbound)

Usage:
    from cost_tracker import CostTracker

    # Log a Whisper transcription cost
    await CostTracker.log_whisper_cost(
        duration_seconds=120,
        user_phone="+1234567890",
        task_id="abc123"
    )

    # Log a RapidAPI call
    await CostTracker.log_rapidapi_cost(
        platform="tiktok",
        user_phone="+1234567890",
        task_id="abc123"
    )
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)

# Cost rates (in cents per unit)
# These are approximate rates - adjust based on your actual pricing

COST_RATES = {
    # OpenAI Whisper: $0.006 per minute = 0.6 cents per minute
    "openai_whisper_per_minute": 0.6,

    # OpenAI GPT-3.5-turbo: ~$0.002 per 1K tokens = 0.2 cents per 1K tokens
    # Average call uses ~500 tokens = ~0.1 cents
    "openai_gpt_per_call": 0.1,

    # Anthropic Claude Haiku: ~$0.00025 per 1K input + $0.00125 per 1K output
    # Average call ~0.05 cents
    "anthropic_claude_per_call": 0.05,

    # RapidAPI TikTok: ~$0.001 per request on basic plan
    "rapidapi_tiktok_per_call": 0.1,

    # RapidAPI YouTube Transcriber: ~$0.002 per request
    "rapidapi_youtube_per_call": 0.2,

    # RapidAPI Instagram: ~$0.001 per request
    "rapidapi_instagram_per_call": 0.1,

    # RapidAPI Facebook: ~$0.001 per request
    "rapidapi_facebook_per_call": 0.1,

    # Twilio SMS outbound: ~$0.0079 per segment = 0.79 cents
    "twilio_sms_outbound_per_segment": 0.79,

    # Twilio SMS inbound: ~$0.0075 per segment = 0.75 cents
    "twilio_sms_inbound_per_segment": 0.75,
}


class CostTracker:
    """Tracks and logs API costs to the database"""

    _supabase = None

    @classmethod
    def _get_supabase(cls):
        """Lazy load supabase client"""
        if cls._supabase is None:
            try:
                from .database import supabase
                cls._supabase = supabase
            except ImportError:
                from database import supabase
                cls._supabase = supabase
        return cls._supabase

    @classmethod
    async def _log_cost(
        cls,
        cost_type: str,
        amount_cents: float,
        user_phone: Optional[str] = None,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> bool:
        """
        Log a cost to the database.

        Args:
            cost_type: Type of cost (e.g., 'openai_whisper', 'rapidapi_tiktok')
            amount_cents: Cost in cents (can be fractional, will be rounded)
            user_phone: Associated user phone number
            task_id: Associated transcription task ID
            metadata: Additional details (duration, tokens, etc.)
            success: Whether the API call succeeded
            error_message: Error message if call failed

        Returns:
            True if logged successfully, False otherwise
        """
        try:
            supabase = cls._get_supabase()
            if not supabase:
                logger.warning("Supabase not available, skipping cost tracking")
                return False

            # Round to nearest cent (or store as fractional cents)
            amount_cents_int = round(amount_cents)

            record = {
                "cost_type": cost_type,
                "amount_cents": amount_cents_int,
                "user_phone": user_phone,
                "task_id": task_id,
                "metadata": metadata or {},
                "success": success,
                "error_message": error_message
            }

            # Run database insert in thread pool
            await asyncio.to_thread(
                lambda: supabase.table("cost_tracking").insert(record).execute()
            )

            logger.debug(f"Logged cost: {cost_type} = {amount_cents_int} cents")
            return True

        except Exception as e:
            # Don't let cost tracking failures break the main flow
            logger.error(f"Failed to log cost: {str(e)}")
            return False

    # ============================================================
    # OpenAI Whisper
    # ============================================================

    @classmethod
    async def log_whisper_cost(
        cls,
        duration_seconds: float,
        user_phone: Optional[str] = None,
        task_id: Optional[str] = None,
        audio_file_size_bytes: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> bool:
        """Log OpenAI Whisper transcription cost"""
        duration_minutes = duration_seconds / 60
        cost_cents = duration_minutes * COST_RATES["openai_whisper_per_minute"]

        metadata = {
            "duration_seconds": duration_seconds,
            "duration_minutes": round(duration_minutes, 2)
        }
        if audio_file_size_bytes:
            metadata["audio_file_size_bytes"] = audio_file_size_bytes

        return await cls._log_cost(
            cost_type="openai_whisper",
            amount_cents=cost_cents,
            user_phone=user_phone,
            task_id=task_id,
            metadata=metadata,
            success=success,
            error_message=error_message
        )

    # ============================================================
    # OpenAI GPT
    # ============================================================

    @classmethod
    async def log_gpt_cost(
        cls,
        model: str = "gpt-3.5-turbo",
        tokens_used: Optional[int] = None,
        user_phone: Optional[str] = None,
        task_id: Optional[str] = None,
        purpose: str = "quote_tldr",
        success: bool = True,
        error_message: Optional[str] = None
    ) -> bool:
        """Log OpenAI GPT API cost"""
        cost_cents = COST_RATES["openai_gpt_per_call"]

        metadata = {
            "model": model,
            "purpose": purpose
        }
        if tokens_used:
            metadata["tokens_used"] = tokens_used

        return await cls._log_cost(
            cost_type="openai_gpt",
            amount_cents=cost_cents,
            user_phone=user_phone,
            task_id=task_id,
            metadata=metadata,
            success=success,
            error_message=error_message
        )

    # ============================================================
    # Anthropic Claude
    # ============================================================

    @classmethod
    async def log_claude_cost(
        cls,
        model: str = "claude-3-haiku-20240307",
        purpose: str = "summary",
        user_phone: Optional[str] = None,
        task_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> bool:
        """Log Anthropic Claude API cost"""
        cost_cents = COST_RATES["anthropic_claude_per_call"]

        metadata = {
            "model": model,
            "purpose": purpose
        }

        return await cls._log_cost(
            cost_type="anthropic_claude",
            amount_cents=cost_cents,
            user_phone=user_phone,
            task_id=task_id,
            metadata=metadata,
            success=success,
            error_message=error_message
        )

    # ============================================================
    # RapidAPI
    # ============================================================

    @classmethod
    async def log_rapidapi_cost(
        cls,
        platform: str,  # 'tiktok', 'youtube', 'instagram', 'facebook'
        user_phone: Optional[str] = None,
        task_id: Optional[str] = None,
        video_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> bool:
        """Log RapidAPI call cost"""
        # Get cost rate for platform
        rate_key = f"rapidapi_{platform}_per_call"
        cost_cents = COST_RATES.get(rate_key, 0.1)  # Default to 0.1 cents

        cost_type = f"rapidapi_{platform}"

        metadata = {
            "platform": platform
        }
        if video_id:
            metadata["video_id"] = video_id

        return await cls._log_cost(
            cost_type=cost_type,
            amount_cents=cost_cents,
            user_phone=user_phone,
            task_id=task_id,
            metadata=metadata,
            success=success,
            error_message=error_message
        )

    # ============================================================
    # Twilio SMS
    # ============================================================

    @classmethod
    async def log_twilio_sms_cost(
        cls,
        direction: str,  # 'outbound' or 'inbound'
        segments: int = 1,
        user_phone: Optional[str] = None,
        message_sid: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> bool:
        """Log Twilio SMS cost"""
        rate_key = f"twilio_sms_{direction}_per_segment"
        cost_per_segment = COST_RATES.get(rate_key, 0.79)
        cost_cents = cost_per_segment * segments

        cost_type = f"twilio_sms_{direction}"

        metadata = {
            "segments": segments
        }
        if message_sid:
            metadata["message_sid"] = message_sid

        return await cls._log_cost(
            cost_type=cost_type,
            amount_cents=cost_cents,
            user_phone=user_phone,
            metadata=metadata,
            success=success,
            error_message=error_message
        )

    # ============================================================
    # Admin Stats
    # ============================================================

    @classmethod
    async def get_admin_stats(cls, period: str = "month") -> Optional[Dict[str, Any]]:
        """
        Get comprehensive admin statistics.

        Args:
            period: 'day', 'week', 'month', or 'all'

        Returns:
            Dictionary with stats or None if failed
        """
        try:
            supabase = cls._get_supabase()
            if not supabase:
                return None

            result = await asyncio.to_thread(
                lambda: supabase.rpc("get_admin_stats", {"period": period}).execute()
            )

            if result.data:
                return result.data
            return None

        except Exception as e:
            logger.error(f"Failed to get admin stats: {str(e)}")
            return None

    @classmethod
    async def get_cost_trends(cls, days: int = 30) -> Optional[list]:
        """
        Get daily cost/revenue trends for charting.

        Args:
            days: Number of days to fetch

        Returns:
            List of daily data or None if failed
        """
        try:
            supabase = cls._get_supabase()
            if not supabase:
                return None

            result = await asyncio.to_thread(
                lambda: supabase.rpc("get_cost_trends", {"days": days}).execute()
            )

            if result.data:
                return result.data
            return None

        except Exception as e:
            logger.error(f"Failed to get cost trends: {str(e)}")
            return None

    @classmethod
    async def format_admin_stats_sms(cls, period: str = "month") -> str:
        """
        Format admin stats for SMS delivery.

        Returns a formatted string suitable for SMS.
        """
        stats = await cls.get_admin_stats(period)

        if not stats:
            return "Unable to fetch admin stats. Please try again later."

        try:
            financials = stats.get("financials", {})
            users = stats.get("users", {})
            usage = stats.get("usage", {})
            cost_breakdown = stats.get("cost_breakdown", [])

            # Format currency
            revenue = financials.get("revenue_cents", 0) / 100
            costs = financials.get("costs_cents", 0) / 100
            profit = financials.get("profit_cents", 0) / 100
            margin = financials.get("margin_percent", 0)

            # Period display
            period_display = {
                "day": "Today",
                "week": "This Week",
                "month": "This Month",
                "all": "All Time"
            }.get(period, "This Month")

            # Build message
            lines = [
                f"ADMIN STATS - {period_display}",
                "=" * 25,
                "",
                "FINANCIALS",
                f"Revenue: ${revenue:.2f}",
                f"Costs: ${costs:.2f}",
                f"Profit: ${profit:.2f} ({margin:.1f}%)",
                "",
                "USERS",
                f"Total: {users.get('total', 0)}",
                f"Active: {users.get('active', 0)}",
                f"New: {users.get('new', 0)}",
                f"Paid: {users.get('paid', 0)} ({users.get('conversion_rate', 0):.1f}%)",
                "",
                "USAGE",
                f"Transcriptions: {usage.get('transcriptions', 0)}",
                f"Success Rate: {usage.get('success_rate', 0):.1f}%",
            ]

            # Add cost breakdown if available
            if cost_breakdown:
                lines.append("")
                lines.append("COST BREAKDOWN")
                for item in cost_breakdown[:5]:  # Top 5
                    cost_type = item.get("cost_type", "unknown").replace("_", " ").title()
                    total = item.get("total_cents", 0) / 100
                    count = item.get("call_count", 0)
                    lines.append(f"  {cost_type}: ${total:.2f} ({count} calls)")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Error formatting admin stats: {str(e)}")
            return f"Error formatting stats: {str(e)}"

    @classmethod
    async def format_admin_stats_detailed(cls) -> str:
        """
        Format detailed admin stats with trends for SMS.
        Includes daily, weekly, and monthly comparisons.
        """
        try:
            # Get stats for different periods
            day_stats = await cls.get_admin_stats("day")
            week_stats = await cls.get_admin_stats("week")
            month_stats = await cls.get_admin_stats("month")

            if not month_stats:
                return "Unable to fetch admin stats. Please try again later."

            # Helper to format financials
            def fmt_financials(stats):
                if not stats:
                    return "N/A"
                f = stats.get("financials", {})
                revenue = f.get("revenue_cents", 0) / 100
                costs = f.get("costs_cents", 0) / 100
                profit = f.get("profit_cents", 0) / 100
                return f"${revenue:.0f}/${costs:.0f}/${profit:.0f}"

            def fmt_usage(stats):
                if not stats:
                    return "0"
                u = stats.get("usage", {})
                return str(u.get("transcriptions", 0))

            # Build compact multi-period message
            m_fin = month_stats.get("financials", {})
            m_users = month_stats.get("users", {})

            lines = [
                "ADMIN STATS REPORT",
                "=" * 20,
                "",
                "MONTHLY OVERVIEW",
                f"Revenue: ${m_fin.get('revenue_cents', 0)/100:.2f}",
                f"Costs: ${m_fin.get('costs_cents', 0)/100:.2f}",
                f"Profit: ${m_fin.get('profit_cents', 0)/100:.2f} ({m_fin.get('margin_percent', 0):.0f}%)",
                "",
                "TRENDS (Rev/Cost/Profit)",
                f"Today: {fmt_financials(day_stats)}",
                f"Week: {fmt_financials(week_stats)}",
                f"Month: {fmt_financials(month_stats)}",
                "",
                "TRANSCRIPTIONS",
                f"Today: {fmt_usage(day_stats)}",
                f"Week: {fmt_usage(week_stats)}",
                f"Month: {fmt_usage(month_stats)}",
                "",
                f"USERS: {m_users.get('total', 0)} total, {m_users.get('paid', 0)} paid",
                f"Conversion: {m_users.get('conversion_rate', 0):.1f}%"
            ]

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Error formatting detailed stats: {str(e)}")
            return f"Error: {str(e)}"


# Convenience functions for easy importing
async def log_whisper_cost(*args, **kwargs):
    return await CostTracker.log_whisper_cost(*args, **kwargs)

async def log_gpt_cost(*args, **kwargs):
    return await CostTracker.log_gpt_cost(*args, **kwargs)

async def log_claude_cost(*args, **kwargs):
    return await CostTracker.log_claude_cost(*args, **kwargs)

async def log_rapidapi_cost(*args, **kwargs):
    return await CostTracker.log_rapidapi_cost(*args, **kwargs)

async def log_twilio_sms_cost(*args, **kwargs):
    return await CostTracker.log_twilio_sms_cost(*args, **kwargs)

async def get_admin_stats(*args, **kwargs):
    return await CostTracker.get_admin_stats(*args, **kwargs)

async def format_admin_stats_sms(*args, **kwargs):
    return await CostTracker.format_admin_stats_sms(*args, **kwargs)
