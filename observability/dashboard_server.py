#!/usr/bin/env python3
"""
Real-time Dashboard Server for SSH Benchmark Monitoring
Provides web-based visualization of metrics and alerts
"""

import json
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

try:
    from flask import Flask, render_template, jsonify, send_from_directory
    from flask_socketio import SocketIO, emit
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    print("Flask and Flask-SocketIO required for dashboard. Install with:")
    print("pip install flask flask-socketio")

class DashboardServer:
    """Web-based dashboard server"""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8050):
        if not HAS_FLASK:
            raise ImportError("Required packages not installed")
        
        self.host = host
        self.port = port
        self.app = Flask(__name__, 
                        static_folder='static',
                        template_folder='templates')
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        
        # Data storage
        self.metrics_history: Dict[str, List] = {
            'cpu': [],
            'memory': [],
            'network': [],
            'ssh_connections': [],
            'file_transfers': [],
            'errors': []
        }
        
        self.alerts: List[Dict] = []
        self.experiments: List[Dict] = []
        
        # Setup routes
        self._setup_routes()
        self._setup_socket_handlers()
        
        # Background updater
        self.update_thread = None
        self.running = False
        
        self.logger = self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging"""
        logger = logging.getLogger("Dashboard")
        logger.setLevel(logging.INFO)
        
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)8s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    def _setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            return render_template('index.html')
        
        @self.app.route('/api/metrics')
        def get_metrics():
            """Get current metrics"""
            return jsonify({
                'timestamp': datetime.now().isoformat(),
                'metrics': self._get_current_metrics(),
                'history': {k: v[-100:] for k, v in self.metrics_history.items()}  # Last 100 points
            })
        
        @self.app.route('/api/alerts')
        def get_alerts():
            """Get alerts"""
            return jsonify({
                'alerts': self.alerts[-50:],  # Last 50 alerts
                'count': len(self.alerts),
                'unacknowledged': len([a for a in self.alerts if not a.get('acknowledged', False)])
            })
        
        @self.app.route('/api/experiments')
        def get_experiments():
            """Get experiment status"""
            return jsonify({
                'experiments': self.experiments,
                'active': len([e for e in self.experiments if e.get('status') == 'running']),
                'completed': len([e for e in self.experiments if e.get('status') == 'completed'])
            })
        
        @self.app.route('/api/system/info')
        def get_system_info():
            """Get system information"""
            try:
                import psutil
                import socket
                
                info = {
                    'hostname': socket.gethostname(),
                    'cpu_count': psutil.cpu_count(),
                    'memory_total_gb': psutil.virtual_memory().total / 1024 / 1024 / 1024,
                    'disk_total_gb': psutil.disk_usage('/').total / 1024 / 1024 / 1024,
                    'boot_time': datetime.fromtimestamp(psutil.boot_time()).isoformat(),
                    'platform': 'Unknown'
                }
                
                # Try to get more info
                try:
                    import platform
                    info['platform'] = f"{platform.system()} {platform.release()}"
                except:
                    pass
                
                return jsonify(info)
                
            except Exception as e:
                return jsonify({'error': str(e)})
        
        @self.app.route('/dashboard')
        def dashboard():
            return render_template('dashboard.html')
        
        @self.app.route('/alerts')
        def alerts_page():
            return render_template('alerts.html')
        
        @self.app.route('/experiments')
        def experiments_page():
            return render_template('experiments.html')
    
    def _setup_socket_handlers(self):
        """Setup SocketIO event handlers"""
        
        @self.socketio.on('connect')
        def handle_connect():
            self.logger.info(f"Client connected: {request.sid}")
            emit('connected', {'message': 'Connected to benchmark dashboard'})
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            self.logger.info(f"Client disconnected: {request.sid}")
        
        @self.socketio.on('request_update')
        def handle_request_update():
            """Client requests immediate update"""
            self._broadcast_update()
        
        @self.socketio.on('acknowledge_alert')
        def handle_acknowledge_alert(alert_id):
            """Client acknowledges an alert"""
            for alert in self.alerts:
                if alert.get('id') == alert_id:
                    alert['acknowledged'] = True
                    alert['acknowledged_at'] = datetime.now().isoformat()
                    alert['acknowledged_by'] = 'dashboard'
                    break
            
            # Broadcast updated alerts
            self.socketio.emit('alerts_updated', {
                'alerts': self.alerts[-20:],
                'timestamp': datetime.now().isoformat()
            })
    
    def _get_current_metrics(self) -> Dict:
        """Get current system metrics"""
        metrics = {}
        
        try:
            import psutil
            
            # CPU
            cpu_percent = psutil.cpu_percent(interval=None, percpu=True)
            metrics['cpu'] = {
                'percent_total': sum(cpu_percent) / len(cpu_percent) if cpu_percent else 0,
                'percent_per_core': cpu_percent,
                'load_avg': psutil.getloadavg()
            }
            
            # Memory
            memory = psutil.virtual_memory()
            metrics['memory'] = {
                'total_gb': memory.total / 1024 / 1024 / 1024,
                'used_gb': memory.used / 1024 / 1024 / 1024,
                'percent': memory.percent
            }
            
            # Disk
            disk = psutil.disk_usage('/')
            metrics['disk'] = {
                'total_gb': disk.total / 1024 / 1024 / 1024,
                'used_gb': disk.used / 1024 / 1024 / 1024,
                'percent': disk.percent
            }
            
            # Network
            net_io = psutil.net_io_counters()
            metrics['network'] = {
                'bytes_sent_mb': net_io.bytes_sent / 1024 / 1024,
                'bytes_recv_mb': net_io.bytes_recv / 1024 / 1024,
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv
            }
            
            # Processes
            metrics['processes'] = {
                'total': len(psutil.pids()),
                'ansible': len([p for p in psutil.process_iter(['name']) 
                               if 'ansible' in str(p.info.get('name', '')).lower()]),
                'ssh': len([p for p in psutil.process_iter(['name']) 
                           if 'ssh' in str(p.info.get('name', '')).lower()])
            }
            
            # Add timestamp
            metrics['timestamp'] = datetime.now().isoformat()
            
        except Exception as e:
            self.logger.error(f"Error getting metrics: {e}")
            metrics['error'] = str(e)
        
        return metrics
    
    def _update_metrics_history(self):
        """Update metrics history"""
        try:
            metrics = self._get_current_metrics()
            timestamp = datetime.now()
            
            # Add to history (with timestamp)
            if 'cpu' in metrics:
                self.metrics_history['cpu'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': metrics['cpu']['percent_total']
                })
            
            if 'memory' in metrics:
                self.metrics_history['memory'].append({
                    'timestamp': timestamp.isoformat(),
                    'value': metrics['memory']['percent']
                })
            
            if 'network' in metrics:
                self.metrics_history['network'].append({
                    'timestamp': timestamp.isoformat(),
                    'bytes_sent': metrics['network']['bytes_sent_mb'],
                    'bytes_recv': metrics['network']['bytes_recv_mb']
                })
            
            # Keep history manageable (last hour at 1-second resolution = 3600 points)
            for key in self.metrics_history:
                if len(self.metrics_history[key]) > 3600:
                    self.metrics_history[key] = self.metrics_history[key][-3600:]
                    
        except Exception as e:
            self.logger.error(f"Error updating metrics history: {e}")
    
    def _broadcast_update(self):
        """Broadcast update to all connected clients"""
        try:
            # Get current data
            data = {
                'metrics': self._get_current_metrics(),
                'alerts_count': len(self.alerts),
                'experiments_active': len([e for e in self.experiments if e.get('status') == 'running']),
                'timestamp': datetime.now().isoformat()
            }
            
            # Emit to all clients
            self.socketio.emit('update', data)
            
        except Exception as e:
            self.logger.error(f"Error broadcasting update: {e}")
    
    def add_alert(self, alert: Dict):
        """Add an alert to the dashboard"""
        alert['timestamp'] = datetime.now().isoformat()
        alert['id'] = f"alert_{int(time.time())}_{len(self.alerts)}"
        
        self.alerts.append(alert)
        
        # Keep only last 100 alerts
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]
        
        # Broadcast new alert
        self.socketio.emit('new_alert', alert)
        
        self.logger.info(f"Alert added: {alert.get('title', 'Unknown')}")
    
    def add_experiment(self, experiment: Dict):
        """Add/update an experiment"""
        # Check if experiment already exists
        for i, exp in enumerate(self.experiments):
            if exp.get('id') == experiment.get('id'):
                self.experiments[i].update(experiment)
                break
        else:
            self.experiments.append(experiment)
        
        # Keep only recent experiments
        if len(self.experiments) > 20:
            self.experiments = self.experiments[-20:]
        
        # Broadcast experiment update
        self.socketio.emit('experiment_update', experiment)
    
    def _background_updater(self):
        """Background thread for updating metrics"""
        while self.running:
            try:
                # Update metrics history
                self._update_metrics_history()
                
                # Broadcast update to clients
                self._broadcast_update()
                
                time.sleep(1)  # Update every second
                
            except Exception as e:
                self.logger.error(f"Error in background updater: {e}")
                time.sleep(5)
    
    def start(self):
        """Start the dashboard server"""
        if self.running:
            self.logger.warning("Dashboard already running")
            return
        
        self.running = True
        
        # Start background updater
        self.update_thread = threading.Thread(target=self._background_updater, daemon=True)
        self.update_thread.start()
        
        # Create templates directory if it doesn't exist
        templates_dir = Path(__file__).parent / 'templates'
        templates_dir.mkdir(exist_ok=True)
        
        static_dir = Path(__file__).parent / 'static'
        static_dir.mkdir(exist_ok=True)
        
        # Create basic HTML templates
        self._create_templates()
        
        self.logger.info(f"Starting dashboard server on http://{self.host}:{self.port}")
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False)
    
    def stop(self):
        """Stop the dashboard server"""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=5)
        
        self.logger.info("Dashboard server stopped")
    
    def _create_templates(self):
        """Create HTML templates for the dashboard"""
        templates_dir = Path(__file__).parent / 'templates'
        static_dir = Path(__file__).parent / 'static'
        
        # Create index.html
        index_html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SSH Benchmark Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            min-height: 100vh;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 10px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        h1 {
            color: #2d3748;
            font-size: 2.5rem;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 15px;
        }
        h1 i { color: #667eea; }
        .subtitle {
            color: #718096;
            font-size: 1.1rem;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 10px;
            padding: 25px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            transition: transform 0.3s ease;
        }
        .stat-card:hover {
            transform: translateY(-5px);
        }
        .stat-title {
            color: #718096;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }
        .stat-value {
            font-size: 2.5rem;
            font-weight: bold;
            color: #2d3748;
        }
        .stat-change {
            font-size: 0.9rem;
            margin-top: 5px;
        }
        .positive { color: #48bb78; }
        .negative { color: #f56565; }
        .charts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .chart-container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 10px;
            padding: 25px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .chart-title {
            color: #2d3748;
            font-size: 1.2rem;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .alerts-container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 10px;
            padding: 25px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            margin-bottom: 30px;
        }
        .alert {
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            border-left: 4px solid;
        }
        .alert-critical { border-color: #f56565; background: #fff5f5; }
        .alert-warning { border-color: #ed8936; background: #fffaf0; }
        .alert-info { border-color: #4299e1; background: #ebf8ff; }
        .nav-bar {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .nav-button {
            padding: 12px 24px;
            background: rgba(255, 255, 255, 0.9);
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            color: #4a5568;
            transition: all 0.3s ease;
        }
        .nav-button:hover {
            background: #ffffff;
            transform: translateY(-2px);
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .nav-button.active {
            background: #667eea;
            color: white;
        }
        footer {
            text-align: center;
            color: rgba(255, 255, 255, 0.8);
            padding: 20px;
            font-size: 0.9rem;
        }
        .timestamp {
            color: #a0aec0;
            font-size: 0.8rem;
            text-align: right;
            margin-top: 10px;
        }
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-running { background: #48bb78; }
        .status-warning { background: #ed8936; }
        .status-stopped { background: #f56565; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
    <script src="https://kit.fontawesome.com/a076d05399.js" crossorigin="anonymous"></script>
</head>
<body>
    <div class="container">
        <header>
            <h1>
                <i class="fas fa-tachometer-alt"></i>
                SSH Benchmark Dashboard
            </h1>
            <p class="subtitle">Real-time monitoring of ControlPersist vs Paramiko performance</p>
            
            <div class="nav-bar">
                <button class="nav-button active" onclick="showSection('overview')">
                    <i class="fas fa-home"></i> Overview
                </button>
                <button class="nav-button" onclick="showSection('metrics')">
                    <i class="fas fa-chart-line"></i> Metrics
                </button>
                <button class="nav-button" onclick="showSection('alerts')">
                    <i class="fas fa-bell"></i> Alerts
                </button>
                <button class="nav-button" onclick="showSection('experiments')">
                    <i class="fas fa-flask"></i> Experiments
                </button>
                <button class="nav-button" onclick="showSection('system')">
                    <i class="fas fa-server"></i> System Info
                </button>
            </div>
        </header>

        <div id="overview-section" class="section">
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-title">CPU Usage</div>
                    <div class="stat-value" id="cpu-usage">0%</div>
                    <div class="stat-change" id="cpu-trend">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Memory Usage</div>
                    <div class="stat-value" id="memory-usage">0%</div>
                    <div class="stat-change" id="memory-trend">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Active Alerts</div>
                    <div class="stat-value" id="active-alerts">0</div>
                    <div class="stat-change">
                        <span id="critical-alerts" class="negative">0 critical</span>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">Experiments</div>
                    <div class="stat-value" id="active-experiments">0</div>
                    <div class="stat-change">
                        <span id="completed-experiments" class="positive">0 completed</span>
                    </div>
                </div>
            </div>

            <div class="charts-grid">
                <div class="chart-container">
                    <div class="chart-title">CPU & Memory Usage</div>
                    <canvas id="resourceChart"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-title">Network I/O</div>
                    <canvas id="networkChart"></canvas>
                </div>
            </div>

            <div class="alerts-container">
                <div class="chart-title">
                    Recent Alerts
                    <button class="nav-button" onclick="showSection('alerts')">View All</button>
                </div>
                <div id="recent-alerts">
                    <!-- Alerts will be populated here -->
                    <div class="alert alert-info">
                        <strong>System Started</strong><br>
                        Dashboard initialized successfully
                    </div>
                </div>
            </div>
        </div>

        <div id="metrics-section" class="section" style="display: none;">
            <div class="chart-container">
                <div class="chart-title">Detailed Metrics</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                    <div>
                        <canvas id="detailedCpuChart"></canvas>
                    </div>
                    <div>
                        <canvas id="detailedMemoryChart"></canvas>
                    </div>
                </div>
            </div>
        </div>

        <div id="alerts-section" class="section" style="display: none;">
            <div class="alerts-container">
                <div class="chart-title">All Alerts</div>
                <div id="all-alerts">
                    <!-- All alerts will be populated here -->
                </div>
            </div>
        </div>

        <div id="experiments-section" class="section" style="display: none;">
            <div class="chart-container">
                <div class="chart-title">Running Experiments</div>
                <div id="experiments-list">
                    <!-- Experiments will be populated here -->
                </div>
            </div>
        </div>

        <div id="system-section" class="section" style="display: none;">
            <div class="chart-container">
                <div class="chart-title">System Information</div>
                <div id="system-info">
                    <!-- System info will be populated here -->
                </div>
            </div>
        </div>

        <div class="timestamp" id="last-update">
            Last update: Never
        </div>
    </div>

    <footer>
        SSH Benchmark Monitoring System | Real-time Dashboard | Updated every second
    </footer>

    <script>
        // Socket.io connection
        const socket = io();
        
        // Chart instances
        let resourceChart, networkChart, detailedCpuChart, detailedMemoryChart;
        
        // Data storage
        let metricsData = {
            cpu: [],
            memory: [],
            network: []
        };
        
        let currentAlerts = [];
        let currentExperiments = [];
        
        // Socket event handlers
        socket.on('connect', () => {
            console.log('Connected to dashboard server');
            document.getElementById('recent-alerts').innerHTML = 
                '<div class="alert alert-info"><strong>Connected</strong><br>Live updates enabled</div>';
        });
        
        socket.on('update', (data) => {
            updateDashboard(data);
        });
        
        socket.on('new_alert', (alert) => {
            addAlert(alert);
        });
        
        socket.on('experiment_update', (experiment) => {
            updateExperiment(experiment);
        });
        
        // Initialize charts
        function initializeCharts() {
            // Resource chart (CPU & Memory)
            const resourceCtx = document.getElementById('resourceChart').getContext('2d');
            resourceChart = new Chart(resourceCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'CPU %',
                            data: [],
                            borderColor: 'rgb(255, 99, 132)',
                            backgroundColor: 'rgba(255, 99, 132, 0.2)',
                            tension: 0.4
                        },
                        {
                            label: 'Memory %',
                            data: [],
                            borderColor: 'rgb(54, 162, 235)',
                            backgroundColor: 'rgba(54, 162, 235, 0.2)',
                            tension: 0.4
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,
                            title: {
                                display: true,
                                text: 'Percentage'
                            }
                        }
                    }
                }
            });
            
            // Network chart
            const networkCtx = document.getElementById('networkChart').getContext('2d');
            networkChart = new Chart(networkCtx, {
                type: 'bar',
                data: {
                    labels: ['Sent', 'Received'],
                    datasets: [{
                        label: 'MB per second',
                        data: [0, 0],
                        backgroundColor: [
                            'rgba(255, 159, 64, 0.8)',
                            'rgba(75, 192, 192, 0.8)'
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'MB/s'
                            }
                        }
                    }
                }
            });
        }
        
        // Update dashboard with new data
        function updateDashboard(data) {
            const metrics = data.metrics || {};
            
            // Update stats
            if (metrics.cpu) {
                document.getElementById('cpu-usage').textContent = 
                    `${metrics.cpu.percent_total.toFixed(1)}%`;
            }
            
            if (metrics.memory) {
                document.getElementById('memory-usage').textContent = 
                    `${metrics.memory.percent.toFixed(1)}%`;
            }
            
            document.getElementById('active-alerts').textContent = data.alerts_count || 0;
            document.getElementById('active-experiments').textContent = data.experiments_active || 0;
            
            // Update timestamp
            document.getElementById('last-update').textContent = 
                `Last update: ${new Date(data.timestamp).toLocaleTimeString()}`;
            
            // Update charts
            updateCharts(metrics);
        }
        
        function updateCharts(metrics) {
            const now = new Date().toLocaleTimeString();
            
            // Update resource chart
            if (resourceChart && metrics.cpu && metrics.memory) {
                // Add new data point
                resourceChart.data.labels.push(now);
                resourceChart.data.datasets[0].data.push(metrics.cpu.percent_total);
                resourceChart.data.datasets[1].data.push(metrics.memory.percent);
                
                // Keep only last 20 points
                if (resourceChart.data.labels.length > 20) {
                    resourceChart.data.labels.shift();
                    resourceChart.data.datasets[0].data.shift();
                    resourceChart.data.datasets[1].data.shift();
                }
                
                resourceChart.update('none');
            }
            
            // Update network chart
            if (networkChart && metrics.network) {
                // Calculate MB/s (simplified)
                networkChart.data.datasets[0].data = [
                    metrics.network.bytes_sent_mb,
                    metrics.network.bytes_recv_mb
                ];
                networkChart.update();
            }
        }
        
        function addAlert(alert) {
            const alertElement = document.createElement('div');
            alertElement.className = `alert alert-${alert.severity || 'info'}`;
            alertElement.innerHTML = `
                <strong>${alert.title || 'Alert'}</strong><br>
                ${alert.message || ''}<br>
                <small>${new Date(alert.timestamp).toLocaleTimeString()}</small>
            `;
            
            // Add to recent alerts
            const recentAlerts = document.getElementById('recent-alerts');
            recentAlerts.insertBefore(alertElement, recentAlerts.firstChild);
            
            // Keep only 5 recent alerts
            if (recentAlerts.children.length > 5) {
                recentAlerts.removeChild(recentAlerts.lastChild);
            }
            
            // Update alert counts
            if (alert.severity === 'critical') {
                const criticalCount = document.getElementById('critical-alerts');
                const current = parseInt(criticalCount.textContent) || 0;
                criticalCount.textContent = `${current + 1} critical`;
                criticalCount.className = 'negative';
            }
        }
        
        function updateExperiment(experiment) {
            // Update experiment display
            console.log('Experiment update:', experiment);
        }
        
        function showSection(sectionId) {
            // Hide all sections
            document.querySelectorAll('.section').forEach(section => {
                section.style.display = 'none';
            });
            
            // Show selected section
            document.getElementById(`${sectionId}-section`).style.display = 'block';
            
            // Update navigation buttons
            document.querySelectorAll('.nav-button').forEach(button => {
                button.classList.remove('active');
            });
            event.target.classList.add('active');
        }
        
        // Request initial data
        function loadInitialData() {
            fetch('/api/metrics')
                .then(response => response.json())
                .then(data => updateDashboard(data));
            
            fetch('/api/alerts')
                .then(response => response.json())
                .then(data => {
                    data.alerts.forEach(alert => addAlert(alert));
                });
        }
        
        // Initialize on load
        document.addEventListener('DOMContentLoaded', () => {
            initializeCharts();
            loadInitialData();
            
            // Request updates every second
            setInterval(() => {
                socket.emit('request_update');
            }, 1000);
        });
    </script>
</body>
</html>
'''
        
        (templates_dir / 'index.html').write_text(index_html)
        
        # Create other template files (simplified versions)
        (templates_dir / 'dashboard.html').write_text('<h1>Detailed Dashboard</h1><p>Detailed metrics view</p>')
        (templates_dir / 'alerts.html').write_text('<h1>Alerts</h1><p>Alert management view</p>')
        (templates_dir / 'experiments.html').write_text('<h1>Experiments</h1><p>Experiment monitoring view</p>')
        
        self.logger.info("HTML templates created")

# Command-line interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Dashboard Server for SSH Benchmarking")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8050, help="Port to listen on")
    parser.add_argument("--test-alert", action="store_true", help="Send a test alert")
    
    args = parser.parse_args()
    
    if HAS_FLASK:
        try:
            dashboard = DashboardServer(args.host, args.port)
            
            if args.test_alert:
                # Send a test alert
                dashboard.add_alert({
                    'severity': 'warning',
                    'title': 'Test Alert',
                    'message': 'This is a test alert from the dashboard system',
                    'source': 'test'
                })
                print("Test alert sent")
            else:
                dashboard.start()
                
        except KeyboardInterrupt:
            print("\nDashboard server stopped")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Required packages not installed. Run:")
        print("pip install flask flask-socketio")
