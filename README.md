# sysload
sysload is a measure of the amount of computational work that a Linux system performs. Designed as a substitute for load average.

sysload evaluates the following three elements. The maximum value of each is 100.

- ALL CPU utilization
- disk I/O utilization
- CPU Utilization in which interrupt from NIC is occurring

Among these values, the highest value is calculated as sysload. Therefore, for machines with high CPU, disk I/O or NIC load, sysload will be high. If you are monitoring sysload, you can determine if it is likely to become saturated with either CPU, disk I/O or NIC.

# sysload ganglia module
[cpustats.py](/ganglia/cpustats.py) is reference implementation of sysload in python(as ganglia python module).

In Linux, processes are often executed by CPUs that are interrupted by NICs. Therefore, even if CPUs that are not  interrupted by NICs is in the idle state, the load tends to be biased towards CPUs that are interrupted by NICs.

Considering the behavior of Linux like this, cpustats.py prepared a parameter called 'interrupt_threshold'. As long as the load on the interrupted CPU does not exceed the interrupt_threshold, the load on the NIC is assumed to be low, and the load on the NIC is not taken into consideration when calculating sysload.

By default, interrupt_threshold is 40.

Usage
=============
cpustats.py is implemented as a python module of ganglia. Therefore, it can be used as module of ganglia.

Also, by executing as follows, you can check how the value of sysload changes.

```bash
 $ python cpustats.py
[cpustats] cpu stats
{'debug': True}
DEBUG: Debug mode on
DEBUG: target_devices: ['eth0', 'eth1', 'eth2', 'eth3', 'virtio0-input']
DEBUG: target_block_devices: ['sda', 'sdb']
DEBUG: interrupt_threshold: 40.000
DEBUG: cpu num: 16
DEBUG: interrupted cpu id: 4, 5, 8, 6, 14, 7, 11, 12, 3, 9, 10, 1
DEBUG: cpu num: 16
DEBUG: interrupted cpu id:
DEBUG: cpu num: 16
DEBUG: interrupted cpu id: 11, 5, 12, 3, 13, 14, 9, 15, 0, 6, 1, 7, 2, 4
DEBUG: cpu num: 16
DEBUG: interrupted cpu id:
DEBUG: cpu num: 16
DEBUG: interrupted cpu id:
DEBUG:   sda_io_util (26791396)
DEBUG:   sdb_io_util (0)
value for si_cpu_user is 0.000
value for si_cpu_nice is 0.000
value for si_cpu_system is 0.000
value for si_cpu_idle is 0.000
value for si_cpu_wio is 0.000
value for si_cpu_intr is 0.000
value for si_cpu_sintr is 0.000
value for proc_ctxt is 0.000
value for proc_intr is 0.000
value for sda_io_util is 0.000
value for sdb_io_util is 0.000
value for sys_load is 0.000
value for sys_load_one is 0.000
value for sys_load_five is 0.000
value for sys_load_fifteen is 0.000
```

For example, when executing the following command:
```bash
 $ stress --cpu `grep -c 'processor' /proc/cpuinfo`
```

sysload will be as follows:
```
value for si_cpu_user is 99.994
value for si_cpu_nice is 0.000
value for si_cpu_system is 0.006
value for si_cpu_idle is 0.000
value for si_cpu_wio is 0.000
value for si_cpu_intr is 0.000
value for si_cpu_sintr is 0.000
value for proc_ctxt is 130.461
value for proc_intr is 4041.354
value for sda_io_util is 0.000
value for sdb_io_util is 0.000
value for sys_load is 100.000
value for sys_load_one is 72.989
value for sys_load_five is 14.598
value for sys_load_fifteen is 4.866
```

When the IO load is increased as follows:
```
$ stress --hdd `grep -c 'processor' /proc/cpuinfo` --io `grep -c 'processor' /proc/cpuinfo`
```

sysload will be higher with io_util as follows():
```
value for si_cpu_user is 0.019
value for si_cpu_nice is 0.000
value for si_cpu_system is 95.850
value for si_cpu_idle is 0.490
value for si_cpu_wio is 3.022
value for si_cpu_intr is 0.000
value for si_cpu_sintr is 0.619
value for proc_ctxt is 583.045
value for proc_intr is 4863.880
value for sda_io_util is 99.973
value for sdb_io_util is 0.000
value for sys_load is 99.973
value for sys_load_one is 99.980
value for sys_load_five is 63.690
value for sys_load_fifteen is 21.230

```

Author 
=======

Takanori Sejima

Contributors 
=======

Junichi Tanaka, Yoshifumi Uetake, kgws

Copyright & License
==========
Copyright © Gree, Inc. All Rights Reserved.

cpustats.py is released under version 2 of the GNU General Public License (GPLv2). See [LICENSE](/LICENSE).