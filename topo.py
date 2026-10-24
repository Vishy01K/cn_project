from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink # Import TCLink to simulate delays later in D2

class DiamondTopo(Topo):
    def build(self):
        # Add switches
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        s4 = self.addSwitch('s4')
        
        # Add hosts
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        
        # Add links (Creating the Diamond shape)
        self.addLink(h1, s1)
        self.addLink(s1, s2) # Top path
        self.addLink(s1, s3) # Bottom path
        self.addLink(s2, s4) # Top path
        self.addLink(s3, s4) # Bottom path
        self.addLink(s4, h2)

def run():
    setLogLevel('info')
    # Connect to Ryu controller
    c0 = RemoteController('c0', ip='127.0.0.1', port=6633)
    
    # Use TCLink so we can add artificial delays in D2
        # Update this line in your topo.py
    net = Mininet(topo=DiamondTopo(), controller=c0, switch=OVSKernelSwitch, link=TCLink, autoSetMacs=True)
    net.start()
    
    print("Diamond Topology Started. Type 'exit' to stop.")
    CLI(net)
    net.stop()

if __name__ == '__main__':
    run()