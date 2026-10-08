// Copyright (C) Microsoft Corporation. All rights reserved.

#pragma once

#include <new.h>
#include <usb.h>
#include <usbdlib.h>
#include <wdfusb.h>
#include "trace.h"
#include "ncm.h"
#include "buffers.h"
#include "callbacks.h"
#include "mac.h"

EXTERN_C_START

class UsbNcmHostDevice
{
public:

    PAGED
    static
    void
    StartReceive(
        _In_ WDFDEVICE usbNcmWdfDevice
    );

    PAGED
    static
    void
    StopReceive(
        _In_ WDFDEVICE usbNcmWdfDevice
    );

    PAGED
    static
    void
    StartTransmit(
        _In_ WDFDEVICE usbNcmWdfDevice
    );

    PAGED
    static
    void
    StopTransmit(
        _In_ WDFDEVICE usbNcmWdfDevice
    );

    _IRQL_requires_max_(DISPATCH_LEVEL)
    static
    NTSTATUS
    TransmitFrames(
        _In_ WDFDEVICE usbNcmWdfDevice,
        _In_ TX_BUFFER_REQUEST * bufferRequest
    );

    PAGED
    UsbNcmHostDevice(
        _In_ WDFDEVICE wdfDevice
    )
        : m_WdfDevice(wdfDevice)
    {
    }

    PAGED
    NTSTATUS
    InitializeDevice(
        void
    );

    PAGED
    NTSTATUS
    CreateAdapter(
        void
    );

    PAGED
    void
    DestroyAdapter(
        void
    );

    PAGED
    NTSTATUS
    EnterWorkingState(
        _In_ WDF_POWER_DEVICE_STATE previousState
    );

    PAGED
    NTSTATUS
    LeaveWorkingState(
        void
    );

    // Reads the default-off data-path switch and creates the OUT lifecycle
    // lock and, only when recovery is enabled, its work item.
    PAGED
    NTSTATUS
    InitializeDataPathControl(
        void
    );

private:

    _IRQL_requires_max_(DISPATCH_LEVEL)
    static
    VOID
    DataBulkInPipeReadCompletetionRoutine(
        _In_ WDFUSBPIPE pipe,
        _In_ WDFMEMORY memory,
        _In_ size_t numBytesTransfered,
        _In_ WDFCONTEXT context
    );

    static
    EVT_WDF_USB_READERS_FAILED
        DataBulkInPipeReadersFailed;

    _IRQL_requires_max_(DISPATCH_LEVEL)
    static
    VOID
    TransmitFramesCompetion(
        _In_ WDFREQUEST request,
        _In_ WDFIOTARGET target,
        _In_ PWDF_REQUEST_COMPLETION_PARAMS params,
        _In_ WDFCONTEXT context
    );

    _IRQL_requires_max_(DISPATCH_LEVEL)
    void
    RequestOutPipeRecovery(
        _In_ NTSTATUS status,
        _In_ USBD_STATUS usbdStatus
    );

    static
    EVT_WDF_WORKITEM
        OutPipeRecoveryWorkItem;

    PAGED
    void
    RecoverOutPipe(
        void
    );

    PAGED
    void
    BeginD0Session(
        void
    );

    _IRQL_requires_(PASSIVE_LEVEL)
    void
    CloseTxAdmissionLocked(
        void
    );

    _IRQL_requires_(PASSIVE_LEVEL)
    void
    OpenTxAdmissionLocked(
        void
    );

    PAGED
    NTSTATUS
    RequestClassSpecificControlTransfer(
        _In_ UINT8 request,
        _In_ WDF_USB_BMREQUEST_DIRECTION direction,
        _In_ WDF_USB_BMREQUEST_RECIPIENT recipient,
        _In_ UINT16 value,
        _In_opt_ PWDF_MEMORY_DESCRIPTOR memoryDescriptor,
        _Out_opt_ PULONG bytesTransferred = nullptr
    );

    PAGED
    NTSTATUS
    SetDeviceFriendlyName(
        void
    );

    PAGED
    NTSTATUS
    SelectConfiguration(
        void
    );

