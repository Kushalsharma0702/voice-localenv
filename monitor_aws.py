#!/usr/bin/env python3
"""
AWS Production Monitoring Script
Monitors Voice Assistant application health and performance
"""

import os
import time
import json
import requests
import psutil
import subprocess
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv('BASE_URL', 'https://31cafa13a316.ngrok-free.app')

def check_system_resources():
    """Check system CPU, memory, and disk usage"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        'cpu_percent': cpu_percent,
        'memory_percent': memory.percent,
        'memory_available_gb': round(memory.available / (1024**3), 2),
        'disk_percent': disk.percent,
        'disk_free_gb': round(disk.free / (1024**3), 2)
    }

def check_service_status():
    """Check systemd service status"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'voice-assistant'],
            capture_output=True,
            text=True
        )
        return result.stdout.strip() == 'active'
    except:
        return False

def check_port_listening():
    """Check if port 8000 is listening"""
    try:
        result = subprocess.run(
            ['netstat', '-tlnp'],
            capture_output=True,
            text=True
        )
        return ':8000' in result.stdout
    except:
        return False

def check_application_health():
    """Check application health endpoint"""
    try:
        response = requests.get(f'{BASE_URL}/health', timeout=10)
        if response.status_code == 200:
            return True, response.json()
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)

def check_redis_status():
    """Check Redis server status"""
    try:
        result = subprocess.run(
            ['redis-cli', 'ping'],
            capture_output=True,
            text=True
        )
        return result.stdout.strip() == 'PONG'
    except:
        return False

def check_database_connection():
    """Check database connectivity"""
    try:
        import psycopg2
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return False, "DATABASE_URL not set"
        
        conn = psycopg2.connect(db_url)
        conn.close()
        return True, "Connected"
    except Exception as e:
        return False, str(e)

def get_recent_logs():
    """Get recent application logs"""
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'voice-assistant', '--lines=10', '--no-pager'],
            capture_output=True,
            text=True
        )
        return result.stdout
    except:
        return "Unable to fetch logs"

def generate_report():
    """Generate comprehensive monitoring report"""
    timestamp = datetime.now()
    
    print("=" * 60)
    print(f"🔍 Voice Assistant Monitoring Report")
    print(f"⏰ Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 Server: 3.108.35.213:8000")
    print("=" * 60)
    
    # System Resources
    print("\n📊 SYSTEM RESOURCES")
    print("-" * 30)
    resources = check_system_resources()
    print(f"CPU Usage: {resources['cpu_percent']}%")
    print(f"Memory Usage: {resources['memory_percent']}% ({resources['memory_available_gb']} GB available)")
    print(f"Disk Usage: {resources['disk_percent']}% ({resources['disk_free_gb']} GB free)")
    
    # Service Status
    print("\n⚙️  SERVICE STATUS")
    print("-" * 30)
    service_active = check_service_status()
    port_listening = check_port_listening()
    redis_running = check_redis_status()
    
    print(f"Voice Assistant Service: {'✅ ACTIVE' if service_active else '❌ INACTIVE'}")
    print(f"Port 8000 Listening: {'✅ YES' if port_listening else '❌ NO'}")
    print(f"Redis Server: {'✅ RUNNING' if redis_running else '❌ STOPPED'}")
    
    # Application Health
    print("\n🏥 APPLICATION HEALTH")
    print("-" * 30)
    health_ok, health_data = check_application_health()
    if health_ok:
        print("✅ Application: HEALTHY")
        if isinstance(health_data, dict):
            services = health_data.get('services', {})
            for service, status in services.items():
                status_icon = "✅" if status == "healthy" else "❌"
                print(f"   {service.title()}: {status_icon} {status}")
    else:
        print(f"❌ Application: UNHEALTHY - {health_data}")
    
    # Database Connection
    print("\n🗄️  DATABASE")
    print("-" * 30)
    db_ok, db_msg = check_database_connection()
    print(f"PostgreSQL Connection: {'✅' if db_ok else '❌'} {db_msg}")
    
    # Quick Log Check
    print("\n📝 RECENT LOGS (Last 10 lines)")
    print("-" * 30)
    recent_logs = get_recent_logs()
    for line in recent_logs.split('\n')[-10:]:
        if line.strip():
            print(f"   {line}")
    
    # Recommendations
    print("\n💡 RECOMMENDATIONS")
    print("-" * 30)
    if not service_active:
        print("⚠️  Start the service: sudo systemctl start voice-assistant")
    if not port_listening:
        print("⚠️  Check if another process is using port 8000")
    if not redis_running:
        print("⚠️  Start Redis: sudo systemctl start redis-server")
    if not health_ok:
        print("⚠️  Check application logs: journalctl -u voice-assistant -f")
    if resources['cpu_percent'] > 80:
        print("⚠️  High CPU usage detected")
    if resources['memory_percent'] > 80:
        print("⚠️  High memory usage detected")
    if resources['disk_percent'] > 80:
        print("⚠️  Low disk space detected")
    
    print("\n" + "=" * 60)
    print("🎉 Monitoring complete!")

def continuous_monitoring(interval=300):
    """Run continuous monitoring every 5 minutes"""
    print(f"🔄 Starting continuous monitoring (every {interval//60} minutes)")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            generate_report()
            print(f"\n⏱️  Next check in {interval//60} minutes...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped by user")

def main():
    """Main function"""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--continuous':
        continuous_monitoring()
    else:
        generate_report()
        print("\n💡 Run with --continuous for continuous monitoring")

if __name__ == "__main__":
    main()
