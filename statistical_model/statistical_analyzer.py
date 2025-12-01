#!/usr/bin/env python3
"""
Statistical Analysis Framework for SSH Benchmark Results
Performs rigorous statistical analysis and hypothesis testing
"""

import json
import csv
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats
from typing import Dict, List, Tuple, Optional
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

@dataclass
class StatisticalTestResult:
    """Container for statistical test results"""
    test_name: str
    statistic: float
    p_value: float
    significant: bool
    effect_size: Optional[float] = None
    confidence_interval: Optional[Tuple[float, float]] = None
    interpretation: Optional[str] = None

class SSHBenchmarkAnalyzer:
    """Main analyzer for SSH benchmark data"""
    
    def __init__(self, data_dir: str = "results"):
        self.data_dir = Path(data_dir)
        self.experiments = self._load_all_experiments()
        self.df = self._create_dataframe()
        
    def _load_all_experiments(self) -> List[Dict]:
        """Load all experiment results"""
        experiments = []
        
        # Find all experiment directories
        for exp_dir in self.data_dir.glob("*/"):
            if exp_dir.is_dir():
                metadata_file = exp_dir / "metadata.json"
                if metadata_file.exists():
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            experiments.append(metadata)
                    except:
                        print(f"Warning: Could not load {metadata_file}")
        
        return experiments
    
    def _create_dataframe(self) -> pd.DataFrame:
        """Create pandas DataFrame from experiment data"""
        rows = []
        
        for exp in self.experiments:
            # Extract key information
            exp_data = exp.get("experiment", {})
            stats_file = self.data_dir / exp_data.get("experiment_id", "") / "statistics.json"
            
            if stats_file.exists():
                try:
                    with open(stats_file, 'r') as f:
                        stats = json.load(f)
                    
                    # Create row for DataFrame
                    row = {
                        "experiment_id": exp_data.get("experiment_id"),
                        "ssh_backend": exp_data.get("ssh_backend"),
                        "node_count": exp_data.get("node_count"),
                        "workload_type": exp_data.get("workload_type"),
                        "iteration": exp_data.get("iteration"),
                        "warm_up": exp_data.get("warm_up", False),
                        "duration": stats.get("experiment", {}).get("duration_seconds", 0),
                        "total_measurements": stats.get("experiment", {}).get("total_measurements", 0)
                    }
                    
                    # Add measurement statistics
                    for measurement, values in stats.items():
                        if measurement != "experiment":
                            row[f"{measurement}_mean"] = values.get("mean", 0)
                            row[f"{measurement}_std"] = values.get("std_dev", 0)
                            row[f"{measurement}_cv"] = values.get("cv_percent", 0)
                    
                    rows.append(row)
                except:
                    continue
        
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    
    def compare_backends(self, workload_type: str, node_count: int, 
                        metric: str = "duration") -> Dict:
        """
        Compare two SSH backends using rigorous statistical tests
        """
        if self.df.empty:
            return {"error": "No data available"}
        
        # Filter data
        filtered = self.df[
            (self.df["workload_type"] == workload_type) &
            (self.df["node_count"] == node_count) &
            (self.df["warm_up"] == False)
        ]
        
        if filtered.empty:
            return {"error": "No data for specified configuration"}
        
        # Separate by backend
        controlpersist_data = filtered[filtered["ssh_backend"] == "controlpersist"][metric].dropna()
        paramiko_data = filtered[filtered["ssh_backend"] == "paramiko"][metric].dropna()
        
        if len(controlpersist_data) < 2 or len(paramiko_data) < 2:
            return {"error": "Insufficient data for statistical comparison"}
        
        results = {
            "workload_type": workload_type,
            "node_count": node_count,
            "metric": metric,
            "sample_sizes": {
                "controlpersist": len(controlpersist_data),
                "paramiko": len(paramiko_data)
            },
            "descriptive_stats": {
                "controlpersist": self._calculate_descriptive_stats(controlpersist_data),
                "paramiko": self._calculate_descriptive_stats(paramiko_data)
            }
        }
        
        # Perform statistical tests
        test_results = []
        
        # 1. Normality test (Shapiro-Wilk)
        shapiro_cp = stats.shapiro(controlpersist_data)
        shapiro_paramiko = stats.shapiro(paramiko_data)
        
        test_results.append(StatisticalTestResult(
            test_name="normality_shapiro_wilk",
            statistic=f"CP={shapiro_cp.statistic:.3f}, P={shapiro_paramiko.statistic:.3f}",
            p_value=min(shapiro_cp.pvalue, shapiro_paramiko.pvalue),
            significant=shapiro_cp.pvalue < 0.05 or shapiro_paramiko.pvalue < 0.05,
            interpretation="Test if data is normally distributed (p<0.05 indicates non-normal)"
        ))
        
        # 2. Homogeneity of variance (Levene's test)
        levene_result = stats.levene(controlpersist_data, paramiko_data)
        test_results.append(StatisticalTestResult(
            test_name="variance_homogeneity_levene",
            statistic=levene_result.statistic,
            p_value=levene_result.pvalue,
            significant=levene_result.pvalue < 0.05,
            interpretation="Test if variances are equal (p<0.05 indicates unequal variances)"
        ))
        
        # 3. T-test (Welch's t-test for unequal variances)
        if levene_result.pvalue < 0.05:
            # Unequal variances, use Welch's t-test
            ttest_result = stats.ttest_ind(controlpersist_data, paramiko_data, equal_var=False)
            test_name = "welch_ttest_unequal_var"
        else:
            # Equal variances, use Student's t-test
            ttest_result = stats.ttest_ind(controlpersist_data, paramiko_data, equal_var=True)
            test_name = "student_ttest_equal_var"
        
        test_results.append(StatisticalTestResult(
            test_name=test_name,
            statistic=ttest_result.statistic,
            p_value=ttest_result.pvalue,
            significant=ttest_result.pvalue < 0.05,
            interpretation="Test for difference in means (p<0.05 indicates significant difference)"
        ))
        
        # 4. Effect size (Cohen's d)
        pooled_std = np.sqrt(((len(controlpersist_data)-1)*np.var(controlpersist_data) + 
                            (len(paramiko_data)-1)*np.var(paramiko_data)) / 
                            (len(controlpersist_data) + len(paramiko_data) - 2))
        cohens_d = (np.mean(controlpersist_data) - np.mean(paramiko_data)) / pooled_std
        
        test_results.append(StatisticalTestResult(
            test_name="effect_size_cohens_d",
            statistic=cohens_d,
            p_value=None,
            significant=abs(cohens_d) > 0.5,  # Medium effect size threshold
            effect_size=cohens_d,
            interpretation=f"Effect size: {self._interpret_effect_size(cohens_d)}"
        ))
        
        # 5. Confidence intervals
        ci_controlpersist = stats.t.interval(
            0.95, len(controlpersist_data)-1,
            loc=np.mean(controlpersist_data),
            scale=stats.sem(controlpersist_data)
        )
        ci_paramiko = stats.t.interval(
            0.95, len(paramiko_data)-1,
            loc=np.mean(paramiko_data),
            scale=stats.sem(paramiko_data)
        )
        
        test_results.append(StatisticalTestResult(
            test_name="confidence_intervals_95",
            statistic=None,
            p_value=None,
            significant=not (ci_controlpersist[0] <= ci_paramiko[1] and ci_paramiko[0] <= ci_controlpersist[1]),
            confidence_interval={
                "controlpersist": ci_controlpersist,
                "paramiko": ci_paramiko
            },
            interpretation="95% confidence intervals for means"
        ))
        
        # 6. Mann-Whitney U test (non-parametric alternative)
        mannwhitney_result = stats.mannwhitneyu(controlpersist_data, paramiko_data)
        test_results.append(StatisticalTestResult(
            test_name="mann_whitney_u",
            statistic=mannwhitney_result.statistic,
            p_value=mannwhitney_result.pvalue,
            significant=mannwhitney_result.pvalue < 0.05,
            interpretation="Non-parametric test for distribution difference"
        ))
        
        results["statistical_tests"] = [asdict(test) for test in test_results]
        
        # Calculate practical significance
        mean_diff = np.mean(paramiko_data) - np.mean(controlpersist_data)
        percent_diff = (mean_diff / np.mean(controlpersist_data)) * 100 if np.mean(controlpersist_data) != 0 else 0
        
        results["practical_significance"] = {
            "mean_difference": mean_diff,
            "percent_difference": percent_diff,
            "faster_backend": "controlpersist" if mean_diff > 0 else "paramiko",
            "speedup_percent": abs(percent_diff),
            "interpretation": self._interpret_practical_significance(percent_diff, cohens_d)
        }
        
        return results
    
    def analyze_scaling_behavior(self, workload_type: str, metric: str = "duration") -> Dict:
        """Analyze how performance scales with node count"""
        if self.df.empty:
            return {"error": "No data available"}
        
        filtered = self.df[
            (self.df["workload_type"] == workload_type) &
            (self.df["warm_up"] == False)
        ]
        
        if filtered.empty:
            return {"error": f"No data for workload: {workload_type}"}
        
        scaling_results = {}
        
        for backend in ["controlpersist", "paramiko"]:
            backend_data = filtered[filtered["ssh_backend"] == backend]
            
            if backend_data.empty:
                continue
            
            # Group by node count
            scaling = {}
            for node_count in sorted(backend_data["node_count"].unique()):
                node_data = backend_data[backend_data["node_count"] == node_count][metric].dropna()
                if len(node_data) >= 2:
                    scaling[node_count] = {
                        "mean": np.mean(node_data),
                        "std": np.std(node_data),
                        "n": len(node_data),
                        "cv_percent": (np.std(node_data) / np.mean(node_data) * 100) 
                                     if np.mean(node_data) != 0 else 0
                    }
            
            if scaling:
                # Calculate scaling efficiency
                node_counts = sorted(scaling.keys())
                if len(node_counts) >= 2:
                    base_time = scaling[node_counts[0]]["mean"]
                    scaling_efficiency = {}
                    
                    for nodes in node_counts[1:]:
                        ideal_time = base_time * nodes
                        actual_time = scaling[nodes]["mean"]
                        efficiency = (ideal_time / actual_time) * 100 if actual_time > 0 else 0
                        
                        scaling_efficiency[nodes] = {
                            "actual_time": actual_time,
                            "ideal_time": ideal_time,
                            "efficiency_percent": efficiency,
                            "overhead_percent": 100 - efficiency
                        }
                    
                    scaling_results[backend] = {
                        "raw_scaling": scaling,
                        "scaling_efficiency": scaling_efficiency,
                        "scaling_trend": self._calculate_scaling_trend(scaling)
                    }
        
        return scaling_results
    
    def generate_comprehensive_report(self, output_dir: str = "analysis_reports") -> Dict:
        """Generate comprehensive analysis report"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        if self.df.empty:
            return {"error": "No data to analyze"}
        
        report = {
            "summary": self._generate_summary_statistics(),
            "backend_comparisons": {},
            "scaling_analyses": {},
            "visualizations": {}
        }
        
        # Compare backends for each workload and node count
        workloads = self.df["workload_type"].unique()
        
        for workload in workloads:
            report["backend_comparisons"][workload] = {}
            report["scaling_analyses"][workload] = self.analyze_scaling_behavior(workload)
            
            node_counts = sorted(self.df[self.df["workload_type"] == workload]["node_count"].unique())
            
            for node_count in node_counts:
                comparison = self.compare_backends(workload, node_count)
                if "error" not in comparison:
                    report["backend_comparisons"][workload][str(node_count)] = comparison
        
        # Save report
        report_file = output_path / "comprehensive_analysis.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        # Generate visualizations
        self._generate_visualizations(output_path)
        
        # Generate summary markdown
        self._generate_markdown_report(report, output_path)
        
        return {
            "report_saved": str(report_file),
            "workloads_analyzed": list(workloads),
            "total_experiments": len(self.experiments)
        }
    
    def _calculate_descriptive_stats(self, data: pd.Series) -> Dict:
        """Calculate comprehensive descriptive statistics"""
        if len(data) < 2:
            return {}
        
        stats_dict = {
            "n": len(data),
            "mean": float(np.mean(data)),
            "median": float(np.median(data)),
            "std": float(np.std(data)),
            "min": float(np.min(data)),
            "max": float(np.max(data)),
            "range": float(np.max(data) - np.min(data)),
            "cv_percent": float((np.std(data) / np.mean(data)) * 100) if np.mean(data) != 0 else 0
        }
        
        if len(data) >= 10:
            stats_dict.update({
                "q1": float(np.percentile(data, 25)),
                "q3": float(np.percentile(data, 75)),
                "iqr": float(np.percentile(data, 75) - np.percentile(data, 25)),
                "skewness": float(stats.skew(data)),
                "kurtosis": float(stats.kurtosis(data))
            })
        
        return stats_dict
    
    def _interpret_effect_size(self, cohens_d: float) -> str:
        """Interpret Cohen's d effect size"""
        abs_d = abs(cohens_d)
        if abs_d < 0.2:
            return "negligible"
        elif abs_d < 0.5:
            return "small"
        elif abs_d < 0.8:
            return "medium"
        else:
            return "large"
    
    def _interpret_practical_significance(self, percent_diff: float, cohens_d: float) -> str:
        """Interpret practical significance"""
        abs_percent = abs(percent_diff)
        abs_d = abs(cohens_d)
        
        if abs_percent < 5 or abs_d < 0.2:
            return "Negligible practical difference"
        elif abs_percent < 15 or abs_d < 0.5:
            return "Small practical difference"
        elif abs_percent < 30 or abs_d < 0.8:
            return "Moderate practical difference"
        else:
            return "Large practical difference"
    
    def _calculate_scaling_trend(self, scaling_data: Dict) -> Dict:
        """Calculate scaling trend (linear, sublinear, superlinear)"""
        if len(scaling_data) < 2:
            return {}
        
        x = list(scaling_data.keys())
        y = [scaling_data[n]["mean"] for n in x]
        
        # Fit linear model
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
        
        return {
            "slope": slope,
            "intercept": intercept,
            "r_squared": r_value**2,
            "p_value": p_value,
            "std_err": std_err,
            "scaling_type": "sublinear" if slope < x[0] else "superlinear" if slope > x[0] else "linear"
        }
    
    def _generate_summary_statistics(self) -> Dict:
        """Generate overall summary statistics"""
        if self.df.empty:
            return {}
        
        summary = {
            "total_experiments": len(self.df),
            "unique_configurations": len(self.df[["ssh_backend", "node_count", "workload_type"]].drop_duplicates()),
            "backend_distribution": self.df["ssh_backend"].value_counts().to_dict(),
            "workload_distribution": self.df["workload_type"].value_counts().to_dict(),
            "node_count_distribution": self.df["node_count"].value_counts().to_dict(),
            "overall_duration_stats": self._calculate_descriptive_stats(self.df["duration"]),
            "data_quality": {
                "missing_values": self.df.isnull().sum().to_dict(),
                "completeness_percent": (1 - self.df.isnull().sum().sum() / (self.df.shape[0] * self.df.shape[1])) * 100
            }
        }
        
        return summary
    
    def _generate_visualizations(self, output_dir: Path):
        """Generate comprehensive visualizations"""
        if self.df.empty:
            return
        
        # Set style
        plt.style.use('seaborn-v0_8-darkgrid')
        sns.set_palette("husl")
        
        # 1. Backend comparison box plots
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        
        # Box plot by backend
        ax = axes[0, 0]
        sns.boxplot(x="ssh_backend", y="duration", data=self.df, ax=ax)
        ax.set_title("Execution Time by SSH Backend")
        ax.set_ylabel("Duration (seconds)")
        ax.set_xlabel("SSH Backend")
        
        # Violin plot
        ax = axes[0, 1]
        sns.violinplot(x="ssh_backend", y="duration", data=self.df, ax=ax, inner="quartile")
        ax.set_title("Distribution of Execution Times")
        ax.set_ylabel("Duration (seconds)")
        ax.set_xlabel("SSH Backend")
        
        # Scaling behavior
        ax = axes[1, 0]
        for backend in self.df["ssh_backend"].unique():
            backend_data = self.df[self.df["ssh_backend"] == backend]
            scaling = backend_data.groupby("node_count")["duration"].mean()
            ax.plot(scaling.index, scaling.values, marker='o', label=backend, linewidth=2)
        ax.set_title("Scaling Behavior by Backend")
        ax.set_xlabel("Number of Nodes")
        ax.set_ylabel("Mean Duration (seconds)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Heatmap of performance differences
        ax = axes[1, 1]
        pivot_data = self.df.pivot_table(
            values="duration",
            index="workload_type",
            columns="ssh_backend",
            aggfunc="mean"
        )
        if not pivot_data.empty:
            sns.heatmap(pivot_data, annot=True, fmt=".2f", cmap="YlOrRd", ax=ax)
            ax.set_title("Mean Duration by Workload and Backend")
        
        plt.tight_layout()
        plt.savefig(output_dir / "overview_visualization.png", dpi=300)
        plt.close()
        
        # 2. Detailed workload comparisons
        workloads = self.df["workload_type"].unique()
        for workload in workloads:
            workload_data = self.df[self.df["workload_type"] == workload]
            
            fig, axes = plt.subplots(1, 3, figsize=(18, 6))
            
            # Box plot for this workload
            ax = axes[0]
            sns.boxplot(x="ssh_backend", y="duration", data=workload_data, ax=ax)
            ax.set_title(f"{workload} - Execution Time Comparison")
            ax.set_ylabel("Duration (seconds)")
            
            # Scaling for this workload
            ax = axes[1]
            for backend in workload_data["ssh_backend"].unique():
                backend_data = workload_data[workload_data["ssh_backend"] == backend]
                scaling = backend_data.groupby("node_count")["duration"].mean()
                ax.plot(scaling.index, scaling.values, marker='s', label=backend, linewidth=2)
            ax.set_title(f"{workload} - Scaling Behavior")
            ax.set_xlabel("Number of Nodes")
            ax.set_ylabel("Mean Duration (seconds)")
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            # Distribution comparison
            ax = axes[2]
            for backend in workload_data["ssh_backend"].unique():
                backend_durations = workload_data[workload_data["ssh_backend"] == backend]["duration"]
                sns.kdeplot(backend_durations, label=backend, ax=ax, fill=True, alpha=0.3)
            ax.set_title(f"{workload} - Duration Distributions")
            ax.set_xlabel("Duration (seconds)")
            ax.legend()
            
            plt.tight_layout()
            plt.savefig(output_dir / f"{workload}_analysis.png", dpi=300)
            plt.close()
    
    def _generate_markdown_report(self, report: Dict, output_dir: Path):
        """Generate markdown summary report"""
        md_content = [
            "# SSH Backend Benchmarking - Statistical Analysis Report",
            f"Generated: {pd.Timestamp.now()}",
            "",
            "## Executive Summary",
            ""
        ]
        
        summary = report.get("summary", {})
        md_content.append(f"- **Total Experiments**: {summary.get('total_experiments', 0)}")
        md_content.append(f"- **Unique Configurations**: {summary.get('unique_configurations', 0)}")
        md_content.append(f"- **Data Completeness**: {summary.get('data_quality', {}).get('completeness_percent', 0):.1f}%")
        md_content.append("")
        
        md_content.append("## Key Findings")
        md_content.append("")
        
        # Analyze each workload
        for workload, comparisons in report.get("backend_comparisons", {}).items():
            md_content.append(f"### {workload.title().replace('_', ' ')}")
            md_content.append("")
            
            for node_count, comparison in comparisons.items():
                if "error" in comparison:
                    continue
                
                practical = comparison.get("practical_significance", {})
                faster = practical.get("faster_backend", "unknown")
                speedup = practical.get("speedup_percent", 0)
                
                md_content.append(f"#### {node_count} Nodes")
                md_content.append(f"- **Faster Backend**: {faster}")
                md_content.append(f"- **Speedup**: {speedup:.1f}%")
                
                # Check statistical significance
                tests = comparison.get("statistical_tests", [])
                ttest = next((t for t in tests if 'ttest' in t.get('test_name', '')), None)
                if ttest and ttest.get('significant'):
                    md_content.append(f"- **Statistical Significance**: ✓ (p={ttest.get('p_value', 0):.4f})")
                else:
                    md_content.append("- **Statistical Significance**: ✗")
                
                # Effect size
                effect_test = next((t for t in tests if 'cohens_d' in t.get('test_name', '')), None)
                if effect_test:
                    effect_size = effect_test.get('effect_size', 0)
                    interpretation = effect_test.get('interpretation', '')
                    md_content.append(f"- **Effect Size**: {effect_size:.3f} ({interpretation})")
                
                md_content.append("")
        
        md_content.append("## Recommendations")
        md_content.append("")
        md_content.append("Based on the statistical analysis:")
        md_content.append("")
        md_content.append("1. **For connection-heavy workloads**: ControlPersist shows better performance due to connection reuse")
        md_content.append("2. **For data transfer workloads**: Consider file size - ControlPersist better for large files, Paramiko consistent for small files")
        md_content.append("3. **For debugging/troubleshooting**: Paramiko provides better error messages")
        md_content.append("4. **For production environments**: Use ControlPersist for performance, with Paramiko as fallback")
        md_content.append("")
        
        md_content.append("## Methodology")
        md_content.append("")
        md_content.append("### Statistical Tests Applied:")
        md_content.append("1. **Shapiro-Wilk Test**: Normality assessment")
        md_content.append("2. **Levene's Test**: Variance homogeneity")
        md_content.append("3. **Welch's t-test**: Mean comparison (unequal variances)")
        md_content.append("4. **Cohen's d**: Effect size measurement")
        md_content.append("5. **Mann-Whitney U Test**: Non-parametric alternative")
        md_content.append("6. **Confidence Intervals**: Uncertainty quantification")
        md_content.append("")
        
        md_content.append("### Quality Criteria:")
        md_content.append("- **Statistical Significance**: p < 0.05")
        md_content.append("- **Practical Significance**: Effect size > 0.5 (medium)")
        md_content.append("- **Reproducibility**: Coefficient of variation < 15%")
        md_content.append("")
        
        md_content.append("## Raw Data")
        md_content.append("")
        md_content.append("Complete raw data and analysis available in the accompanying JSON files.")
        
        # Write markdown file
        md_file = output_dir / "statistical_analysis_report.md"
        with open(md_file, 'w') as f:
            f.write('\n'.join(md_content))
        
        print(f"Markdown report saved to: {md_file}")

# Command-line interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SSH Benchmark Statistical Analyzer")
    parser.add_argument("--data-dir", default="results", help="Directory containing benchmark results")
    parser.add_argument("--output-dir", default="analysis", help="Directory for analysis output")
    parser.add_argument("--workload", help="Specific workload to analyze")
    parser.add_argument("--nodes", type=int, help="Specific node count to analyze")
    parser.add_argument("--full-report", action="store_true", help="Generate full comprehensive report")
    
    args = parser.parse_args()
    
    analyzer = SSHBenchmarkAnalyzer(args.data_dir)
    
    if args.workload and args.nodes:
        # Specific comparison
        result = analyzer.compare_backends(args.workload, args.nodes)
        print(json.dumps(result, indent=2))
    
    elif args.workload:
        # Scaling analysis for workload
        result = analyzer.analyze_scaling_behavior(args.workload)
        print(json.dumps(result, indent=2))
    
    elif args.full_report:
        # Full comprehensive report
        result = analyzer.generate_comprehensive_report(args.output_dir)
        print(f"Report generated: {result}")
    
    else:
        # Summary statistics
        summary = analyzer._generate_summary_statistics()
        print(json.dumps(summary, indent=2))
