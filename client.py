import socket                                                                                          # Probe Sender,Send Packets and With TimeStamp,Uses Reply Data to Calculate RTT and Packet Loss                                                              
import time

def start_client(server_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0) #  timeout forthe packet loss detection
    
    server_address = (server_ip, 5005)
    total_packets = 10
    lost_packets = 0
    
    print(f"Starting Diagnostic Tool targeting {server_ip}...")
    print("-" * 50)

    for i in range(1, total_packets + 1):
        send_time = time.time()
        message = f"{i}:{send_time}"
        
        try:

            sock.sendto(message.encode('utf-8'), server_address)              #<----Send UDP probe
            
            #reply
            data, server = sock.recvfrom(1024)
            receive_time = time.time()
            
            # calculating the RTT
            rtt = (receive_time - send_time) * 1000 
            print(f"Packet {i}: Success | RTT: {rtt:.4f} ms")
            
        except socket.timeout:
            lost_packets += 1
            print(f"Packet {i}: LOST (Timeout)")
            
    print("-" * 50)
    print(f"Summary: Sent {total_packets}, Lost {lost_packets}, Loss Rate: {(lost_packets/total_packets)*100}%")
    sock.close()

# =============================
# D1 ABOVE D2 STARTS FROM HERE
# =============================
import sys
import json
import csv
import os
import statistics
import urllib.request
 
CONTROLLER_URL = 'http://127.0.0.1:8080'      # Ryu REST API of d2_controller.py
LOSS_PENALTY_MS = 10.0                        # same scoring as the controller
 
 
def api(method, path, body=None, base=None, timeout=3.0):
    """Tiny REST helper (stdlib only)."""
    url = (base or CONTROLLER_URL) + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))
 
 
def _probe_once(sock, server_ip, seq, timeout, port=5005):
    """Send one probe, return RTT in ms or None. Replies whose sequence number does not
    match (late replies of earlier, already-lost probes) are discarded."""
    t0 = time.perf_counter()
    try:
        sock.sendto(f"{seq}:{time.time()}".encode('utf-8'), (server_ip, port))
    except OSError:
        return None
    deadline = t0 + timeout
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return None
        sock.settimeout(remaining)
        try:
            data, _ = sock.recvfrom(1024)
        except socket.timeout:
            return None
        except OSError:                       # e.g.  error -> icmp port unreachable
            return None
        try:
            tag, rseq, _ = data.decode('utf-8').split(':', 2)
            if tag == 'ACK' and int(rseq) == seq:
                return (time.perf_counter() - t0) * 1000.0
        except ValueError:
            pass                          
 
def summarize(rtts, sent):
    n = len(rtts)
    jitter = (sum(abs(b - a) for a, b in zip(rtts, rtts[1:])) / (n - 1)) if n > 1 else 0.0
    return {'sent': sent, 'received': n,
            'loss_pct': round(100.0 * (sent - n) / sent, 2) if sent else 100.0,
            'min': round(min(rtts), 3) if rtts else None,
            'avg': round(sum(rtts) / n, 3) if rtts else None,
            'max': round(max(rtts), 3) if rtts else None,
            'stdev': round(statistics.pstdev(rtts), 3) if n > 1 else 0.0,
            'jitter': round(jitter, 3)}
 
 
def probe_path(server_ip, count=20, interval=0.05, timeout=1.0, port=5005):
    """Probe whatever path is currently active; return RTT / loss / jitter statistics."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtts = []
    try:
        for seq in range(1, count + 1):
            rtt = _probe_once(sock, server_ip, seq, timeout, port)
            if rtt is not None:
                rtts.append(rtt)
            time.sleep(interval)
    finally:
        sock.close()
    return summarize(rtts, count)
 
 
def monitor_probes(server_ip, duration=20.0, interval=0.1, timeout=0.5, port=5005):
    """Continuous probing. Returns [{'t': send_epoch, 'seq': n, 'rtt': ms|None}, ...]."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    samples, seq, end = [], 0, time.time() + duration
    try:
        while time.time() < end:
            seq += 1
            t = time.time()
            samples.append({'t': t, 'seq': seq, 'rtt': _probe_once(sock, server_ip, seq, timeout, port)})
            time.sleep(interval)
    finally:
        sock.close()
    return samples
 
 
