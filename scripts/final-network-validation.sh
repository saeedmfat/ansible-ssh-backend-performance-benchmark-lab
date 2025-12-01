#!/bin/bash

echo "=== FINAL NETWORK VALIDATION ==="
echo

echo "1. Container Network Status:"
lxc list
echo

echo "2. Container Network Details:"
lxc exec ansible-base-template -- ip addr show eth0
lxc exec ansible-base-template -- ip route show
echo

echo "3. DNS Configuration:"
lxc exec ansible-base-template -- cat /etc/resolv.conf
echo

echo "4. Connectivity Tests:"
echo "   - Gateway (10.0.100.1):"
lxc exec ansible-base-template -- ping -c 2 10.0.100.1 > /dev/null 2>&1 && echo "      ✓ SUCCESS" || echo "      ✗ FAILED"
echo "   - Internet IP (8.8.8.8):"
lxc exec ansible-base-template -- ping -c 2 8.8.8.8 > /dev/null 2>&1 && echo "      ✓ SUCCESS" || echo "      ✗ FAILED"
echo "   - DNS Resolution:"
lxc exec ansible-base-template -- nslookup google.com > /dev/null 2>&1 && echo "      ✓ SUCCESS" || echo "      ✗ FAILED"
echo "   - Internet Hostname:"
lxc exec ansible-base-template -- ping -c 2 google.com > /dev/null 2>&1 && echo "      ✓ SUCCESS" || echo "      ✗ FAILED"
echo

echo "5. Package Manager Test:"
lxc exec ansible-base-template -- apt update > /dev/null 2>&1 && echo "   ✓ SUCCESS" || echo "   ✗ FAILED"

echo
echo "=== VALIDATION COMPLETE ==="
