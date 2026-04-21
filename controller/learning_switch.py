"""
SDN Learning Switch Controller - Ryu Implementation
=====================================================
Implements a Layer-2 learning switch that:
  - Learns MAC addresses from incoming packets (packet_in events)
  - Installs OpenFlow flow rules for known destinations
  - Falls back to flooding for unknown destinations
  - Supports flow table inspection and statistics
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, icmp, tcp, udp
from ryu.lib import mac as mac_lib
import logging
import time


class LearningSwitch(app_manager.RyuApp):
    """
    Ryu Learning Switch Controller (OpenFlow 1.3)

    Behaviour:
    - On connection: installs a table-miss flow (send unknown packets to controller)
    - On packet_in: learns src MAC -> port mapping
    - If dst MAC is known: installs a unicast flow rule and forwards
    - If dst MAC is unknown: floods out all ports except ingress
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # Flow rule priorities
    PRIORITY_TABLE_MISS = 0       # lowest – catches everything not matched above
    PRIORITY_LEARNED    = 10      # unicast flows installed after learning

    # Flow idle/hard timeouts (seconds)
    IDLE_TIMEOUT = 30
    HARD_TIMEOUT = 120

    def __init__(self, *args, **kwargs):
        super(LearningSwitch, self).__init__(*args, **kwargs)

        # mac_to_port[dpid][mac] = port_no
        self.mac_to_port = {}

        # Simple per-switch packet/byte counters for reporting
        self.stats = {}

        self.logger.setLevel(logging.INFO)
        self.logger.info("=" * 60)
        self.logger.info("  SDN Learning Switch Controller  -  Starting up")
        self.logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Helper: send an OpenFlow message to a datapath
    # ------------------------------------------------------------------
    def _send_msg(self, datapath, msg):
        datapath.send_msg(msg)

    # ------------------------------------------------------------------
    # Helper: install a flow rule on the switch
    # ------------------------------------------------------------------
    def add_flow(self, datapath, priority, match, actions,
                 idle_timeout=0, hard_timeout=0, buffer_id=None):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        kwargs = dict(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )
        if buffer_id is not None:
            kwargs["buffer_id"] = buffer_id

        mod = parser.OFPFlowMod(**kwargs)
        datapath.send_msg(mod)
        self.logger.debug("[DPID %016x] Flow installed: %s -> %s",
                          datapath.id, match, actions)

    # ------------------------------------------------------------------
    # Event: switch connects – install table-miss flow
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser

        self.mac_to_port.setdefault(datapath.id, {})
        self.stats[datapath.id] = {"packet_in": 0, "flow_installed": 0}

        self.logger.info("[DPID %016x] Switch connected. Installing table-miss flow.",
                         datapath.id)

        # Table-miss: match everything, send to controller, no timeout
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, self.PRIORITY_TABLE_MISS, match, actions)

    # ------------------------------------------------------------------
    # Event: packet_in  (main learning + forwarding logic)
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        dpid     = datapath.id
        in_port  = msg.match["in_port"]

        # Parse the Ethernet frame
        pkt  = packet.Packet(msg.data)
        eth  = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return  # Not an Ethernet frame – ignore

        dst_mac = eth.dst
        src_mac = eth.src

        # Ignore LLDP (link-layer discovery) packets
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        self.stats[dpid]["packet_in"] += 1

        # ---- 1. LEARN: record src MAC -> in_port mapping ----
        if src_mac not in self.mac_to_port[dpid]:
            self.logger.info("[DPID %016x] LEARN  src=%s  port=%d",
                             dpid, src_mac, in_port)
        self.mac_to_port[dpid][src_mac] = in_port

        # ---- 2. DECIDE: known destination? ----
        if dst_mac in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst_mac]
            self.logger.info("[DPID %016x] FORWARD dst=%s -> port=%d (learned)",
                             dpid, dst_mac, out_port)
        else:
            out_port = ofproto.OFPP_FLOOD
            self.logger.info("[DPID %016x] FLOOD  dst=%s unknown",
                             dpid, dst_mac)

        actions = [parser.OFPActionOutput(out_port)]

        # ---- 3. INSTALL FLOW RULE for known unicast destinations ----
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst_mac,
                                    eth_src=src_mac)

            # If the packet is still buffered on the switch, include buffer_id
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, self.PRIORITY_LEARNED, match, actions,
                              idle_timeout=self.IDLE_TIMEOUT,
                              hard_timeout=self.HARD_TIMEOUT,
                              buffer_id=msg.buffer_id)
                self.stats[dpid]["flow_installed"] += 1
                return   # Switch will forward the buffered packet itself
            else:
                self.add_flow(datapath, self.PRIORITY_LEARNED, match, actions,
                              idle_timeout=self.IDLE_TIMEOUT,
                              hard_timeout=self.HARD_TIMEOUT)
                self.stats[dpid]["flow_installed"] += 1

        # ---- 4. FORWARD current packet ----
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data  # packet not buffered on switch – send it ourselves

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)

        # ---- 5. Log packet details for validation ----
        self._log_packet_info(pkt, dpid, in_port, out_port)

    # ------------------------------------------------------------------
    # Helper: pretty-print packet details
    # ------------------------------------------------------------------
    def _log_packet_info(self, pkt, dpid, in_port, out_port):
        eth = pkt.get_protocol(ethernet.ethernet)
        ip4 = pkt.get_protocol(ipv4.ipv4)

        if ip4:
            proto_name = {1: "ICMP", 6: "TCP", 17: "UDP"}.get(ip4.proto, str(ip4.proto))
            self.logger.info(
                "[DPID %016x]   ETH %s -> %s | IP %s -> %s | %s | in_port=%d out_port=%s",
                dpid, eth.src, eth.dst,
                ip4.src, ip4.dst, proto_name,
                in_port, out_port if isinstance(out_port, int) else "FLOOD"
            )

    # ------------------------------------------------------------------
    # Event: flow removed (for logging)
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        msg  = ev.msg
        dpid = msg.datapath.id
        self.logger.info(
            "[DPID %016x] Flow REMOVED: match=%s  reason=%s  packets=%d  bytes=%d",
            dpid, msg.match, msg.reason, msg.packet_count, msg.byte_count
        )

    # ------------------------------------------------------------------
    # Utility: dump the current MAC table (call from REST or manually)
    # ------------------------------------------------------------------
    def dump_mac_table(self):
        self.logger.info("===== MAC Address Table =====")
        for dpid, table in self.mac_to_port.items():
            self.logger.info("Switch DPID: %016x", dpid)
            for mac, port in table.items():
                self.logger.info("  %-20s  ->  port %d", mac, port)
        self.logger.info("=============================")

    # ------------------------------------------------------------------
    # Utility: dump controller stats
    # ------------------------------------------------------------------
    def dump_stats(self):
        self.logger.info("===== Controller Stats =====")
        for dpid, s in self.stats.items():
            self.logger.info("Switch %016x | packet_in=%d | flows_installed=%d",
                             dpid, s["packet_in"], s["flow_installed"])
        self.logger.info("============================")
