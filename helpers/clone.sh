#!/bin/bash

read -p "[?] How many client VMs do you want to create? " VM_COUNT

if ! [[ "$VM_COUNT" =~ ^[0-9]+$ ]] || [ "$VM_COUNT" -le 0 ]; then
    echo "[-] Error: Please enter a valid positive number."
    exit 1
fi

mkdir -p logs
for i in $(seq 1 $VM_COUNT); do
  echo "[+] Cloning client-$i..."
  sudo virt-clone --original client-base --name client-$i --file /var/lib/libvirt/images/client-$i.qcow2 > logs/clone_client-$i.log 2>&1
done
wait

echo "[✓] All clones finished. Logs saved to clone_vm*.log"
