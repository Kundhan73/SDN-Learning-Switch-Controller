#!/usr/bin/env python3
"""
Mininet Topology for SDN Learning Switch Project
=================================================
Topology:
         h1 (10.0.0.1)
          |
         s1 ---- h2 (10.0.0.2)
          |
         h3 (10.0.0.3)

One Open vSwitch (s1) connected to three hosts.
The Ryu controller runs externally on 127.0.0.1:6633.

Usage:
    sudo python3 topology.py
"""

from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import time


def build_topology():
    """Create and return the Mininet network."""

    # Use RemoteController -> Ryu running on localhost port 6633
    net = Mininet(
        controller=RemoteController,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,   # deterministic MACs: 00:00:00:00:00:01 etc.
        autoStaticArp=False # let the switch learn via ARP (don't pre-populate)
    )

    info("*** Creating controller\n")
    c0 = net.addController(
        "c0",
        controller=RemoteController,
        ip="127.0.0.1",
        port=6633,
        protocol="tcp"
    )

    info("*** Creating switch\n")
    s1 = net.addSwitch("s1", cls=OVSKernelSwitch, protocols="OpenFlow13")

    info("*** Creating hosts\n")
    h1 = net.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
    h2 = net.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")
    h3 = net.addHost("h3", ip="10.0.0.3/24", mac="00:00:00:00:00:03")

    info("*** Creating links (100 Mbps, 1 ms delay)\n")
    net.addLink(h1, s1, bw=100, delay="1ms")
    net.addLink(h2, s1, bw=100, delay="1ms")
    net.addLink(h3, s1, bw=100, delay="1ms")

    return net, c0, s1, [h1, h2, h3]


def run():
    setLogLevel("info")

    info("\n" + "=" * 60 + "\n")
    info("  SDN Learning Switch - Mininet Topology\n")
    info("=" * 60 + "\n\n")

    net, c0, s1, hosts = build_topology()

    info("*** Starting network\n")
    net.start()

    # Force switch to use OpenFlow 1.3
    s1.cmd("ovs-vsctl set bridge s1 protocols=OpenFlow13")

    info("\n*** Topology ready.\n")
    info("    h1: 10.0.0.1  MAC: 00:00:00:00:00:01\n")
    info("    h2: 10.0.0.2  MAC: 00:00:00:00:00:02\n")
    info("    h3: 10.0.0.3  MAC: 00:00:00:00:00:03\n")
    info("    s1 connected to Ryu controller at 127.0.0.1:6633\n\n")

    info("*** Running automated test scenarios...\n\n")
    time.sleep(2)  # allow controller to connect

    # -------------------------------------------------------
    # Scenario 1: Basic connectivity (ping all)
    # -------------------------------------------------------
    info("\n[Scenario 1] Basic ping test (all hosts)\n")
    info("-" * 45 + "\n")
    result = net.pingAll()
    info(f"  Packet loss: {result:.1f}%\n")

    time.sleep(1)

    # -------------------------------------------------------
    # Scenario 2: iperf throughput h1 -> h2
    # -------------------------------------------------------
    info("\n[Scenario 2] iperf throughput  h1 -> h2 (10 seconds)\n")
    info("-" * 45 + "\n")
    h1, h2, h3 = hosts
    h2.cmd("iperf -s &")         # start iperf server on h2
    time.sleep(0.5)
    out = h1.cmd("iperf -c 10.0.0.2 -t 10")
    info(out + "\n")
    h2.cmd("kill %iperf 2>/dev/null")

    # -------------------------------------------------------
    # Scenario 3: Individual pings to verify learning
    # -------------------------------------------------------
    info("\n[Scenario 3] Individual ping tests\n")
    info("-" * 45 + "\n")

    pairs = [("h1", "h2", "10.0.0.2"),
             ("h1", "h3", "10.0.0.3"),
             ("h2", "h3", "10.0.0.3")]

    for src_name, dst_name, dst_ip in pairs:
        src = net.get(src_name)
        result = src.cmd(f"ping -c 3 -W 2 {dst_ip}")
        # Extract the summary line
        for line in result.splitlines():
            if "packet" in line or "rtt" in line:
                info(f"  {src_name} -> {dst_name}: {line.strip()}\n")

    # -------------------------------------------------------
    # Scenario 4: Flow table inspection
    # -------------------------------------------------------
    info("\n[Scenario 4] Flow table on s1\n")
    info("-" * 45 + "\n")
    flow_table = s1.cmd("ovs-ofctl -O OpenFlow13 dump-flows s1")
    info(flow_table + "\n")

    # -------------------------------------------------------
    # Scenario 5: Port statistics
    # -------------------------------------------------------
    info("\n[Scenario 5] Port statistics on s1\n")
    info("-" * 45 + "\n")
    port_stats = s1.cmd("ovs-ofctl -O OpenFlow13 dump-ports s1")
    info(port_stats + "\n")

    info("\n*** Automated tests complete. Entering CLI...\n")
    info("    Try: h1 ping h2, h1 ping h3, ovs-ofctl dump-flows s1\n\n")

    CLI(net)

    info("*** Stopping network\n")
    net.stop()


if __name__ == "__main__":
    run()
