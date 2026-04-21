# SDN Learning Switch Controller

**Course Assignment — Computer Networks | SDN Mininet Project (Orange)**

## Problem Statement

Implement an SDN controller that mimics a **learning switch** by:
- Dynamically learning MAC addresses from incoming packets
- Installing OpenFlow flow rules for known MAC-to-port mappings
- Forwarding packets to the correct port (or flooding for unknown destinations)
- Demonstrating the entire lifecycle via Mininet simulation

---

## Topology

```
  h1 (10.0.0.1 / 00:00:00:00:00:01)
       |  (100 Mbps, 1 ms)
       |
      s1  (OVSKernelSwitch, OpenFlow 1.3)  <---> Ryu Controller (127.0.0.1:6633)
       |
       |  (100 Mbps, 1 ms)
  h2 (10.0.0.2 / 00:00:00:00:00:02)
       |
  h3 (10.0.0.3 / 00:00:00:00:00:03)
```

3 hosts connected to a single OpenFlow switch managed by a remote Ryu controller.

---

## Prerequisites

```bash
# Ubuntu 20.04/22.04
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip wireshark tcpdump iperf

# Install Ryu SDN framework
pip3 install ryu

# Verify installations
mn --version
ryu-manager --version
ovs-vsctl show
```

---

## Project Structure

```
sdn_learning_switch/
├── controller/
│   └── learning_switch.py     # Ryu controller (learning switch logic)
├── topology/
│   └── topology.py            # Mininet topology + automated test scenarios
├── tests/
│   └── run_tests.py           # Manual test helper / validation script
└── README.md
```

---

## Setup & Execution

### Step 1 — Start the Ryu Controller

Open **Terminal 1**:

```bash
cd sdn_learning_switch/
ryu-manager --verbose controller/learning_switch.py
```

You should see:
```
loading app controller/learning_switch.py
SDN Learning Switch Controller  -  Starting up
...
```

---

### Step 2 — Start Mininet Topology

Open **Terminal 2**:

```bash
cd sdn_learning_switch/
sudo python3 topology/topology.py
```

The script will:
1. Create the 3-host, 1-switch topology
2. Connect the switch to your Ryu controller
3. Run automated test Scenarios 1–5
4. Drop you into the Mininet CLI for manual testing

---

### Step 3 — Manual Testing in the Mininet CLI

```bash
# Test all-pairs ping
mininet> pingall

# Ping specific host
mininet> h1 ping -c 4 h2

# iperf throughput test
mininet> h2 iperf -s &
mininet> h1 iperf -c 10.0.0.2 -t 10

# Inspect flow table on the switch
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1

# Inspect port statistics
mininet> sh ovs-ofctl -O OpenFlow13 dump-ports s1

# Capture packets on h1's link
mininet> sh tcpdump -i s1-eth1 -n -c 20 &
mininet> h1 ping -c 5 h2

# Exit
mininet> exit
```

---

## Controller Logic — How It Works

| Step | Event | Action |
|------|-------|--------|
| 1 | Switch connects | Install **table-miss** flow (priority=0): send all unmatched packets to controller |
| 2 | `packet_in` received | Extract Ethernet frame |
| 3 | MAC learning | Record `src_mac → in_port` in MAC table |
| 4 | Destination known? | **YES** → Install unicast flow rule (priority=10, idle_timeout=30s) |
| 5 | Destination unknown? | **NO** → Flood out all ports (OFPP_FLOOD) |
| 6 | Flow rule hit | Future packets forwarded by switch hardware, no controller involvement |
| 7 | Flow removed | Controller logs packet/byte counts |

### Flow Rule Match-Action Design

```
Table-miss rule (installed on switch connect):
  match:   * (everything)
  action:  OUTPUT → CONTROLLER
  priority: 0

Learned unicast rule (installed after MAC learning):
  match:   in_port=X, eth_src=AA:BB:CC:DD:EE:FF, eth_dst=11:22:33:44:55:66
  action:  OUTPUT → port Y
  priority: 10
  idle_timeout: 30s
  hard_timeout: 120s
```

---

## Test Scenarios

### Scenario 1 — Basic Connectivity (pingAll)

```bash
mininet> pingall
```

**Expected output:**
```
*** Ping: testing ping reachability
h1 -> h2 h3
h2 -> h1 h3
h3 -> h1 h2
*** Results: 0% dropped (6/6 received)
```

**What happens:**
- First ping triggers ARP → packet_in → controller floods → learns MAC
- Subsequent pings → unicast flow rule hit → forwarded at line rate

---

### Scenario 2 — Flow Table Inspection (Before vs After)

**Before any traffic:**
```bash
ovs-ofctl -O OpenFlow13 dump-flows s1
# Output: only 1 table-miss rule (priority=0)
```

**After pingAll:**
```bash
ovs-ofctl -O OpenFlow13 dump-flows s1
# Output: table-miss rule + multiple unicast rules (priority=10)
# Each unicast rule shows packet_count increasing
```

---

### Scenario 3 — iperf Throughput Measurement

```bash
mininet> h2 iperf -s &
mininet> h1 iperf -c 10.0.0.2 -t 10
```

**Expected:**
```
[  3]  0.0-10.0 sec  ~110 MBytes  ~90 Mbits/sec
```

Validates that the installed flow rule handles bulk TCP traffic efficiently.

---

### Scenario 4 — Wireshark / tcpdump Packet Capture

```bash
# Capture on the h1 <-> s1 link
sudo tcpdump -i s1-eth1 -n icmp
mininet> h1 ping -c 5 h2
```

**Expected observation:**
- **Packet 1**: ARP request broadcast (controller floods) → packet_in event visible in Ryu logs
- **Packet 2+**: ICMP echo requests forwarded directly (flow rule in switch) → no packet_in

---

### Scenario 5 — Normal vs First-Packet Latency

```bash
# First ping (table miss, packet_in, flow install)
mininet> h1 ping -c 1 h2

# Subsequent pings (flow rule hit, no controller)
mininet> h1 ping -c 5 h2
```

**Expected:**
- First ping RTT slightly higher (~few ms) due to controller round-trip
- Subsequent pings lower and stable (~2 ms at 1 ms link delay × 2)

---

## Expected Ryu Controller Log Output

```
[DPID 0000000000000001] Switch connected. Installing table-miss flow.
[DPID 0000000000000001] LEARN  src=00:00:00:00:00:01  port=1
[DPID 0000000000000001] FLOOD  dst=ff:ff:ff:ff:ff:ff unknown
[DPID 0000000000000001] LEARN  src=00:00:00:00:00:02  port=2
[DPID 0000000000000001] FORWARD dst=00:00:00:00:00:01 -> port=1 (learned)
[DPID 0000000000000001] Flow installed: OFPMatch(...) -> [OFPActionOutput(port=1)]
```

---

## Performance Metrics Summary

| Metric | Expected Value | Tool |
|--------|---------------|------|
| ping RTT (h1 → h2) | ~2–4 ms | `ping` |
| Packet loss | 0% | `pingall` |
| iperf throughput (h1→h2) | ~90 Mbps | `iperf` |
| Flow rules after pingAll | ≥ 6 unicast + 1 table-miss | `ovs-ofctl dump-flows` |
| First packet latency | slightly higher than steady-state | `ping -c 1` |

