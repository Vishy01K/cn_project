# ============================================================================
# D2 - Ryu SDN controller for the Network Diagnostic and Path Analysis Tool
#
# Run:  ryu-manager --observe-links --ofp-tcp-listen-port 6633 d2_controller.py
#       (REST API on http://127.0.0.1:8080, the port ryu's WSGI uses by default)
#
# What it does
#   1. Topology discovery   : switches/links via ryu.topology (LLDP), hosts via packet-in
#   2. Path computation     : enumerates every simple switch path between the two hosts
#   3. Path installation    : proactive per-path flows (no flooding in the diamond loop)
#   4. Dynamic behaviour    : link down/up events -> path status + automatic failover
#   5. Closed loop          : diagnostic tool POSTs measured RTT/loss per path, the
#                             controller (mode "adaptive") moves traffic to the best path
#   6. REST API             : /d2/topology /d2/paths /d2/select /d2/report /d2/events
# ============================================================================
import json

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4, ether_types
from ryu.topology import event
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from webob import Response

APP_NAME = 'd2_controller_app'
LOSS_PENALTY_MS = 10.0      # adaptive score = avg_rtt_ms + LOSS_PENALTY_MS * loss_pct
UNMEASURED_SCORE = 1e6      # alive but never measured -> tried after measured paths


