#!/usr/bin/env python3
import argparse
import random
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
import time
import subprocess
import platform
import os
import tempfile
import requests
from urllib.parse import urljoin
import json
from datetime import datetime, timedelta, timezone
from PIL import Image
import io
import psutil
import socket
import hashlib

DEVICE_CONFIG_FILE = r"/etc/mullvad-vpn/device.json"

# global variable to store the process object of the capture
capture_process = None
tmp_pcap_file = os.path.join(tempfile.gettempdir(), "temp_capture.pcap")
whoami = None

# global session for all requests through a proxy
session = requests.Session()

def start_pcap_capture(windows_interface="Ethernet0"):
    global capture_process, tmp_pcap_file
    cmd = []

    # cleanup any previous pcap
    try:
        capture_process.terminate()
        os.remove(tmp_pcap_file)
    except Exception as e:
        pass

    # using tshark to capture network traffic, only UDP packets and only the
    # first 64 bytes of each packet
    if platform.system() == "Windows":
        cmd = ["tshark", "-i", windows_interface, "-f" ,"port 51820" ,"-s", "64", "-w", tmp_pcap_file]
    else: # Linux and potentially macOS
        cmd = ["sudo", "tshark", "-i", "any", "-f" ,"port 51820" ,"-s", "64", "-w", tmp_pcap_file]
    capture_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def end_pcap_capture():
    global capture_process, tmp_pcap_file
    capture_process.terminate()
    
    cmd = ["sudo", "cat", tmp_pcap_file]
    pcap_data = subprocess.run(cmd, 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE,
                               ).stdout
    
    cmd = ["sudo", "rm", tmp_pcap_file]
    subprocess.run(cmd)
    return pcap_data

def wait_for_page_load(driver, timeout, extra_sleep=2):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )

    time.sleep(extra_sleep)

def start_browser(custom_path):
    try:
        options = Options()
        options.binary_location = custom_path
        firefox_service = Service(executable_path="/usr/local/bin/geckodriver",)
        driver = webdriver.Firefox(options=options, service=firefox_service)
        # we try default from exp1
        # driver.set_window_size(2560, 1440) # 1440p
        return driver
    except Exception as error:
        print("exception on start_browser:", error)
        return None

def visit_site(driver, url, timeout):
    screenshot_as_binary = None
    try:
        driver.command_executor.set_timeout(timeout)
        driver.get(url)
        wait_for_page_load(driver, timeout)
    except Exception as error:
        print("exception on visit:", error)
        driver.quit()
        close_executable("mullvad-browser")
        return None

    try:
        screenshot_as_binary = driver.get_screenshot_as_png()
        # resize screenshot
        # Load the screenshot into Pillow Image
        image = Image.open(io.BytesIO(screenshot_as_binary))

        # Resize the image to 50% of its original size
        new_size = (int(image.width / 2), int(image.height / 2))
        resized_image = image.resize(new_size, Image.LANCZOS)

        # Save the resized image to a BytesIO object in PNG format with 90% quality
        image_bytes_io = io.BytesIO()
        resized_image.save(image_bytes_io, format="PNG", quality=90)
        screenshot_as_binary = image_bytes_io.getvalue()
    except Exception as error:
        print("exception on screenshot:", error)
    finally:
        driver.quit()
        close_executable("mullvad-browser")

    return screenshot_as_binary

