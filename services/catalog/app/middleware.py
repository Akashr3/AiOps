import logging
import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("catalog.access")


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log HTTP requests in structured JSON format"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # Extract request info
        client_host = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else 0
        
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000
            
            # Log successful request
            logger.info(
                "HTTP request completed",
                extra={
                    "http": {
                        "request": {
                            "method": request.method,
                            "path": request.url.path,
                            "query": str(request.url.query) if request.url.query else None,
                        },
                        "response": {
                            "status_code": response.status_code,
                            "status_text": "OK" if response.status_code < 400 else "Error",
                        },
                        "version": "1.1",
                    },
                    "source": {
                        "ip": client_host,
                        "port": client_port,
                    },
                    "url": {
                        "path": request.url.path,
                        "full": str(request.url),
                    },
                    "duration_ms": round(duration_ms, 2),
                }
            )
            
            return response
            
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            
            # Log failed request
            logger.error(
                f"HTTP request failed: {str(exc)}",
                extra={
                    "http": {
                        "request": {
                            "method": request.method,
                            "path": request.url.path,
                        },
                        "response": {
                            "status_code": 500,
                            "status_text": "Internal Server Error",
                        },
                    },
                    "source": {
                        "ip": client_host,
                        "port": client_port,
                    },
                    "duration_ms": round(duration_ms, 2),
                    "error": {
                        "message": str(exc),
                        "type": type(exc).__name__,
                    }
                }
            )
            raise
