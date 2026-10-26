from mininet.topo import Topo
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
        self.addLink(s1, s2)
        self.addLink(s1, s3) 
        self.addLink(s2, s4)
        self.addLink(s3, s4) 
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

if __name__ == '__main__':
    run()
