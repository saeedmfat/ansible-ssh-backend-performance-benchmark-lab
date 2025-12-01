#!/usr/bin/env python3
"""
Scientific Measurement Collector for SSH Backend Benchmarking
Collects precise timing and resource usage data with statistical rigor
"""

import json
import csv
import time
import statistics
import subprocess
import threading
import queue
from datetime import datetime
from pathlib import Path
import psutil
import numpy as np
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any
import signal
import sys

@dataclass
class MeasurementPoint:
    """A single measurement point with metadata"""
    name: str
    value: float
    unit: str
    timestamp_ns: int
    host: str = "controller"
    process_id: int = 0
    thread_id: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ExperimentRun:
    """Complete experiment run metadata"""
    experiment_id: str
    start_time_ns: int
    end_time_ns: Optional[int] = None
    ssh_backend: str = ""
    node_count: int = 0
    workload_type: str = ""
    iteration: int = 0
    warm_up: bool = False
    measurement_points: List[MeasurementPoint] = field(default_factory=list)
    resource_samples: List[Dict] = field(default_factory=list)
    
    @property
    def duration_ns(self) -> Optional[int]:
        if self.end_time_ns:
            return self.end_time_ns - self.start_time_ns
        return None

class HighPrecisionTimer:
    """High precision timing using monotonic clock"""
    
    @staticmethod
    def now_ns() -> int:
        """Get current time in nanoseconds with maximum precision"""
        return time.perf_counter_ns()
    
    @staticmethod
    def ns_to_seconds(ns: int) -> float:
        """Convert nanoseconds to seconds"""
        return ns / 1_000_000_000.0
    
    @staticmethod
    def measure_latency(func, *args, **kwargs) -> tuple:
        """Measure execution time of a function"""
        start_ns = HighPrecisionTimer.now_ns()
        result = func(*args, **kwargs)
        end_ns = HighPrecisionTimer.now_ns()
        latency_ns = end_ns - start_ns
        return result, latency_ns

