#!/usr/bin/env python3
"""
HTTPS Server for Next Train App
Usage: python3 serve_https.py [port]
Default port: 8443
"""

import http.server
import ssl
import socketserver
import os
import sys
import tempfile
import subprocess
from pathlib import Path

def create_self_signed_cert(cert_path, key_path):
    """Create a self-signed certificate for localhost"""
    cmd = [
        'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
        '-keyout', key_path, '-out', cert_path,
        '-days', '365', '-nodes',
        '-subj', '/C=CN/ST=Beijing/L=Beijing/O=LocalDev/OU=IT/CN=localhost'
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✓ Created SSL certificate: {cert_path}")
        print(f"✓ Created SSL key: {key_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create SSL certificate: {e}")
        return False
    except FileNotFoundError:
        print("✗ OpenSSL not found. Please install OpenSSL to use HTTPS.")
        return False

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8443
    
    # Certificate paths
    temp_dir = tempfile.gettempdir()
    cert_path = os.path.join(temp_dir, 'server.crt')
    key_path = os.path.join(temp_dir, 'server.key')
    
    # Create certificate if it doesn't exist
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        print("Creating SSL certificate...")
        if not create_self_signed_cert(cert_path, key_path):
            print("Falling back to HTTP...")
            port = 8000 if port == 8443 else port
            
    print(f'Starting {"HTTPS" if os.path.exists(cert_path) else "HTTP"} server...')
    print(f'Port: {port}')
    print(f'Directory: {os.getcwd()}')
    print(f'URL: {"https" if os.path.exists(cert_path) else "http"}://localhost:{port}/')
    print('-' * 50)
    
    # Create server
    Handler = http.server.SimpleHTTPRequestHandler
    
    with socketserver.TCPServer(('', port), Handler) as httpd:
        if os.path.exists(cert_path) and os.path.exists(key_path):
            # Setup SSL
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            
        print(f'✓ Server running at {"https" if os.path.exists(cert_path) else "http"}://localhost:{port}/')
        print('Press Ctrl+C to stop')
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n✓ Server stopped')

if __name__ == '__main__':
    main()