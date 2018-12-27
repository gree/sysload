#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import commands
import threading
import time
import re
import array

descriptors = list()
Desc_Skel   = {}
_Worker_Thread = None
_Lock = threading.Lock() # synchronization lock
Debug = False

Uint32_Max = 4294967295
Uint64_Max = 18446744073709551615

USER_HZ = os.sysconf(os.sysconf_names['SC_CLK_TCK'])

# /proc/stat
ProcStatPos = {
    '_user'   : 1,
    '_nice'   : 2,
    '_system' : 3,
    '_idle'   : 4,
    '_wio'    : 5,
    '_intr'   : 6,
    '_sintr'  : 7,
    }

def dprint(f, *v):
    if Debug:
        print >> sys.stderr, 'DEBUG: '+f % v

def parse_list(string):
    l = list()
    if not isinstance(string, str):
        return l

    if string.find(',') >= 0:
        l.extend(string.split(','))
    else:
        l.append(string)

    return l

def find_block_devices():
    devices = list()
    f = None
    try:
        # SCSI, Virtual Disk, CCISS, Fusion IO
        pattern = re.compile('^(x?[svh]d[a-z]|cciss\/c0d0|fio[a-z])$')

        f = open('/proc/diskstats', 'r')
        for l in f:
            elm = l.split(None)
            m = pattern.search(elm[2])
            if m:
                devices.append(m.group(1))
    finally:
        if f:
            f.close()

    return devices

def find_interrupted_cpu(target_device):
    r = commands.getoutput("egrep -c '^processor' /proc/cpuinfo")
    cpu_num = int(r)

    dprint('cpu num: %d', cpu_num)

    f = open('/proc/interrupts', 'r')
    interrupted_cpu = list()

    for l in f:
        if not l.find(target_device) >= 0:
            continue
        if l.find('tx') >= 0:
            continue

        elm = l.split(None)
        elm.pop(0) # irq number

        for i in range(cpu_num):
            a = elm[i]
            if a.isdigit() and int(a) > 0 and interrupted_cpu.count(str(i)) == 0:
                interrupted_cpu.append(str(i))

    dprint('interrupted cpu id: %s', ', '.join(interrupted_cpu))

    if len(interrupted_cpu) == cpu_num: # IRQ is balancing on all CPU.
        return 'ALL'
    else:
        return interrupted_cpu

def counter_wrap(num):
    if num > Uint32_Max: 
        num = Uint32_Max # round
    elif num < 0: # overflow
        if (num + Uint32_Max+1) >= 0: # 32bit
            num += Uint32_Max+1
        elif (num + Uint64_Max+1) >= 0 and (num + Uint64_Max+1) <= Uint32_Max: # 64bit
            num += Uint64_Max+1
        else:
            num = Uint32_Max # round

    return num

