# Network Diagnostic and Path Analysis Tool

A Python-based network diagnostic and path-analysis project built using
UDP socket programming, Mininet, Open vSwitch and the Ryu SDN
controller.

The project measures application-level network performance and
demonstrates how an SDN controller can discover network topology, manage
alternative paths, use measured performance metrics and react to network
failures.

## 1. Project Overview

The project uses a Mininet diamond topology to connect a source host
(`h1`) and a destination host (`h2`) through two alternative routes.

The diagnostic client sends UDP probes to the destination server.
Successful acknowledgements are used to calculate round-trip time (RTT),
while missing acknowledgements are detected using timeouts.

The D2 implementation extends the basic diagnostic tool by integrating
the client with a Ryu controller through REST APIs. It retrieves
topology and path information, tests alternative paths, reports
measurements, compares path performance and supports network-degradation
and failover scenarios.

## 2. Objectives

-   Send UDP diagnostic probes between network hosts.
-   Measure round-trip time (RTT) for successful probes.
-   Estimate packet loss using response timeouts.
-   Monitor RTT and packet loss continuously.
-   Build a diamond-shaped Mininet topology with alternative routes.
-   Use Ryu and OpenFlow to manage the software-defined network.
-   Discover switches, links and connected hosts through the controller.
-   Retrieve and test available host-to-host paths.
-   Classify paths as healthy, degraded, failed, inconsistent or
    blackholed using controller status and probe measurements.
-   Compare paths using RTT and packet-loss measurements.
-   Report measurements to the controller and support adaptive path
    selection.
-   Analyse outage and failover timing during network failure scenarios.

## 3. Network Architecture

### Diamond topology

The topology contains two hosts and four switches:

-   Source host: `h1`
-   Destination host: `h2`
-   Switches: `s1`, `s2`, `s3`, `s4`

The two alternative routes are:

``` text
                 s2
               /    \
h1 ---- s1           s4 ---- h2
               \    /
                 s3
```

The paths are:

-   Path 1: `h1 -> s1 -> s2 -> s4 -> h2`
-   Path 2: `h1 -> s1 -> s3 -> s4 -> h2`

The D2 topology configures different link delays for the two branches so
that their measured performance can be compared.

### Communication channels

The project uses two separate communication mechanisms:

  -----------------------------------------------------------------------
  Communication           Protocol                Purpose
  ----------------------- ----------------------- -----------------------
  Diagnostic client to    UDP                     Send probes and receive
  server                                          acknowledgements

  Client to Ryu           HTTP REST               Retrieve topology and
  controller                                      paths, select paths and
                                                  report measurements

  Open vSwitch to Ryu     OpenFlow over TCP       Controller-switch
  controller                                      communication
  -----------------------------------------------------------------------

Important default ports:

-   UDP diagnostic server: `5005`
-   OpenFlow controller: `6633`
-   Ryu REST API: `8080`

## 4. D1 and D2 Features

### D1 --- Basic UDP diagnostics

The D1 client:

1.  Creates an IPv4 UDP socket.
2.  Sends 10 numbered probes to the destination host on UDP port `5005`.
3.  Records the send and receive timestamps.
4.  Calculates RTT for successful responses.
5.  Counts socket timeouts as lost probes.
6.  Displays the total number of probes, lost probes and packet-loss
    percentage.

### D2 --- Path-aware diagnostics

The D2 client adds the following functionality:

-   **Probe validation:** checks that a received response is an ACK with
    the matching sequence number.
-   **RTT statistics:** calculates minimum, average and maximum RTT.
-   **Packet-loss measurement:** calculates the percentage of probes
    without a valid response.
-   **Jitter:** calculates the average absolute difference between
    consecutive successful RTT measurements.
-   **Standard deviation:** calculates the population standard deviation
    of successful RTT measurements.
-   **Continuous monitoring:** records timestamped probe samples,
    including unsuccessful probes.
-   **Topology and path retrieval:** communicates with the Ryu
    controller using REST endpoints.
