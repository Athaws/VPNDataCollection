#!/bin/bash

read -r -p "[?] Really remove all VMs? NOTE: This will also clear the DHCP leases of the network. (y/N): " CONFIRM

if [ "$CONFIRM" != "y" ]; then
    exit 1
fi

VM_NETWORK="clientnetwork"

echo "[+] Removing old DHCP leases to accomodate net clients"

sudo virsh net-destroy $VM_NETWORK
sudo rm -f /var/lib/libvirt/dnsmasq/$VM_NETWORK.leases
sudo virsh net-start $VM_NETWORK

echo "[+] Terminating all running VMs"

for vm in $(sudo virsh list --state-running --name); do
    sudo virsh destroy $vm
done

echo "[+] Undefining all VMs and deleting qcow2 files"

for vm in $(sudo virsh list --all --name | grep '[0-9]'); do
    sudo rm /var/lib/libvirt/images/$vm.qcow2
    sudo virsh undefine $vm
done
    
echo "All VMs have been deleted and undefined"
