#!/bin/bash

echo "Checking system requirements for scientific benchmarking..."

ERRORS=0

# Check Python
echo -n "Python 3.8+: "
if python3 --version | grep -q "Python 3\.[8-9]\|Python 3\.1[0-9]"; then
    echo "✓ $(python3 --version)"
else
    echo "✗ $(python3 --version) - Python 3.8+ required"
    ERRORS=$((ERRORS + 1))
fi

# Check Ansible
echo -n "Ansible: "
if ansible --version &>/dev/null; then
    echo "✓ $(ansible --version | head -1)"
else
    echo "✗ Not installed"
    ERRORS=$((ERRORS + 1))
fi

# Check LXC/LXD
echo -n "LXD: "
if lxc --version &>/dev/null; then
    echo "✓ $(lxc --version)"
else
    echo "✗ Not installed"
    ERRORS=$((ERRORS + 1))
fi

# Check Python packages
echo -n "Python packages: "
REQUIRED_PACKAGES="numpy scipy pandas matplotlib seaborn psutil"
MISSING=""
for pkg in $REQUIRED_PACKAGES; do
    if ! python3 -c "import $pkg" &>/dev/null; then
        MISSING="$MISSING $pkg"
    fi
done

if [ -z "$MISSING" ]; then
    echo "✓ All required packages installed"
else
    echo "✗ Missing:$MISSING"
    ERRORS=$((ERRORS + 1))
fi

# Check disk space
echo -n "Disk space (> 10GB free): "
FREE_GB=$(df -BG ~ | awk 'NR==2 {print $4}' | sed 's/G//')
if [ "$FREE_GB" -gt 10 ]; then
    echo "✓ ${FREE_GB}GB free"
else
    echo "✗ Only ${FREE_GB}GB free"
    ERRORS=$((ERRORS + 1))
fi

# Check memory
echo -n "Memory (> 8GB total): "
TOTAL_GB=$(free -g | awk '/^Mem:/ {print $2}')
if [ "$TOTAL_GB" -ge 8 ]; then
    echo "✓ ${TOTAL_GB}GB total"
else
    echo "✗ Only ${TOTAL_GB}GB total"
    ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -eq 0 ]; then
    echo ""
    echo "✓ All system requirements satisfied"
    exit 0
else
    echo ""
    echo "✗ Found $ERRORS requirement issues"
    echo "Please fix these before running benchmarks"
    exit 1
fi
