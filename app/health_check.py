"""
Health check endpoints for monitoring system status
Provides comprehensive health monitoring for all critical services
"""
import os
import time
import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import requests
from fastapi import HTTPException

from database import supabase

logger = logging.getLogger(__name__)

class HealthChecker:
    """Comprehensive health monitoring for all system components"""
    
    def __init__(self):
        self.start_time = time.time()
        
    async def check_all(self) -> Dict[str, Any]:
        """Run all health checks and return comprehensive status"""
        checks = {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": int(time.time() - self.start_time),
            "overall_status": "healthy",
            "services": {}
        }
        
        # Run all checks in parallel for speed
        check_tasks = {
            "database": self.check_database(),
            "storage": self.check_supabase_storage(),
            "openai": self.check_openai_api(),
            "environment": self.check_environment(),
            "disk_space": self.check_disk_space(),
            "memory": self.check_memory_usage()
        }
        
        # Execute all checks concurrently
        results = {}
        for service_name, task in check_tasks.items():
            try:
                results[service_name] = await task
            except Exception as e:
                results[service_name] = {
                    "status": "unhealthy",
                    "error": str(e),
                    "response_time_ms": 0
                }
        
        checks["services"] = results
        
        # Determine overall health status
        unhealthy_services = [name for name, result in results.items() 
                            if result.get("status") != "healthy"]
        
        if unhealthy_services:
            checks["overall_status"] = "degraded" if len(unhealthy_services) <= 2 else "unhealthy"
            checks["unhealthy_services"] = unhealthy_services
        
        return checks
    
    async def check_database(self) -> Dict[str, Any]:
        """Check Supabase database connectivity and performance"""
        start_time = time.time()
        
        try:
            if not supabase:
                return {
                    "status": "unhealthy",
                    "error": "Supabase client not initialized",
                    "response_time_ms": 0
                }
            
            # Test basic connectivity with a simple query
            result = supabase.table('transcriptions').select('count', count='exact').limit(1).execute()
            
            response_time = int((time.time() - start_time) * 1000)
            
            # Check if we got a response
            if hasattr(result, 'count') or result.data is not None:
                # Get additional stats
                total_records = result.count if hasattr(result, 'count') else 0
                
                return {
                    "status": "healthy",
                    "response_time_ms": response_time,
                    "total_transcriptions": total_records,
                    "connection": "active"
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": "No response from database",
                    "response_time_ms": response_time
                }
                
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            return {
                "status": "unhealthy",
                "error": f"Database connection failed: {str(e)}",
                "response_time_ms": response_time
            }
    
    async def check_supabase_storage(self) -> Dict[str, Any]:
        """Check Supabase Storage bucket accessibility"""
        start_time = time.time()
        
        try:
            if not supabase:
                return {
                    "status": "unhealthy",
                    "error": "Supabase client not initialized",
                    "response_time_ms": 0
                }
            
            # Test storage bucket access
            buckets = supabase.storage.list_buckets()
            
            response_time = int((time.time() - start_time) * 1000)
            
            # Check if assets bucket exists
            assets_bucket_exists = any(b.name == 'assets' for b in buckets) if buckets else False
            
            if assets_bucket_exists:
                # Test file listing in assets bucket
                try:
                    files = supabase.storage.from_('assets').list('thumbnails', {"limit": 1})
                    file_count = len(files) if files else 0
                    
                    return {
                        "status": "healthy",
                        "response_time_ms": response_time,
                        "buckets_found": len(buckets),
                        "assets_bucket": "accessible",
                        "sample_files": file_count
                    }
                except Exception as e:
                    return {
                        "status": "degraded",
                        "response_time_ms": response_time,
                        "buckets_found": len(buckets),
                        "assets_bucket": "accessible",
                        "file_listing_error": str(e)
                    }
            else:
                return {
                    "status": "unhealthy",
                    "error": "Assets bucket not found",
                    "response_time_ms": response_time,
                    "buckets_found": len(buckets)
                }
                
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            return {
                "status": "unhealthy",
                "error": f"Storage check failed: {str(e)}",
                "response_time_ms": response_time
            }
    
    async def check_openai_api(self) -> Dict[str, Any]:
        """Check OpenAI API connectivity and quota"""
        start_time = time.time()
        
        try:
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                return {
                    "status": "unhealthy",
                    "error": "OpenAI API key not configured",
                    "response_time_ms": 0
                }
            
            # Test API connectivity with a minimal request
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            
            # Use models endpoint for lightweight check
            response = requests.get(
                'https://api.openai.com/v1/models',
                headers=headers,
                timeout=10
            )
            
            response_time = int((time.time() - start_time) * 1000)
            
            if response.status_code == 200:
                models_data = response.json()
                whisper_available = any('whisper' in model.get('id', '') for model in models_data.get('data', []))
                gpt4_available = any('gpt-4' in model.get('id', '') for model in models_data.get('data', []))
                
                return {
                    "status": "healthy",
                    "response_time_ms": response_time,
                    "whisper_available": whisper_available,
                    "gpt4_available": gpt4_available,
                    "total_models": len(models_data.get('data', []))
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": f"OpenAI API returned {response.status_code}",
                    "response_time_ms": response_time
                }
                
        except requests.exceptions.Timeout:
            response_time = int((time.time() - start_time) * 1000)
            return {
                "status": "unhealthy",
                "error": "OpenAI API timeout",
                "response_time_ms": response_time
            }
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            return {
                "status": "unhealthy",
                "error": f"OpenAI API check failed: {str(e)}",
                "response_time_ms": response_time
            }
    
    async def check_environment(self) -> Dict[str, Any]:
        """Check critical environment variables and configuration"""
        try:
            required_vars = [
                'OPENAI_API_KEY',
                'SUPABASE_URL', 
                'SUPABASE_SERVICE_KEY',
                'API_KEY'
            ]
            
            optional_vars = [
                'RAPIDAPI_KEY',
                'STRIPE_SECRET_KEY',
                'BASE_URL'
            ]
            
            missing_required = [var for var in required_vars if not os.getenv(var)]
            missing_optional = [var for var in optional_vars if not os.getenv(var)]
            
            status = "healthy" if not missing_required else "unhealthy"
            
            result = {
                "status": status,
                "required_vars_set": len(required_vars) - len(missing_required),
                "required_vars_total": len(required_vars),
                "optional_vars_set": len(optional_vars) - len(missing_optional),
                "optional_vars_total": len(optional_vars),
                "response_time_ms": 1  # Environment check is instant
            }
            
            if missing_required:
                result["missing_required"] = missing_required
            if missing_optional:
                result["missing_optional"] = missing_optional
                
            return result
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": f"Environment check failed: {str(e)}",
                "response_time_ms": 1
            }
    
    async def check_disk_space(self) -> Dict[str, Any]:
        """Check available disk space"""
        try:
            import shutil
            
            # Check current directory space (where app runs)
            total, used, free = shutil.disk_usage('.')
            
            # Convert to MB for readability
            total_mb = total // (1024 * 1024)
            used_mb = used // (1024 * 1024)
            free_mb = free // (1024 * 1024)
            usage_percent = (used / total) * 100
            
            # Determine status based on free space
            if free_mb < 100:  # Less than 100MB free
                status = "unhealthy"
            elif free_mb < 500:  # Less than 500MB free
                status = "degraded"
            else:
                status = "healthy"
            
            return {
                "status": status,
                "total_mb": total_mb,
                "used_mb": used_mb,
                "free_mb": free_mb,
                "usage_percent": round(usage_percent, 2),
                "response_time_ms": 1
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": f"Disk space check failed: {str(e)}",
                "response_time_ms": 1
            }
    
    async def check_memory_usage(self) -> Dict[str, Any]:
        """Check memory usage (if psutil is available)"""
        try:
            import psutil
            
            # Get memory info
            memory = psutil.virtual_memory()
            
            # Convert to MB
            total_mb = memory.total // (1024 * 1024)
            available_mb = memory.available // (1024 * 1024)
            used_mb = (memory.total - memory.available) // (1024 * 1024)
            usage_percent = memory.percent
            
            # Determine status based on memory usage
            if usage_percent > 90:
                status = "unhealthy"
            elif usage_percent > 80:
                status = "degraded"
            else:
                status = "healthy"
            
            return {
                "status": status,
                "total_mb": total_mb,
                "used_mb": used_mb,
                "available_mb": available_mb,
                "usage_percent": round(usage_percent, 2),
                "response_time_ms": 1
            }
            
        except ImportError:
            return {
                "status": "unknown",
                "error": "psutil not available for memory monitoring",
                "response_time_ms": 1
            }
        except Exception as e:
            return {
                "status": "unhealthy", 
                "error": f"Memory check failed: {str(e)}",
                "response_time_ms": 1
            }

# Global health checker instance
health_checker = HealthChecker()

# Convenience functions for FastAPI endpoints
async def get_health_status() -> Dict[str, Any]:
    """Get comprehensive health status"""
    return await health_checker.check_all()

async def get_simple_health() -> Dict[str, str]:
    """Get simple health check for load balancers"""
    try:
        # Quick database connectivity check
        if supabase:
            supabase.table('transcriptions').select('task_id').limit(1).execute()
            return {"status": "healthy"}
        else:
            return {"status": "unhealthy", "error": "Database not available"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

async def get_readiness() -> Dict[str, Any]:
    """Check if service is ready to handle requests"""
    checks = {
        "ready": True,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }
    
    # Critical readiness checks
    critical_checks = {
        "database": health_checker.check_database(),
        "environment": health_checker.check_environment()
    }
    
    results = {}
    for check_name, task in critical_checks.items():
        try:
            result = await task
            results[check_name] = result
            if result.get("status") != "healthy":
                checks["ready"] = False
        except Exception as e:
            results[check_name] = {"status": "unhealthy", "error": str(e)}
            checks["ready"] = False
    
    checks["checks"] = results
    return checks