#!/usr/bin/env python3
from flask import Flask, request, jsonify
import threading
import requests
import random
import argparse
import os, sys
import time
import json
import re

# shared states, protected by lock
accounts = []
allocated_accounts = {}
vpn_server_list = []
done_dict_on = {}
done_dict_off = {}
pending_visits = []
url2line = {}
datadir = None
samples = None
starting_time = None
last_update_time = None
unique_clients = set()
lock = threading.Lock()

app = Flask(__name__)

@app.route('/')
def hello():
    return "hello world - here be a data collection server\nAvailable endpoints: /setup [GET], /status [GET], /work [GET,POST]\n"

@app.route('/setup', methods=['GET'])
def setup():
    global allocated_accounts
    with lock:
        id = request.args.get('id', default="*", type=str)
        if id == "*":
            return jsonify({"error": "missing id"}), 400
        if id in allocated_accounts:
            return jsonify({
            "account": allocated_accounts[id]
        }), 200
        try:
            allocated_accounts[id] = accounts.pop()
            return jsonify({
                "account": allocated_accounts[id]
            }), 200
        except:
            return jsonify({"error": "no available accounts remain"}), 400

@app.route('/status', methods=['GET'])
def status():
    global done_dict_on, done_dict_off, starting_time, last_update_time, unique_clients, allocated_accounts, vpn_server_list, url2line, lock

    with lock:
        total_collected = 0
        for vpn in vpn_server_list:
            total_collected += (sum(done_dict_on[vpn].values()) + sum(done_dict_off[vpn].values()))
        return jsonify({
            "total_to_collect": 2 * samples * len(url2line) * len(vpn_server_list),
            "total_collected": total_collected,
            "elapsed": time.time() - starting_time,
            "last_update": time.time() - last_update_time,
            "unique_clients": list(unique_clients),
            "allocated_accounts": f"{len(allocated_accounts)} of {len(accounts)}",
        })

@app.route('/work', methods=['GET'])
def get_work():
    global done_dict_on, done_dict_off, unique_clients, allocated_accounts, pending_visits, lock

    with lock:
        id = request.args.get('id', default="*", type=str)
        if not id:
            return ("missing id", 400)
        unique_clients.add(id)

        if pending_visits:
            return jsonify(random.choice(pending_visits))
        else:
            return jsonify({"error": "no links left to visit"}), 400

@app.route('/work', methods=['POST'])
def post_work():
    global done_dict_on, done_dict_off, datadir, samples, last_update_time, unique_clients, pending_visits, lock

    id = request.form.get('id')                 # unique identifier per client
    url = request.form.get('url')               # url visited
    vpn = request.form.get('vpn')               # name of vpn server used
    daita = request.form.get('daita')           # if daita was on or off
    png_data = request.form.get('png_data')     # hex-encoded PNG file
    pcap_data = request.form.get('pcap_data')   # hex-encoded PCAP file

    if not id or not url or not png_data or not pcap_data or not vpn or not daita:
        return "missing one or more required fields", 400

    print("Received work for url: ", url, 'from', id)

    try:
        png_data = bytes.fromhex(png_data)
        pcap_data = bytes.fromhex(pcap_data)
    except:
        return "failed to decode hex-encoded data", 400

    png_kib = len(png_data)/1024
    pcap_kib = len(pcap_data)/1024

    print(f"Got {png_kib:.1f} KiB of PNG data")
    print(f"Got {pcap_kib:.1f} KiB of pcap data")

    # we report 200 here because the client did its reporting, just that the
    # data was too small or large so we won't save it and repeat the visit
    if pcap_kib < 3 or pcap_kib > 1500:
        return ("pcap data too small, but OK", 200)
    if png_kib < 3:
        return ("png data too small, but OK", 200)
    
    print('Saving the sample..')
    with lock:
        done_dict = done_dict_on if daita == 'on' else done_dict_off
        if (daita == "on" and done_dict[vpn][url] >= samples) or (daita == "off" and done_dict[vpn][url] >= samples):
            return ("Already done, but OK", 200)

        # save to disk: datadir/f"{vpn_dir}/{url2line[url]_{on|off}}".{png,pcap}
        site = url2line[url]
        sample = get_free_sample(site, vpn, daita)
        p = os.path.join(datadir, vpn, f"{str(site)}_{daita}", f"{sample}")
        with open(f"{p}.png", 'wb') as f:
            f.write(png_data)
        with open(f"{p}.pcap", 'wb') as f:
            f.write(pcap_data)

        # increment and see if all visits for this combo is done
        done_dict[vpn][url] += 1
        visit = {"url": url, "vpn": vpn, "daita": daita}
        if done_dict[vpn][url] >= samples and visit in pending_visits:
            print(f"Done with {url} for DAITA: {daita} / {vpn}, there are now {len(pending_visits)} combinations left")
            pending_visits.remove(visit)

        last_update_time = time.time()

    return ("OK\n", 200)

