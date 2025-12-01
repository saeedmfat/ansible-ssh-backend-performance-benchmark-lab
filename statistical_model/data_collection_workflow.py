#!/usr/bin/env python3
"""
Complete Data Collection Workflow for SSH Benchmarking
Orchestrates warm-up runs, measurement iterations, and data collection
"""

import time
import json
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import signal
import sys

class BenchmarkOrchestrator:
    """Orchestrates complete benchmark workflow with statistical rigor"""
    
    def __init__(self, output_dir: str = "benchmark_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Load configuration
        self.config = self._load_configuration()
        
        # Results storage
        self.results = []
        self.current_iteration = 0
        self.stop_requested = False
        
        # Setup signal handling
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_interrupt)
    
    def _load_configuration(self) -> Dict:
        """Load benchmark configuration"""
        config_path = Path("~/ansible-benchmark/statistical_model/statistical_model.yaml").expanduser()
        
        if config_path.exists():
            try:
                import yaml
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f)
            except:
                pass
        
        # Default configuration
        return {
            "experiment_design": {
                "independent_variables": {
                    "ssh_backend": ["controlpersist", "paramiko"],
                    "node_count": [1, 3, 5, 10, 15, 20],
                    "workload_type": ["connection_intensive", "data_transfer", "computation", "realworld", "mixed"]
                }
            },
            "statistical_methodology": {
                "sampling": {
                    "iterations_per_configuration": 5,
                    "warm_up_iterations": 3,
                    "cool_down_period": 30
                }
            }
        }
    
    def generate_experiment_matrix(self) -> List[Dict]:
        """Generate all experiment configurations"""
        configs = []
        
        backends = self.config["experiment_design"]["independent_variables"]["ssh_backend"]
        node_counts = self.config["experiment_design"]["independent_variables"]["node_count"]
        workloads = self.config["experiment_design"]["independent_variables"]["workload_type"]
        
        iterations = self.config["statistical_methodology"]["sampling"]["iterations_per_configuration"]
        warm_ups = self.config["statistical_methodology"]["sampling"]["warm_up_iterations"]
        
        # Generate all combinations
        for backend in backends:
            for node_count in node_counts:
                for workload in workloads:
                    # Warm-up runs
                    for i in range(warm_ups):
                        configs.append({
                            "experiment_id": f"{backend}_{node_count}_{workload}_warmup_{i+1}",
                            "ssh_backend": backend,
                            "node_count": node_count,
                            "workload_type": workload,
                            "iteration": i + 1,
                            "warm_up": True,
                            "target_group": f"targets_{node_count}"
                        })
                    
                    # Measurement runs
                    for i in range(iterations):
                        configs.append({
                            "experiment_id": f"{backend}_{node_count}_{workload}_iteration_{i+1}",
                            "ssh_backend": backend,
                            "node_count": node_count,
                            "workload_type": workload,
                            "iteration": i + 1,
                            "warm_up": False,
                            "target_group": f"targets_{node_count}"
                        })
        
        return configs
    
    def run_single_experiment(self, config: Dict) -> Dict:
        """Run a single experiment configuration"""
        if self.stop_requested:
            return {"status": "cancelled", "config": config}
        
        experiment_id = config["experiment_id"]
        print(f"\n{'='*60}")
        print(f"Starting Experiment: {experiment_id}")
        print(f"{'='*60}")
        
        try:
            # Start measurement collector
            from measurement_collector import ScientificMeasurementCollector
            collector = ScientificMeasurementCollector(str(self.output_dir))
            
            collector.start_experiment(
                experiment_id=config["experiment_id"],
                ssh_backend=config["ssh_backend"],
                node_count=config["node_count"],
                workload_type=config["workload_type"],
                iteration=config["iteration"],
                warm_up=config["warm_up"]
            )
            
            # Run the workload
            workload_script = Path(f"~/ansible-benchmark/scripts/run_workload.sh").expanduser()
            
            cmd = [
                str(workload_script),
                config["workload_type"],
                config["ssh_backend"],
                config["target_group"]
            ]
            
            print(f"Command: {' '.join(cmd)}")
            
            # Execute workload
            start_time = time.time()
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Monitor output
            output_lines = []
            for line in process.stdout:
                output_lines.append(line.strip())
                print(f"  {line.strip()}")
            
            process.wait()
            end_time = time.time()
            
            # Record completion
            collector.record_measurement(
                "workload_completion",
                end_time - start_time,
                "seconds",
                {"exit_code": process.returncode}
            )
            
            # Stop experiment and get results
            results = collector.stop_experiment()
            
            # Add metadata
            results["config"] = config
            results["output"] = output_lines[-10:]  # Last 10 lines
            results["exit_code"] = process.returncode
            results["status"] = "success" if process.returncode == 0 else "failed"
            
            # Cool down period
            if not config["warm_up"]:
                cool_down = self.config["statistical_methodology"]["sampling"]["cool_down_period"]
                print(f"Cooling down for {cool_down} seconds...")
                time.sleep(cool_down)
            
            print(f"Experiment completed: {results['status']}")
            
            return results
            
        except Exception as e:
            print(f"Error in experiment {experiment_id}: {str(e)}")
            return {
                "status": "error",
                "config": config,
                "error": str(e)
            }
    
    def run_parallel_experiments(self, max_parallel: int = 2) -> Dict:
        """Run experiments in parallel (with caution)"""
        all_configs = self.generate_experiment_matrix()
        total_experiments = len(all_configs)
        
        print(f"\n{'#'*60}")
        print(f"BENCHMARK ORCHESTRATOR")
        print(f"{'#'*60}")
        print(f"Total experiments to run: {total_experiments}")
        print(f"Parallel executions: {max_parallel}")
        print(f"Output directory: {self.output_dir}")
        print(f"{'#'*60}\n")
        
        results = {
            "total_experiments": total_experiments,
            "completed": 0,
            "successful": 0,
            "failed": 0,
            "cancelled": 0,
            "experiments": []
        }
        
        # Run in batches to avoid overwhelming the system
        batch_size = max_parallel * 2
        for batch_start in range(0, total_experiments, batch_size):
            if self.stop_requested:
                break
            
            batch = all_configs[batch_start:batch_start + batch_size]
            print(f"\nProcessing batch {batch_start//batch_size + 1}: {len(batch)} experiments")
            
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                future_to_config = {
                    executor.submit(self.run_single_experiment, config): config 
                    for config in batch
                }
                
                for future in as_completed(future_to_config):
                    if self.stop_requested:
                        future.cancel()
                        continue
                    
                    config = future_to_config[future]
                    try:
                        result = future.result(timeout=300)  # 5 minute timeout
                        results["experiments"].append(result)
                        results["completed"] += 1
                        
                        if result.get("status") == "success":
                            results["successful"] += 1
                        elif result.get("status") == "failed":
                            results["failed"] += 1
                        elif result.get("status") == "cancelled":
                            results["cancelled"] += 1
                        
                        # Update progress
                        progress = (results["completed"] / total_experiments) * 100
                        print(f"Progress: {progress:.1f}% ({results['completed']}/{total_experiments})")
                        
                    except Exception as e:
                        print(f"Exception in experiment {config['experiment_id']}: {e}")
                        results["failed"] += 1
                        results["completed"] += 1
        
        # Save summary
        self._save_summary(results)
        
        return results
    
    def run_sequential_experiments(self) -> Dict:
        """Run experiments sequentially (more reliable)"""
        all_configs = self.generate_experiment_matrix()
        total_experiments = len(all_configs)
        
        print(f"\n{'#'*60}")
        print(f"SEQUENTIAL BENCHMARK EXECUTION")
        print(f"{'#'*60}")
        print(f"Total experiments to run: {total_experiments}")
        print(f"Output directory: {self.output_dir}")
        print(f"{'#'*60}\n")
        
        results = {
            "total_experiments": total_experiments,
            "completed": 0,
            "successful": 0,
            "failed": 0,
            "cancelled": 0,
            "experiments": []
        }
        
        for i, config in enumerate(all_configs, 1):
            if self.stop_requested:
                print("Stop requested. Cancelling remaining experiments.")
                break
            
            print(f"\nExperiment {i}/{total_experiments}")
            print(f"ID: {config['experiment_id']}")
            
            result = self.run_single_experiment(config)
            results["experiments"].append(result)
            results["completed"] = i
            
            if result.get("status") == "success":
                results["successful"] += 1
            elif result.get("status") == "failed":
                results["failed"] += 1
            elif result.get("status") == "cancelled":
                results["cancelled"] += 1
            
            # Progress update
            progress = (i / total_experiments) * 100
            remaining = total_experiments - i
            est_time = remaining * 120  # Estimate 2 minutes per experiment
            
            print(f"Progress: {progress:.1f}%")
            print(f"Remaining: {remaining} experiments (~{est_time//60} minutes)")
            print(f"Success rate: {results['successful']}/{i} ({results['successful']/i*100:.1f}%)")
        
        # Save summary
        self._save_summary(results)
        
        return results
    
    def _save_summary(self, results: Dict):
        """Save results summary"""
        summary_file = self.output_dir / "benchmark_summary.json"
        
        summary = {
            "timestamp": datetime.now().isoformat(),
            "total_experiments": results["total_experiments"],
            "completed": results["completed"],
            "successful": results["successful"],
            "failed": results["failed"],
            "cancelled": results["cancelled"],
            "success_rate": (results["successful"] / results["completed"] * 100) if results["completed"] > 0 else 0,
            "configurations_tested": len(set(exp["config"]["experiment_id"].rsplit("_", 2)[0] 
                                          for exp in results["experiments"] if "config" in exp))
        }
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\n{'#'*60}")
        print("BENCHMARK SUMMARY")
        print(f"{'#'*60}")
        print(f"Total experiments: {summary['total_experiments']}")
        print(f"Completed: {summary['completed']}")
        print(f"Successful: {summary['successful']}")
        print(f"Failed: {summary['failed']}")
        print(f"Cancelled: {summary['cancelled']}")
        print(f"Success rate: {summary['success_rate']:.1f}%")
        print(f"Unique configurations: {summary['configurations_tested']}")
        print(f"Summary saved to: {summary_file}")
        print(f"{'#'*60}")
    
    def _handle_interrupt(self, signum, frame):
        """Handle interrupt signals gracefully"""
        print(f"\n{'!'*60}")
        print("INTERRUPT RECEIVED - Stopping benchmark gracefully")
        print(f"{'!'*60}")
        self.stop_requested = True

