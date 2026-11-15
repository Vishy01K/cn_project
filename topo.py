from mininet.topo import Topo                                                                                     # Virtual Network, Client and Server Run on this
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink # Import TCLink to simulate delays D1

class DiamondTopo(Topo):
    def build(self):
        #Switches
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        s4 = self.addSwitch('s4')
        
        # Hosts
        h1 = self.addHost('h1') 
        h2 = self.addHost('h2')
         
        # Links
        self.addLink(h1, s1)
        # D2 tweak: per-link delay so the two paths differ (LINK_DELAYS is defined in the D2 section)
        self.addLink(s1, s2, delay=LINK_DELAYS[('s1', 's2')])
        self.addLink(s1, s3, delay=LINK_DELAYS[('s1', 's3')])
        self.addLink(s2, s4, delay=LINK_DELAYS[('s2', 's4')])
        self.addLink(s3, s4, delay=LINK_DELAYS[('s3', 's4')])
        self.addLink(s4, h2)

def run():
    setLogLevel('info')
    # Connect Ryu 
    c0 = RemoteController('c0', ip='127.0.0.1', port=6633)
    
    net = Mininet(topo=DiamondTopo(), controller=c0, switch=OVSKernelSwitch, link=TCLink, autoSetMacs=True)
    net.start()
    
    print("Diamond Topology Started. Type 'exit' to stop.")
    CLI(net)
    net.stop()

# ============================================================================
# D2  -  Scenario automation on top of the D1 topology D2 starts from here
# ============================================================================
import os
import sys
import json
import time

import client                       # D1 client module; D2 section holds the analysis code

LINK_DELAYS = {('s1', 's2'): '5ms', ('s1', 's3'): '20ms',
               ('s2', 's4'): '5ms', ('s3', 's4'): '20ms'}
H2_IP = '10.0.0.2'
HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_PY = os.path.join(HERE, 'client.py')
SERVER_PY = os.path.join(HERE, 'server.py')


def set_link(net, a, b, loss=0):
    """(Re)apply netem on both ends of a link: keeps its delay, sets loss %."""
    key = (a, b) if (a, b) in LINK_DELAYS else (b, a)
    for link in net.linksBetween(net.get(a), net.get(b)):
        for intf in (link.intf1, link.intf2):
            intf.config(delay=LINK_DELAYS[key], loss=loss)


def h1_json(net, cmd):
    """Run client.py on h1 and parse the last JSON line it printed."""
    out = net.get('h1').cmd('python3 %s %s' % (CLIENT_PY, cmd))
    for line in reversed(out.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    raise RuntimeError('no JSON from h1: %r' % out)


def d2_survey(net, label, count=20):
    probe = lambda c, i, t: h1_json(net, '%s --d2 probe --count %d --interval %s --timeout %s' % (H2_IP, c, i, t))
    return client.run_d2_survey(H2_IP, count=count, label=label, probe_fn=probe)


def d2_wait_ready(net, tries=8):
    """Generate ARP traffic and wait until the controller knows both hosts and >=1 path."""
    h1, h2 = net.get('h1', 'h2')
    for _ in range(tries):
        net.ping([h1, h2], timeout='1')
        try:
            if client.api('GET', '/d2/paths')['paths']:
                return True
        except Exception:
            pass
        time.sleep(2)
    print('Controller never reported a path - is d2_controller.py running with --observe-links?')
    return False


def d2_monitor(net, duration, label, inject=None):
    """Probe continuously on h1 while `inject(net)` (optional) breaks/repairs the network."""
    h1 = net.get('h1')
    h1.sendCmd('python3 %s %s --d2 monitor --duration %s --interval 0.1 --timeout 0.5' % (CLIENT_PY, H2_IP, duration))
    inject_t = inject(net) if inject else None
    out = h1.waitOutput()
    samples = json.loads(out.strip().splitlines()[-1])
    events = client.api('GET', '/d2/events')
    client.analyse_failover(samples, events, label=label, inject_t=inject_t)


def d2_auto(net):
    if not d2_wait_ready(net):
        return
    client.api('POST', '/d2/select', {'mode': 'adaptive'})

    print('\n##### Scenario 1: baseline - compare both paths #####')
    d2_survey(net, 'baseline')

    print('\n##### Scenario 2: 20% loss on s2-s4 (degraded path) #####')
    set_link(net, 's2', 's4', loss=20)
    d2_survey(net, 'degraded_s2_s4', count=40)
    set_link(net, 's2', 's4', loss=0)

    print('\n##### Scenario 3: silent blackhole on s2-s4 (controller still sees link up) #####')
    set_link(net, 's2', 's4', loss=100)
    d2_survey(net, 'blackhole_s2_s4')
    set_link(net, 's2', 's4', loss=0)
    time.sleep(3)

    print('\n##### Scenario 4: live link failure s1-s2 and recovery, failover timing #####')
    d2_survey(net, 'pre_failure')                       # adaptive mode

    def break_then_repair(n):
        time.sleep(4)
        t = time.time()
        n.configLinkStatus('s1', 's2', 'down')
        time.sleep(8)
        n.configLinkStatus('s1', 's2', 'up')
        return t
    d2_monitor(net, 18, 'link_failure_s1_s2', inject=break_then_repair)
    time.sleep(6)                                      

    print('\n##### Scenario 5: survey while link s1-s2 is down #####')
    net.configLinkStatus('s1', 's2', 'down')
    time.sleep(3)
    d2_survey(net, 'link_down_s1_s2')
    net.configLinkStatus('s1', 's2', 'up')
    time.sleep(6)

    print('\n##### Scenario 6: recovery #####')
    d2_survey(net, 'recovered')
    print('\nDone. Raw data: d2_results.csv, d2_failover.csv  (plot with: python3 d2_report.py)')


class D2CLI(CLI):
    def do_d2survey(self, line):
        "d2survey [label] - force each path, measure, classify, compare"
        d2_survey(self.mn, line.strip() or 'manual')

    def do_d2loss(self, line):
        "d2loss <sA> <sB> <percent> - set packet loss on a link (0 restores)"
        try:
            a, b, pct = line.split()
            set_link(self.mn, a, b, loss=float(pct))
        except (ValueError, KeyError):
            print('usage: d2loss s2 s4 30')

    def do_d2monitor(self, line):
        "d2monitor [seconds] - continuous probing; break a link in another way meanwhile"
        d2_monitor(self.mn, float(line) if line.strip() else 15, 'cli_monitor')

    def do_d2auto(self, line):
        "d2auto - run all D2 scenarios"
        d2_auto(self.mn)


def run_d2():
    setLogLevel('info')
    c0 = RemoteController('c0', ip='127.0.0.1', port=6633)
    net = Mininet(topo=DiamondTopo(), controller=c0, switch=OVSKernelSwitch,
                  link=TCLink, autoSetMacs=True)
    net.start()
    h2 = net.get('h2')
    pid = h2.cmd('python3 %s > /tmp/d2_server.log 2>&1 & echo $!' % SERVER_PY).strip()
    try:
        if len(sys.argv) > 2 and sys.argv[2] == 'auto':
            d2_auto(net)
        print("D2 ready. Commands: d2survey, d2loss, d2monitor, d2auto  (type 'exit' to stop)")
        D2CLI(net)
    finally:
        h2.cmd('kill %s' % pid)
        net.stop()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'd2':
        run_d2()
    else:
        run()
