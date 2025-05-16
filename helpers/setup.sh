#!/bin/bash

set -e

read -p "[?] Enter the network name (default: clientnetwork): " NETWORK_NAME
NETWORK_NAME=${NETWORK_NAME:-clientnetwork}

read -p "[?] Enter the bridge interface name (default: virbr1): " BRIDGE_NAME
BRIDGE_NAME=${BRIDGE_NAME:-virbr1}

read -p "[?] Enter the host machine IP address (default: 192.168.100.1): " IP_ADDRESS
IP_ADDRESS=${IP_ADDRESS:-192.168.100.1}

read -p "[?] Enter the DHCP start range (default: 192.168.100.100): " DHCP_RANGE_START
DHCP_RANGE_START=${DHCP_RANGE_START:-192.168.100.100}

read -p "[?] Enter the DHCP end range (default: 192.168.100.200): " DHCP_RANGE_END
DHCP_RANGE_END=${DHCP_RANGE_END:-192.168.100.200}

read -p "[?] Run in quiet mode? (y/N): " QUIET_MODE
QUIET_MODE=${QUIET_MODE,,}

run_cmd() {
    if [[ "$QUIET_MODE" == "y" ]]; then
        "$@" > /dev/null 2>&1
    else
        "$@"
    fi
}

echo_msg() {
    if [[ "$QUIET_MODE" != "y" ]]; then
        echo "$@"
    fi
}

echo_msg "[+] Updating system package list..."
run_cmd sudo apt update -qq

echo_msg "[+] Installing KVM, QEMU, and required dependencies..."
run_cmd sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virtinst python3-flask python3-requests

echo_msg "[+] Enabling and starting libvirt services..."
run_cmd sudo systemctl enable --now libvirtd

echo_msg "[+] Creating network XML file..."
cat <<EOF | sudo tee /etc/libvirt/qemu/networks/$NETWORK_NAME.xml > /dev/null
<network>
  <name>$NETWORK_NAME</name>
  <bridge name="$BRIDGE_NAME"/>
  <forward mode="nat"/>
  <ip address="$IP_ADDRESS" netmask="$NETMASK">
    <dhcp>
      <range start="$DHCP_RANGE_START" end="$DHCP_RANGE_END"/>
    </dhcp>
  </ip>
</network>
EOF

echo_msg "[+] Defining and starting the virtual network..."
run_cmd sudo virsh net-define /etc/libvirt/qemu/networks/$NETWORK_NAME.xml || echo "Network already defined."
run_cmd sudo virsh net-autostart $NETWORK_NAME
run_cmd sudo virsh net-start $NETWORK_NAME || echo "Network already running."

echo_msg "[+] Adding firewall rules to allow traffic from VMs (PORT 5000 DEFAULT)..."
run_cmd sudo iptables -A INPUT -p tcp --dport 5000 -m iprange --src-range $DHCP_RANGE_START-$DHCP_RANGE_END -j ACCEPT
run_cmd sudo iptables -A INPUT -p tcp --dport 5000 -j DROP

echo "[*] Setup complete. Set the server to listen on IP $IP_ADDRESS when started."
