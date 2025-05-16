#!/bin/bash

LOGFILE="collection.log"
URL="http://192.168.100.1:5000/status"
CHECK_INTERVAL=900

while true; do
    response=$(curl -s "$URL")

    if [[ -n "$response" ]]; then
        total_to_collect=$(echo "$response" | jq '.total_to_collect')
        total_collected=$(echo "$response" | jq '.total_collected')

        if [[ "$total_collected" -eq "$total_to_collect" ]]; then
            echo "[+] Collection complete. Shutting down VMs and killing 'server' screen session." >> "$LOGFILE"

            for vm in $(sudo virsh list --state-running --name); do
                sudo virsh shutdown "$vm"
            done

            screen -S server -X quit

            echo "[+] Shutdown of VMs and server script complete." >> "$LOGFILE"
            exit 0
        else
            echo "[ $(date) ] Total collected: $total_collected. Still waiting on hitting $total_to_collect" >> "$LOGFILE"
        fi
    fi
    sleep "$CHECK_INTERVAL"
done