    PAGED
    NTSTATUS
    SelectSetting(
        void
    );

    PAGED
    NTSTATUS
    RetrieveDataBulkPipes(
        void
    );

private:

    static
    USBNCM_DEVICE_EVENT_CALLBACKS const
        s_NcmDeviceCallbacks;

    WDFDEVICE
        m_WdfDevice = nullptr;

    NETADAPTER
        m_NetAdapter = nullptr;

    WDFUSBDEVICE
        m_WdfUsbTargetDevice = nullptr;

    WDFUSBINTERFACE
        m_ControlInterface = nullptr;

    WDFUSBINTERFACE
        m_DataInterface = nullptr;

    WDFUSBPIPE
        m_DataBulkInPipe = nullptr;

    WDFUSBPIPE
        m_DataBulkOutPipe = nullptr;

    ULONG
        m_DataBulkOutPipeMaximumPacketSize = 0;

    BYTE
        m_MacAddress[ETH_LENGTH_OF_ADDRESS] = {};

    NTB_PARAMETERS
        m_NtbParamters = {};

    BOOLEAN
        m_Use32BitNtb = FALSE;

    UINT16
        m_MaxDatagramSize = 0;

    UINT32
        m_HostSelectedNtbInMaxSize = 0;

    USBNCM_ADAPTER_EVENT_CALLBACKS const *
        m_NcmAdapterCallbacks = nullptr;

    // Data-pipe failure diagnostics; read with a debugger. Nothing in the
    // driver acts on them. KMDF reports a request cancelled by its own send
    // timeout as STATUS_IO_TIMEOUT, so timeouts are counted separately from
    // STATUS_CANCELLED (stop or explicit cancel).
    LONG
        m_TxSendFailures = 0;

    LONG
        m_TxCompletionFailures = 0;

    LONG
        m_TxCancellations = 0;

    LONG
        m_TxTimeouts = 0;

    LONG
        m_RxReadersFailures = 0;

    // Default-off switch (Apple1902::DataPathOut* bits), fixed per device.
    ULONG
        m_DataPathDebug = 0;

    // Requests handed to WdfRequestSend and not yet completed. Incremented
    // before the send; WdfRequestSend may run the completion inline.
    LONG
        m_TxInflight = 0;

    // Instrumentation only (switch bit 0x1).
    LONG
        m_TxInflightPeak = 0;

    LONG
        m_TxSuccesses = 0;

    LONG64
        m_TxLastSuccessTime = 0;

    LONG
        m_TxFirstFailureLogged = 0;

    LONG
        m_TxAdmissionRejects = 0;

    // Admission gate for bulk-OUT sends. TransmitFrames holds a reference for
    // its whole send section, at up to DISPATCH_LEVEL. Only recovery mode
    // closes it, and only under m_TxLifecycleLock, which waits for every
    // active section to leave before the target is stopped or reset.
    EX_RUNDOWN_REF
        m_TxAdmission = {};

    // Guarded by m_TxLifecycleLock (PASSIVE_LEVEL only; never taken on the
    // send or completion path).
    WDFWAITLOCK
        m_TxLifecycleLock = nullptr;

    BOOLEAN
        m_TxAdmissionOpen = TRUE;

    BOOLEAN
        m_TxPipeRunning = FALSE;

    ULONG
        m_TxRecoveryAttempts = 0;

    ULONG64
        m_TxLastRecoveryTime = 0;

    // Recovery only (switch bit 0x2). Null otherwise.
    WDFWORKITEM
        m_TxRecoveryWorkItem = nullptr;

    // 1 from enqueue until the work item has finished deciding and acting.
    LONG
        m_TxRecoveryQueued = 0;

    LONG
        m_TxRecoveryTriggerStatus = 0;

    LONG
        m_TxRecoveryTriggerUsbdStatus = 0;

    LONG
        m_TxRecoveryCoalesced = 0;

    LONG
        m_TxRecoverySkipped = 0;

};

WDF_DECLARE_CONTEXT_TYPE_WITH_NAME(UsbNcmHostDevice, NcmGetHostDeviceFromHandle)

EXTERN_C_END
