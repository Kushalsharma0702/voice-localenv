#!/usr/bin/env python3
"""
AWS Cognito Configuration Helper
Helps configure Cognito app client settings for localhost and production
"""

print("🔧 AWS Cognito Configuration Guide")
print("=" * 50)

print("\n📋 STEP 1: Configure Cognito App Client for Production Domain")
print("1. Go to AWS Console → Cognito → User Pools")
print("2. Select your User Pool: ap-south-1_MYtre8r4L")
print("3. Go to 'App Integration' → 'App clients and analytics'")
print("4. Click on your app client: 6vvpsk667mdsq42kqlokc25il")
print("5. Click 'Edit' in the Hosted UI section")
print("6. Add these URLs:")
print("   📥 Allowed callback URLs:")
print("      - http://collections.intalksai.com/auth/callback")
print("      - https://c2299b13328d.ngrok-free.app/auth/callback  (current ngrok URL)")
print("      - http://localhost:8000/auth/callback  (for local development)")
print("   📤 Allowed sign-out URLs:")
print("      - http://collections.intalksai.com/")
print("      - https://c2299b13328d.ngrok-free.app/  (current ngrok URL)")
print("      - http://localhost:8000/  (for local development)")
print("7. Ensure these OAuth scopes are selected:")
print("   ✅ openid")
print("   ✅ email") 
print("   ✅ profile")
print("8. Ensure 'Authorization code grant' is selected")
print("9. Click 'Save changes'")

print("\n🚀 STEP 2: Test Production Domain")
print("1. Deploy your FastAPI server to collections.intalksai.com")
print("2. Visit http://collections.intalksai.com")
print("3. You should be redirected to Cognito login")
print("4. After login, you should be redirected back to your dashboard")

print("\n🌐 STEP 3: For Local Development (Optional)")
print("If you want to test locally:")
print("1. Update your .env file with localhost URLs:")
print("   COGNITO_REDIRECT_URI=\"http://localhost:8000/auth/callback\"")
print("   COGNITO_LOGOUT_URI=\"http://localhost:8000/\"")
print("2. Ensure localhost URLs are in Cognito app client settings")
print("3. Start your local server and test authentication")
print("4. Switch back to production URLs when deploying")

print("\n💡 How It Works:")
print("✅ User visits collections.intalksai.com → Redirected to Cognito hosted UI")
print("✅ User logs in with Cognito → Redirected back to your app")
print("✅ Your app receives auth code → Exchanges for tokens")
print("✅ User session created → Access granted to dashboard")

print("\n🔍 Current Configuration:")
print("- Production Domain: http://collections.intalksai.com")
print("- Cognito User Pool: ap-south-1_MYtre8r4L")
print("- Cognito App Client: 6vvpsk667mdsq42kqlokc25il")
print("- Cognito Domain: https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com")
print("- Production Callback: http://collections.intalksai.com/auth/callback")
print("- Database: AWS RDS (db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com)")

print("\n" + "=" * 50)
print("🎉 Follow these steps to complete the setup!")
