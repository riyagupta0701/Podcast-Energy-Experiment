import json
import math
from pathlib import Path
from collections import defaultdict
import argparse

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.stats import shapiro, ttest_ind, mannwhitneyu

import seaborn as sns


# Load Energy Data From Trial JSON Files

# Reads all trial_*.json files inside each configuration folder.
# Extracts total_energy_joules for successful runs.
# Returns: { config_name : [list of energy values] }

def load_data(results_dir):
    data = defaultdict(list)

    for config_dir in Path(results_dir).iterdir():
        if not config_dir.is_dir():
            continue

        for trial_file in config_dir.glob("trial_*.json"):
            with open(trial_file) as f:
                trial = json.load(f)

            # Only include successful runs
            if trial.get("success"):
                energy = trial["energy_data"]["total_energy_joules"]
                data[config_dir.name].append(energy)

    return data


# Outlier Removal (Three-Standard-Deviation Rule)

# Removes values where:
# |x − mean| > 3 * std
# Returns cleaned list + number of removed samples

def remove_outliers(values):
    mean = np.mean(values)
    std = np.std(values, ddof=1)  # sample standard deviation

    filtered = [
        x for x in values
        if abs(x - mean) <= 3 * std
    ]

    removed = len(values) - len(filtered)
    return filtered, removed


# Descriptive Statistics

# Computes summary statistics for exploratory analysis:
# - n
# - mean
# - standard deviation (sample)
# - median

def describe(values):
    return {
        "n": len(values),
        "mean": np.mean(values),
        "std": np.std(values, ddof=1),
        "median": np.median(values),
    }


# Normality Test (Shapiro-Wilk)

# Returns:
#   p-value
#   Boolean flag (True = normal assumed)

def normality_test(values):
    stat, p = shapiro(values)
    is_normal = p >= 0.05   # p < 0.05 → not normal
    return p, is_normal

# Statistical Hypothesis Testing

# If both groups normal -> Welch's t-test
# If not normal -> Mann-Whitney U test

# Returns:
#   test name
#   p-value

def compare_groups(a, b, normal_a, normal_b):
    normal = normal_a and normal_b

    if normal:
        stat, p = ttest_ind(a, b, equal_var=False) 
        test_name = "Welch's t-test"
    else:
        stat, p = mannwhitneyu(a, b, alternative="two-sided")
        test_name = "Mann-Whitney U"

    return test_name, p


# Effect Size (Parametric)

# Cohen's d: Measures standardized mean difference
# Used only when data are normal

def cohens_d(a, b):
    mean_diff = np.mean(a) - np.mean(b)
    pooled_std = math.sqrt(
        (np.var(a, ddof=1) + np.var(b, ddof=1)) / 2
    )
    return mean_diff / pooled_std


# Effect Size (Non-Parametric)

# Median difference:
#   Difference in medians (delta M)


def median_difference(a, b):
    return np.median(a) - np.median(b)


# Common Language Effect Size (CLES):
#   U / (N1 * N2)

#   Interpreted as probability that
#   a random value from A > random value from B
def common_language_effect_size(a, b):
    stat, _ = mannwhitneyu(a, b, alternative="two-sided")
    n1 = len(a)
    n2 = len(b)
    return stat / (n1 * n2)


# Plotting (Exploratory Visualisation)