def classify(path, st):
    """Correlate the end-to-end measurement with the controller's view of the path."""
    ctrl_down = path['status'] == 'down'
    if ctrl_down and st['loss_pct'] >= 100:
        return 'FAILED (link down: %s)' % ','.join(path['down_links'])
    if ctrl_down:
        return 'INCONSISTENT (controller says down, data plane reachable)'
    if st['loss_pct'] >= 100:
        return 'BLACKHOLE (controller says up, 100% loss)'
    if st['loss_pct'] > 0:
        return 'DEGRADED (%.1f%% loss)' % st['loss_pct']
    return 'HEALTHY'
 
 
def _score(st):
    if st['received'] == 0:
        return float('inf')
    return st['avg'] + LOSS_PENALTY_MS * st['loss_pct']
 
 
def _fmt(v):
    return '-' if v is None else ('%.2f' % v)
 
 
def run_d2_survey(server_ip='10.0.0.2', count=20, interval=0.05, timeout=1.0,
                  label='run', csv_path='d2_results.csv', base=None, probe_fn=None):
    """Force each controller path in turn, measure it, classify it, compare them, then hand
    control back to the controller in adaptive mode with the measurements reported."""
    if probe_fn is None:
        probe_fn = lambda c, i, t: probe_path(server_ip, c, i, t)
 
    topo = api('GET', '/d2/topology', base=base)
    print('\n=== D2 survey [%s] ===' % label)
    print('Discovered topology: switches=%s' % ','.join(topo['switches']))
    for l in topo['links']:
        print('  link %s:%s <-> %s:%s  [%s]' % (l['a'], l['a_port'], l['b'], l['b_port'], l['status']))
    for h in topo['hosts']:
        print('  host %s (%s) at %s:%s' % (h['ip'], h['mac'], h['switch'], h['port']))
 
    paths = api('GET', '/d2/paths', base=base)['paths']
    if not paths:
        print('No host-to-host path known yet: generate traffic first (e.g. pingall).')
        return []
 
    rows = []
    for p in paths:
        api('POST', '/d2/select', {'path_id': p['id']}, base=base)
        time.sleep(0.5)                                  # flows settle
        st = probe_fn(count, interval, timeout)
        verdict = classify(p, st)
        api('POST', '/d2/report', {'path_key': p['key'],
                                   'avg_rtt_ms': st['avg'] or 0.0,
                                   'loss_pct': st['loss_pct']}, base=base)
        rows.append((p, st, verdict))
 
    usable = [r for r in rows if r[1]['received'] > 0]
    best = min(usable, key=lambda r: _score(r[1])) if usable else None
 
    print('\n%-3s %-14s %-6s %7s %8s %8s %8s %8s  %-9s %s' %
          ('id', 'path', 'ctrl', 'loss%', 'min', 'avg', 'max', 'jitter', 'vs best', 'verdict'))
    for p, st, verdict in rows:
        if best and st['received'] > 0:
            d = st['avg'] - best[1]['avg']
            vs = 'BEST' if p['id'] == best[0]['id'] else '+%.1fms' % d
        else:
            vs = '-'
        print('%-3d %-14s %-6s %7.1f %8s %8s %8s %8s  %-9s %s' %
              (p['id'], p['key'], p['status'], st['loss_pct'], _fmt(st['min']), _fmt(st['avg']),
               _fmt(st['max']), _fmt(st['jitter']), vs, verdict))
 
    if best:
        print('\nBest path: %s (avg RTT %.2f ms, loss %.1f%%)' %
              (best[0]['key'], best[1]['avg'], best[1]['loss_pct']))
    else:
        print('\nNo usable path: every path failed.')
    failed = [r[0]['key'] for r in rows if r[2].startswith(('FAILED', 'BLACKHOLE'))]
    if failed:
        print('Failed paths: %s' % ', '.join(failed))
 
    api('POST', '/d2/select', {'mode': 'adaptive'}, base=base)     
    time.sleep(0.3)
    print('Controller now routes via: %s (adaptive)' % api('GET', '/d2/topology', base=base)['active_path'])
 
    new_file = not os.path.exists(csv_path)
    with open(csv_path, 'a', newline='') as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(['timestamp', 'label', 'path_id', 'path', 'controller_status', 'verdict', 'sent',
                        'received', 'loss_pct', 'min_ms', 'avg_ms', 'max_ms', 'jitter_ms', 'stdev_ms'])
        for p, st, verdict in rows:
            w.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), label, p['id'], p['key'], p['status'],
                        verdict.split(' ')[0], st['sent'], st['received'], st['loss_pct'], st['min'],
                        st['avg'], st['max'], st['jitter'], st['stdev']])
    print('Results appended to %s' % csv_path)
    return rows
 
 
