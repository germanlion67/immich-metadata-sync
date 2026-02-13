#!/usr/bin/env python3
"""
IMMICH ULTRA-SYNC Web Interface

A simple Flask web interface for managing and triggering sync operations.
This provides a basic UI to trigger sync operations and view status.
"""

import os
import sys
import subprocess
import json
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, Response
from flask_cors import CORS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SYNC_SCRIPT = os.path.join(SCRIPT_DIR, 'script', 'immich-ultra-sync.py')
LOG_FILE = os.environ.get('IMMICH_LOG_FILE', '/app/immich_ultra_sync.txt')
PORT = int(os.environ.get('FLASK_PORT', 5000))
HOST = os.environ.get('FLASK_HOST', '0.0.0.0')

# Global state for tracking sync status
sync_status = {
    'running': False,
    'last_run': None,
    'last_result': None,
    'process': None
}

# HTML template for the web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IMMICH ULTRA-SYNC - Web Interface</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .header h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 2.5em;
        }
        .header p {
            color: #666;
            font-size: 1.1em;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .card h2 {
            color: #333;
            margin-bottom: 20px;
            font-size: 1.5em;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        .status {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .status-item {
            flex: 1;
            min-width: 200px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        .status-item strong {
            display: block;
            color: #555;
            margin-bottom: 5px;
            font-size: 0.9em;
        }
        .status-item span {
            display: block;
            color: #333;
            font-size: 1.2em;
        }
        .running {
            border-left-color: #ffc107;
        }
        .success {
            border-left-color: #28a745;
        }
        .error {
            border-left-color: #dc3545;
        }
        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.3s ease;
            text-align: center;
            font-weight: 600;
            color: white;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
        }
        .btn:active {
            transform: translateY(0);
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .btn-secondary {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }
        .btn-success {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        }
        .btn-danger {
            background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
        }
        .options {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin-bottom: 20px;
        }
        .option-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 6px;
        }
        .option-item input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
        }
        .option-item label {
            cursor: pointer;
            color: #333;
            font-size: 0.95em;
        }
        .logs {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            border-radius: 8px;
            max-height: 500px;
            overflow-y: auto;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9em;
            line-height: 1.5;
        }
        .logs::-webkit-scrollbar {
            width: 10px;
        }
        .logs::-webkit-scrollbar-track {
            background: #2d2d2d;
            border-radius: 4px;
        }
        .logs::-webkit-scrollbar-thumb {
            background: #555;
            border-radius: 4px;
        }
        .logs::-webkit-scrollbar-thumb:hover {
            background: #666;
        }
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s ease-in-out infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
            margin-left: 10px;
        }
        .badge-running {
            background: #ffc107;
            color: #333;
        }
        .badge-idle {
            background: #6c757d;
            color: white;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📸 IMMICH ULTRA-SYNC <span class="badge" id="statusBadge">Idle</span></h1>
            <p>Web interface for managing metadata synchronization</p>
        </div>

        <div class="card">
            <h2>Current Status</h2>
            <div class="status">
                <div class="status-item" id="statusContainer">
                    <strong>Sync Status</strong>
                    <span id="syncStatus">Idle</span>
                </div>
                <div class="status-item">
                    <strong>Last Run</strong>
                    <span id="lastRun">Never</span>
                </div>
                <div class="status-item">
                    <strong>Last Result</strong>
                    <span id="lastResult">-</span>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Sync Options</h2>
            <div class="options">
                <div class="option-item">
                    <input type="checkbox" id="optPeople" checked>
                    <label for="optPeople">People</label>
                </div>
                <div class="option-item">
                    <input type="checkbox" id="optGps" checked>
                    <label for="optGps">GPS</label>
                </div>
                <div class="option-item">
                    <input type="checkbox" id="optCaption" checked>
                    <label for="optCaption">Caption</label>
                </div>
                <div class="option-item">
                    <input type="checkbox" id="optTime" checked>
                    <label for="optTime">Time</label>
                </div>
                <div class="option-item">
                    <input type="checkbox" id="optRating" checked>
                    <label for="optRating">Rating</label>
                </div>
                <div class="option-item">
                    <input type="checkbox" id="optAlbums" checked>
                    <label for="optAlbums">Albums</label>
                </div>
                <div class="option-item">
                    <input type="checkbox" id="optOnlyNew" checked>
                    <label for="optOnlyNew">Only New</label>
                </div>
                <div class="option-item">
                    <input type="checkbox" id="optDryRun">
                    <label for="optDryRun">Dry Run</label>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Actions</h2>
            <div class="controls">
                <button class="btn btn-primary" onclick="runSync()">▶️ Run Sync</button>
                <button class="btn btn-secondary" onclick="runSyncAll()">🔄 Sync All</button>
                <button class="btn btn-success" onclick="refreshStatus()">📊 Refresh Status</button>
                <button class="btn btn-danger" onclick="clearLogs()">🗑️ Clear Logs</button>
            </div>
        </div>

        <div class="card">
            <h2>Logs</h2>
            <div class="logs" id="logs">Loading logs...</div>
        </div>
    </div>

    <script>
        let autoRefreshInterval;

        async function fetchStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                document.getElementById('syncStatus').textContent = data.running ? 'Running' : 'Idle';
                document.getElementById('lastRun').textContent = data.last_run || 'Never';
                document.getElementById('lastResult').textContent = data.last_result || '-';
                
                const statusContainer = document.getElementById('statusContainer');
                const statusBadge = document.getElementById('statusBadge');
                statusContainer.className = 'status-item ' + (data.running ? 'running' : '');
                statusBadge.className = 'badge ' + (data.running ? 'badge-running' : 'badge-idle');
                statusBadge.textContent = data.running ? 'Running' : 'Idle';
                
                if (data.running) {
                    statusBadge.innerHTML = '<span class="spinner"></span> Running';
                }
            } catch (error) {
                console.error('Error fetching status:', error);
            }
        }

        async function fetchLogs() {
            try {
                const response = await fetch('/api/logs');
                const data = await response.json();
                document.getElementById('logs').textContent = data.logs || 'No logs available';
            } catch (error) {
                console.error('Error fetching logs:', error);
                document.getElementById('logs').textContent = 'Error loading logs: ' + error.message;
            }
        }

        function getSelectedOptions() {
            const options = [];
            if (document.getElementById('optPeople').checked) options.push('--people');
            if (document.getElementById('optGps').checked) options.push('--gps');
            if (document.getElementById('optCaption').checked) options.push('--caption');
            if (document.getElementById('optTime').checked) options.push('--time');
            if (document.getElementById('optRating').checked) options.push('--rating');
            if (document.getElementById('optAlbums').checked) options.push('--albums');
            if (document.getElementById('optOnlyNew').checked) options.push('--only-new');
            if (document.getElementById('optDryRun').checked) options.push('--dry-run');
            return options;
        }

        async function runSync() {
            const options = getSelectedOptions();
            if (options.length === 0 || (options.length === 1 && options[0] === '--only-new') || 
                (options.length === 1 && options[0] === '--dry-run') ||
                (options.length === 2 && options.includes('--only-new') && options.includes('--dry-run'))) {
                alert('Please select at least one sync option (People, GPS, Caption, Time, Rating, or Albums)');
                return;
            }
            
            try {
                const response = await fetch('/api/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ options })
                });
                const data = await response.json();
                alert(data.message);
                refreshStatus();
                startAutoRefresh();
            } catch (error) {
                alert('Error starting sync: ' + error.message);
            }
        }

        async function runSyncAll() {
            const additionalOptions = [];
            if (document.getElementById('optOnlyNew').checked) additionalOptions.push('--only-new');
            if (document.getElementById('optDryRun').checked) additionalOptions.push('--dry-run');
            
            try {
                const response = await fetch('/api/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ options: ['--all', ...additionalOptions] })
                });
                const data = await response.json();
                alert(data.message);
                refreshStatus();
                startAutoRefresh();
            } catch (error) {
                alert('Error starting sync: ' + error.message);
            }
        }

        async function clearLogs() {
            try {
                const response = await fetch('/api/clear-logs', { method: 'POST' });
                const data = await response.json();
                alert(data.message);
                fetchLogs();
            } catch (error) {
                alert('Error clearing logs: ' + error.message);
            }
        }

        function refreshStatus() {
            fetchStatus();
            fetchLogs();
        }

        function startAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
            }
            autoRefreshInterval = setInterval(() => {
                fetchStatus();
                fetchLogs();
            }, 3000);
        }

        function stopAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }
        }

        // Initial load
        refreshStatus();
        startAutoRefresh();

        // Stop auto-refresh when page is hidden
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                stopAutoRefresh();
            } else {
                startAutoRefresh();
            }
        });
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    """Serve the main web interface."""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/status')
def get_status():
    """Get current sync status."""
    # Check if process is still running
    if sync_status['process'] is not None:
        retcode = sync_status['process'].poll()
        if retcode is not None:
            # Process has finished
            sync_status['running'] = False
            sync_status['last_result'] = 'Success' if retcode == 0 else f'Failed (exit code {retcode})'
            sync_status['process'] = None
    
    return jsonify({
        'running': sync_status['running'],
        'last_run': sync_status['last_run'],
        'last_result': sync_status['last_result']
    })