def plot_main_results(data, output_dir="results/plots"):

    sns.set(style="whitegrid")

    output_dir = Path(output_dir)
    main_dir = output_dir / "main_figures"
    main_dir.mkdir(parents=True, exist_ok=True)

    # PLAYBACK DIFFERENCE (Section 3.1)

    comparisons = [
        ("chrome_apple_1x", "chrome_apple_2x", "Chrome - Apple"),
        ("chrome_spotify_1x", "chrome_spotify_2x", "Chrome - Spotify"),
        ("brave_apple_1x", "brave_apple_2x", "Brave - Apple"),
        ("brave_spotify_1x", "brave_spotify_2x", "Brave - Spotify"),
    ]

    differences = {}

    for one_x, two_x, label in comparisons:
        if one_x in data and two_x in data:
            mean_1x = np.mean(data[one_x])
            mean_2x = np.mean(data[two_x])
            differences[label] = mean_2x - mean_1x

    if differences:
        labels = list(differences.keys())
        values = list(differences.values())

        plt.figure(figsize=(8, 5))
        plt.bar(labels, values)
        plt.axhline(0)
        plt.ylabel("Energy Difference (2x - 1x) [J]")
        plt.title("Energy Difference Between 2x and 1x Playback")

        for i, v in enumerate(values):
            plt.text(i, v, f"{v:.2f} J",
                     ha="center",
                     va="bottom" if v >= 0 else "top")

        plt.xticks(rotation=20)
        plt.tight_layout()
        plt.savefig(main_dir / "figure1_playback_difference.png", dpi=300)
        plt.close()

    # CHROME PLAYBACK BOXPLOT (Section 3.2)

    chrome_groups = []
    chrome_labels = []

    for config, label in [
        ("chrome_apple_1x", "Apple 1x"),
        ("chrome_apple_2x", "Apple 2x"),
        ("chrome_spotify_1x", "Spotify 1x"),
        ("chrome_spotify_2x", "Spotify 2x"),
    ]:
        if config in data:
            chrome_groups.append(data[config])
            chrome_labels.append(label)

    if chrome_groups:
        plt.figure(figsize=(8, 5))
        sns.boxplot(data=chrome_groups)
        plt.xticks(range(len(chrome_labels)), chrome_labels)
        plt.ylabel("Energy (J)")
        plt.title("Playback Speed Comparison - Chrome")
        plt.tight_layout()
        plt.savefig(main_dir / "figure2_chrome_boxplot.png", dpi=300)
        plt.close()

    # BRAVE PLAYBACK BOXPLOT (Section 3.2)

    brave_groups = []
    brave_labels = []

    for config, label in [
        ("brave_apple_1x", "Apple 1x"),
        ("brave_apple_2x", "Apple 2x"),
        ("brave_spotify_1x", "Spotify 1x"),
        ("brave_spotify_2x", "Spotify 2x"),
    ]:
        if config in data:
            brave_groups.append(data[config])
            brave_labels.append(label)

    if brave_groups:
        plt.figure(figsize=(8, 5))
        sns.boxplot(data=brave_groups)
        plt.xticks(range(len(brave_labels)), brave_labels)
        plt.ylabel("Energy (J)")
        plt.title("Playback Speed Comparison Brave")
        plt.tight_layout()
        plt.savefig(main_dir / "figure3_brave_boxplot.png", dpi=300)
        plt.close()

    # PLATFORM COMPARISON BAR CHART (Section 3.3)

    summary = {
        "Chrome": {"Apple": [], "Spotify": []},
        "Brave": {"Apple": [], "Spotify": []},
    }

    for config, values in data.items():
        mean_val = np.mean(values)

        browser = None
        platform = None

        if "chrome" in config:
            browser = "Chrome"
        elif "brave" in config:
            browser = "Brave"

        if "apple" in config:
            platform = "Apple"
        elif "spotify" in config:
            platform = "Spotify"

        if browser and platform:
            summary[browser][platform].append(mean_val)

    chrome_apple = np.mean(summary["Chrome"]["Apple"])
    chrome_spotify = np.mean(summary["Chrome"]["Spotify"])
    brave_apple = np.mean(summary["Brave"]["Apple"])
    brave_spotify = np.mean(summary["Brave"]["Spotify"])

    browsers = ["Chrome", "Brave"]
    apple_means = [chrome_apple, brave_apple]
    spotify_means = [chrome_spotify, brave_spotify]

    x = np.arange(len(browsers))
    width = 0.35

    plt.figure(figsize=(8, 5))
    plt.bar(x - width / 2, apple_means, width, label="Apple Podcasts")
    plt.bar(x + width / 2, spotify_means, width, label="Spotify")

    plt.xticks(x, browsers)
    plt.ylabel("Average Energy (J)")
    plt.title("Average Energy Consumption by Platform and Browser")
    plt.legend()
    plt.tight_layout()
    plt.savefig(main_dir / "figure4_platform_comparison.png", dpi=300)
    plt.close()

    print(f"Main results figures saved to {main_dir}")

def plot_appendix_results(data, output_dir="results"):
    sns.set(style="whitegrid")

    output_dir = Path(output_dir)
    plots_dir = output_dir / "plots"

    # Create subdirectories
    box_dir = plots_dir / "box"
    violin_dir = plots_dir / "violin"

    box_dir.mkdir(parents=True, exist_ok=True)
    violin_dir.mkdir(parents=True, exist_ok=True)

    configs = list(data.keys())
    values = list(data.values())

    # GLOBAL BOX PLOT
    plt.figure(figsize=(14, 6))
    sns.boxplot(data=values)
    plt.xticks(range(len(configs)), configs, rotation=30)
    plt.ylabel("Energy (Joules)")
    plt.title("Energy Consumption by Configuration")
    plt.tight_layout()
    plt.savefig(box_dir / "global_boxplot.png", dpi=300)
    plt.close()

    # GLOBAL VIOLIN PLOT
    plt.figure(figsize=(14, 6))
    sns.violinplot(data=values)
    plt.xticks(range(len(configs)), configs, rotation=30)
    plt.ylabel("Energy (Joules)")
    plt.title("Energy Distribution by Configuration")
    plt.tight_layout()
    plt.savefig(violin_dir / "global_violinplot.png", dpi=300)
    plt.close()

    # PAIRWISE BOX PLOTS
    pairs = [
        ("chrome_spotify_1x", "chrome_spotify_2x"),
        ("brave_spotify_1x", "brave_spotify_2x"),
        ("chrome_apple_1x", "chrome_apple_2x"),
        ("brave_apple_1x", "brave_apple_2x"),
    ]

    for a, b in pairs:
        if a in data and b in data:
            plt.figure(figsize=(6, 5))
            sns.boxplot(data=[data[a], data[b]])
            plt.xticks([0, 1], [a, b], rotation=15)
            plt.ylabel("Energy (Joules)")
            plt.title(f"{a} vs {b}")
            plt.tight_layout()
            plt.savefig(box_dir / f"{a}_vs_{b}.png", dpi=300)
            plt.close()

    print(f"Plots saved under {plots_dir}")