class D2Controller(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(D2Controller, self).__init__(*args, **kwargs)
        self.datapaths = {}            # dpid -> datapath
        self.links_all = {}            # (a, b) -> (port_on_a, port_on_b); never removed
        self.links_alive = set()       # directed (a, b) currently up
        self.isl_ports = {}            # dpid -> set(ports that face another switch)
        self.hosts = {}                # mac -> {'dpid','port','ip'}  (insertion ordered)
        self.mode = 'auto'             # auto | manual | adaptive
        self.manual_key = None         # path key used in manual mode
        self.active_key = None         # path key currently installed
        self.metrics = {}              # path key -> {'avg_rtt_ms','loss_pct','ts'}
        self.event_log = []               # human-readable event log (for demo/report)
        self.seq = 0
        wsgi = kwargs['wsgi']
        wsgi.register(D2Rest, {APP_NAME: self})

    # ------------------------------------------------------------------ utils
    def log_event(self, text):
        self.seq += 1
        self.event_log.append({'n': self.seq, 't': round(__import__('time').time(), 3), 'event': text})
        self.event_log = self.event_log[-200:]
        self.logger.info('D2 | %s', text)

    @staticmethod
    def pkey(path):
        return '-'.join('s%d' % d for d in path)

    # ------------------------------------------------------- switch handshake
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.datapaths[dp.id] = dp
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)          # table-miss -> controller
        self.log_event('switch s%d connected' % dp.id)

    def add_flow(self, dp, priority, match, actions):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority,
                                      match=match, instructions=inst))

    def del_flows_for_mac(self, dp, mac):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE,
                                      out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                                      match=parser.OFPMatch(eth_dst=mac)))

    def packet_out(self, dp, in_port, out_ports, data):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        actions = [parser.OFPActionOutput(p) for p in out_ports]
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER,
                                        in_port=in_port, actions=actions, data=data))

    # ------------------------------------------------- topology discovery (D2)
    @set_ev_cls(event.EventLinkAdd)
    def link_add(self, ev):
        l = ev.link
        a, b = l.src.dpid, l.dst.dpid
        self.links_all[(a, b)] = (l.src.port_no, l.dst.port_no)
        self.links_alive.add((a, b))
        self.isl_ports.setdefault(a, set()).add(l.src.port_no)
        self.isl_ports.setdefault(b, set()).add(l.dst.port_no)
        self.log_event('link UP   s%d:%d -> s%d:%d' % (a, l.src.port_no, b, l.dst.port_no))
        self.reconcile()

    @set_ev_cls(event.EventLinkDelete)
    def link_delete(self, ev):
        l = ev.link
        a, b = l.src.dpid, l.dst.dpid
        self.links_alive.discard((a, b))
        self.log_event('link DOWN s%d:%d -> s%d:%d' % (a, l.src.port_no, b, l.dst.port_no))
        # old measurements of any path that used this link are no longer valid
        for p in self.all_paths():
            if (a, b) in zip(p, p[1:]) or (b, a) in zip(p, p[1:]):
                self.metrics.pop(self.pkey(p), None)
        self.reconcile()

    def discovery_ready(self):
        return bool(self.datapaths) and all(self.isl_ports.get(d) for d in self.datapaths)

    # ------------------------------------------------------- path computation
    def host_pair(self):
        h = list(self.hosts.items())
        if len(h) < 2:
            return None
        return h[0], h[1]

    def all_paths(self):
        """All simple switch paths between the two host switches over every link
        ever discovered (alive or not) -> stable ids, so a failed path stays listed."""
        pair = self.host_pair()
        if not pair:
            return []
        src, dst = pair[0][1]['dpid'], pair[1][1]['dpid']
        if src == dst:
            return [[src]]
        adj = {}
        for (a, b) in self.links_all:
            adj.setdefault(a, set()).add(b)
        found = []

        def dfs(node, path):
            if node == dst:
                found.append(list(path))
                return
            for nxt in sorted(adj.get(node, ())):
                if nxt not in path:
                    path.append(nxt)
                    dfs(nxt, path)
                    path.pop()
        dfs(src, [src])
        found.sort(key=lambda p: (len(p), p))
        return found

    def path_down_links(self, path):
        down = []
        for a, b in zip(path, path[1:]):
            if (a, b) not in self.links_alive or (b, a) not in self.links_alive:
                down.append('s%d-s%d' % (a, b))
        return down

    def path_alive(self, path):
        return not self.path_down_links(path)

    def score(self, path):
        m = self.metrics.get(self.pkey(path))
        if m is None:
            return UNMEASURED_SCORE
        if m['loss_pct'] >= 100:
            return float('inf')
        return m['avg_rtt_ms'] + LOSS_PENALTY_MS * m['loss_pct']

    def choose_path(self):
        paths = self.all_paths()
        if not paths:
            return None
        if self.mode == 'manual':               # forced, even if down (lets the tool
            for p in paths:                     # observe a failed path end-to-end)
                if self.pkey(p) == self.manual_key:
                    return p
        alive = [p for p in paths if self.path_alive(p)]
        if not alive:
            return None
        if self.mode == 'adaptive':
            return min(alive, key=lambda p: (self.score(p), len(p), p))
        return alive[0]                          # auto: shortest alive path

    # --------------------------------------------------------- flow installation
    def reconcile(self, force=False):
        pair = self.host_pair()
        if not pair:
            return
        path = self.choose_path()
        if path is None:
            if self.active_key is not None:
                self.log_event('NO alive path between hosts')
            self.active_key = None
            return
        key = self.pkey(path)
        if key == self.active_key and not force:
            return
        old = self.active_key
        self.install_path(path)
        self.active_key = key
        if old and old != key:
            self.log_event('FAILOVER/REROUTE %s -> %s (mode=%s)' % (old, key, self.mode))
        else:
            self.log_event('path installed %s (mode=%s)' % (key, self.mode))

    def install_path(self, path):
        (m1, h1), (m2, h2) = self.host_pair()
        for dp in self.datapaths.values():                # clear old state first
            self.del_flows_for_mac(dp, m1)
            self.del_flows_for_mac(dp, m2)
        for dst_mac, hops, dst_host in ((m2, path, h2), (m1, list(reversed(path)), h1)):
            for i, dpid in enumerate(hops):
                dp = self.datapaths.get(dpid)
                if dp is None:
                    continue
                if i == len(hops) - 1:
                    out = dst_host['port']
                else:
                    out = self.links_all[(dpid, hops[i + 1])][0]
                parser = dp.ofproto_parser
                self.add_flow(dp, 10, parser.OFPMatch(eth_dst=dst_mac),
                              [parser.OFPActionOutput(out)])

    # -------------------------------------------------------------- packet-in
    def edge_ports(self, dpid):
        dp = self.datapaths[dpid]
        ports = {p for p in dp.ports if p < dp.ofproto.OFPP_MAX}
        return ports - self.isl_ports.get(dpid, set())

    def flood_edges(self, src_dpid, src_port, data):
        """ARP/broadcast: flood ONLY on host-facing ports -> no loop in the diamond."""
        for dpid, dp in self.datapaths.items():
            ports = [p for p in self.edge_ports(dpid)
                     if not (dpid == src_dpid and p == src_port)]
            if ports:
                self.packet_out(dp, dp.ofproto.OFPP_CONTROLLER, ports, data)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype in (ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_IPV6):
            return
        if not self.discovery_ready():
            return                       # links unknown -> do not risk flooding a loop

        arp_pkt = pkt.get_protocol(arp.arp)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)

        if in_port not in self.isl_ports.get(dp.id, ()) and eth.src not in self.hosts:
            ip = arp_pkt.src_ip if arp_pkt else (ip_pkt.src if ip_pkt else None)
            self.hosts[eth.src] = {'dpid': dp.id, 'port': in_port, 'ip': ip}
            self.log_event('host learned %s ip=%s at s%d:%d' % (eth.src, ip, dp.id, in_port))
            self.reconcile(force=True)

        if arp_pkt is not None:
            self.flood_edges(dp.id, in_port, msg.data)
        elif eth.dst in self.hosts and self.active_key is not None:
            # flows now exist: push this first packet through the table
            self.packet_out(dp, in_port, [dp.ofproto.OFPP_TABLE], msg.data)

    # ------------------------------------------------------------- REST helpers
    def describe_topology(self):
        links = []
        seen = set()
        for (a, b), (pa, pb) in sorted(self.links_all.items()):
            if (b, a) in seen:
                continue
            seen.add((a, b))
            up = (a, b) in self.links_alive and (b, a) in self.links_alive
            links.append({'a': 's%d' % a, 'a_port': pa, 'b': 's%d' % b, 'b_port': pb,
                          'status': 'up' if up else 'down'})
        return {'switches': ['s%d' % d for d in sorted(self.datapaths)],
                'links': links,
                'hosts': [{'mac': m, 'ip': h['ip'], 'switch': 's%d' % h['dpid'], 'port': h['port']}
                          for m, h in self.hosts.items()],
                'mode': self.mode, 'active_path': self.active_key}

    def describe_paths(self):
        out = []
        for i, p in enumerate(self.all_paths()):
            down = self.path_down_links(p)
            key = self.pkey(p)
            out.append({'id': i, 'key': key, 'hops': ['s%d' % d for d in p],
                        'hop_count': len(p),
                        'status': 'down' if down else 'up', 'down_links': down,
                        'active': key == self.active_key,
                        'metrics': self.metrics.get(key)})
        return out


