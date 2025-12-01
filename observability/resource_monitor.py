#!/usr/bin/env python3
"""
Comprehensive Resource Monitoring System
Monitors CPU, memory, disk, network, temperature, and application metrics
"""

import time
import json
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any
import psutil
import logging
import signal
import sys
import socket

@dataclass
class ResourceSample:
    """A single resource measurement sample"""
    timestamp_ns: int
    hostname: str
    sample_type: str  # 'system', 'process', 'container', 'network'
    metrics: Dict[str, Any]
    tags: Dict[str, str] = field(default_factory=dict)

class ResourceMonitor:
    """Main resource monitoring class"""
    
    def __init__(self, output_dir: str = "monitoring_data", sample_interval: float = 0.1):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.sample_interval = sample_interval
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.samples: List[ResourceSample] = []
        
        # Setup logging
        self.logger = self._setup_logging()
        
        # Cache for efficiency
        self.last_cpu_times = None
        self.last_net_io = None
        self.last_disk_io = None
        
        # Signal handling
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.info(f"Resource Monitor initialized. Output: {output_dir}")
    
    def _setup_logging(self) -> logging.Logger:
        """Setup structured logging"""
        logger = logging.getLogger("ResourceMonitor")
        logger.setLevel(logging.INFO)
        
        # File handler
        log_file = self.output_dir / "resource_monitor.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # JSON formatter for structured logging
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_record = {
                    "timestamp": datetime.now().isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "hostname": socket.gethostname(),
                    "pid": record.process,
                    "thread": record.threadName,
                }
                if record.exc_info:
                    log_record["exception"] = self.formatException(record.exc_info)
                return json.dumps(log_record)
        
        file_handler.setFormatter(JSONFormatter())
        
        # Simple formatter for console
        console_format = logging.Formatter(
            '[%(asctime)s] [%(levelname)8s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def start(self):
        """Start the monitoring thread"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.logger.warning("Monitor already running")
            return
        
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        self.logger.info("Resource monitoring started")
    
    def stop(self):
        """Stop the monitoring thread"""
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
            self.logger.info("Resource monitoring stopped")
        
        # Save remaining samples
        self._save_samples()
    
    def _monitoring_loop(self):
        """Main monitoring loop"""
        self.logger.debug("Starting monitoring loop")
        
        while not self.stop_event.is_set():
            try:
                start_time = time.perf_counter_ns()
                
                # Collect all metrics
                samples = self._collect_all_metrics()
                self.samples.extend(samples)
                
                # Save samples periodically to manage memory
                if len(self.samples) >= 1000:
                    self._save_samples()
                
                # Calculate actual sleep time to maintain consistent sampling
                elapsed_ns = time.perf_counter_ns() - start_time
                sleep_time = max(0, self.sample_interval - (elapsed_ns / 1e9))
                
                time.sleep(sleep_time)
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                time.sleep(1)  # Prevent tight error loop
    
    def _collect_all_metrics(self) -> List[ResourceSample]:
        """Collect metrics from all sources"""
        samples = []
        timestamp_ns = time.perf_counter_ns()
        hostname = socket.gethostname()
        
        # System-level metrics
        system_sample = self._collect_system_metrics(timestamp_ns, hostname)
        samples.append(system_sample)
        
        # Process-level metrics
        process_sample = self._collect_process_metrics(timestamp_ns, hostname)
        samples.append(process_sample)
        
        # Network metrics
        network_sample = self._collect_network_metrics(timestamp_ns, hostname)
        samples.append(network_sample)
        
        # Container metrics (if using LXC)
        container_samples = self._collect_container_metrics(timestamp_ns, hostname)
        samples.extend(container_samples)
        
        # Ansible-specific metrics
        ansible_sample = self._collect_ansible_metrics(timestamp_ns, hostname)
        if ansible_sample:
            samples.append(ansible_sample)
        
        # Temperature and hardware metrics
        hw_sample = self._collect_hardware_metrics(timestamp_ns, hostname)
        if hw_sample:
            samples.append(hw_sample)
        
        return samples
    
    def _collect_system_metrics(self, timestamp_ns: int, hostname: str) -> ResourceSample:
        """Collect system-wide resource metrics"""
        metrics = {}
        
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=None, percpu=True)
            cpu_freq = psutil.cpu_freq()
            load_avg = psutil.getloadavg()
            
            metrics["cpu"] = {
                "percent_per_core": cpu_percent,
                "percent_total": sum(cpu_percent) / len(cpu_percent) if cpu_percent else 0,
                "frequency_mhz": cpu_freq.current if cpu_freq else None,
                "load_1min": load_avg[0],
                "load_5min": load_avg[1],
                "load_15min": load_avg[2],
                "context_switches": psutil.cpu_stats().ctx_switches,
                "interrupts": psutil.cpu_stats().interrupts
            }
            
            # Memory
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            metrics["memory"] = {
                "total_mb": memory.total / 1024 / 1024,
                "available_mb": memory.available / 1024 / 1024,
                "used_mb": memory.used / 1024 / 1024,
                "used_percent": memory.percent,
                "swap_total_mb": swap.total / 1024 / 1024,
                "swap_used_mb": swap.used / 1024 / 1024,
                "swap_used_percent": swap.percent
            }
            
            # Disk
            disk_usage = psutil.disk_usage('/')
            disk_io = psutil.disk_io_counters()
            
            metrics["disk"] = {
                "total_gb": disk_usage.total / 1024 / 1024 / 1024,
                "used_gb": disk_usage.used / 1024 / 1024 / 1024,
                "free_gb": disk_usage.free / 1024 / 1024 / 1024,
                "used_percent": disk_usage.percent,
                "read_mb": disk_io.read_bytes / 1024 / 1024 if disk_io else 0,
                "write_mb": disk_io.write_bytes / 1024 / 1024 if disk_io else 0,
                "read_ops": disk_io.read_count if disk_io else 0,
                "write_ops": disk_io.write_count if disk_io else 0
            }
            
        except Exception as e:
            self.logger.warning(f"Error collecting system metrics: {e}")
        
        return ResourceSample(
            timestamp_ns=timestamp_ns,
            hostname=hostname,
            sample_type="system",
            metrics=metrics,
            tags={"component": "system", "scope": "global"}
        )
    
    def _collect_process_metrics(self, timestamp_ns: int, hostname: str) -> ResourceSample:
        """Collect metrics for specific processes"""
        metrics = {}
        
        try:
            current_process = psutil.Process()
            
            # Find relevant processes
            relevant_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    pinfo = proc.info
                    if any(keyword in str(pinfo.get('cmdline', [])).lower() 
                           for keyword in ['ansible', 'ssh', 'python', 'lxc']):
                        relevant_processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Collect metrics for each relevant process
            process_metrics = []
            for proc in relevant_processes:
                try:
                    with proc.oneshot():
                        pmem = proc.memory_info()
                        pio = proc.io_counters()
                        
                        process_metrics.append({
                            "pid": proc.pid,
                            "name": proc.name(),
                            "cmdline": proc.cmdline(),
                            "cpu_percent": proc.cpu_percent(),
                            "memory_mb": pmem.rss / 1024 / 1024,
                            "memory_percent": proc.memory_percent(),
                            "num_threads": proc.num_threads(),
                            "num_fds": proc.num_fds() if hasattr(proc, 'num_fds') else 0,
                            "read_mb": pio.read_bytes / 1024 / 1024 if pio else 0,
                            "write_mb": pio.write_bytes / 1024 / 1024 if pio else 0,
                            "create_time": datetime.fromtimestamp(proc.create_time()).isoformat(),
                            "status": proc.status()
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            metrics["processes"] = process_metrics
            metrics["total_relevant_processes"] = len(process_metrics)
            
        except Exception as e:
            self.logger.warning(f"Error collecting process metrics: {e}")
        
        return ResourceSample(
            timestamp_ns=timestamp_ns,
            hostname=hostname,
            sample_type="process",
            metrics=metrics,
            tags={"component": "process", "scope": "application"}
        )
    
    def _collect_network_metrics(self, timestamp_ns: int, hostname: str) -> ResourceSample:
        """Collect network interface metrics"""
        metrics = {}
        
        try:
            # Overall network I/O
            net_io = psutil.net_io_counters()
            
            metrics["overall"] = {
                "bytes_sent_mb": net_io.bytes_sent / 1024 / 1024,
                "bytes_recv_mb": net_io.bytes_recv / 1024 / 1024,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv,
                "errin": net_io.errin,
                "errout": net_io.errout,
                "dropin": net_io.dropin,
                "dropout": net_io.dropout
            }
            
            # Per-interface metrics
            interfaces = []
            for name, stats in psutil.net_if_stats().items():
                try:
                    addrs = psutil.net_if_addrs().get(name, [])
                    io_counters = psutil.net_io_counters(pernic=True).get(name)
                    
                    interface_info = {
                        "name": name,
                        "is_up": stats.isup,
                        "duplex": stats.duplex,
                        "speed_mbps": stats.speed,
                        "mtu": stats.mtu,
                        "addresses": [
                            {
                                "family": str(addr.family),
                                "address": addr.address,
                                "netmask": addr.netmask
                            }
                            for addr in addrs
                        ]
                    }
                    
                    if io_counters:
                        interface_info.update({
                            "bytes_sent_mb": io_counters.bytes_sent / 1024 / 1024,
                            "bytes_recv_mb": io_counters.bytes_recv / 1024 / 1024,
                            "packets_sent": io_counters.packets_sent,
                            "packets_recv": io_counters.packets_recv
                        })
                    
                    interfaces.append(interface_info)
                except Exception as e:
                    self.logger.debug(f"Error collecting metrics for interface {name}: {e}")
            
            metrics["interfaces"] = interfaces
            
            # Connection tracking
            connections = []
            for conn in psutil.net_connections(kind='inet'):
                try:
                    connections.append({
                        "fd": conn.fd,
                        "family": str(conn.family),
                        "type": str(conn.type),
                        "laddr": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else None,
                        "raddr": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else None,
                        "status": conn.status,
                        "pid": conn.pid
                    })
                except:
                    continue
            
            metrics["connections"] = {
                "total": len(connections),
                "tcp_established": len([c for c in connections if c.get("status") == "ESTABLISHED"]),
                "listening": len([c for c in connections if c.get("status") == "LISTEN"])
            }
            
        except Exception as e:
            self.logger.warning(f"Error collecting network metrics: {e}")
        
        return ResourceSample(
            timestamp_ns=timestamp_ns,
            hostname=hostname,
            sample_type="network",
            metrics=metrics,
            tags={"component": "network", "scope": "system"}
        )
    
    def _collect_container_metrics(self, timestamp_ns: int, hostname: str) -> List[ResourceSample]:
        """Collect LXC container metrics"""
        samples = []
        
        try:
            # Get list of containers
            result = subprocess.run(
                ["lxc", "list", "--format", "json"],
                capture_output=True,
                text=True,
                check=True
            )
            containers = json.loads(result.stdout)
            
            for container in containers:
                if container.get("status") == "Running":
                    container_name = container.get("name")
                    
                    try:
                        # Get detailed container info
                        info_result = subprocess.run(
                            ["lxc", "info", container_name, "--resources"],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if info_result.returncode == 0:
                            container_metrics = {}
                            for line in info_result.stdout.strip().split('\n'):
                                if ':' in line:
                                    key, value = line.split(':', 1)
                                    container_metrics[key.strip()] = value.strip()
                            
                            # Parse IP addresses
                            ipv4 = container.get("ipv4", "").split()[0] if container.get("ipv4") else ""
                            ipv6 = container.get("ipv6", "").split()[0] if container.get("ipv6") else ""
                            
                            sample = ResourceSample(
                                timestamp_ns=timestamp_ns,
                                hostname=hostname,
                                sample_type="container",
                                metrics={
                                    "name": container_name,
                                    "status": container.get("status"),
                                    "type": container.get("type"),
                                    "ipv4": ipv4,
                                    "ipv6": ipv6,
                                    "resources": container_metrics
                                },
                                tags={
                                    "component": "container",
                                    "container_name": container_name,
                                    "scope": "virtualization"
                                }
                            )
                            samples.append(sample)
                    except Exception as e:
                        self.logger.debug(f"Error collecting metrics for container {container_name}: {e}")
                        
        except Exception as e:
            self.logger.warning(f"Error collecting container metrics: {e}")
        
        return samples
    
    def _collect_ansible_metrics(self, timestamp_ns: int, hostname: str) -> Optional[ResourceSample]:
        """Collect Ansible-specific metrics"""
        # This would be enhanced by parsing Ansible logs or using callbacks
        # For now, we'll collect what we can from process inspection
        
        try:
            # Find Ansible processes
            ansible_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    pinfo = proc.info
                    cmdline = ' '.join(pinfo.get('cmdline', []))
                    if 'ansible' in cmdline.lower():
                        ansible_processes.append({
                            "pid": proc.pid,
                            "cmdline": cmdline,
                            "memory_mb": proc.memory_info().rss / 1024 / 1024
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if ansible_processes:
                return ResourceSample(
                    timestamp_ns=timestamp_ns,
                    hostname=hostname,
                    sample_type="ansible",
                    metrics={
                        "processes": ansible_processes,
                        "count": len(ansible_processes)
                    },
                    tags={"component": "ansible", "scope": "application"}
                )
                
        except Exception as e:
            self.logger.debug(f"Error collecting Ansible metrics: {e}")
        
        return None
    
    def _collect_hardware_metrics(self, timestamp_ns: int, hostname: str) -> Optional[ResourceSample]:
        """Collect hardware sensors (temperature, fans, etc.)"""
        metrics = {}
        
        try:
            # Try to get temperature sensors
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    metrics["temperatures"] = {}
                    for name, entries in temps.items():
                        metrics["temperatures"][name] = [
                            {"label": e.label or f"sensor_{i}", "current": e.current}
                            for i, e in enumerate(entries)
                        ]
            
            # Try to get fan speeds
            if hasattr(psutil, "sensors_fans"):
                fans = psutil.sensors_fans()
                if fans:
                    metrics["fans"] = {}
                    for name, entries in fans.items():
                        metrics["fans"][name] = [
                            {"label": e.label or f"fan_{i}", "current": e.current}
                            for i, e in enumerate(entries)
                        ]
            
            # Battery (for laptops)
            if hasattr(psutil, "sensors_battery"):
                battery = psutil.sensors_battery()
                if battery:
                    metrics["battery"] = {
                        "percent": battery.percent,
                        "secsleft": battery.secsleft,
                        "power_plugged": battery.power_plugged
                    }
            
            if metrics:
                return ResourceSample(
                    timestamp_ns=timestamp_ns,
                    hostname=hostname,
                    sample_type="hardware",
                    metrics=metrics,
                    tags={"component": "hardware", "scope": "physical"}
                )
                
        except Exception as e:
            self.logger.debug(f"Error collecting hardware metrics: {e}")
        
        return None
    
    def _save_samples(self):
        """Save collected samples to disk"""
        if not self.samples:
            return
        
        try:
            # Create timestamped file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = self.output_dir / f"resource_samples_{timestamp}.jsonl"
            
            with open(file_path, 'a') as f:
                for sample in self.samples:
                    f.write(json.dumps(asdict(sample), default=str) + '\n')
            
            self.logger.debug(f"Saved {len(self.samples)} samples to {file_path}")
            
            # Clear saved samples
            self.samples.clear()
            
        except Exception as e:
            self.logger.error(f"Error saving samples: {e}")
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
        sys.exit(0)
    
    def generate_summary_report(self) -> Dict:
        """Generate summary report of collected metrics"""
        if not self.samples:
            return {"error": "No samples collected"}
        
        # Load recent samples
        sample_files = sorted(self.output_dir.glob("resource_samples_*.jsonl"))
        if not sample_files:
            return {"error": "No sample files found"}
        
        # Load last file
        last_file = sample_files[-1]
        samples = []
        with open(last_file, 'r') as f:
            for line in f:
                samples.append(json.loads(line))
        
        if not samples:
            return {"error": "No samples in file"}
        
        # Generate summary
        summary = {
            "total_samples": len(samples),
            "time_range": {
                "first": samples[0].get("timestamp_ns"),
                "last": samples[-1].get("timestamp_ns"),
                "duration_ns": samples[-1].get("timestamp_ns", 0) - samples[0].get("timestamp_ns", 0)
            },
            "sample_types": {},
            "metrics_available": set()
        }
        
        # Count by sample type
        for sample in samples:
            sample_type = sample.get("sample_type", "unknown")
            summary["sample_types"][sample_type] = summary["sample_types"].get(sample_type, 0) + 1
            
            # Collect available metrics
            metrics = sample.get("metrics", {})
            if isinstance(metrics, dict):
                summary["metrics_available"].update(metrics.keys())
        
        summary["metrics_available"] = list(summary["metrics_available"])
        
        return summary

# Command-line interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Resource Monitor for SSH Benchmarking")
    parser.add_argument("--output-dir", default="monitoring_data", help="Output directory")
    parser.add_argument("--interval", type=float, default=0.1, help="Sampling interval in seconds")
    parser.add_argument("--duration", type=float, help="Monitoring duration in seconds (optional)")
    parser.add_argument("--summary", action="store_true", help="Generate summary report")
    
    args = parser.parse_args()
    
    if args.summary:
        monitor = ResourceMonitor(args.output_dir)
        report = monitor.generate_summary_report()
        print(json.dumps(report, indent=2))
    else:
        monitor = ResourceMonitor(args.output_dir, args.interval)
        monitor.start()
        
        try:
            if args.duration:
                time.sleep(args.duration)
                monitor.stop()
            else:
                # Run until interrupted
                while True:
                    time.sleep(1)
        except KeyboardInterrupt:
            monitor.stop()
            print("\nMonitoring stopped by user")
