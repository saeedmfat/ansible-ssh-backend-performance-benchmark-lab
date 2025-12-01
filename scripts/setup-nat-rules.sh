#!/bin/bash
# Remove any existing rules for our network
sudo iptables -t nat -D POSTROUTING -s 10.0.100.0/24 -o enxee98f4c537ca -j MASQUERADE 2>/dev/null || true
sudo iptables -D FORWARD -i lxdbr0 -o enxee98f4c537ca -j ACCEPT 2>/dev/null || true
sudo iptables -D FORWARD -i enxee98f4c537ca -o lxdbr0 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true

# Add correct NAT rules
sudo iptables -t nat -A POSTROUTING -s 10.0.100.0/24 -o enxee98f4c537ca -j MASQUERADE
sudo iptables -I FORWARD -i lxdbr0 -o enxee98f4c537ca -j ACCEPT
sudo iptables -I FORWARD -i enxee98f4c537ca -o lxdbr0 -m state --state RELATED,ESTABLISHED -j ACCEPT

echo "NAT rules configured for LXD network"
