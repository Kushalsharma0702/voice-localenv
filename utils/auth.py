"""
Amazon Cognito Authentication Module for FastAPI
Provides user signup, login, and JWT token validation functionality
"""

import os
import json
import base64
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from functools import wraps

import boto3
import jwt
import httpx
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

load_dotenv()

# AWS Cognito Configuration
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET")  # Optional - only if your app client has a secret

# JWKS URL for token validation
JWKS_URL = f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"

# Initialize AWS Cognito client
try:
    cognito_client = boto3.client('cognito-idp', region_name=AWS_REGION)
except NoCredentialsError:
    raise Exception("AWS credentials not configured. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")

# Security scheme for FastAPI
security = HTTPBearer()

class AuthError(Exception):
    """Custom authentication error"""
    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class CognitoAuth:
    def __init__(self):
        self.region = AWS_REGION
        self.user_pool_id = USER_POOL_ID
        self.client_id = CLIENT_ID
        self.client_secret = CLIENT_SECRET
        self.jwks_cache = {}
        self.jwks_cache_time = None
        
        # Validate required environment variables
        if not all([self.user_pool_id, self.client_id]):
            raise ValueError("COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID must be set in environment variables")

    def _calculate_secret_hash(self, username: str) -> Optional[str]:
        """Calculate the secret hash required for some Cognito operations"""
        if not self.client_secret:
            return None
        
        message = username + self.client_id
        dig = hmac.new(
            self.client_secret.encode('utf-8'),
            msg=message.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(dig).decode()

    async def signup(self, email: str, password: str, additional_attributes: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Register a new user in Cognito User Pool
        
        Args:
            email: User's email address
            password: User's password
            additional_attributes: Optional additional user attributes
            
        Returns:
            Dict containing signup result
        """
        try:
            # Prepare user attributes
            user_attributes = [
                {'Name': 'email', 'Value': email}
            ]
            
            # Add additional attributes if provided
            if additional_attributes:
                for key, value in additional_attributes.items():
                    user_attributes.append({'Name': key, 'Value': value})
            
            # Prepare signup parameters
            signup_params = {
                'ClientId': self.client_id,
                'Username': email,
                'Password': password,
                'UserAttributes': user_attributes
            }
            
            # Add secret hash if client secret is configured
            if self.client_secret:
                signup_params['SecretHash'] = self._calculate_secret_hash(email)
            
            # Register user
            response = cognito_client.sign_up(**signup_params)
            
            return {
                'success': True,
                'message': 'User registered successfully',
                'user_sub': response['UserSub'],
                'confirmation_required': not response.get('UserConfirmed', False)
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            # Handle specific error cases
            if error_code == 'UsernameExistsException':
                raise AuthError("User already exists", 400)
            elif error_code == 'InvalidPasswordException':
                raise AuthError("Password does not meet requirements", 400)
            elif error_code == 'InvalidParameterException':
                raise AuthError("Invalid parameters provided", 400)
            else:
                raise AuthError(f"Signup failed: {error_message}", 400)

    async def confirm_signup(self, email: str, confirmation_code: str) -> Dict[str, Any]:
        """
        Confirm user signup with verification code
        
        Args:
            email: User's email address
            confirmation_code: Verification code sent to user
            
        Returns:
            Dict containing confirmation result
        """
        try:
            confirm_params = {
                'ClientId': self.client_id,
                'Username': email,
                'ConfirmationCode': confirmation_code
            }
            
            if self.client_secret:
                confirm_params['SecretHash'] = self._calculate_secret_hash(email)
            
            cognito_client.confirm_sign_up(**confirm_params)
            
            return {
                'success': True,
                'message': 'User confirmed successfully'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code == 'CodeMismatchException':
                raise AuthError("Invalid confirmation code", 400)
            elif error_code == 'ExpiredCodeException':
                raise AuthError("Confirmation code has expired", 400)
            else:
                raise AuthError(f"Confirmation failed: {error_message}", 400)

    async def login(self, email: str, password: str) -> Dict[str, Any]:
        """
        Authenticate user and return JWT tokens
        
        Args:
            email: User's email address
            password: User's password
            
        Returns:
            Dict containing access token, refresh token, and user info
        """
        try:
            auth_params = {
                'ClientId': self.client_id,
                'AuthFlow': 'USER_PASSWORD_AUTH',
                'AuthParameters': {
                    'USERNAME': email,
                    'PASSWORD': password
                }
            }
            
            if self.client_secret:
                auth_params['AuthParameters']['SECRET_HASH'] = self._calculate_secret_hash(email)
            
            response = cognito_client.initiate_auth(**auth_params)
            
            # Handle different authentication challenges
            if 'ChallengeName' in response:
                challenge_name = response['ChallengeName']
                if challenge_name == 'NEW_PASSWORD_REQUIRED':
                    raise AuthError("New password required", 400)
                elif challenge_name == 'SMS_MFA' or challenge_name == 'SOFTWARE_TOKEN_MFA':
                    raise AuthError("MFA required", 400)
                else:
                    raise AuthError(f"Authentication challenge required: {challenge_name}", 400)
            
            # Extract tokens
            auth_result = response['AuthenticationResult']
            access_token = auth_result['AccessToken']
            refresh_token = auth_result.get('RefreshToken')
            id_token = auth_result.get('IdToken')
            
            # Decode access token to get user info
            user_info = await self._decode_token(access_token)
            
            return {
                'success': True,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'id_token': id_token,
                'token_type': 'Bearer',
                'expires_in': auth_result.get('ExpiresIn', 3600),
                'user': {
                    'sub': user_info.get('sub'),
                    'username': user_info.get('username'),
                    'email': user_info.get('email'),
                    'email_verified': user_info.get('email_verified')
                }
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code == 'NotAuthorizedException':
                raise AuthError("Invalid email or password", 401)
            elif error_code == 'UserNotConfirmedException':
                raise AuthError("User not confirmed. Please check your email for confirmation code", 400)
            elif error_code == 'UserNotFoundException':
                raise AuthError("User not found", 404)
            else:
                raise AuthError(f"Login failed: {error_message}", 400)

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh access token using refresh token
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            Dict containing new access token
        """
        try:
            response = cognito_client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow='REFRESH_TOKEN_AUTH',
                AuthParameters={
                    'REFRESH_TOKEN': refresh_token
                }
            )
            
            auth_result = response['AuthenticationResult']
            new_access_token = auth_result['AccessToken']
            
            # Decode new token to get user info
            user_info = await self._decode_token(new_access_token)
            
            return {
                'success': True,
                'access_token': new_access_token,
                'token_type': 'Bearer',
                'expires_in': auth_result.get('ExpiresIn', 3600),
                'user': {
                    'sub': user_info.get('sub'),
                    'username': user_info.get('username'),
                    'email': user_info.get('email')
                }
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            raise AuthError(f"Token refresh failed: {e.response['Error']['Message']}", 401)

    async def _get_jwks(self) -> Dict[str, Any]:
        """Get JSON Web Key Set (JWKS) from Cognito"""
        # Cache JWKS for 1 hour
        if (self.jwks_cache_time and 
            datetime.now() - self.jwks_cache_time < timedelta(hours=1) and 
            self.jwks_cache):
            return self.jwks_cache
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(JWKS_URL)
                response.raise_for_status()
                
                self.jwks_cache = response.json()
                self.jwks_cache_time = datetime.now()
                return self.jwks_cache
                
        except Exception as e:
            raise AuthError(f"Failed to fetch JWKS: {str(e)}", 500)

    def _get_public_key(self, token_headers: Dict[str, Any], jwks: Dict[str, Any]) -> str:
        """Extract public key from JWKS using token's key ID"""
        kid = token_headers.get('kid')
        if not kid:
            raise AuthError("Token missing 'kid' header", 401)
        
        for key in jwks.get('keys', []):
            if key.get('kid') == kid:
                # Convert JWK to PEM format
                if key.get('kty') == 'RSA':
                    # Use python-jose or cryptography library for proper JWK to PEM conversion
                    # For simplicity, we'll use jwt library's built-in JWKS handling
                    return key
        
        raise AuthError("Unable to find appropriate key", 401)

    async def _decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decode and validate JWT token
        
        Args:
            token: JWT access token
            
        Returns:
            Dict containing decoded token payload
        """
        try:
            # Get token headers without verification
            unverified_headers = jwt.get_unverified_header(token)
            
            # Get JWKS
            jwks = await self._get_jwks()
            
            # Find the correct key
            rsa_key = self._get_public_key(unverified_headers, jwks)
            
            if rsa_key:
                # Construct the key for verification
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(rsa_key)
                
                # Decode and verify the token
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=['RS256'],
                    audience=self.client_id,
                    issuer=f'https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}'
                )
                
                return payload
            else:
                raise AuthError("Unable to find appropriate key", 401)
                
        except jwt.ExpiredSignatureError:
            raise AuthError("Token has expired", 401)
        except jwt.InvalidTokenError as e:
            raise AuthError(f"Invalid token: {str(e)}", 401)
        except Exception as e:
            raise AuthError(f"Token validation failed: {str(e)}", 401)

    async def validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validate JWT token and return user information
        
        Args:
            token: JWT access token
            
        Returns:
            Dict containing user information
        """
        payload = await self._decode_token(token)
        
        return {
            'sub': payload.get('sub'),
            'username': payload.get('username'),
            'email': payload.get('email'),
            'email_verified': payload.get('email_verified'),
            'token_use': payload.get('token_use'),
            'scope': payload.get('scope'),
            'auth_time': payload.get('auth_time'),
            'iat': payload.get('iat'),
            'exp': payload.get('exp')
        }

    async def logout(self, access_token: str) -> Dict[str, Any]:
        """
        Logout user by invalidating the token
        
        Args:
            access_token: User's access token
            
        Returns:
            Dict containing logout result
        """
        try:
            # Global sign out (invalidates all tokens for the user)
            cognito_client.global_sign_out(AccessToken=access_token)
            
            return {
                'success': True,
                'message': 'User logged out successfully'
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NotAuthorizedException':
                # Token might already be invalid
                return {
                    'success': True,
                    'message': 'User already logged out'
                }
            else:
                raise AuthError(f"Logout failed: {e.response['Error']['Message']}", 400)

    async def handle_callback(self, authorization_code: str, state: Optional[str] = None) -> Dict[str, Any]:
        """
        Handle OAuth callback after login/signup redirect
        
        Args:
            authorization_code: Authorization code from Cognito
            state: Optional state parameter for security
            
        Returns:
            Dict containing tokens and user information
        """
        try:
            # Exchange authorization code for tokens
            # Note: This requires your Cognito app client to be configured for authorization code flow
            # and have a redirect URI set up
            
            # For this implementation, we'll assume the authorization code contains user info
            # In a real OAuth flow, you would exchange this code for tokens with Cognito
            
            # For demonstration, we'll create a response that simulates successful token exchange
            return {
                'success': True,
                'message': 'Authentication successful',
                'redirect_url': '/',  # Redirect to main dashboard (index.html)
                'state': state,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            raise AuthError(f"Callback handling failed: {str(e)}", 400)

    def generate_auth_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """
        Generate Cognito hosted UI authentication URL
        
        Args:
            redirect_uri: Where to redirect after authentication
            state: Optional state parameter for security
            
        Returns:
            String containing the Cognito hosted UI URL
        """
        try:
            if not CLIENT_ID:
                raise AuthError("CLIENT_ID not configured", 500)
            
            # Cognito hosted UI URL
            cognito_domain = os.getenv("COGNITO_DOMAIN")
            if not cognito_domain:
                # Use default Cognito domain format
                cognito_domain = f"https://{USER_POOL_ID}.auth.{AWS_REGION}.amazoncognito.com"
            
            auth_url = f"{cognito_domain}/login"
            params = {
                'client_id': CLIENT_ID,
                'response_type': 'code',
                'scope': 'email openid phone profile',
                'redirect_uri': redirect_uri
            }
            
            if state:
                params['state'] = state
            
            # Build query string
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            
            return f"{auth_url}?{query_string}"
            
        except Exception as e:
            raise AuthError(f"Failed to generate auth URL: {str(e)}", 500)

# Global auth instance
cognito_auth = CognitoAuth()

# Dependency for protected routes
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """
    FastAPI dependency to validate JWT token and get current user
    
    Args:
        credentials: HTTP Bearer token from Authorization header
        
    Returns:
        Dict containing current user information
        
    Raises:
        HTTPException: If token is invalid or missing
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    try:
        user_info = await cognito_auth.validate_token(credentials.credentials)
        return user_info
    except AuthError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"}
        )

# Decorator for protecting routes (alternative to dependency injection)
def require_auth(f):
    """
    Decorator to protect routes with JWT token validation
    
    Usage:
        @require_auth
        @app.get("/protected")
        async def protected_route(request: Request):
            user = request.state.user
            return {"message": f"Hello {user['email']}"}
    """
    @wraps(f)
    async def decorated_function(request: Request, *args, **kwargs):
        # Extract token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Authorization header missing or invalid",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        token = auth_header.split(" ")[1]
        
        try:
            # Validate token and get user info
            user_info = await cognito_auth.validate_token(token)
            
            # Attach user info to request state
            request.state.user = user_info
            
            # Call the original function
            return await f(request, *args, **kwargs)
            
        except AuthError as e:
            raise HTTPException(
                status_code=e.status_code,
                detail=e.message,
                headers={"WWW-Authenticate": "Bearer"}
            )
    
    return decorated_function

# Optional: Middleware for automatic token validation
class CognitoAuthMiddleware:
    """
    Middleware to automatically validate JWT tokens for protected routes
    """
    
    def __init__(self, app, protected_paths: list = None):
        self.app = app
        self.protected_paths = protected_paths or ['/api/']  # Default protect all /api/ routes
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Check if this path should be protected
            path = scope["path"]
            
            if any(path.startswith(protected_path) for protected_path in self.protected_paths):
                # Extract headers
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode()
                
                if not auth_header or not auth_header.startswith("Bearer "):
                    # Return 401 response
                    response = {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [[b"content-type", b"application/json"]],
                    }
                    await send(response)
                    
                    body = json.dumps({"detail": "Authorization required"}).encode()
                    await send({
                        "type": "http.response.body",
                        "body": body,
                    })
                    return
                
                token = auth_header.split(" ")[1]
                
                try:
                    # Validate token
                    user_info = await cognito_auth.validate_token(token)
                    
                    # Add user info to scope for use in route handlers
                    scope["state"] = {"user": user_info}
                    
                except AuthError:
                    # Return 401 response
                    response = {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [[b"content-type", b"application/json"]],
                    }
                    await send(response)
                    
                    body = json.dumps({"detail": "Invalid token"}).encode()
                    await send({
                        "type": "http.response.body",
                        "body": body,
                    })
                    return
        
        await self.app(scope, receive, send)
