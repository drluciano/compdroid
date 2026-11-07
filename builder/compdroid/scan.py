"""Native-mode readiness scan.

The game's AArch64 code runs directly on the phone. Almost every instruction
works unchanged under Android; the exceptions are the few that talk to the
Horizon kernel or read registers whose values differ between the Switch and
Linux. This scan finds them so the rewriter (M2) knows what it has to patch,
and reports layout issues such as 16 KB page alignment.

Results are *candidates*: data embedded in .text can match an encoding.
"""

from __future__ import annotations

from array import array
from collections import Counter
from dataclasses import dataclass, field

from .formats import Nso

# Exact 32-bit encodings with Rt masked out (mask 0xFFFFFFE0).
SYSREG_PATTERNS = {
    0xD53BD060: ("mrs TPIDRRO_EL0", "Switch thread pointer; Linux owns this register, must be rewritten"),
    0xD53BD040: ("mrs TPIDR_EL0", "user TLS; collides with Android's bionic TLS, must be rewritten"),
    0xD51BD040: ("msr TPIDR_EL0", "user TLS write; must be rewritten"),
    0xD53BE020: ("mrs CNTPCT_EL0", "physical counter; Switch ticks at 19.2 MHz, phones differ"),
    0xD53BE040: ("mrs CNTVCT_EL0", "virtual counter; rescale to 19.2 MHz"),
    0xD53BE000: ("mrs CNTFRQ_EL0", "counter frequency; game expects 19200000"),
}
SVC_MASK = 0xFFE0001F
SVC_BASE = 0xD4000001

# Common Horizon SVC numbers, for readable reports (public Switchbrew list, subset).
SVC_NAMES = {
    0x01: "SetHeapSize", 0x02: "SetMemoryPermission", 0x03: "SetMemoryAttribute",
    0x04: "MapMemory", 0x05: "UnmapMemory", 0x06: "QueryMemory", 0x07: "ExitProcess",
    0x08: "CreateThread", 0x09: "StartThread", 0x0A: "ExitThread", 0x0B: "SleepThread",
    0x0C: "GetThreadPriority", 0x0D: "SetThreadPriority", 0x0E: "GetThreadCoreMask",
    0x0F: "SetThreadCoreMask", 0x10: "GetCurrentProcessorNumber", 0x11: "SignalEvent",
    0x12: "ClearEvent", 0x13: "MapSharedMemory", 0x14: "UnmapSharedMemory",
    0x15: "CreateTransferMemory", 0x16: "CloseHandle", 0x17: "ResetSignal",
    0x18: "WaitSynchronization", 0x19: "CancelSynchronization", 0x1A: "ArbitrateLock",
    0x1B: "ArbitrateUnlock", 0x1C: "WaitProcessWideKeyAtomic", 0x1D: "SignalProcessWideKey",
    0x1E: "GetSystemTick", 0x1F: "ConnectToNamedPort", 0x21: "SendSyncRequest",
    0x22: "SendSyncRequestWithUserBuffer", 0x25: "GetThreadId", 0x26: "Break",
    0x27: "OutputDebugString", 0x29: "GetInfo", 0x2C: "MapPhysicalMemory",
    0x2D: "UnmapPhysicalMemory", 0x32: "SetThreadActivity", 0x33: "GetThreadContext3",
    0x34: "WaitForAddress", 0x35: "SignalToAddress", 0x36: "SynchronizePreemptionState",
    0x40: "CreateSession", 0x41: "AcceptSession", 0x43: "ReplyAndReceive",
    0x45: "CreateEvent", 0x4B: "CreateCodeMemory", 0x4C: "ControlCodeMemory",
    0x77: "MapProcessCodeMemory", 0x78: "UnmapProcessCodeMemory",
}

PAGE_4K = 0x1000
PAGE_16K = 0x4000


@dataclass
class ModuleScan:
    module: str
    text_size: int
    svc: Counter = field(default_factory=Counter)
    sysreg: Counter = field(default_factory=Counter)
    page16k_issues: list[str] = field(default_factory=list)

    @property
    def rewrite_sites(self) -> int:
        return sum(self.svc.values()) + sum(self.sysreg.values())


def scan_words(text: bytes) -> tuple[Counter, Counter]:
    words = array("I")
    words.frombytes(text[: len(text) // 4 * 4])
    if words.itemsize != 4:
        raise RuntimeError("unexpected array item size")
    import sys

    if sys.byteorder != "little":
        words.byteswap()

    svc: Counter = Counter()
    sysreg: Counter = Counter()
    patterns = SYSREG_PATTERNS
    for w in words:
        # Fast reject: both SVC and MRS/MSR live in the 0xD4xxxxxx-0xD5xxxxxx block.
        top = w >> 25
        if top != 0x6A:  # 0xD4000000 >> 25 == 0x6A, covers 0xD4.. and 0xD5..
            continue
        if (w & SVC_MASK) == SVC_BASE:
            svc[(w >> 5) & 0xFFFF] += 1
            continue
        key = w & 0xFFFFFFE0
        if key in patterns:
            sysreg[patterns[key][0]] += 1
    return svc, sysreg


def page16k_report(nso: Nso) -> list[str]:
    issues = []
    segs = [nso.segments[n] for n in ("text", "ro", "data")]
    for a, b in zip(segs, segs[1:]):
        if b.memory_offset % PAGE_16K:
            issues.append(
                f"{b.name} starts at +0x{b.memory_offset:X}, not 16 KB aligned: "
                f"{a.name}/{b.name} share a 16 KB page, so the loader must map them with merged permissions"
            )
    return issues


def scan_module(name: str, nso: Nso) -> ModuleScan:
    text = nso.segment_bytes("text")
    svc, sysreg = scan_words(text)
    return ModuleScan(
        module=name, text_size=len(text), svc=svc, sysreg=sysreg, page16k_issues=page16k_report(nso)
    )
