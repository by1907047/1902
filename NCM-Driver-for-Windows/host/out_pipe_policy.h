#pragma once
// Portable policy for the experimental, default-off bulk-OUT diagnostics and
// pipe-only recovery. No WDK types, so tests/out_recovery_probe.py can run it
// on any host; device.cpp checks each constant against the WDK definitions.

// Device hardware key ("Device Parameters") value name. Missing means 0.
#define SIDELINE1902_DATA_PATH_DEBUG_VALUE L"Sideline1902DataPathDebug"

namespace Apple1902 {

constexpr unsigned long DataPathOutInstrumentation = 0x1;
constexpr unsigned long DataPathOutPipeRecovery = 0x2;
constexpr unsigned long DataPathKnownBits = DataPathOutInstrumentation | DataPathOutPipeRecovery;

// Missing value, a failed read and any unknown bit all select 0 (off).
inline unsigned long DataPathDebugFromRegistry(bool found, unsigned long value)
{
    return found && (value & ~DataPathKnownBits) == 0 ? value : 0;
}

namespace Status {
constexpr unsigned Cancelled = 0xC0000120u;           // STATUS_CANCELLED
constexpr unsigned IoTimeout = 0xC00000B5u;           // STATUS_IO_TIMEOUT
constexpr unsigned NoSuchDevice = 0xC000000Eu;        // STATUS_NO_SUCH_DEVICE
constexpr unsigned DeviceNotConnected = 0xC000009Du;  // STATUS_DEVICE_NOT_CONNECTED
constexpr unsigned DeviceRemoved = 0xC00002B6u;       // STATUS_DEVICE_REMOVED
constexpr unsigned DeletePending = 0xC0000056u;       // STATUS_DELETE_PENDING
constexpr unsigned DeviceDoesNotExist = 0xC00000C0u;  // STATUS_DEVICE_DOES_NOT_EXIST
constexpr unsigned DevicePoweredOff = 0x8000000Fu;    // STATUS_DEVICE_POWERED_OFF
constexpr unsigned UsbdXactError = 0xC0000011u;       // USBD_STATUS_XACT_ERROR
constexpr unsigned UsbdDeviceGone = 0xC0007000u;      // USBD_STATUS_DEVICE_GONE
}

enum class TxCompletion
{
    Success,
    Cancelled,         // STATUS_CANCELLED: a stop or an explicit cancel
    TimedOut,          // KMDF reports its own send timeout as STATUS_IO_TIMEOUT
    DeviceGone,        // removal, disconnect or power-off; never recovered
    PipeError,         // the one class recovery acts on
    OtherFailure,
};

// Only the transaction error seen on hardware is recovered. Stall, babble and
// every other USBD status stay OtherFailure until there is evidence for them.
inline TxCompletion ClassifyTxCompletion(unsigned status, unsigned usbdStatus)
{
    if ((status & 0x80000000u) == 0) return TxCompletion::Success;
    if (status == Status::Cancelled) return TxCompletion::Cancelled;
    if (status == Status::IoTimeout) return TxCompletion::TimedOut;
    switch (status)
    {
    case Status::NoSuchDevice:
    case Status::DeviceNotConnected:
    case Status::DeviceRemoved:
    case Status::DeletePending:
    case Status::DeviceDoesNotExist:
    case Status::DevicePoweredOff:
        return TxCompletion::DeviceGone;
    }
    if (usbdStatus == Status::UsbdDeviceGone) return TxCompletion::DeviceGone;
    if (usbdStatus == Status::UsbdXactError) return TxCompletion::PipeError;
    return TxCompletion::OtherFailure;
}

// Continuous-credit bucket, not an irreversible lifetime D0 limit. All
// mutations are made under DataPathLock. Times/credit use interrupt-time
// units (100 ns): one token costs 60 s and elapsed time refills continuously.
constexpr unsigned OutRecoveryCapacity = 3;
constexpr unsigned long long OutRecoveryRefill = 60ull * 10000000ull;
constexpr unsigned long long OutRecoveryCreditCapacity = OutRecoveryCapacity * OutRecoveryRefill;
constexpr unsigned long long OutRecoveryCooldown = 10ull * 10000000ull;

struct OutRecoveryBudget
{
    unsigned long long Credit = OutRecoveryCreditCapacity;
    unsigned long long SampleTime = 0;
    unsigned long long LastAttempt = 0;
    bool HasAttempt = false;
};

inline void ResetOutRecoveryBudget(OutRecoveryBudget& budget, unsigned long long now)
{
    budget = { OutRecoveryCreditCapacity, now, 0, false };
}

enum class OutRecoveryDecision { Run, NotRunning, Deferred };

struct OutRecoveryPlan
{
    OutRecoveryDecision Decision;
    unsigned long long Wait;
};

// Run reserves exactly one token and records its start; Deferred reserves
// none and supplies a positive bounded relative wait for the existing timer.
// Unsigned subtraction tolerates one timestamp wrap. Add only available
// space, not an unbounded elapsed value which could overflow before clamping.
inline OutRecoveryPlan TryBeginOutRecovery(
    bool running,
    OutRecoveryBudget& budget,
    unsigned long long now)
{
    if (!running) return { OutRecoveryDecision::NotRunning, 0 };
    const unsigned long long elapsed = now - budget.SampleTime;
    const unsigned long long space = OutRecoveryCreditCapacity - budget.Credit;
    budget.Credit += elapsed < space ? elapsed : space;
    budget.SampleTime = now;

    const unsigned long long sinceAttempt = now - budget.LastAttempt;
    const unsigned long long cooldown = budget.HasAttempt && sinceAttempt < OutRecoveryCooldown
        ? OutRecoveryCooldown - sinceAttempt : 0;
    const unsigned long long creditWait = budget.Credit < OutRecoveryRefill
        ? OutRecoveryRefill - budget.Credit : 0;
    const unsigned long long wait = cooldown > creditWait ? cooldown : creditWait;
    if (wait != 0) return { OutRecoveryDecision::Deferred, wait };

    budget.Credit -= OutRecoveryRefill;
    budget.LastAttempt = now;
    budget.HasAttempt = true;
    return { OutRecoveryDecision::Run, 0 };
}
}