def close_executable(executable_name):
    try:
        subprocess.run(
            ["sudo", "pkill", "-f", executable_name],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except:
        pass

def is_mullvadvpn_service_running():
    try:
        result = subprocess.run(["sudo", "systemctl", "is-active", "mullvad-daemon"],
            capture_output=True, text=True, check=True)
        return "active" in result.stdout
    except Exception as e:
        print("is_mullvadvpn_service_running error", e)
        return False

def toggle_mullvadvpn_service(action):
    try:
        print("Toggling mullvadvpn service:", action)
        if action == "on":
            action = "start"
        else:
            action = "stop"
        subprocess.run(["sudo", "systemctl", action, "mullvad-daemon"], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    except Exception as e:
        print("toggle_mullvadvpn_service error", e)

def toggle_mullvadvpn_tunnel(action):
    try:
        print("Toggling mullvadvpn tunnel:", action)
        if action == "on":
            action = "connect"
        else:
            action = "disconnect"

        subprocess.run(["mullvad", action], capture_output=True, text=True, check=True)
        time.sleep(2)
    except Exception as e:
        print("toggle_mullvadvpn_tunnel error", e)
        return False

def is_mullvadvpn_tunnel_running():
    try:
        result = subprocess.run(["mullvad", "status"], capture_output=True, text=True, check=True)
        return "Connected" in result.stdout
    except Exception as e:
        print("is_mullvadvpn_tunnel_running error", e)
        return False

def configure_mullvad(account):#, settings):
    try:
        # enable LAN access
        command = ["mullvad", "lan", "set", "allow"]
        subprocess.run(command, capture_output=True, text=True, check=True)

        # enable DAITA
        command = ["mullvad", "tunnel", "set", "wireguard", "--daita", "on"]
        subprocess.run(command, capture_output=True, text=True, check=True)

        # use default mullvad port 51820
        command = ["mullvad", "relay", "set", "tunnel", "wireguard", "-p", "51820"]
        subprocess.run(command, capture_output=True, text=True, check=True)

    except Exception as e:
        print("configure_mullvad error", e)
        return False

def get_device_json(account):
    # we set the timestamp 1 year in the future, this is to prevent the client
    # from refreshing our keys, the refresh doesn't work very well when we set
    # a custom relay
    timestamp = datetime.now(timezone.utc) + timedelta(days=365)
    timestamp = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "logged_in": {
            "account_token": account["account_token"],
            "device": {
                "id": account["device_id"],
                "name": account["device_name"],
                "wg_data": {
                    "private_key": account["device_private_key"],
                    "addresses": {
                        "ipv4_address": account["device_ipv4_address"],
                        "ipv6_address": account["device_ipv6_address"]
                    },
                    "created": timestamp
                },
                "hijack_dns": False,
                "created": timestamp
            }
        }
    }

def setup_vpn(server):
    global session
    try:
        response = session.get(urljoin(server, "setup"), params={'id': whoami})

        if response.status_code != 200:
            print("Received unexpected status code from server:", response.status_code)
            return False

        # we assume the output from the server is correct, and looks something like:
        # {
        #   "account": {
        #     "account_token": "9321816363818742",
        #     "device_id": "a3eedd02-09c1-4f5b-9090-9f3d27ea66bb",
        #     "device_ipv4_address": "10.64.10.49/32",
        #     "device_ipv6_address": "fc00:bbbb:bbbb:bb01::a40:a31/128",
        #     "device_name": "gifted krill",
        #     "device_private_key": "MCWA6YO5PBE/MEsyRqs6Teej1GKqhGJFnH3xCCvjC2c="
        #   }
        # }
        data = response.json()
        account = data["account"]

        # stop the mullvadvpn service and disconnect the tunnel
        if is_mullvadvpn_service_running():
            toggle_mullvadvpn_tunnel("off")
            toggle_mullvadvpn_service("off")

        # overwrite the device config with data submitted by the server
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp_f:
            json.dump(get_device_json(account), tmp_f, indent=4)
            tmp_path = tmp_f.name
        subprocess.run(["sudo", "mv", tmp_path, DEVICE_CONFIG_FILE], check=True)
        
        # enable the mullvadvpn daemon again, this has to be done prior to the
        # configuration of the mullvad daemon
        toggle_mullvadvpn_service("on")

        # make some configuration
        configure_mullvad(account)

        # and finally, enable the tunnel
        toggle_mullvadvpn_tunnel("on")

        if not is_mullvadvpn_tunnel_running():
            raise Exception("unable to establish a mullvad vpn tunnel connection")

        return True
    except Exception as e:
        print("setup failed, error", e)
        return False

def get_work(server):
    global session
    try:
        work_url = urljoin(server, "work")
        response = session.get(work_url, params={'id': whoami})
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return ""

def post_work_to_server(server, url, png_data, pcap_data):
    global session
    payload = {
        'id': whoami,
        'url': url,
        'png_data': png_data.hex(),
        'pcap_data': pcap_data.hex(),
    }
    try:
        return session.post(urljoin(server, "work"), data=payload).status_code == 200
    except requests.RequestException:
        return False

def is_admin():
    return os.geteuid() == 0

def successful_tunnel_restart():
    toggle_mullvadvpn_tunnel("off")
    toggle_mullvadvpn_service("off")
    toggle_mullvadvpn_service("on")
    toggle_mullvadvpn_tunnel("on")
    return is_mullvadvpn_tunnel_running()

def generate_identifier():
    ip_addresses = []

    # Get info about all network interfaces
    for _, interface_addresses in psutil.net_if_addrs().items():
        for address in interface_addresses:
            if address.family == socket.AF_INET:  # Check for IPv4 addresses
                ip_address = address.address
                if ip_address != "127.0.0.1":  # Exclude localhost
                    ip_addresses.append(ip_address)

    # Fallback to localhost if no external IP found
    if not ip_addresses:
        ip_addresses.append('127.0.0.1')

    # Concatenate all IP addresses into a single string
    concatenated_ips = ''.join(ip_addresses)

    # Hash the concatenated string to generate a fixed-length identifier
    hash_object = hashlib.md5(concatenated_ips.encode())
    hex_dig = hash_object.hexdigest()

    # Return the first 16 characters of the hash
    return hex_dig[:16]

def main(args):
    global whoami
    global session
    print("requires Python 3.6+")
    print("requires GeckoDriver to be installed and in PATH, see https://github.com/mozilla/geckodriver/releases/latest")
    print("requires tshark to be installed and in PATH, see https://www.wireshark.org/download.html")
    print("requires executing user to have sudoer rights: ALL=(ALL) NOPASSWD: ALL")
    print("requires Firefox (or Mullvad Browser) to be installed")
    print("requires `pip install selenium requests Pillow psutil`")

    # deterministic identifier of 16 characters, derived from the IP addresses
    # of the machine
    whoami = generate_identifier()
    print(f"whoami: {whoami}")

    server = "http://" + args.server if not args.server.startswith("http://") else args.server

    while True:
        while not setup_vpn(server):
            r = random.randint(10, 20)
            print(f"VPN is not setup, sleeping for {r} seconds")
            time.sleep(r)

        # Keep track of how many iterations of work have been completed. When
        # args.restart_tunnel_threshold is reached, we'll restart the tunnel.
        work_count = 0

        # Keep track of the number of attempts to get work from the server. If
        # we fail to get work from the server 10 times in a row, we'll restart
        # the tunnel.
        work_attempts = 0

        while True:
            work = get_work(server)
            if not work:
                # disable tunnel and service if no work, prevents traffic from
                # idle clients
                if is_mullvadvpn_service_running():
                    toggle_mullvadvpn_tunnel("off")
                    toggle_mullvadvpn_service("off")

                work_attempts += 1
                if work_attempts > 10:
                    print("Failed to get work from server 10 times in a row, stopping client")
                    break

                r = random.randint(10, 20)
                print(f"No work available, sleeping for {r} seconds")
                time.sleep(r)
            else:
                # reset work attempts and restart VPN if it's not running
                work_attempts = 0
                if not is_mullvadvpn_service_running():
                    toggle_mullvadvpn_service("on")
                    toggle_mullvadvpn_tunnel("on")

                print(f"{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Got work: {work}")
                driver = start_browser(args.firefox)
                if driver is None:
                    print("Failed to start browser, skipping work")
                    continue
                # Sleep for 5 seconds to let the browser start up. Every visit has a
                # fresh browser and profile thanks to Selenium. This is a little bit
                # of being a bad citizen, but hopefully it's not too bad.
                # Unfortunately the options to cache reset within Firefox aren't
                # reliable enough to use.
                time.sleep(5)
                start_pcap_capture()
                png = visit_site(driver, work, args.timeout)
                if png is None:
                    print("Failed to visit site, skipping work")
                    end_pcap_capture()
                    continue
                print(f"Captured {len(png)/1024:.1f} KiB of png data.")
                pcap_bytes = end_pcap_capture()
                print(f"Captured {len(pcap_bytes)/1024:.1f} KiB of pcap data.")
                while not post_work_to_server(server, work, png, pcap_bytes):
                    r = random.randint(10, 20)
                    print(f"Failed to post work to server, retrying in {r} seconds")
                    time.sleep(r)

                # Increment the counter and check whether or not the threshold has
                # been reached, when it's reached we'll restart the tunnel.
                work_count += 1
                if work_count > args.restart_tunnel_threshold:
                    print("Restart tunnel threshold reached, restarting tunnel")

                    while not successful_tunnel_restart():
                        r = random.randint(10, 20)
                        print(f"Tunnel restart failed, sleeping for {r} seconds")
                        time.sleep(r)

                    work_count = 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture a screenshot with Selenium and send to a server.")
    # Mullvad Browser binary path argument with a default value
    parser.add_argument("--firefox", default="/usr/lib/mullvad-browser/mullvadbrowser.real",
                        help="Path to the Firefox binary.")
    # Timeout argument with a default value of 20 seconds
    parser.add_argument("--timeout", type=float, default=20.0, 
                        help="Time to wait for website to load.")
    # Collection server URL argument with a default value
    parser.add_argument("--server", default="http://localhost:5000",
                        help="URL of the collection server.")
    parser.add_argument("--restart-tunnel-threshold", type=int, default=5,
                        help="Restart tunnel threshold.")
    args = parser.parse_args()
    main(args)