@app.route('/api/logs')
def get_logs():
    """Get sync logs."""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                # Get last 100 lines
                lines = f.readlines()
                logs = ''.join(lines[-100:])
        else:
            logs = 'No log file found'
    except Exception as e:
        logs = f'Error reading logs: {str(e)}'
    
    return jsonify({'logs': logs})


@app.route('/api/sync', methods=['POST'])
def start_sync():
    """Start a sync operation."""
    if sync_status['running']:
        return jsonify({'error': 'Sync already running'}), 400
    
    try:
        data = request.get_json()
        options = data.get('options', [])
        
        # Validate options
        valid_options = [
            '--all', '--people', '--gps', '--caption', '--time', '--rating', 
            '--albums', '--only-new', '--dry-run', '--face-coordinates'
        ]
        for opt in options:
            if opt not in valid_options:
                return jsonify({'error': f'Invalid option: {opt}'}), 400
        
        # Build command
        cmd = ['python3', SYNC_SCRIPT] + options
        
        # Start process
        logger.info(f'Starting sync with command: {" ".join(cmd)}')
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Update status
        sync_status['running'] = True
        sync_status['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sync_status['process'] = process
        
        return jsonify({'message': 'Sync started successfully'})
    
    except Exception as e:
        logger.error(f'Error starting sync: {str(e)}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/clear-logs', methods=['POST'])
def clear_logs():
    """Clear log file."""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'w') as f:
                f.write('')
        return jsonify({'message': 'Logs cleared successfully'})
    except Exception as e:
        logger.error(f'Error clearing logs: {str(e)}')
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})


if __name__ == '__main__':
    logger.info(f'Starting IMMICH ULTRA-SYNC Web Interface on {HOST}:{PORT}')
    logger.info(f'Sync script: {SYNC_SCRIPT}')
    logger.info(f'Log file: {LOG_FILE}')
    app.run(host=HOST, port=PORT, debug=False)
