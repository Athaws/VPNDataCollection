#!/bin/bash

set -e

VM_CPU=2
VM_RAM=4096
VM_DISK=20
VM_NETWORK="clientnetwork"
BASE_VM_NAME="client-base"
BASE_DISK_PATH="/var/lib/libvirt/images/${BASE_VM_NAME}.qcow2"

echo_msg() { echo -e "\033[1;33m$1\033[0m"; }
error_exit() { echo -e "\033[1;31m[-] $1\033[0m"; exit 1; }

read -p "[?] How many client VMs do you want to create (not including the base)? " VM_COUNT

    if ! [[ "$VM_COUNT" =~ ^[0-9]+$ ]] || [ "$VM_COUNT" -le 0 ]; then
        echo "[-] Error: Please enter a valid positive number."
        exit 1
    fi

    TOTAL_CORES=$(nproc)
    TOTAL_RAM=$(free -m | awk '/^Mem:/ {print $2}')
    TOTAL_DISK=$(df -BG / | awk 'NR==2 {gsub("G",""); print $4}')

    REQ_CORES=$((VM_CPU * (VM_COUNT + 1)))
    REQ_RAM=$((VM_RAM * (VM_COUNT + 1)))
    REQ_DISK=$((VM_DISK * (VM_COUNT + 1)))

    echo_msg "[+] System Resources:"
    echo "  CPU Cores: $TOTAL_CORES"
    echo "  RAM: ${TOTAL_RAM}MB"
    echo "  Free Disk: ${TOTAL_DISK}GB"

    [ "$REQ_CORES" -gt "$TOTAL_CORES" ] && error_exit "Not enough CPU cores! Needed: $REQ_CORES, Available: $TOTAL_CORES"
    [ "$REQ_RAM" -gt "$TOTAL_RAM" ] && error_exit "Not enough RAM! Needed: ${REQ_RAM}MB, Available: ${TOTAL_RAM}MB"
    [ "$REQ_DISK" -gt "$TOTAL_DISK" ] && error_exit "Not enough disk space! Needed: ${REQ_DISK}GB, Available: ${TOTAL_DISK}GB"

if ! sudo virsh dominfo "$BASE_VM_NAME" &>/dev/null; then
    read -p "[?] Enter the path to the OS image (e.g., /var/lib/libvirt/images/ubuntu.iso): " OS_IMAGE

    [ ! -f "$OS_IMAGE" ] && error_exit "OS image not found at $OS_IMAGE"

    echo_msg "[+] Creating base VM: $BASE_VM_NAME"
    sudo qemu-img create -f qcow2 "$BASE_DISK_PATH" "${VM_DISK}G"

    sudo virt-install --name "$BASE_VM_NAME" \
        --vcpus "$VM_CPU" \
        --memory "$VM_RAM" \
        --disk path="$BASE_DISK_PATH",format=qcow2,bus=virtio \
        --cdrom "$OS_IMAGE" \
        --network network="$VM_NETWORK",model=virtio \
        --os-variant ubuntu24.04 \
        --graphics vnc,listen=0.0.0.0 \
        --console pty,target_type=serial \
        --noautoconsole

    echo "[*] Started install of base VM $VM_NAME"
fi

echo_msg "[*] Waiting for base VM to finish installing..."

while true; do
    STATE=$(sudo virsh domstate "$BASE_VM_NAME" 2>/dev/null || echo "not found")
    if [[ "$STATE" == "shut off" ]]; then
        echo_msg "[✓] Base VM is shut down. Proceeding to clone..."
        break
    fi
    echo -n "."
    sleep 60
done

for i in $(seq 1 "$VM_COUNT"); do
    TARGET_NAME="client-$i"
    TARGET_DISK="/var/lib/libvirt/images/${TARGET_NAME}.qcow2"
    LOG_FILE="logs/clone_${TARGET_NAME}.log"

    echo_msg "[+] Cloning $TARGET_NAME..."
    sudo virt-clone --original "$BASE_VM_NAME" \
        --name "$TARGET_NAME" \
        --file "$TARGET_DISK" > "$LOG_FILE" 2>&1

    echo "[✓] Cloned $TARGET_NAME (log: $LOG_FILE)"
done

echo "[+] All $VM_COUNT VM clones have been created."
echo "[+] Use 'virsh list --all' to list them"
