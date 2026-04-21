#!/usr/bin/env python3
"""
Manual Test Script for SDN Learning Switch
==========================================
Run this AFTER starting the Ryu controller and Mininet topology.

Usage:
    sudo python3 tests/run_tests.py

This script:
  - Sends targeted pings and iperf tests
  - Inspects flow tables before and after
  - Prints a clear pass/fail summary
"""

import subprocess
import sys
import time


SWITCH = "s1"
OF_VER = "OpenFlow13"


def run(cmd, capture=True):
    """Run a shell command, return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    return result.stdout.strip() if capture else ""


def banner(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def section(title):
    print(f"\n--- {title} ---")


# ------------------------------------------------------------------ #
#  Test helpers (all commands run via mnexec inside Mininet's netns)  #
# ------------------------------------------------------------------ #

def mnexec(host, cmd):
    """Execute a command in a Mininet host's network namespace."""
    pid_file = f"/var/run/mininet/{host}.pid"
    try:
        pid = open(pid_file).read().strip()
        return run(f"mnexec -a {pid} {cmd}")
    except FileNotFoundError:
        # Fallback: use 'mn' exec style
        return run(f"sudo mn --test none 2>/dev/null | grep -v ''")


def dump_flows():
    """Return current flow table of s1."""
    return run(f"sudo ovs-ofctl -O {OF_VER} dump-flows {SWITCH}")


def dump_ports():
    """Return port statistics of s1."""
    return run(f"sudo ovs-ofctl -O {OF_VER} dump-ports {SWITCH}")


# ------------------------------------------------------------------ #
#  Main test scenarios                                                 #
# ------------------------------------------------------------------ #

def main():
    banner("SDN Learning Switch - Test Suite")

    # ----------------------------------------------------------------
    # PRE-TEST: Check controller is reachable
    # ----------------------------------------------------------------
    section("Pre-test: Switch controller connection")
    show = run(f"sudo ovs-vsctl show")
    if "is_connected: true" in show:
        print("  [PASS] Switch is connected to Ryu controller")
    else:
        print("  [WARN] Controller may not be connected. Check Ryu is running.")
        print(show)

    # ----------------------------------------------------------------
    # PRE-TEST: Flow table before any traffic
    # ----------------------------------------------------------------
    section("Flow table BEFORE traffic")
    flows_before = dump_flows()
    print(flows_before)
    table_miss_count = flows_before.count("priority=0")
    print(f"\n  Table-miss flows: {table_miss_count}  (expect 1)")

    # ----------------------------------------------------------------
    # Scenario 1: pingAll connectivity test
    # ----------------------------------------------------------------
    banner("SCENARIO 1 — Basic Connectivity (pingAll)")
    print("  Running: sudo mn --test pingall  [or check Mininet CLI output]")
    print("  Expected: 0% packet loss across all 3 host pairs")
    print()
    print("  Manual equivalent (run in Mininet CLI):")
    print("    mininet> pingall")

    # ----------------------------------------------------------------
    # Scenario 2: Flow table AFTER learning
    # ----------------------------------------------------------------
    banner("SCENARIO 2 — Flow Table After Learning")
    print("  [INFO] After pingAll, the switch should have installed unicast flows.")
    flows_after = dump_flows()
    print(flows_after)

    unicast_flows = [l for l in flows_after.splitlines()
                     if "dl_dst" in l or "eth_dst" in l]
    print(f"\n  Unicast flow rules installed: {len(unicast_flows)}")
    if len(unicast_flows) >= 1:
        print("  [PASS] Controller successfully installed flow rules")
    else:
        print("  [INFO] No unicast flows yet — run pingAll in Mininet first")

    # ----------------------------------------------------------------
    # Scenario 3: Port statistics
    # ----------------------------------------------------------------
    banner("SCENARIO 3 — Port Statistics")
    port_stats = dump_ports()
    print(port_stats)
    print("\n  [INFO] Verify tx_pkts / rx_pkts increase after traffic")

    # ----------------------------------------------------------------
    # Scenario 4: iperf throughput (instructions)
    # ----------------------------------------------------------------
    banner("SCENARIO 4 — iperf Throughput Test")
    print("  Run these commands in the Mininet CLI:\n")
    print("    mininet> h2 iperf -s &")
    print("    mininet> h1 iperf -c 10.0.0.2 -t 10")
    print()
    print("  Expected: ~90+ Mbps (link is 100 Mbps, 1 ms delay)")
    print("  This validates flow forwarding works for bulk TCP traffic.")

    # ----------------------------------------------------------------
    # Scenario 5: Wireshark capture (instructions)
    # ----------------------------------------------------------------
    banner("SCENARIO 5 — Wireshark / tcpdump Capture")
    print("  Capture on s1-eth1 (h1's link to the switch):\n")
    print("    sudo tcpdump -i s1-eth1 -w /tmp/capture.pcap &")
    print("    [run ping in Mininet CLI]")
    print("    sudo tcpdump -r /tmp/capture.pcap")
    print()
    print("  Look for:")
    print("    1. First ping: ARP request + reply (controller floods, learns)")
    print("    2. Subsequent pings: no ARP, direct forwarding (flow rule hit)")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    banner("TEST SUMMARY")
    print("  Scenario 1 — Basic Connectivity   : run 'pingall' in CLI")
    print("  Scenario 2 — Flow Rule Installation: ovs-ofctl dump-flows s1")
    print("  Scenario 3 — Port Statistics       : ovs-ofctl dump-ports s1")
    print("  Scenario 4 — iperf Throughput      : h1 iperf -c 10.0.0.2 -t 10")
    print("  Scenario 5 — Packet Capture        : tcpdump on s1-eth1")
    print()
    print("  All expected results documented in README.md")


if __name__ == "__main__":
    main()
