# Copyright (c) 2021 The Regents of the University of California
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""

This script shows an example of running a CXL-DMSim simulation
using the gem5 library and defaults to simulating CXL ASIC Device.
This simulation boots Ubuntu 18.04 using 1 Atomic CPU
cores. The simulation then switches to 1 TIMING CPU core to run the lmbench_cxl.sh.

Usage
-----

```
scons build/X86/gem5.opt -j16
build/X86/gem5.opt configs/example/gem5_library/x86-cxl-run.py
```
"""
import argparse
import math
import m5

from pathlib import Path

from gem5.utils.requires import requires
from gem5.components.boards.x86_board import X86Board

from gem5.components.memory.single_channel import DIMM_DDR5_4400, SingleChannelDDR4_3200
from gem5.components.processors.simple_switchable_processor import (
    SimpleSwitchableProcessor,
)
from gem5.components.processors.cpu_types import CPUTypes
from gem5.isas import ISA
from gem5.simulate.simulator import Simulator
from gem5.simulate.exit_event import ExitEvent
from gem5.resources.resource import DiskImageResource, KernelResource

# This runs a check to ensure the gem5 binary is compiled to X86 and to the
# MESI Three Level coherence protocol.
requires(
    isa_required=ISA.X86,
)
from gem5.components.cachehierarchies.classic.private_l1_private_l2_shared_l3_cache_hierarchy import (
    PrivateL1PrivateL2SharedL3CacheHierarchy,
)

parser = argparse.ArgumentParser(description='CXL system parameters.')
parser.add_argument('--is_asic', action='store', type=str, nargs='?', choices=['True', 'False'], default='True', help='Choose to simulate CXL ASIC Device or FPGA Device.')
parser.add_argument('--test_cmd', type=str, choices=['lmbench_cxl.sh', 
                                                     'lmbench_dram.sh', 
                                                     'merci_dram.sh', 
                                                     'merci_cxl.sh', 
                                                     'merci_dram+cxl.sh',
                                                     'stream_dram.sh',
                                                     'stream_cxl.sh'
                                                     ], default='lmbench_cxl.sh', help='Choose a test to run.')
parser.add_argument('--num_cpus', type=int, default=1, help='Number of CPUs')
parser.add_argument('--cpu_type', type=str, choices=['TIMING', 'O3'], default='TIMING', help='CPU type')
parser.add_argument('--cxl_mem_type', type=str, choices=['Simple', 'DRAM'], default='DRAM', help='CXL memory type')
parser.add_argument('--save_chckpt', type=str, default=None, help="Path to where desired checkpoint directory is locationed")


args = parser.parse_args()

checkpoint_path = Path(args.save_chckpt).resolve()


# Here we setup a MESI Three Level Cache Hierarchy.
cache_hierarchy = PrivateL1PrivateL2SharedL3CacheHierarchy(
    l1d_size="48kB",
    l1d_assoc=6,
    l1i_size="32kB",
    l1i_assoc=8,
    l2_size="2MB",
    l2_assoc=16,
    l3_size="96MB",
    l3_assoc=48,
)

# Setup the system memory.
memory = DIMM_DDR5_4400(size="3GB")
if args.is_asic:
    cxl_memory = DIMM_DDR5_4400(size="8GB")
else:
    cxl_memory = SingleChannelDDR4_3200(size="8GB")
# Here we setup the processor. This is a special switchable processor in which
# a starting core type and a switch core type must be specified. Once a
# configuration is instantiated a user may call `processor.switch()` to switch
# from the starting core types to the switch core types. In this simulation
# we start with ATOMIC cores to simulate the OS boot, then switch to the O3
# cores for the command we wish to run after boot.

processor = SimpleSwitchableProcessor(
    starting_core_type=CPUTypes.ATOMIC,
    switch_core_type = CPUTypes.O3 if args.cpu_type == 'O3' else CPUTypes.TIMING,
    isa=ISA.X86,
    num_cores=args.num_cpus,
)

# Here we setup the board and CXL device memory size. The X86Board allows for Full-System X86 simulations.
board = X86Board(
    clk_freq="2.4GHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy,
    cxl_memory=cxl_memory,
    is_asic=(args.is_asic == 'True')    
)

# Here we set the Full System workload.
# The `set_kernel_disk_workload` function for the X86Board takes a kernel, a
# disk image, and, optionally, a command to run.

# This is the command to run after the system has booted. The first `m5 exit`
# will stop the simulation so we can switch the CPU cores from ATOMIC to O3
# and continue the simulation to run the command. After simulation
# has ended you may inspect `m5out/board.pc.com_1.device` to see the echo
# output.
command = (
    "m5 exit;"
    + "numactl -H;"
    + "m5 resetstats;"
    + "/home/cxl_benchmark/" + args.test_cmd + ";"
)

# Please modify the paths of kernel and disk_image according to the location of your files.
board.set_kernel_disk_workload(
    kernel=KernelResource(local_path='/mnt/ssd/CXL-DMSim-Zoo/fs_images/vmlinux_20240920'),
    disk_image=DiskImageResource(local_path='/mnt/ssd/CXL-DMSim-Zoo/fs_images/parsec.img'),
    readfile_contents=command,
    checkpoint = checkpoint_path,

)

def smarts_generator(
    k: int, U: int, W: int, processor
):
    """
    :param k: the systematic sampling interval. Each interval simulation k*U
    instructions. The interval includes the fast-forwarding part, detailed
    warmup part, and the detail simulation part.
    :param U: sampling unit size. The instruction length in each unit.
    :param W: the length of the detailed warmup part.

    Each interval instruction length is k*U.
    The warmup part starts at (k-1)*U-W
    The detailed simulation part starts at (k-1)*U

    This exit generator only works with SwitchableProcessor.
    When it reaches to the start of the detailed warmup part, it resets the
    stats; then it switches the core type and schedule for the end of the
    warmup part and the end of the interval. When it reaches to the end of the
    detailed warmup part, it resets the stats. When it reaches to the end of
    the detailed simulation, it dumps the stats; then it switches the core type
    and schedule for the start of the next detailed warmup part.
    """
    is_switchable = isinstance(processor, SimpleSwitchableProcessor)
    warmup_start = U * (k - 1) - W
    warmup_plus_detailed = U + W
    counter = 0

    while is_switchable:
        print(f"curTick is {m5.curTick()}")
        print("got to warmup start\n")

        print("switch core type")
        # switch core type
        processor.switch()
        print(
            "now schedule for end of warmup and start of detailed simluation\n"
        )
        # schedule for warmup end
        # schedule for detailed simulation end
        processor.get_cores()[0]._set_simpoint([W, warmup_plus_detailed], True)
        print("fall back to simulation\n")
        # fall back to simualtion
        yield False

        # reached warmup end
        print(f"curTick is {m5.curTick()}")
        print("got to detail simulation start\n")
        print("now reset m5 stats\n")

        # reset stats
        m5.stats.reset()
        print("fall back to simulation\n")
        # fall back to simulation
        yield False

        # reached end of detailed simulation
        print(f"curTick is {m5.curTick()}")
        print("got to end of detail simulation\n")
        print("now dump stats\n")
        # dump stats
        m5.stats.dump()

        # switch core type
        print("switch core type\n")
        processor.switch()
        print(
            "now schedule for next warmup start and detail simulation start\n"
        )
        # schedule for the next start of warmup
        print("schedule for the next start of warmup\n")
        processor.get_cores()[0]._set_simpoint([warmup_start], True)
        print("increase n counter\n")
        # increment sample counter
        counter += 1
        print("switch core type to functional core type")
        print("fall back to simulation\n")
        yield False

program_length = 14721791534
N = 10000
ideal_region_length = math.ceil(program_length/N)
ideal_U = 1000
ideal_k = math.ceil(ideal_region_length/ideal_U)
ideal_W = 2 * ideal_U

simulator = Simulator(
    board=board,
    on_exit_event={
        ExitEvent.SIMPOINT_BEGIN: smarts_generator(
            k=ideal_k,
            U=ideal_U,
            W=ideal_W,
            processor=processor,
        )
    }
)

m5.stats.reset()
processor.get_cores()[0]._set_simpoint([1], False)
simulator.run()

print("Simulation Complete")