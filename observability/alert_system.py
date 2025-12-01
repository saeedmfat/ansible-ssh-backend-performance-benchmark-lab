#!/usr/bin/env python3
"""
Alerting and Notification System for SSH Benchmarking
Monitors metrics and sends alerts when thresholds are breached
"""

import json
import time
import smtplib
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import queue

@dataclass
class Alert:
    """Alert definition"""
    id: str
    severity: str  # 'info', 'warning', 'critical'
    title: str
    message: str
    timestamp: datetime
    source: str
    metrics: Dict[str, Any]
    acknowledged: bool = False
    resolved: bool = False
    
    def to_dict(self):
        return asdict(self)

class AlertRule:
    """Rule for triggering alerts"""
    
    def __init__(self, name: str, condition: str, severity: str, 
                 actions: List[str], cooldown_seconds: int = 300):
        self.name = name
        self.condition = condition  # Python expression that returns bool
        self.severity = severity
        self.actions = actions
        self.cooldown_seconds = cooldown_seconds
        self.last_triggered = None
    
    def should_trigger(self, metrics: Dict) -> bool:
        """Check if rule should trigger based on metrics"""
        try:
            # Evaluate condition in a safe way
            local_vars = {**metrics, 'time': time.time()}
            
            # Add helper functions
            def avg(values):
                return sum(values) / len(values) if values else 0
            
            def max_value(values):
                return max(values) if values else 0
            
            def min_value(values):
                return min(values) if values else 0
            
            def count(values):
                return len(values)
            
            local_vars.update({
                'avg': avg,
                'max': max_value,
                'min': min_value,
                'count': count
            })
            
            result = eval(self.condition, {"__builtins__": {}}, local_vars)
            
            # Check cooldown
            if result and self.last_triggered:
                time_since_last = time.time() - self.last_triggered
                if time_since_last < self.cooldown_seconds:
                    return False
            
            return bool(result)
            
        except Exception as e:
            logging.error(f"Error evaluating alert rule {self.name}: {e}")
            return False
    
    def trigger(self):
        """Mark rule as triggered"""
        self.last_triggered = time.time()

