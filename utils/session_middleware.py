"""
Redis-based Session Middleware for FastAPI
Provides persistent session management with Redis backend
"""
import json
import uuid
from typing import Any, Dict, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import redis
import os
from dotenv import load_dotenv

load_dotenv()

class RedisSessionMiddleware(BaseHTTPMiddleware):
    """Redis-based session middleware for persistent session storage"""
    
    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        max_age: int = 3600 * 24 * 7,  # 7 days
        session_cookie: str = "session_id",
        redis_url: Optional[str] = None,
        domain: Optional[str] = None,
        secure: bool = True,
        httponly: bool = True,
        samesite: str = "none"
    ):
        super().__init__(app)
        self.secret_key = secret_key
        self.max_age = max_age
        self.session_cookie = session_cookie
        self.domain = domain
        self.secure = secure
        self.httponly = httponly
        self.samesite = samesite
        
        # Initialize Redis connection
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            # Test connection
            self.redis_client.ping()
            print(f"✅ Redis session store connected: {self.redis_url}")
        except Exception as e:
            print(f"❌ Redis session store connection failed: {e}")
            self.redis_client = None
    
    async def dispatch(self, request: Request, call_next):
        """Process request and manage session"""
        
        # Get session ID from cookie
        session_id = request.cookies.get(self.session_cookie)
        
        # Load session data
        session_data = {}
        if session_id and self.redis_client:
            try:
                stored_data = self.redis_client.get(f"session:{session_id}")
                if stored_data:
                    session_data = json.loads(stored_data)
            except Exception as e:
                print(f"Error loading session {session_id}: {e}")
                session_data = {}
        
        # Create new session ID if none exists
        if not session_id:
            session_id = str(uuid.uuid4())
        
        # Attach session to request
        request.state.session = SessionDict(session_data, session_id, self.redis_client, self.max_age)
        
        # Process request
        response = await call_next(request)
        
        # Save session data and set cookie
        if hasattr(request.state, 'session') and request.state.session.modified:
            self._save_session(session_id, request.state.session.data)
            self._set_session_cookie(response, session_id)
        elif not request.cookies.get(self.session_cookie):
            # Set cookie even if session wasn't modified (for new sessions)
            self._set_session_cookie(response, session_id)
        
        return response
    
    def _save_session(self, session_id: str, session_data: Dict[str, Any]):
        """Save session data to Redis"""
        if self.redis_client:
            try:
                serialized_data = json.dumps(session_data)
                self.redis_client.setex(
                    f"session:{session_id}",
                    self.max_age,
                    serialized_data
                )
            except Exception as e:
                print(f"Error saving session {session_id}: {e}")
    
    def _set_session_cookie(self, response: Response, session_id: str):
        """Set session cookie in response"""
        response.set_cookie(
            key=self.session_cookie,
            value=session_id,
            max_age=self.max_age,
            httponly=self.httponly,
            secure=self.secure,
            samesite=self.samesite,
            domain=self.domain
        )


class SessionDict:
    """Session dictionary with modification tracking"""
    
    def __init__(self, data: Dict[str, Any], session_id: str, redis_client, max_age: int):
        self.data = data
        self.session_id = session_id
        self.redis_client = redis_client
        self.max_age = max_age
        self.modified = False
    
    def __getitem__(self, key):
        return self.data[key]
    
    def __setitem__(self, key, value):
        self.data[key] = value
        self.modified = True
        self._save_immediately()
    
    def __delitem__(self, key):
        del self.data[key]
        self.modified = True
        self._save_immediately()
    
    def __contains__(self, key):
        return key in self.data
    
    def get(self, key, default=None):
        return self.data.get(key, default)
    
    def pop(self, key, default=None):
        if key in self.data:
            self.modified = True
            self._save_immediately()
            return self.data.pop(key, default)
        return default
    
    def clear(self):
        if self.data:
            self.data.clear()
            self.modified = True
            self._save_immediately()
    
    def update(self, other):
        self.data.update(other)
        self.modified = True
        self._save_immediately()
    
    def setdefault(self, key, default=None):
        if key not in self.data:
            self.data[key] = default
            self.modified = True
            self._save_immediately()
        return self.data[key]
    
    def _save_immediately(self):
        """Immediately save session to Redis"""
        if self.redis_client:
            try:
                serialized_data = json.dumps(self.data)
                self.redis_client.setex(
                    f"session:{self.session_id}",
                    self.max_age,
                    serialized_data
                )
            except Exception as e:
                print(f"Error immediately saving session {self.session_id}: {e}")


def get_session(request: Request) -> SessionDict:
    """Get session from request"""
    if hasattr(request.state, 'session'):
        return request.state.session
    return SessionDict({}, "no-session", None, 3600)
