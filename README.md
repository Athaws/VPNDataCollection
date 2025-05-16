# VPN Data Collection Tool

Client & Server along with helper scripts to orchestrate VMs that collect VPN-traffic using Mullvad VPN, to analyze effect and overhead of DAITA.

## Set up, Installation and Usage
- Prepare an ISO file of your preferred liking - currently `client.py` is setup for using a slightly stripped custom Ubuntu Desktop 24.04.1 ISO with cloud-init autoinstallation.
- Run `setup.sh` on the host, or simply replicate what it does (install qemu-kvm/virsh/libvirt, enable libvirtd, create virsh network)
- Run `create_client_vms.sh` on the host, or again, simply replicate what it does (virt-install clients)
- While the VM's are installing, setup a background screen session to run the server: `screen -S server`
- In the screen session, run `./server.py --datadir DATADIR --list LIST --database DATABASE --vpnlist LIST [--samples SAMPLES] [--host HOST] [--port PORT]` - brackets == optional (have defaults that work with the client)
- Once the VMS are installed they will shut off - when ready to start the data collection, start them all: `toggle_vms.sh on`
- For now, all of the autoinstallation is handled inside the ISO - eventually this will be moved to outside for an extreme bump in convenience.
    + Our custom ISO simply pulls down this repo after first reboot, then executes the client script immediately (already has all the requirements listed below pre-configured/pre-installed)
- With all of this done, it's now simply time to wait for the POSTs to flood into the server along with the monitor to shut off the operation when everything's fully collected.

## Client
- Ubuntu 24.04.1 (for now, looking to expand to more flavours and operating systems eventually)
- Use `client.py` on the client VMs and make sure it can run. Some of the requirements:
    + GeckoDriver to be installed and in PATH, see https://github.com/mozilla/geckodriver/releases/latest,
    + Tshark to be installed and in PATH, see https://www.wireshark.org/download.html,
    + Firefox (or Mullvad Browser) to be installed,
    + The following Python libraries are needed: `selenium requests pillow psutil`
    + Preferrably, add the running user on client to sudoers with NOPASSWD: ALL
        - Note on this: Mullvad Browser *will not* work if script is ran as root.

## Server
- Ubuntu 24.04 host (can use whatever flavour of GNU/Linux you want, but then you'll need to do your own setup of virsh/qemu/etc.)
- Use `server.py` and make sure it can run. Requires Python modules `flask requests`. 
- We used `screen` to run it in the background; also the script `monitor.sh` in another `screen` session can be used to shut off when collection is complete if you choose to do so as well.
- Custom `database.json` needed for config-data of Mullvad accounts.
- `list` and `serverlist` to supply list of URLs to visit as well as list of (Mullvad VPN) servers to use.

## Disclaimers and Attributions

This tool was developed as part of a Bachelor's thesis at Karlstad University by [Simon Andersson](https://github.com/s4andersson) and [Rasmus Melin](https://athaw.se/).

Primary client, benefactor and supervisor: Senior lecturer [Tobias Pulls](https://pulls.name/), in conjunction with [Mullvad](https://mullvad.net/en).