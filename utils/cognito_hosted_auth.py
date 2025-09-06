"""
Amazon Cognito Hosted UI Authentication for FastAPI
Redirects users to Cognito hosted UI and handles authentication with Redis sessions
"""

import os
import json
import jwt
import base64
import httpx
from urllib.parse import urlencode, parse_qs
from typing import Optional, Dict, Any
from fastapi import HTTPException, Request, Response, Depends
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .session_middleware import get_session
from dotenv import load_dotenv

load_dotenv()

# Cognito Configuration
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
COGNITO_REGION = os.getenv("COGNITO_REGION", "ap-south-1")  # Use dedicated Cognito region
USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET")
COGNITO_DOMAIN = os.getenv("COGNITO_DOMAIN")
REDIRECT_URI = os.getenv("COGNITO_REDIRECT_URI")
LOGOUT_URI = os.getenv("COGNITO_LOGOUT_URI")

# JWKS URL for token validation (use COGNITO_REGION)
JWKS_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"

# Security scheme
security = HTTPBearer(auto_error=False)

class CognitoHostedUIAuth:
    """Amazon Cognito Hosted UI Authentication Handler"""
    
    def __init__(self):
        self.jwks_cache = None
        print(f"🔐 Cognito Hosted UI Auth initialized")
        print(f"📍 User Pool ID: {USER_POOL_ID}")
        print(f"🆔 Client ID: {CLIENT_ID}")
        print(f"🌐 Domain: {COGNITO_DOMAIN}")
    
    def get_login_url(self, state: str = "default") -> str:
        """Generate Cognito hosted UI login URL"""
        # Use the correct hosted UI login endpoint
        auth_url = f"{COGNITO_DOMAIN}/login/continue"
        params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "scope": "email openid profile",
            "redirect_uri": REDIRECT_URI,
            "state": state
        }
        return auth_url + "?" + urlencode(params)
    
    def get_logout_url(self) -> str:
        """Generate Cognito hosted UI logout URL"""
        # Use the correct hosted UI logout endpoint
        logout_url = f"{COGNITO_DOMAIN}/logout"
        params = {
            "client_id": CLIENT_ID,
            "logout_uri": LOGOUT_URI
        }
        return logout_url + "?" + urlencode(params)
    
    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for tokens"""
        # Use the correct hosted UI token endpoint
        token_url = f"{COGNITO_DOMAIN}/oauth2/token"
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI
        }
        
        # Add client secret if available
        if CLIENT_SECRET:
            auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
            auth_bytes = base64.b64encode(auth_string.encode()).decode()
            headers["Authorization"] = f"Basic {auth_bytes}"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, headers=headers, data=data)
            
            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Token exchange failed: {response.text}"
                )
    
    async def get_jwks(self) -> Dict[str, Any]:
        """Get JWKS from Cognito"""
        if not self.jwks_cache:
            async with httpx.AsyncClient() as client:
                print(f"🔑 Fetching JWKS from: {JWKS_URL}")
                response = await client.get(JWKS_URL)
                if response.status_code != 200:
                    print(f"❌ JWKS request failed: {response.status_code} - {response.text}")
                    raise HTTPException(status_code=500, detail="Failed to fetch JWKS")
                
                jwks_data = response.json()
                print(f"✅ JWKS response: {jwks_data}")
                self.jwks_cache = jwks_data
        return self.jwks_cache
    
    async def get_user_info_from_access_token(self, access_token: str) -> Dict[str, Any]:
        """Get user info from Cognito UserInfo endpoint using access token"""
        userinfo_url = f"{COGNITO_DOMAIN}/oauth2/userInfo"
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(userinfo_url, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to get user info: {response.text}"
                )
    
    async def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token against Cognito JWKS"""
        try:
            # Decode token header to get kid
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            
            # Get JWKS
            jwks = await self.get_jwks()
            
            # Check if jwks has keys
            if "keys" not in jwks:
                print(f"❌ JWKS Error: Expected 'keys' field but got: {jwks}")
                raise HTTPException(status_code=500, detail="Invalid JWKS response")
            
            # Find matching key
            key = None
            for jwk in jwks["keys"]:
                if jwk["kid"] == kid:
                    key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
                    break
            
            if not key:
                raise HTTPException(status_code=401, detail="Invalid token key")
            
            # Check token type to determine validation approach
            decoded_payload = jwt.decode(token, options={"verify_signature": False})
            token_use = decoded_payload.get("token_use")
            
            if token_use == "id":
                # ID token - validate with audience (client_id)
                payload = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256"],
                    audience=CLIENT_ID,
                    issuer=f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}"
                )
            elif token_use == "access":
                # Access token - validate without audience claim (access tokens don't have 'aud')
                payload = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256"],
                    # No audience validation for access tokens
                    issuer=f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}"
                )
            else:
                # Unknown token type - try without audience
                payload = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256"],
                    issuer=f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}"
                )
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    
    def is_authenticated(self, request: Request) -> bool:
        """Check if user has valid session"""
        session = get_session(request)
        return session.get("user") is not None
    
    def get_user_from_session(self, request: Request) -> Optional[Dict[str, Any]]:
        """Get user data from session"""
        session = get_session(request)
        return session.get("user")

# Global auth instance
cognito_auth = CognitoHostedUIAuth()

# Dependencies
async def get_current_user(request: Request) -> Dict[str, Any]:
    """FastAPI dependency to get current authenticated user"""
    user = cognito_auth.get_user_from_session(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user

async def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    """FastAPI dependency to get current user (optional)"""
    return cognito_auth.get_user_from_session(request)

def require_auth(user: dict = Depends(get_current_user)):
    """Dependency that requires authentication"""
    return user
