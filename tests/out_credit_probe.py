"""Compile the actual production credit helper with ASan/UBSan; no devices.

Only unsigned elapsed arithmetic and bounded saturating refill are specified.
The driver's actual timer, admission and WDF work-item behavior is exercised by
out_recovery_probe.py, not by this smaller arithmetic test.
"""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'NCM-Driver-for-Windows/host/out_pipe_policy.h'

BODY = r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <limits>
using namespace Apple1902;
static unsigned checks = 0;
#define CHECK(e) do { ++checks; if (!(e)) { \
    std::fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#e); std::abort(); } } while (0)
static constexpr unsigned long long S = 10000000ull;
static constexpr unsigned long long T = OutRecoveryRefill;
static constexpr unsigned long long C = OutRecoveryCreditCapacity;
static constexpr unsigned long long M = std::numeric_limits<unsigned long long>::max();
static void CheckPlan(const OutRecoveryPlan& p, OutRecoveryDecision d,
                      unsigned long long wait = 0) {
    CHECK(p.Decision == d); CHECK(p.Wait == wait);
}
int main() {
    static_assert(OutRecoveryCapacity == 3 && OutRecoveryRefill == 60*S && OutRecoveryCooldown == 10*S);
    OutRecoveryBudget b;
    ResetOutRecoveryBudget(b, 0);
    CHECK(b.Credit == C && b.SampleTime == 0 && !b.HasAttempt);
    CheckPlan(TryBeginOutRecovery(true,b,0), OutRecoveryDecision::Run);
    CHECK(b.Credit == 2*T && b.HasAttempt && b.LastAttempt == 0);
    CheckPlan(TryBeginOutRecovery(true,b,0), OutRecoveryDecision::Deferred,10*S);
    CheckPlan(TryBeginOutRecovery(true,b,10*S-1), OutRecoveryDecision::Deferred,1);
    CheckPlan(TryBeginOutRecovery(true,b,10*S), OutRecoveryDecision::Run);
    CheckPlan(TryBeginOutRecovery(true,b,20*S), OutRecoveryDecision::Run);
    CHECK(b.Credit == 20*S);
    CheckPlan(TryBeginOutRecovery(true,b,30*S), OutRecoveryDecision::Deferred,30*S);
    CHECK(b.Credit == 30*S);
    CheckPlan(TryBeginOutRecovery(true,b,60*S-1), OutRecoveryDecision::Deferred,1);
    CheckPlan(TryBeginOutRecovery(true,b,60*S), OutRecoveryDecision::Run);
    CHECK(b.Credit == 0);
    CheckPlan(TryBeginOutRecovery(true,b,70*S), OutRecoveryDecision::Deferred,50*S);
    CheckPlan(TryBeginOutRecovery(true,b,120*S), OutRecoveryDecision::Run);
    CHECK(b.Credit == 0);
    // NotRunning is terminal and must not reserve credit or mutate a clock.
    auto old = b;
    CheckPlan(TryBeginOutRecovery(false,b,180*S), OutRecoveryDecision::NotRunning);
    CHECK(b.Credit == old.Credit && b.SampleTime == old.SampleTime && b.LastAttempt == old.LastAttempt);
    // Cooldown wins over an earlier token, and vice versa; no zero relative timer.
    b = {T-1, 200*S, 200*S, true};
    CheckPlan(TryBeginOutRecovery(true,b,200*S), OutRecoveryDecision::Deferred,10*S);
    b = {0, 200*S, 190*S, true};
    CheckPlan(TryBeginOutRecovery(true,b,200*S), OutRecoveryDecision::Deferred,60*S);
    // Long-idle saturating refill must not overflow before clamping. The
    // naive min(cap,credit+elapsed) mutation fails precisely this case.
    b = {100, 0, 0, false};
    CheckPlan(TryBeginOutRecovery(true,b,M-50), OutRecoveryDecision::Run);
    CHECK(b.Credit == 2*T);
    // Timestamp zero is a real attempt; HasAttempt, not a zero sentinel.
    b = {T,0,0,true};
    CheckPlan(TryBeginOutRecovery(true,b,0), OutRecoveryDecision::Deferred,10*S);
    // Refill and cooldown both use unsigned modular elapsed across U64 wrap.
    const auto origin = M-5*S+1;
    ResetOutRecoveryBudget(b,origin);
    CheckPlan(TryBeginOutRecovery(true,b,origin), OutRecoveryDecision::Run);
    CheckPlan(TryBeginOutRecovery(true,b,origin+10*S-1), OutRecoveryDecision::Deferred,1);
    CheckPlan(TryBeginOutRecovery(true,b,origin+10*S), OutRecoveryDecision::Run);
    CHECK(b.Credit == T+10*S && b.LastAttempt == origin+10*S);
    b = {0,origin,origin-10*S,true};
    CheckPlan(TryBeginOutRecovery(true,b,origin+T-1), OutRecoveryDecision::Deferred,1);
    CheckPlan(TryBeginOutRecovery(true,b,origin+T), OutRecoveryDecision::Run);
    CHECK(b.Credit == 0);
    // Re-evaluation at the same timestamp never refills or spends while deferred.
    b = {0,0,0,true};
    for (unsigned i=0;i<1000;++i) {
        CheckPlan(TryBeginOutRecovery(true,b,0), OutRecoveryDecision::Deferred,T);
        CHECK(b.Credit == 0 && b.SampleTime == 0);
    }
    // A fault storm has bounded burst/rate. Only time, never success counters,
    // creates credit. Total attempts remain outside this helper altogether.
    ResetOutRecoveryBudget(b,0);
    unsigned attempts = 0;
    for (unsigned second=0;second<=3600;++second) {
        auto p = TryBeginOutRecovery(true,b,second*S);
        CHECK(b.Credit <= C);
        if (p.Decision == OutRecoveryDecision::Run) ++attempts;
        else CHECK(p.Decision == OutRecoveryDecision::Deferred && p.Wait > 0 && p.Wait <= T);
        CHECK(attempts <= OutRecoveryCapacity + second/60);
    }
    CHECK(attempts == 63);
    // Restarting a D0 session is an explicit fresh burst; queue lifecycle
    // must not call this helper (verified in production source-contract tests).
    ResetOutRecoveryBudget(b,M);
    CHECK(b.Credit == C && b.SampleTime == M && !b.HasAttempt && b.LastAttempt == 0);
    CheckPlan(TryBeginOutRecovery(true,b,M), OutRecoveryDecision::Run);
    std::printf("OUT continuous credit: %u checks, 0 failures\n",checks);
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='sideline-out-credit-') as tmp:
        cpp = Path(tmp)/'credit.cpp'
        cpp.write_text('#include <cstdlib>\n#include "' + str(POLICY) + '"\n' + BODY)
        binary = Path(tmp)/'credit'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined',
                        '-g','-O1',str(cpp),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True,timeout=15,
                       env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))


if __name__ == '__main__':
    main()