-   **Path selection:** requests that the controller select a particular
    path for measurement.
-   **Path classification:** identifies healthy, degraded, failed,
    inconsistent and blackhole conditions.
-   **Path comparison:** calculates a score using average RTT and packet
    loss.
-   **Adaptive mode:** returns path selection to the controller's
    adaptive logic after a survey.
-   **CSV output:** stores path-survey and failover-analysis results.

The client path score is:

``` text
Score = Average RTT (ms) + 10.0 × Packet Loss (%)
```

A lower score is preferred. Paths with no successful probe responses are
treated as unusable by the client-side comparison.

The jitter value is the project's average absolute difference between
consecutive successful RTT samples.

## 5. Project Structure

``` text
cn_project/
│
├── client.py
│   ├── D1 UDP diagnostic client
│   ├── D2 probe and monitoring functions
│   ├── RTT, loss, jitter and standard-deviation calculations
│   ├── REST API communication
│   ├── Path survey and comparison
│   └── Failover analysis helper
│
├── server.py
│   └── UDP server that receives probes and sends ACK responses
│
├── topo.py
│   ├── D1 Mininet diamond topology
│   ├── D2 topology and link-delay configuration
│   ├── Link degradation controls
│   ├── D2 survey and monitoring helpers
│   └── Mininet CLI commands for D2 scenarios
│
├── d2_controller.py
│   ├── Ryu SDN controller application
│   ├── Switch and link discovery
│   ├── Host learning and path computation
│   ├── OpenFlow forwarding-rule installation
│   ├── Path selection and adaptive logic
│   └── REST endpoints and event logging
│
├── ryu/
│   └── Ryu-related controller application files
│
├── terminal1_commands/
│   └── Controller startup instructions
│
└── terminal2_commands/
    └── Mininet topology and diagnostic execution instructions
```

The D2 execution can generate:

-   `d2_results.csv` --- path-survey measurements.
-   `d2_failover.csv` --- outage and failover timing analysis.

## 6. Requirements

The project is intended to run on Ubuntu Linux.

Required software:

-   Python 3
-   Mininet
-   Open vSwitch
-   Ryu SDN framework
-   Git

The Python diagnostic client and server use Python standard-library
modules. The network topology and controller require the corresponding
Mininet, Open vSwitch and Ryu environment.

### Install system packages

``` bash
sudo apt update

sudo apt install mininet openvswitch-switch \
python3-venv python3-full python3-pip git -y
```

### Create and activate a Ryu virtual environment

``` bash
python3 -m venv ~/ryu-env
source ~/ryu-env/bin/activate
```

Install the Ryu dependencies:

``` bash
pip install setuptools==69.5.1
pip install ryu
```

Keep the Ryu virtual environment activated in the terminal used to run
the controller.

## 7. Clone the Repository

``` bash
git clone https://github.com/Vishy01K/cn_project.git

cd cn_project
```

Run the commands from the project directory unless the command specifies
another path.

## 8. Running D1 --- Basic UDP Diagnostics

D1 uses the basic Ryu switching application and the original diamond
topology.

### Terminal 1 --- Start the Ryu controller

Activate the Ryu environment:

``` bash
source ~/ryu-env/bin/activate
```

Start the controller:

``` bash
ryu-manager --verbose ryu.app.simple_switch_stp_13
```

Keep this terminal running.

### Terminal 2 --- Start Mininet

Clean up any previous Mininet network:

``` bash
sudo mn -c
```

Start the D1 topology:

``` bash
sudo python3 topo.py
```

At the Mininet prompt, start the UDP server on `h2`:

``` text
mininet> h2 python3 server.py &
```

Run the client from `h1`:

``` text
mininet> h1 python3 client.py 10.0.0.2
```

The destination IP `10.0.0.2` is the example address used for `h2` in
this project. Use the actual destination host IP if the topology
configuration changes.

## 9. Running D2 --- Path-aware Diagnostics

D2 uses the custom Ryu controller and the D2-enabled Mininet topology.

### Terminal 1 --- Start the D2 controller