class D2Rest(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(D2Rest, self).__init__(req, link, data, **config)
        self.app = data[APP_NAME]

    @staticmethod
    def _json(obj, status=200):
        return Response(content_type='application/json', status=status,
                        body=json.dumps(obj).encode('utf-8'))

    @route('d2', '/d2/topology', methods=['GET'])
    def topology(self, req, **kw):
        return self._json(self.app.describe_topology())

    @route('d2', '/d2/paths', methods=['GET'])
    def paths(self, req, **kw):
        return self._json({'mode': self.app.mode, 'paths': self.app.describe_paths()})

    @route('d2', '/d2/events', methods=['GET'])
    def events(self, req, **kw):
        return self._json(self.app.event_log)

    @route('d2', '/d2/select', methods=['POST'])
    def select(self, req, **kw):
        """body: {"path_id": 1}  -> manual   |  {"mode": "auto"|"adaptive"}"""
        try:
            body = json.loads(req.body.decode('utf-8') or '{}')
        except ValueError:
            return self._json({'error': 'bad json'}, 400)
        app = self.app
        if 'path_id' in body:
            paths = app.all_paths()
            pid = int(body['path_id'])
            if not 0 <= pid < len(paths):
                return self._json({'error': 'unknown path_id'}, 404)
            app.mode, app.manual_key = 'manual', app.pkey(paths[pid])
        elif body.get('mode') in ('auto', 'adaptive'):
            app.mode = body['mode']
        else:
            return self._json({'error': 'need path_id or mode'}, 400)
        app.log_event('select -> mode=%s manual=%s' % (app.mode, app.manual_key))
        app.reconcile(force=(app.mode == 'manual'))
        return self._json({'mode': app.mode, 'active_path': app.active_key})

    @route('d2', '/d2/report', methods=['POST'])
    def report(self, req, **kw):
        """body: {"path_key": "s1-s2-s4", "avg_rtt_ms": 21.3, "loss_pct": 0}"""
        try:
            b = json.loads(req.body.decode('utf-8'))
            self.app.metrics[b['path_key']] = {
                'avg_rtt_ms': float(b['avg_rtt_ms']), 'loss_pct': float(b['loss_pct']),
                'ts': __import__('time').time()}
        except (ValueError, KeyError, TypeError):
            return self._json({'error': 'bad report'}, 400)
        if self.app.mode == 'adaptive':
            self.app.reconcile()
        return self._json({'ok': True})