class ResourceMonitor(threading.Thread):
    """Background thread for continuous resource monitoring"""
    
    def __init__(self, sample_interval: float = 0.1):
        super().__init__()
        self.sample_interval = sample_interval
        self.stop_event = threading.Event()
        self.samples = []
        self.daemon = True
    
    def run(self):
        """Main monitoring loop"""
        while not self.stop_event.is_set():
            sample = self._collect_sample()
            self.samples.append(sample)
            time.sleep(self.sample_interval)
    
    def _collect_sample(self) -> Dict:
        """Collect a single resource sample"""
        timestamp_ns = HighPrecisionTimer.now_ns()
        
        # System resources
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk_io = psutil.disk_io_counters()
        net_io = psutil.net_io_counters()
        
        # Process-specific resources
        current_process = psutil.Process()
        process_info = {
            "cpu_percent": current_process.cpu_percent(),
            "memory_mb": current_process.memory_info().rss / 1024 / 1024,
            "num_threads": current_process.num_threads(),
            "num_fds": current_process.num_fds() if hasattr(current_process, 'num_fds') else 0
        }
        
        # Container stats (if using LXC)
        container_stats = self._get_container_stats()
        
        return {
            "timestamp_ns": timestamp_ns,
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_used_mb": memory.used / 1024 / 1024,
                "disk_read_mb": disk_io.read_bytes / 1024 / 1024 if disk_io else 0,
                "disk_write_mb": disk_io.write_bytes / 1024 / 1024 if disk_io else 0,
                "net_sent_mb": net_io.bytes_sent / 1024 / 1024 if net_io else 0,
                "net_recv_mb": net_io.bytes_recv / 1024 / 1024 if net_io else 0
            },
            "process": process_info,
            "containers": container_stats
        }
    
    def _get_container_stats(self) -> Dict:
        """Get LXC container statistics if available"""
        try:
            result = subprocess.run(
                ["lxc", "list", "--format", "json"],
                capture_output=True,
                text=True,
                check=True
            )
            containers = json.loads(result.stdout)
            
            stats = {}
            for container in containers:
                if container["status"] == "Running":
                    name = container["name"]
                    try:
                        stat_result = subprocess.run(
                            ["lxc", "info", name, "--resources"],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        if stat_result.returncode == 0:
                            container_stats = {}
                            for line in stat_result.stdout.strip().split('\n'):
                                if ':' in line:
                                    key, value = line.split(':', 1)
                                    container_stats[key.strip()] = value.strip()
                            stats[name] = container_stats
                    except:
                        continue
            return stats
        except:
            return {}
    
    def stop(self):
        """Stop the monitoring thread"""
        self.stop_event.set()
        self.join(timeout=5)
    
    def get_samples(self) -> List[Dict]:
        """Get all collected samples"""
        return self.samples.copy()

class ScientificMeasurementCollector:
    """Main measurement collector with statistical rigor"""
    
    def __init__(self, output_base_dir: str = "results"):
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(exist_ok=True)
        
        self.current_experiment: Optional[ExperimentRun] = None
        self.resource_monitor: Optional[ResourceMonitor] = None
        self.experiment_queue = queue.Queue()
        
        # Setup signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def start_experiment(self, experiment_id: str, ssh_backend: str, 
                        node_count: int, workload_type: str, 
                        iteration: int, warm_up: bool = False) -> str:
        """Start a new experiment run"""
        if self.current_experiment:
            self._finalize_experiment()
        
        # Generate unique experiment ID if not provided
        if not experiment_id:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            experiment_id = f"{ssh_backend}_{node_count}_{workload_type}_{timestamp}"
        
        # Create experiment record
        self.current_experiment = ExperimentRun(
            experiment_id=experiment_id,
            start_time_ns=HighPrecisionTimer.now_ns(),
            ssh_backend=ssh_backend,
            node_count=node_count,
            workload_type=workload_type,
            iteration=iteration,
            warm_up=warm_up
        )
        
        # Start resource monitoring
        self.resource_monitor = ResourceMonitor(sample_interval=0.05)  # 50ms sampling
        self.resource_monitor.start()
        
        # Record experiment start
        self.record_measurement("experiment_start", 0, "seconds")
        
        print(f"[MEASUREMENT] Started experiment: {experiment_id}")
        print(f"[MEASUREMENT] Configuration: {ssh_backend}, {node_count} nodes, {workload_type}")
        
        return experiment_id
    
    def record_measurement(self, name: str, value: float, unit: str, 
                          metadata: Optional[Dict] = None) -> MeasurementPoint:
        """Record a single measurement point"""
        if not self.current_experiment:
            raise RuntimeError("No active experiment. Call start_experiment() first.")
        
        measurement = MeasurementPoint(
            name=name,
            value=value,
            unit=unit,
            timestamp_ns=HighPrecisionTimer.now_ns(),
            process_id=os.getpid() if 'os' in sys.modules else 0,
            thread_id=threading.get_ident(),
            metadata=metadata or {}
        )
        
        self.current_experiment.measurement_points.append(measurement)
        return measurement
    
    def stop_experiment(self) -> Dict:
        """Stop the current experiment and return results"""
        if not self.current_experiment:
            raise RuntimeError("No active experiment")
        
        # Stop resource monitoring
        if self.resource_monitor:
            self.resource_monitor.stop()
            self.current_experiment.resource_samples = self.resource_monitor.get_samples()
        
        # Record experiment end
        self.current_experiment.end_time_ns = HighPrecisionTimer.now_ns()
        self.record_measurement("experiment_end", 0, "seconds")
        
        # Calculate derived metrics
        results = self._calculate_statistics()
        
        # Save results
        self._save_experiment_results()
        
        # Queue for later analysis
        self.experiment_queue.put(self.current_experiment)
        
        print(f"[MEASUREMENT] Experiment completed: {self.current_experiment.experiment_id}")
        print(f"[MEASUREMENT] Duration: {results['duration_seconds']:.2f}s")
        print(f"[MEASUREMENT] Measurements recorded: {len(self.current_experiment.measurement_points)}")
        
        experiment_copy = self.current_experiment
        self.current_experiment = None
        
        return results
    
    def _calculate_statistics(self) -> Dict:
        """Calculate descriptive statistics for the experiment"""
        if not self.current_experiment:
            return {}
        
        # Extract measurement values
        measurement_values = {}
        for point in self.current_experiment.measurement_points:
            if point.name not in measurement_values:
                measurement_values[point.name] = []
            measurement_values[point.name].append(point.value)
        
        # Calculate statistics for each measurement type
        statistics_results = {}
        for name, values in measurement_values.items():
            if len(values) > 1:
                stats = {
                    "count": len(values),
                    "mean": statistics.mean(values),
                    "median": statistics.median(values),
                    "std_dev": statistics.stdev(values) if len(values) > 1 else 0,
                    "min": min(values),
                    "max": max(values),
                    "cv_percent": (statistics.stdev(values) / statistics.mean(values) * 100) 
                                  if statistics.mean(values) != 0 else 0
                }
                
                # Calculate percentiles if we have enough data
                if len(values) >= 10:
                    stats["p25"] = np.percentile(values, 25)
                    stats["p75"] = np.percentile(values, 75)
                    stats["iqr"] = stats["p75"] - stats["p25"]
                
                statistics_results[name] = stats
        
        # Overall experiment statistics
        duration_ns = self.current_experiment.duration_ns or 0
        statistics_results["experiment"] = {
            "duration_seconds": HighPrecisionTimer.ns_to_seconds(duration_ns),
            "total_measurements": len(self.current_experiment.measurement_points),
            "resource_samples": len(self.current_experiment.resource_samples),
            "measurement_frequency_hz": (len(self.current_experiment.measurement_points) / 
                                       HighPrecisionTimer.ns_to_seconds(duration_ns) 
                                       if duration_ns > 0 else 0)
        }
        
        return statistics_results
    
    def _save_experiment_results(self):
        """Save experiment results to files"""
        if not self.current_experiment:
            return
        
        exp_dir = self.output_base_dir / self.current_experiment.experiment_id
        exp_dir.mkdir(exist_ok=True)
        
        # Save experiment metadata
        metadata = {
            "experiment": asdict(self.current_experiment),
            "system_info": self._collect_system_info(),
            "timestamp": datetime.now().isoformat()
        }
        
        with open(exp_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        
        # Save measurements as CSV for easy analysis
        self._save_measurements_csv(exp_dir)
        
        # Save resource samples
        if self.current_experiment.resource_samples:
            with open(exp_dir / "resource_samples.json", "w") as f:
                json.dump(self.current_experiment.resource_samples, f, indent=2)
        
        print(f"[MEASUREMENT] Results saved to: {exp_dir}")
    
    def _save_measurements_csv(self, exp_dir: Path):
        """Save measurements in CSV format"""
        csv_path = exp_dir / "measurements.csv"
        
        with open(csv_path, "w", newline="") as csvfile:
            fieldnames = ["timestamp_ns", "name", "value", "unit", "host", 
                         "process_id", "thread_id", "metadata"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for point in self.current_experiment.measurement_points:
                row = asdict(point)
                row["metadata"] = json.dumps(row["metadata"])
                writer.writerow(row)
        
        # Also save summary statistics
        stats = self._calculate_statistics()
        stats_path = exp_dir / "statistics.json"
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)
    
    def _collect_system_info(self) -> Dict:
        """Collect system information for reproducibility"""
        try:
            # CPU info
            cpu_info = {}
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if ":" in line:
                        key, value = line.split(":", 1)
                        cpu_info[key.strip()] = value.strip()
            
            # Memory info
            memory_info = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if ":" in line:
                        key, value = line.split(":", 1)
                        memory_info[key.strip()] = value.strip()
            
            # Kernel info
            kernel_info = {
                "release": subprocess.run(["uname", "-r"], capture_output=True, text=True).stdout.strip(),
                "version": subprocess.run(["uname", "-v"], capture_output=True, text=True).stdout.strip()
            }
            
            # LXC info
            lxc_info = {}
            try:
                lxc_version = subprocess.run(["lxc", "--version"], capture_output=True, text=True)
                lxc_info["version"] = lxc_version.stdout.strip()
            except:
                lxc_info["version"] = "not_available"
            
            return {
                "cpu": cpu_info,
                "memory": memory_info,
                "kernel": kernel_info,
                "lxc": lxc_info,
                "python_version": sys.version,
                "psutil_version": psutil.__version__
            }
        except:
            return {"error": "Could not collect system info"}
    
    def _finalize_experiment(self):
        """Ensure current experiment is properly finalized"""
        if self.current_experiment:
            try:
                self.stop_experiment()
            except:
                pass
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals gracefully"""
        print(f"\n[MEASUREMENT] Received signal {signum}, finalizing...")
        self._finalize_experiment()
        sys.exit(0)

# Example usage
if __name__ == "__main__":
    # Example of using the measurement collector
    collector = ScientificMeasurementCollector("test_results")
    
    # Start an experiment
    collector.start_experiment(
        experiment_id="test_run_001",
        ssh_backend="controlpersist",
        node_count=5,
        workload_type="connection_intensive",
        iteration=1,
        warm_up=False
    )
    
    # Record some measurements
    collector.record_measurement("connection_start", 0.0, "seconds")
    time.sleep(0.1)
    collector.record_measurement("connection_established", 0.125, "seconds")
    
    # Simulate some workload
    for i in range(5):
        time.sleep(0.05)
        collector.record_measurement(f"task_{i}_complete", 0.05 * (i + 1), "seconds")
    
    # Stop and get results
    results = collector.stop_experiment()
    print(f"Test completed. Results: {json.dumps(results, indent=2)}")
