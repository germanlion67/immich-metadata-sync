#!/usr/bin/env python3
"""
IMMICH ULTRA-SYNC Web Interface

A simple Flask web interface for managing Immich metadata sync operations.
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory

# Add script directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'script'))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# Global variable to store sync status
sync_status = {
    'running': False,
    'last_run': None,
    'last_result': None,
    'last_log': ''
}

SCRIPT_DIR = Path(__file__).parent / 'script'
SYNC_SCRIPT = SCRIPT_DIR / 'immich-ultra-sync.py'


@app.route('/')
def index():
    """Main page with sync controls."""
    return render_template('index.html', status=sync_status)


@app.route('/api/status')
def get_status():
    """Get current sync status."""
    return jsonify(sync_status)


@app.route('/api/sync', methods=['POST'])
def trigger_sync():
    """Trigger a sync operation."""
    global sync_status
    
    if sync_status['running']:
        return jsonify({'error': 'Sync already running'}), 409
    
    # Get sync options from request
    data = request.get_json() or {}
    dry_run = data.get('dry_run', False)
    only_new = data.get('only_new', True)
    albums = data.get('albums', False)
    face_coordinates = data.get('face_coordinates', False)
    
    # Build command
    cmd = ['python3', str(SYNC_SCRIPT), '--all']
    
    if dry_run:
        cmd.append('--dry-run')
    if only_new:
        cmd.append('--only-new')
    if albums:
        cmd.append('--albums')
    if face_coordinates:
        cmd.append('--face-coordinates')
    
    try:
        sync_status['running'] = True
        sync_status['last_run'] = datetime.now().isoformat()
        
        # Run sync in background
        result = subprocess.run(
            cmd,
            cwd=SCRIPT_DIR.parent,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        sync_status['running'] = False
        sync_status['last_result'] = 'success' if result.returncode == 0 else 'error'
        sync_status['last_log'] = result.stdout + result.stderr
        
        return jsonify({
            'status': 'completed',
            'result': sync_status['last_result'],
            'output': sync_status['last_log']
        })
        
    except subprocess.TimeoutExpired:
        sync_status['running'] = False
        sync_status['last_result'] = 'timeout'
        sync_status['last_log'] = 'Sync operation timed out after 1 hour'
        return jsonify({'error': 'Sync timed out'}), 500
        
    except Exception as e:
        sync_status['running'] = False
        sync_status['last_result'] = 'error'
        sync_status['last_log'] = str(e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/logs')
def get_logs():
    """Get recent log entries."""
    log_file = os.environ.get('IMMICH_LOG_FILE', 'immich_ultra_sync.txt')
    
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                # Get last 100 lines
                lines = f.readlines()
                recent_lines = lines[-100:] if len(lines) > 100 else lines
                return jsonify({'logs': ''.join(recent_lines)})
        else:
            return jsonify({'logs': 'No log file found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'version': '1.5.0',
        'sync_running': sync_status['running']
    })


if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    templates_dir = Path(__file__).parent / 'templates'
    templates_dir.mkdir(exist_ok=True)
    
    # Run the Flask app
    port = int(os.environ.get('FLASK_PORT', 5000))
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    
    print(f"Starting IMMICH ULTRA-SYNC Web Interface on {host}:{port}")
    print(f"Open http://localhost:{port} in your browser")
    
    app.run(host=host, port=port, debug=debug)