def get_free_sample(site, vpn, daita) -> int:
    global datadir, vpn_server_list
    sample = 0
    while True:
        p = os.path.join(datadir, vpn, f"{str(site)}_{daita}", f"{sample}.png")
        if not os.path.exists(p):
            return sample   
        sample += 1

def setup_url_list(url_list) -> None:
    global done_dict_on, done_dict_off, vpn_server_list, url2line

    urls = []
    with open(url_list, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            urls.append(line)

    # requirement: all URLs must be unique
    if len(urls) != len(set(urls)):
        print("URL list contains duplicates, exiting")
        print(f"URL length: {len(urls)}")
        print(f"URL set length: {len(set(urls))}")
        sys.exit(1)
    # requirement: all URLs must be HTTP(S)
    for url in urls:
        if not url.startswith("http://") and not url.startswith("https://"):
            print(f"URL {url} is not HTTP(S), exiting")
            sys.exit(1)

    for vpn in vpn_server_list:
        for (i, url) in enumerate(urls):
            url2line[url] = i
            done_dict_on[vpn][url] = 0
            done_dict_off[vpn][url] = 0

    print(f"Loaded {len(urls)} URLs from {url_list}")

def setup_vpn_list(vpn_list) -> None:
    global vpn_server_list, done_dict_on, done_dict_off

    vpns = []
    with open(vpn_list, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            vpns.append(line)

    # Assert all servers entered actually support DAITA
    mullvad_servers = requests.get("https://api.mullvad.net/app/v1/relays").json()['wireguard']['relays']
    servers_without_daita = [
        vpn_name for vpn_name in vpns if not any(server['hostname'] == vpn_name and server.get('daita', False) for server in mullvad_servers)
    ]

    if servers_without_daita:
        print(f"The following servers do not support DAITA: {', '.join(servers_without_daita)}")
        sys.exit(1)
    vpn_server_list = vpns.copy()
    for vpn in vpn_server_list:
        done_dict_on[vpn] = dict()
        done_dict_off[vpn] = dict()

def setup_datadir(dir) -> None:
    global datadir, url2line, samples, done_dict_on, done_dict_off, vpn_server_list
    total_to_collect = 2 * samples * len(url2line) * len(vpn_server_list)
    total_samples = 0

    if os.path.exists(dir):
        if not os.access(dir, os.W_OK):
            print(f"datadir {dir} is not writable, exiting")
            sys.exit(1)

        for vpn in vpn_server_list:
            vpn_dir = os.path.join(dir, vpn)
            if not os.path.exists(vpn_dir):
                print(f"{vpn_dir} is missing, exiting")
                sys.exit(1)
            if not os.access(vpn_dir, os.W_OK):
                print(f"{vpn_dir} is not writable, exiting")
                sys.exit(1)
            files_on = [
                [f for f in files if not f.startswith(".")]
                for root, _, files in sorted(
                                        os.walk(vpn_dir),
                                        key=lambda x: int(re.search(r"(\d+)_on$", x[0]).group(1)) 
                                        if re.search(r"(\d+)_on$", x[0]) else float("inf")
                                        )
                if root.endswith("_on")
            ]
            files_off = [
                [f for f in files if not f.startswith(".")]
                for root, _, files in sorted(
                                        os.walk(vpn_dir),
                                        key=lambda x: int(re.search(r"(\d+)_off$", x[0]).group(1)) 
                                        if re.search(r"(\d+)_off$", x[0]) else float("inf")
                                        )
                if root.endswith("_off")
            ]
            done_on = [len(files) for files in files_on]
            done_off = [len(files) for files in files_off]
            if sum(done_on) % 2 != 0:
                print(f"{vpn_dir} (on) does not contain a multiple of 2 files, exiting")
                sys.exit(1)
            if sum(done_off) % 2 != 0:
                print(f"{vpn_dir} (off) does not contain a multiple of 2 files, exiting")
                sys.exit(1)

            png_files_on = [[f for f in files if f.endswith(".png")] for files in files_on]
            png_files_off = [[f for f in files if f.endswith(".png")] for files in files_off]
            for i, pnglist in enumerate(png_files_on):
                pcaplist = [png.replace(".png", ".pcap") for png in pnglist]
                if any(pcap not in files_on[i] for pcap in pcaplist):
                    print(f"{vpn_dir} (on) - a pcap file is missing, exiting")
                    sys.exit(1)
            for i, pnglist in enumerate(png_files_off):
                pcaplist = [png.replace(".png", ".pcap") for png in pnglist]
                if any(pcap not in files_off[i] for pcap in pcaplist):
                    print(f"{vpn_dir} (off) - a pcap file is missing, exiting")
                    sys.exit(1)

            for i, url in enumerate(done_dict_on[vpn]):
                done_dict_on[vpn][url] = done_on[i] // 2
            for i, url in enumerate(done_dict_off[vpn]):
                done_dict_off[vpn][url] = done_off[i] // 2
            total_samples += (sum(done_on) // 2 + sum(done_off) // 2)
        
        print(f"datadir {dir} exists, contains {total_samples} samples, {total_to_collect - total_samples} to go")
    else:
        os.mkdir(dir)
        # create subdirs: one per server, two per site/line per server (one for DAITA on, one for DAITA off)
        for vpn in vpn_server_list:
            os.mkdir(os.path.join(dir, vpn))
            for url in done_dict_on[vpn]:
                os.mkdir(os.path.join(dir, vpn, f"{url2line[url]}_on"))
            for url in done_dict_off[vpn]:
                os.mkdir(os.path.join(dir, vpn, f"{url2line[url]}_off"))

        print(f"datadir {dir} created, contains 0 samples, {total_to_collect} to go")

    datadir = dir

def setup_database(database_file) -> None:
    global accounts

    with open(database_file, 'r') as file:
        d = json.load(file)
        accounts = d["accounts"]

        # randomize the accounts
        random.shuffle(accounts)

    print(f"Loaded {len(accounts)} accounts from {database_file}")

def setup_visit_list():
    global pending_visits, done_dict_on, done_dict_off, samples
    
    all_done_dicts = [("on", done_dict_on), ("off", done_dict_off)]
    pending_visits = [
        {"url": url, "vpn": vpn, "daita": daita}
        for daita, done_dict in all_done_dicts
        for vpn in done_dict
        for url, count in done_dict[vpn].items()
        if count < samples
    ]

def main(args) -> None:
    global samples, starting_time, last_update_time
    if not 0 < args.samples < 1000:
        print(f"samples must be in range 0 < x < 1000, exiting")
        sys.exit(1)
    samples = args.samples
    
    setup_vpn_list(args.vpnlist)
    setup_url_list(args.urllist)
    setup_datadir(args.datadir)
    setup_database(args.database)
    setup_visit_list()

    starting_time = time.time()
    last_update_time = starting_time
    app.run(debug=False, threaded=True, port=args.port, host=args.host)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run a data collection server.")
    parser.add_argument("--datadir", type=str, required=True, help="Directory to store data in.")
    parser.add_argument("--urllist", type=str, required=True, help="List of URLs to collect data for.")
    parser.add_argument("--vpnlist", type=str, required=True, help="List of VPNs relays to use")
    parser.add_argument("--samples", type=int, default=100, help="Number of samples to collect for each URL.")
    parser.add_argument("--host", type=str, default="192.168.100.1", help="Host to listen on.")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on.")
    parser.add_argument("--database", type=str, required=True, help="File with mullvad account information.")

    args = parser.parse_args()
    main(args)