def analyse_failover(samples, events, label='failover', inject_t=None, csv_path='d2_failover.csv'):
    """Correlate outages seen by the probes with the controller's link-down / failover events."""
    outages, start, lost = [], None, 0
    for s in samples:
        if s['rtt'] is None:
            if start is None:
                start, lost = s['t'], 0
            lost += 1
        elif start is not None:
            outages.append((start, s['t'] + s['rtt'] / 1000.0, lost))
            start = None
    if start is not None:
        outages.append((start, None, lost))
 
    total = len(samples)
    nlost = sum(1 for s in samples if s['rtt'] is None)
    print('\n=== D2 failover analysis [%s] ===' % label)
    print('probes sent: %d, lost: %d (%.1f%%)' % (total, nlost, 100.0 * nlost / total if total else 0))
    if not outages:
        print('No outage observed.')
    new_file = not os.path.exists(csv_path)
    with open(csv_path, 'a', newline='') as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(['timestamp', 'label', 'lost_probes', 'outage_ms', 'inject_to_ctrl_detect_ms',
                        'ctrl_detect_to_failover_ms'])
        for (a, b, n) in outages:
            down = next((e for e in events if e['event'].startswith('link DOWN') and e['t'] >= a - 2.0), None)
            fo = next((e for e in events if 'FAILOVER' in e['event'] and down and e['t'] >= down['t']), None)
            dur = (b - a) * 1000.0 if b else None
            det = (down['t'] - inject_t) * 1000.0 if (down and inject_t) else None
            react = (fo['t'] - down['t']) * 1000.0 if (down and fo) else None
            print('outage: %d probes lost, traffic interrupted for %s ms' %
                  (n, '%.0f' % dur if dur is not None else 'unresolved (still down)'))
            if down:
                print('  controller saw: %s' % down['event'])
            if det is not None:
                print('  failure injected -> controller detected: %.0f ms' % det)
            if fo:
                print('  controller reaction: %s (%.0f ms after detection)' % (fo['event'], react))
            w.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), label, n,
                        '' if dur is None else round(dur), '' if det is None else round(det),
                        '' if react is None else round(react)])
    print('Failover data appended to %s' % csv_path)
 
 
def d2_main():
    import argparse
    ap = argparse.ArgumentParser(description='D2 path-aware diagnostic tool')
    ap.add_argument('server_ip', nargs='?', default='10.0.0.2')
    ap.add_argument('--d2', choices=['probe', 'monitor', 'survey'], required=True,
                    help='probe: JSON stats of the active path | monitor: JSON samples | '
                         'survey: all paths (needs the controller REST API to be reachable)')
    ap.add_argument('--count', type=int, default=20)
    ap.add_argument('--interval', type=float, default=0.05)
    ap.add_argument('--timeout', type=float, default=1.0)
    ap.add_argument('--duration', type=float, default=20.0)
    ap.add_argument('--label', default='run')
    ap.add_argument('--controller', default=CONTROLLER_URL)
    ap.add_argument('--csv', default='d2_results.csv')
    a = ap.parse_args()
    if a.d2 == 'probe':
        print(json.dumps(probe_path(a.server_ip, a.count, a.interval, a.timeout)))
    elif a.d2 == 'monitor':
        print(json.dumps(monitor_probes(a.server_ip, a.duration, a.interval, a.timeout)))
    else:
        run_d2_survey(a.server_ip, a.count, a.interval, a.timeout, a.label, a.csv, a.controller)
 
 
if __name__ == "__main__":
    if '--d2' in sys.argv:
        d2_main()
        sys.exit(0)
  
    import sys
    target_ip = sys.argv[1] if len(sys.argv) > 1 else '10.0.0.2'
    start_client(target_ip)