# MAIN ANALYSIS PIPELINE

# Structure mirrors report sections:
# 3.1 Cleaning
# 3.2 Exploratory analysis
# 3.3 Normality
# 3.4 Significance testing
# 3.5 Effect size

def main():
    
    parser = argparse.ArgumentParser(description="Analyze experiment results")
    parser.add_argument("--input-dir", default="results", help="Results directory")
    args = parser.parse_args()

    # Load measurements
    data = load_data(args.input_dir)

    print("\n=== 3.1 Data Cleaning ===\n")

    cleaned_data = {}
    total_removed = 0

    # Remove statistical outliers per configuration
    for config, values in data.items():
        filtered, removed = remove_outliers(values)
        cleaned_data[config] = filtered
        total_removed += removed

        print(f"{config}: removed {removed} outliers")

    print(f"\nTotal outliers removed: {total_removed}\n")

    print("\n=== 3.2 Exploratory Analysis ===\n")

    # Print statistics
    for config, values in cleaned_data.items():
        stats = describe(values)
        print(f"{config}: {stats}")

    # Generate plots
    plot_appendix_results(cleaned_data)
    
    #Generate blog style plots
    plot_main_results(cleaned_data)

    print("\n=== 3.3 Normality Testing ===\n")

    normality_results = {}

    # Perform Shapiro-Wilk test per configuration
    for config, values in cleaned_data.items():
        p, is_normal = normality_test(values)
        normality_results[config] = is_normal

        print(f"{config}:")
        print(f"  Shapiro p = {p:.6f}")
        print(f"  Normal distribution assumed? {is_normal}\n")

    print("\n=== 3.4 Statistical Significance Testing ===\n")

    # Predefined 1x vs 2x comparisons
    pairs = [
        ("chrome_spotify_1x", "chrome_spotify_2x"),
        ("brave_spotify_1x", "brave_spotify_2x"),
        ("chrome_apple_1x", "chrome_apple_2x"),
        ("brave_apple_1x", "brave_apple_2x"),
    ]

    comparison_results = []

    for a, b in pairs:
        if a in cleaned_data and b in cleaned_data:

            test_name, p = compare_groups(
                cleaned_data[a],
                cleaned_data[b],
                normality_results[a],
                normality_results[b],
            )

            significance = "statistically significant" if p < 0.05 else "not significant"

            print(f"{a} vs {b}")
            print(f"  Test used: {test_name}")
            print(f"  p-value: {p:.6f}")
            print(f"  Result: {significance}\n")

            comparison_results.append((a, b, p))

    print("\n=== 3.5 Effect Size Analysis ===\n")

    # Compute effect sizes depending on normality
    for a, b, p in comparison_results:

        normal = normality_results[a] and normality_results[b]

        print(f"{a} vs {b}")

        if normal:
            d = cohens_d(cleaned_data[a], cleaned_data[b])

            abs_d = abs(d)
            if abs_d < 0.2:
                interpretation = "negligible"
            elif abs_d < 0.5:
                interpretation = "small"
            elif abs_d < 0.8:
                interpretation = "medium"
            else:
                interpretation = "large"

            print(f"  Effect size method: Cohen's d")
            print(f"  Cohen's d = {d:.4f}")
            print(f"  Magnitude: {interpretation}\n")

        else:
            delta_m = median_difference(cleaned_data[a], cleaned_data[b])
            cles = common_language_effect_size(cleaned_data[a], cleaned_data[b])

            print(f"  Effect size method: Non-parametric")
            print(f"  Median difference (delta M) = {delta_m:.4f}")
            print(f"  Common language effect size (U / N1N2) = {cles:.4f}")
            print(f"  Interpretation: {cles*100:.2f}% probability that a random value from {a} exceeds one from {b}\n")


if __name__ == "__main__":
    main()