class AlertManager:
    """Main alert manager"""
    
    def __init__(self, config_file: str = "alert_config.yaml"):
        self.config_file = Path(config_file)
        self.config = self._load_config()
        
        self.alerts: List[Alert] = []
        self.rules: List[AlertRule] = []
        self.alert_queue = queue.Queue()
        
        self.logger = self._setup_logging()
        self.running = False
        self.monitor_thread = None
        
        # Load rules
        self._load_rules()
        
        self.logger.info(f"Alert Manager initialized with {len(self.rules)} rules")
    
    def _load_config(self) -> Dict:
        """Load configuration"""
        default_config = {
            "alerting": {
                "enabled": True,
                "check_interval": 10,  # seconds
                "retention_days": 30,
                "max_alerts": 1000
            },
            "notifications": {
                "email": {
                    "enabled": False,
                    "smtp_server": "smtp.gmail.com",
                    "smtp_port": 587,
                    "username": "",
                    "password": "",
                    "from_address": "alerts@benchmark.local",
                    "to_addresses": ["admin@benchmark.local"]
                },
                "slack": {
                    "enabled": False,
                    "webhook_url": "",
                    "channel": "#alerts"
                },
                "console": {
                    "enabled": True,
                    "format": "colored"
                }
            },
            "storage": {
                "alerts_file": "alerts.json",
                "metrics_dir": "metrics"
            }
        }
        
        if self.config_file.exists():
            try:
                import yaml
                with open(self.config_file, 'r') as f:
                    loaded_config = yaml.safe_load(f)
                    # Merge with defaults
                    default_config.update(loaded_config)
            except Exception as e:
                print(f"Warning: Could not load config file: {e}")
        
        return default_config
    
    def _load_rules(self):
        """Load alert rules"""
        # Default rules for SSH benchmarking
        default_rules = [
            AlertRule(
                name="high_cpu_usage",
                condition="metrics.get('cpu_percent_total', 0) > 90",
                severity="warning",
                actions=["console", "email"],
                cooldown_seconds=300
            ),
            AlertRule(
                name="high_memory_usage",
                condition="metrics.get('memory_used_percent', 0) > 95",
                severity="critical",
                actions=["console", "email"],
                cooldown_seconds=300
            ),
            AlertRule(
                name="high_error_rate",
                condition="metrics.get('error_rate', 0) > 10",
                severity="warning",
                actions=["console", "slack"],
                cooldown_seconds=60
            ),
            AlertRule(
                name="slow_ssh_connections",
                condition="metrics.get('ssh_connection_time_avg_ms', 0) > 2000",
                severity="warning",
                actions=["console"],
                cooldown_seconds=60
            ),
            AlertRule(
                name="container_unreachable",
                condition="metrics.get('unreachable_containers', 0) > 0",
                severity="critical",
                actions=["console", "email", "slack"],
                cooldown_seconds=30
            ),
            AlertRule(
                name="low_disk_space",
                condition="metrics.get('disk_free_percent', 100) < 10",
                severity="warning",
                actions=["console", "email"],
                cooldown_seconds=3600
            ),
            AlertRule(
                name="high_temperature",
                condition="max(metrics.get('temperatures', {}).get('core', []), default=0) > 85",
                severity="warning",
                actions=["console"],
                cooldown_seconds=300
            ),
            AlertRule(
                name="network_packet_loss",
                condition="metrics.get('network_packet_loss_percent', 0) > 5",
                severity="warning",
                actions=["console", "email"],
                cooldown_seconds=60
            ),
            AlertRule(
                name="benchmark_timeout",
                condition="metrics.get('benchmark_duration_seconds', 0) > 3600",
                severity="info",
                actions=["console"],
                cooldown_seconds=3600
            ),
            AlertRule(
                name="high_variance",
                condition="metrics.get('coefficient_of_variation', 0) > 20",
                severity="warning",
                actions=["console"],
                cooldown_seconds=300
            )
        ]
        
        self.rules = default_rules
    
    def _setup_logging(self):
        """Setup logging"""
        logger = logging.getLogger("AlertManager")
        logger.setLevel(logging.INFO)
        
        # Console handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)8s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    def start(self):
        """Start the alert manager"""
        if self.running:
            self.logger.warning("Alert manager already running")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        
        self.logger.info("Alert manager started")
    
    def stop(self):
        """Stop the alert manager"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        # Save alerts
        self._save_alerts()
        
        self.logger.info("Alert manager stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop"""
        check_interval = self.config["alerting"]["check_interval"]
        
        while self.running:
            try:
                # Collect current metrics
                metrics = self._collect_current_metrics()
                
                # Check all rules
                for rule in self.rules:
                    if rule.should_trigger(metrics):
                        self._trigger_alert(rule, metrics)
                        rule.trigger()
                
                # Process alert queue
                self._process_alert_queue()
                
                # Cleanup old alerts
                self._cleanup_old_alerts()
                
                time.sleep(check_interval)
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(1)
    
    def _collect_current_metrics(self) -> Dict:
        """Collect current metrics for alert evaluation"""
        metrics = {}
        
        try:
            # Try to load latest metrics from resource monitor
            metrics_dir = Path(self.config["storage"]["metrics_dir"])
            if metrics_dir.exists():
                # Find latest metrics file
                metric_files = sorted(metrics_dir.glob("resource_samples_*.jsonl"))
                if metric_files:
                    latest_file = metric_files[-1]
                    
                    # Read last few lines
                    lines = []
                    with open(latest_file, 'r') as f:
                        for line in f:
                            lines.append(line)
                    
                    # Process last 10 samples
                    recent_samples = []
                    for line in lines[-10:]:
                        try:
                            sample = json.loads(line)
                            recent_samples.append(sample)
                        except:
                            continue
                    
                    if recent_samples:
                        # Extract metrics
                        metrics = self._extract_metrics_from_samples(recent_samples)
            
        except Exception as e:
            self.logger.debug(f"Error collecting metrics: {e}")
        
        # Add system metrics
        try:
            import psutil
            metrics['cpu_percent_total'] = psutil.cpu_percent(interval=None)
            metrics['memory_used_percent'] = psutil.virtual_memory().percent
            metrics['disk_free_percent'] = 100 - psutil.disk_usage('/').percent
            
            # Network
            net_io = psutil.net_io_counters()
            metrics['network_packets_sent'] = net_io.packets_sent
            metrics['network_packets_recv'] = net_io.packets_recv
            
            # Temperature if available
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    core_temps = []
                    for sensor in temps.get('coretemp', []):
                        core_temps.append(sensor.current)
                    metrics['temperatures'] = {'core': core_temps}
            
        except Exception as e:
            self.logger.debug(f"Error collecting system metrics: {e}")
        
        return metrics
    
    def _extract_metrics_from_samples(self, samples: List[Dict]) -> Dict:
        """Extract aggregated metrics from resource samples"""
        metrics = {}
        
        # Group by sample type
        by_type = {}
        for sample in samples:
            sample_type = sample.get('sample_type')
            if sample_type not in by_type:
                by_type[sample_type] = []
            by_type[sample_type].append(sample)
        
        # Process system samples
        if 'system' in by_type:
            system_samples = by_type['system']
            
            # CPU metrics
            cpu_percents = []
            for sample in system_samples:
                cpu_data = sample.get('metrics', {}).get('cpu', {})
                if 'percent_total' in cpu_data:
                    cpu_percents.append(cpu_data['percent_total'])
            
            if cpu_percents:
                metrics['cpu_percent_avg'] = sum(cpu_percents) / len(cpu_percents)
                metrics['cpu_percent_max'] = max(cpu_percents)
                metrics['cpu_percent_min'] = min(cpu_percents)
        
        return metrics
    
    def _trigger_alert(self, rule: AlertRule, metrics: Dict):
        """Trigger an alert"""
        alert_id = f"{rule.name}_{int(time.time())}"
        
        alert = Alert(
            id=alert_id,
            severity=rule.severity,
            title=f"{rule.severity.upper()}: {rule.name.replace('_', ' ').title()}",
            message=f"Alert triggered by rule: {rule.name}\nCondition: {rule.condition}",
            timestamp=datetime.now(),
            source="alert_manager",
            metrics=metrics
        )
        
        # Add to queue for processing
        self.alert_queue.put(alert)
        
        # Also store locally
        self.alerts.append(alert)
        
        self.logger.warning(f"Alert triggered: {rule.name} ({rule.severity})")
    
    def _process_alert_queue(self):
        """Process alerts in the queue"""
        while not self.alert_queue.empty():
            try:
                alert = self.alert_queue.get_nowait()
                
                # Execute actions
                for action in self.rules[0].actions:  # Use first matching rule's actions
                    if action == "console":
                        self._send_console_alert(alert)
                    elif action == "email":
                        self._send_email_alert(alert)
                    elif action == "slack":
                        self._send_slack_alert(alert)
                
                self.alert_queue.task_done()
                
            except queue.Empty:
                break
    
    def _send_console_alert(self, alert: Alert):
        """Send alert to console"""
        colors = {
            'info': '\033[94m',      # Blue
            'warning': '\033[93m',   # Yellow
            'critical': '\033[91m',  # Red
        }
        reset = '\033[0m'
        
        color = colors.get(alert.severity, reset)
        
        print(f"\n{color}{'='*60}")
        print(f"ALERT: {alert.title}")
        print(f"{'='*60}{reset}")
        print(f"Severity: {alert.severity}")
        print(f"Time: {alert.timestamp}")
        print(f"Message: {alert.message}")
        
        if alert.metrics:
            print("\nRelevant Metrics:")
            for key, value in list(alert.metrics.items())[:5]:  # Show first 5 metrics
                print(f"  {key}: {value}")
        
        print(f"{color}{'='*60}{reset}\n")
    
    def _send_email_alert(self, alert: Alert):
        """Send alert via email"""
        if not self.config["notifications"]["email"]["enabled"]:
            return
        
        try:
            config = self.config["notifications"]["email"]
            
            msg = MIMEMultipart()
            msg['From'] = config['from_address']
            msg['To'] = ', '.join(config['to_addresses'])
            msg['Subject'] = f"[{alert.severity.upper()}] {alert.title}"
            
            # Create HTML email
            html = f"""
            <html>
            <body>
                <h2 style="color: {'red' if alert.severity == 'critical' else 'orange' if alert.severity == 'warning' else 'blue'}">
                    {alert.severity.upper()} ALERT: {alert.title}
                </h2>
                <p><strong>Time:</strong> {alert.timestamp}</p>
                <p><strong>Message:</strong> {alert.message}</p>
                
                <h3>Metrics:</h3>
                <table border="1" cellpadding="5">
                    <tr><th>Metric</th><th>Value</th></tr>
            """
            
            for key, value in list(alert.metrics.items())[:10]:  # Show first 10 metrics
                html += f"<tr><td>{key}</td><td>{value}</td></tr>"
            
            html += """
                </table>
                <br>
                <p><em>This is an automated alert from the SSH Benchmarking System.</em></p>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            # Send email
            with smtplib.SMTP(config['smtp_server'], config['smtp_port']) as server:
                server.starttls()
                server.login(config['username'], config['password'])
                server.send_message(msg)
            
            self.logger.info(f"Email alert sent: {alert.id}")
            
        except Exception as e:
            self.logger.error(f"Failed to send email alert: {e}")
    
    def _send_slack_alert(self, alert: Alert):
        """Send alert to Slack"""
        if not self.config["notifications"]["slack"]["enabled"]:
            return
        
        try:
            import requests
            
            config = self.config["notifications"]["slack"]
            
            # Create Slack message
            color = {
                'critical': '#FF0000',
                'warning': '#FFA500',
                'info': '#0000FF'
            }.get(alert.severity, '#808080')
            
            slack_message = {
                "channel": config["channel"],
                "username": "Benchmark Alert Bot",
                "icon_emoji": ":warning:" if alert.severity in ['warning', 'critical'] else ":information_source:",
                "attachments": [
                    {
                        "color": color,
                        "title": f"{alert.severity.upper()}: {alert.title}",
                        "text": alert.message,
                        "fields": [
                            {
                                "title": key,
                                "value": str(value),
                                "short": True
                            }
                            for key, value in list(alert.metrics.items())[:5]
                        ],
                        "footer": "SSH Benchmarking System",
                        "ts": int(alert.timestamp.timestamp())
                    }
                ]
            }
            
            response = requests.post(
                config["webhook_url"],
                json=slack_message,
                timeout=10
            )
            
            if response.status_code == 200:
                self.logger.info(f"Slack alert sent: {alert.id}")
            else:
                self.logger.error(f"Failed to send Slack alert: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"Failed to send Slack alert: {e}")
    
    def _cleanup_old_alerts(self):
        """Remove old alerts"""
        retention_days = self.config["alerting"]["retention_days"]
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        # Remove old alerts
        self.alerts = [a for a in self.alerts if a.timestamp > cutoff_date]
        
        # Limit total alerts
        max_alerts = self.config["alerting"]["max_alerts"]
        if len(self.alerts) > max_alerts:
            self.alerts = self.alerts[-max_alerts:]
    
    def _save_alerts(self):
        """Save alerts to file"""
        try:
            alerts_file = Path(self.config["storage"]["alerts_file"])
            
            alerts_data = {
                "timestamp": datetime.now().isoformat(),
                "alerts": [alert.to_dict() for alert in self.alerts]
            }
            
            with open(alerts_file, 'w') as f:
                json.dump(alerts_data, f, indent=2, default=str)
            
            self.logger.debug(f"Alerts saved to {alerts_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to save alerts: {e}")
    
    def get_alerts(self, severity: Optional[str] = None, 
                   start_time: Optional[datetime] = None,
                   end_time: Optional[datetime] = None) -> List[Alert]:
        """Get filtered alerts"""
        filtered = self.alerts
        
        if severity:
            filtered = [a for a in filtered if a.severity == severity]
        
        if start_time:
            filtered = [a for a in filtered if a.timestamp >= start_time]
        
        if end_time:
            filtered = [a for a in filtered if a.timestamp <= end_time]
        
        return filtered
    
    def acknowledge_alert(self, alert_id: str):
        """Acknowledge an alert"""
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                self.logger.info(f"Alert acknowledged: {alert_id}")
                return True
        return False
    
    def resolve_alert(self, alert_id: str):
        """Resolve an alert"""
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.resolved = True
                self.logger.info(f"Alert resolved: {alert_id}")
                return True
        return False

# Command-line interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Alert Manager for SSH Benchmarking")
    parser.add_argument("--start", action="store_true", help="Start the alert manager")
    parser.add_argument("--stop", action="store_true", help="Stop the alert manager")
    parser.add_argument("--status", action="store_true", help="Show alert status")
    parser.add_argument("--list", action="store_true", help="List active alerts")
    parser.add_argument("--config", default="alert_config.yaml", help="Configuration file")
    parser.add_argument("--test", action="store_true", help="Test alert system")
    
    args = parser.parse_args()
    
    manager = AlertManager(args.config)
    
    if args.test:
        # Test the alert system
        print("Testing alert system...")
        
        test_metrics = {
            'cpu_percent_total': 95,
            'memory_used_percent': 80,
            'error_rate': 15,
            'ssh_connection_time_avg_ms': 2500
        }
        
        for rule in manager.rules:
            if rule.should_trigger(test_metrics):
                print(f"Rule would trigger: {rule.name}")
                manager._trigger_alert(rule, test_metrics)
        
        # Process alerts
        manager._process_alert_queue()
        
    elif args.start:
        manager.start()
        try:
            # Keep running
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            manager.stop()
            
    elif args.stop:
        manager.stop()
        
    elif args.status:
        print(f"Alert Manager Status:")
        print(f"  Running: {manager.running}")
        print(f"  Total alerts: {len(manager.alerts)}")
        print(f"  Rules configured: {len(manager.rules)}")
        
        # Alert counts by severity
        severity_counts = {}
        for alert in manager.alerts:
            severity_counts[alert.severity] = severity_counts.get(alert.severity, 0) + 1
        
        print(f"  Alerts by severity:")
        for severity, count in severity_counts.items():
            print(f"    {severity}: {count}")
            
    elif args.list:
        alerts = manager.get_alerts()
        if not alerts:
            print("No active alerts")
        else:
            print(f"Active alerts ({len(alerts)}):")
            for alert in alerts[-10:]:  # Show last 10
                status = "ACK" if alert.acknowledged else "NEW"
                status += "/RES" if alert.resolved else ""
                print(f"  [{status}] {alert.timestamp} - {alert.severity}: {alert.title}")
    
    else:
        parser.print_help()