class UpdateMetricThread(threading.Thread):

    def __init__(self, params):
        threading.Thread.__init__(self)
        self.running       = False
        self.shuttingdown  = False
        self.refresh_rate  = 15
        if 'refresh_rate' in params:
            self.refresh_rate = int(params['refresh_rate'])

        self.metric = {}

        self.metric_shelter = {}
        self.metric_shelter['time'] = time.time()

        self.array = {}

        self.array['sys_load_one']     = array.array('f', [0.0 for u in range(60/self.refresh_rate)])
        self.array['sys_load_five']    = array.array('f', [0.0 for u in range(300/self.refresh_rate)])
        self.array['sys_load_fifteen'] = array.array('f', [0.0 for u in range(900/self.refresh_rate)])

        self.target_devices       = params['target_devices']

        self.interrupted_cpu_group = {}
        for dev in self.target_devices:
            r = find_interrupted_cpu(dev)
            if isinstance(r, str) or (isinstance(r, list) and len(r) > 0):
                self.interrupted_cpu_group[dev] = r

        self.target_block_devices = params['target_block_devices']
        self.interrupt_threshold  = float(params['interrupt_threshold'])
        self.mp                   = params['metric_prefix']

        self.stats      = {}
        self.stats_prev = {}

    def shutdown(self):
        self.shuttingdown = True
        if not self.running:
            return
        self.join()

    def run(self):
        self.running = True

        while not self.shuttingdown:
            _Lock.acquire()
            try:
              self.update_metric()
            except:
              pass
            _Lock.release()
            time.sleep(self.refresh_rate)

        self.running = False

    def add_jiffies(self, elm, prefix):
        for k, v in ProcStatPos.iteritems():
            l = long(elm[v])
            self.stats[prefix+k]        += l
            self.stats[prefix+'_total'] += l

    def add_all_cpu_jiffies(self, elm):
        self.add_jiffies(elm, 'all_cpu')

    def add_cpu_jiffies(self, elm, dev):
        self.add_jiffies(elm, dev)

    def cpu_stat(self):
        for dev in self.interrupted_cpu_group.iterkeys():
            f = open('/proc/stat', 'r')
            for l in f:
                elm = l.split(None)

                if len(elm) < 2 or elm[1].isdigit() == False:
                    continue
                elif elm[0] == 'ctxt' and self.stats['proc_ctxt'] == 0L:
                    self.stats['proc_ctxt'] = long(elm[1])
                elif elm[0] == 'intr' and self.stats['proc_intr'] == 0L:
                    self.stats['proc_intr'] = long(elm[1])
                elif not elm[0].find('cpu') >= 0:
                    continue

                if elm[0] == 'cpu':
                    self.add_all_cpu_jiffies(elm)
                    if self.interrupted_cpu_group[dev] == 'ALL':
                        self.add_cpu_jiffies(elm, dev)
                else:
                    n = elm[0].replace('cpu', '')
                    if n.isdigit() and self.interrupted_cpu_group[dev].count(n) > 0:
                        self.add_cpu_jiffies(elm, dev)
            f.close

    def io_stat(self):
        f = open('/proc/diskstats', 'r')
        for l in f:
            elm = l.split(None)
            if elm[2] in self.target_block_devices:
                if elm[2].find('cciss') >= 0:
                    k = 'cciss'
                else:
                    k = elm[2]
                v = int(elm[12]) # number of milliseconds spent doing I/Os
                dprint('  %s (%d)', k+'_io_util', v)
                self.stats[k+'_io_util'] = v
        f.close

    def sys_load(self):
        sys_load = 0.0

        for k, v in self.metric.iteritems():
            dprint('  %s (%f)', k, v)

            if k.find('_io_util') > 0:
                if v > sys_load:
                    sys_load = v
                continue

            if k.find('_idle') == -1:
                continue

            usage = 100.0 - v
            if usage < sys_load:
                continue

            if k == 'all_cpu_idle':
                sys_load = usage
            elif k == self.mp+'_idle' and (self.metric[self.mp+'_intr'] + self.metric[self.mp+'_sintr'] + self.metric[self.mp+'_system']) > self.interrupt_threshold:
                sys_load = usage

        return sys_load

    def calc_load(self, key):
        self.array[key].pop(0)
        self.array[key].append(self.metric['sys_load'])
        num = sum = 0
        for v in self.array[key]:
            num += 1
            sum += v
        self.metric[key] = sum/num

    def update_metric(self):
        # initialize
        self.metric = {}
        self.stats = {}
        self.stats['time'] = time.time()
        self.stats['all_cpu_total']  = 0L
        self.stats['proc_ctxt']  = 0L
        self.stats['proc_intr']  = 0L
        for dev in self.interrupted_cpu_group.iterkeys():
            self.stats[dev+'_total'] = 0L
        for k in ProcStatPos.keys():
            self.stats['all_cpu'+k] = 0L
            for dev in self.interrupted_cpu_group.iterkeys():
                self.stats[dev+k]   = 0L

        self.cpu_stat()
        self.io_stat()

        if 'time' in self.stats_prev:
            sintr = 0.0
            busy_dev = None
            for dev in self.interrupted_cpu_group.iterkeys():
                dev_diff = self.stats[dev+'_total']-self.stats_prev[dev+'_total']
                dprint('%s:%s: %d = %d - %d',
                       'DO DIFF',
                       dev,
                       dev_diff,
                       self.stats[dev+'_total'],
                       self.stats_prev[dev+'_total'])
                for name in self.stats.iterkeys():
                    if name.find(dev) >= 0:
                        d = self.stats[name] - self.stats_prev[name]
                        if d > 0:
                            self.metric[name] = float(d)/dev_diff*USER_HZ
                        else:
                            self.metric[name] = 0.0
                        if name == dev+'_sintr' and sintr <= self.metric[dev+'_sintr']:
                            sintr = self.metric[dev+'_sintr']
                            busy_dev = dev

            for k in ProcStatPos.keys():
                self.metric[self.mp+k] = self.metric[busy_dev+k]

            all_cpu_total_diff = self.stats['all_cpu_total'] - self.stats_prev['all_cpu_total']
            dprint(':%s: %d = %d - %d',
                   'DO ALL CPU DIFF',
                   all_cpu_total_diff,
                   self.stats['all_cpu_total'],
                   self.stats_prev['all_cpu_total'])
            t = self.stats['time'] - self.stats_prev['time']

            for name in self.stats.iterkeys():
                if name == 'time':
                    continue
                if not name in self.stats_prev:
                    continue

                d = self.stats[name] - self.stats_prev[name]
                if name.find('_io_util') > 0:
                    self.metric[name] = ( float(counter_wrap(d))/(t*USER_HZ) ) *10.0 # ticks in milliseconds
                elif d > 0:
                    if name.find('all_cpu') >= 0:
                        self.metric[name] = float(d)/all_cpu_total_diff*USER_HZ
                    elif name == 'proc_ctxt' or name == 'proc_intr':
                        self.metric[name] = float(counter_wrap(d))/t
                else:
                    self.metric[name] = 0.0

            self.metric['sys_load'] = self.sys_load()
            self.calc_load('sys_load_one')
            self.calc_load('sys_load_five')
            self.calc_load('sys_load_fifteen')

        self.stats_prev = self.stats.copy()

    def metric_of(self, name):
        val = 0
        _Lock.acquire()
        try:
            now = time.time()
            if self.metric_shelter['time'] < (now - 1):
                self.metric_shelter = self.metric.copy()
                self.metric_shelter['time'] = now

            if name in self.metric_shelter:
                val = self.metric_shelter[name]
        except:
            pass
        _Lock.release()
        return val