Activate the Ryu virtual environment:

``` bash
source ~/ryu-env/bin/activate
```

Start the D2 controller with link discovery enabled:

``` bash
ryu-manager --observe-links --ofp-tcp-listen-port 6633 d2_controller.py
```

Keep this terminal running while Mininet is active.

### Terminal 2 --- Start the D2 topology

Move to the repository directory:

``` bash
cd ~/cn_project
```

Clean up any previous Mininet network if required:

``` bash
sudo mn -c
```

Start the D2 topology:

``` bash
sudo python3 topo.py d2
```

The D2 topology starts the UDP server on `h2` automatically. Wait for
the Mininet prompt.

The topology's D2 readiness helper generates traffic to help the
controller learn the hosts and discover available paths before a survey.

### Run a baseline survey

At the Mininet prompt:

``` text
mininet> d2survey baseline
```

This command:

1.  Retrieves the discovered topology and available paths.
2.  Selects each path in turn.
3.  Measures its performance using UDP probes.
4.  Classifies each path.
5.  Reports measurements to the controller.
6.  Compares the usable paths.
7.  Returns the controller to adaptive mode.
8.  Appends results to `d2_results.csv`.

### Simulate packet-loss degradation

Apply 30% packet loss to the `s2-s4` link:

``` text
mininet> d2loss s2 s4 30
```

Run another survey:

``` text
mininet> d2survey degraded
```

Restore the link's packet loss to zero:

``` text
mininet> d2loss s2 s4 0
```

Run a recovery survey:

``` text
mininet> d2survey recovered
```

### Simulate a silent blackhole

Apply 100% packet loss to the `s2-s4` link while the controller still
sees the link as physically up:

``` text
mininet> d2loss s2 s4 100
```

Run the survey:

``` text
mininet> d2survey blackhole
```

Restore the link:

``` text
mininet> d2loss s2 s4 0
```

### Simulate a physical link failure

Bring the `s1-s2` link down:

``` text
mininet> link s1 s2 down
```

Run the survey:

``` text
mininet> d2survey link_down
```

Restore the link:

``` text
mininet> link s1 s2 up
```

Run a recovery survey:

``` text
mininet> d2survey recovered
```

### Run the automated D2 scenarios

The Mininet D2 CLI provides:

``` text
mininet> d2auto
```

This runs the D2 scenario sequence implemented in `topo.py`, including
baseline measurement, degraded-link testing, blackhole testing, link
failure, continuous monitoring, failover analysis and recovery.

The automated scenario records survey data in `d2_results.csv` and
failover-analysis data in `d2_failover.csv`.

### Other D2 Mininet commands

  ----------------------------------------------------------------------------
  Command                                  Purpose
  ---------------------------------------- -----------------------------------
  `d2survey [label]`                       Survey and compare available paths

  `d2loss <switchA> <switchB> <percent>`   Configure packet loss on a link;
                                           use `0` to restore

  `d2monitor [seconds]`                    Run continuous probe monitoring

  `d2auto`                                 Execute the automated D2 scenarios

  `exit`                                   Stop the Mininet CLI and topology
  ----------------------------------------------------------------------------

## 10. D2 Client Command-line Modes

The client also exposes direct D2 command-line modes through `argparse`.
These are useful when running the client from the appropriate Mininet
host environment.

### Probe the currently active path

``` bash
python3 client.py 10.0.0.2 --d2 probe
```

Customise the number of probes:

``` bash
python3 client.py 10.0.0.2 --d2 probe --count 30
```

### Continuously monitor the destination

``` bash
python3 client.py 10.0.0.2 --d2 monitor --duration 20
```

### Run the REST-based path survey

``` bash
python3 client.py 10.0.0.2 --d2 survey
```

The survey mode requires the D2 controller REST API to be reachable. The
Mininet `d2survey` command is the project-provided workflow for
coordinating path selection and probing through the topology.

