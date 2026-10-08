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

// Attempts are counted per D0 session, not per queue start, and spaced by a
// cooldown. Times are KeQueryInterruptTime units (100 ns).
constexpr unsigned MaxOutRecoveriesPerD0 = 3;
constexpr unsigned long long OutRecoveryCooldown = 10ull * 10000000ull;

enum class OutRecoveryDecision { Run, NotRunning, BudgetExhausted, Cooldown };

inline OutRecoveryDecision DecideOutRecovery(
    bool running,
    unsigned attempts,
    unsigned long long now,
    unsigned long long lastAttempt)
{
    if (!running) return OutRecoveryDecision::NotRunning;
    if (attempts >= MaxOutRecoveriesPerD0) return OutRecoveryDecision::BudgetExhausted;
    if (attempts > 0 && now - lastAttempt < OutRecoveryCooldown) return OutRecoveryDecision::Cooldown;
    return OutRecoveryDecision::Run;
}
}
