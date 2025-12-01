#!/usr/bin/env python3
"""
Custom Ansible Callback Plugin for Benchmark Logging
Captures detailed timing and performance metrics for SSH backend comparison
"""

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import time
import logging
from datetime import datetime
from collections import defaultdict

from ansible.plugins.callback import CallbackBase
from ansible import constants as C

# Try to import our resource monitor
try:
    from resource_monitor import ResourceMonitor
    HAS_RESOURCE_MONITOR = True
except ImportError:
    HAS_RESOURCE_MONITOR = False

class CallbackModule(CallbackBase):
    """
    Ansible callback plugin for benchmarking and performance monitoring
    """
    
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'benchmark_monitor'
    CALLBACK_NEEDS_WHITELIST = False
    
    def __init__(self):
        super(CallbackModule, self).__init__()
        
        # Setup logging
        self.logger = self._setup_logging()
        
        # Metrics storage
        self.metrics = {
            'playbook_start': None,
            'playbook_end': None,
            'plays': {},
            'tasks': {},
            'hosts': defaultdict(dict),
            'ssh_connections': defaultdict(list),
            'file_transfers': defaultdict(list),
            'errors': []
        }
        
        # Resource monitoring
        self.resource_monitor = None
        if HAS_RESOURCE_MONITOR:
            try:
                self.resource_monitor = ResourceMonitor(
                    output_dir="ansible_metrics",
                    sample_interval=0.05  # 50ms sampling
                )
            except Exception as e:
                self.logger.warning(f"Failed to initialize resource monitor: {e}")
        
        self.current_play = None
        self.current_task = None
        self.task_start_time = None
        
        self.logger.info("Benchmark callback plugin initialized")
    
    def _setup_logging(self):
        """Setup structured logging for the callback"""
        logger = logging.getLogger('ansible.benchmark')
        logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers
        logger.handlers = []
        
        # File handler with JSON formatting
        file_handler = logging.FileHandler('/var/log/ansible_benchmark.jsonl')
        file_handler.setLevel(logging.DEBUG)
        
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_record = {
                    'timestamp': datetime.now().isoformat(),
                    'level': record.levelname,
                    'logger': record.name,
                    'message': record.getMessage(),
                    'module': record.module if hasattr(record, 'module') else 'unknown',
                    'function': record.funcName,
                    'line': record.lineno
                }
                if hasattr(record, 'ansible_metadata'):
                    log_record.update(record.ansible_metadata)
                if record.exc_info:
                    log_record['exception'] = self.formatException(record.exc_info)
                return json.dumps(log_record)
        
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)
        
        return logger
    
    def v2_playbook_on_start(self, playbook):
        """Called when playbook starts"""
        self.metrics['playbook_start'] = time.perf_counter_ns()
        self.metrics['playbook_file'] = playbook._file_name
        
        # Start resource monitoring
        if self.resource_monitor:
            self.resource_monitor.start()
        
        self.logger.info(
            f"Playbook started: {playbook._file_name}",
            extra={'ansible_metadata': {'event': 'playbook_start', 'file': playbook._file_name}}
        )
    
    def v2_playbook_on_play_start(self, play):
        """Called when a play starts"""
        self.current_play = play.get_name()
        play_start = time.perf_counter_ns()
        
        self.metrics['plays'][self.current_play] = {
            'start': play_start,
            'hosts': [h.name for h in play.hosts],
            'vars': dict(play.vars),
            'tasks': []
        }
        
        self.logger.info(
            f"Play started: {self.current_play}",
            extra={'ansible_metadata': {
                'event': 'play_start',
                'play': self.current_play,
                'hosts': len(play.hosts)
            }}
        )
    
    def v2_runner_on_start(self, host, task):
        """Called when a task starts on a host"""
        if not self.current_task:
            self.current_task = task.get_name()
            self.task_start_time = time.perf_counter_ns()
            
            self.metrics['tasks'][self.current_task] = {
                'start': self.task_start_time,
                'module': task.action,
                'args': task.args,
                'host_timings': {}
            }
    
    def v2_runner_on_ok(self, result):
        """Called when a task completes successfully on a host"""
        host = result._host.get_name()
        task_name = result._task.get_name()
        task_end = time.perf_counter_ns()
        
        # Record timing
        if task_name in self.metrics['tasks']:
            task_start = self.metrics['tasks'][task_name]['start']
            duration_ns = task_end - task_start
            
            self.metrics['tasks'][task_name]['host_timings'][host] = {
                'start': task_start,
                'end': task_end,
                'duration_ns': duration_ns,
                'result': 'ok',
                'changed': result.is_changed()
            }
            
            # Special handling for different module types
            if result._task.action == 'copy':
                self._record_file_transfer(host, result, duration_ns)
            elif result._task.action in ['raw', 'command', 'shell']:
                self._record_command_execution(host, result, duration_ns)
            
            self.logger.debug(
                f"Task completed: {task_name} on {host}",
                extra={'ansible_metadata': {
                    'event': 'task_complete',
                    'task': task_name,
                    'host': host,
                    'duration_ns': duration_ns,
                    'module': result._task.action,
                    'changed': result.is_changed()
                }}
            )
    
    def v2_runner_on_failed(self, result, ignore_errors=False):
        """Called when a task fails on a host"""
        host = result._host.get_name()
        task_name = result._task.get_name()
        task_end = time.perf_counter_ns()
        
        error_info = {
            'host': host,
            'task': task_name,
            'module': result._task.action,
            'error': result._result.get('msg', 'Unknown error'),
            'stderr': result._result.get('stderr', ''),
            'stdout': result._result.get('stdout', ''),
            'timestamp_ns': task_end
        }
        
        self.metrics['errors'].append(error_info)
        
        self.logger.error(
            f"Task failed: {task_name} on {host}",
            extra={'ansible_metadata': {
                'event': 'task_failed',
                'task': task_name,
                'host': host,
                'error': error_info['error'],
                'ignore_errors': ignore_errors
            }}
        )
    
    def v2_runner_on_unreachable(self, result):
        """Called when a host is unreachable"""
        host = result._host.get_name()
        task_name = result._task.get_name()
        
        error_info = {
            'host': host,
            'task': task_name,
            'error': 'Host unreachable',
            'details': result._result,
            'timestamp_ns': time.perf_counter_ns()
        }
        
        self.metrics['errors'].append(error_info)
        
        self.logger.error(
            f"Host unreachable: {host}",
            extra={'ansible_metadata': {
                'event': 'host_unreachable',
                'host': host,
                'task': task_name
            }}
        )
    
    def v2_playbook_on_stats(self, stats):
        """Called when playbook ends - generate final metrics"""
        self.metrics['playbook_end'] = time.perf_counter_ns()
        
        # Calculate overall statistics
        playbook_duration_ns = self.metrics['playbook_end'] - self.metrics['playbook_start']
        self.metrics['summary'] = self._calculate_statistics(playbook_duration_ns)
        
        # Stop resource monitoring
        if self.resource_monitor:
            self.resource_monitor.stop()
            resource_summary = self.resource_monitor.generate_summary_report()
            self.metrics['resource_summary'] = resource_summary
        
        # Save metrics
        self._save_metrics()
        
        self.logger.info(
            f"Playbook completed in {playbook_duration_ns / 1e9:.2f} seconds",
            extra={'ansible_metadata': {
                'event': 'playbook_complete',
                'duration_seconds': playbook_duration_ns / 1e9,
                'tasks_executed': len(self.metrics['tasks']),
                'errors': len(self.metrics['errors'])
            }}
        )
    
    def _record_file_transfer(self, host, result, duration_ns):
        """Record file transfer metrics"""
        if 'dest' in result._task.args:
            transfer_info = {
                'host': host,
                'source': result._task.args.get('src', 'inline'),
                'destination': result._task.args.get('dest'),
                'size_bytes': len(result._result.get('content', '')) if 'content' in result._result else 0,
                'duration_ns': duration_ns,
                'throughput_mbps': self._calculate_throughput(
                    len(result._result.get('content', '')),
                    duration_ns
                ) if 'content' in result._result else 0,
                'timestamp_ns': time.perf_counter_ns()
            }
            self.metrics['file_transfers'][host].append(transfer_info)
    
    def _record_command_execution(self, host, result, duration_ns):
        """Record command execution metrics"""
        cmd_info = {
            'host': host,
            'command': result._task.args.get('_raw_params', ''),
            'duration_ns': duration_ns,
            'stdout_length': len(result._result.get('stdout', '')),
            'stderr_length': len(result._result.get('stderr', '')),
            'rc': result._result.get('rc', 0),
            'timestamp_ns': time.perf_counter_ns()
        }
        
        # Store in host metrics
        if 'commands' not in self.metrics['hosts'][host]:
            self.metrics['hosts'][host]['commands'] = []
        self.metrics['hosts'][host]['commands'].append(cmd_info)
    
    def _calculate_throughput(self, size_bytes, duration_ns):
        """Calculate throughput in MB/s"""
        if duration_ns == 0:
            return 0
        return (size_bytes / (duration_ns / 1e9)) / 1024 / 1024
    
    def _calculate_statistics(self, total_duration_ns):
        """Calculate comprehensive statistics"""
        stats = {
            'total_duration_seconds': total_duration_ns / 1e9,
            'task_count': len(self.metrics['tasks']),
            'host_count': len(self.metrics['hosts']),
            'error_count': len(self.metrics['errors']),
            'file_transfer_count': sum(len(transfers) for transfers in self.metrics['file_transfers'].values()),
            'tasks': {},
            'host_performance': {}
        }
        
        # Calculate task statistics
        for task_name, task_data in self.metrics['tasks'].items():
            if task_data['host_timings']:
                durations = [t['duration_ns'] for t in task_data['host_timings'].values()]
                stats['tasks'][task_name] = {
                    'count': len(durations),
                    'mean_ns': sum(durations) / len(durations),
                    'min_ns': min(durations),
                    'max_ns': max(durations),
                    'std_ns': self._calculate_std(durations)
                }
        
        # Calculate host performance statistics
        for host, host_data in self.metrics['hosts'].items():
            if 'commands' in host_data:
                cmd_durations = [cmd['duration_ns'] for cmd in host_data['commands']]
                stats['host_performance'][host] = {
                    'command_count': len(cmd_durations),
                    'mean_command_duration_ns': sum(cmd_durations) / len(cmd_durations) if cmd_durations else 0,
                    'total_commands_executed': len(cmd_durations)
                }
        
        return stats
    
    def _calculate_std(self, values):
        """Calculate standard deviation"""
        if len(values) < 2:
            return 0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def _save_metrics(self):
        """Save metrics to file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"/var/log/ansible_benchmark_metrics_{timestamp}.json"
            
            with open(filename, 'w') as f:
                json.dump(self.metrics, f, indent=2, default=str)
            
            self.logger.info(f"Metrics saved to {filename}")
            
            # Also save summary CSV for easy analysis
            self._save_summary_csv(filename.replace('.json', '_summary.csv'))
            
        except Exception as e:
            self.logger.error(f"Failed to save metrics: {e}")
    
    def _save_summary_csv(self, filename):
        """Save summary statistics to CSV"""
        try:
            import csv
            
            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                
                # Write header
                writer.writerow([
                    'task_name', 'module', 'host_count', 'mean_duration_ms',
                    'min_duration_ms', 'max_duration_ms', 'std_duration_ms'
                ])
                
                # Write task statistics
                for task_name, stats in self.metrics.get('summary', {}).get('tasks', {}).items():
                    writer.writerow([
                        task_name,
                        self.metrics['tasks'].get(task_name, {}).get('module', 'unknown'),
                        stats['count'],
                        stats['mean_ns'] / 1e6,  # Convert to milliseconds
                        stats['min_ns'] / 1e6,
                        stats['max_ns'] / 1e6,
                        stats['std_ns'] / 1e6
                    ])
            
            self.logger.debug(f"Summary CSV saved to {filename}")
            
        except Exception as e:
            self.logger.warning(f"Failed to save CSV summary: {e}")

# Enable this callback by adding to ansible.cfg:
# callback_plugins = /path/to/this/directory
# callback_whitelist = benchmark_monitor