def metric_init(params):
    global descriptors, Desc_Skel, _Worker_Thread, Debug

    print '[cpustats] cpu stats'

    print params

    Desc_Skel = {
        'name'        : 'XXX',
        'call_back'   : metric_of,
        'time_max'    : 60,
        'value_type'  : 'float',
        'format'      : '%.3f',
        'units'       : '%',
        'slope'       : 'both',
        'description' : 'XXX',
        'groups'      : 'cpu',
        }

    if "debug" in params:
        Debug = params["debug"]
    dprint("%s", "Debug mode on")

    if 'target_devices' in params:
        params['target_devices'] = parse_list(params['target_devices'])
    elif 'target_device' in params:
        params['target_devices'] = parse_list(params['target_device'])
    else:
        params['target_devices'] = ['eth0', 'eth1', 'eth2', 'eth3', 'virtio0-input']
    dprint('target_devices: %s', params['target_devices'])

    if 'target_block_devices' in params:
        params['target_block_devices'] = parse_list(params['target_block_devices'])
    elif 'target_block_device' in params:
        params['target_block_devices'] = parse_list(params['target_block_device'])
    else:
        params['target_block_devices'] = find_block_devices()
    dprint('target_block_devices: %s', params['target_block_devices'])

    if 'interrupt_threshold' not in params:
        params['interrupt_threshold'] = 40.0
    dprint("interrupt_threshold: %.3f", float(params['interrupt_threshold']))

    if "metric_prefix" not in params:
        params["metric_prefix"] = "si_cpu"

    _Worker_Thread = UpdateMetricThread(params)
    _Worker_Thread.start()

    # IP:HOSTNAME
    if "spoof_host" in params:
        Desc_Skel["spoof_host"] = params["spoof_host"]

    mp = params["metric_prefix"]

    descriptors.append(create_desc(Desc_Skel, {
                "name"       : mp+"_user",
                "description": "Software Interrupted CPU User",
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : mp+"_nice",
                "description": "Software Interrupted CPU Nice",
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : mp+"_system",
                "description": "Software Interrupted CPU System",
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : mp+"_idle",
                "description": "Software Interrupted CPU Idle",
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : mp+"_wio",
                "description": "Software Interrupted CPU wio",
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : mp+"_intr",
                "description": "Software Interrupted CPU intr",
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : mp+"_sintr",
                "description": "Software Interrupted CPU sintr",
                }))

    descriptors.append(create_desc(Desc_Skel, {
                "name"       : "proc_ctxt",
                "description": "Context Switch",
                'groups'     : 'process',
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : "proc_intr",
                "description": "Interrupts",
                'groups'     : 'process',
                }))

    for dev in params['target_block_devices']:
        if dev.find('fio') >= 0:
            name  = dev
            group = 'fusion'
        elif dev.find('cciss') >= 0:
            name = group = 'cciss'
        else:
            name  = dev
            group = 'disk'
        descriptors.append(create_desc(Desc_Skel, {
                    'name'       : name + '_io_util',
                    'description': name + 'IO Util',
                    'groups'     : group,
                    }))

    descriptors.append(create_desc(Desc_Skel, {
                "name"       : "sys_load",
                "description": "Sys Load",
                'groups'     : 'load',
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : "sys_load_one",
                "description": "Sys Load 1min",
                'groups'     : 'load',
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : "sys_load_five",
                "description": "Sys Load 5min",
                'groups'     : 'load',
                }))
    descriptors.append(create_desc(Desc_Skel, {
                "name"       : "sys_load_fifteen",
                "description": "Sys Load 15min",
                'groups'     : 'load',
                }))
    return descriptors

def create_desc(skel, prop):
    d = skel.copy()
    for k, v in prop.iteritems():
        d[k] = v
    return d

def metric_of(name):
    return _Worker_Thread.metric_of(name)

def metric_cleanup():
    _Worker_Thread.shutdown()

if __name__ == '__main__':
    try:
        params = { 'debug' : True }
        if len(sys.argv) > 1:
            params['target_block_device'] = sys.argv[1]
        if len(sys.argv) > 2:
            params['interrupt_threshold'] = float(sys.argv[2])
        metric_init(params)
        time.sleep(0.3)
        while True:
            for d in descriptors:
                v = d['call_back'](d['name'])
                print ('value for %s is '+d['format']) % (d['name'],  v)
            time.sleep(5)
    except KeyboardInterrupt:
        metric_cleanup();
        time.sleep(0.2)
        os._exit(1)
    except StandardError:
        print sys.exc_info()[0]
        os._exit(2)
