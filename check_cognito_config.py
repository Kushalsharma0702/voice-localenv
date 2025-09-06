#!/usr/bin/env python3
"""
Comprehensive Cognito Client Configuration Checker
Checks all aspects of the Cognito app client configuration
"""
import os
import boto3
import json
from dotenv import load_dotenv

load_dotenv()

def check_cognito_client_config():
    """Check complete Cognito app client configuration"""
    
    print("🔍 Comprehensive Cognito App Client Configuration Check")
    print("=" * 70)
    
    # Environment variables
    region = os.getenv("COGNITO_REGION", "ap-south-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    client_id = os.getenv("COGNITO_CLIENT_ID")
    client_secret = os.getenv("COGNITO_CLIENT_SECRET")
    domain = "https://collections.intalksai.com"
    
    print(f"🌍 Domain: {domain}")
    print(f"📍 Region: {region}")
    print(f"🏊 User Pool ID: {user_pool_id}")
    print(f"📱 Client ID: {client_id}")
    print(f"🔐 Client Secret: {'Set' if client_secret else 'Not Set'}")
    
    try:
        # Initialize Cognito client
        cognito_client = boto3.client('cognito-idp', region_name=region)
        
        # Get app client configuration
        print(f"\n🔍 Getting app client configuration...")
        response = cognito_client.describe_user_pool_client(
            UserPoolId=user_pool_id,
            ClientId=client_id
        )
        
        client_config = response['UserPoolClient']
        
        print(f"\n📋 Complete App Client Configuration:")
        print(f"   🏷️  Client Name: {client_config.get('ClientName')}")
        print(f"   🔐 Generate Secret: {client_config.get('GenerateSecret', False)}")
        print(f"   ⏰ Refresh Token Validity: {client_config.get('RefreshTokenValidity')} days")
        print(f"   🎫 Access Token Validity: {client_config.get('AccessTokenValidity')} minutes")
        print(f"   🆔 ID Token Validity: {client_config.get('IdTokenValidity')} minutes")
        
        # OAuth Configuration
        print(f"\n🔄 OAuth Configuration:")
        oauth_flows = client_config.get('AllowedOAuthFlows', [])
        oauth_scopes = client_config.get('AllowedOAuthScopes', [])
        oauth_enabled = client_config.get('AllowedOAuthFlowsUserPoolClient', False)
        
        print(f"   ✅ OAuth Flows: {oauth_flows}")
        print(f"   📦 OAuth Scopes: {oauth_scopes}")
        print(f"   🌐 OAuth Enabled: {oauth_enabled}")
        
        # URLs Configuration
        print(f"\n🔗 URL Configuration:")
        callback_urls = client_config.get('CallbackURLs', [])
        logout_urls = client_config.get('LogoutURLs', [])
        
        print(f"   📞 Callback URLs:")
        for url in callback_urls:
            status = "✅" if url.startswith("https://collections.intalksai.com") else "⚠️"
            print(f"      {status} {url}")
        
        print(f"   🚪 Logout URLs:")
        for url in logout_urls:
            status = "✅" if url.startswith("https://collections.intalksai.com") else "⚠️"
            print(f"      {status} {url}")
        
        # Identity Providers
        print(f"\n🆔 Identity Providers:")
        providers = client_config.get('SupportedIdentityProviders', [])
        for provider in providers:
            print(f"   ✅ {provider}")
        
        # Auth Flows
        print(f"\n🔐 Explicit Auth Flows:")
        auth_flows = client_config.get('ExplicitAuthFlows', [])
        for flow in auth_flows:
            print(f"   ✅ {flow}")
        
        # Check for common issues
        print(f"\n🚨 Issue Detection:")
        issues = []
        
        # Check OAuth flows
        if 'code' not in oauth_flows:
            issues.append("Missing 'code' in AllowedOAuthFlows")
        
        # Check OAuth enabled
        if not oauth_enabled:
            issues.append("AllowedOAuthFlowsUserPoolClient is False")
        
        # Check callback URL
        expected_callback = f"{domain}/auth/callback"
        if expected_callback not in callback_urls:
            issues.append(f"Missing callback URL: {expected_callback}")
        
        # Check OAuth scopes
        required_scopes = ['email', 'openid', 'profile']
        missing_scopes = [scope for scope in required_scopes if scope not in oauth_scopes]
        if missing_scopes:
            issues.append(f"Missing OAuth scopes: {missing_scopes}")
        
        # Check secret configuration
        generate_secret = client_config.get('GenerateSecret', False)
        has_secret = bool(client_secret)
        
        if generate_secret and not has_secret:
            issues.append("App client is configured to generate secret but COGNITO_CLIENT_SECRET is not set")
        elif not generate_secret and has_secret:
            issues.append("App client is configured as public (no secret) but COGNITO_CLIENT_SECRET is set")
        
        if issues:
            print(f"   ❌ Found {len(issues)} issues:")
            for issue in issues:
                print(f"      • {issue}")
        else:
            print(f"   ✅ No configuration issues found!")
        
        # Test the auth URL generation
        print(f"\n🧪 Testing Auth URL Generation:")
        from urllib.parse import urlencode
        
        auth_url = f"https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com/oauth2/authorize"
        params = {
            "client_id": client_id,
            "response_type": "code",
            "scope": "email openid profile",
            "redirect_uri": f"{domain}/auth/callback",
            "state": "test"
        }
        full_auth_url = auth_url + "?" + urlencode(params)
        
        print(f"   🔗 Generated Auth URL:")
        print(f"      {full_auth_url}")
        
        # Recommendations
        print(f"\n💡 Recommendations:")
        if generate_secret:
            print(f"   • App client is configured with secret - use Basic Auth for token exchange")
        else:
            print(f"   • App client is public - use client_id only for token exchange")
        
        print(f"   • Test the auth URL manually in a browser")
        print(f"   • Check that the domain {domain} is accessible via HTTPS")
        print(f"   • Verify that the callback handler is working at {domain}/auth/callback")
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking configuration: {str(e)}")
        return False

if __name__ == "__main__":
    check_cognito_client_config()