Available command-line options include:

  Option                             Default Description
  ---------------- ------------------------- ---------------------------------
  `--d2`                            Required `probe`, `monitor` or `survey`
  `--count`                             `20` Number of probes
  `--interval`                        `0.05` Delay between probes in seconds
  `--timeout`                          `1.0` Probe timeout in seconds
  `--duration`                        `20.0` Monitoring duration in seconds
  `--label`                            `run` Survey label
  `--controller`     `http://127.0.0.1:8080` Controller REST base URL
  `--csv`                   `d2_results.csv` Survey output CSV

## 11. REST API Endpoints

The D2 client communicates with the Ryu controller through the following
REST endpoints:

  -----------------------------------------------------------------------
  Method                  Endpoint                Purpose
  ----------------------- ----------------------- -----------------------
  GET                     `/d2/topology`          Retrieve switches,
                                                  links, hosts, mode and
                                                  active path

  GET                     `/d2/paths`             Retrieve available
                                                  paths and their status

  GET                     `/d2/events`            Retrieve controller
                                                  event history

  POST                    `/d2/select`            Select a path or change
                                                  controller mode

  POST                    `/d2/report`            Submit path RTT and
                                                  packet-loss
                                                  measurements
  -----------------------------------------------------------------------

The controller's REST API uses JSON request and response bodies.

## 12. Path Classification

The client combines the controller's path status with measured packet
loss.

  Controller status               Measured packet loss Client classification
  ------------------- -------------------------------- -----------------------
  Down                                            100% FAILED
  Down                                      Below 100% INCONSISTENT
  Up                                              100% BLACKHOLE
  Up                    Greater than 0% and below 100% DEGRADED
  Up                                                0% HEALTHY

A blackhole condition is identified when the controller reports a path
as up but the client receives no valid probe responses.

A physical link-down event and a silent packet-dropping condition are
therefore treated as different situations.

## 13. Results and Output Files

### `d2_results.csv`

Stores path-survey information, including:

-   Timestamp and survey label.
-   Path ID and path key.
-   Controller path status.
-   Verdict.
-   Number of probes sent and received.
-   Packet-loss percentage.
-   Minimum, average and maximum RTT.
-   Jitter.
-   Standard deviation.

### `d2_failover.csv`

Stores outage and failover-analysis information, including:

-   Timestamp and scenario label.
-   Number of lost probes.
-   Estimated outage duration.
-   Failure-injection-to-controller-detection delay.
-   Controller-detection-to-failover reaction delay.

The failover analysis correlates the probe samples with controller
link-down and failover events.

## 14. Troubleshooting

**Controller connection issues**

-   Ensure the Ryu virtual environment is activated.
-   Check that the controller is running before starting Mininet.
-   For D2, use `--observe-links` and OpenFlow port `6633`.
-   Check that the REST API is reachable on port `8080`.

**No paths discovered**

-   Ensure the D2 controller is running.
-   Start the D2 topology.
-   Generate traffic between the hosts using `pingall` if host discovery
    is not complete.
-   Check the controller's topology and path endpoints.

**No UDP responses**

-   Ensure the UDP server is running on `h2`.
-   Verify the destination IP address.
-   Confirm that the client and server use UDP port `5005`.
-   Check the Mininet host and script paths.

**Old Mininet state**

Clean up stale Mininet networks before restarting:

``` bash
sudo mn -c
```

## 15. Notes and Scope

-   RTT and packet-loss measurements are application-level measurements
    based on UDP probes and acknowledgements.
-   A timeout indicates that a valid response was not received before
    the deadline; it does not independently prove whether the outgoing
    probe or returning ACK was lost.
-   The client-side jitter calculation is the average absolute
    difference between consecutive successful RTT samples.
-   Path results depend on the current topology, controller state and
    network conditions.
-   The automated D2 scenario is implemented by the D2 helpers in
    `topo.py`; the direct `client.py --d2` modes are `probe`, `monitor`
    and `survey`.
-   Use the checked-in terminal command files as the reference for the
    repository's environment-specific setup. Replace example directory
    paths with the actual clone location.

## Repository

<https://github.com/Vishy01K/cn_project>