# Command-line interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SSH Benchmark Orchestrator")
    parser.add_argument("--output-dir", default="benchmark_results", help="Output directory for results")
    parser.add_argument("--parallel", type=int, default=1, help="Number of parallel executions (use with caution)")
    parser.add_argument("--sequential", action="store_true", help="Run experiments sequentially (default)")
    parser.add_argument("--test-single", help="Test single configuration (format: backend_nodes_workload)")
    
    args = parser.parse_args()
    
    orchestrator = BenchmarkOrchestrator(args.output_dir)
    
    if args.test_single:
        # Test single configuration
        parts = args.test_single.split("_")
        if len(parts) >= 3:
            backend, nodes, workload = parts[0], int(parts[1]), "_".join(parts[2:])
            
            config = {
                "experiment_id": f"{backend}_{nodes}_{workload}_test",
                "ssh_backend": backend,
                "node_count": nodes,
                "workload_type": workload,
                "iteration": 1,
                "warm_up": False,
                "target_group": f"targets_{nodes}"
            }
            
            print(f"Testing single configuration: {config}")
            result = orchestrator.run_single_experiment(config)
            print(f"Result: {json.dumps(result, indent=2)}")
    
    elif args.parallel > 1:
        # Parallel execution
        print(f"Running with {args.parallel} parallel executions")
        results = orchestrator.run_parallel_experiments(max_parallel=args.parallel)
    
    else:
        # Sequential execution (default)
        results = orchestrator.run_sequential_experiments()
